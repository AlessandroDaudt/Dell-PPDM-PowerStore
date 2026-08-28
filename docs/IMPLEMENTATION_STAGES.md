# Implementation stages

Integration branches are cumulative. Each stage keeps the previous flow and adds one domain.

| Stage | Branch | Deliverable |
| --- | --- | --- |
| 0 | `main` | Individual PowerStore volume |
| 1 | `feature/powerstore-block` | Individual volumes and PowerStore block volume groups |
| 2 | `feature/powermax-storage-groups` | PowerMax Storage Groups, masking views for hosts, and Brocade zoning |

## Block flow

For storage backup, execution follows this order:

1. validate hosts, WWPNs, fabrics, credentials, and capacity;
2. create the LUN or volume group on the array;
3. present the LUN to hosts (PowerStore mappings or a PowerMax masking view);
4. create or activate Brocade zones when enabled;
5. create or reuse the PPDM policy with Data Domain, interface, storage unit, schedule, and retention;
6. confirm the resource and record IDs in the workflow.

PowerMax uses `POST .../sloprovisioning/symmetrix/{symmetrixId}/maskingview`. The Port Group must
exist on the array and can be provided in PowerMax inventory or in the request. Missing PowerMax
hosts are created through the `createHostParam` selection, using the registered WWPNs.

## Validation

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --no-project --python 3.12 --with-requirements requirements-dev.txt pytest -q
uv run --no-project --python 3.12 --with ruff==0.12.9 ruff check app tests
```
