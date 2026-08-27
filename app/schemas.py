import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WWN_HEX = re.compile(r"^[0-9a-fA-F]{16}$")


def normalize_wwn(value: str) -> str:
    compact = re.sub(r"[^0-9a-fA-F]", "", value or "")
    if not WWN_HEX.fullmatch(compact):
        raise ValueError("WWN deve conter exatamente 16 dígitos hexadecimais")
    compact = compact.lower()
    return ":".join(compact[index : index + 2] for index in range(0, 16, 2))


class WWNInput(BaseModel):
    value: str
    label: str = ""
    fabric: str = "A"
    role: Literal["INITIATOR", "TARGET", "SWITCH"] = "INITIATOR"

    @field_validator("value")
    @classmethod
    def validate_wwn(cls, value: str) -> str:
        return normalize_wwn(value)

    @field_validator("fabric")
    @classmethod
    def normalize_fabric(cls, value: str) -> str:
        return value.strip().upper()[:16] or "A"


class WWNRead(WWNInput):
    id: int
    model_config = ConfigDict(from_attributes=True)


class EquipmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    type: Literal["POWERSTORE", "PPDM", "BROCADE", "HOST"]
    management_address: str | None = Field(default=None, max_length=255)
    api_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=1024)
    verify_ssl: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    wwns: list[WWNInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_address(self):
        if self.type != "HOST" and not self.management_address:
            raise ValueError("endereço de gerenciamento é obrigatório para este tipo")
        if self.type in {"POWERSTORE", "PPDM", "BROCADE"} and not self.username:
            raise ValueError("usuário de API é obrigatório para este tipo")
        return self


class EquipmentUpdate(EquipmentCreate):
    password: str | None = None


class EquipmentRead(BaseModel):
    id: int
    name: str
    type: str
    management_address: str | None
    api_port: int | None
    username: str | None
    verify_ssl: bool
    settings: dict[str, Any]
    wwns: list[WWNRead]
    created_at: datetime
    updated_at: datetime


class VolumeMemberOptions(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    size_gib: int = Field(ge=1, le=65536)
    description: str = Field(default="Criado pelo SANFlow Dell", max_length=256)
    logical_unit_number: int | None = Field(default=None, ge=0, le=16383)


class VolumeOptions(BaseModel):
    name: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    size_gib: int | None = Field(default=None, ge=1, le=65536)
    description: str = Field(default="Criado pelo SANFlow Dell", max_length=256)
    resource_type: Literal["VOLUME", "VOLUME_GROUP"] = "VOLUME"
    group_name: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    group_description: str | None = Field(default=None, max_length=256)
    members: list[VolumeMemberOptions] = Field(default_factory=list, max_length=128)
    write_order_consistent: bool = True
    appliance_id: str | None = None
    performance_policy_id: str | None = None
    protection_policy_id: str | None = None
    logical_unit_number: int | None = Field(default=None, ge=0, le=16383)

    @model_validator(mode="after")
    def validate_resource(self):
        if self.resource_type == "VOLUME_GROUP":
            if not self.group_name:
                raise ValueError("group_name é obrigatório para VOLUME_GROUP")
            if not self.members:
                raise ValueError("members é obrigatório para VOLUME_GROUP")
            names = [member.name.casefold() for member in self.members]
            if len(names) != len(set(names)):
                raise ValueError("members não pode conter nomes repetidos")
        else:
            if not self.name or self.size_gib is None:
                raise ValueError("name e size_gib são obrigatórios para VOLUME")
            if self.group_name or self.members:
                raise ValueError("group_name e members só podem ser usados em VOLUME_GROUP")
        return self


class ZoningOptions(BaseModel):
    enabled: bool = True
    config_name: str = Field(default="SANFLOW_CFG", min_length=1, max_length=64)
    naming_template: str = Field(default="Z_{host}_{storage}_{fabric}", max_length=128)
    activate: bool = True
    peer_zoning: bool = False


class BackupOptions(BaseModel):
    mode: Literal["NONE", "EXISTING_POLICY", "CREATE_POLICY"] = "EXISTING_POLICY"
    policy_id: str | None = None
    policy_name: str | None = Field(default=None, max_length=128)
    data_domain_id: str | None = None
    data_domain_interface: str | None = None
    storage_unit_id: str | None = None
    frequency: Literal["HOURLY", "DAILY", "WEEKLY", "MONTHLY"] = "DAILY"
    interval: int = Field(default=1, ge=1, le=24)
    start_time: str = Field(default="22:00:00", pattern=r"^\d{2}:\d{2}:\d{2}$")
    duration_hours: int = Field(default=8, ge=1, le=24)
    weekdays: list[str] = Field(default_factory=lambda: ["SATURDAY"])
    day_of_month: int = Field(default=1, ge=1, le=31)
    retention_interval: int = Field(default=30, ge=1, le=3650)
    retention_unit: Literal["DAY", "WEEK", "MONTH", "YEAR"] = "DAY"
    retention_lock: bool = False
    backup_level: Literal["SYNTHETIC_FULL", "FULL"] = "SYNTHETIC_FULL"
    encrypted: bool = True
    data_consistency: Literal["CRASH_CONSISTENT", "APPLICATION_CONSISTENT"] = (
        "CRASH_CONSISTENT"
    )
    snapshot_enabled: bool = False
    replication_enabled: bool = False
    cloud_tier_enabled: bool = False
    raw_overrides: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "EXISTING_POLICY" and not self.policy_id:
            raise ValueError("policy_id é obrigatório no modo EXISTING_POLICY")
        if self.mode == "CREATE_POLICY" and (not self.policy_name or not self.data_domain_id):
            raise ValueError("policy_name e data_domain_id são obrigatórios ao criar uma política")
        requested = {
            "SNAPSHOT": self.snapshot_enabled,
            "REPLICATION": self.replication_enabled,
            "CLOUD_TIER": self.cloud_tier_enabled,
        }
        if self.mode == "CREATE_POLICY" and any(requested.values()):
            configured = []
            for key in ("objectives", "stages", "additional_objectives"):
                value = self.raw_overrides.get(key, [])
                if isinstance(value, list):
                    configured.extend(value)
            configured_types = {
                str(item.get("type", "")).upper()
                for item in configured
                if isinstance(item, dict)
            }
            missing = [
                name
                for name, enabled in requested.items()
                if enabled and name not in configured_types
            ]
            if missing:
                raise ValueError(
                    "objetivos avançados selecionados exigem a definição completa em "
                    f"raw_overrides: {', '.join(missing)}"
                )
        return self


class ProvisionRequest(BaseModel):
    storage_id: int
    ppdm_id: int | None = None
    host_ids: list[int] = Field(min_length=1)
    brocade_ids: list[int] = Field(default_factory=list)
    volume: VolumeOptions
    zoning: ZoningOptions = Field(default_factory=ZoningOptions)
    backup: BackupOptions = Field(default_factory=BackupOptions)
    dry_run: bool = True

    @model_validator(mode="after")
    def validate_integrations(self):
        if self.zoning.enabled and not self.brocade_ids:
            raise ValueError("selecione ao menos um Brocade quando o zoning estiver habilitado")
        if self.backup.mode != "NONE" and self.ppdm_id is None:
            raise ValueError("selecione um PPDM quando o backup estiver habilitado")
        return self


class WorkflowStepRead(BaseModel):
    id: int
    step_order: int
    name: str
    status: str
    message: str
    details: dict[str, Any]
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowRead(BaseModel):
    id: int
    status: str
    dry_run: bool
    request: dict[str, Any]
    current_step: str | None
    volume_id: str | None
    volume_wwn: str | None
    policy_id: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: list[WorkflowStepRead]
