import httpx

from app.services.brocade import BrocadeClient
from app.services.cisco_mds import CiscoMDSClient
from app.services.datadomain import DataDomainClient


def test_datadomain_status_authenticates_and_collects_capacity_and_network():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/rest/v1.0/auth":
            return httpx.Response(200, headers={"X-DD-AUTH-TOKEN": "dd-token"})
        assert request.headers["X-DD-AUTH-TOKEN"] == "dd-token"
        if request.url.path == "/rest/v1.0/system":
            return httpx.Response(200, json={"name": "DD-01"})
        if request.url.path.endswith("/stats/capacity"):
            return httpx.Response(200, json={"used_bytes": 123})
        if request.url.path.endswith("/stats/network"):
            return httpx.Response(404)
        if request.url.path.endswith("/stats/throughput"):
            return httpx.Response(200, json={"read_bytes": 456})
        if request.url.path.endswith("/stats/file-systems"):
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/mtrees"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    with DataDomainClient(
        "dd", "api-user", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.get_status()

    assert result["state"] == "OK"
    assert result["metrics"]["capacity"]["used_bytes"] == 123
    assert result["metrics"]["network"]["read_bytes"] == 456
    assert [request.url.path for request in calls].count("/rest/v1.0/auth") == 1


def test_brocade_status_merges_interface_and_statistics():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/fibrechannel/"):
            return httpx.Response(
                200,
                json={"fibrechannel": [{"name": "0/1", "operational-status": "online"}]},
            )
        if request.url.path.endswith("/fibrechannel-statistics/"):
            return httpx.Response(
                200,
                json={"fibrechannel-statistics": [{"name": "0/1", "rx_error_frames": 2}]},
            )
        return httpx.Response(404)

    with BrocadeClient(
        "brocade", "api-user", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.get_status()

    assert result["metrics"]["ports"][0]["name"] == "0/1"
    assert result["metrics"]["ports"][0]["statistics"]["rx_error_frames"] == 2


def test_cisco_mds_status_keeps_raw_commands_and_parses_port_counters():
    def handler(request: httpx.Request) -> httpx.Response:
        command = request.read().decode()
        if "interface counters detailed" in command:
            body = "fc1/1 is up\n  rx_error_frames: 3\n  tx_b2b_credit_remain: 12\n"
        elif "interface brief" in command:
            body = "fc1/1 is up\n"
        else:
            body = "ok"
        return httpx.Response(
            200,
            json={"ins_api": {"outputs": {"output": {"code": "200", "body": body}}}},
        )

    with CiscoMDSClient(
        "mds", "api-user", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.get_status()

    port = result["metrics"]["ports"][0]
    assert port["name"] == "fc1/1"
    assert port["rx_error_frames"] == "3"
    assert port["tx_b2b_credit_remain"] == "12"
    assert "transceiver" in result["metrics"]["raw"]
