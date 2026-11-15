# LLM Grafana

## FLUX.2 image dashboard

`dashboards/flux2.json` is a separate database-managed dashboard with UID
`flux2-inference`. Import it after the companion Prometheus `flux2` job and
image backend are healthy. Keep `inference-baseline`, its 24 panels and its
revision history intact. No Grafana image rollout or file provisioning is needed.
Back up the current live dashboards before an API/UI import and export the saved
image dashboard afterward. Use Grafana's version check when overwriting it later.

The **Image Pod** variable discovers only `up{job="flux2"}`. Every panel filters
the selected instance before aggregation; both GPUs retain their `gpu` label.
Eighteen panels show readiness, scrape/GPU collector health, output disk space,
active jobs, starts/completions, safe failure/rejection
categories, generation/job p95 latency, GPU measurements, load/generation OOM count and alert state.
Idle percentiles and missing measurements remain **No data**. No prompts, user
UUIDs or job IDs are metric labels. A ready/GPU chart complements the backend's
BF16/no-offload validation; charts alone do not prove dtype or tensor placement.

The companion Prometheus repository owns eight alert rules and threshold tests,
including immediate detection of any observed OOM and missing required exporter
metrics. Live acceptance requires the initialized OOM counter to be zero.
The alert panel displays pending/firing rules; outbound notifications require
separate Alertmanager configuration and a chosen receiver. Browser-only image
retention is independent of the backend's 24-hour temporary output TTL.
Job/status/idempotency and daily usage are process-local and reset on service
restart; busy requests receive 429 immediately, with no waiting queue.

Read-only acceptance (use the actual Pod hostname, without a scheme):

```sh
python scripts/test_flux2_dashboard.py
promtool test rules scripts/flux2-queries.test.json
GRAFANA_SETTINGS_FILE=/path/to/private/settings.env python scripts/check-flux2-deployment.py --expected-instance image-pod-8889.proxy.runpod.net
```

The cloud check verifies the live dashboard, private datasource, healthy model,
both GPUs, single active-job/no-queue bounds, all panel queries and eight loaded
alert rules. It does not generate images or change deployments. Also run the
existing `scripts/check-deployment.py` with current chat instances to verify chat
monitoring. For rollback, remove/disable the image scrape while retaining chat
targets and both monitoring volumes; keep the separate image dashboard for history.

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

## Current BF16 Pod

The database-managed `inference-baseline` dashboard retains its 24 panels.
Its single-select **Pod** variable is restricted to
`label_values(up{job="vllm",instance="zwwucot0v5wy0b-8889.proxy.runpod.net"}, instance)`
and saves `zwwucot0v5wy0b` as the current selection.

Every vLLM/GPU selector includes `job="vllm"` and `instance="${pod}"`
before aggregation. Historical series retain their original instance labels.
The November 15, 2026 migration from `66j3wfha6suokg` changed only the
variable definition, query and current value in live dashboard version 14.
Panels, layout, private datasource, volume and revision history are preserved.
The snapshot is exported from that saved live dashboard; no image rollout is needed.
Back up the latest live dashboard privately before any subsequent API update,
keep its current version, and save with `overwrite: false` for conflict detection.

Validate login protection, all 24 filters, the private datasource and the chat
scrape/GPU health with:

```sh
python scripts/check-deployment.py \
  --expected-instance zwwucot0v5wy0b-8889.proxy.runpod.net
```

For a worktree, `GRAFANA_SETTINGS_FILE` can point to the existing ignored settings
file. This check covers the `vllm` job; the separate FLUX.2 check is above.
Latency and token-rate panels require inference activity in the selected range;
idle/unavailable metrics are not replaced with invented zero values.

## Local Docker

Create the shared Docker network once with `docker network create llm-monitoring`
(skip creation if it already exists). Start Prometheus from its sibling repository
first. Copy `.env.example` to `.env`, supply a password, and run
`docker compose up -d --build` here. Open http://127.0.0.1:3000. Grafana reaches
`http://prometheus:9090` through the shared Docker network.

The default volume name reuses the old local `monitoring_grafana-data` volume
if it exists. Set `GRAFANA_VOLUME_NAME` to choose another volume; never use
`down -v` when retaining dashboard data. Import the snapshot on a new database.
