# Implementation stages

The integration branches are cumulative. Each stage preserves the previous flow and adds a domain.

| Stage | Branch | Delivery |
| --- | --- | --- |
| 0 | `main` | Volume individual PowerStore |
| 1 | `feature/powerstore-block` | Individual volumes and PowerStore block volume groups |
| 2 | `feature/powermax-storage-groups` | PowerMax Storage Groups, masking views for hosts, and Brocade zoning |
| 3 | `feature/powerstore-nas` | PowerStore NAS file systems/shares, publication, and PPDM NAS workflow |
| 4 | `feature/powerscale-nas` | PowerScale SMB/NFS shares, publication, and PPDM NAS workflow |
| 5 | `feature/dell-unity-nas` | Dell Unity CIFS/NFS shares, publication, and PPDM NAS workflow |
| 6 | `feature/cisco-fibre-channel` | Cisco MDS Fibre Channel zoning through NX-API, with VSAN, zoneset, and idempotent activation |

## Storage backup flow

For block volumes, execution follows this order:

1. validate hosts, WWPNs, fabrics, credentials, and capacity;
2. create the LUN or volume group on the array;
3. present the LUN to hosts (PowerStore mappings or a PowerMax masking view);
4. create/activate zones on the selected fabric when enabled (Brocade through Ansible/FOS REST or Cisco MDS through NX-API);
5. create or reuse the PPDM workflow with Data Domain, interface, storage unit, schedule, and retention;
6. confirm the resource and record IDs in the workflow.

PowerMax uses a Storage Group plus masking view. The Port Group must exist on the array and can be
provided when registering PowerMax or in the request. Missing hosts can be created through the
`createHostParam` selection using the registered WWPNs.

## NAS flow

For NAS, execution does not use LUN presentation or FC zoning:

1. validate the NAS server, protocol, path, and credentials;
2. create or reconcile the share; on PowerStore, `NAS_DATA` also creates the file system;
3. publish the share and confirm that it can be read from the array;
4. create or reuse the PPDM NAS workflow with the selected Data Domain, interface, storage unit,
   schedule, retention, and NAS Protection Engine;
5. wait for asset discovery in PPDM and assign it to the policy.

The Data Domain and NAS Protection Engine are required when creating a NAS policy. The application
configures the policy reference but does not install or provision the Protection Engine.

## Validation

From the repository root:

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --no-project --python 3.12 --with-requirements requirements-dev.txt pytest -q
uv run --no-project --python 3.12 --with ruff==0.12.9 ruff check app tests
```
