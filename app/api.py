import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.crypto import decrypt_secret, encrypt_secret
from app.database import get_db
from app.models import WWN, AuditEvent, Equipment, StatusSample, Workflow
from app.schemas import (
    EquipmentCreate,
    EquipmentRead,
    EquipmentUpdate,
    ProvisionRequest,
    WorkflowRead,
    WorkflowStepRead,
    WWNRead,
)
from app.services.cisco_mds import CiscoMDSClient
from app.services.datadomain import DataDomainClient
from app.services.orchestrator import create_workflow, equipment_settings, run_workflow
from app.services.powermax import PowerMaxClient
from app.services.powerscale import PowerScaleClient
from app.services.powerstore import PowerStoreClient
from app.services.powerstore_nas import PowerStoreNASClient
from app.services.ppdm import PPDMClient
from app.services.status_monitor import status_monitor
from app.services.unity import UnityClient

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


def _status_read(sample: StatusSample) -> dict:
    try:
        metrics = json.loads(sample.metrics_json or "{}")
    except json.JSONDecodeError:
        metrics = {}
    return {
        "id": sample.id,
        "equipment_id": sample.equipment_id,
        "component_key": sample.component_key,
        "component_name": sample.component_name,
        "component_type": sample.component_type,
        "state": sample.state,
        "sampled_at": sample.sampled_at,
        "metrics": metrics,
        "error": sample.error,
    }


@router.get("/status")
def current_status(_: AuthUser, db: DbSession):
    """Return the newest persisted sample for every equipment component."""
    rows = db.execute(
        select(StatusSample)
        .join(Equipment, Equipment.id == StatusSample.equipment_id)
        .where(Equipment.type != "HOST")
        .order_by(desc(StatusSample.sampled_at), desc(StatusSample.id))
    ).scalars()
    latest: dict[tuple[int, str], StatusSample] = {}
    for sample in rows:
        latest.setdefault((sample.equipment_id, sample.component_key), sample)
    return {
        "sample_interval_seconds": get_settings().status_sample_interval_seconds,
        "retention_days": get_settings().status_retention_days,
        "systems": [_status_read(sample) for sample in latest.values()],
    }


@router.get("/status/history")
def status_history(
    _: AuthUser,
    db: DbSession,
    equipment_id: int | None = Query(default=None, ge=1),
    component_key: str | None = Query(default=None, max_length=255),
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=5000, ge=1, le=10000),
):
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    statement = select(StatusSample).where(StatusSample.sampled_at >= cutoff)
    if equipment_id is not None:
        statement = statement.where(StatusSample.equipment_id == equipment_id)
    if component_key:
        statement = statement.where(StatusSample.component_key == component_key)
    samples = db.scalars(statement.order_by(StatusSample.sampled_at).limit(limit)).all()
    return {
        "hours": hours,
        "retention_days": get_settings().status_retention_days,
        "samples": [_status_read(sample) for sample in samples],
    }


@router.post("/status/collect")
def collect_status(_: AuthUser):
    return status_monitor.collector.collect_now()


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
def update_equipment(equipment_id: int, payload: EquipmentUpdate, user: AuthUser, db: DbSession):
    equipment = db.scalar(
        select(Equipment).where(Equipment.id == equipment_id).options(selectinload(Equipment.wwns))
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
        select(Equipment).where(Equipment.id == equipment_id).options(selectinload(Equipment.wwns))
    )
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return equipment


@router.post("/equipment/{equipment_id}/test")
def test_equipment(equipment_id: int, _: AuthUser, db: DbSession):
    equipment = _get_equipment(db, equipment_id)
    password = decrypt_secret(equipment.encrypted_password)
    if equipment.type in {"POWERSTORE", "POWERSTORE_NAS"}:
        client_type = (
            PowerStoreNASClient if equipment.type == "POWERSTORE_NAS" else PowerStoreClient
        )
        with client_type(
            equipment.management_address or "",
            equipment.username or "",
            password,
            equipment.api_port,
            equipment.verify_ssl,
        ) as client:
            return client.test_connection()
    if equipment.type == "POWERSCALE":
        settings = equipment_settings(equipment)
        with PowerScaleClient(
            equipment.management_address or "",
            equipment.username or "",
            password,
            equipment.api_port,
            equipment.verify_ssl,
            settings.get("api_version", "3"),
        ) as client:
            return client.test_connection()
    if equipment.type == "UNITY":
        settings = equipment_settings(equipment)
        with UnityClient(
            equipment.management_address or "",
            equipment.username or "",
            password,
            equipment.api_port,
            equipment.verify_ssl,
            settings.get("api_version", "5.2"),
        ) as client:
            return client.test_connection()
    if equipment.type == "POWERMAX":
        settings = equipment_settings(equipment)
        with PowerMaxClient(
            equipment.management_address or "",
            equipment.username or "",
            password,
            equipment.api_port,
            equipment.verify_ssl,
            settings.get("api_version", "100"),
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
    if equipment.type == "DATA_DOMAIN":
        with DataDomainClient(
            equipment.management_address or "",
            equipment.username or "",
            password,
            equipment.api_port,
            equipment.verify_ssl,
        ) as client:
            return client.test_connection()
    if equipment.type == "CISCO_MDS":
        settings = equipment_settings(equipment)
        with CiscoMDSClient(
            equipment.management_address or "",
            equipment.username or "",
            password,
            equipment.api_port,
            equipment.verify_ssl,
            settings.get("api_version", "1.2"),
        ) as client:
            return client.test_connection()
    if equipment.type == "BROCADE":
        return {
            "ok": True,
            "system": "Brocade",
            "message": (
                "Authentication and zoning are validated by the playbook in dry-run/live mode"
            ),
        }
    return {"ok": True, "system": "Host", "wwns": len(equipment.wwns)}


@router.get("/integrations/powerstore/{equipment_id}/options")
def powerstore_options(equipment_id: int, _: AuthUser, db: DbSession):
    equipment = _get_equipment(db, equipment_id)
    if equipment.type == "POWERSTORE_NAS":
        with PowerStoreNASClient(
            equipment.management_address or "",
            equipment.username or "",
            decrypt_secret(equipment.encrypted_password),
            equipment.api_port,
            equipment.verify_ssl,
        ) as client:
            return client.get_nas_options()
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


@router.get("/integrations/powerscale/{equipment_id}/options")
def powerscale_options(equipment_id: int, _: AuthUser, db: DbSession):
    equipment = _get_equipment(db, equipment_id)
    if equipment.type != "POWERSCALE":
        raise HTTPException(status_code=400, detail="Equipment is not a PowerScale")
    settings = equipment_settings(equipment)
    with PowerScaleClient(
        equipment.management_address or "",
        equipment.username or "",
        decrypt_secret(equipment.encrypted_password),
        equipment.api_port,
        equipment.verify_ssl,
        settings.get("api_version", "3"),
    ) as client:
        return client.get_nas_options()


@router.get("/integrations/unity/{equipment_id}/options")
def unity_options(equipment_id: int, _: AuthUser, db: DbSession):
    equipment = _get_equipment(db, equipment_id)
    if equipment.type != "UNITY":
        raise HTTPException(status_code=400, detail="Equipment is not a Dell Unity")
    settings = equipment_settings(equipment)
    with UnityClient(
        equipment.management_address or "",
        equipment.username or "",
        decrypt_secret(equipment.encrypted_password),
        equipment.api_port,
        equipment.verify_ssl,
        settings.get("api_version", "5.2"),
    ) as client:
        return client.get_nas_options()


@router.get("/integrations/powermax/{equipment_id}/options")
def powermax_options(equipment_id: int, _: AuthUser, db: DbSession):
    equipment = _get_equipment(db, equipment_id)
    if equipment.type != "POWERMAX":
        raise HTTPException(status_code=400, detail="Equipment is not a PowerMax")
    settings = equipment_settings(equipment)
    symmetrix_id = settings.get("symmetrix_id")
    if not symmetrix_id:
        raise HTTPException(status_code=400, detail="symmetrix_id is not configured on PowerMax")
    with PowerMaxClient(
        equipment.management_address or "",
        equipment.username or "",
        decrypt_secret(equipment.encrypted_password),
        equipment.api_port,
        equipment.verify_ssl,
        settings.get("api_version", "100"),
    ) as client:
        return client.get_options(symmetrix_id)


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


@router.get("/integrations/ppdm/{equipment_id}/nas-options")
def ppdm_nas_options(equipment_id: int, _: AuthUser, db: DbSession):
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
        return client.get_nas_options()


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
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .order_by(desc(Workflow.id))
        .limit(limit)
    )
    if status_filter:
        statement = statement.where(Workflow.status == status_filter.upper())
    return [workflow_read(item) for item in db.scalars(statement).unique().all()]


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
def get_workflow(workflow_id: int, _: AuthUser, db: DbSession):
    workflow = db.scalar(
        select(Workflow).where(Workflow.id == workflow_id).options(selectinload(Workflow.steps))
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
