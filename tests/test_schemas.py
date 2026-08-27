import pytest
from pydantic import ValidationError

from app.schemas import BackupOptions, ProvisionRequest, normalize_wwn


def test_normalize_wwn_accepts_common_formats():
    assert normalize_wwn("10000090FA123456") == "10:00:00:90:fa:12:34:56"
    assert normalize_wwn("10-00-00-90-FA-12-34-56") == "10:00:00:90:fa:12:34:56"


def test_normalize_wwn_rejects_invalid_value():
    with pytest.raises(ValueError):
        normalize_wwn("not-a-wwn")


def test_existing_policy_requires_id():
    with pytest.raises(ValidationError):
        BackupOptions(mode="EXISTING_POLICY")


def test_advanced_objective_cannot_be_silently_ignored():
    with pytest.raises(ValidationError, match="REPLICATION"):
        BackupOptions(
            mode="CREATE_POLICY",
            policy_name="POL_REPL",
            data_domain_id="dd-1",
            replication_enabled=True,
        )


def test_advanced_objective_accepts_documented_override():
    options = BackupOptions(
        mode="CREATE_POLICY",
        policy_name="POL_REPL",
        data_domain_id="dd-1",
        replication_enabled=True,
        raw_overrides={"additional_objectives": [{"type": "REPLICATION"}]},
    )
    assert options.replication_enabled is True


def test_provision_requires_ppdm_when_backup_enabled():
    with pytest.raises(ValidationError):
        ProvisionRequest.model_validate(
            {
                "storage_id": 1,
                "host_ids": [2],
                "brocade_ids": [3],
                "volume": {"name": "VOL_01", "size_gib": 10},
                "backup": {"mode": "EXISTING_POLICY", "policy_id": "policy-1"},
            }
        )


def test_dry_run_payload_can_disable_optional_integrations():
    request = ProvisionRequest.model_validate(
        {
            "storage_id": 1,
            "host_ids": [2],
            "volume": {"name": "VOL_01", "size_gib": 10},
            "zoning": {"enabled": False},
            "backup": {"mode": "NONE"},
            "dry_run": True,
        }
    )
    assert request.dry_run is True
