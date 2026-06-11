# Vitalab Portable Server Migration And Persistent Deployment

## Updated Requirement

The deployment must be portable. Future work should migrate the whole project
to a new server, including frontend, backend, algorithms, data services, and
deployment/runtime automation. The current `10.7.117.30` server is only the
first deployment target, not the architecture boundary.

Therefore, deployment assets must separate:

- Portable project runtime and infrastructure definitions.
- Environment-specific inventory such as host, user, paths, ports, tunnel URL,
  and secrets.
- Data migration artifacts such as Qdrant snapshots and PDF/RAG artifacts.

Do not hard-code `10.7.117.30`, `/home/gjsk/project/vitalab`, quick tunnel
hostnames, or user-specific paths into reusable deployment logic.

## Current State

- Current target server: `10.7.117.30`, user `gjsk`.
- Current target runtime directory: `/home/gjsk/project/vitalab`.
- As of 2026-06-10, Phase 1 server deployment is running on the target server.
  Docker Compose services are `qdrant`, `api`, `web`, and
  `cloudflared-quick`.
- The server already had a process bound to host port `8001`, and
  `18001` is owned by an existing inference container
  (`triton-server-vllm`). The portable first-server runtime default is now
  `ENZYME_API_PORT=18081` while the Vitalab API container still listens on
  `8001`; deploy preflight fails fast if the configured host port is occupied
  by an unknown process.
- Cloudflare Pages production URL `https://shengji-enzyme-rag-lab.pages.dev`
  should proxy API traffic through a KV dynamic backend origin instead of a
  hard-coded quick tunnel URL.
- Future target servers must be supported by changing inventory/env files, not
  by rewriting deployment scripts.
- SSH network reachability and passwordless public-key login were verified on
  2026-06-08.
- A non-secret local SSH alias was added under `deploy/remote/vitalab/`.
- Current public Cloudflare backend access still depends on quick tunnel URLs,
  but the quick tunnel URL should be written to Cloudflare KV by the sentinel
  rather than manually injected into Pages source.
- The server IP is in the private `10.0.0.0/8` range, so Cloudflare Pages
  cannot directly call it by IP from the public internet.

## SSH Access Plan

- Do not store the server password in this repository, shell scripts, logs, or
  deployment configs.
- Install the workstation public key into `/home/gjsk/.ssh/authorized_keys`.
- After key installation, use:

```bash
scripts/ssh_vitalab.sh
```

or:

```bash
ssh -F deploy/remote/vitalab/ssh_config vitalab
```

## Recommended Deployment Strategy

Use Docker Compose for service persistence and systemd for boot persistence.
For portability, Compose files should be committed as reusable templates, and
server-specific values should live in `.env` files, SSH inventory, or
server-local secret files.

Phase 1 should deploy a portable serving baseline:

- Qdrant with a persistent named volume or bind mount.
- FastAPI backend for recommendation, evidence search, general QA, documents,
  dashboard summary, and PDF serving.
- Static frontend serving locally for server-side validation.
- Server-side cloudflared quick tunnel as a temporary public bridge until a
  real domain is available.
- Cloudflare Pages Worker that reads current backend origin from Cloudflare KV.
- Server-side quick tunnel sentinel that updates KV after tunnel rotation.

Phase 2 should add heavier and less urgent components:

- MinerU API, preferably after GPU/runtime audit.
- PDF ingestion worker.
- Named tunnel after a real Cloudflare-controlled domain is purchased.
- Remote frontend deployment automation, so the Pages build/upload is driven
  from the same deploy inventory rather than manual URL edits.

Phase 3 should complete full-project portability:

- One-command bootstrap for a fresh server.
- One-command deploy/update using an inventory file.
- Snapshot-based backup and restore for Qdrant and required artifacts.
- Server replacement drill: deploy the same stack to a second host and verify
  Cloudflare frontend/API cutover.

This keeps the first server migration focused on replacing the Mac-local
runtime with a server-local runtime without mixing in GPU parsing complexity.

## 2026-06-10 Deployment Result

Remote runtime:

- Root: `/home/gjsk/project/vitalab`
- API: current first-server portable default is
  `127.0.0.1:18081 -> container api:8001`.
- Web: `127.0.0.1:5173 -> nginx:80`
- Qdrant: `127.0.0.1:6333/6334`
- Quick tunnel: `https://shade-temp-raising-vendor.trycloudflare.com`
- Pages production: `https://shengji-enzyme-rag-lab.pages.dev`

Running services:

- `vitalab-api-1`: healthy, restart policy `unless-stopped`
- `vitalab-qdrant-1`: running, restart policy `unless-stopped`
- `vitalab-web-1`: running, restart policy `unless-stopped`
- `vitalab-cloudflared-quick-1`: running, restart policy `unless-stopped`

Persistence:

- `vitalab-compose.service` is installed and enabled under user-level systemd.
- The unit uses `sg docker` because the remote user systemd manager did not
  inherit the `docker` supplementary group even though `gjsk` belongs to it.
- `systemctl --user is-active vitalab-compose.service` returned `active`.
- `loginctl show-user gjsk -p Linger` returned `Linger=no`, so this is not yet
  a true boot-level guarantee. Full boot persistence requires either root-level
  installation of `/home/gjsk/project/vitalab/deploy/systemd/vitalab-compose.service`
  or root running `loginctl enable-linger gjsk`.

Data layer:

- Synced artifacts contain 76 RAG input directories and 76 evidence directories.
- BGE cache `BAAI/bge-base-en-v1.5` was migrated to
  `/home/gjsk/project/vitalab/data/model_cache`.
- Remote Qdrant collection was rebuilt from artifacts:
  `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1`.
- Reindex result: 76 documents, 3057 `rag_chunk` points, 133 `table_record`
  points, 3720 `evidence_record` points, 6910 total points.
- Collection status: `green`, `points_count=6910`.
- Snapshot created:
  `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1-2380629183313722-2026-06-10-09-22-55.snapshot`
  with checksum
  `596fc848683db40f8523f1c43a4b4087d8f26fd4bd3bf27cac99f14d14e7480a`.

Verification:

- Remote local API health returned `status=ok`.
- Remote dashboard summary returned `processed_docs=76`,
  `processed_pages=867`, `qdrant_points=6910`, `qdrant_status=green`.
- Remote document catalog returned 76 documents.
- Pages production `/api/health` returned `status=ok`.
- Pages production `/api/search/evidence` returned 3 hits for a lipase
  immobilization query, with top hit `point_type=evidence_record`.

## 2026-06-10 Phase 1 Closure Hardening

Scope:

- Treat Phase 1 as a product-facing serving baseline, not a one-off demo.
- Domain purchase/named tunnel remains out of scope for this closure pass.
- Focus on broken interfaces, misleading UI, error robustness, deploy
  portability, and reducing obvious runtime traps.

Changes made:

- FastAPI error handling now classifies generator/API-key and upstream provider
  failures into client-safe error payloads instead of returning raw exception
  strings to the frontend.
- NDJSON streaming endpoints use the same safe error contract as JSON endpoints.
- Secret-like values are redacted from API error messages before they are shown
  to users or written through normal warning logs.
- Legacy `/PDF/{pdf_name}` route now maps to the canonical
  `/api/pdfs/{pdf_name}` implementation, matching the Cloudflare Worker
  `/PDF/*` proxy contract.
- Remote `web` service is no longer a bare static nginx container. It now builds
  a local nginx image with same-origin proxying for `/api`, `/api/*`, `/PDF`,
  and `/PDF/*` to `api:8001`.
- Remote `verify_remote.sh` and `status.sh` now check web same-origin
  `/api/health`, so frontend/backend connectivity is part of acceptance rather
  than an implicit assumption.
- Remote `deploy.sh` now fail-fast checks both API host port and web host port,
  while allowing already-running Compose-owned containers to keep their ports.
- Frontend error rendering now understands both FastAPI structured errors and
  Cloudflare Worker simple errors such as `backend_origin_unavailable`.
- Removed visible Phase 1 UI dead ends: the unimplemented login button and the
  sidebar `任务历史` anchor that had no matching section.

Validation:

- `python3 -m py_compile src/enzyme_recommender/api/app.py tests/test_phase1_hardening.py`
- `PYTHONPATH=src .venv/bin/python -m unittest tests.test_phase1_hardening`
  passed 4 tests.
- `PYTHONPATH=src .venv/bin/python -m unittest tests.test_core_contracts`
  passed 116 tests. Existing `ResourceWarning` remains a known test hygiene
  issue, not a failed contract.
- `node --check web/app.js`
- `node tests/worker_kv_smoke.mjs`
- `for f in deploy/remote/vitalab/scripts/*.sh; do bash -n "$f"; done`
- `git diff --check`
- Remote deploy was applied with
  `deploy/remote/vitalab/scripts/sync_runtime.sh /private/tmp/vitalab.gpu.pages.env`
  and `deploy/remote/vitalab/scripts/deploy.sh /private/tmp/vitalab.gpu.pages.env`.
- Remote acceptance passed with
  `deploy/remote/vitalab/scripts/verify_remote.sh /private/tmp/vitalab.gpu.pages.env`:
  API health `status=ok`, web same-origin API health `status=ok`,
  document catalog count `76`, Qdrant `points_count=6910`,
  Qdrant status `green`, and Pages proxy `/api/health` `status=ok`.
- Cloudflare Pages static frontend was not redeployed in this pass because the
  available local inventory only contained the historical
  `CLOUDFLARE_BACKEND_ORIGIN`; it did not include
  `CLOUDFLARE_KV_NAMESPACE_ID`, `CLOUDFLARE_ACCOUNT_ID`, or
  `CLOUDFLARE_API_TOKEN`. Do not bypass the KV dynamic origin requirement by
  reintroducing hard-coded quick tunnel origin deployment.

## 2026-06-11 Runtime Port Normalization

The original plan preferred host API port `18001`, but the first GPU server
already publishes `triton-server-vllm` on `0.0.0.0:18001 -> 8001`. Vitalab must
not kill or reclaim that service. The canonical first-server remote contract is
therefore:

- Host API port: `ENZYME_API_PORT=18081`.
- API container internal port: `8001`.
- Host web port: `SHENGJI_WEB_PORT=5173`.
- Local development may still use `8001` through `deploy/local/`; this is a
  separate local contract and should not leak into remote deploy scripts.

Remote `compose.yaml`, `deploy.sh`, `status.sh`, `verify_remote.sh`,
`runtime.env.example`, and this workflow now use the same remote fallback:
`127.0.0.1:18081 -> api:8001`.

## 2026-06-11 Cloudflare KV Origin Activation

Cloudflare KV dynamic origin is now active:

- KV namespace title: `vitalab-origin-registry`.
- KV namespace id: `9c79c7d016914e00ac13ab8222de6e01`.
- Pages Worker binding: `VITALAB_ORIGIN_KV`.
- KV key: `current_backend_origin`.
- Current origin written by sentinel:
  `https://benefit-crawford-struct-continuing.trycloudflare.com`.

Actions completed:

- Created or reused the KV namespace and seeded the initial quick tunnel origin.
- Deployed the KV-aware Cloudflare Pages Worker for
  `shengji-enzyme-rag-lab`.
- Installed `<VITALAB_ROOT>/secrets/cloudflare.env` on the server with strict
  file permissions.
- Installed and started `vitalab-quick-tunnel-sentinel.service`.
- Sentinel detected the stale quick tunnel origin, restarted
  `cloudflared-quick`, validated a new origin, wrote it to KV, and confirmed
  Pages proxy health.

Validation:

- `https://shengji-enzyme-rag-lab.pages.dev/api/health` returned `status=ok`.
- `deploy/remote/vitalab/scripts/verify_remote.sh
  /private/tmp/vitalab.gpu.pages.env` passed API, web same-origin API,
  documents, dashboard, Qdrant, tunnel origin, KV origin, and Pages proxy
  health checks.

Security note:

- Cloudflare tokens were intentionally kept out of repository files and docs.
- Because the tokens were shared in chat during setup, rotate both Cloudflare
  tokens after confirming the deployment remains healthy, then update only the
  local operations env and server-side `secrets/cloudflare.env`.

Residual engineering debt:

- `src/enzyme_recommender/api/app.py`, `web/app.js`, and
  `tests/test_core_contracts.py` exceed the project preference of 1000 lines.
  This pass did not split them because the closure goal is stability and
  product hardening; Phase 2 should split FastAPI routes/services, frontend
  request/render modules, and broad contract tests before adding more features.
- Local macOS static web serving still uses Python `http.server` without
  same-origin API proxy; local development relies on `web/app.js` defaulting to
  `http://127.0.0.1:8001` unless `window.ENZYME_API_BASE_URL` is set.
- Remote API Docker image currently reinstalls large ML dependencies during a
  rebuild. Phase 2 should split dependency/base image layers and pin runtime
  wheels to avoid multi-minute rebuilds after small application changes.

## Proposed Portable Layout

```text
<VITALAB_ROOT>/
  app/                   # synced source/runtime files
  config/                # non-secret configs
  secrets/               # chmod 700, not committed
  data/qdrant/            # persistent Qdrant storage or restored snapshots
  data/snapshots/         # Qdrant snapshots for import/export
  artifacts/              # runtime artifacts needed by API
  logs/                   # service logs if not using Docker logging only
  deploy/                 # compose, env examples, helper scripts
```

For the current server, `<VITALAB_ROOT>` is `/home/gjsk/project/vitalab`.

Local repository deployment assets should move toward:

```text
deploy/remote/vitalab/
  inventory.example.env
  inventory.gpu.env.example
  compose.yaml
  systemd/
  scripts/
```

Actual secrets and private inventory values stay outside git.

As of 2026-06-08, the portable skeleton exists under
`deploy/remote/vitalab/` and includes:

- Inventory examples for generic and first GPU target.
- Remote runtime env and API runtime config templates.
- Docker Compose stack for Qdrant, API, web, quick tunnel, named tunnel, and
  optional ingestion worker.
- API/Web Dockerfiles and Docker build ignore rules.
- Linux systemd and macOS launchd persistence templates.
- Bootstrap, audit, sync, deploy, status, logs, verify, Qdrant backup/restore,
  persistence install, and Cloudflare Pages deploy scripts.
- Cloudflare Pages Worker template reads backend origin at runtime from KV.
- Quick tunnel sentinel and Linux/macOS persistence templates are part of the
  portable deployment skeleton.

## Portability Requirements

- Runtime root must be controlled by `VITALAB_ROOT`.
- Service ports must be controlled by env vars:
  `QDRANT_HTTP_PORT`, `QDRANT_GRPC_PORT`, `ENZYME_API_PORT`,
  `SHENGJI_WEB_PORT`, `MINERU_PORT`.
- Cloudflare backend origin must be runtime state in KV, not manually edited in
  source files or injected into Pages deployments.
- Compose must support restore from Qdrant snapshots and artifact sync.
- Deployment must be reproducible on a fresh server after installing Docker,
  cloudflared, and systemd service files.
- Frontend, backend, algorithms, schemas, configs, scripts, and selected
  artifacts must be synced by allowlist, not by copying the whole repository.
- Secrets must be injected through server-local files or secret managers, not
  committed into repo docs, Compose files, env examples, or logs.
- Verification must include frontend, API, Qdrant, collection count, dashboard
  stats, document catalog, and at least one retrieval/query smoke test.

## Migration Plan

1. SSH bootstrap for current server
   - Install local public key on the server.
   - Verify `scripts/ssh_vitalab.sh 'hostname && pwd'`.
   - Create `/home/gjsk/project/vitalab`.

2. Portable deployment blueprint
   - Add inventory/env template for host, user, root path, ports, and tunnel
     mode.
   - Add Compose template for Qdrant, API, optional web, optional cloudflared.
   - Add bootstrap/deploy/status scripts that read inventory instead of
     hard-coded server values.
   - Add systemd unit template for Compose persistence.

3. Server audit
   - Check OS, CPU, RAM, disk, Docker availability, NVIDIA driver/GPU status,
     Python version, outbound network access, and firewall.
   - Decide whether Docker Compose can run all Phase 1 services.

4. Data migration
   - Prefer Qdrant collection snapshot export/import over raw storage copying.
   - Collection to migrate:
     `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1`.
   - Validate restored collection count and `qdrant_status`.

5. Runtime sync
   - Sync only required paths, not the whole 4GB+ repository:
     `src`, `configs`, `schemas`, `scripts`, `web`, selected `artifacts`.
   - Keep secrets outside git and outside command logs.

6. Compose and service persistence
   - Add `docker-compose.yml` or equivalent remote compose file.
   - Configure restart policy `unless-stopped`.
   - Add systemd unit to run Compose at boot.
   - Persist Qdrant data under `${VITALAB_ROOT}/data/qdrant`.

7. Cloudflare bridge
   - Temporary: run server-side quick tunnel and publish the current origin to
     Cloudflare KV via the sentinel.
   - Long-term: replace quick tunnel with named tunnel once a real domain is
     controlled in Cloudflare.

8. Verification
- Local server health: `curl http://127.0.0.1:18081/api/health`.
   - Tunnel health: `curl https://<temporary-or-fixed-origin>/api/health`.
   - Pages health: `curl https://shengji-enzyme-rag-lab.pages.dev/api/health`.
   - Dashboard summary: check `processed_docs`, `processed_pages`,
     `qdrant_points`, and `qdrant_status`.

9. Migration rehearsal for a future new server
   - Instantiate a second inventory file with a different host/root.
   - Deploy the same Compose stack.
   - Restore snapshots and artifacts.
   - Switch only Cloudflare origin/inventory and verify identical public API
     behavior.

## Risks And Boundaries

- Without a purchased Cloudflare-controlled domain, public API access still uses
  quick tunnel and can change after cloudflared restart or network interruption.
- Current quick tunnel origin is temporary and account-less. It has no uptime
  guarantee and must be replaced by a named tunnel after a real domain is
  controlled in Cloudflare.
- Current persistence is user-level systemd with `Linger=no`. It survives
  service restarts within the active user manager, but it is not yet a strict
  boot-level production guarantee until root-level systemd install or linger is
  enabled.
- The server private IP cannot be used as a public Pages backend origin.
- Raw Qdrant storage copying can corrupt or mismatch versions; snapshot-based
  migration is preferred.
- MinerU/GPU deployment should not be mixed into the first serving migration
  unless server audit confirms runtime readiness.
- Secrets such as LLM API keys must be transferred out-of-band or written only
  to server-local secret files with strict permissions.
- If deployment scripts hard-code the first server, future migration will fail
  the portability requirement even if the first deployment works.
- Cloudflare KV is eventually consistent; after sentinel writes a new origin,
  Pages proxy recovery can take a short propagation window.
- Quick Tunnel is still a transitional bridge and should not be treated as a
  production SLA path, especially for streaming/SSE behavior.

## TODO

- [x] Install workstation public key on server.
- [x] Verify passwordless SSH via `scripts/ssh_vitalab.sh`.
- [x] Create `/home/gjsk/project/vitalab`.
- [x] Add portable inventory/env template.
- [x] Add portable Compose template.
- [x] Add bootstrap/deploy/status scripts that consume inventory.
- [x] Add systemd persistence template.
- [x] Add macOS launchd persistence template.
- [x] Add Cloudflare Pages proxy templates generated from inventory.
- [x] Add Cloudflare Pages Worker KV dynamic origin template.
- [x] Add quick tunnel sentinel script and persistence templates.
- [x] Add Cloudflare KV bootstrap helper.
- [x] Audit server runtime and Docker/GPU readiness.
- [x] Decide Compose service set for Phase 1.
- [x] Sync minimal runtime files.
- [x] Start Qdrant and API on server.
- [x] Start server-side quick tunnel.
- [x] Rebuild remote Qdrant collection from synced artifacts.
- [x] Create remote Qdrant snapshot after rebuild.
- [x] Deploy Cloudflare Pages proxy update.
- [x] Run public and local sanity checks.
- [ ] Create/reuse Cloudflare KV namespace `vitalab-origin-registry` and bind
      it to Pages as `VITALAB_ORIGIN_KV`.
- [ ] Install `<VITALAB_ROOT>/secrets/cloudflare.env` on the server with a
      minimal KV-write token.
- [ ] Deploy the KV-aware Pages Worker and start
      `vitalab-quick-tunnel-sentinel.service`.
- [ ] Enable true boot-level persistence via root-level systemd install or
      `loginctl enable-linger gjsk`.
- [ ] Replace quick tunnel with named tunnel after owning/controlling a real
      Cloudflare domain.
- [ ] Rehearse deployment on a second/fresh server inventory before declaring
      the deployment portable.
