from typing import Any

import httpx

from app.services.base_client import ExternalAPIError, build_base_url, response_data


class PowerScaleClient:
    """OneFS PAPI client for NAS share discovery and reconciliation."""

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        port: int | None = None,
        verify_ssl: bool = True,
        api_version: str = "3",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_version = str(api_version)
        self.base_url = build_base_url(address, port, 8080)
        self.client = httpx.Client(
            base_url=self.base_url,
            auth=httpx.BasicAuth(username, password),
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
            "PowerScale",
            method,
            str(response.request.url),
            response.status_code,
            response_data(response),
        )

    def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None
    ) -> Any:
        response = self.client.request(method.upper(), path, params=params, json=json)
        self._raise(method.upper(), response)
        return response_data(response)

    def test_connection(self) -> dict[str, Any]:
        data = self.request("GET", "/platform/1/cluster/config")
        return {
            "ok": True,
            "system": "PowerScale",
            "name": data.get("name") if isinstance(data, dict) else None,
            "version": (
                data.get("onefs_version", {}).get("version") if isinstance(data, dict) else None
            ),
        }

    def _status_optional(self, path: str) -> Any:
        try:
            return self.request("GET", path)
        except ExternalAPIError as exc:
            if exc.status_code in {400, 404, 405, 501}:
                return {"available": False, "reason": str(exc)}
            raise

    def get_status(self) -> dict[str, Any]:
        cluster = self.request("GET", "/platform/1/cluster/config")
        metrics = {
            "cluster": cluster,
            "capacity": self._status_optional("/platform/1/cluster/statfs"),
            "system": self._status_optional(
                f"/platform/{self.api_version}/statistics/summary/system"
            ),
            "network": self._status_optional(
                f"/platform/{self.api_version}/statistics/summary/protocol"
            ),
            "drives": self._status_optional(
                f"/platform/{self.api_version}/statistics/summary/drive"
            ),
        }
        return {"state": "OK", "metrics": metrics, "error": None}

    def _collection(self, data: Any, key: str) -> list[dict[str, Any]]:
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
        return data if isinstance(data, list) else []

    def list_smb_shares(self) -> list[dict[str, Any]]:
        data = self.request(
            "GET", f"/platform/{self.api_version}/protocols/smb/shares", params={"limit": 1000}
        )
        return self._collection(data, "shares")

    def list_nfs_exports(self) -> list[dict[str, Any]]:
        data = self.request(
            "GET", f"/platform/{self.api_version}/protocols/nfs/exports", params={"limit": 1000}
        )
        return self._collection(data, "exports")

    def get_nas_options(self) -> dict[str, Any]:
        return {
            "smb_shares": self.list_smb_shares(),
            "nfs_exports": self.list_nfs_exports(),
            "access_zones": self._collection(
                self.request("GET", "/platform/1/zones", params={"limit": 1000}), "zones"
            ),
        }

    def get_share(self, share_id: str, protocol: str = "NFS") -> dict[str, Any]:
        endpoint = "smb/shares" if protocol.upper() == "SMB" else "nfs/exports"
        return self.request("GET", f"/platform/{self.api_version}/protocols/{endpoint}/{share_id}")

    def ensure_share(self, options: dict[str, Any]) -> dict[str, Any]:
        protocol = options.get("nas_protocol", "NFS").upper()
        path = options["nas_path"]
        name = options["name"]
        existing = self.list_smb_shares() if protocol == "SMB" else self.list_nfs_exports()
        for share in existing:
            paths = share.get("paths") or [share.get("path")]
            if share.get("name", "").casefold() == name.casefold() or path in paths:
                return {**share, "already_exists": True, "protocol": protocol}

        zone = options.get("nas_server_id") or options.get("raw_overrides", {}).get("zone")
        if protocol == "SMB":
            payload: dict[str, Any] = {"name": name, "path": path}
            if zone:
                payload["zone"] = zone
            endpoint = f"/platform/{self.api_version}/protocols/smb/shares"
        else:
            payload = {"name": name, "paths": [path]}
            if zone:
                payload["zone"] = zone
            endpoint = f"/platform/{self.api_version}/protocols/nfs/exports"
        payload.update(options.get("raw_overrides") or {})
        created = self.request("POST", endpoint, json=payload)
        if not isinstance(created, dict) or not (created.get("id") or created.get("name")):
            raise ExternalAPIError("PowerScale", "POST", endpoint, None, "Response has no share ID")
        return {**created, "already_exists": False, "protocol": protocol}

    def publish_share(
        self, share: dict[str, Any], options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Confirm that the OneFS share publication is visible by its resource ID."""
        options = options or share
        share_id = share.get("id") or share.get("name")
        if not share_id:
            raise ExternalAPIError("PowerScale", "GET", "/platform/share", None, "Share has no ID")
        published = self.get_share(str(share_id), options.get("nas_protocol", "NFS"))
        if not isinstance(published, dict):
            raise ExternalAPIError(
                "PowerScale", "GET", "/platform/share", None, "Share was not published"
            )
        return {**published, "published": True}
