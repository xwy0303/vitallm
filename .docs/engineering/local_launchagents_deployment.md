# Local LaunchAgents Deployment

## Purpose

macOS local persistence uses LaunchAgents for four services:

- Qdrant on `127.0.0.1:6333/6334`
- MinerU API on `127.0.0.1:8000`
- FastAPI backend on `127.0.0.1:8001`
- Static frontend on `127.0.0.1:5173`

Deployment assets live under `deploy/local/`. Launchd-specific behavior must
stay out of `src/`, `web/`, and runtime schemas.

LaunchAgents do not execute repository scripts directly. The installer syncs a
runtime mirror into `~/Library/Application Support/Shengji/app` and generates
small wrappers under `~/Library/Application Support/Shengji/bin`. This avoids
macOS TCC failures when launchd tries to run code directly from `Desktop` or
`Documents`.

## Runtime Boundaries

- Logs are stored at `~/Library/Logs/Shengji/`, not in the repository.
- Qdrant storage is copied into the runtime mirror at
  `~/Library/Application Support/Shengji/app/.local/qdrant/storage`.
- The repository `.local/qdrant/storage` remains the development source copy and
  is not committed.
- `.env.local` remains the local secret source and must not be rendered into
  plist files or printed by status/log scripts. During install, `.env.local` is
  copied into the local runtime mirror with mode `600` if it exists.

## Qdrant Data Governance

Do not rename collections or migrate Qdrant storage as part of LaunchAgents
deployment. Collection governance is handled by the ingestion/data-governance
workflow.

The active formal collection is `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1`, rebuilt from
the registered PDF corpus and existing artifacts on 2026-05-25. The historical
`enzyme_immobilization_b10` collection is retained only as rollback data and
must not be used as the default target for new PDF ingestion.

## Docker Boundary

Future Docker Compose deployment should add Docker-specific config, volumes,
and service definitions without depending on LaunchAgents. Keep service URLs
and environment-variable boundaries stable so local launchd and Docker
deployments can coexist.
