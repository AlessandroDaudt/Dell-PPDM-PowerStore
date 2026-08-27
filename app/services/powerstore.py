from typing import Any

import httpx

from app.services.base_client import ExternalAPIError, build_base_url, response_data


class PowerStoreClient:
    """PowerStore REST client with persistent Basic Auth session and CSRF token."""

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
        self._csrf_token: str | None = None
        self.client = httpx.Client(
            base_url=self.base_url,
            auth=httpx.BasicAuth(username, password),
            verify=verify_ssl,
            timeout=httpx.Timeout(45.0, connect=15.0),
            headers={"Accept": "application/json"},
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
        detail = response_data(response)
        raise ExternalAPIError(
            "PowerStore", method, str(response.request.url), response.status_code, detail
        )

    def _bootstrap_session(self) -> dict[str, Any]:
        response = self.client.get("/api/rest/cluster")
        self._raise("GET", response)
        self._csrf_token = response.headers.get("DELL-EMC-TOKEN") or response.headers.get(
            "dell-emc-token"
        )
        data = response_data(response)
        if isinstance(data, list):
            return data[0] if data else {}
        return data if isinstance(data, dict) else {}

    def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None
    ) -> Any:
        method = method.upper()
        headers: dict[str, str] = {}
        if method in {"POST", "PATCH", "DELETE"}:
            if not self._csrf_token:
                self._bootstrap_session()
            if self._csrf_token:
                headers["DELL-EMC-TOKEN"] = self._csrf_token
        response = self.client.request(method, path, params=params, json=json, headers=headers)
        self._raise(method, response)
        return response_data(response)

    def test_connection(self) -> dict[str, Any]:
        cluster = self._bootstrap_session()
        return {
            "ok": True,
            "system": "PowerStore",
            "name": cluster.get("name", "PowerStore"),
            "id": cluster.get("id"),
        }

    def _status_optional(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return self.request("GET", path, params=params)
        except ExternalAPIError as exc:
            if exc.status_code in {400, 404, 405, 501}:
                return {"available": False, "reason": str(exc)}
            raise

    def get_status(self) -> dict[str, Any]:
        """Return capacity, health, network and port data from the array."""
        cluster = self._bootstrap_session()
        metrics = {
            "cluster": cluster,
            "appliances": self._status_optional("/api/rest/appliance"),
            "hardware": self._status_optional("/api/rest/hardware"),
            "nodes": self._status_optional("/api/rest/node"),
            "network": self._status_optional("/api/rest/network"),
            "storage_containers": self._status_optional("/api/rest/storage_container"),
            "fc_ports": self._status_optional("/api/rest/fc_port"),
            "eth_ports": self._status_optional("/api/rest/eth_port"),
        }
        return {"state": "OK", "metrics": metrics, "error": None}

    def get_options(self) -> dict[str, Any]:
        self._bootstrap_session()
        result: dict[str, Any] = {}
        for key, path, params in (
            ("appliances", "/api/rest/appliance", {"select": "id,name,service_tag"}),
            ("volume_groups", "/api/rest/volume_group", {"select": "id,name,description"}),
            ("fc_ports", "/api/rest/fc_port", {"select": "id,name,wwn,link_state"}),
            (
                "protection_policies",
                "/api/rest/protection_policy",
                {"select": "id,name,description"},
            ),
            (
                "performance_policies",
                "/api/rest/performance_policy",
                {"select": "id,name,description"},
            ),
        ):
            try:
                data = self.request("GET", path, params=params)
            except ExternalAPIError as exc:
                if exc.status_code == 404 and key.endswith("policies"):
                    policy_type = "Protection" if key.startswith("protection") else "Performance"
                    data = self.request(
                        "GET",
                        "/api/rest/policy",
                        params={"select": "id,name,type", "type": f"eq.{policy_type}"},
                    )
                else:
                    raise
            result[key] = data if isinstance(data, list) else []
        return result

    @staticmethod
    def _require_id(
        data: Any, system: str, method: str, path: str, resource: str
    ) -> dict[str, Any]:
        if not isinstance(data, dict) or not data.get("id"):
            raise ExternalAPIError(system, method, path, None, f"resposta sem id de {resource}")
        return data

    def create_volume(self, options: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": options["name"],
            "size": int(options["size_gib"]) * 1024**3,
            "description": options.get("description", ""),
        }
        for key in ("appliance_id", "performance_policy_id", "protection_policy_id"):
            if options.get(key):
                payload[key] = options[key]
        if options.get("volume_group_id"):
            payload["volume_group_id"] = options["volume_group_id"]
        created = self.request("POST", "/api/rest/volume", json=payload)
        return self._require_id(created, "PowerStore", "POST", "/api/rest/volume", "volume")

    def get_volume_groups(self) -> list[dict[str, Any]]:
        data = self.request(
            "GET", "/api/rest/volume_group", params={"select": "id,name,description,volumes"}
        )
        return data if isinstance(data, list) else []

    def get_volume_group(self, group_id: str) -> dict[str, Any]:
        data = self.request(
            "GET",
            f"/api/rest/volume_group/{group_id}",
            params={"select": "id,name,description,volumes,type"},
        )
        return data if isinstance(data, dict) else {}

    def create_volume_group(self, options: dict[str, Any]) -> dict[str, Any]:
        """Create a PowerStore volume group and its member volumes natively."""
        group_payload: dict[str, Any] = {
            "name": options["group_name"],
            "description": options.get("group_description") or options.get("description", ""),
            "is_write_order_consistent": options.get("write_order_consistent", True),
        }
        if options.get("protection_policy_id"):
            group_payload["protection_policy_id"] = options["protection_policy_id"]
        created = self._require_id(
            self.request("POST", "/api/rest/volume_group", json=group_payload),
            "PowerStore",
            "POST",
            "/api/rest/volume_group",
            "grupo de volumes",
        )
        members: list[dict[str, Any]] = []
        for member in options.get("members", []):
            members.append(self.create_volume({**member, "volume_group_id": created["id"]}))
        return {**created, "type": "Primary", "volumes": members}

    def map_volume_group(self, host_id: str, volume_group_id: str) -> dict[str, Any]:
        """Attach a volume group through the native PowerStore group operation."""
        path = f"/api/rest/volume_group/{volume_group_id}/attach"
        try:
            created = self.request("POST", path, json={"host_id": host_id})
        except ExternalAPIError as exc:
            if exc.status_code != 404:
                raise
            group = self.get_volume_group(volume_group_id)
            mappings = [
                self.map_volume(host_id, str(volume["id"]))
                for volume in group.get("volumes", [])
                if volume.get("id")
            ]
            return {
                "host_id": host_id,
                "volume_group_id": volume_group_id,
                "created": True,
                "compatibility_fallback": "individual_volume_mappings",
                "mappings": mappings,
            }
        result = created if isinstance(created, dict) else {}
        return {"host_id": host_id, "volume_group_id": volume_group_id, "created": True, **result}

    def get_volume(self, volume_id: str) -> dict[str, Any]:
        data = self.request(
            "GET",
            f"/api/rest/volume/{volume_id}",
            params={"select": "id,name,size,wwn,type"},
        )
        return data if isinstance(data, dict) else {}

    def ensure_host(
        self, name: str, os_type: str, initiator_wwns: list[str], existing_id: str | None = None
    ) -> dict[str, Any]:
        if existing_id:
            data = self.request(
                "GET", f"/api/rest/host/{existing_id}", params={"select": "id,name,host_initiators"}
            )
            host = data if isinstance(data, dict) else {"id": existing_id, "name": name}
            return self._add_missing_initiators(host, initiator_wwns)

        hosts = self.request(
            "GET", "/api/rest/host", params={"select": "id,name,host_initiators,os_type"}
        )
        for host in hosts if isinstance(hosts, list) else []:
            if str(host.get("name", "")).casefold() == name.casefold():
                return self._add_missing_initiators(host, initiator_wwns)

        payload = {
            "name": name,
            "os_type": os_type,
            "initiators": [{"port_name": wwn, "port_type": "FC"} for wwn in initiator_wwns],
        }
        created = self.request("POST", "/api/rest/host", json=payload)
        if not isinstance(created, dict) or not created.get("id"):
            raise ExternalAPIError(
                "PowerStore", "POST", "/api/rest/host", None, "resposta sem id do host"
            )
        return created

    def _add_missing_initiators(
        self, host: dict[str, Any], initiator_wwns: list[str]
    ) -> dict[str, Any]:
        current = {item.get("port_name") for item in host.get("host_initiators", [])}
        missing = [item for item in initiator_wwns if item not in current]
        if not missing:
            return host
        self.request(
            "PATCH",
            f"/api/rest/host/{host['id']}",
            json={"add_initiators": [{"port_name": item, "port_type": "FC"} for item in missing]},
        )
        host["host_initiators"] = host.get("host_initiators", []) + [
            {"port_name": item, "port_type": "FC"} for item in missing
        ]
        return host

    def map_volume(
        self, host_id: str, volume_id: str, logical_unit_number: int | None = None
    ) -> dict[str, Any]:
        mappings = self.request(
            "GET",
            "/api/rest/host_volume_mapping",
            params={
                "select": "id,host_id,volume_id,logical_unit_number",
                "host_id": f"eq.{host_id}",
                "volume_id": f"eq.{volume_id}",
            },
        )
        for mapping in mappings if isinstance(mappings, list) else []:
            if mapping.get("host_id") == host_id and mapping.get("volume_id") == volume_id:
                return {**mapping, "already_exists": True}

        payload: dict[str, Any] = {"host_id": host_id, "volume_id": volume_id}
        if logical_unit_number is not None:
            payload["logical_unit_number"] = logical_unit_number
        payload.pop("host_id")
        created = self.request("POST", f"/api/rest/host/{host_id}/attach", json=payload)
        result = created if isinstance(created, dict) else {}
        return {"created": True, "host_id": host_id, **payload, **result}
