# Architecture

## Scope

SANFlow is a control plane, not a data plane. It coordinates management systems; I/O and backup traffic continue to flow directly between hosts, PowerStore and PowerProtect DD.

In this scope, “presenting a LUN” means registering/reconciling host WWPNs in PowerStore or creating a PowerMax masking view, then configuring zoning across the fabrics. SCSI rescan, multipath and filesystem work inside the operating system remain host-side activities, so SANFlow does not need SSH credentials for servers.

## Domains

1. **Inventory:** equipment, endpoints, encrypted credentials, device-specific settings and WWNs.
2. **Discovery:** real-time PowerStore block, PowerMax, PowerStore NAS, PowerScale and PPDM option retrieval.
3. **Orchestration:** persistent, sequential and audited workflows.
4. **Integrations:** REST clients with sessions, TLS, timeouts and normalized errors.
5. **Zoning:** a Fibre Channel adapter layer; Brocade uses an isolated Ansible process, while Cisco MDS uses direct NX-API calls.
6. **Interface:** a SPA with no Node toolchain, served by the same container.

## Data model

```mermaid
erDiagram
    EQUIPMENT ||--o{ WWN : owns
    WORKFLOW ||--|{ WORKFLOW_STEP : records
    EQUIPMENT {
      int id
      string type
      string management_address
      string encrypted_password
      json settings
    }
    WWN {
      string value
      string fabric
      string role
    }
    WORKFLOW {
      string status
      bool dry_run
      json request
      string volume_id
      string policy_id
    }
    WORKFLOW_STEP {
      int step_order
      string status
      json details
    }
```

## Idempotency

- Inventory names are unique and WWNs are unique within an equipment entry.
- Existing PowerStore hosts are reused by `powerstore_host_id` or by name.
- Existing mappings between a host and volume are detected.
- A PowerStore block group is represented by the array as a `volume_group` and its members are created with `volume_group_id`; group host mapping uses the native group endpoint when available.
- A PowerMax Storage Group is reconciled by name through Unisphere REST and is provisioned using the array's SRP/SLO policy; repeated runs do not create a duplicate group.
- A PowerStore NAS resource is reconciled by share path. `NAS_DATA` creates a file system before the share; both resource types are discovered and protected as PPDM NAS assets.
- A PowerMax Storage Group is presented through a masking view that binds the Storage Group, a Port Group and each selected host. Missing PowerMax hosts are created from the registered initiator WWPNs.
- The playbook reads the defined configuration, does not recreate existing zones and preserves cfg members. Cisco MDS reads the current VSAN zone/zoneset, adds only missing PWWN or zoneset members and activates only when requested.
- PPDM assignment runs after asset discovery. A new run should use an existing policy or a new policy name to avoid duplicates.

## Consistency and compensation

There is no distributed transaction across the four products. Each step is confirmed before the next one. If a later step fails, earlier resources remain and their IDs are stored in the workflow. This prevents an automatic rollback from deleting a LUN that a host may already have discovered.

## Compatibility

- PowerStore: `/api/rest` base URI, with `DELL-EMC-TOKEN` for mutations.
- PowerMax: Unisphere `/univmax/restapi/{version}` with Basic Auth and a configured Symmetrix ID.
- PowerStore NAS: the same PowerStore REST session and CSRF token as block resources, using file-service endpoints.
- PowerScale: OneFS PAPI with Basic Auth; SMB and NFS share paths are reconciled before PPDM discovery.
- Dell Unity: Unisphere REST with Basic Auth, `X-EMC-REST-CLIENT` and a session CSRF token; CIFS and NFS shares are reconciled by path.
- PPDM NAS: a NAS asset source and a deployed NAS Protection Engine are prerequisites for live protection.
- PPDM: v2 login; v2 policies through 19.16 and v3 from 19.17 onward, following Dell’s published transition.
- Fabric OS: REST login, `brocade-zone` YANG module, ZoneDB checksum and different actions for FOS 9.1 and 9.2+.
- Cisco MDS: NX-API `/ins` with `cli_show_ascii` for inspection and `cli_conf` for VSAN zone/zoneset reconciliation. The adapter supports standard zoning; peer zoning remains Brocade-only.
