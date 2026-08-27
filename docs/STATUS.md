# Status monitoring

The **Status** menu is an observational dashboard for the infrastructure registered in SANFlow. It shows the newest persisted sample for each appliance, Data Domain and Fibre Channel switch, plus a history window of up to 30 days.

## Collection and retention

- The collector starts with the application and performs an initial collection in a background thread.
- The default interval is 60 seconds. Samples are truncated to the minute and upserted by equipment, component and minute, so retries do not duplicate a sample.
- The browser refreshes the current view every 15 seconds. This improves the switch view without pretending that the persisted sampling rate is sub-minute.
- A cleanup runs after every collection and deletes rows older than `APP_STATUS_RETENTION_DAYS` (30 days by default).
- Configure the interval and retention in `.env`:

```dotenv
APP_STATUS_SAMPLE_INTERVAL_SECONDS=60
APP_STATUS_RETENTION_DAYS=30
```

The retention value is bounded to a safe positive range by the application. The database volume must have enough space for the number of equipment components and the raw vendor payloads collected during that window.

## Equipment coverage

| Type | Collected information |
| --- | --- |
| PowerStore / PowerStore NAS | cluster health, appliances, hardware/nodes, capacity-related fields, network, FC/Ethernet ports, storage containers |
| PowerMax | array system state, SRP information and Storage Groups |
| PowerScale | cluster state, filesystem capacity, system/protocol statistics and drive statistics when exposed by OneFS |
| Dell Unity | system and system capacity, disks, storage resources, filesystems and management interfaces |
| PPDM | PPDM version, discovered Data Domains and protection-storage metrics when exposed by the PPDM version |
| Data Domain | system, capacity, file-system statistics, MTree inventory and network/throughput endpoint when exposed by DDOS |
| Brocade | Fibre Channel port state and Fabric OS interface statistics |
| Cisco MDS | interface state/counters, transceiver, environment and version command output through NX-API |

Register a Data Domain directly in Inventory to obtain DDOS telemetry. A Data Domain discovered only through PPDM is also shown as a component, but its detail is limited to the fields returned by PPDM. Network metrics are marked unavailable when the installed appliance does not expose a supported REST resource; SANFlow never estimates or fabricates them.

For switches, the dashboard presents common fields such as status, speed, utilization/txwait, attenuation or optical power, errors and buffer credits when present. The **Todos os dados coletados** section keeps the complete response/command output, including vendor-specific fields not mapped to the common table.

## API

All routes require the existing administrative session:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/status` | newest sample for every component and collection settings |
| `GET` | `/api/status/history?equipment_id=1&component_key=equipment&hours=720` | historical samples, up to 30 days |
| `POST` | `/api/status/collect` | run an immediate collection and retention cleanup |

The status endpoint returns `OK`, `DEGRADED`, `ERROR` or `UNKNOWN`. An equipment connection failure is saved as an `ERROR` sample, allowing the dashboard to show an outage without stopping collection for other devices. Unsupported optional resources are retained in the metrics payload with `available: false` and a reason.

## Operational notes

Status collection uses the same encrypted inventory credentials as provisioning. It does not perform mutations on arrays, switches, PPDM or Data Domain. Keep TLS validation enabled and grant the status accounts read-only access to the vendor resources. Review the vendor-specific permissions and endpoint availability for the exact firmware installed in the environment.
