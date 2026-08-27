# Implementation stages

The integrations were developed as a cumulative branch chain. Each branch starts at the previous stage, so the last branch includes every earlier capability.

| Stage | Branch | Scope |
| --- | --- | --- |
| 0 | `main` | Existing PowerStore individual-volume workflow |
| 1 | `feature/powerstore-block` | PowerStore individual volumes and native block volume groups |
| 2 | `feature/powermax-storage-groups` | PowerMax Storage Groups through Unisphere REST |
| 3 | `feature/powerstore-nas` | PowerStore NAS file systems/shares and PPDM NAS Protection Engine workflow |
| 4 | `feature/powerscale-nas` | PowerScale SMB/NFS shares through OneFS PAPI |
| 5 | `feature/dell-unity-nas` | Dell Unity CIFS/NFS shares through Unisphere REST |

## Workflow behavior

- Block `VOLUME` keeps the original host registration, FC zoning and PPDM flow.
- PowerStore `VOLUME_GROUP` creates the group and its member volumes in the array, then uses the native group attach endpoint when available.
- PowerMax `POWERMAX_STORAGE_GROUP` is hostless in this workflow. Set `zoning.enabled` to `false` and configure the array `symmetrix_id`; SRP, SLO, emulation and volume count are passed to Unisphere.
- NAS `NAS_SHARE` and `NAS_DATA` do not use FC hosts or Brocade. They reconcile the share on the selected Dell NAS, discover it in PPDM and assign it to a centralized NAS policy.
- A live NAS run assumes that the PPDM NAS asset source is enabled, NAS credentials are already registered, and a reachable NAS Protection Engine is deployed. SANFlow selects the engine in the policy payload; it does not deploy the VM or container engine.

## Validation

From the repository root, the test suite can be run without a system Python installation by using `uv`:

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --no-project --python 3.12 --with-requirements requirements-dev.txt pytest -q
uv run --no-project --python 3.12 --with ruff==0.12.9 ruff check app tests
```
