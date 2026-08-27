import json

import httpx

from app.services.powermax import PowerMaxClient


def test_powermax_creates_native_storage_group_and_reuses_existing_group():
    calls = []
    list_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/univmax/restapi/100/sloprovisioning/symmetrix/SYM-1/storagegroup":
            if request.method == "GET":
                nonlocal list_calls
                list_calls += 1
                return httpx.Response(
                    200, json={"storageGroupId": [] if list_calls == 1 else ["APP_SG"]}
                )
            body = json.loads(request.content)
            assert body["storageGroupId"] == "APP_SG"
            assert body["sloBasedStorageGroupParam"][0]["volumeAttributes"][0]["num_of_vols"] == 2
            return httpx.Response(201, json={"storageGroupId": "APP_SG"})
        if request.url.path == (
            "/univmax/restapi/100/sloprovisioning/symmetrix/SYM-1/storagegroup/APP_SG"
        ):
            return httpx.Response(200, json={"storageGroupId": "APP_SG", "name": "APP_SG"})
        return httpx.Response(404, json={"message": "unexpected"})

    with PowerMaxClient(
        "powermax.local",
        "api-user",
        "secret",
        api_version="100",
        transport=httpx.MockTransport(handler),
    ) as client:
        client.symmetrix_id = "SYM-1"
        created = client.ensure_storage_group(
            {
                "name": "APP_SG",
                "size_gib": 100,
                "volume_count": 2,
                "srp_id": "SRP_1",
                "slo_id": "Diamond",
            }
        )
        reused = client.ensure_storage_group(
            {"name": "APP_SG", "size_gib": 100, "volume_count": 2}
        )

    assert created["id"] == "APP_SG"
    assert created["already_exists"] is False
    assert reused["already_exists"] is True
    assert len([item for item in calls if item.method == "POST"]) == 1
