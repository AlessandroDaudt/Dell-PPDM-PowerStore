# API do SANFlow e integrações

A especificação OpenAPI navegável fica em `http://<sanflow>:8080/docs`.

## Endpoints principais

| Método | Caminho | Uso |
| --- | --- | --- |
| `POST` | `/api/auth/login` | cria sessão administrativa |
| `GET/POST` | `/api/equipment` | lista ou cadastra equipamentos e WWNs |
| `PUT/DELETE` | `/api/equipment/{id}` | altera ou remove um cadastro |
| `POST` | `/api/equipment/{id}/test` | testa a integração |
| `GET` | `/api/integrations/powerstore/{id}/options` | appliances e políticas atuais |
| `GET` | `/api/integrations/ppdm/{id}/options` | versão, DDs, interfaces, storage units e políticas |
| `POST` | `/api/workflows` | inicia dry-run ou execução live |
| `GET` | `/api/workflows/{id}` | estado e detalhes por etapa |
| `GET` | `/api/audit` | trilha de auditoria |

## PowerStore

O cliente mantém uma sessão Basic Auth e faz `GET /api/rest/cluster` antes de uma mutação para capturar `DELL-EMC-TOKEN`. As principais operações são:

- `POST /api/rest/volume`
- `GET/POST /api/rest/host`
- `GET /api/rest/host_volume_mapping` e `POST /api/rest/host/{id}/attach`
- `GET /api/rest/appliance`, `/fc_port`, `/protection_policy` e `/performance_policy`

## PPDM

- Login: `POST /api/v2/login` e uso do `access_token` como Bearer.
- Opções: `/api/v2/nodes`, `/storage-systems`, `/datadomain-mtrees` e `/protection-policies`.
- Assets: `GET /api/v2/assets` com `type eq "POWERSTORE_BLOCK"`.
- Associação: `POST /api/v2/protection-policies/{id}/asset-assignments`.
- Criação: `POST /api/v2/protection-policies` ou `/api/v3/protection-policies`.

O campo `raw_overrides` permite mesclar propriedades documentadas pela versão exata do PPDM. Use `additional_objectives` para acrescentar objetivos completos de snapshot, replicação ou Cloud Tier sem substituir o objetivo BACKUP gerado pelo SANFlow. Ao marcar uma dessas opções, a API exige o objetivo correspondente; nenhuma seleção avançada é ignorada silenciosamente. A validação estrita do PPDM rejeitará campos desconhecidos, o que é intencional.

## Exemplo

Veja [examples/provision-request.json](examples/provision-request.json). IDs de equipamento são internos ao SANFlow.
