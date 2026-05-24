# Local LaunchAgents Deployment

This directory contains local macOS LaunchAgents deployment assets for Shengji.
It manages service lifecycle only and keeps launchd-specific behavior out of
`src/`, `web/`, and runtime config files.

## Services

| Label | Port | Purpose |
| --- | --- | --- |
| `com.shengji.qdrant` | `6333`, `6334` | Qdrant vector store |
| `com.shengji.mineru` | `8000` | MinerU PDF parser API |
| `com.shengji.api` | `8001` | FastAPI backend |
| `com.shengji.web` | `5173` | Static frontend |
| `com.shengji.logrotate` | n/a | Daily log rotation |

## Install

Stop manually started services on ports `8000`, `6333`, `6334`, `8001`, and
`5173`, then run:

```bash
deploy/local/install_launchagents.sh
```

Check status:

```bash
deploy/local/status_launchagents.sh
```

Restart one service:

```bash
deploy/local/restart_launchagents.sh api
```

Uninstall LaunchAgents without deleting logs, storage, artifacts, PDFs, or
model caches:

```bash
deploy/local/uninstall_launchagents.sh
```

## Logs

Runtime logs are written outside the repository:

```text
~/Library/Logs/Shengji/
```

Use:

```bash
deploy/local/bin/logs.sh api --tail 100
deploy/local/bin/logs.sh all --follow
```

Logs are rotated daily by `com.shengji.logrotate`. Defaults are 50 MB per file
and 14 days of compressed history. Override with `deploy/local/env.local` if
needed.

## Runtime Mirror

LaunchAgents run from a local runtime mirror instead of directly executing
files under the repository. During install, the script syncs the required app
runtime to:

```text
~/Library/Application Support/Shengji/app
```

and generates small wrappers under:

```text
~/Library/Application Support/Shengji/bin
```

This avoids macOS TCC failures when launchd accesses projects located under
`Desktop` or `Documents`.

## Runtime Data Boundary

Qdrant storage in the runtime mirror is:

```text
~/Library/Application Support/Shengji/app/.local/qdrant/storage
```

The repository `.local/qdrant/storage` remains the development source copy and
is not committed.

The current collection name `enzyme_immobilization_b10` is historical. It now
contains the local MVP literature index, not only the B10 PDF. Collection
rename, storage migration, and reindexing must be handled as a separate data
governance task.

## Local Overrides

Copy `deploy/local/env.example` to `deploy/local/env.local` to override ports,
log path, or runtime config. Do not put API keys in LaunchAgent plist files.
The API continues to load secrets from `.env.local`.

## Docker Boundary

Future Docker deployment should reuse the same service contracts and introduce
Docker-specific config separately. Do not make business code depend on launchd
paths or plist behavior.
