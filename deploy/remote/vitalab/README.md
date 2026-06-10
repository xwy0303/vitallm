# Vitalab Portable Deployment

This directory defines a portable deployment skeleton for moving the Shengji
project to Linux or macOS servers. It keeps server-specific values in inventory
files and keeps secrets out of git.

## Design Goal

The deployment must be reproducible on a fresh server by changing inventory and
secret files only. Do not hard-code hostnames, usernames, root paths, ports, or
Cloudflare tunnel URLs into reusable scripts.

Current first target:

```text
host: 10.7.117.30
user: gjsk
root: /home/gjsk/project/vitalab
```

## Directory Contents

```text
deploy/remote/vitalab/
  inventory.example.env          # portable inventory template
  inventory.gpu.env.example      # first target example
  runtime.env.example            # non-secret runtime defaults
  compose.yaml                   # portable Docker Compose stack
  config/runtime.remote.yaml     # remote API runtime config
  docker/                        # API/Web Docker build assets
  scripts/                       # bootstrap, sync, deploy, verify, logs
  systemd/                       # Linux persistence template
  launchd/                       # macOS persistence template
  cloudflare/                    # Pages Worker KV dynamic origin templates
  cloudflared/                   # named tunnel config example
```

## Inventory

Copy an inventory file and edit only target-specific values:

```bash
cp deploy/remote/vitalab/inventory.gpu.env.example /private/tmp/vitalab.gpu.env
```

Important fields:

```bash
VITALAB_HOST="10.7.117.30"
VITALAB_USER="gjsk"
VITALAB_ROOT="/home/gjsk/project/vitalab"
VITALAB_REMOTE_OS="linux"   # linux, macos, or auto
VITALAB_COMPOSE_PROFILES="quick-tunnel"
SYNC_INCLUDE_PDFS="false"
```

Keep real inventories outside git when they include sensitive hostnames or
operational details.

## Secrets

Secrets live only on the server:

```text
<VITALAB_ROOT>/secrets/api.env
<VITALAB_ROOT>/secrets/cloudflare.env
```

Example content:

```bash
SILICONFLOW_API_KEY=...
DEEPSEEK_API_KEY=...
AMINER_MCP_AUTH_TOKEN=...
```

`cloudflare.env` is required only for the quick tunnel sentinel:

```bash
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_KV_NAMESPACE_ID=...
CLOUDFLARE_API_TOKEN=...
```

Never commit these values or echo them into logs.

## Deployment Flow

From the repository root:

```bash
deploy/remote/vitalab/scripts/bootstrap_remote.sh /private/tmp/vitalab.gpu.env
deploy/remote/vitalab/scripts/audit_remote.sh /private/tmp/vitalab.gpu.env
deploy/remote/vitalab/scripts/sync_runtime.sh /private/tmp/vitalab.gpu.env
deploy/remote/vitalab/scripts/deploy.sh /private/tmp/vitalab.gpu.env
deploy/remote/vitalab/scripts/verify_remote.sh /private/tmp/vitalab.gpu.env
```

Install persistence after the first successful deploy:

```bash
deploy/remote/vitalab/scripts/install_persistence.sh /private/tmp/vitalab.gpu.env
```

Linux uses systemd. macOS uses LaunchAgents. The Compose service topology stays
the same on both OS families.

## Compose Services

Default profile:

```text
qdrant
api
web
cloudflared-quick
```

Optional profiles:

```text
worker         # ingestion-worker
named-tunnel   # cloudflared named tunnel after owning a real domain
```

Use comma or space separated profiles in inventory:

```bash
VITALAB_COMPOSE_PROFILES="quick-tunnel worker"
```

## Data Migration

Prefer Qdrant snapshots over raw storage copying:

```bash
deploy/remote/vitalab/scripts/backup_qdrant_snapshot.sh /private/tmp/vitalab.gpu.env
```

Restore is intentionally guarded:

```bash
RESTORE_CONFIRM=I_UNDERSTAND_QDRANT_RESTORE \
  deploy/remote/vitalab/scripts/restore_qdrant_snapshot.sh \
  /private/tmp/vitalab.gpu.env \
  "http://example/snapshot.snapshot"
```

Raw Qdrant storage copying is not the default path because it is version and
shutdown-state sensitive.

## Cloudflare Bridge

Without a Cloudflare-controlled domain, use the `quick-tunnel` profile plus a
Cloudflare KV backed dynamic origin. The stable browser entry remains:

```text
https://shengji-enzyme-rag-lab.pages.dev
```

The Pages Worker reads the backend origin from KV on each proxied `/api` and
`/PDF` request:

```text
KV namespace title: vitalab-origin-registry
KV binding: VITALAB_ORIGIN_KV
KV key: current_backend_origin
```

Create or reuse the KV namespace, and optionally seed the current tunnel URL:

```bash
CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_API_TOKEN=... \
  deploy/remote/vitalab/scripts/bootstrap_cloudflare_kv.sh \
  /private/tmp/vitalab.gpu.env
```

Put the printed `CLOUDFLARE_KV_NAMESPACE_ID` in the inventory, then deploy the
Cloudflare Pages frontend/proxy from a generated temporary package:

```bash
deploy/remote/vitalab/scripts/deploy_pages.sh /private/tmp/vitalab.gpu.env
```

On the server, put the sentinel token in:

```text
<VITALAB_ROOT>/secrets/cloudflare.env
```

Then install persistence:

```bash
deploy/remote/vitalab/scripts/install_persistence.sh /private/tmp/vitalab.gpu.env
```

The sentinel checks local API health, validates the current KV origin, restarts
only `cloudflared-quick` when needed, extracts the latest
`https://*.trycloudflare.com` URL from Compose logs, validates it, writes it to
KV, and finally checks Pages proxy health.

Inspect current tunnel and sentinel logs with:

```bash
deploy/remote/vitalab/scripts/logs.sh /private/tmp/vitalab.gpu.env cloudflared-quick 200
deploy/remote/vitalab/scripts/logs.sh /private/tmp/vitalab.gpu.env sentinel 200
```

The server-side token must be scoped to write the selected KV namespace only.
It must not have Pages deploy or broad account administration privileges.

For production, replace quick tunnel with named tunnel and a domain you control.
Keep the same Worker/KV structure and add the named tunnel host suffix to:

```bash
ALLOWED_BACKEND_HOST_SUFFIXES=".trycloudflare.com,.your-domain.example"
```

## Verification

Remote local checks:

```bash
deploy/remote/vitalab/scripts/status.sh /private/tmp/vitalab.gpu.env
deploy/remote/vitalab/scripts/verify_remote.sh /private/tmp/vitalab.gpu.env
```

Expected checks include:

- API `/api/health`
- document catalog count
- dashboard summary
- Qdrant collections
- current tunnel origin health from `<VITALAB_ROOT>/config/current_backend_origin`
- Cloudflare KV origin
- Pages proxy `/api/health`

## SSH Helper

The repository includes a non-secret SSH alias:

```bash
ssh -F deploy/remote/vitalab/ssh_config vitalab
```

or:

```bash
scripts/ssh_vitalab.sh
```

The public key already installed for the first server is:

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOVulI5IxO9fRUwjIAKSQ+mmnL5ZbFUq6hxgZZct6hK4 codex-local
```
