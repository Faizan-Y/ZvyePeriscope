# Zyvefit Nutritionist Console — Cloud Deployment Handoff

This README is for the engineer who will deploy the Zyvefit Nutritionist Console and its scheduled-message worker to a cloud environment. It documents the current project structure, required configuration, database migration order, runtime processes, and items that must be addressed before enabling public access or real WhatsApp delivery.

> **Important deployment gate:** The current application code does not implement user login/authentication. Do not expose it to the public internet as-is, especially with live WhatsApp sends enabled. Before public launch, add application authentication and authorization or put the entire console behind a properly configured private access layer (for example, VPN/identity-aware proxy) and verify every API route is protected. A frontend-only login screen is not sufficient. The API currently exposes data and write/send endpoints without built-in user authentication.

> **Live sending is real:** The test database is not a WhatsApp sandbox. Any approved live send reaches real recipients stored in or resolved from the database.

## 1. Project overview

The application consists of a FastAPI backend, a browser frontend served by FastAPI, a PostgreSQL database, the existing Periskope Python client/adapter, and a separate scheduler process.

- **Frontend:** `web/index.html`, `web/app.js`, and `web/styles.css`.
- **API/backend:** `api.py`.
- **PostgreSQL operations:** `db.py` and schema-related helpers in the project.
- **Periskope integration:** `Periskope.py` and `periskope_adapter.py`.
- **Existing recurring scheduler and one-off scheduled queue worker:** `scheduler.py`, with `schedule_engine.py` and `db.py` as dependencies.
- **Database migrations:** `sql/001_media_and_template_scope.sql` and `sql/002_scheduled_message_jobs.sql`.
- **Uploaded files:** `data/uploads/` locally; cloud deployment requires durable storage as described below.

The same code repository can run the API and scheduler as two separate cloud processes. The frontend does not need a separate JavaScript build service in the current implementation: FastAPI serves the `web/` files and API routes from the same application.

## 2. Required files

Deploy from the **complete project**, not from a patch ZIP alone. Confirm these files and folders are present (additional files in the working project should be retained):

```text
project-root/
├── api.py
├── db.py
├── Periskope.py
├── periskope_adapter.py
├── scheduler.py
├── schedule_engine.py
├── requirements.txt
├── web/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── sql/
│   ├── 001_media_and_template_scope.sql
│   └── 002_scheduled_message_jobs.sql
├── data/
│   └── uploads/             # local development only; must be durable in cloud
└── .env                     # local only; do NOT commit/deploy this file
```

Do not replace `Periskope.py`, `periskope_adapter.py`, `db.py`, or `schedule_engine.py` with placeholder versions. They are part of the existing working integration.

## 3. Deployment architecture

Create at least these cloud resources:

1. **Web/API service** — runs FastAPI and serves the frontend.
2. **Worker service** — runs the existing scheduler continuously, as a separate process.
3. **Managed PostgreSQL database** — dedicated to Zyvefit, with backups enabled and network access restricted to the API/worker.
4. **Persistent media storage** — durable mounted storage or object storage with HTTPS media URLs the Periskope service can fetch.
5. **Authentication and HTTPS** — required before exposing the console to nutritionists or other users.

Keep the API and scheduler on the same release/version and give both the same database connection, timezone, Periskope credentials, and send kill-switch settings. Start with a single scheduler worker instance. Do not scale the scheduler horizontally until its claim/locking behavior, deployment restart behavior, and duplicate handling have been verified in the production environment.

## 4. Runtime commands

Use a supported Python version (Python 3.11 or newer is recommended) and install dependencies from the single root `requirements.txt`:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Web/API service

For a cloud platform that supplies a `PORT` environment variable, use a start command similar to:

```bash
uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}
```

The platform's HTTPS proxy should terminate TLS and forward traffic to this service. Do not expose a raw app port directly if the platform provides an HTTPS ingress/reverse proxy.

### Scheduler worker

Start in preview/dry-run mode first:

```bash
python scheduler.py
```

This is the default and does not send live messages. Review logs and the target database before allowing delivery.

When the deployment owner has explicitly approved live delivery, start the worker with:

```bash
python scheduler.py --send
```

The scheduler's default poll is 30 seconds unless `POLL_SECONDS` is set. It processes due recurring schedules from `message_schedules` and due one-off composer jobs from `scheduled_message_jobs` (the latter requires migration `002`). It uses the existing `SENDS_ENABLED` setting and a `STOP_SENDS` file beside `scheduler.py` as emergency stops, plus a per-cycle cap.

The scheduler should be a managed worker service with automatic restart and restricted logs. Do not run it as an API startup side effect.

## 5. Environment variables and secret management

In cloud, configure secrets and settings in the cloud platform's environment/secret manager. **Do not upload the local `.env` file to the repository or the cloud deployment.** The current API loads a `.env` file next to `api.py` with `override=True`; if a `.env` file is deployed, it may override values set in the cloud platform. Keep that file absent in cloud and set the variables in the platform instead.

| Variable | Purpose / deployment guidance |
|---|---|
| `DATABASE_URL` | Connection URL for the dedicated managed PostgreSQL database. Use the provider's private connection URL where supported and enforce TLS. URL-encode reserved characters in passwords (`@` becomes `%40`). Never commit this value. |
| `DATABASE_SCHEMA` | Currently use `public`; the supplied migration SQL references `public` explicitly. A custom schema needs migration/API review before deployment. |
| `ALLOW_DB_WRITES` | Keep `false` during initial checks. Set `true` only after the production database, migrations, access controls, and backup/restore are verified. |
| `ENABLE_LIVE_WHATSAPP_SENDS` | Keep `false` while deploying and testing. Enable only after explicit sign-off for real sends and after authentication and target verification are complete. |
| `LIVE_SENDS_REQUIRED_DATABASE` | The code defaults this to `zyvefit_portal_test` as a safety guard. For production, the deployment owner must deliberately set it to the exact intended production database name after reviewing the target. If left as the test database name, sends to another database should remain blocked. Do not change this blindly. |
| `PERISKOPE_API_KEY` | Secret used by the existing Periskope client. Store only in the cloud secret manager. |
| `PERISKOPE_PHONE` | Connected sender number in international digits, including country code. Store as a server-side setting, not in frontend code. |
| `SENDS_ENABLED` | Shared live-send kill switch for the API and scheduler. Start with `false`; set `true` only during an approved live operation. Setting it to `false` blocks live sending. |
| `UPLOAD_DIR` | Directory for uploaded files. Configure it to a durable volume if using file-system storage. Ephemeral container disk is not durable. |
| `MAX_UPLOAD_MB` | Upload size limit; current default is 25 MB (application clamps the value to at most 100 MB). |
| `APP_TIMEZONE` | Scheduler timezone; use `Asia/Kolkata` unless the business owner approves a different timezone. |
| `POLL_SECONDS` | Scheduler polling interval in seconds; default is 30. |
| `MAX_SENDS_PER_CYCLE` | Recurring/worker send-attempt cap per cycle; default is 25. Increase only after operational testing. CLI `--max-sends` can override it. |
| `MISFIRE_GRACE_MINUTES` | Grace window for due recurring schedules; default is 5 minutes. |
| `CATCHUP_MINUTES` | Scheduler catch-up window; default is 1440 minutes (24 hours). Confirm business expectations before changing it. |
| `LOG_LEVEL` | Logging level, typically `INFO` in production. Protect logs because they may contain identifiers and operational message details. |
| `HEARTBEAT_URL` | Optional external watchdog/health-check ping URL. Treat it as a secret if the chosen service uses a private token URL. |

No `WHATSAPP_ALLOWED_CHAT_IDS` environment variable is required by this version. Since an allowlist is intentionally not used, application authentication/authorization and server-side recipient selection must be properly secured before deployment.

## 6. PostgreSQL requirements and migrations

### Use a dedicated database

Create a dedicated production database for Zyvefit instead of using a shared/general-purpose database that contains tables belonging to unrelated applications. Create a least-privilege database role for the application; do not run the application as a PostgreSQL superuser. The role needs the privileges required by the API and scheduler, including the relevant tables/sequences and migration-created objects.

Before connecting production:

1. Take and test a backup of the current Zyvefit data.
2. Provision the intended production database and restrict network access.
3. Restore only the approved Zyvefit tables/data, or use the approved migration/import process.
4. Confirm the actual database name, role, schema, and expected table/column names.
5. Apply the migrations below in order if they are not already reflected in the target database.

### Migration order

- `sql/001_media_and_template_scope.sql` — media library and template audience/media metadata.
- `sql/002_scheduled_message_jobs.sql` — persistent one-off scheduled composer messages. The existing recurring schedule table `message_schedules` remains in use.

The application does not automatically run these migrations. Review each SQL file and run it manually against the confirmed target database. Migration `002` currently uses the `public` schema and foreign keys to the Zyvefit `members`, `whatsapp_groups`, `templates`, and `message_logs` tables; verify those structures before applying it. Do not point a migration command at a local database or production database until the target has been confirmed.

After migrations, check:

```text
GET /api/health
GET /api/db/check
```

The database check should show the expected database name, `read_ready: true`, `migration_ready: true`, `scheduled_message_jobs_ready: true`, and `writes_ready: true` once writes are deliberately enabled. Live-send readiness also depends on credentials and the database safety guard. Do not share full connection strings or secrets from cloud logs or health tooling.

## 7. Media storage requirements

The development implementation stores uploaded file bytes in `UPLOAD_DIR` and writes metadata into `media_assets` / `templates`. In a cloud container, the local filesystem may be wiped when the container restarts or is redeployed.

Before production media uploads:

- Use a durable mounted volume or object storage service.
- Ensure database metadata points to the persistent file/object.
- Ensure URLs passed to Periskope are publicly reachable HTTPS URLs (or appropriate short-lived signed HTTPS URLs if supported and tested by the provider).
- Do not pass local URLs such as `http://127.0.0.1:8000/uploads/...` or relative paths such as `/uploads/...` to Periskope; its service cannot fetch files from the developer's laptop or an internal-only address.
- Verify access control and privacy for nutrition plans or member-specific documents. Do not make sensitive media publicly readable without an approved access strategy.

Cloud media/object storage integration is a deployment requirement to implement or verify; do not assume the local upload path automatically becomes a valid public Periskope URL.

## 8. Live sending and scheduled messaging

The application supports three live audience modes: one member, one group, or a tier with an optional phase. Tier sends resolve active members and send once per distinct matched group. The API creates audit log rows before requesting delivery; a provider response of `QUEUED` means accepted/queued, not proof of delivery.

Composer scheduling writes one-off jobs to PostgreSQL. The scheduler must be running in `--send` mode at the due time for them to be delivered. The existing recurring `message_schedules` process remains separate logically but runs within the same scheduler process.

Before the first production send:

1. Confirm the database name and active member/group mappings.
2. Call the preview endpoint from the authenticated/controlled environment and review every target; preview must not send.
3. Test with one specifically approved group and a harmless text message.
4. Check the response, Periskope status, and `message_logs` before retrying any uncertain request.
5. Confirm emergency stop procedure: set `SENDS_ENABLED=false` and/or create `STOP_SENDS` beside `scheduler.py`.

Do not automatically retry uncertain failures. The provider may have accepted a request even if the caller timed out; check Periskope and `message_logs` first to avoid duplicates.

## 9. Health checks and smoke-test checklist

Before launch, the deployment engineer should confirm all of the following:

- [ ] API health check succeeds and reports the correct managed database.
- [ ] `GET /api/db/check` confirms the schema and migration requirements.
- [ ] Frontend loads through the intended HTTPS domain.
- [ ] All mutating API endpoints require authenticated, authorized access before public exposure.
- [ ] Database backups and a restore test are complete.
- [ ] Application DB role is not a superuser and has only required privileges.
- [ ] Persistent media storage survives a service redeploy; Periskope can retrieve an HTTPS test asset.
- [ ] Scheduler starts in dry-run mode and previews only the expected targets.
- [ ] Timezone and polling cadence are verified.
- [ ] Live sends remain off until explicitly approved.
- [ ] A controlled one-group live test is confirmed in Periskope and `message_logs`.
- [ ] Emergency stop is tested and documented.
- [ ] Logs, secrets, database access, and backups have appropriate retention and access restrictions.



