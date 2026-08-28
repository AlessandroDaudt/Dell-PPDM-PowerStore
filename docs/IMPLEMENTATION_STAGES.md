# Implementation stages

Integration branches are cumulative. Each stage keeps the previous flow and adds one domain.

| Etapa | Branch | Entrega |
| --- | --- | --- |
| 0 | `main` | Individual volume PowerStore |
| 1 | `feature/powerstore-block` | Volumes individuais e grupos de volumes block PowerStore |
| 2 | `feature/powermax-storage-groups` | Storage Groups PowerMax, masking views para hosts e zoning Brocade |
| 3 | `feature/powerstore-nas` | File systems/shares PowerStore NAS, publication e rotina PPDM NAS |
| 4 | `feature/powerscale-nas` | Shares SMB/NFS PowerScale, publication e rotina PPDM NAS |
| 5 | `feature/dell-unity-nas` | Shares CIFS/NFS Dell Unity, publication e rotina PPDM NAS |

## Storage backup flow

Para volumes block, a execution segue esta ordem:

1. validar hosts, WWPNs, fabrics, credenciais e capacidade;
2. create a LUN ou o grupo de volumes no array;
3. present a LUN aos hosts (mappings PowerStore ou masking view PowerMax);
4. create/activate Brocade zones when enabled;
5. create ou reutilizar a rotina PPDM com Data Domain, interface, storage unit, schedule e retention;
6. confirm the resource and record IDs in the workflow.

O PowerMax usa Storage Group + masking view. O Port Group precisa existir no array e pode ser
provided in PowerMax inventory or in the request. Missing hosts can be created by the
the `createHostParam` selection, using the registered WWPNs.

## Fluxo NAS

For NAS resources, the execution does not use LUN presentation or FC zoning:

1. validar o servidor NAS, protocolo, caminho e credenciais;
2. create or reconcile the share; on PowerStore, `NAS_DATA` also creates the file system;
3. publicar o share e confirmar a leitura dele no array;
4. create or reuse the PPDM NAS policy with the selected Data Domain, interface, and storage unit,
   schedule, retention e NAS Protection Engine;
5. wait for the asset to be discovered in PPDM and assign it to the policy.

O Data Domain and the NAS Protection Engine sao obrigatorios ao create uma policy NAS. A application
configures the reference in the policy, but does not install or provision the Protection Engine.

## Validation

From the repository root:

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --no-project --python 3.12 --with-requirements requirements-dev.txt pytest -q
uv run --no-project --python 3.12 --with ruff==0.12.9 ruff check app tests
```
