# Referências oficiais consultadas

Consulta realizada em agosto de 2026. A versão embarcada em cada appliance (`/swaggerui` ou OpenAPI local) continua sendo a autoridade para o ambiente.

## Dell PowerStore

- [PowerStore REST API Developers Guide](https://www.dell.com/support/manuals/en-us/powerstore-1000/pwrstr-apidevg/reference-content?guid=guid-20ffc160-8ff2-45a7-b678-1a5f7bc75569) — referência de recursos e OpenAPI no appliance.
- [The PowerStore REST API](https://www.dell.com/support/manuals/en-us/powerstore-9000t/pwrstr-apidevg/the-powerstore-rest-api?guid=guid-33000e1c-83e0-4bf3-8fb3-44b65d57d2dc) — capacidades e segurança SSL.
- [Connecting and authenticating](https://www.dell.com/support/manuals/en-us/powerstore-9000t/pwrstr-apidevg/connecting-and-authenticating?guid=guid-cb6a0ceb-8323-48e6-b752-1d0429aa1594&lang=en-us) — Basic Auth, sessão e `DELL-EMC-TOKEN`.
- [PowerStore API — Developer Portal](https://developer.dell.com/apis/3898/versions/3.2.0/docs/Intro-files/01-Overview/01-The-PowerStore-REST-API.md) — tarefas de volume, host e mappings.

## Dell PowerProtect Data Manager

- [PPDM Public REST API](https://developer.dell.com/apis/4378) — contratos v2/v3, assets, políticas, storage e autenticação.
- [PPDM 19.22 Storage Array User Guide](https://www.dell.com/support/manuals/en-us/enterprise-copy-data-management/pp-dm_19.22_storage_array_ug/powerprotect-data-manager-for-storage-arrays?guid=guid-4ea1b71a-e96a-4e53-8c0e-84d4a6d1d258&lang=en-us) — suporte a volumes/volume groups PowerStore, snapshots, backup e réplica.
- [Configure a primary backup objective](https://www.dell.com/support/manuals/en-us/enterprise-copy-data-management/pp-dm_19.20_powerstore_storage_ug/configure-a-primary-backup-objective?guid=guid-84ec84f3-e139-4e11-95b0-196381a5cda3&lang=en-us) — DD, storage unit, agenda e retenção.
- [Dell automation repository for PPDM](https://github.com/dell/powerprotect-data-manager) — exemplos oficiais de login, políticas v2/v3, Data Domain e asset assignments.
- [Integrate PowerStore with PowerProtect DD](https://www.dell.com/support/kbdoc/en-us/000215639/how-to-integrate-powerstore-with-powerprotect-data-domain-for-data-backup) — alerta para não combinar PPDM-integrated com PowerStore-integrated remote backup.

## Broadcom Brocade Fabric OS

- [SAN Design and Best Practices](https://docs.broadcom.com/doc/53-1004781) — visão REST/YANG e `defined-configuration`.
- [Fabric OS downloads and documentation](https://knowledge.broadcom.com/external/article/267270/fos-fabric-os-downloads-and-documentatio.html) — documentação por release.
- [Fabric OS 8.2.3 release notes](https://docs.broadcom.com/doc/FOS-823f-RN) — suporte REST e YANG oficiais.

## Decisões derivadas

- Sessão PowerStore persistente e CSRF antes de qualquer mutação.
- Login PPDM sempre v2; escolha de políticas v2/v3 baseada na versão do node.
- DDs obtidos por `/api/v2/storage-systems` e storage units por `/api/v2/datadomain-mtrees`.
- Zoning com membros WWPN na mesma fabric, preservação da cfg e checksum antes de salvar/ativar.
