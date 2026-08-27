# SANFlow Dell

Web control plane for automating, in one workflow, Dell PowerStore volumes or block volume groups, presentation to physical hosts, Fibre Channel zoning on Brocade or Cisco MDS switches and volume assignment to a protection policy in Dell PowerProtect Data Manager (PPDM).

> Status: initial release ready for lab and acceptance testing. **Dry-run is the default.** Before the first production use, validate the exact PowerStoreOS, PPDM, Fabric OS and Cisco NX-OS versions in the vendor documentation and run a controlled change.

## End-to-end flow

```mermaid
flowchart LR
    A[1. Validate inventory<br/>WWNs · fabrics · credentials] --> B[2. PowerStore REST<br/>create volume]
    B --> C[3. PowerStore REST<br/>register host and map LUN]
    C --> D[4. Fibre Channel adapter<br/>Brocade FOS or Cisco MDS NX-API<br/>create zones and activate cfg]
    D --> E[5. PPDM REST<br/>discover asset]
    E --> F[6. PPDM REST<br/>assign policy]
    F --> G[Data Domain<br/>backup · retention · replication]

    B -. volume ID and WWN .-> H[(Audit trail)]
    D -. ZoneDB checksum .-> H
    F -. policy and asset IDs .-> H
```

### API sequence

```mermaid
sequenceDiagram
    actor O as Operator
    participant S as SANFlow
    participant P as PowerStore
    participant B as Brocade FOS / Cisco MDS NX-API
    participant M as PPDM
    participant D as Data Domain

    O->>S: Submit LUN specification
    S->>S: Validate types, WWPNs and fabrics
    S->>P: GET /api/rest/cluster (session + CSRF)
    S->>P: POST /api/rest/volume
    P-->>S: volume ID + WWN
    loop Each physical host
        S->>P: GET/POST /api/rest/host
        S->>P: POST /api/rest/host/{id}/attach
    end
    alt Brocade fabric
        S->>B: ansible-playbook
        B->>B: FOS REST login and reconcile zone/cfg
        B->>B: Save or activate with ZoneDB checksum
    else Cisco MDS fabric
        S->>B: POST /ins (cli_show_ascii / cli_conf)
        B->>B: Reconcile zone and zoneset in VSAN
        B->>B: Activate zoneset when requested
    end
    S->>M: POST /api/v2/login
    S->>M: GET /api/v2/assets (wait for discovery)
    alt Existing policy
        S->>M: POST /protection-policies/{id}/asset-assignments
    else New policy
        S->>M: POST /api/v2 or v3/protection-policies
        S->>M: POST /protection-policies/{id}/asset-assignments
    end
    M->>D: Schedule backup according to objective
    S-->>O: Per-step result and technical IDs
```

### Fibre Channel zoning flow

```mermaid
flowchart TD
    L[Selected Fibre Channel switch] --> T{Fabric type}
    T -- Brocade --> B[FOS REST login]
    T -- Cisco MDS --> C[NX-API POST /ins]
    B --> R[Read current zoning]
    C --> Q[Read zones and zoneset in VSAN]
    R --> X{Zone and cfg need changes?}
    Q --> Y{Zone and zoneset need changes?}
    X -- no --> O[Keep current configuration]
    Y -- no --> O
    X -- yes --> Z[Reconcile zone, cfg and checksum]
    Y -- yes --> N[Reconcile zone and zoneset]
    Z --> A{Activate cfg?}
    N --> A
    A -- yes --> E[Activate effective cfg / zoneset]
    A -- no --> O
    E --> O
```

### Failure handling

```mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> RUNNING
    RUNNING --> COMPLETED: six steps confirmed
    RUNNING --> FAILED: REST error, timeout or playbook failure
    FAILED --> Analysis: step detail + audit event
    Analysis --> Retry: correct cause and submit a new request
    note right of FAILED
      SANFlow does not automatically delete
      an already-created volume. Remediation
      is deliberate to prevent data loss.
    end note
```

## What the interface provides

- Registration of PowerStore, PPDM, Brocade or Cisco MDS switches and physical hosts.
- Multiple WWPNs per equipment entry, separated by fabric and function (`INITIATOR`, `TARGET` or `SWITCH`).
- Live retrieval of PowerStore appliances and policies.
- Live retrieval of PPDM versions, Data Domains, preferred interfaces, storage units and PowerStore policies.
- Creation of PPDM v2 or v3 policies, or assignment to an existing policy.
- Native PowerStore individual-volume and block-volume-group provisioning, including group mapping when supported by PowerStoreOS.
- Native PowerMax Storage Group provisioning through Unisphere REST, with array, SRP, SLO and volume-count parameters.
- PowerMax Storage Group presentation to the selected hosts through native masking views that bind the Storage Group, Port Group and host initiators; optional Brocade or Cisco MDS zoning remains part of the block flow.
- Fibre Channel zoning through the selected adapter: Brocade FOS via Ansible or Cisco MDS through NX-API, with VSAN/zoneset reconciliation and optional activation.
- PowerStore NAS file-system and share discovery/reconciliation, with PPDM NAS policy assignment through a selected Protection Engine.
- PowerScale SMB/NFS share discovery and reconciliation through OneFS PAPI, with the same PPDM NAS Protection Engine workflow.
- Dell Unity CIFS/NFS share discovery and reconciliation through Unisphere REST, with CSRF protection and the same PPDM NAS Protection Engine workflow.
- Hourly, daily, weekly or monthly schedules; windows, retention, Retention Lock, consistency and backup level.
- Live inspection of existing policy objectives; Snapshot, Replication and Cloud Tier can be required and defined through version-specific JSON without silently ignoring incomplete selections.
- End-to-end dry-run, live execution and detailed per-step history.
- The application’s own OpenAPI specification at `/docs`.

## Architecture

```mermaid
flowchart TB
    UI[Responsive web SPA<br/>HTML · CSS · JavaScript] --> API[FastAPI]
    API --> DB[(Persistent SQLite)]
    API --> ORCH[Workflow orchestrator]
    ORCH --> PSC[PowerStore client<br/>Basic Auth + CSRF]
    ORCH --> PPC[PPDM client<br/>Bearer token · v2/v3]
    ORCH --> ANS[ansible-playbook]
    ANS --> FOS[Brocade Fabric OS REST/YANG]
    ORCH --> MDS[Cisco MDS NX-API /ins]
    PSC --> PS[PowerStore]
    PPC --> PPDM[PowerProtect Data Manager]
    PPDM --> DD[PowerProtect DD]
```

| Component | Responsibility |
| --- | --- |
| FastAPI | authentication, inventory, live options, workflows and audit events |
| SQLite | inventory, WWNs, execution state and events; persisted in a Docker volume |
| REST clients | sessions, tokens, timeouts, HTTP validation and PPDM v2/v3 compatibility |
| Ansible / NX-API | idempotent zoning per fabric using Brocade FOS REST or Cisco MDS `/ins` |
| SPA | registration, provisioning, backup selection and operational tracking |

## Quick start with Docker

Prerequisites: Docker Engine 24+ and Docker Compose v2.

```bash
cp .env.example .env
# edit APP_SECRET_KEY, APP_ADMIN_PASSWORD and the remaining settings
docker compose up --build -d
```

Open `http://localhost:8080`. Service health is available at `GET /health`.

1. Register the selected PowerStore, PowerMax, PowerScale or Unity endpoint. For NAS, register the NAS appliance; for block, register target WWPNs per fabric.
2. For block resources, register each physical host with initiator WWPNs and the principal Brocade or Cisco MDS switch for each fabric. PowerMax also needs a Symmetrix ID and an existing Port Group.
3. Register PPDM and, for a new NAS policy, select a Data Domain and NAS Protection Engine after synchronization.
4. Use **Test** in the inventory and run the first provisioning in dry-run mode.
5. Review all six steps: NAS share creation/publication or block LUN presentation/zoning, followed by PPDM protection.
6. Only then run a live change window.

See the detailed runbook in [docs/OPERATIONS.md](docs/OPERATIONS.md).

### Cisco MDS Fibre Channel

Register one Cisco MDS endpoint per fabric with NX-API enabled over HTTPS. Set the NX-API version (normally `1.2`), the default VSAN and zoneset. The block workflow reads the current zones/zoneset through `cli_show_ascii`, then reconciles and optionally activates the zoneset through `cli_conf`. Peer zoning is currently supported only on Brocade.

## Repository layout

```text
app/
  api.py                    application endpoints
  models.py                 inventory, WWNs, workflows and audit events
  services/
    powerstore.py           PowerStore REST client
    ppdm.py                 PPDM v2/v3 REST client
    ansible_runner.py       controlled Brocade playbook execution
    cisco_mds.py            Cisco MDS NX-API zoning client
    orchestrator.py         provisioning state machine
  static/                   web interface
playbooks/
  brocade_zoning.yml        FOS REST zoning for 9.1/9.2+
docs/                       architecture, operations, security and references
tests/                      unit tests with mocked APIs
```

## Important guardrails

- Equipment passwords are encrypted with Fernet using a key derived from `APP_SECRET_KEY`.
- Do not change `APP_SECRET_KEY` without planning credential re-encryption first.
- Keep `verify_ssl=true` and install trusted certificates on the appliances. Disabling validation is intended only for controlled labs.
- Use dedicated accounts with the minimum privileges required by the endpoints.
- One principal switch per fabric is sufficient; the ZoneDB is distributed across the fabric. Cisco MDS uses one configured NX-API endpoint per selected fabric.
- Cisco MDS zoning supports standard zones and zonesets in a VSAN. Peer zoning is currently limited to Brocade.
- Volumes already associated with a local PowerStore policy may be incompatible with PPDM protection depending on the version. Do not combine PPDM-integrated and PowerStore-integrated remote backup.
- Provisioning is progressive and has no automatic destructive rollback. See [docs/SECURITY.md](docs/SECURITY.md) and [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Documentation

- [Architecture and decisions](docs/ARCHITECTURE.md)
- [Implementation stages and branches](docs/IMPLEMENTATION_STAGES.md)
- [Operations runbook](docs/OPERATIONS.md)
- [API and integrations](docs/API.md)
- [Security](docs/SECURITY.md)
- [Official references consulted](docs/OFFICIAL_REFERENCES.md)

## Primary official sources

- [Dell PowerStore REST API Developers Guide](https://www.dell.com/support/manuals/en-us/powerstore-1000/pwrstr-apidevg/reference-content?guid=guid-20ffc160-8ff2-45a7-b678-1a5f7bc75569)
- [Dell PowerStore API Developer Portal](https://developer.dell.com/apis/3898/versions/3.2.0/docs/Intro-files/01-Overview/01-The-PowerStore-REST-API.md)
- [PowerProtect Data Manager NAS User Guide](https://www.dell.com/support/manuals/en-us/enterprise-copy-data-management/pp-dm_19.22_nas_ug/powerprotect-data-manager-overview?guid=guid-46a6e468-104c-4c76-9131-46bf666e2191)
- [Dell PowerScale OneFS API](https://developer.dell.com/api/export-pdf/390010/version/9.2.0.0?uuid=4088)
- [Dell Unity REST API](https://developer.dell.com/apis/3028/versions/5.2.0/docs/TUTORIALS/tutorials.md)
- [Dell PowerProtect Data Manager Public REST API](https://developer.dell.com/apis/4378)
- [Dell PPDM Storage Array User Guide](https://www.dell.com/support/manuals/en-us/enterprise-copy-data-management/pp-dm_19.22_storage_array_ug/powerprotect-data-manager-for-storage-arrays?guid=guid-4ea1b71a-e96a-4e53-8c0e-84d4a6d1d258&lang=en-us)
- [Broadcom SAN Design and Best Practices — REST API/YANG](https://docs.broadcom.com/doc/53-1004781)
- [Cisco MDS NX-API Zoning Reference](https://developer.cisco.com/cisco-mds-9000-series-nx-api-reference/latest/zoning/)
- [Cisco MDS NX-OS Programmability Guide](https://www.cisco.com/c/en/us/td/docs/dcn/mds9000/sw/9x/programmability/cisco-mds-9000-nx-os-programmability-guide-9x/nx_api.html)

## License

MIT. See [LICENSE](LICENSE).
