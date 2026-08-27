import json
import re
import traceback
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt_secret
from app.database import SessionLocal
from app.models import (
    AuditEvent,
    Equipment,
    EquipmentType,
    StepStatus,
    Workflow,
    WorkflowStatus,
    WorkflowStep,
    utcnow,
)
from app.services.ansible_runner import run_brocade_zoning
from app.services.powermax import PowerMaxClient
from app.services.powerscale import PowerScaleClient
from app.services.powerstore import PowerStoreClient
from app.services.powerstore_nas import PowerStoreNASClient
from app.services.ppdm import PPDMClient
from app.services.unity import UnityClient

STEP_NAMES = [
    "Validar inventário e WWNs",
    "Criar LUN no PowerStore",
    "Apresentar LUN aos hosts",
    "Configurar zoning Brocade",
    "Configurar proteção no PPDM",
    "Verificar resultado ponta a ponta",
]


def equipment_settings(equipment: Equipment) -> dict[str, Any]:
    try:
        value = json.loads(equipment.settings_json or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def create_workflow(db: Session, request_data: dict[str, Any], dry_run: bool) -> Workflow:
    workflow = Workflow(
        status=WorkflowStatus.PENDING.value,
        dry_run=dry_run,
        request_json=json.dumps(request_data, ensure_ascii=False),
    )
    db.add(workflow)
    db.flush()
    for order, name in enumerate(STEP_NAMES, start=1):
        db.add(
            WorkflowStep(
                workflow_id=workflow.id,
                step_order=order,
                name=name,
                status=StepStatus.PENDING.value,
            )
        )
    db.add(
        AuditEvent(
            actor="admin",
            action="workflow.create",
            resource_type="workflow",
            resource_id=str(workflow.id),
            outcome="PENDING",
            details_json=json.dumps({"dry_run": dry_run}),
        )
    )
    db.commit()
    db.refresh(workflow)
    return workflow


class WorkflowRunner:
    def __init__(self, workflow_id: int) -> None:
        self.workflow_id = workflow_id
        self.db = SessionLocal()
        self.workflow = self.db.get(Workflow, workflow_id)
        if not self.workflow:
            self.db.close()
            raise ValueError(f"workflow {workflow_id} não encontrado")
        self.request: dict[str, Any] = json.loads(self.workflow.request_json)
        self.context: dict[str, Any] = {}

    def close(self) -> None:
        self.db.close()

    def _get_equipment(self, equipment_id: int, expected_type: EquipmentType) -> Equipment:
        equipment = self.db.get(Equipment, equipment_id)
        if not equipment:
            raise ValueError(f"equipamento {equipment_id} não encontrado")
        if equipment.type != expected_type.value:
            raise ValueError(
                f"equipamento {equipment.name} é {equipment.type}, esperado {expected_type.value}"
            )
        return equipment

    def _step(self, order: int, action: Callable[[], tuple[str, dict[str, Any]]]) -> None:
        step = next(item for item in self.workflow.steps if item.step_order == order)
        step.status = StepStatus.RUNNING.value
        step.started_at = utcnow()
        self.workflow.current_step = step.name
        self.db.commit()
        try:
            message, details = action()
            step.status = StepStatus.COMPLETED.value
            step.message = message
            step.details_json = json.dumps(details, ensure_ascii=False, default=str)
            step.finished_at = utcnow()
            self.db.commit()
        except Exception as exc:
            step.status = StepStatus.FAILED.value
            step.message = str(exc)
            step.details_json = json.dumps(
                {"error_type": exc.__class__.__name__}, ensure_ascii=False
            )
            step.finished_at = utcnow()
            self.db.commit()
            raise

    def _validate(self) -> tuple[str, dict[str, Any]]:
        resource_type = self.request["volume"].get("resource_type", "VOLUME")
        if resource_type == "POWERMAX_STORAGE_GROUP":
            storage = self._get_equipment(self.request["storage_id"], EquipmentType.POWERMAX)
        elif resource_type in {"NAS_SHARE", "NAS_DATA"}:
            storage = self.db.get(Equipment, self.request["storage_id"])
            if not storage:
                raise ValueError(f"equipamento {self.request['storage_id']} não encontrado")
            if storage.type not in {"POWERSTORE_NAS", "POWERSCALE", "UNITY"}:
                raise ValueError(
                    f"equipamento {storage.name} é {storage.type}, esperado um storage NAS Dell"
                )
        else:
            storage = self._get_equipment(self.request["storage_id"], EquipmentType.POWERSTORE)
        hosts = [
            self._get_equipment(item, EquipmentType.HOST) for item in self.request["host_ids"]
        ]
        brocades = [
            self._get_equipment(item, EquipmentType.BROCADE)
            for item in self.request.get("brocade_ids", [])
        ]
        ppdm = None
        if self.request["backup"]["mode"] != "NONE":
            ppdm = self._get_equipment(self.request["ppdm_id"], EquipmentType.PPDM)

        for host in hosts:
            initiators = [wwn for wwn in host.wwns if wwn.role == "INITIATOR"]
            if not initiators:
                raise ValueError(f"host {host.name} não possui WWN iniciador")
        if resource_type == "POWERMAX_STORAGE_GROUP":
            settings = equipment_settings(storage)
            if not settings.get("symmetrix_id"):
                raise ValueError(f"PowerMax {storage.name} não possui symmetrix_id configurado")
        elif resource_type in {"NAS_SHARE", "NAS_DATA"}:
            if not self.request["volume"].get("nas_path"):
                raise ValueError("recurso NAS não possui nas_path")
        elif self.request["zoning"]["enabled"]:
            targets = [wwn for wwn in storage.wwns if wwn.role == "TARGET"]
            if not targets:
                raise ValueError(f"PowerStore {storage.name} não possui WWN target")
            fabrics = {wwn.fabric for wwn in targets}
            for switch in brocades:
                fabric = str(equipment_settings(switch).get("fabric", "A")).upper()
                if fabric not in fabrics:
                    raise ValueError(
                        f"não há WWN target do PowerStore para a fabric {fabric} ({switch.name})"
                    )

        self.context.update(storage=storage, hosts=hosts, brocades=brocades, ppdm=ppdm)
        return (
            "Inventário validado",
            {
                "storage": storage.name,
                "hosts": [host.name for host in hosts],
                "brocades": [switch.name for switch in brocades],
                "ppdm": ppdm.name if ppdm else None,
            },
        )

    def _create_volume(self) -> tuple[str, dict[str, Any]]:
        storage: Equipment = self.context["storage"]
        volume = self.request["volume"]
        is_group = volume.get("resource_type") == "VOLUME_GROUP"
        is_powermax_group = volume.get("resource_type") == "POWERMAX_STORAGE_GROUP"
        is_nas = volume.get("resource_type") in {"NAS_SHARE", "NAS_DATA"}
        if self.workflow.dry_run:
            if is_nas:
                created = {
                    "id": f"dryrun-nas-{self.workflow.id}",
                    "name": volume["name"],
                    "path": volume["nas_path"],
                    "protocol": volume["nas_protocol"],
                    "planned_requests": [
                        "GET /api/rest/nas_server",
                        "GET /api/rest/file_system",
                        "GET /api/rest/smb_share or /api/rest/nfs_export",
                        "POST /api/rest/file_system and share when the resource is new",
                    ],
                }
            elif is_powermax_group:
                created = {
                    "id": f"dryrun-powermax-sg-{self.workflow.id}",
                    "name": volume["name"],
                    "planned_request": (
                        "POST /univmax/restapi/{version}/sloprovisioning/symmetrix/"
                        "{symmetrix_id}/storagegroup"
                    ),
                    "payload": {
                        "storageGroupId": volume["name"],
                        "num_of_vols": volume["volume_count"],
                        "volume_size": volume["size_gib"],
                    },
                }
            elif is_group:
                created = {
                    "id": f"dryrun-volume-group-{self.workflow.id}",
                    "name": volume["group_name"],
                    "type": "Primary",
                    "volumes": [
                        {
                            "id": f"dryrun-volume-{self.workflow.id}-{index}",
                            "name": member["name"],
                            "size": member["size_gib"] * 1024**3,
                            "wwn": "naa.dry-run",
                        }
                        for index, member in enumerate(volume["members"], start=1)
                    ],
                    "planned_requests": [
                        "POST /api/rest/volume_group",
                        "POST /api/rest/volume (per member)",
                    ],
                }
            else:
                created = {
                    "id": f"dryrun-volume-{self.workflow.id}",
                    "name": volume["name"],
                    "size": volume["size_gib"] * 1024**3,
                    "wwn": "naa.dry-run",
                    "planned_request": "POST /api/rest/volume",
                }
        else:
            if is_nas:
                if storage.type == "POWERSCALE":
                    client_type = PowerScaleClient
                elif storage.type == "UNITY":
                    client_type = UnityClient
                else:
                    client_type = PowerStoreNASClient
                with client_type(
                    storage.management_address or "",
                    storage.username or "",
                    decrypt_secret(storage.encrypted_password),
                    storage.api_port,
                    storage.verify_ssl,
                    equipment_settings(storage).get(
                        "api_version", "5.2" if storage.type == "UNITY" else "3"
                    )
                    if storage.type in {"POWERSCALE", "UNITY"}
                    else None,
                ) as client:
                    created = client.ensure_share(volume)
            elif is_powermax_group:
                settings = equipment_settings(storage)
                with PowerMaxClient(
                    storage.management_address or "",
                    storage.username or "",
                    decrypt_secret(storage.encrypted_password),
                    storage.api_port,
                    storage.verify_ssl,
                    settings.get("api_version", "100"),
                ) as client:
                    client.symmetrix_id = settings["symmetrix_id"]
                    created = client.ensure_storage_group(volume)
            else:
                with PowerStoreClient(
                    storage.management_address or "",
                    storage.username or "",
                    decrypt_secret(storage.encrypted_password),
                    storage.api_port,
                    storage.verify_ssl,
                ) as client:
                    if is_group:
                        created = client.create_volume_group(volume)
                    else:
                        created = client.create_volume(volume)
                        full_volume = client.get_volume(created["id"])
                        created = {**created, **full_volume}
        self.workflow.volume_id = str(created["id"])
        self.workflow.volume_wwn = created.get("wwn")
        self.db.commit()
        self.context["volume"] = created
        resource_name = volume.get("name") or volume.get("group_name")
        return f"LUN {resource_name} preparada", created

    def _map_hosts(self) -> tuple[str, dict[str, Any]]:
        if self.request["volume"].get("resource_type") == "POWERMAX_STORAGE_GROUP":
            return (
                "Apresentação de hosts não aplicável ao Storage Group PowerMax",
                {"skipped": True},
            )
        if self.request["volume"].get("resource_type") in {"NAS_SHARE", "NAS_DATA"}:
            return "Apresentação FC não aplicável ao recurso NAS", {"skipped": True}
        storage: Equipment = self.context["storage"]
        volume_id = self.context["volume"]["id"]
        mappings: list[dict[str, Any]] = []
        if self.workflow.dry_run:
            for host in self.context["hosts"]:
                mappings.append(
                    {
                        "host": host.name,
                        "host_id": f"dryrun-host-{host.id}",
                        "volume_id": volume_id,
                        "planned_requests": [
                            "GET/POST /api/rest/host",
                            (
                                "POST /api/rest/volume_group/{id}/attach"
                                if self.request["volume"].get("resource_type") == "VOLUME_GROUP"
                                else "POST /api/rest/host_volume_mapping"
                            ),
                        ],
                    }
                )
        else:
            with PowerStoreClient(
                storage.management_address or "",
                storage.username or "",
                decrypt_secret(storage.encrypted_password),
                storage.api_port,
                storage.verify_ssl,
            ) as client:
                for host in self.context["hosts"]:
                    settings = equipment_settings(host)
                    registered = client.ensure_host(
                        host.name,
                        settings.get("os_type", "Linux"),
                        [wwn.value for wwn in host.wwns if wwn.role == "INITIATOR"],
                        settings.get("powerstore_host_id"),
                    )
                    if self.request["volume"].get("resource_type") == "VOLUME_GROUP":
                        mapped = client.map_volume_group(registered["id"], volume_id)
                    else:
                        mapped = client.map_volume(
                            registered["id"],
                            volume_id,
                            self.request["volume"].get("logical_unit_number"),
                        )
                    mappings.append({"host": host.name, "host_id": registered["id"], **mapped})
        self.context["mappings"] = mappings
        return f"LUN apresentada a {len(mappings)} host(s)", {"mappings": mappings}

    def _zone(self) -> tuple[str, dict[str, Any]]:
        if self.request["volume"].get("resource_type") == "POWERMAX_STORAGE_GROUP":
            return "Zoning não aplicável ao Storage Group PowerMax", {"skipped": True}
        if self.request["volume"].get("resource_type") in {"NAS_SHARE", "NAS_DATA"}:
            return "Zoning não aplicável ao recurso NAS", {"skipped": True}
        if not self.request["zoning"]["enabled"]:
            return "Zoning desabilitado pela solicitação", {"skipped": True}
        storage: Equipment = self.context["storage"]
        ansible_switches: list[dict[str, Any]] = []
        zone_names: list[str] = []
        for switch in self.context["brocades"]:
            settings = equipment_settings(switch)
            fabric = str(settings.get("fabric", "A")).upper()
            target_wwns = [
                item.value
                for item in storage.wwns
                if item.role == "TARGET" and item.fabric == fabric
            ]
            for host in self.context["hosts"]:
                initiators = [
                    item.value
                    for item in host.wwns
                    if item.role == "INITIATOR" and item.fabric == fabric
                ]
                if not initiators:
                    continue
                zone_name = self.request["zoning"]["naming_template"].format(
                    host=host.name, storage=storage.name, fabric=fabric
                )
                zone_name = re.sub(r"[^A-Za-z0-9_.-]", "_", zone_name)[:64]
                zone_names.append(zone_name)
                ansible_switches.append(
                    {
                        "inventory_name": f"switch_{switch.id}_{host.id}",
                        "switch_api_url": (
                            f"https://{switch.management_address}:{switch.api_port or 443}"
                        ),
                        "switch_username": switch.username or "",
                        "switch_password": decrypt_secret(switch.encrypted_password),
                        "verify_ssl": switch.verify_ssl,
                        "fabric_id": settings.get("fid", 128),
                        "fos_generation": str(settings.get("fos_generation", "9.1")),
                        "zone_name": zone_name,
                        "zone_members": (
                            initiators
                            if self.request["zoning"]["peer_zoning"]
                            else initiators + target_wwns
                        ),
                        "zone_principal_members": (
                            target_wwns if self.request["zoning"]["peer_zoning"] else []
                        ),
                        "zone_config": settings.get(
                            "active_config", self.request["zoning"]["config_name"]
                        ),
                        "activate_config": self.request["zoning"]["activate"],
                        "peer_zoning": self.request["zoning"]["peer_zoning"],
                    }
                )
        if not ansible_switches:
            raise ValueError("nenhuma combinação válida de WWNs por fabric para criar zonas")
        if self.workflow.dry_run:
            result = {
                "planned_playbook": str(get_settings().ansible_playbook),
                "switch_tasks": [
                    {
                        "switch": item["inventory_name"],
                        "zone": item["zone_name"],
                        "members": item["zone_members"],
                    }
                    for item in ansible_switches
                ],
            }
        else:
            result = run_brocade_zoning(ansible_switches)
        self.context["zones"] = zone_names
        return f"{len(zone_names)} zona(s) processada(s) via Ansible REST", result

    def _backup(self) -> tuple[str, dict[str, Any]]:
        options = self.request["backup"]
        if options["mode"] == "NONE":
            return "Proteção PPDM desabilitada pela solicitação", {"skipped": True}
        ppdm: Equipment = self.context["ppdm"]
        is_nas = self.request["volume"].get("resource_type") in {"NAS_SHARE", "NAS_DATA"}
        if self.workflow.dry_run:
            policy_id = options.get("policy_id") or f"dryrun-policy-{self.workflow.id}"
            result = {
                "policy_id": policy_id,
                "mode": options["mode"],
                "planned_requests": [
                    "POST /api/v2/login",
                    "GET /api/v2/assets",
                    "GET /api/v2/protection-engines (NAS)" if is_nas else "",
                    "POST /api/v2|v3/protection-policies (quando CREATE_POLICY)",
                    f"POST /api/v2/protection-policies/{policy_id}/asset-assignments",
                ],
            }
        else:
            with PPDMClient(
                ppdm.management_address or "",
                ppdm.username or "",
                decrypt_secret(ppdm.encrypted_password),
                ppdm.api_port,
                ppdm.verify_ssl,
            ) as client:
                if options["mode"] == "CREATE_POLICY":
                    policy = (
                        client.create_nas_policy(options)
                        if is_nas
                        else client.create_powerstore_policy(options)
                    )
                    policy_id = policy["id"]
                else:
                    policy_id = options["policy_id"]
                settings = get_settings()
                if is_nas:
                    asset = client.wait_for_nas_asset(
                        self.request["volume"]["name"],
                        self.request["volume"].get("nas_path"),
                        timeout=settings.ppdm_discovery_timeout,
                        interval=settings.ppdm_discovery_interval,
                    )
                else:
                    asset_name = (
                        self.request["volume"].get("name")
                        or self.request["volume"].get("group_name")
                    )
                    asset = client.wait_for_powerstore_asset(
                        asset_name,
                        timeout=settings.ppdm_discovery_timeout,
                        interval=settings.ppdm_discovery_interval,
                    )
                assignment = client.assign_asset(policy_id, asset["id"])
                result = {
                    "policy_id": policy_id,
                    "asset_id": asset["id"],
                    "asset_name": asset.get("name"),
                    "assignment": assignment,
                }
        self.workflow.policy_id = str(policy_id)
        self.db.commit()
        self.context["backup"] = result
        return "Volume associado à proteção do PPDM", result

    def _verify(self) -> tuple[str, dict[str, Any]]:
        if self.workflow.dry_run:
            details = {
                "mode": "dry-run",
                "volume": self.context["volume"],
                "mappings": len(self.context.get("mappings", [])),
                "zones": self.context.get("zones", []),
                "policy_id": self.workflow.policy_id,
            }
            return "Plano validado sem alterar os equipamentos", details
        storage: Equipment = self.context["storage"]
        if self.request["volume"].get("resource_type") in {"NAS_SHARE", "NAS_DATA"}:
            storage = self.context["storage"]
            if storage.type == "POWERSCALE":
                client_type = PowerScaleClient
            elif storage.type == "UNITY":
                client_type = UnityClient
            else:
                client_type = PowerStoreNASClient
            with client_type(
                storage.management_address or "",
                storage.username or "",
                decrypt_secret(storage.encrypted_password),
                storage.api_port,
                storage.verify_ssl,
                equipment_settings(storage).get(
                    "api_version", "5.2" if storage.type == "UNITY" else "3"
                )
                if storage.type in {"POWERSCALE", "UNITY"}
                else None,
            ) as client:
                volume = client.get_share(
                    self.workflow.volume_id or "",
                    self.request["volume"].get("nas_protocol", "NFS"),
                )
        elif self.request["volume"].get("resource_type") == "POWERMAX_STORAGE_GROUP":
            settings = equipment_settings(storage)
            with PowerMaxClient(
                storage.management_address or "",
                storage.username or "",
                decrypt_secret(storage.encrypted_password),
                storage.api_port,
                storage.verify_ssl,
                settings.get("api_version", "100"),
            ) as client:
                client.symmetrix_id = settings["symmetrix_id"]
                volume = client.get_storage_group(self.workflow.volume_id or "")
        else:
            with PowerStoreClient(
                storage.management_address or "",
                storage.username or "",
                decrypt_secret(storage.encrypted_password),
                storage.api_port,
                storage.verify_ssl,
            ) as client:
                if self.request["volume"].get("resource_type") == "VOLUME_GROUP":
                    volume = client.get_volume_group(self.workflow.volume_id or "")
                else:
                    volume = client.get_volume(self.workflow.volume_id or "")
        if not volume.get("id"):
            raise ValueError("PowerStore não retornou o volume na verificação final")
        return (
            "Provisionamento verificado com sucesso",
            {
                "volume": volume,
                "host_mappings": self.context.get("mappings", []),
                "zones": self.context.get("zones", []),
                "policy_id": self.workflow.policy_id,
            },
        )

    def run(self) -> None:
        self.workflow.status = WorkflowStatus.RUNNING.value
        self.workflow.started_at = utcnow()
        self.db.commit()
        try:
            for order, action in enumerate(
                [
                    self._validate,
                    self._create_volume,
                    self._map_hosts,
                    self._zone,
                    self._backup,
                    self._verify,
                ],
                start=1,
            ):
                self._step(order, action)
            self.workflow.status = WorkflowStatus.COMPLETED.value
            self.workflow.current_step = None
            self.workflow.finished_at = utcnow()
            self.db.add(
                AuditEvent(
                    actor="system",
                    action="workflow.complete",
                    resource_type="workflow",
                    resource_id=str(self.workflow.id),
                    outcome="COMPLETED",
                    details_json=json.dumps({"dry_run": self.workflow.dry_run}),
                )
            )
            self.db.commit()
        except Exception as exc:
            self.workflow.status = WorkflowStatus.FAILED.value
            self.workflow.error = str(exc)
            self.workflow.finished_at = utcnow()
            self.db.add(
                AuditEvent(
                    actor="system",
                    action="workflow.fail",
                    resource_type="workflow",
                    resource_id=str(self.workflow.id),
                    outcome="FAILED",
                    details_json=json.dumps(
                        {
                            "error": str(exc),
                            "trace": traceback.format_exc(limit=8),
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            self.db.commit()
        finally:
            self.close()


def run_workflow(workflow_id: int) -> None:
    WorkflowRunner(workflow_id).run()
