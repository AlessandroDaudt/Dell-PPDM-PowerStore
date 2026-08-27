import json

import httpx

from app.services.ppdm import PPDMClient


def test_ppdm_creates_nas_policy_with_protection_engine():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/login":
            return httpx.Response(200, json={"access_token": "token-1"})
        if request.url.path == "/api/v2/nodes":
            return httpx.Response(200, json={"content": [{"version": "19.22.0"}]})
        if request.url.path == "/api/v3/protection-policies":
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"id": "nas-policy-1"})
        return httpx.Response(404, json={"message": "unexpected"})

    options = {
        "policy_name": "NAS_DAILY",
        "data_domain_id": "dd-1",
        "data_domain_interface": None,
        "storage_unit_id": None,
        "data_consistency": "CRASH_CONSISTENT",
        "backup_level": "SYNTHETIC_FULL",
        "frequency": "DAILY",
        "interval": 1,
        "weekdays": ["SATURDAY"],
        "day_of_month": 1,
        "start_time": "22:00:00",
        "duration_hours": 8,
        "retention_interval": 30,
        "retention_unit": "DAY",
        "retention_lock": True,
        "encrypted": True,
        "nas_protection_engine_id": "engine-1",
    }
    with PPDMClient("ppdm", "admin", "secret", transport=httpx.MockTransport(handler)) as client:
        policy = client.create_nas_policy(options)

    assert policy["id"] == "nas-policy-1"
    assert captured["body"]["assetType"] == "NAS"
    assert captured["body"]["objectives"][0]["protectionEngineId"] == "engine-1"
