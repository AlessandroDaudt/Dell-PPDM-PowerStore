# Implementation stages

Integration branches are cumulative. Each stage keeps the previous flow and adds one domain.

| Etapa | Branch | Entrega |
| --- | --- | --- |
| 0 | `main` | Volume individual PowerStore |
| 1 | `feature/powerstore-block` | Individual PowerStore volumes and block volume groups |
| 2 | `feature/powermax-storage-groups` | PowerMax Storage Groups, host masking views, and Brocade zoning |

## Block flow

For storage backup, execution follows this order:

1. validate hosts, WWPNs, fabrics, credentials, and capacity;
2. create the LUN or volume group on the array;
3. present the LUN to hosts (PowerStore mappings or a PowerMax masking view);
4. create/activate Brocade zones when enabled;
5. create or reuse the PPDM policy with Data Domain, interface, storage unit, schedule, and retention;
6. confirm the resource and record IDs in the workflow.

O PowerMax usa `POST .../sloprovisioning/symmetrix/{symmetrixId}/maskingview`. O Port Group precisa
exist on the array and can be provided in PowerMax inventory or in the request. PowerMax hosts
that do not exist are created through the `createHostParam` selection, using the registered WWPNs.

## Validation

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --no-project --python 3.12 --with-requirements requirements-dev.txt pytest -q
uv run --no-project --python 3.12 --with ruff==0.12.9 ruff check app tests
```
