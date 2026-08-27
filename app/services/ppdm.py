import copy
import time
import uuid
from datetime import date
from typing import Any

import httpx

from app.services.base_client import ExternalAPIError, build_base_url, response_data


def deep_merge(target: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(target)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class PPDMClient:
    """PPDM v2/v3 public REST client."""

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        port: int | None = None,
        verify_ssl: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = build_base_url(address, port, 8443)
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

    def login(self) -> str:
        response = self.client.post(
            "/api/v2/login", json={"username": self.username, "password": self.password}
        )
        if not response.is_success:
            raise ExternalAPIError(
                "PPDM",
                "POST",
                str(response.request.url),
                response.status_code,
                response_data(response),
            )
        data = response_data(response)
        if not isinstance(data, dict) or not data.get("access_token"):
            raise ExternalAPIError("PPDM", "POST", "/api/v2/login", None, "token ausente")
        self.token = data["access_token"]
        return self.token

    def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None
    ) -> Any:
        if not self.token:
            self.login()
        response = self.client.request(
            method,
            path,
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        if response.status_code == 401:
            self.login()
            response = self.client.request(
                method,
                path,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {self.token}"},
            )
        if not response.is_success:
            raise ExternalAPIError(
                "PPDM",
                method,
                str(response.request.url),
                response.status_code,
                response_data(response),
            )
        return response_data(response)

    @staticmethod
    def _content(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict) and isinstance(data.get("content"), list):
            return data["content"]
        return data if isinstance(data, list) else []

    def get_version(self) -> str:
        nodes = self._content(self.request("GET", "/api/v2/nodes"))
        return str(nodes[0].get("version", "unknown")) if nodes else "unknown"

    @staticmethod
    def uses_v3(version: str) -> bool:
        try:
            major, minor, *_ = version.split("-")[0].split(".")
            return (int(major), int(minor)) >= (19, 17)
        except (TypeError, ValueError):
            return False

    def test_connection(self) -> dict[str, Any]:
        self.login()
        version = self.get_version()
        return {"ok": True, "system": "PPDM", "version": version}

    def get_options(self) -> dict[str, Any]:
        version = self.get_version()
        api = "v3" if self.uses_v3(version) else "v2"
        storage = self._content(
            self.request(
                "GET",
                "/api/v2/storage-systems",
                params={"filter": 'type eq "DATA_DOMAIN_SYSTEM"', "pageSize": 500},
            )
        )
        policies = self._content(
            self.request(
                "GET",
                f"/api/{api}/protection-policies",
                params={"pageSize": 500},
            )
        )
        policies = [
            item
            for item in policies
            if not item.get("assetType")
            or str(item.get("assetType")).upper() in {"POWERSTORE_BLOCK", "POWERMAX_BLOCK"}
        ]
        mtrees = self._content(
            self.request("GET", "/api/v2/datadomain-mtrees", params={"pageSize": 500})
        )
        return {
            "version": version,
            "policy_api": api,
            "data_domains": storage,
            "storage_units": mtrees,
            "policies": policies,
        }

    def get_nas_options(self) -> dict[str, Any]:
        """Load NAS policies and protection engines without changing block options."""
        version = self.get_version()
        api = "v3" if self.uses_v3(version) else "v2"
        policies = self._content(
            self.request(
                "GET",
                f"/api/{api}/protection-policies",
                params={"filter": 'assetType eq "NAS"', "pageSize": 500},
            )
        )
        engines = self._content(
            self.request("GET", "/api/v2/protection-engines", params={"pageSize": 500})
        )
        data_domains = self._content(
            self.request("GET", "/api/v2/storage-systems", params={"pageSize": 500})
        )
        data_domains = [
            item
            for item in data_domains
            if str(item.get("type", "DATA_DOMAIN_SYSTEM")).upper() == "DATA_DOMAIN_SYSTEM"
        ]
        storage_units = self._content(
            self.request("GET", "/api/v2/datadomain-mtrees", params={"pageSize": 500})
        )
        return {
            "version": version,
            "policy_api": api,
            "policies": policies,
            "protection_engines": engines,
            "data_domains": data_domains,
            "storage_units": storage_units,
        }

    @staticmethod
    def _schedule(options: dict[str, Any], v3: bool) -> dict[str, Any]:
        start = f"{date.today().isoformat()}T{options['start_time']}Z"
        frequency = options["frequency"]
        if v3:
            pattern: dict[str, Any] = {"type": frequency}
            if frequency == "HOURLY":
                pattern["interval"] = options["interval"]
            elif frequency == "WEEKLY":
                pattern["daysOfWeek"] = options["weekdays"]
            elif frequency == "MONTHLY":
                pattern["dayOfMonth"] = options["day_of_month"]
            return {
                "recurrence": {"pattern": pattern},
                "window": {"startTime": start, "duration": f"PT{options['duration_hours']}H"},
            }
        schedule: dict[str, Any] = {
            "frequency": frequency,
            "startTime": start,
            "duration": f"PT{options['duration_hours']}H",
        }
        if frequency == "HOURLY":
            schedule["interval"] = options["interval"]
        elif frequency == "WEEKLY":
            schedule["weekDays"] = options["weekdays"]
        elif frequency == "MONTHLY":
            schedule["dayOfMonth"] = options["day_of_month"]
        return schedule

    def create_powerstore_policy(self, options: dict[str, Any]) -> dict[str, Any]:
        version = self.get_version()
        v3 = self.uses_v3(version)
        schedule = self._schedule(options, v3)
        operation_id = str(uuid.uuid4())
        objective_id = str(uuid.uuid4())
        if v3:
            payload: dict[str, Any] = {
                "name": options["policy_name"],
                "assetType": options.get("asset_type", "POWERSTORE_BLOCK"),
                "disabled": False,
                "purpose": "CENTRALIZED",
                "objectives": [
                    {
                        "id": objective_id,
                        "type": "BACKUP",
                        "config": {"dataConsistency": options["data_consistency"]},
                        "target": {
                            "storageContainerId": options["data_domain_id"],
                            "preferredInterfaceId": options.get("data_domain_interface"),
                            "storageTargetId": options.get("storage_unit_id"),
                        },
                        "operations": [
                            {
                                "id": operation_id,
                                "backupLevel": options["backup_level"],
                                "schedule": schedule,
                            }
                        ],
                        "retentions": [
                            {
                                "id": str(uuid.uuid4()),
                                "time": [
                                    {
                                        "type": (
                                            "RETENTION_AND_LOCK"
                                            if options["retention_lock"]
                                            else "RETENTION"
                                        ),
                                        "unitValue": options["retention_interval"],
                                        "unitType": options["retention_unit"],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            target = payload["objectives"][0]["target"]
            payload["objectives"][0]["target"] = {k: v for k, v in target.items() if v}
            endpoint = "/api/v3/protection-policies"
        else:
            payload = {
                "name": options["policy_name"],
                "assetType": options.get("asset_type", "POWERSTORE_BLOCK"),
                "type": "ACTIVE",
                "encrypted": options["encrypted"],
                "enabled": True,
                "priority": 1,
                "dataConsistency": options["data_consistency"],
                "stages": [
                    {
                        "id": objective_id,
                        "type": "PROTECTION",
                        "passive": False,
                        "target": {
                            "storageSystemId": options["data_domain_id"],
                            "preferredInterfaceId": options.get("data_domain_interface"),
                            "storageTargetId": options.get("storage_unit_id"),
                        },
                        "operations": [
                            {
                                "type": "AUTO_FULL",
                                "backupType": options["backup_level"],
                                "schedule": schedule,
                            }
                        ],
                        "retention": {
                            "interval": options["retention_interval"],
                            "unit": options["retention_unit"],
                            "storageSystemRetentionLock": options["retention_lock"],
                        },
                    }
                ],
            }
            target = payload["stages"][0]["target"]
            payload["stages"][0]["target"] = {k: v for k, v in target.items() if v}
            endpoint = "/api/v2/protection-policies"
        overrides = copy.deepcopy(options.get("raw_overrides") or {})
        additional_objectives = overrides.pop("additional_objectives", [])
        payload = deep_merge(payload, overrides)
        if additional_objectives:
            container = "objectives" if v3 else "stages"
            if not isinstance(additional_objectives, list):
                raise ValueError("raw_overrides.additional_objectives deve ser uma lista")
            payload.setdefault(container, []).extend(additional_objectives)
        created = self.request("POST", endpoint, json=payload)
        if not isinstance(created, dict) or not created.get("id"):
            raise ExternalAPIError("PPDM", "POST", endpoint, None, "resposta sem id da política")
        return created

    def create_nas_policy(self, options: dict[str, Any]) -> dict[str, Any]:
        """Create a centralized NAS policy that uses a NAS Protection Engine."""
        if not options.get("data_domain_id"):
            raise ValueError("data_domain_id Ã© obrigatÃ³rio para uma polÃ­tica NAS")
        if not options.get("nas_protection_engine_id"):
            raise ValueError("nas_protection_engine_id Ã© obrigatÃ³rio para uma polÃ­tica NAS")
        version = self.get_version()
        v3 = self.uses_v3(version)
        schedule = self._schedule(options, v3)
        objective_id = str(uuid.uuid4())
        target: dict[str, Any] = {
            "storageContainerId": options.get("data_domain_id"),
            "preferredInterfaceId": options.get("data_domain_interface"),
            "storageTargetId": options.get("storage_unit_id"),
        }
        if v3:
            objective: dict[str, Any] = {
                "id": objective_id,
                "type": "BACKUP",
                "config": {"dataConsistency": options["data_consistency"]},
                "target": {key: value for key, value in target.items() if value},
                "operations": [
                    {
                        "id": str(uuid.uuid4()),
                        "backupLevel": options["backup_level"],
                        "schedule": schedule,
                    }
                ],
                "retentions": [
                    {
                        "id": str(uuid.uuid4()),
                        "time": [
                            {
                                "type": "RETENTION_AND_LOCK"
                                if options["retention_lock"]
                                else "RETENTION",
                                "unitValue": options["retention_interval"],
                                "unitType": options["retention_unit"],
                            }
                        ],
                    }
                ],
            }
            if options.get("nas_protection_engine_id"):
                objective["protectionEngineId"] = options["nas_protection_engine_id"]
            payload: dict[str, Any] = {
                "name": options["policy_name"],
                "assetType": "NAS",
                "disabled": False,
                "purpose": "CENTRALIZED",
                "objectives": [objective],
            }
            endpoint = "/api/v3/protection-policies"
        else:
            stage: dict[str, Any] = {
                "id": objective_id,
                "type": "PROTECTION",
                "passive": False,
                "target": {
                    "storageSystemId": options.get("data_domain_id"),
                    "preferredInterfaceId": options.get("data_domain_interface"),
                    "storageTargetId": options.get("storage_unit_id"),
                },
                "operations": [
                    {
                        "type": "AUTO_FULL",
                        "backupType": options["backup_level"],
                        "schedule": schedule,
                    }
                ],
                "retention": {
                    "interval": options["retention_interval"],
                    "unit": options["retention_unit"],
                    "storageSystemRetentionLock": options["retention_lock"],
                },
            }
            if options.get("nas_protection_engine_id"):
                stage["protectionEngineId"] = options["nas_protection_engine_id"]
            payload = {
                "name": options["policy_name"],
                "assetType": "NAS",
                "type": "ACTIVE",
                "encrypted": options["encrypted"],
                "enabled": True,
                "priority": 1,
                "dataConsistency": options["data_consistency"],
                "stages": [stage],
            }
            endpoint = "/api/v2/protection-policies"
        overrides = copy.deepcopy(options.get("raw_overrides") or {})
        additional = overrides.pop("additional_objectives", [])
        payload = deep_merge(payload, overrides)
        if additional:
            payload.setdefault("objectives" if v3 else "stages", []).extend(additional)
        created = self.request("POST", endpoint, json=payload)
        if not isinstance(created, dict) or not created.get("id"):
            raise ExternalAPIError(
                "PPDM", "POST", endpoint, None, "resposta sem id da política NAS"
            )
        return created

    def find_powerstore_asset(self, name: str) -> dict[str, Any] | None:
        data = self.request(
            "GET",
            "/api/v2/assets",
            params={
                "filter": f'type eq "POWERSTORE_BLOCK" and name eq "{name}"',
                "pageSize": 100,
            },
        )
        assets = self._content(data)
        for asset in assets:
            if asset.get("name") == name and asset.get("subtype") in {
                "POWERSTORE_VOLUME",
                "POWERSTORE_VOLUME_GROUP",
            }:
                return asset
        return assets[0] if assets else None

    def find_nas_asset(self, name: str, path: str | None = None) -> dict[str, Any] | None:
        data = self.request(
            "GET",
            "/api/v2/assets",
            params={"filter": 'type eq "NAS"', "pageSize": 500},
        )
        assets = self._content(data)
        wanted = path or name
        for asset in assets:
            values = {str(asset.get(key, "")) for key in ("name", "path", "sharePath", "assetPath")}
            if name in values or wanted in values:
                return asset
        return assets[0] if len(assets) == 1 else None

    def wait_for_nas_asset(
        self, name: str, path: str | None = None, timeout: int = 180, interval: int = 10
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            asset = self.find_nas_asset(name, path)
            if asset:
                return asset
            if time.monotonic() >= deadline:
                raise ExternalAPIError(
                    "PPDM",
                    "GET",
                    "/api/v2/assets",
                    None,
                    f"recurso block {name} não apareceu no inventário em {timeout}s; "
                    "execute a descoberta do storage no PPDM",
                )
            time.sleep(interval)

    def find_block_asset(self, name: str) -> dict[str, Any] | None:
        """Find a discovered block asset without assuming the array vendor subtype."""
        data = self.request(
            "GET",
            "/api/v2/assets",
            params={"filter": f'name eq "{name}"', "pageSize": 500},
        )
        assets = self._content(data)
        for asset in assets:
            if str(asset.get("name", "")) == name:
                return asset
        return assets[0] if len(assets) == 1 else None

    def wait_for_block_asset(
        self, name: str, timeout: int = 180, interval: int = 10
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        path = name
        while True:
            asset = self.find_block_asset(name)
            if asset:
                return asset
            if time.monotonic() >= deadline:
                raise ExternalAPIError(
                    "PPDM",
                    "GET",
                    "/api/v2/assets",
                    None,
                    f"share NAS {path or name} não apareceu no inventário em {timeout}s; "
                    "confirme a origem NAS e a implantação do NAS Protection Engine",
                )
            time.sleep(interval)

    def assign_assets(self, policy_id: str, asset_ids: list[str]) -> Any:
        return self.request(
            "POST", f"/api/v2/protection-policies/{policy_id}/asset-assignments", json=asset_ids
        )

    """

                    "PPDM",
                    "GET",
                    "/api/v2/assets",
                    None,
                    f"share NAS {path or name} nÃ£o apareceu no inventÃ¡rio em {timeout}s; "
                    "confirme a origem NAS e a implantação do NAS Protection Engine",
                )
            time.sleep(interval)

    """

    def wait_for_powerstore_asset(
        self, name: str, timeout: int = 180, interval: int = 10
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            asset = self.find_powerstore_asset(name)
            if asset:
                return asset
            if time.monotonic() >= deadline:
                raise ExternalAPIError(
                    "PPDM",
                    "GET",
                    "/api/v2/assets",
                    None,
                    f"volume {name} não apareceu no inventário em {timeout}s; "
                    "execute a descoberta do PowerStore no PPDM",
                )
            time.sleep(interval)

    def assign_asset(self, policy_id: str, asset_id: str) -> Any:
        return self.request(
            "POST",
            f"/api/v2/protection-policies/{policy_id}/asset-assignments",
            json=[asset_id],
        )
