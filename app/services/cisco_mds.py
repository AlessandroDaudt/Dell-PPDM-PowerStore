import re
from typing import Any

import httpx

from app.services.base_client import ExternalAPIError, build_base_url, response_data


class CiscoMDSClient:
    """Cisco MDS NX-API client for idempotent VSAN zoning."""

    _TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
    _ZONE_PATTERN = re.compile(r"^\s*zone name (?P<name>\S+) vsan (?P<vsan>\d+)")
    _PWWN_PATTERN = re.compile(r"^\s*pwwn (?P<wwn>\S+)")
    _ZONESET_PATTERN = re.compile(r"^\s*zoneset name (?P<name>\S+) vsan (?P<vsan>\d+)")
    _ZONESET_MEMBER_PATTERN = re.compile(r"^\s+zone(?: name)? (?P<name>\S+)")

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        port: int | None = None,
        verify_ssl: bool = True,
        api_version: str = "1.2",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_version = str(api_version)
        self.base_url = build_base_url(address, port, 443)
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
            "Cisco MDS",
            method,
            str(response.request.url),
            response.status_code,
            response_data(response),
        )

    @staticmethod
    def _output_items(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        ins_api = data.get("ins_api")
        if not isinstance(ins_api, dict):
            return []
        outputs = ins_api.get("outputs", {}).get("output", {})
        if isinstance(outputs, list):
            return [item for item in outputs if isinstance(item, dict)]
        return [outputs] if isinstance(outputs, dict) else []

    def _execute(self, command: str, command_type: str) -> Any:
        payload = {
            "ins_api": {
                "version": self.api_version,
                "type": command_type,
                "chunk": "0",
                "sid": "1",
                "input": command,
                "output_format": "json",
            }
        }
        response = self.client.post("/ins", json=payload)
        self._raise("POST", response)
        data = response_data(response)
        outputs = self._output_items(data)
        if not outputs:
            raise ExternalAPIError(
                "Cisco MDS", "POST", str(response.request.url), None, "resposta NX-API sem output"
            )
        errors = [item for item in outputs if str(item.get("code", "200")) != "200"]
        if errors:
            detail = errors[0].get("msg") or errors[0].get("body") or errors[0]
            raise ExternalAPIError("Cisco MDS", "POST", str(response.request.url), None, detail)
        if command_type == "cli_conf":
            return outputs[0].get("body", {})
        return outputs[0].get("body", {})

    def show(self, command: str) -> Any:
        return self._execute(command, "cli_show_ascii")

    def configure(self, commands: list[str]) -> Any:
        if not commands:
            return {}
        return self._execute(" ; ".join(commands), "cli_conf")

    def test_connection(self) -> dict[str, Any]:
        body = self.show("show nxapi")
        result: dict[str, Any] = {"ok": True, "system": "Cisco MDS", "nxapi": body}
        if isinstance(body, dict):
            result.update(
                {
                    "nxapi_status": body.get("nxapi_status"),
                    "http_port": body.get("http_port"),
                }
            )
        return result

    @classmethod
    def _validate_token(cls, value: str, label: str) -> str:
        value = str(value).strip()
        if not value or not cls._TOKEN_PATTERN.fullmatch(value):
            raise ValueError(f"{label} invalido para Cisco MDS")
        return value

    @classmethod
    def _parse_zones(cls, body: Any, vsan_id: int) -> dict[str, set[str]]:
        if not isinstance(body, str):
            return {}
        zones: dict[str, set[str]] = {}
        current: str | None = None
        for line in body.splitlines():
            zone = cls._ZONE_PATTERN.match(line)
            if zone:
                if int(zone.group("vsan")) == vsan_id:
                    current = zone.group("name")
                    zones.setdefault(current, set())
                else:
                    current = None
                continue
            member = cls._PWWN_PATTERN.match(line)
            if current and member:
                zones[current].add(member.group("wwn").casefold())
        return zones

    @classmethod
    def _parse_zonesets(cls, body: Any, vsan_id: int) -> dict[str, set[str]]:
        if not isinstance(body, str):
            return {}
        zonesets: dict[str, set[str]] = {}
        current: str | None = None
        for line in body.splitlines():
            zoneset = cls._ZONESET_PATTERN.match(line)
            if zoneset:
                if int(zoneset.group("vsan")) == vsan_id:
                    current = zoneset.group("name")
                    zonesets.setdefault(current, set())
                else:
                    current = None
                continue
            member = cls._ZONESET_MEMBER_PATTERN.match(line)
            if current and member:
                zonesets[current].add(member.group("name").casefold())
        return zonesets

    def get_zones(self, vsan_id: int) -> dict[str, set[str]]:
        return self._parse_zones(self.show(f"show zone vsan {vsan_id}"), vsan_id)

    def get_zonesets(self, vsan_id: int, active: bool = False) -> dict[str, set[str]]:
        command = "show zoneset brief active" if active else "show zoneset brief"
        return self._parse_zonesets(self.show(f"{command} vsan {vsan_id}"), vsan_id)

    def ensure_zoning(
        self,
        zone_name: str,
        vsan_id: int,
        zoneset_name: str,
        initiator_wwns: list[str],
        target_wwns: list[str],
        activate: bool = True,
        peer_zoning: bool = False,
    ) -> dict[str, Any]:
        if peer_zoning:
            raise ValueError("peer zoning ainda nao e suportado pelo adaptador Cisco MDS")
        zone_name = self._validate_token(zone_name, "zone_name")
        zoneset_name = self._validate_token(zoneset_name, "zoneset_name")
        if not 1 <= int(vsan_id) <= 4093:
            raise ValueError("vsan_id deve estar entre 1 e 4093")
        initiators = [self._validate_token(item, "WWPN") for item in initiator_wwns]
        targets = [self._validate_token(item, "WWPN") for item in target_wwns]
        desired_members = list(dict.fromkeys([*initiators, *targets]))
        if not desired_members:
            raise ValueError("Cisco MDS exige ao menos um initiator ou target na zone")

        zones = self.get_zones(vsan_id)
        existing_zone_name = next(
            (name for name in zones if name.casefold() == zone_name.casefold()), None
        )
        existing_members = zones.get(existing_zone_name, set()) if existing_zone_name else set()
        commands: list[str] = []
        missing_members = [
            item for item in desired_members if item.casefold() not in existing_members
        ]
        if existing_zone_name is None or missing_members:
            commands.append(f"zone name {zone_name} vsan {vsan_id}")
            commands.extend(f"member pwwn {item}" for item in missing_members or desired_members)

        zonesets = self.get_zonesets(vsan_id)
        existing_zoneset_name = next(
            (name for name in zonesets if name.casefold() == zoneset_name.casefold()), None
        )
        zoneset_members = (
            zonesets.get(existing_zoneset_name, set()) if existing_zoneset_name else set()
        )
        if zone_name.casefold() not in zoneset_members:
            commands.extend([f"zoneset name {zoneset_name} vsan {vsan_id}", f"member {zone_name}"])

        active_zonesets = {name.casefold() for name in self.get_zonesets(vsan_id, active=True)}
        if activate and zoneset_name.casefold() not in active_zonesets:
            commands.append(f"zoneset activate name {zoneset_name} vsan {vsan_id}")

        response = self.configure(commands) if commands else {}
        return {
            "zone_name": zone_name,
            "zoneset_name": zoneset_name,
            "vsan_id": vsan_id,
            "changed": bool(commands),
            "commands": commands,
            "response": response,
        }
