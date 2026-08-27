import httpx

from app.services.powerstore import PowerStoreClient


def test_powerstore_create_host_map_and_csrf_token():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/rest/cluster":
            return httpx.Response(
                200,
                json=[{"id": "cluster-1", "name": "PS-PRD"}],
                headers={"DELL-EMC-TOKEN": "csrf-1"},
            )
        if request.url.path == "/api/rest/volume" and request.method == "POST":
            assert request.headers["DELL-EMC-TOKEN"] == "csrf-1"
            return httpx.Response(201, json={"id": "volume-1"})
        if request.url.path == "/api/rest/volume/volume-1":
            return httpx.Response(200, json={"id": "volume-1", "name": "VOL_1", "wwn": "naa.1"})
        if request.url.path == "/api/rest/host" and request.method == "GET":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/rest/host" and request.method == "POST":
            return httpx.Response(201, json={"id": "host-1"})
        if request.url.path == "/api/rest/host_volume_mapping" and request.method == "GET":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/rest/host/host-1/attach" and request.method == "POST":
            return httpx.Response(204)
        return httpx.Response(404, json={"message": "unexpected"})

    with PowerStoreClient(
        "powerstore.local",
        "api-user",
        "secret",
        transport=httpx.MockTransport(handler),
    ) as client:
        created = client.create_volume({"name": "VOL_1", "size_gib": 100, "description": "test"})
        volume = client.get_volume(created["id"])
        host = client.ensure_host("host-01", "Linux", ["10:00:00:90:fa:12:34:56"])
        mapping = client.map_volume(host["id"], volume["id"], 7)

    assert volume["wwn"] == "naa.1"
    assert mapping["created"] is True
    assert mapping["logical_unit_number"] == 7
    assert len([request for request in requests if request.url.path == "/api/rest/cluster"]) == 1


def test_powerstore_reuses_existing_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/rest/host_volume_mapping":
            return httpx.Response(
                200, json=[{"id": "mapping-1", "host_id": "h1", "volume_id": "v1"}]
            )
        return httpx.Response(404)

    with PowerStoreClient("ps", "u", "p", transport=httpx.MockTransport(handler)) as client:
        result = client.map_volume("h1", "v1")
    assert result["already_exists"] is True
