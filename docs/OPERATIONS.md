# Operations runbook

## 1. Preparation

- Confirm the compatibility matrix for PowerStoreOS, PPDM, DDOS and Fabric OS.
- Configure consistent DNS/NTP and trusted TLS certificates.
- Create dedicated automation accounts.
- Confirm that PowerStore is already a PPDM asset source and that discovery works.
- Confirm that DDBoost is enabled on PowerProtect DD.
- On Brocade, use the principal switch for each fabric and confirm the cfg to activate.
- On Cisco MDS, enable NX-API over HTTPS, confirm the API port and verify the target VSAN/zoneset before a live run.

## 2. Start the service

```bash
cp .env.example .env
# generate a long secret key and a strong administrative password
docker compose up --build -d
docker compose ps
```

Back up the `sanflow_data` volume. It contains the database and encrypted credentials; restoring it also requires the same `APP_SECRET_KEY`.

## 2.1 Status monitoring

Open **Status** after registering the infrastructure. The first collection is started with the application; **Coletar agora** runs an immediate cycle. The default persistent sample interval is one minute and the browser refreshes the current view every 15 seconds. Historical samples are retained for 30 days and are automatically deleted after that period.

For Data Domain disk and network usage, register the Data Domain endpoint directly as `DATA_DOMAIN` using its embedded REST port (3009 by default) and a read-only account. PPDM-discovered Data Domains remain visible, but only PPDM-returned fields are available. On switches, inspect the common port table and expand **Todos os dados coletados** for vendor-specific attenuation, optical power, error counters, txwait and buffer-credit fields.

If a metric is not supported by the firmware or API version, the dashboard labels it `N/A` and preserves the reason in the raw details. This is expected and is different from a collection error.

## 3. Inventory registration

### PowerStore

Register the management endpoint, port 443, user, TLS setting and every FC target WWPN. Set `fabric=A` or `fabric=B` according to the connectivity design.

### PowerMax

Register the Unisphere endpoint, API version and `symmetrix_id`. The Storage Group block flow requires at least one host and an existing Port Group. Register each host's initiator WWPNs; an optional `powermax_host_id` reuses an existing PowerMax host. The workflow creates or reuses the Storage Group, creates one masking view per selected host and then proceeds to zoning and PPDM.

### PowerStore NAS, PowerScale and Dell Unity NAS

Register the NAS endpoint and select `NAS_SHARE` for an existing filesystem/path or `NAS_DATA` when PowerStore must create the file system first. Select the NAS protocol, path, NAS server and file system when the array exposes them. SANFlow creates or reconciles the share, reads it back to confirm publication, and does not request FC hosts or Brocade/Cisco MDS zoning.

### Hosts

Register the name exactly as it should appear in PowerStore, the operating system and the HBA WWPNs. If the host already exists, `PowerStore host ID` removes ambiguity.

### Brocade

Register one principal switch per fabric. Provide the FID, active cfg and FOS generation (`9.1` or `9.2`) so the playbook selects the correct commit action.

### Cisco MDS

Register one MDS switch per fabric with type `CISCO_MDS`, NX-API credentials, HTTPS port and `api_version` (normally `1.2`). Set `fabric` (`A` or `B`), `default_vsan` and `default_zoneset` in the settings. Add its registered ID to `fabric_ids` in a block request. SANFlow reads the current zone and zoneset in that VSAN, adds only missing PWWNs/members and activates the zoneset when requested. `peer_zoning` is not supported by this adapter.

### PPDM

Register the endpoint on port 8443. **Fetch Data Domains and policies** reads options at change time; SANFlow does not maintain a parallel catalog. For a new NAS policy, select both the Data Domain and the NAS Protection Engine. The engine must already be deployed and reachable by PPDM; this application only references it in the policy.

## 4. First execution

1. Keep **Safe dry-run** enabled.
2. Select the storage, hosts and Brocade or Cisco MDS switches.
3. Synchronize the selected array and PPDM options. For NAS, confirm the share path/protocol, Data Domain and Protection Engine.
4. Prefer an existing, approved PPDM policy, or choose **Create new policy** and complete the Data Domain, schedule and retention fields.
5. Execute the workflow and open the six-step detail view.
6. For block, validate LUN presentation, masking views/mappings, zone names, members and cfg/zoneset. For NAS, validate share creation/publication, asset discovery, policy, DD and retention.
7. During an approved change window, repeat in live mode.

## 5. Failures

| Step | Recommended action |
| --- | --- |
| Validation | correct the inventory type, fabric, role or WWN |
| Create LUN / share | check capacity, array filesystem/NAS server, path, policy IDs, TLS and the array account |
| Present block resource | confirm the host WWPNs, PowerMax Port Group/host IDs or PowerStore mapping state |
| Zoning | Brocade: check FID, cfg, concurrent checksum changes and open ZoneDB transactions. Cisco MDS: check NX-API reachability, VSAN, zoneset and command output |
| NAS publication | confirm the share/export instance can be read back from the array and the path is reachable |
| PPDM | run the matching block or NAS discovery, confirm the Data Domain and Protection Engine, and verify compatibility |
| Verification | use the workflow IDs to compare against the official consoles |

Do not automatically delete a volume after a zoning or PPDM failure. First determine whether it is already in use or visible in the fabric.

## 6. Application update and rollback

Back up the data volume and `.env`, build the new image and start Compose. To roll back, use the previous image tag; do not replace or remove the data volume.
