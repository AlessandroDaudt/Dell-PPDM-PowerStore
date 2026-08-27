import copy
from typing import Any

import httpx

from app.services.base_client import ExternalAPIError, build_base_url, response_data


class PowerMaxClient:
    """Unisphere for PowerMax REST client for native storage-group provisioning."""

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        port: int | None = None,
        verify_ssl: bool = True,
        api_version: str = "100",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        root = build_base_url(address, port, 8443)
        self.api_version = str(api_version).removeprefix("v")
        self.base_url = f"{root}/univmax/restapi/{self.api_version}"
        self.symmetrix_id: str | None = None
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
            "PowerMax",
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

    def get_version(self) -> dict[str, Any]:
        # /version is unversioned in the Unisphere REST API.
        data = self.client.get("/univmax/restapi/version")
        self._raise("GET", data)
        value = response_data(data)
        return value if isinstance(value, dict) else {"version": value}

    def test_connection(self) -> dict[str, Any]:
        version = self.get_version()
        return {"ok": True, "system": "PowerMax", **version}

    def _array_path(self, suffix: str) -> str:
        if not self.symmetrix_id:
            raise ValueError("symmetrix_id é obrigatório para operações PowerMax")
        return f"/sloprovisioning/symmetrix/{self.symmetrix_id}/{suffix.lstrip('/')}"

    def get_options(self, symmetrix_id: str) -> dict[str, Any]:
        self.symmetrix_id = symmetrix_id
        groups = self.get_storage_groups()
        return {
            "api_version": self.api_version,
            "symmetrix_id": symmetrix_id,
            "storage_groups": groups,
        }

    def get_storage_groups(self) -> list[dict[str, Any]]:
        data = self.request("GET", self._array_path("storagegroup"))
        if isinstance(data, dict):
            names = data.get("storageGroupId") or data.get("storageGroupIds") or []
            if isinstance(names, list):
                return [{"id": str(name), "name": str(name)} for name in names]
        return data if isinstance(data, list) else []

    def get_storage_group(self, group_id: str) -> dict[str, Any]:
        data = self.request("GET", self._array_path(f"storagegroup/{group_id}"))
        if isinstance(data, dict):
            return data
        return {"id": group_id, "name": group_id, "data": data}

    @staticmethod
    def _require_id(data: Any, path: str) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {"id": path.rsplit("/", 1)[-1], "data": data}
        group_id = data.get("id") or data.get("storageGroupId") or data.get("storageGroupName")
        if group_id:
            return {**data, "id": str(group_id)}
        raise ExternalAPIError("PowerMax", "POST", path, None, "resposta sem id do storage group")

    def build_storage_group_payload(self, options: dict[str, Any]) -> dict[str, Any]:
        name = options["name"]
        volume_size = options["size_gib"]
        volume_count = options.get("volume_count", 1)
        prefix = options.get("volume_prefix") or name
        payload: dict[str, Any] = {
            "executionOption": "SYNCHRONOUS",
            "storageGroupId": name,
            "srpId": options.get("srp_id"),
            "emulation": options.get("emulation", "FBA"),
            "sloBasedStorageGroupParam": [
                {
                    "sloId": options.get("slo_id"),
                    "volumeAttributes": [
                        {
                            "num_of_vols": volume_count,
                            "volume_size": str(volume_size),
                            "capacityUnit": "GB",
                            "volumeIdentifier": {
                                "volumeIdentifierChoice": "identifier_name",
                                "identifier_name": prefix,
                            },
                        }
                    ],
                }
            ],
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        return _deep_merge(payload, copy.deepcopy(options.get("raw_overrides") or {}))

    def ensure_storage_group(self, options: dict[str, Any]) -> dict[str, Any]:
        if not self.symmetrix_id:
            raise ValueError("symmetrix_id é obrigatório para operações PowerMax")
        existing = next(
            (item for item in self.get_storage_groups() if item.get("name") == options["name"]),
            None,
        )
        if existing:
            group = self.get_storage_group(str(existing.get("id") or existing["name"]))
            return {
                **group,
                "id": str(group.get("id") or existing.get("id") or options["name"]),
                "already_exists": True,
            }
        path = self._array_path("storagegroup")
        created = self.request("POST", path, json=self.build_storage_group_payload(options))
        return {**self._require_id(created, path), "already_exists": False}


def _deep_merge(target: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key] = _deep_merge(target[key], value)
        else:
            target[key] = value
    return target
