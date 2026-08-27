from typing import Any
from urllib.parse import urlparse

import httpx


class ExternalAPIError(RuntimeError):
    def __init__(
        self,
        system: str,
        method: str,
        url: str,
        status_code: int | None,
        detail: Any,
    ) -> None:
        self.system = system
        self.method = method
        self.url = url
        self.status_code = status_code
        self.detail = detail
        message = f"{system}: {method} {url} falhou"
        if status_code:
            message += f" (HTTP {status_code})"
        if detail:
            message += f": {detail}"
        super().__init__(message)


def build_base_url(address: str, port: int | None, default_port: int) -> str:
    candidate = address.strip().rstrip("/")
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = parsed.hostname or address
    scheme = parsed.scheme or "https"
    selected_port = parsed.port or port or default_port
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{scheme}://{host}:{selected_port}"


def response_data(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return response.text
