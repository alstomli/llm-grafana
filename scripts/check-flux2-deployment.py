"""Read-only FLUX.2 dashboard/exporter checks through Grafana's private datasource."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UID = 'flux2-inference'
ROOT = Path(__file__).resolve().parents[1]
SELECTORS = re.compile(r'\b(?:up|ALERTS|gpu_[a-zA-Z0-9_:]+|flux2_[a-zA-Z0-9_:]+)\{((?:"[^"]*"|[^{}])*)\}')


def validate_dashboard(dashboard):
    assert dashboard['uid'] == UID, 'Wrong dashboard UID'
    panels = dashboard['panels']
    assert len(panels) == 18 and len({p['id'] for p in panels}) == 18
    variable = next(v for v in dashboard['templating']['list'] if v['name'] == 'pod')
    assert variable['query']['query'] == 'label_values(up{job="flux2"}, instance)'
    assert variable['multi'] is False and variable['includeAll'] is False
    for panel in panels:
        assert panel['datasource']['uid'] == 'prometheus'
        for target in panel['targets']:
            expr = target['expr']
            selectors = SELECTORS.findall(expr)
            assert selectors, f'No metric selector in {panel["title"]}'
            assert all('job="flux2"' in s and 'instance="${pod}"' in s for s in selectors), panel['title']
            assert 'vllm' not in expr and 'or vector(0)' not in expr
            assert not re.search(r'\b(user_id|job_id|prompt|account_id)\s*=', expr)
            if '_bucket' in expr:
                assert 'histogram_quantile(0.95, sum by(le)' in expr
            if panel['title'].startswith('GPU ') and panel['type'] == 'timeseries':
                assert '{{gpu}}' in target['legendFormat']
    return panels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='https://grafana-production-5c5e.up.railway.app')
    parser.add_argument('--expected-instance', required=True, help='Exact image metrics proxy hostname')
    parser.add_argument('--settings-file', default=os.environ.get('GRAFANA_SETTINGS_FILE', str(ROOT / '.secrets/railway-grafana.env')))
    args = parser.parse_args()
    assert re.fullmatch(r'[a-zA-Z0-9.-]+', args.expected_instance), 'Invalid metrics hostname'
    settings = dict(line.split('=', 1) for line in Path(args.settings_file).read_text().splitlines() if '=' in line)
    credential = base64.b64encode(('admin:' + settings['GRAFANA_PASSWORD']).encode()).decode()

    def get(path):
        request = Request(args.url.rstrip('/') + path, headers={'Authorization': 'Basic ' + credential})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def prom(path):
        result = get('/api/datasources/proxy/uid/prometheus' + path)
        assert result['status'] == 'success', 'Prometheus query failed'
        return result['data']

    def query(expr):
        return prom('/api/v1/query?' + urlencode({'query': expr}))['result']

    dashboard = get('/api/dashboards/uid/' + UID)
    panels = validate_dashboard(dashboard['dashboard'])
    assert dashboard['meta']['provisioned'] is False, 'Keep this dashboard database-managed'
    targets = [t for t in prom('/api/v1/targets')['activeTargets'] if t['labels'].get('job') == 'flux2']
    assert {t['labels']['instance'] for t in targets} == {args.expected_instance}, 'Unexpected image scrape targets'
    assert all(t['health'] == 'up' for t in targets), 'Image scrape unavailable'
    selector = '{job="flux2",instance="' + args.expected_instance + '"}'
    for metric in ('up', 'flux2_model_ready', 'gpu_exporter_up'):
        values = query(metric + selector)
        assert len(values) == 1 and values[0]['value'][1] == '1', f'{metric} must be healthy'
    oom = query('flux2_oom_total' + selector)
    assert len(oom) == 1 and float(oom[0]['value'][1]) == 0, 'OOM counter must be present and zero during rollout acceptance'
    for metric in ('gpu_memory_used_bytes', 'gpu_memory_total_bytes'):
        values = query(metric + selector)
        assert {v['metric'].get('gpu') for v in values} == {'0', '1'}, f'{metric}: both GPUs required'
        assert all(float(v['value'][1]) > 0 for v in values), 'Missing GPU memory measurement'
    jobs = query('flux2_jobs' + selector)
    counts = {v['metric'].get('state'): float(v['value'][1]) for v in jobs}
    assert 'running' in counts, 'Missing active-job gauge'
    assert counts.get('queued', 0) == 0 and 0 <= counts['running'] <= 1, 'Only one immediate job and no waiting queue are allowed'
    for panel in panels:
        for target in panel['targets']:
            # Parse/execute every real dashboard query; idle histogram/counter series
            # may legitimately have no observations and are never replaced with zero.
            query(target['expr'].replace('${pod}', args.expected_instance).replace('$__rate_interval', '5m'))
    rules = prom('/api/v1/rules?type=alert')['groups']
    flux_rules = [r for group in rules if group['name'] == 'flux2' for r in group['rules']]
    expected_rules = {'Flux2ScrapeDown', 'Flux2ModelNotReady', 'Flux2GpuCollectorDown',
                      'Flux2RequiredMetricsMissing', 'Flux2OutOfMemory', 'Flux2GenerationFailures',
                      'Flux2DiskLow', 'Flux2DiskCritical'}
    assert {r['name'] for r in flux_rules} == expected_rules and all(r['health'] == 'ok' for r in flux_rules), 'FLUX.2 alert rules missing or unhealthy'
    print('PASS: image dashboard, protected scrape, both GPUs, no-queue admission, queries and alert rules')


if __name__ == '__main__':
    main()
