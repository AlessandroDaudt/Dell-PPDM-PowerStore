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

### Hosts

Register the name exactly as it should appear in PowerStore, the operating system and the HBA WWPNs. If the host already exists, `PowerStore host ID` removes ambiguity.

### Brocade

Register one principal switch per fabric. Provide the FID, active cfg and FOS generation (`9.1` or `9.2`) so the playbook selects the correct commit action.

### PPDM

Register the endpoint on port 8443. **Fetch Data Domains and policies** reads options at change time; SANFlow does not maintain a parallel catalog.

## 4. First execution

1. Keep **Safe dry-run** enabled.
2. Select the storage, hosts and Brocade switches.
3. Synchronize PowerStore and PPDM options.
4. Prefer an existing, approved PPDM policy.
5. Execute the workflow and open the six-step detail view.
6. Validate zone names, members, cfg, policy, DD and retention.
7. During an approved change window, repeat in live mode.

## 5. Failures

| Step | Recommended action |
| --- | --- |
| Validation | correct the inventory type, fabric, role or WWN |
| Create LUN | check capacity, appliance, policy IDs, TLS and the PowerStore account |
| Map host | confirm that the WWPN does not belong to another host and review `os_type` |
| Zoning | check FID, cfg, concurrent checksum changes and any open ZoneDB transaction |
| PPDM | run discovery for the PowerStore asset source and confirm compatibility |
| Verification | use the workflow IDs to compare against the official consoles |

Do not automatically delete a volume after a zoning or PPDM failure. First determine whether it is already in use or visible in the fabric.

## 6. Application update and rollback

Back up the data volume and `.env`, build the new image and start Compose. To roll back, use the previous image tag; do not replace or remove the data volume.
