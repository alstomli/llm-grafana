# LLM Grafana

Grafana for the personal Qwen chat system. Sibling projects:
[LLM server](https://github.com/alstomli/llm-inference-server),
[Prometheus](https://github.com/alstomli/llm-prometheus), and
[chat frontend](https://github.com/alstomli/qwen-chat).

## Files

- `Dockerfile`: extends official `grafana/grafana:12.1.0`.
- `provisioning/datasource.yml`: connects to Prometheus using `PROMETHEUS_URL`.
- `provisioning/dashboards.yml`: retires the legacy file provider safely.
- `dashboards/inference.json`: export/restore snapshot of the 24-panel dashboard.
- `scripts/check-deployment.py`: verifies cloud login protection, the dashboard, private Prometheus connectivity, and the active Pod scrape.

## Dashboard editing and backups

The live dashboard is stored in Grafana's SQLite database on its persistent
`/var/lib/grafana` volume. Use **Edit → Save dashboard** in the browser.
The image does not copy dashboard JSON into Grafana. An empty legacy provider
with `disableDeletion: true` preserves dashboards and revision history while
releasing them from file provisioning. Keep that configuration for migrations.

For a fresh database, import `dashboards/inference.json` through Grafana once.
To update through JSON, export the latest live dashboard first, edit it, then
import with UID `inference-baseline` and choose overwrite. Export after UI edits
to keep the snapshot current in Git. Never roll back to an old image that
provisions this dashboard from a file: that can overwrite UI edits.

## Build

From this repository root:

```sh
docker buildx build --platform linux/amd64 --load -t zihan000/llm-grafana:local .
```

Choose a new release tag when publishing to Docker Hub. Existing Railway service
still uses `zihan000/qwen-inference:grafana-0.1.3`; repository separation does not
replace that published image or change the running service.

## Railway

Run alongside `llm-prometheus` in the same Railway project/environment:

- Service name `grafana`, port `3000`, volume `/var/lib/grafana`.
- `PORT=3000`, `GF_SERVER_HTTP_PORT=3000`.
- `PROMETHEUS_URL=http://prometheus.railway.internal:9090`.
- `GF_SECURITY_ADMIN_USER=admin` and a secret `GF_SECURITY_ADMIN_PASSWORD`.
- `GF_SERVER_ROOT_URL` = the public HTTPS origin; `GF_SECURITY_COOKIE_SECURE=true`.
- Preserve the existing `RAILWAY_RUN_UID=0` if the volume requires it.
- Health endpoint `/api/health`, one replica, serverless sleeping disabled.
- Keep anonymous access and signup disabled. Existing resource ceilings are
  0.5 vCPU and 0.5 GB RAM.

Dashboard: https://grafana-production-5c5e.up.railway.app/d/inference-baseline

The local cloud-login file `.secrets/railway-grafana.env` contains
`GRAFANA_PASSWORD` for `python scripts/check-deployment.py`. It and local JSON
backups are ignored by Git and excluded from image builds.

## Local Docker

Create the shared Docker network once with `docker network create llm-monitoring`
(skip creation if it already exists). Start Prometheus from its sibling repository
first. Copy `.env.example` to `.env`, supply a password, and run
`docker compose up -d --build` here. Open http://127.0.0.1:3000. Grafana reaches
`http://prometheus:9090` through the shared Docker network.

The default volume name reuses the old local `monitoring_grafana-data` volume
if it exists. Set `GRAFANA_VOLUME_NAME` to choose another volume; never use
`down -v` when retaining dashboard data. Import the snapshot on a new database.
