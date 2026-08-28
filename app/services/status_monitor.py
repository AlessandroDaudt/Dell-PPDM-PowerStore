import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.crypto import decrypt_secret
from app.database import SessionLocal
from app.models import Equipment, EquipmentType, StatusSample, utcnow
from app.services.brocade import BrocadeClient
from app.services.cisco_mds import CiscoMDSClient
from app.services.datadomain import DataDomainClient
from app.services.powermax import PowerMaxClient
from app.services.powerscale import PowerScaleClient
from app.services.powerstore import PowerStoreClient
from app.services.powerstore_nas import PowerStoreNASClient
from app.services.ppdm import PPDMClient
from app.services.unity import UnityClient

logger = logging.getLogger(__name__)


@dataclass
class CollectedStatus:
    component_key: str
    component_name: str
    component_type: str
    state: str
    metrics: dict[str, Any]
    error: str | None = None


class StatusCollector:
    """Collect vendor telemetry, persist one sample per component and prune old data."""

    COLLECTED_TYPES = {
        EquipmentType.POWERSTORE.value,
        EquipmentType.POWERMAX.value,
        EquipmentType.POWERSTORE_NAS.value,
        EquipmentType.POWERSCALE.value,
        EquipmentType.UNITY.value,
        EquipmentType.CISCO_MDS.value,
        EquipmentType.DATA_DOMAIN.value,
        EquipmentType.PPDM.value,
        EquipmentType.BROCADE.value,
    }

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self._lock = threading.Lock()

    def _client(self, equipment: Equipment) -> Any:
        password = decrypt_secret(equipment.encrypted_password)
        settings = json.loads(equipment.settings_json or "{}")
        common = {
            "address": equipment.management_address or "",
            "username": equipment.username or "",
            "password": password,
            "port": equipment.api_port,
            "verify_ssl": equipment.verify_ssl,
        }
        if equipment.type == EquipmentType.POWERSTORE.value:
            return PowerStoreClient(**common)
        if equipment.type == EquipmentType.POWERSTORE_NAS.value:
            return PowerStoreNASClient(**common)
        if equipment.type == EquipmentType.POWERMAX.value:
            return PowerMaxClient(**common, api_version=settings.get("api_version", "100"))
        if equipment.type == EquipmentType.POWERSCALE.value:
            return PowerScaleClient(**common, api_version=settings.get("api_version", "3"))
        if equipment.type == EquipmentType.UNITY.value:
            return UnityClient(**common, api_version=settings.get("api_version", "5.2"))
        if equipment.type == EquipmentType.CISCO_MDS.value:
            return CiscoMDSClient(**common, api_version=settings.get("api_version", "1.2"))
        if equipment.type == EquipmentType.DATA_DOMAIN.value:
            return DataDomainClient(**common)
        if equipment.type == EquipmentType.PPDM.value:
            return PPDMClient(**common)
        if equipment.type == EquipmentType.BROCADE.value:
            return BrocadeClient(**common)
        raise ValueError(f"Equipment type cannot be collected: {equipment.type}")

    def _collect_one(self, equipment: Equipment) -> list[CollectedStatus]:
        try:
            with self._client(equipment) as client:
                result = (
                    client.get_status(
                        json.loads(equipment.settings_json or "{}").get("symmetrix_id")
                    )
                    if equipment.type == EquipmentType.POWERMAX.value
                    else client.get_status()
                )
            state = str(result.get("state", "UNKNOWN")).upper()
            metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
            error = result.get("error")
            records = [
                CollectedStatus("equipment", equipment.name, equipment.type, state, metrics, error)
            ]
            if equipment.type == EquipmentType.PPDM.value:
                records.extend(self._ppdm_data_domain_records(metrics))
            return records
        except Exception as exc:  # a failing appliance must not stop the other samples
            logger.warning("status collection failed for equipment %s: %s", equipment.name, exc)
            return [
                CollectedStatus("equipment", equipment.name, equipment.type, "ERROR", {}, str(exc))
            ]

    @staticmethod
    def _ppdm_data_domain_records(metrics: dict[str, Any]) -> list[CollectedStatus]:
        data_domains = metrics.get("data_domains")
        if not isinstance(data_domains, list):
            return []
        records: list[CollectedStatus] = []
        for data_domain in data_domains:
            if not isinstance(data_domain, dict):
                continue
            identifier = (
                data_domain.get("id")
                or data_domain.get("uuid")
                or data_domain.get("storageSystemId")
            )
            if not identifier:
                continue
            name = data_domain.get("name") or data_domain.get("hostname") or str(identifier)
            records.append(
                CollectedStatus(
                    f"datadomain:{identifier}",
                    str(name),
                    EquipmentType.DATA_DOMAIN.value,
                    "OK",
                    {"storage_system": data_domain},
                )
            )
        return records

    @staticmethod
    def _upsert(db: Session, equipment_id: int, sampled_at: Any, record: CollectedStatus) -> None:
        sample = db.scalar(
            select(StatusSample).where(
                StatusSample.equipment_id == equipment_id,
                StatusSample.component_key == record.component_key,
                StatusSample.sampled_at == sampled_at,
            )
        )
        values = {
            "component_name": record.component_name,
            "component_type": record.component_type,
            "state": record.state,
            "metrics_json": json.dumps(record.metrics, ensure_ascii=False, default=str),
            "error": record.error,
        }
        if sample:
            for key, value in values.items():
                setattr(sample, key, value)
        else:
            db.add(
                StatusSample(
                    equipment_id=equipment_id,
                    sampled_at=sampled_at,
                    **{"component_key": record.component_key},
                    **values,
                )
            )

    def collect_now(self) -> dict[str, int | str]:
        with self._lock:
            sampled_at = utcnow().replace(second=0, microsecond=0)
            db = self.session_factory()
            try:
                equipment = db.scalars(
                    select(Equipment)
                    .where(Equipment.type.in_(self.COLLECTED_TYPES))
                    .order_by(Equipment.id)
                ).all()
                samples = 0
                errors = 0
                for item in equipment:
                    records = self._collect_one(item)
                    for record in records:
                        self._upsert(db, item.id, sampled_at, record)
                        samples += 1
                        errors += record.state == "ERROR"
                cutoff = utcnow() - timedelta(days=self.settings.status_retention_days)
                deleted = (
                    db.execute(
                        delete(StatusSample).where(StatusSample.sampled_at < cutoff)
                    ).rowcount
                    or 0
                )
                db.commit()
                return {
                    "sampled_at": sampled_at.isoformat(),
                    "equipment": len(equipment),
                    "samples": samples,
                    "errors": errors,
                    "deleted": deleted,
                }
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()


class StatusMonitor:
    def __init__(self, collector: StatusCollector | None = None) -> None:
        self.collector = collector or StatusCollector()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.collector.collect_now()
            except Exception:
                logger.exception("status collection cycle failed")
            self._stop.wait(self.collector.settings.status_sample_interval_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="status-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None


status_monitor = StatusMonitor()
