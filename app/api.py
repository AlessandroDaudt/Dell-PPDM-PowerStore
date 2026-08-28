import json
import secrets
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.crypto import decrypt_secret, encrypt_secret
from app.database import get_db
from app.models import WWN, AuditEvent, Equipment, Workflow
from app.schemas import (
    EquipmentCreate,
    EquipmentRead,
    EquipmentUpdate,
    ProvisionRequest,
    WorkflowRead,
    WorkflowStepRead,
    WWNRead,
)
from app.services.orchestrator import create_workflow, equipment_settings, run_workflow
from app.services.powerstore import PowerStoreClient
from app.services.ppdm import PPDMClient

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]


def require_auth(request: Request) -> str:
    username = request.session.get("username")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return str(username)


AuthUser = Annotated[str, Depends(require_auth)]


def equipment_read(equipment: Equipment) -> EquipmentRead:
    return EquipmentRead(
        id=equipment.id,
        name=equipment.name,
        type=equipment.type,
        management_address=equipment.management_address,
        api_port=equipment.api_port,
        username=equipment.username,
        verify_ssl=equipment.verify_ssl,
        settings=equipment_settings(equipment),
        wwns=[WWNRead.model_validate(item) for item in equipment.wwns],
        created_at=equipment.created_at,
        updated_at=equipment.updated_at,
    )


def workflow_read(workflow: Workflow) -> WorkflowRead:
    return WorkflowRead(
        id=workflow.id,
        status=workflow.status,
        dry_run=workflow.dry_run,
        request=json.loads(workflow.request_json),
        current_step=workflow.current_step,
        volume_id=workflow.volume_id,
        volume_wwn=workflow.volume_wwn,
        policy_id=workflow.policy_id,
        error=workflow.error,
        created_at=workflow.created_at,
        started_at=workflow.started_at,
        finished_at=workflow.finished_at,
        steps=[
            WorkflowStepRead(
                id=step.id,
                step_order=step.step_order,
                name=step.name,
                status=step.status,
                message=step.message,
                details=json.loads(step.details_json or "{}"),
                started_at=step.started_at,
                finished_at=step.finished_at,
            )
            for step in workflow.steps
        ],
    )


@router.post("/auth/login")
def login(request: Request, payload: dict[str, str]):
    settings = get_settings()
    username_ok = secrets.compare_digest(payload.get("username", ""), settings.admin_username)
    password_ok = secrets.compare_digest(payload.get("password", ""), settings.admin_password)
    if not (username_ok and password_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.session.clear()
    request.session["username"] = settings.admin_username
    return {"authenticated": True, "username": settings.admin_username}


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"authenticated": False}


@router.get("/auth/status")
def auth_status(request: Request):
    username = request.session.get("username")
    return {"authenticated": bool(username), "username": username}


@router.get("/dashboard")
def dashboard(_: AuthUser, db: DbSession):
    equipment_counts = dict(
        db.execute(select(Equipment.type, func.count()).group_by(Equipment.type)).all()
    )
    workflow_counts = dict(
        db.execute(select(Workflow.status, func.count()).group_by(Workflow.status)).all()
    )
    recent = db.scalars(
        select(Workflow).options(selectinload(Workflow.steps)).order_by(desc(Workflow.id)).limit(5)
    ).all()
    return {
        "equipment": equipment_counts,
        "workflows": workflow_counts,
        "recent_workflows": [workflow_read(item).model_dump(mode="json") for item in recent],
        "default_dry_run": get_settings().default_dry_run,
    }


@router.get("/equipment", response_model=list[EquipmentRead])
def list_equipment(_: AuthUser, db: DbSession, type: str | None = Query(default=None)):
    statement = (
        select(Equipment)
        .options(selectinload(Equipment.wwns))
        .order_by(Equipment.type, Equipment.name)
    )
    if type:
        statement = statement.where(Equipment.type == type.upper())
    return [equipment_read(item) for item in db.scalars(statement).unique().all()]


@router.post("/equipment", response_model=EquipmentRead, status_code=201)
def add_equipment(payload: EquipmentCreate, user: AuthUser, db: DbSession):
    equipment = Equipment(
        name=payload.name.strip(),
        type=payload.type,
        management_address=(payload.management_address or "").strip() or None,
        api_port=payload.api_port,
        username=(payload.username or "").strip() or None,
        encrypted_password=encrypt_secret(payload.password),
        verify_ssl=payload.verify_ssl,
        settings_json=json.dumps(payload.settings, ensure_ascii=False),
    )
    equipment.wwns = [WWN(**item.model_dump()) for item in payload.wwns]
    db.add(equipment)
    db.add(
        AuditEvent(
            actor=user,
            action="equipment.create",
            resource_type="equipment",
            resource_id=payload.name,
            outcome="SUCCESS",
            details_json=json.dumps({"type": payload.type}),
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Name or WWN is already registered") from exc
    db.refresh(equipment)
    return equipment_read(equipment)


@router.put("/equipment/{equipment_id}", response_model=EquipmentRead)
def update_equipment(
    equipment_id: int, payload: EquipmentUpdate, user: AuthUser, db: DbSession
):
    equipment = db.scalar(
        select(Equipment)
        .where(Equipment.id == equipment_id)
        .options(selectinload(Equipment.wwns))
    )
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")
    equipment.name = payload.name.strip()
    equipment.type = payload.type
    equipment.management_address = (payload.management_address or "").strip() or None
    equipment.api_port = payload.api_port
    equipment.username = (payload.username or "").strip() or None
    if payload.password:
        equipment.encrypted_password = encrypt_secret(payload.password)
    equipment.verify_ssl = payload.verify_ssl
    equipment.settings_json = json.dumps(payload.settings, ensure_ascii=False)
    for existing_wwn in list(equipment.wwns):
        db.delete(existing_wwn)
    db.flush()
    equipment.wwns = [WWN(**item.model_dump()) for item in payload.wwns]
    db.add(
        AuditEvent(
            actor=user,
            action="equipment.update",
            resource_type="equipment",
            resource_id=str(equipment_id),
            outcome="SUCCESS",
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Name or WWN is already registered") from exc
    db.refresh(equipment)
    return equipment_read(equipment)


@router.delete("/equipment/{equipment_id}", status_code=204)
def delete_equipment(equipment_id: int, user: AuthUser, db: DbSession):
    equipment = db.get(Equipment, equipment_id)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")
    db.delete(equipment)
    db.add(
        AuditEvent(
            actor=user,
            action="equipment.delete",
            resource_type="equipment",
            resource_id=str(equipment_id),
            outcome="SUCCESS",
        )
    )
    db.commit()


def _get_equipment(db: Session, equipment_id: int) -> Equipment:
    equipment = db.scalar(
        select(Equipment)
        .where(Equipment.id == equipment_id)
        .options(selectinload(Equipment.wwns))
    )
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return equipment


@router.post("/equipment/{equipment_id}/test")
def test_equipment(equipment_id: int, _: AuthUser, db: DbSession):
    equipment = _get_equipment(db, equipment_id)
    password = decrypt_secret(equipment.encrypted_password)
    if equipment.type == "POWERSTORE":
        with PowerStoreClient(
            equipment.management_address or "",
            equipment.username or "",
            password,
            equipment.api_port,
            equipment.verify_ssl,
        ) as client:
            return client.test_connection()
    if equipment.type == "PPDM":
        with PPDMClient(
            equipment.management_address or "",
            equipment.username or "",
            password,
            equipment.api_port,
            equipment.verify_ssl,
        ) as client:
            return client.test_connection()
    if equipment.type == "BROCADE":
        return {
            "ok": True,
            "system": "Brocade",
            "message": "Authentication and zoning are validated by the playbook in dry-run/live mode",
        }
    return {"ok": True, "system": "Host", "wwns": len(equipment.wwns)}


@router.get("/integrations/powerstore/{equipment_id}/options")
def powerstore_options(equipment_id: int, _: AuthUser, db: DbSession):
    equipment = _get_equipment(db, equipment_id)
    if equipment.type != "POWERSTORE":
        raise HTTPException(status_code=400, detail="Equipment is not a PowerStore")
    with PowerStoreClient(
        equipment.management_address or "",
        equipment.username or "",
        decrypt_secret(equipment.encrypted_password),
        equipment.api_port,
        equipment.verify_ssl,
    ) as client:
        return client.get_options()


@router.get("/integrations/ppdm/{equipment_id}/options")
def ppdm_options(equipment_id: int, _: AuthUser, db: DbSession):
    equipment = _get_equipment(db, equipment_id)
    if equipment.type != "PPDM":
        raise HTTPException(status_code=400, detail="Equipment is not a PPDM")
    with PPDMClient(
        equipment.management_address or "",
        equipment.username or "",
        decrypt_secret(equipment.encrypted_password),
        equipment.api_port,
        equipment.verify_ssl,
    ) as client:
        return client.get_options()


@router.post("/workflows", response_model=WorkflowRead, status_code=202)
def start_workflow(
    payload: ProvisionRequest, background_tasks: BackgroundTasks, _: AuthUser, db: DbSession
):
    workflow = create_workflow(db, payload.model_dump(mode="json"), payload.dry_run)
    background_tasks.add_task(run_workflow, workflow.id)
    return workflow_read(workflow)


@router.get("/workflows", response_model=list[WorkflowRead])
def list_workflows(
    _: AuthUser,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
):
    statement = (
        select(Workflow).options(selectinload(Workflow.steps)).order_by(desc(Workflow.id)).limit(limit)
    )
    if status_filter:
        statement = statement.where(Workflow.status == status_filter.upper())
    return [workflow_read(item) for item in db.scalars(statement).unique().all()]


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
def get_workflow(workflow_id: int, _: AuthUser, db: DbSession):
    workflow = db.scalar(
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(selectinload(Workflow.steps))
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow_read(workflow)


@router.get("/audit")
def list_audit(_: AuthUser, db: DbSession, limit: int = Query(default=100, ge=1, le=500)):
    events = db.scalars(select(AuditEvent).order_by(desc(AuditEvent.id)).limit(limit)).all()
    return [
        {
            "id": event.id,
            "actor": event.actor,
            "action": event.action,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "outcome": event.outcome,
            "details": json.loads(event.details_json or "{}"),
            "created_at": event.created_at,
        }
        for event in events
    ]
