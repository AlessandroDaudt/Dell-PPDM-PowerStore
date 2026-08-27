from typing import Any

import httpx

from app.services.base_client import ExternalAPIError, build_base_url, response_data


class DataDomainClient:
    """Embedded Data Domain REST client used by the status collector."""

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        port: int | None = None,
        verify_ssl: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = f"{build_base_url(address, port, 3009)}/rest/v1.0"
        self.username = username
        self.password = password
        self.token: str | None = None
        self.client = httpx.Client(
            base_url=self.base_url,
            verify=verify_ssl,
            timeout=httpx.Timeout(60.0, connect=15.0),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
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
            "Data Domain",
            method,
            str(response.request.url),
            response.status_code,
            response_data(response),
        )

    def login(self) -> str:
        response = self.client.post(
            "/auth", json={"username": self.username, "password": self.password}
        )
        self._raise("POST", response)
        token = response.headers.get("X-DD-AUTH-TOKEN")
        if not token:
            data = response_data(response)
            if isinstance(data, dict):
                token = data.get("token") or data.get("auth_token")
        if not token:
            raise ExternalAPIError("Data Domain", "POST", "/auth", None, "token ausente")
        self.token = str(token)
        return self.token

    def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None
    ) -> Any:
        if not self.token:
            self.login()
        headers = {"X-DD-AUTH-TOKEN": self.token or ""}
        response = self.client.request(
            method.upper(), path, params=params, json=json, headers=headers
        )
        if response.status_code == 401:
            self.login()
            response = self.client.request(
                method.upper(),
                path,
                params=params,
                json=json,
                headers={"X-DD-AUTH-TOKEN": self.token or ""},
            )
        self._raise(method.upper(), response)
        return response_data(response)

    def test_connection(self) -> dict[str, Any]:
        system = self.request("GET", "/system")
        return {"ok": True, "system": "Data Domain", "details": system}

    def _status_optional(self, path: str) -> Any:
        try:
            return self.request("GET", path)
        except ExternalAPIError as exc:
            if exc.status_code in {400, 404, 405, 501}:
                return {"available": False, "reason": str(exc)}
            raise

    def get_status(self) -> dict[str, Any]:
        system = self.request("GET", "/system")
        network = {
            "available": False,
            "reason": "métrica de rede não exposta pela API REST do equipamento",
        }
        for path in (
            "/dd-systems/0/stats/network",
            "/dd-systems/0/stats/throughput",
            "/dd-systems/0/stats/performance",
        ):
            candidate = self._status_optional(path)
            if not (isinstance(candidate, dict) and candidate.get("available") is False):
                network = candidate
                break
        metrics = {
            "system": system,
            "capacity": self._status_optional("/dd-systems/0/stats/capacity"),
            "file_systems": self._status_optional("/dd-systems/0/stats/file-systems"),
            "mtrees": self._status_optional("/dd-systems/0/mtrees"),
            "network": network,
        }
        return {"state": "OK", "metrics": metrics, "error": None}
