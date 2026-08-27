from datetime import timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import Base
from app.models import Equipment, StatusSample, utcnow
from app.services.status_monitor import CollectedStatus, StatusCollector


def test_status_collector_upserts_minute_and_deletes_samples_older_than_retention():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as db:
        equipment = Equipment(
            name="MDS-01",
            type="CISCO_MDS",
            management_address="mds",
            username="api-user",
            encrypted_password="",
        )
        db.add(equipment)
        db.flush()
        db.add(
            StatusSample(
                equipment_id=equipment.id,
                component_key="equipment",
                component_name="MDS-01",
                component_type="CISCO_MDS",
                state="OK",
                sampled_at=utcnow() - timedelta(days=31),
                metrics_json="{}",
            )
        )
        db.commit()

    collector = StatusCollector(
        session_factory=session_factory,
        settings=Settings(status_retention_days=30),
    )
    collector._collect_one = lambda _equipment: [
        CollectedStatus("equipment", "MDS-01", "CISCO_MDS", "OK", {"ports": []})
    ]
    result = collector.collect_now()

    with Session(engine) as db:
        samples = db.scalars(select(StatusSample)).all()
    assert result["samples"] == 1
    assert result["deleted"] == 1
    assert len(samples) == 1
    assert samples[0].metrics_json == '{"ports": []}'
