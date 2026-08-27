# Official references consulted

Research performed in August 2026. The documentation embedded in each appliance (`/swaggerui` or its local OpenAPI specification) remains authoritative for the target environment.

## Dell PowerStore

- [PowerStore REST API Developers Guide](https://www.dell.com/support/manuals/en-us/powerstore-1000/pwrstr-apidevg/reference-content?guid=guid-20ffc160-8ff2-45a7-b678-1a5f7bc75569) — resource reference and appliance OpenAPI.
- [The PowerStore REST API](https://www.dell.com/support/manuals/en-us/powerstore-9000t/pwrstr-apidevg/the-powerstore-rest-api?guid=guid-33000e1c-83e0-4bf3-8fb3-44b65d57d2dc) — capabilities and SSL security.
- [Connecting and authenticating](https://www.dell.com/support/manuals/en-us/powerstore-9000t/pwrstr-apidevg/connecting-and-authenticating?guid=guid-cb6a0ceb-8323-48e6-b752-1d0429aa1594&lang=en-us) — Basic Auth, sessions and `DELL-EMC-TOKEN`.
- [PowerStore API — Developer Portal](https://developer.dell.com/apis/3898/versions/3.2.0/docs/Intro-files/01-Overview/01-The-PowerStore-REST-API.md) — volume, host and mapping tasks.

## Dell PowerProtect Data Manager

- [PPDM Public REST API](https://developer.dell.com/apis/4378) — v2/v3 contracts, assets, policies, storage and authentication.
- [PPDM 19.22 Storage Array User Guide](https://www.dell.com/support/manuals/en-us/enterprise-copy-data-management/pp-dm_19.22_storage_array_ug/powerprotect-data-manager-for-storage-arrays?guid=guid-4ea1b71a-e96a-4e53-8c0e-84d4a6d1d258&lang=en-us) — PowerStore volumes/volume groups, snapshots, backup and replication.
- [Configure a primary backup objective](https://www.dell.com/support/manuals/en-us/enterprise-copy-data-management/pp-dm_19.20_powerstore_storage_ug/configure-a-primary-backup-objective?guid=guid-84ec84f3-e139-4e11-95b0-196381a5cda3&lang=en-us) — DD, storage unit, schedule and retention.
- [Dell automation repository for PPDM](https://github.com/dell/powerprotect-data-manager) — official login, v2/v3 policy, Data Domain and asset-assignment examples.
- [Integrate PowerStore with PowerProtect DD](https://www.dell.com/support/kbdoc/en-us/000215639/how-to-integrate-powerstore-with-powerprotect-data-domain-for-data-backup) — warning not to combine PPDM-integrated and PowerStore-integrated remote backup.

## Broadcom Brocade Fabric OS

- [SAN Design and Best Practices](https://docs.broadcom.com/doc/53-1004781) — REST/YANG and `defined-configuration` overview.
- [Fabric OS downloads and documentation](https://knowledge.broadcom.com/external/article/267270/fos-fabric-os-downloads-and-documentatio.html) — release-specific documentation.
- [Fabric OS 8.2.3 release notes](https://docs.broadcom.com/doc/FOS-823f-RN) — official REST and YANG support.

## Cisco MDS NX-API

- [Cisco MDS 9000 Series NX-API Zoning Reference](https://developer.cisco.com/cisco-mds-9000-series-nx-api-reference/latest/zoning/) — official `cli_show_ascii` and `cli_conf` zoning examples for zones, zonesets and activation.
- [Cisco MDS NX-OS Programmability Guide](https://www.cisco.com/c/en/us/td/docs/dcn/mds9000/sw/9x/programmability/cisco-mds-9000-nx-os-programmability-guide-9x/nx_api.html) — NX-API endpoint, payload and transport configuration.

## Derived decisions

- Keep a persistent PowerStore session and obtain CSRF before every mutation.
- Always log in to PPDM through v2; select the policy endpoint (v2 or v3) from the node version.
- Retrieve DDs from `/api/v2/storage-systems` and storage units from `/api/v2/datadomain-mtrees`.
- Zone WWPN members within the same fabric, preserve cfg entries and obtain a checksum before save/activation.
- Use the Cisco MDS `/ins` endpoint with JSON `ins_api` payloads; read the current VSAN state before sending `cli_conf` changes and activate a zoneset only when requested.
