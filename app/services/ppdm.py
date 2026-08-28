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
                raise ValueError("raw_overrides.additional_objectives must be a list")
            payload.setdefault(container, []).extend(additional_objectives)
        created = self.request("POST", endpoint, json=payload)
        if not isinstance(created, dict) or not created.get("id"):
            raise ExternalAPIError(
                "PPDM", "POST", endpoint, None, "response did not include a policy ID"
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
                    f"block resource {name} did not appear in inventory within {timeout}s; "
                    "execute a descoberta do storage no PPDM",
                )
            time.sleep(interval)

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
                    f"volume {name} did not appear in inventory within {timeout}s; "
                    "trigger PowerStore discovery in PPDM",
                )
            time.sleep(interval)

    def assign_asset(self, policy_id: str, asset_id: str) -> Any:
        return self.request(
            "POST",
            f"/api/v2/protection-policies/{policy_id}/asset-assignments",
            json=[asset_id],
        )
