import json

import httpx

from app.services.ppdm import PPDMClient, deep_merge


def test_ppdm_options_are_loaded_from_live_endpoints():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/login":
            return httpx.Response(200, json={"access_token": "token-1"})
        assert request.headers["Authorization"] == "Bearer token-1"
        if request.url.path == "/api/v2/nodes":
            return httpx.Response(200, json={"content": [{"version": "19.22.0"}]})
        if request.url.path == "/api/v2/storage-systems":
            return httpx.Response(200, json={"content": [{"id": "dd1", "name": "DD-PRD"}]})
        if request.url.path == "/api/v3/protection-policies":
            return httpx.Response(200, json={"content": [{"id": "p1", "name": "DAILY"}]})
        if request.url.path == "/api/v2/datadomain-mtrees":
            return httpx.Response(200, json={"content": [{"id": "su1", "name": "SU-01"}]})
        return httpx.Response(404, json={"message": "unexpected"})

    with PPDMClient("ppdm", "admin", "secret", transport=httpx.MockTransport(handler)) as client:
        options = client.get_options()

    assert options["policy_api"] == "v3"
    assert options["data_domains"][0]["name"] == "DD-PRD"
    assert options["policies"][0]["id"] == "p1"


def test_ppdm_assigns_powerstore_volume_to_policy():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/login":
            return httpx.Response(200, json={"access_token": "token-1"})
        if request.url.path == "/api/v2/assets":
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "id": "asset-1",
                            "name": "VOL_1",
                            "type": "POWERSTORE_BLOCK",
                            "subtype": "POWERSTORE_VOLUME",
                        }
                    ]
                },
            )
        if request.url.path.endswith("/asset-assignments"):
            captured["body"] = json.loads(request.content)
            return httpx.Response(204)
        return httpx.Response(404)

    with PPDMClient("ppdm", "admin", "secret", transport=httpx.MockTransport(handler)) as client:
        asset = client.find_powerstore_asset("VOL_1")
        client.assign_asset("policy-1", asset["id"])

    assert captured["body"] == ["asset-1"]


def test_deep_merge_preserves_nested_defaults():
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}}) == {"a": {"b": 3, "c": 2}}


def test_v3_policy_uses_retention_lock_and_appends_objectives():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/login":
            return httpx.Response(200, json={"access_token": "token-1"})
        if request.url.path == "/api/v2/nodes":
            return httpx.Response(200, json={"content": [{"version": "19.22.0"}]})
        if request.url.path == "/api/v3/protection-policies":
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"id": "policy-1"})
        return httpx.Response(404)

    options = {
        "policy_name": "POL-1",
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
        "raw_overrides": {
            "additional_objectives": [{"id": "replica-1", "type": "REPLICATION"}]
        },
    }
    with PPDMClient(
        "ppdm", "admin", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        client.create_powerstore_policy(options)

    body = captured["body"]
    retention_type = body["objectives"][0]["retentions"][0]["time"][0]["type"]
    assert retention_type == "RETENTION_AND_LOCK"
    assert body["objectives"][1]["type"] == "REPLICATION"
