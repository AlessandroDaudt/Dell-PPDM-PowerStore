# Operations runbook

## 1. Preparation

- Confirm the compatibility matrix for PowerStoreOS, PPDM, DDOS and Fabric OS.
- Configure consistent DNS/NTP and trusted TLS certificates.
- Create dedicated automation accounts.
- Confirm that PowerStore is already a PPDM asset source and that discovery works.
- Confirm that DDBoost is enabled on PowerProtect DD.
- On Brocade, use the principal switch for each fabric and confirm the cfg to activate.

## 2. Start the service

```bash
cp .env.example .env
# generate a long secret key and a strong administrative password
docker compose up --build -d
docker compose ps
```

Back up the `sanflow_data` volume. It contains the database and encrypted credentials; restoring it also requires the same `APP_SECRET_KEY`.

## 3. Inventory registration

### PowerStore

Register the management endpoint, port 443, user, TLS setting and every FC target WWPN. Set `fabric=A` or `fabric=B` according to the connectivity design.

### PowerMax

Register the Unisphere endpoint, API version and `symmetrix_id`. The Storage Group block flow requires at least one host and an existing Port Group. Register each host's initiator WWPNs; an optional `powermax_host_id` reuses an existing PowerMax host. The workflow creates or reuses the Storage Group, creates one masking view per selected host and then proceeds to zoning and PPDM.

### PowerStore NAS, PowerScale and Dell Unity NAS

Register the NAS endpoint and select `NAS_SHARE` for an existing filesystem/path or `NAS_DATA` when PowerStore must create the file system first. Select the NAS protocol, path, NAS server and file system when the array exposes them. SANFlow creates or reconciles the share, reads it back to confirm publication, and does not request FC hosts or Brocade zoning.

### Hosts

Register the name exactly as it should appear in PowerStore, the operating system and the HBA WWPNs. If the host already exists, `PowerStore host ID` removes ambiguity.

### Brocade

Register one principal switch per fabric. Provide the FID, active cfg and FOS generation (`9.1` or `9.2`) so the playbook selects the correct commit action.

### PPDM

Register the endpoint on port 8443. **Fetch Data Domains and policies** reads options at change time; SANFlow does not maintain a parallel catalog. For a new NAS policy, select both the Data Domain and the NAS Protection Engine. The engine must already be deployed and reachable by PPDM; this application only references it in the policy.

## 4. First execution

1. Keep **Safe dry-run** enabled.
2. Select the storage, hosts and Brocade switches.
3. Synchronize the selected array and PPDM options. For NAS, confirm the share path/protocol, Data Domain and Protection Engine.
4. Prefer an existing, approved PPDM policy, or choose **Create new policy** and complete the Data Domain, schedule and retention fields.
5. Execute the workflow and open the six-step detail view.
6. For block, validate LUN presentation, masking views/mappings, zone names, members and cfg. For NAS, validate share creation/publication, asset discovery, policy, DD and retention.
7. During an approved change window, repeat in live mode.

## 5. Failures

| Step | Recommended action |
| --- | --- |
| Validation | correct the inventory type, fabric, role or WWN |
| Create LUN / share | check capacity, array filesystem/NAS server, path, policy IDs, TLS and the array account |
| Present block resource | confirm the host WWPNs, PowerMax Port Group/host IDs or PowerStore mapping state |
| Zoning | check FID, cfg, concurrent checksum changes and any open ZoneDB transaction |
| NAS publication | confirm the share/export instance can be read back from the array and the path is reachable |
| PPDM | run the matching block or NAS discovery, confirm the Data Domain and Protection Engine, and verify compatibility |
| Verification | use the workflow IDs to compare against the official consoles |

Do not automatically delete a volume after a zoning or PPDM failure. First determine whether it is already in use or visible in the fabric.

## 6. Application update and rollback

Back up the data volume and `.env`, build the new image and start Compose. To roll back, use the previous image tag; do not replace or remove the data volume.
