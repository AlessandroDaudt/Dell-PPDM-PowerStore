from typing import Any

import httpx

from app.services.base_client import ExternalAPIError, build_base_url, response_data


class BrocadeClient:
    """Fabric OS REST client for switch and Fibre Channel port telemetry."""

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        port: int | None = None,
        verify_ssl: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = build_base_url(address, port, 443)
        self.client = httpx.Client(
            base_url=self.base_url,
            auth=httpx.BasicAuth(username, password),
            verify=verify_ssl,
            timeout=httpx.Timeout(60.0, connect=15.0),
            headers={
                "Accept": "application/yang-data+json, application/json",
                "Content-Type": "application/yang-data+json",
            },
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self) -> None:
        self.client.close()

    def _raise(self, method: str, response: httpx.Response) -> None:
        if response.is_success:
            return
        raise ExternalAPIError(
            "Brocade",
            method,
            str(response.request.url),
            response.status_code,
            response_data(response),
        )

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> Any:
        method = method.upper()
        response = self.client.request(method, path, params=params)
        self._raise(method, response)
        return response_data(response)

    @staticmethod
    def _items(data: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
        for value in data.values():
            nested = BrocadeClient._items(value, keys)
            if nested:
                return nested
        return []

    def test_connection(self) -> dict[str, Any]:
        data = self.request("GET", "/rest/running/brocade-interface/fibrechannel/")
        return {
            "ok": True,
            "system": "Brocade",
            "ports": len(self._items(data, ("fibrechannel", "interface"))),
        }

    def get_status(self) -> dict[str, Any]:
        interfaces = self.request("GET", "/rest/running/brocade-interface/fibrechannel/")
        try:
            statistics = self.request(
                "GET", "/rest/running/brocade-interface/fibrechannel-statistics/"
            )
        except ExternalAPIError as exc:
            if exc.status_code in {400, 404, 405, 501}:
                statistics = {"available": False, "reason": str(exc)}
            else:
                raise
        ports = self._items(interfaces, ("fibrechannel", "interface"))
        stats = self._items(statistics, ("fibrechannel-statistics", "statistics", "interface"))
        stats_by_name = {
            str(item.get("name") or item.get("port_name") or item.get("portName")): item
            for item in stats
            if item.get("name") or item.get("port_name") or item.get("portName")
        }
        normalized_ports = []
        for port in ports:
            name = str(port.get("name") or port.get("port_name") or port.get("portName") or "")
            normalized_ports.append({**port, "statistics": stats_by_name.get(name, {})})
        return {
            "state": "OK",
            "metrics": {
                "ports": normalized_ports,
                "interfaces": interfaces,
                "statistics": statistics,
            },
            "error": None,
        }
