# Etapas de implementacao

As branches de integracao sao cumulativas. Cada etapa mantem o fluxo anterior e adiciona um dominio.

| Etapa | Branch | Entrega |
| --- | --- | --- |
| 0 | `main` | Volume individual PowerStore |
| 1 | `feature/powerstore-block` | Volumes individuais e grupos de volumes block PowerStore |
| 2 | `feature/powermax-storage-groups` | Storage Groups PowerMax, masking views para hosts e zoning Brocade |
| 3 | `feature/powerstore-nas` | File systems/shares PowerStore NAS, publicacao e rotina PPDM NAS |
| 4 | `feature/powerscale-nas` | Shares SMB/NFS PowerScale, publicacao e rotina PPDM NAS |
| 5 | `feature/dell-unity-nas` | Shares CIFS/NFS Dell Unity, publicacao e rotina PPDM NAS |

## Fluxo de backup de storage

Para volumes block, a execucao segue esta ordem:

1. validar hosts, WWPNs, fabrics, credenciais e capacidade;
2. criar a LUN ou o grupo de volumes no array;
3. apresentar a LUN aos hosts (mappings PowerStore ou masking view PowerMax);
4. criar/ativar as zonas Brocade quando habilitado;
5. criar ou reutilizar a rotina PPDM com Data Domain, interface, storage unit, agenda e retencao;
6. confirmar o recurso e registrar IDs no workflow.

O PowerMax usa Storage Group + masking view. O Port Group precisa existir no array e pode ser
informado no cadastro do PowerMax ou na solicitacao. Hosts inexistentes podem ser criados pela
selecao `createHostParam`, usando os WWPNs cadastrados.

## Fluxo NAS

Para NAS, a execucao nao usa apresentacao de LUN nem zoning FC:

1. validar o servidor NAS, protocolo, caminho e credenciais;
2. criar ou reconciliar o share; em PowerStore `NAS_DATA` tambem cria o file system;
3. publicar o share e confirmar a leitura dele no array;
4. criar ou reutilizar a rotina PPDM NAS com o Data Domain selecionado, interface, storage unit,
   agenda, retencao e NAS Protection Engine;
5. aguardar a descoberta do asset no PPDM e associa-lo a politica.

O Data Domain e o NAS Protection Engine sao obrigatorios ao criar uma politica NAS. A aplicacao
configura a referencia na politica, mas nao instala nem provisiona o Protection Engine.

## Validacao

Na raiz do repositorio:

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --no-project --python 3.12 --with-requirements requirements-dev.txt pytest -q
uv run --no-project --python 3.12 --with ruff==0.12.9 ruff check app tests
```
