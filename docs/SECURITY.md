# Security

## Credentials

Appliance passwords are encrypted before they are stored in SQLite. The Fernet key is derived from `APP_SECRET_KEY`, which must be supplied by a secret manager or a protected `.env` file. PowerStore, PPDM and Brocade tokens exist only in memory during a call.

The Ansible inventory is created in a temporary directory, contains only the required credentials and is removed at the end. Sensitive tasks use `no_log: true`.

## Production recommendations

- Publish the application behind an HTTPS reverse proxy.
- Restrict access to the management network with a firewall and, where required, an additional proxy authentication layer.
- Change the default username/password and `APP_SECRET_KEY` before the first start.
- Use signed certificates and keep `verify_ssl=true`.
- Apply least privilege and rotate appliance accounts.
- Protect and test restoration of the SQLite volume and its corresponding secret.
- Forward logs and audit events to the SIEM.
- Do not expose `/docs` outside the management network without additional authentication.

## Current limits

- The application has one environment-configured administrative account; integrate a proxy/OIDC provider for multiple users.
- SQLite is suitable for a single container. For high concurrency, migrate the model to PostgreSQL.
- Live mode performs real changes after UI confirmation. ITSM approvals should be completed before calling `/api/workflows`.

## Reporting

Do not open a public issue containing real addresses, WWNs, token-bearing logs or credentials. Remove sensitive data before sharing diagnostics.
