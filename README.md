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

## Choose a Runpod Pod

The existing `inference-baseline` dashboard retains its 24 panels and has two
variables. **Profile** (`profile`) offers `4bit` and `bf16` and opens on `4bit`.
**Pod** (`pod`) lists only the selected profile's Pods, the most recently scraped
first, by querying the latest `up` sample time of each instance in the selected
time range. It uses named regex captures to display the Pod ID
while retaining the full instance hostname as its value. Selection is single-Pod
and no Pod is saved; Grafana selects the first in the list. Keep the variable's
sort disabled: alphabetical order can select a previous Pod after a migration.
When saving the dashboard, do not save the current variable values, and leave the exported Pod empty.

The `profile` label comes from Prometheus. Series collected before it was added
do not appear in the Pod picker. After a migration the previous Pod stays listed
while the selected time range covers its data.

Every vLLM/GPU metric selector includes `job="vllm"` and
`instance="${pod}"`. Filtering happens before sums, rates, and histogram
quantiles, so selecting one Pod does not combine its latency buckets or counters
with the other Pod. Existing instance labels and historical series are retained.
The panel IDs, layout, units, and visualization settings are reused.

The monitored Pods are whatever Prometheus scrapes; this repository does not
list them. The current Pod of each profile is recorded in `llm-inference-server`.

The live dashboard is backed up before editing and updated in its database using
the same UID and a version check. No Grafana image redeployment is needed. The
repository snapshot is the edited live dashboard. The related Prometheus and
Runpod changes are documented in their sibling repositories.

Validate all 24 filters, the scrapes, and GPU health with:

```sh
python scripts/check-deployment.py
```

This requires every vLLM target to be up. When a profile is stopped on purpose,
name only the profiles that must be up (repeat `--profile` for more than one):

```sh
python scripts/check-deployment.py --profile 4bit
```

A named profile with no target fails. Add `--expected-instance` once per Pod to
also require that the checked targets are exactly those hostnames:

```sh
python scripts/check-deployment.py --profile 4bit \
  --expected-instance your4bitpodid-8889.proxy.runpod.net
```

For a worktree, `GRAFANA_SETTINGS_FILE` can point to the existing ignored settings
file. Query validation uses the actual private Prometheus datasource. Latency and
token-rate panels need inference activity inside the selected time range;
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
