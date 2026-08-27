from typing import Any

from app.services.base_client import ExternalAPIError
from app.services.powerstore import PowerStoreClient


class PowerStoreNASClient(PowerStoreClient):
    """PowerStore file-services client for NAS discovery and reconciliation."""

    def _list_optional(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        try:
            data = self.request("GET", path, params=params)
        except ExternalAPIError as exc:
            if exc.status_code == 404:
                return []
            raise
        return data if isinstance(data, list) else []

    def get_nas_options(self) -> dict[str, Any]:
        self._bootstrap_session()
        return {
            "nas_servers": self._list_optional(
                "/api/rest/nas_server", {"select": "id,name,nas_server_type"}
            ),
            "file_systems": self._list_optional(
                "/api/rest/file_system", {"select": "id,name,size,nas_server_id"}
            ),
            "smb_shares": self._list_optional(
                "/api/rest/smb_share", {"select": "id,name,path,file_system_id,nas_server_id"}
            ),
            "nfs_exports": self._list_optional(
                "/api/rest/nfs_export", {"select": "id,name,path,file_system_id,nas_server_id"}
            ),
        }

    def get_file_system(self, file_system_id: str) -> dict[str, Any]:
        data = self.request("GET", f"/api/rest/file_system/{file_system_id}")
        return data if isinstance(data, dict) else {}

    def get_share(self, share_id: str, protocol: str = "NFS") -> dict[str, Any]:
        endpoint = "smb_share" if protocol.upper() == "SMB" else "nfs_export"
        data = self.request("GET", f"/api/rest/{endpoint}/{share_id}")
        return data if isinstance(data, dict) else {}

    def ensure_file_system(self, options: dict[str, Any]) -> dict[str, Any]:
        file_systems = self._list_optional("/api/rest/file_system", {"select": "id,name,size"})
        for item in file_systems:
            if str(item.get("name", "")).casefold() == str(options["name"]).casefold():
                return {**item, "already_exists": True}
        payload: dict[str, Any] = {
            "name": options["name"],
            "size": int(options["size_gib"]) * 1024**3,
        }
        if options.get("nas_server_id"):
            payload["nas_server_id"] = options["nas_server_id"]
        payload.update(options.get("raw_overrides") or {})
        created = self.request("POST", "/api/rest/file_system", json=payload)
        if not isinstance(created, dict) or not created.get("id"):
            raise ExternalAPIError("PowerStore NAS", "POST", "/api/rest/file_system", None, "resposta sem id do file system")
        return {**created, "already_exists": False}

    def ensure_share(self, options: dict[str, Any]) -> dict[str, Any]:
        protocol = options.get("nas_protocol", "NFS").upper()
        endpoint = "smb_share" if protocol == "SMB" else "nfs_export"
        shares = self._list_optional(
            f"/api/rest/{endpoint}", {"select": "id,name,path,file_system_id,nas_server_id"}
        )
        path = options["nas_path"]
        for item in shares:
            if str(item.get("path", "")) == path or (
                str(item.get("name", "")).casefold() == options["name"].casefold()
            ):
                return {**item, "already_exists": True, "protocol": protocol}

        file_system = None
        if options.get("resource_type") == "NAS_DATA":
            file_system = self.ensure_file_system(options)
        payload: dict[str, Any] = {
            "name": options["name"],
            "path": path,
        }
        file_system_id = options.get("nas_file_system_id") or (file_system or {}).get("id")
        if file_system_id:
            payload["file_system_id"] = file_system_id
        if options.get("nas_server_id"):
            payload["nas_server_id"] = options["nas_server_id"]
        payload.update(options.get("raw_overrides") or {})
        created = self.request("POST", f"/api/rest/{endpoint}", json=payload)
        if not isinstance(created, dict) or not created.get("id"):
            raise ExternalAPIError("PowerStore NAS", "POST", f"/api/rest/{endpoint}", None, "resposta sem id do share")
        return {**created, "already_exists": False, "protocol": protocol, "file_system": file_system}
