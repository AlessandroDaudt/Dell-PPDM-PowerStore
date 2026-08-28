from typing import Any

import httpx

from app.services.base_client import ExternalAPIError, build_base_url, response_data


class UnityClient:
    """Dell Unity Unisphere REST client for CIFS and NFS share operations."""

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        port: int | None = None,
        verify_ssl: bool = True,
        api_version: str = "5.2",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_version = str(api_version)
        self.base_url = build_base_url(address, port, 443)
        self._csrf_token: str | None = None
        self.client = httpx.Client(
            base_url=self.base_url,
            auth=httpx.BasicAuth(username, password),
            verify=verify_ssl,
            timeout=httpx.Timeout(60.0, connect=15.0),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-EMC-REST-CLIENT": "true",
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
            "Dell Unity",
            method,
            str(response.request.url),
            response.status_code,
            response_data(response),
        )

    def _bootstrap_session(self) -> dict[str, Any]:
        response = self.client.get("/api/types/basicSystemInfo/instances?compact=true")
        self._raise("GET", response)
        self._csrf_token = response.headers.get("EMC-CSRF-TOKEN") or response.headers.get(
            "emc-csrf-token"
        )
        data = response_data(response)
        entries = self._entries(data)
        return entries[0] if entries else (data if isinstance(data, dict) else {})

    def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None
    ) -> Any:
        method = method.upper()
        headers: dict[str, str] = {}
        if method in {"POST", "PUT", "DELETE", "PATCH"}:
            if not self._csrf_token:
                self._bootstrap_session()
            if self._csrf_token:
                headers["EMC-CSRF-TOKEN"] = self._csrf_token
        response = self.client.request(method, path, params=params, json=json, headers=headers)
        self._raise(method, response)
        return response_data(response)

    @staticmethod
    def _entries(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            entries = data["entries"]
        elif isinstance(data, list):
            entries = data
        else:
            entries = []
        result: list[dict[str, Any]] = []
        for entry in entries:
            if isinstance(entry, dict):
                content = entry.get("content", entry)
                if isinstance(content, dict):
                    result.append(content)
        return result

    def test_connection(self) -> dict[str, Any]:
        info = self._bootstrap_session()
        return {"ok": True, "system": "Dell Unity", "name": info.get("name"), "id": info.get("id")}

    def _status_optional(self, resource: str) -> Any:
        try:
            return self._list(resource)
        except ExternalAPIError as exc:
            if exc.status_code in {400, 404, 405, 501}:
                return {"available": False, "reason": str(exc)}
            raise

    def get_status(self) -> dict[str, Any]:
        system = self._bootstrap_session()
        metrics = {
            "system": system,
            "capacity": self._status_optional("systemCapacity"),
            "disks": self._status_optional("disk"),
            "storage_resources": self._status_optional("storageResource"),
            "filesystems": self._status_optional("filesystem"),
            "network": self._status_optional("mgmtInterface"),
        }
        return {"state": "OK", "metrics": metrics, "error": None}

    def _list(self, resource: str) -> list[dict[str, Any]]:
        return self._entries(self.request("GET", f"/api/types/{resource}/instances?compact=true"))

    def get_nas_options(self) -> dict[str, Any]:
        return {
            "nas_servers": self._list("nasServer"),
            "file_systems": self._list("filesystem"),
            "cifs_shares": self._list("cifsShare"),
            "nfs_shares": self._list("nfsShare"),
        }

    def get_share(self, share_id: str, protocol: str = "NFS") -> dict[str, Any]:
        resource = "cifsShare" if protocol.upper() == "SMB" else "nfsShare"
        data = self.request("GET", f"/api/instances/{resource}/{share_id}")
        entries = self._entries(data)
        return entries[0] if entries else (data if isinstance(data, dict) else {})

    def ensure_share(self, options: dict[str, Any]) -> dict[str, Any]:
        protocol = options.get("nas_protocol", "NFS").upper()
        resource = "cifsShare" if protocol == "SMB" else "nfsShare"
        path = options["nas_path"]
        name = options["name"]
        for share in self._list(resource):
            if share.get("name", "").casefold() == name.casefold() or share.get("path") == path:
                return {**share, "already_exists": True, "protocol": protocol}

        payload: dict[str, Any] = {"name": name, "path": path}
        if options.get("nas_file_system_id"):
            payload["filesystem"] = {"id": options["nas_file_system_id"]}
        if options.get("nas_server_id"):
            payload["nasServer"] = {"id": options["nas_server_id"]}
        payload.update(options.get("raw_overrides") or {})
        endpoint = f"/api/types/{resource}/instances"
        created = self.request("POST", endpoint, json=payload)
        entries = self._entries(created)
        result = entries[0] if entries else (created if isinstance(created, dict) else {})
        if not result.get("id"):
            raise ExternalAPIError("Dell Unity", "POST", endpoint, None, "Response has no share ID")
        return {**result, "already_exists": False, "protocol": protocol}

    def publish_share(
        self, share: dict[str, Any], options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Confirm that the created or reused share is published by Unity."""
        options = options or share
        share_id = share.get("id")
        if not share_id:
            raise ExternalAPIError(
                "Dell Unity",
                "GET",
                "/api/instances/{share}/",
                None,
                "Share has no ID for publication",
            )
        protocol = options.get("nas_protocol", share.get("protocol", "NFS"))
        published = self.get_share(str(share_id), protocol)
        if not published.get("id"):
            raise ExternalAPIError(
                "Dell Unity",
                "GET",
                f"/api/instances/{{share}}/{share_id}",
                None,
                "Share not found after creation",
            )
        return {**published, "published": True, "protocol": protocol.upper()}
