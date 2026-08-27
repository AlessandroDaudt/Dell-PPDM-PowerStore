import json

import httpx

from app.services.unity import UnityClient


def test_unity_reconciles_existing_cifs_share_and_uses_csrf_for_creation():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/types/basicSystemInfo/instances":
            return httpx.Response(
                200,
                json={"entries": [{"content": {"id": "system-1", "name": "UNITY-1"}}]},
                headers={"EMC-CSRF-TOKEN": "csrf-1"},
            )
        if request.url.path == "/api/types/cifsShare/instances":
            if request.method == "GET":
                return httpx.Response(200, json={"entries": []})
            assert request.headers["EMC-CSRF-TOKEN"] == "csrf-1"
            body = json.loads(request.content)
            assert body["filesystem"]["id"] == "fs-1"
            return httpx.Response(201, json={"entries": [{"content": {"id": "share-1"}}]})
        if request.url.path == "/api/instances/cifsShare/share-1":
            return httpx.Response(
                200, json={"id": "share-1", "name": "finance", "path": "/finance"}
            )
        return httpx.Response(404, json={"message": "unexpected"})

    with UnityClient(
        "unity", "api-user", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.ensure_share(
            {
                "name": "finance",
                "nas_path": "/finance",
                "nas_protocol": "SMB",
                "nas_file_system_id": "fs-1",
            }
        )

    assert result["id"] == "share-1"
    assert result["protocol"] == "SMB"
    assert [request.url.path for request in requests].count(
        "/api/types/basicSystemInfo/instances"
    ) == 1


def test_unity_publish_share_verifies_the_share_instance():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/instances/nfsShare/share-9":
            return httpx.Response(200, json={"id": "share-9", "name": "backup", "path": "/backup"})
        return httpx.Response(404, json={"message": "unexpected"})

    with UnityClient(
        "unity", "api-user", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.publish_share({"id": "share-9", "protocol": "NFS"}, {"nas_protocol": "NFS"})

    assert result["id"] == "share-9"
    assert result["published"] is True
