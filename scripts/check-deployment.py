"""Check the deployed cloud dashboard without printing credentials."""
import base64
import argparse
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = 'https://grafana-production-5c5e.up.railway.app'
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--expected-instance', action='append', default=[])
args = parser.parse_args()
settings_file = Path(os.environ.get('GRAFANA_SETTINGS_FILE', root / '.secrets/railway-grafana.env'))
settings = dict(line.split('=', 1) for line in settings_file.read_text().splitlines() if '=' in line)
authorization = 'Basic ' + base64.b64encode(('admin:' + settings['GRAFANA_PASSWORD']).encode()).decode()


def get(path, authenticated=False):
    headers = {'User-Agent': 'monitoring-check/1.0'}
    if authenticated:
        headers['Authorization'] = authorization
    with urlopen(Request(BASE + path, headers=headers), timeout=30) as response:
        return json.load(response)


assert get('/api/health')['database'] == 'ok'
try:
    get('/api/search')
except HTTPError as error:
    assert error.code == 401
else:
    raise AssertionError('Grafana must require login')
print('PASS: HTTPS health and login protection')

dashboard = get('/api/dashboards/uid/inference-baseline', True)['dashboard']
assert len(dashboard['panels']) == 24
panel_titles = {panel['title'] for panel in dashboard['panels']}
assert {'TPOT p95', 'First-token latency(TTFT) p95', 'Inter-token latency(ITL) p95'} <= panel_titles
assert get('/api/dashboards/uid/inference-baseline', True)['meta']['provisioned'] is False
variables = dashboard.get('templating', {}).get('list', [])
pod_variable = next(item for item in variables if item['name'] == 'pod')
assert pod_variable['label'] == 'Pod' and pod_variable['multi'] is False
metric_names = re.compile(r'\b(?:up|gpu_[a-zA-Z0-9_:]+|vllm:[a-zA-Z0-9_:]+)')
selector_suffix = '{job="vllm",instance="${pod}"}'
for panel in dashboard['panels']:
    for target in panel.get('targets', []):
        expr = target.get('expr', '')
        for match in metric_names.finditer(expr):
            assert expr.startswith(selector_suffix, match.end()), f'Unfiltered metric in panel {panel["id"]}'
datasource = get('/api/datasources/uid/prometheus', True)
assert datasource['url'] == 'http://prometheus.railway.internal:9090'
assert get('/api/datasources/uid/prometheus/health', True)['status'] == 'OK'
print('PASS: 24 dashboard panels and private Prometheus connection')

targets = get('/api/datasources/proxy/uid/prometheus/api/v1/targets', True)['data']['activeTargets']
active_targets = [target for target in targets if target['labels'].get('job') == 'vllm']
assert active_targets and all(target['health'] == 'up' for target in active_targets), 'Active vLLM scrape target is unhealthy'
active_instances = {target['labels']['instance'] for target in active_targets}
if args.expected_instance:
    assert active_instances == set(args.expected_instance), 'Unexpected active Pod scrape targets'

for query in ['up{job="vllm"}', 'gpu_exporter_up']:
    path = '/api/datasources/proxy/uid/prometheus/api/v1/query?' + urlencode({'query': query})
    result = get(path, True)['data']['result']
    # A migrated Pod can leave old samples visible until Prometheus marks them stale.
    result = [item for item in result if item['metric'].get('instance') in active_instances]
    assert {item['metric']['instance'] for item in result} == active_instances, f'{query} is missing a Pod'
    assert result and all(item['value'][1] == '1' for item in result), f'{query} is not healthy'
    print(f'PASS: {query} = 1')

print('PASS: Cloud monitoring is collecting live Runpod metrics')
