import json

import httpx
import pytest

from app.services.cisco_mds import CiscoMDSClient


def nxapi_response(body, code="200"):
    return httpx.Response(
        200,
        json={"ins_api": {"outputs": {"output": {"code": code, "body": body}}}},
    )


def test_cisco_mds_creates_zone_zoneset_and_activates_it():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        command_type = payload["ins_api"]["type"]
        command = payload["ins_api"]["input"]
        captured["path"] = request.url.path
        captured["version"] = payload["ins_api"]["version"]
        if command_type == "cli_show_ascii":
            return nxapi_response("")
        assert command_type == "cli_conf"
        captured["command"] = command
        return nxapi_response("configuration complete")

    with CiscoMDSClient(
        "mds", "api-user", "secret", port=8443, transport=httpx.MockTransport(handler)
    ) as client:
        result = client.ensure_zoning(
            "Z_APP_HOST1",
            10,
            "SANFLOW_CFG",
            ["10:00:00:90:fa:12:34:56"],
            ["50:00:00:90:fa:65:43:21"],
        )

    assert result["changed"] is True
    assert captured["path"] == "/ins"
    assert captured["version"] == "1.2"
    assert "zone name Z_APP_HOST1 vsan 10" in captured["command"]
    assert "member pwwn 10:00:00:90:fa:12:34:56" in captured["command"]
    assert "member pwwn 50:00:00:90:fa:65:43:21" in captured["command"]
    assert "zoneset name SANFLOW_CFG vsan 10" in captured["command"]
    assert "zoneset activate name SANFLOW_CFG vsan 10" in captured["command"]


def test_cisco_mds_reuses_an_already_active_zone():
    config_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal config_calls
        payload = json.loads(request.content)
        command_type = payload["ins_api"]["type"]
        command = payload["ins_api"]["input"]
        if command_type == "cli_conf":
            config_calls += 1
            return nxapi_response("unexpected configuration")
        if command == "show zone vsan 10":
            body = (
                "zone name Z_APP_HOST1 vsan 10\n"
                "  pwwn 10:00:00:90:fa:12:34:56\n"
                "  pwwn 50:00:00:90:fa:65:43:21\n"
            )
        elif command == "show zoneset brief vsan 10":
            body = "zoneset name SANFLOW_CFG vsan 10\n  zone Z_APP_HOST1\n"
        else:
            body = "zoneset name SANFLOW_CFG vsan 10\n  zone Z_APP_HOST1\n"
        return nxapi_response(body)

    with CiscoMDSClient(
        "mds", "api-user", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.ensure_zoning(
            "Z_APP_HOST1",
            10,
            "SANFLOW_CFG",
            ["10:00:00:90:fa:12:34:56"],
            ["50:00:00:90:fa:65:43:21"],
        )

    assert result["changed"] is False
    assert config_calls == 0


def test_cisco_mds_rejects_peer_zoning():
    with CiscoMDSClient("mds", "api-user", "secret") as client:
        with pytest.raises(ValueError, match="peer zoning"):
            client.ensure_zoning(
                "Z_APP_HOST1",
                10,
                "SANFLOW_CFG",
                ["10:00:00:90:fa:12:34:56"],
                ["50:00:00:90:fa:65:43:21"],
                peer_zoning=True,
            )
