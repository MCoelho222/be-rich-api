# Operations

**Scope:** this file covers deployment, scheduled jobs, configuration, backups and logging.
Related files: [schemas.md](schemas.md) (§16 exchange rates, §17 holidays), [auth.md](auth.md) and [api.md](api.md).

The UI and API are deployed with **Docker Compose on a single VPS**. Existing data is **not migrated**: the redesign starts from an empty database with a new Alembic baseline.

---

## 1. Services (docker-compose)

| Service | Image / command | Role |
|---|---|---|
| `proxy` | Caddy | Handles TLS automatically (Let's Encrypt). Sends `/api/*` to `api` and everything else to `web`, so both are served **from one origin** (auth.md §3). |
| `web` | `be-rich-ui`, `next start` | The frontend. |
| `api` | `be-rich-api`, `gunicorn -k uvicorn.workers.UvicornWorker` | The HTTP API. Runs **no** scheduled jobs (§2). |
| `worker` | `be-rich-api`, `python -m app.jobs` | Runs the scheduled jobs (APScheduler). Exactly **one** instance. |
| `db` | `postgres:15` | Database, stored on a named volume. Not exposed to the internet. |
| `mailpit` *(dev only)* | `axllent/mailpit` | Catches outgoing emails in development. Its web inbox runs on port 8025. |

### 1.1 Why jobs run in a separate `worker` container
Each gunicorn worker is its own process. If the scheduler ran inside the `api` service, every job would run once per worker. A single dedicated worker runs each job exactly once.

### 1.2 Startup order
1. `db` passes its healthcheck.
2. `api` runs `alembic upgrade head` in its entrypoint (the existing `docker-entrypoint.sh`), then starts.
3. `worker` starts after `api` is healthy, so migrations have already run.

### 1.3 Healthchecks
- `GET /api/v1/health` returns `{ "status": "ok", "db": "ok" }`. It checks database connectivity with `SELECT 1`.
- Caddy and Docker both use it as the healthcheck.

### 1.4 On Vercel
The API can also run as a Vercel Python function (`vercel.json`), with the database on Neon through Vercel's integration.
- **Region:** the function must run in the database's region. `vercel.json` pins it to `gru1` (São Paulo), next to Neon's `sa-east-1`. In another region every query pays a cross-continent round trip, and endpoints with many queries hit the function's 10-second timeout.
- **Dependencies:** Vercel installs from `requirements.txt`. Don't add a `pyproject.toml` with a `[project]` table: Vercel would install from it instead, without the dependencies.
- **Jobs:** there is no worker; see §2.4.
- **Migrations:** they don't run on deploy; see §4.1.

---

## 2. Scheduled jobs

All times are in `America/Sao_Paulo`.

### 2.1 Job rules
- **Idempotent:** every job can run twice without side effects.
- **Runnable by hand:** `docker compose exec worker python -m app.jobs run <job>`.
- **Logged:** each run logs its start, end, result counts and any errors.

### 2.2 Jobs

| Job | Schedule | What it does |
|---|---|---|
| `fx_daily` | Daily at **13:00**, retried hourly until 20:00 on failure | Fetches the latest rates for every supported `Currency` pair from the provider (schemas §16.2) and upserts them into `exchange_rate`. The European Central Bank publishes around 16:00 CET (about 12:00 in Brasília); weekends and holidays have no new rates, which is expected. |
| `holidays_seed` | At startup, and every **Jan 2 at 03:00** | Makes sure `holiday` covers the current year and the next 2 years (schemas §17.1). It inserts missing dates and never deletes. |
| `invitations_expire` | Every hour | Sets `status = EXPIRED` on `PENDING` invitations past `expires_at` (schemas §6.1 rule 4). |
| `sessions_cleanup` | Daily at **04:00** | Deletes invalid sessions, and password-reset tokens that are used or more than 1 day past expiry (auth.md §2). |
| `rate_limit_cleanup` | Daily at **04:10** | Deletes rate-limit counters older than 1 day (auth.md §5). |

### 2.3 Historical exchange rates
Historical rates (schemas §16.2) are **not** a scheduled job. The API fetches a missing date on demand, inside the request that needs it, with a 5-second timeout. If that fetch fails, it falls back as described in schemas §16.4.

### 2.4 On Vercel (no worker)

Vercel has no long-running process for the scheduler, so Vercel Cron calls `GET /api/v1/cron/daily` once a day (`vercel.json`, `0 17 * * *` = **14:00** in São Paulo, within the hour on the Hobby plan). The call runs `fx_daily`, `invitations_expire`, `sessions_cleanup`, `rate_limit_cleanup` and `holidays_seed`, in that order.

- **Auth:** Vercel sends `Authorization: Bearer <CRON_SECRET>`. Any other value gets 401. Without `CRON_SECRET` the endpoint answers 404, so it is off in Docker, where the worker runs the jobs.
- **Failures:** a failing job doesn't stop the others. The response lists each job's counts and `failed`, and is a 500 when any job failed, so it shows as failed in Vercel's cron logs.
- **Differences from §2.2:** `fx_daily` runs once with no hourly retries. A missed day keeps the previous rates, which are still used with their `rates_as_of` date. `invitations_expire` runs daily rather than hourly.
- **By hand:** `curl -H "Authorization: Bearer $CRON_SECRET" https://<api>/api/v1/cron/daily`.

---

## 3. Configuration (environment variables)

Variables are loaded from `.env`, which is **never committed** (a `.env.example` file is committed instead). Both `api` and `worker` read the same variables.

| Variable | Example | Used by | Notes |
|---|---|---|---|
| `ENV` | `production` / `development` | api, worker | Controls the cookie `Secure` flag, the error detail level and the email backend. |
| `APP_URL` | `https://berich.example.com` | api | Used to build email links. |
| `DATABASE_URL` | `postgresql+psycopg://…@db:5432/berich` | api, worker | Replaces the current `DB_URL`. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | | db | |
| `TZ` | `America/Sao_Paulo` | api, worker | The meaning of "today" comes from the code, which uses this zone explicitly. The variable only affects logs. |
| `EMAIL_BACKEND` | `resend` / `smtp` | api | `smtp` together with Mailpit in development. |
| `RESEND_API_KEY` | | api | Secret. |
| `SMTP_HOST`, `SMTP_PORT` | `mailpit`, `1025` | api | Development only. |
| `EMAIL_FROM` | `Be Rich <no-reply@example.com>` | api | |
| `FX_PROVIDER` | `frankfurter` | api, worker | |
| `FX_BASE_URL` | `https://api.frankfurter.dev/v1` | api, worker | The default. The old `api.frankfurter.app` domain now answers with a redirect. |
| `LOG_LEVEL` | `INFO` | api, worker | |
| `CRON_SECRET` | 32+ random characters | api | Vercel only (§2.4). Secret. Unset elsewhere, which disables `/cron/daily`. |
| `NEXT_PUBLIC_API_BASE` | `/api/v1` | web | A relative path, because the UI and API share an origin. |

### 3.1 Settings to remove from the current code
- `echo=True` on the SQLAlchemy engine. It logs every SQL statement, including personal data.
- The hard-coded CORS origin list. CORS isn't needed once both apps share an origin. In development, the Next.js `rewrites` feature proxies `/api` to `localhost:8000`.

---

## 4. Database

### 4.1 Migrations
- **Fresh start:** delete the 3 existing Alembic versions and generate a new **baseline** migration from the new models.
- Every schema change after that is a new Alembic revision, and migrations run automatically on deploy (§1.2).
- **On Vercel** (§1.4) nothing runs them on deploy. Run them by hand against the production database's direct (unpooled) URL, before deploying code that needs them: `DATABASE_URL=<DATABASE_URL_UNPOOLED> alembic upgrade head`.
- **Seed data:**
  - Holidays come from the `holidays_seed` job.
  - The default categories and the Cash account are created per household at signup (schemas §4.1). There is no global seed for them.

### 4.2 Backups
- **Nightly backup:** `pg_dump -Fc` at **02:00**, stored **off the server** (for example an S3-compatible bucket), and encrypted.
- **Retention:** 7 daily backups, 4 weekly backups and 6 monthly backups.
- **Restore test:** restore the latest backup into a temporary container **once a month**, and record the result.

---

## 5. Logging and privacy

- **Structured logs:** one JSON line per request, containing method, path, status, duration, `user_id` and `household_id`.
- **Never logged:** request bodies, passwords, tokens, cookies, CPF, phone numbers or addresses (the LGPD note in schemas §5).
- **Errors:** unhandled exceptions are logged with a stack trace. The response contains only the error envelope (api.md §2) with a `request_id`, and the same `request_id` appears in the log line.
- **Log size:** container logs use Docker's `json-file` driver with rotation (`max-size: 10m`, `max-file: 5`).

---

## 6. Security checklist

- Only HTTPS is allowed. Caddy redirects HTTP and sends `Strict-Transport-Security`.
- Only ports 80 and 443 are open (firewall). The database and Mailpit are reachable only on the internal Docker network.
- Secrets live only in `.env` on the server, with file permissions `600`.
- Images are rebuilt monthly to pick up base-image security patches.

---

## 7. Local development

```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

- **Development overrides:** `api` runs with `--reload` and the source code mounted. `mailpit` is added. There is no `proxy`.
- **UI:** `pnpm dev` on port 3000, with `rewrites` sending `/api/*` to `http://localhost:8000`.
- **Demo data:** `python -m app.scripts.seed_demo` creates a demo household with two members, accounts, cards, a few months of entries and recurrences. It is used for manual testing and for building the dashboard.
- **Tests:** `pytest` runs against a dedicated Postgres test database, not SQLite, because the schema uses decimal and array types. Each test runs inside a transaction that is rolled back.
