import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.config import get_settings


class AnsibleExecutionError(RuntimeError):
    pass


def run_brocade_zoning(
    switches: list[dict[str, Any]], timeout: int | None = None
) -> dict[str, Any]:
    settings = get_settings()
    playbook = Path(settings.ansible_playbook)
    if not playbook.exists():
        raise AnsibleExecutionError(f"playbook não encontrado: {playbook}")

    inventory = {
        "all": {
            "children": {
                "brocade_switches": {
                    "hosts": {
                        item["inventory_name"]: {
                            "ansible_connection": "local",
                            **{
                                key: value for key, value in item.items() if key != "inventory_name"
                            },
                        }
                        for item in switches
                    }
                }
            }
        }
    }
    with tempfile.TemporaryDirectory(prefix="sanflow-ansible-") as temp_dir:
        inventory_path = Path(temp_dir) / "inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "ANSIBLE_HOST_KEY_CHECKING": "False",
                "ANSIBLE_DISPLAY_ARGS_TO_STDOUT": "False",
                "ANSIBLE_NOCOLOR": "1",
                "ANSIBLE_RETRY_FILES_ENABLED": "False",
            }
        )
        try:
            result = subprocess.run(
                ["ansible-playbook", "-i", str(inventory_path), str(playbook)],
                capture_output=True,
                text=True,
                timeout=timeout or settings.ansible_timeout,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AnsibleExecutionError("ansible-playbook não está instalado") from exc
        except subprocess.TimeoutExpired as exc:
            raise AnsibleExecutionError("tempo limite do playbook excedido") from exc

    output = (result.stdout or "")[-12000:]
    errors = (result.stderr or "")[-4000:]
    if result.returncode != 0:
        raise AnsibleExecutionError(
            f"playbook terminou com código {result.returncode}: {errors or output}"
        )
    return {"return_code": result.returncode, "output": output}
