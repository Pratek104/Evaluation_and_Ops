# Deployment

## Prerequisites

- Python 3.10+ for a direct deployment, or Docker.
- An OpenRouter API key for chat answers.
- The handbook PDF at `data/raw/xyz_company.pdf` or a custom `PDF_PATH`.
- Persistent storage for `data/runtime/`.

## Environment

Start from `.env.example` and provide values through your platform's secret
manager where possible:

```dotenv
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=google/gemma-4-26b-a4b-it:free
PDF_PATH=data/raw/xyz_company.pdf
RBAC_DB_PATH=data/runtime/xyz_rbac.db
RAG_CACHE_DIR=data/runtime/rag_cache
LOG_LEVEL=INFO
```

Do not commit the resulting `.env`.

## Direct Python deployment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m streamlit run streamlit_app.py \
  --server.address=0.0.0.0 \
  --server.port=8501 \
  --server.headless=true
```

Use a process supervisor (systemd, Windows Service, or a platform runner) to
restart the process and capture logs.

## Docker

Build:

```bash
docker build -t xyz-employee-portal .
```

Run with a persistent runtime volume:

```bash
docker run --rm -p 8501:8501 \
  --env-file .env \
  -v "$(pwd)/data/runtime:/app/data/runtime" \
  xyz-employee-portal
```

Compose:

```bash
docker compose up --build -d
```

The image:

- uses Python 3.12 slim,
- installs the package from `pyproject.toml`,
- runs as the unprivileged `app` user,
- exposes port `8501`,
- declares `/app/data/runtime` as a volume,
- checks `/_stcore/health` for container health.

### First start

The first chat request downloads the local embedding model and builds the cache.
Allow outbound access to the model source, or pre-populate
`data/runtime/rag_cache/` from a trusted build. The database is seeded
automatically.

## Reverse proxy

Put the app behind a TLS-terminating proxy such as nginx, Caddy, or a cloud load
balancer. Streamlit supports WebSockets, so enable connection upgrades and avoid
short proxy timeouts.

Example nginx location:

```nginx
location / {
    proxy_pass http://127.0.0.1:8501;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
}
```

## Persistence and backups

Back up:

- `data/runtime/xyz_rbac.db` (authentication, directory, audit),
- `data/runtime/rag_cache/` (optional; can be rebuilt),
- the configured handbook PDF.

Use SQLite's online backup mechanism or stop the app before copying the database.
Test restores periodically.

## Scaling notes

The default deployment is single-instance. Streamlit session state, the SQLite
database, and the embedding cache are local. For multiple replicas:

1. Move RBAC and audit data to a shared database.
2. Replace local session assumptions with a shared session strategy.
3. Share or prebuild the embedding cache.
4. Ensure all replicas use the same handbook version and model configuration.

## Operations

Health check:

```bash
curl http://localhost:8501/_stcore/health
```

Reset demo data only in non-production environments:

```bash
python scripts/reset_demo_data.py --yes
python scripts/verify_seed.py
```

Logs go to standard error with the format configured in `xyz_portal.config`.
Set `LOG_LEVEL` to `DEBUG` only for short troubleshooting windows.
