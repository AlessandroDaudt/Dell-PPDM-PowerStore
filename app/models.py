import enum
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class EquipmentType(str, enum.Enum):
    POWERSTORE = "POWERSTORE"
    POWERMAX = "POWERMAX"
    PPDM = "PPDM"
    BROCADE = "BROCADE"
    HOST = "HOST"


class WorkflowStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class StepStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    management_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    wwns: Mapped[list["WWN"]] = relationship(
        back_populates="equipment", cascade="all, delete-orphan"
    )


class WWN(Base):
    __tablename__ = "wwns"
    __table_args__ = (UniqueConstraint("equipment_id", "value", name="uq_equipment_wwn"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), index=True
    )
    value: Mapped[str] = mapped_column(String(23), index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    fabric: Mapped[str] = mapped_column(String(16), default="A")
    role: Mapped[str] = mapped_column(String(32), default="INITIATOR")

    equipment: Mapped[Equipment] = relationship(back_populates="wwns")


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=WorkflowStatus.PENDING.value)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    request_json: Mapped[str] = mapped_column(Text)
    current_step: Mapped[str | None] = mapped_column(String(128), nullable=True)
    volume_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    volume_wwn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowStep.step_order"
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    step_order: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default=StepStatus.PENDING.value)
    message: Mapped[str] = mapped_column(Text, default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow: Mapped[Workflow] = relationship(back_populates="steps")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
