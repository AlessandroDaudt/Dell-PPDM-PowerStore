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
            raise ValueError("symmetrix_id is required for PowerMax operations")
        return f"/sloprovisioning/symmetrix/{self.symmetrix_id}/{suffix.lstrip('/')}"

    def get_options(self, symmetrix_id: str) -> dict[str, Any]:
        self.symmetrix_id = symmetrix_id
        groups = self.get_storage_groups()
        return {
            "api_version": self.api_version,
            "symmetrix_id": symmetrix_id,
            "storage_groups": groups,
            "hosts": self.get_hosts(),
            "port_groups": self.get_port_groups(),
            "masking_views": self.get_masking_views(),
        }

    @staticmethod
    def _named_items(data: Any, key: str) -> list[dict[str, Any]]:
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return [{"id": str(value), "name": str(value)} for value in data[key]]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def get_hosts(self) -> list[dict[str, Any]]:
        return self._named_items(self.request("GET", self._array_path("host")), "hostId")

    def get_port_groups(self) -> list[dict[str, Any]]:
        return self._named_items(self.request("GET", self._array_path("portgroup")), "portGroupId")

    def get_masking_views(self) -> list[dict[str, Any]]:
        data = self.request("GET", self._array_path("maskingview"))
        if isinstance(data, dict) and isinstance(data.get("maskingView"), list):
            return [
                {**item, "id": str(item.get("maskingViewId") or item.get("id"))}
                for item in data["maskingView"]
                if isinstance(item, dict) and (item.get("maskingViewId") or item.get("id"))
            ]
        return self._named_items(data, "maskingViewId")

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

    def get_masking_view(self, masking_view_id: str) -> dict[str, Any]:
        data = self.request("GET", self._array_path(f"maskingview/{masking_view_id}"))
        return data if isinstance(data, dict) else {"id": masking_view_id, "data": data}

    @staticmethod
    def _require_id(data: Any, path: str) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {"id": path.rsplit("/", 1)[-1], "data": data}
        group_id = data.get("id") or data.get("storageGroupId") or data.get("storageGroupName")
        if group_id:
            return {**data, "id": str(group_id)}
        raise ExternalAPIError(
            "PowerMax", "POST", path, None, "response did not include a storage group ID"
        )

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
        overrides = copy.deepcopy(options.get("raw_overrides") or {})
        overrides.pop("masking_view", None)
        return _deep_merge(payload, overrides)

    def ensure_storage_group(self, options: dict[str, Any]) -> dict[str, Any]:
        if not self.symmetrix_id:
            raise ValueError("symmetrix_id is required for PowerMax operations")
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

    def build_masking_view_payload(
        self,
        masking_view_id: str,
        storage_group_id: str,
        host_id: str,
        port_group_id: str,
        initiator_wwns: list[str],
        host_exists: bool,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        host_selection = (
            {"useExistingHostParam": {"hostId": host_id}}
            if host_exists
            else {"createHostParam": {"hostId": host_id, "initiatorId": initiator_wwns}}
        )
        payload: dict[str, Any] = {
            "executionOption": "SYNCHRONOUS",
            "maskingViewId": masking_view_id,
            "portGroupSelection": {"useExistingPortGroupParam": {"portGroupId": port_group_id}},
            "hostOrHostGroupSelection": host_selection,
            "storageGroupSelection": {
                "useExistingStorageGroupParam": {"storageGroupId": storage_group_id}
            },
        }
        overrides = (options or {}).get("raw_overrides") or {}
        return _deep_merge(payload, copy.deepcopy(overrides.get("masking_view") or {}))

    def ensure_masking_view(
        self,
        storage_group_id: str,
        host_name: str,
        initiator_wwns: list[str],
        port_group_id: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        if not port_group_id:
            raise ValueError(
                "PowerMax requires a Port Group to present the Storage Group to the host"
            )
        prefix = options.get("masking_view_prefix") or storage_group_id
        masking_view_id = f"{prefix}_{host_name}"[:64]
        for item in self.get_masking_views():
            item_id = str(item.get("id") or item.get("maskingViewId") or item.get("name") or "")
            if item_id.casefold() == masking_view_id.casefold():
                return {**item, "id": item_id, "already_exists": True}

        hosts = self.get_hosts()
        host_id = str(options.get("powermax_host_id") or host_name)
        host_exists = any(
            str(item.get("id") or item.get("hostId") or item.get("name") or "").casefold()
            == host_id.casefold()
            for item in hosts
        )
        path = self._array_path("maskingview")
        created = self.request(
            "POST",
            path,
            json=self.build_masking_view_payload(
                masking_view_id,
                storage_group_id,
                host_id,
                port_group_id,
                initiator_wwns,
                host_exists,
                options,
            ),
        )
        if isinstance(created, dict):
            return {
                **created,
                "id": str(created.get("maskingViewId") or created.get("id") or masking_view_id),
                "already_exists": False,
            }
        return {"id": masking_view_id, "already_exists": False, "data": created}


def _deep_merge(target: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key] = _deep_merge(target[key], value)
        else:
            target[key] = value
    return target
