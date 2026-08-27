import json

import httpx

from app.services.powerscale import PowerScaleClient


def test_powerscale_lists_and_reconciles_nfs_export():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/platform/3/protocols/smb/shares":
            return httpx.Response(200, json={"shares": []})
        if request.url.path == "/platform/3/protocols/nfs/exports":
            if request.method == "GET":
                return httpx.Response(200, json={"exports": []})
            body = json.loads(request.content)
            assert body["paths"] == ["/ifs/data/finance"]
            return httpx.Response(201, json={"id": "export-1", "name": "finance"})
        return httpx.Response(404, json={"message": "unexpected"})

    with PowerScaleClient(
        "powerscale", "api-user", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.ensure_share(
            {
                "name": "finance",
                "nas_path": "/ifs/data/finance",
                "nas_protocol": "NFS",
            }
        )

    assert result["id"] == "export-1"
    assert result["protocol"] == "NFS"
