# Deployment

The stack is Supabase PostgreSQL, FastAPI Cloud, Vercel, and the existing Qdrant
collection. Supabase Auth is not used: the API owns users and JWT authentication.
Use separate Pole Position resources; do not change Voyage AI resources.

## Database

Create a Supabase project. Disable the Data API and automatic table exposure:
the frontend never connects directly to PostgreSQL. Use the **session pooler**
connection on port **5432**, with a URL beginning `postgresql+asyncpg://`.
Percent-encode special characters in the password. Set `DATABASE_SSL=true`.
Set `DATABASE_SSL_CA_FILE=./data/certificates/supabase-ca.crt` to verify the
server against the official Supabase CA (downloaded from Database Settings).
Avoid the transaction pooler on port 6543 for this configuration.

Run `uv run alembic upgrade head` with the new production `DATABASE_URL` and
`DATABASE_SSL=true` supplied privately as environment variables. Verify the
target project first. Do not run pytest against production or set
`TEST_DATABASE_URL` in the production app. Migrations are an explicit release
step, not an application startup side effect.

## Backend

Prepare the local deployable corpus before every backend release:

```sh
uv run python scripts/prepare_deployment.py
```

The generated `deployment_data/` contains the active manifest and six validated
chunk artifacts. It contains no PDFs, credentials, or vectors. It stays out of
GitHub but is included in local FastAPI Cloud CLI uploads through
`.fastapicloudignore`. A plain GitHub checkout **does not contain this bundle**;
do not enable backend GitHub auto-deployment until a private artifact-delivery
step has been configured. Old local corpus files and rollback backups remain.

FastAPI entrypoint: `pole_position.main:app` (configured in `pyproject.toml`).
Set these FastAPI Cloud environment variables privately:

| Variable | Production value |
| --- | --- |
| `DATABASE_URL` | New Supabase session-pooler URL, `postgresql+asyncpg://…` |
| `DATABASE_SSL` | `true` |
| `DATABASE_SSL_CA_FILE` | `./data/certificates/supabase-ca.crt` |
| `JWT_SECRET_KEY` | Strong private secret |
| `OPENAI_API_KEY` | Private OpenAI key |
| `ANSWER_MODEL` | The model already verified by live chat |
| `RERANK_ENABLED` | `true` |
| `QDRANT_URL` | Existing Qdrant Cloud URL |
| `QDRANT_API_KEY` | Private Qdrant key |
| `QDRANT_COLLECTION` | `fia_regulations` |
| `CORPUS_ROOT` | `./deployment_data` |
| `VALIDATE_CORPUS_ON_STARTUP` | `true` |
| `CORS_ORIGINS` | Exact approved frontend origin(s), comma-separated |

After login and approval, deploy to the explicit Pole Position app:

```sh
uv run fastapi deploy --app-id YOUR_POLE_POSITION_APP_ID
```

Check `/api/health` and `/api/ready`. Readiness verifies the local BM25 corpus,
not external service availability. Perform a real guest question, then test
registration/login and a saved follow-up conversation. Updating local PDFs or
Qdrant is not enough: redeploy a new bundle after changing the active manifest.

## Frontend

Import the GitHub repository into Vercel with root directory `frontend`, preset
Vite, build command `npm run build`, output `dist`. Set:

```ini
VITE_API_BASE_URL=https://YOUR_BACKEND.fastapicloud.dev/api
```

The `/api` suffix is required. This variable is public; **never** put OpenAI,
Qdrant, database, or JWT secrets in any `VITE_` variable. Frontend API URLs are
compiled at build time, so rebuild after changing them. Set the exact Vercel
origin in backend `CORS_ORIGINS`; preview URLs are not automatically allowed.

## Release checks and limits

Run backend tests against a dedicated `_test` database and frontend build/tests
before publishing. Check public guest chat, citation drawer, auth, saved chats,
and follow-ups after publishing. Keep the previous backend deployment available
for rollback.

Guest chat makes paid model requests. CORS is not abuse protection: the API
currently has no distributed rate limiter. Configure provider spending alerts
and decide appropriate usage limits before promoting the public demo widely.
Hosting free/Hobby tiers also have resource limits; do not upgrade without
approval.
