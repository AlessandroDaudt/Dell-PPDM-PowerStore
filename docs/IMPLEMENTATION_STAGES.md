# Etapas de implementação

As branches de integração são cumulativas. Cada etapa mantém o fluxo anterior e adiciona um domínio.

| Etapa | Branch | Entrega |
| --- | --- | --- |
| 0 | `main` | Volume individual PowerStore |
| 1 | `feature/powerstore-block` | Volumes individuais e grupos de volumes block PowerStore |
| 2 | `feature/powermax-storage-groups` | Storage Groups PowerMax, masking views para hosts e zoning Brocade |

## Fluxo block

Para backup de storage, a execução segue esta ordem:

1. validar hosts, WWPNs, fabrics, credenciais e capacidade;
2. criar a LUN ou o grupo de volumes no array;
3. apresentar a LUN aos hosts (mappings PowerStore ou masking view PowerMax);
4. criar/ativar as zonas Brocade quando habilitado;
5. criar ou reutilizar a rotina PPDM com Data Domain, interface, storage unit, agenda e retenção;
6. confirmar o recurso e registrar IDs no workflow.

O PowerMax usa `POST .../sloprovisioning/symmetrix/{symmetrixId}/maskingview`. O Port Group precisa
existir no array e pode ser informado no cadastro do PowerMax ou na solicitação. Hosts PowerMax
inexistentes são criados pela seleção `createHostParam`, usando os WWPNs cadastrados.

## Validação

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --no-project --python 3.12 --with-requirements requirements-dev.txt pytest -q
uv run --no-project --python 3.12 --with ruff==0.12.9 ruff check app tests
```
