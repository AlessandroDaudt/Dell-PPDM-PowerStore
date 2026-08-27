import json

import httpx

from app.services.powerstore_nas import PowerStoreNASClient


def test_powerstore_nas_reconciles_file_system_and_smb_share():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/rest/cluster":
            return httpx.Response(200, json=[{"id": "cluster-1"}], headers={"DELL-EMC-TOKEN": "csrf-1"})
        if request.url.path == "/api/rest/smb_share" and request.method == "GET":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/rest/file_system" and request.method == "GET":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/rest/file_system" and request.method == "POST":
            body = json.loads(request.content)
            assert body["size"] == 50 * 1024**3
            return httpx.Response(201, json={"id": "fs-1", "name": "FINANCE"})
        if request.url.path == "/api/rest/smb_share" and request.method == "POST":
            body = json.loads(request.content)
            assert body["file_system_id"] == "fs-1"
            return httpx.Response(201, json={"id": "share-1", "name": "FINANCE", "path": "/finance"})
        return httpx.Response(404, json={"message": "unexpected"})

    with PowerStoreNASClient("ps", "u", "p", transport=httpx.MockTransport(handler)) as client:
        result = client.ensure_share(
            {
                "resource_type": "NAS_DATA",
                "name": "FINANCE",
                "size_gib": 50,
                "nas_path": "/finance",
                "nas_protocol": "SMB",
            }
        )

    assert result["id"] == "share-1"
    assert result["file_system"]["id"] == "fs-1"
