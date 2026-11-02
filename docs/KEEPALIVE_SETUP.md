# Pole Position availability monitoring

Verified against current official documentation on **2 November 2026**.
Implementation is local only: no deployment, production environment change,
monitoring token, or external job was created as part of this change.

## What this checks

`GET https://pole-position.fastapicloud.dev/internal/keepalive`

The hostname comes from this project's deployed API links in `README.md` and
`frontend/.env.example`, not Voyage AI. The route is **outside `/api`**. The
Vercel frontend is not the scheduler target. If the backend domain changes,
update this URL and the job together.

The route requires a dedicated `KEEPALIVE_TOKEN` matched against the
`X-Keepalive-Token` header using `secrets.compare_digest`. Missing, incorrect,
empty, or unconfigured tokens return **403**, before any database access.
There is no bearer-token or query-string alternative.

An authorized request checks out a connection from the application's existing
SQLAlchemy/asyncpg engine, runs `SELECT 1` against its configured `DATABASE_URL`,
and returns **200** with `{"status":"ok","database":"ok"}` only on success.
Connection, SQL, or timeout failure returns generic **503**. The route's
200/403/503 responses have `Cache-Control: no-store`; it does not disclose
database details or log exception messages/header values.

No tables, migrations, writes, Supabase Auth calls, embeddings, Qdrant queries,
or model requests are involved. Existing public endpoints remain distinct:

| Endpoint | Purpose |
| --- | --- |
| `/api/health` | Public liveness only; does not access PostgreSQL |
| `/api/ready` | Local retrieval corpus/BM25 readiness; not a database probe |
| `/internal/keepalive` | Private HTTP + application database connectivity probe |

The new endpoint does not appear in Swagger. Application startup gains no
network checks or background loop. Existing optional startup corpus validation
is retained because it verifies the required private deployment bundle.

## Hosting limits: review before enabling

**Monitoring is not an always-on free-hosting guarantee.** Checks may reduce
cold starts and inactivity pauses; outages, quota limits, cold-start latency,
and provider policy still apply. Do not use shorter intervals to circumvent
plan restrictions.

- **FastAPI Cloud Hobby:** minimum replicas remain zero; idle apps scale down.
  Current pricing documents a **planned 180 Nano replica-hours per billing
  period, shared across the team's apps**, with resource billing not yet
  invoiced during beta. One replica kept running for 30 days uses about 720
  replica-hours, including idle time. Thus the requested five-minute schedule
  could exceed the planned allowance, especially with Voyage AI in the same
  team. Check the actual account plan/notices before enabling continuous
  monitoring; use limited demo windows or an appropriate plan if necessary.
  Do not assume every five-minute request uses only its SQL execution time.
  [Usage and pricing](https://fastapicloud.com/docs/team-management/billing/usage-based-billing/),
  [autoscaling](https://fastapicloud.com/docs/advanced-features/autoscaling/).
- **Supabase Free:** low database activity over seven days can cause pausing.
  Application database queries count as activity, but no request frequency
  guarantees exemption. A paused project must be resumed in Supabase; this
  endpoint does not call a resume API. Free also has database/resource limits;
  monitor usage rather than relying on synthetic traffic alone.
  [Pausing policy](https://supabase.com/docs/guides/platform/free-project-pausing),
  [plan limits](https://supabase.com/pricing).
- **cron-job.org:** executions normally have a 30-second limit; delays and
  failures are possible. Repeated failures can deactivate a job. Monitoring
  itself therefore needs notifications and history review.
  [Official FAQ](https://cron-job.org/en/faq/).

At five-minute intervals there are 288 requests/day. **Do not enable a 24/7
schedule until you have reviewed the shared compute budget.** A monitoring
schedule does not reserve capacity or provide an SLA.

## Your deployment and secret setup

1. Review and deploy the local changes yourself. Follow [deployment.md](deployment.md)
   for the existing private corpus bundle and separate backend/frontend release
   steps. There is no migration to apply for monitoring.
2. Generate a **NEW Pole Position-only** random 32-byte monitoring token locally.
   On macOS this copies the result without printing it:

   ```sh
   openssl rand -hex 32 | pbcopy
   ```

   This is a separate token from Voyage AI, JWT signing, OpenAI, Qdrant, and the
   cron-job.org account API key. Never reuse any of those secrets.
3. Store the token as `KEEPALIVE_TOKEN` in **Pole Position's backend environment**
   and as the header value in **Pole Position's own cron-job.org job**. Apply the
   backend environment using the provider's normal release/restart workflow.
   Never place it in `VITE_` variables, Git, screenshots, the job URL, logs, or
   chat. `.env.example` intentionally has an empty placeholder; that disables
   the endpoint until configured. Local development may use its own separate
   test token in an ignored `.env`.
4. Verify the deployment before enabling the scheduled job. Check the hostname,
   credentials, and success body below. Do not send a token to an unverified
   redirect or a different application's backend.

## Create a separate job in your existing cron-job.org account

This is a manual setup checklist, **not** an instruction to modify Voyage AI's
job or create anything automatically.

| Setting | Value |
| --- | --- |
| Name | `Pole Position — availability` |
| URL | `https://pole-position.fastapicloud.dev/internal/keepalive` |
| Method | `GET` |
| Custom header | `X-Keepalive-Token: <the new Pole Position token>` |
| Request body | None |
| Schedule | Every five minutes (`*/5 * * * *`), subject to the budget review above |
| Scheduler timeout | **30 seconds** |
| Success criterion | **HTTP 200**; verify the expected JSON on the initial test |
| Redirects | Do not treat redirects as success; use the final HTTPS URL directly |
| Failure notification | Enabled; notify after the first failure |
| Recovery notification | Enabled; success after a previous failure |
| Automatic deactivation notification | Enabled |

Select a notification channel/email you actually receive and check account
notification preferences. The documented notification fields are `onFailure`,
`onFailureCount=1`, `onSuccess`, and `onDisable`; labels may differ in the UI.
See the [official job settings](https://docs.cron-job.org/rest-api.html).
Treat the custom header as a credential when sharing job configuration.

## Local and deployed verification

Start the local backend normally with its own ignored development environment:

```sh
uv run uvicorn pole_position.main:app --reload
```

These read-only checks need no token and should yield 200 and 403 respectively:

```sh
curl -i --max-time 30 http://127.0.0.1:8000/api/health
curl -i --max-time 30 http://127.0.0.1:8000/internal/keepalive
```

To verify the authorized local endpoint without echoing the token or putting it
in process arguments, use a hidden prompt:

```sh
uv run python - <<'PY'
import getpass
import httpx

url = "http://127.0.0.1:8000/internal/keepalive"
token = getpass.getpass("Pole Position monitoring token: ")
try:
    response = httpx.get(url, headers={"X-Keepalive-Token": token},
                         timeout=30, follow_redirects=False)
    print("HTTP", response.status_code)
    print("Cache-Control:", response.headers.get("cache-control"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response.headers.get("cache-control") == "no-store"
    print("HTTP and database probe passed.")
except (httpx.HTTPError, AssertionError, ValueError):
    print("Probe failed; inspect the status, deployment, and provider dashboards privately.")
    raise SystemExit(1) from None
PY
```

For deployed verification, change only `url` to the exact HTTPS endpoint above
and use the deployed Pole Position token. A scheduler's 30 seconds includes
provider cold start before Python begins. A 30-second client timeout is not
necessarily a database failure.

### Confirm scheduled runs and real database activity

1. Use the job's manual test, then inspect at least two **scheduled** executions
   roughly five minutes apart. Verify HTTP 200, response body, duration, and
   `Cache-Control: no-store`. Check the job is still enabled and its next-run
   time is set. Do not confuse a manual success with an active schedule.
2. Confirm corresponding `/internal/keepalive` access-log entries on FastAPI
   Cloud. Do not enable request-header logging. Inspect compute usage/notices
   for the whole team, not just this application.
3. Inspect Supabase database query activity around those timestamps. The probe
   uses direct PostgreSQL, so Auth/Data API traffic charts need not increase.
   If available, Query Performance / `pg_stat_statements` should show executions
   of `SELECT 1` (possibly normalized). Pool pre-pings can also contribute;
   do not expect a strict one-to-one count or enable/reset extensions or logs
   just for this check. HTTP 200 itself is only emitted after the SQL returns.
4. Test failure/recovery behavior locally by stopping/restarting **only your
   local development database**. Expect 503 then 200. Never stop production or
   alter its credentials merely to test monitoring notifications. For scheduler
   alerts, use a disposable test job if desired, not changes to the production
   database or the real job's stored secret.

## Timeouts and first-load resilience

- Existing `pool_pre_ping=True` handles stale pooled connections. Pool checkout
  and asyncpg connection establishment are each bounded at five seconds;
  commands have a ten-second driver timeout. TLS verification is unchanged.
- The keepalive request has an **eight-second overall application deadline**,
  including checkout, reconnect/pre-ping, SQL, and connection return. It is not
  an eight-second guarantee for the hosting platform's cold start.
- Frontend body-free GET requests use a 15-second per-attempt deadline with at
  most two retries after 500ms and 1000ms. Network errors, read timeouts, and
  502/503/504 are retryable; auth/validation/rate-limit errors and malformed
  successful JSON are not. The full read budget is about 46.5 seconds.
- Mutations, including chat generation, registration, login, rename, and delete,
  have a 180-second deadline and **no automatic retries**. A client timeout does
  not guarantee the server stopped or rolled back a write. Inspect saved state
  before explicitly resubmitting. Caller cancellation also cancels backoff;
  existing loading, retry, and session-recovery UI remain in place.

These changes neither resume paused infrastructure nor guarantee model/Qdrant
availability or generated-answer quality.

## Tests

```sh
uv run pytest -q tests/test_keepalive.py tests/test_health.py tests/test_deployment.py
cd frontend
npm test
npm run build
```

The real-SQL endpoint test uses the existing guarded `TEST_DATABASE_URL` fixture:
it must be a separate `postgresql+asyncpg` database ending in `_test`. It records
an actual `SELECT 1` against that database. Never set test URLs to production.
Other tests simulate acquisition, query, release, timeout, authentication, and
frontend retry boundaries without cloud calls.

## Disable or rotate monitoring

Disable the **Pole Position** job in cron-job.org first. Remove/empty
`KEEPALIVE_TOKEN` in this backend's environment and apply that change; subsequent
probe requests return 403 without database access. Public health and chat remain
available independently. To rotate, generate a fresh project-only token and
replace both copies; expect failures during a non-atomic update. Never disable
notifications just to hide a failing job. Do not pause/delete the database to
disable monitoring, and do not change Voyage AI's job or token.
