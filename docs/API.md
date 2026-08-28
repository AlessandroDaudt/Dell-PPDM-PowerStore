# San Flow API and integrations

The interactive OpenAPI specification is available at `http://<sanflow>:8080/docs`.

## Main endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/login` | creates an administrative session |
| `GET/POST` | `/api/equipment` | lists or registers equipment and WWNs |
| `PUT/DELETE` | `/api/equipment/{id}` | updates or removes an inventory entry |
| `POST` | `/api/equipment/{id}/test` | tests an integration |
| `GET` | `/api/integrations/powerstore/{id}/options` | current appliances and policies |
| `GET` | `/api/integrations/ppdm/{id}/options` | version, DDs, interfaces, storage units and policies |
| `POST` | `/api/workflows` | starts a dry-run or live execution |
| `GET` | `/api/workflows/{id}` | workflow state and per-step details |
| `GET` | `/api/audit` | audit trail |

## PowerStore

The client keeps a Basic Auth session and calls `GET /api/rest/cluster` before a mutation to capture `DELL-EMC-TOKEN`. The main operations are:

- `POST /api/rest/volume`
- `POST /api/rest/volume_group`, followed by `POST /api/rest/volume` with `volume_group_id` for block volume groups.
- `GET/POST /api/rest/host`
- `GET /api/rest/host_volume_mapping` and `POST /api/rest/host/{id}/attach`
- `POST /api/rest/volume_group/{id}/attach` for native group mapping; older arrays fall back to individual member mappings.
- `GET /api/rest/appliance`, `/fc_port`, `/protection_policy` and `/performance_policy`

## PowerMax

- `GET /api/integrations/powermax/{id}/options` discovers the configured Symmetrix storage groups, hosts, Port Groups and masking views.
- Native provisioning uses `POST /univmax/restapi/{version}/sloprovisioning/symmetrix/{symmetrixId}/storagegroup`.
- Storage presentation uses a masking view: `POST .../sloprovisioning/symmetrix/{symmetrixId}/maskingview`.
- The request supports `storageGroupId`, `srpId`, SLO, emulation, capacity, count, Port Group and version-specific `raw_overrides`.
- The Port Group is selected from the PowerMax options or the equipment default. A missing host is created with its registered initiator WWPNs, then the masking view binds host, Port Group and Storage Group.
- A block workflow does not finish at Storage Group creation: it presents the group to every selected host, then optionally configures Brocade zoning and assigns the discovered block asset to PPDM.

## PowerStore NAS

- `GET /api/integrations/powerstore/{id}/options` returns NAS servers, file systems, SMB shares and NFS exports when the equipment is registered as `POWERSTORE_NAS`.
- `POST /api/rest/file_system` creates NAS data and `POST /api/rest/smb_share` or `POST /api/rest/nfs_export` reconciles a share.
- NAS workflows do not configure FC hosts or Brocade zoning. They discover the resulting share in PPDM and assign it to a centralized NAS policy.
- The workflow explicitly verifies publication with a GET of the created/reused share before it creates or reuses the PPDM policy.
- `GET /api/integrations/ppdm/{id}/nas-options` exposes NAS policies and Protection Engines. A live NAS policy workflow must use an engine deployed and reachable from the NAS.

## PowerScale

- `GET /api/integrations/powerscale/{id}/options` reads OneFS SMB shares, NFS exports and access zones.
- The adapter uses `/platform/{version}/protocols/smb/shares` and `/platform/{version}/protocols/nfs/exports` with Basic Auth.
- `NAS_SHARE` reconciles the share by name/path and preserves existing shares; a missing share is created with `raw_overrides` available for zone and permission fields.
- After reconciliation, publication is verified by reading the SMB share or NFS export back from OneFS.

## Dell Unity

- `GET /api/integrations/unity/{id}/options` reads NAS servers, file systems, CIFS shares and NFS shares from Unisphere.
- The adapter uses `/api/types/cifsShare/instances`, `/api/types/nfsShare/instances`, `/api/types/filesystem/instances` and `/api/types/nasServer/instances`.
- Unity requests send `X-EMC-REST-CLIENT: true`; mutating requests also send the CSRF token captured from a system-information GET.
- Unity shares are then discovered in PPDM and assigned to a centralized NAS policy using the configured NAS Protection Engine.
- After reconciliation, publication is verified by reading the CIFS share or NFS share instance back from Unisphere.

## PPDM

- Login: `POST /api/v2/login`, then use `access_token` as a Bearer token.
- Options: `/api/v2/nodes`, `/storage-systems`, `/datadomain-mtrees` and `/protection-policies`.
- Assets: `GET /api/v2/assets`; NAS assets are matched by share name/path and block assets by volume or Storage Group name.
- Assignment: `POST /api/v2/protection-policies/{id}/asset-assignments`.
- Creation: `POST /api/v2/protection-policies` or `/api/v3/protection-policies`.

The `raw_overrides` field merges properties documented for the exact PPDM version. Use `additional_objectives` to append complete Snapshot, Replication or Cloud Tier objectives without replacing the BACKUP objective generated by San Flow. When one of these options is selected, the API requires the corresponding objective; no advanced selection is silently ignored. For NAS `CREATE_POLICY`, `data_domain_id` and `nas_protection_engine_id` are mandatory. Strict PPDM validation rejects unknown fields intentionally.

## Example

See [examples/provision-request.json](examples/provision-request.json) for PowerStore block,
[examples/provision-powermax-request.json](examples/provision-powermax-request.json) for Storage
Group presentation and [examples/provision-nas-request.json](examples/provision-nas-request.json)
for share publication plus Data Domain/Protection Engine selection. Equipment IDs are internal to San Flow.
