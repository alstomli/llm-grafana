"""Validate image query isolation, the chat dashboard and its deployment check."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import runpy
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('flux_check', Path(__file__).with_name('check-flux2-deployment.py'))
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = json.loads((ROOT / 'dashboards/flux2.json').read_text(encoding='utf-8'))

    def test_all_image_queries_are_scoped_and_gpu_series_separate(self):
        checker.validate_dashboard(self.dashboard)
        rectangles = [p['gridPos'] for p in self.dashboard['panels']]
        for i, a in enumerate(rectangles):
            self.assertLessEqual(a['x'] + a['w'], 24)
            for b in rectangles[i + 1:]:
                overlap = a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']
                self.assertFalse(overlap, 'Overlapping panels')

    def test_unscoped_queries_and_zero_fallback_fail_validation(self):
        for old, new in [('instance="${pod}"', 'instance=~".*"'), ('job="flux2"', 'job="vllm"')]:
            bad = copy.deepcopy(self.dashboard)
            bad['panels'][0]['targets'][0]['expr'] = bad['panels'][0]['targets'][0]['expr'].replace(old, new)
            with self.assertRaises(AssertionError):
                checker.validate_dashboard(bad)
        bad = copy.deepcopy(self.dashboard)
        bad['panels'][0]['targets'][0]['expr'] += ' or vector(0)'
        with self.assertRaises(AssertionError):
            checker.validate_dashboard(bad)

    def test_chat_dashboard_contract_remains_distinct(self):
        chat = json.loads((ROOT / 'dashboards/inference.json').read_text())
        self.assertEqual(chat['uid'], 'inference-baseline')
        self.assertEqual(len(chat['panels']), 24)
        self.assertNotEqual(chat['uid'], self.dashboard['uid'])
        for panel in chat['panels']:
            for target in panel.get('targets', []):
                self.assertNotIn('flux2', target.get('expr', ''))

    def test_chat_dashboard_opens_on_the_4bit_profile(self):
        chat = json.loads((ROOT / 'dashboards/inference.json').read_text(encoding='utf-8'))
        variables = chat['templating']['list']
        self.assertEqual([v['name'] for v in variables], ['profile', 'pod'])
        profile = variables[0]
        self.assertEqual((profile['type'], profile['label'], profile['hide']), ('custom', 'Profile', 0))
        self.assertEqual(profile['query'], '4bit,bf16')
        self.assertEqual([o['value'] for o in profile['options']], ['4bit', 'bf16'])
        self.assertEqual(profile['current']['value'], '4bit')
        self.assertFalse(profile['multi'] or profile['includeAll'])

    def test_chat_pod_picker_lists_the_selected_profile_with_no_saved_pod(self):
        source = (ROOT / 'dashboards/inference.json').read_text(encoding='utf-8')
        pod = next(v for v in json.loads(source)['templating']['list'] if v['name'] == 'pod')
        query = 'label_values(up{job="vllm", profile="${profile}"}, instance)'
        self.assertEqual(pod['query']['query'], query)
        self.assertEqual(pod['definition'], query)
        self.assertFalse(pod['multi'] or pod['includeAll'])
        self.assertEqual((pod['current'], pod['options']), ({}, []))
        self.assertEqual(pod['refresh'], 2)  # list Pods again when the time range changes
        self.assertNotRegex(source, r'[a-z0-9]+-[0-9]+\.proxy\.runpod\.net')
        # Grafana reads the named groups as the shown text and the stored value.
        pattern = pod['regex'].strip('/').replace('(?<', '(?P<')
        match = re.search(pattern, 'fourbitpod-8889.proxy.runpod.net')
        self.assertEqual(match.groupdict(), {'text': 'fourbitpod', 'value': 'fourbitpod-8889.proxy.runpod.net'})

    def test_chat_panels_filter_every_metric_by_job_and_selected_pod(self):
        chat = json.loads((ROOT / 'dashboards/inference.json').read_text(encoding='utf-8'))
        selectors = re.compile(r'\b(?:up|gpu_[a-zA-Z0-9_:]+|vllm:[a-zA-Z0-9_:]+)(?:\{((?:"[^"]*"|[^{}])*)\})?')
        for panel in chat['panels']:
            found = [m.group(1) or '' for t in panel['targets'] for m in selectors.finditer(t['expr'])]
            self.assertTrue(found, panel['title'])
            for matchers in found:
                self.assertIn('job="vllm"', matchers, panel['title'])
                self.assertIn('instance="${pod}"', matchers, panel['title'])

    def test_promql_fixtures_cover_every_current_dashboard_query(self):
        fixture = json.loads((ROOT / 'scripts/flux2-queries.test.json').read_text())
        expected = [t['expr'].replace('${pod}', 'flux.example').replace('$__rate_interval', '5m')
                    for p in self.dashboard['panels'] for t in p['targets']]
        self.assertEqual([q['expr'] for q in fixture['tests'][0]['promql_expr_test']], expected)


FOUR_BIT = 'fourbitpod-8889.proxy.runpod.net'
BF16 = 'bfsixteenpod-8889.proxy.runpod.net'


class DeploymentCheckTests(unittest.TestCase):
    """Run the real deployment check against a stand-in for live Grafana."""

    def setUp(self):
        self.dashboard = json.loads((ROOT / 'dashboards/inference.json').read_text(encoding='utf-8'))
        self.targets = [('4bit', FOUR_BIT, 'up'), ('bf16', BF16, 'down')]

    def grafana(self, request, timeout):
        url = urlsplit(request.full_url)
        if url.path == '/api/search':
            raise HTTPError(request.full_url, 401, 'Unauthorized', {}, None)
        proxy = '/api/datasources/proxy/uid/prometheus/api/v1/'
        if url.path == proxy + 'query':
            # Prometheus keeps up=0 for a stopped Pod but has no GPU sample for it.
            keep_down = parse_qs(url.query)['query'] != ['gpu_exporter_up']
            body = {'data': {'result': [
                {'metric': {'instance': instance}, 'value': [0, '1' if health == 'up' else '0']}
                for _, instance, health in self.targets if keep_down or health == 'up'
            ]}}
        else:
            body = {
                '/api/health': {'database': 'ok'},
                '/api/dashboards/uid/inference-baseline': {'dashboard': self.dashboard, 'meta': {'provisioned': False}},
                '/api/datasources/uid/prometheus': {'url': 'http://prometheus.railway.internal:9090'},
                '/api/datasources/uid/prometheus/health': {'status': 'OK'},
                proxy + 'targets': {'data': {'activeTargets': [
                    {'labels': {'job': 'vllm', 'instance': instance, **({'profile': profile} if profile else {})},
                     'health': health}
                    for profile, instance, health in self.targets
                ] + [{'labels': {'job': 'flux2', 'instance': 'image'}, 'health': 'down'}]}},
            }[url.path]
        return io.BytesIO(json.dumps(body).encode())

    def check(self, *arguments):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / 'settings.env'
            settings.write_text('GRAFANA_PASSWORD=test-only')
            script = str(ROOT / 'scripts/check-deployment.py')
            with mock.patch.dict(os.environ, GRAFANA_SETTINGS_FILE=str(settings)), \
                    mock.patch.object(sys, 'argv', [script, *arguments]), \
                    mock.patch('urllib.request.urlopen', self.grafana), \
                    contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(script)

    def test_every_vllm_target_must_be_up_when_no_profile_is_named(self):
        with self.assertRaisesRegex(AssertionError, 'unhealthy'):
            self.check()
        self.targets = [('4bit', FOUR_BIT, 'up'), ('bf16', BF16, 'up')]
        self.check()

    def test_targets_without_a_profile_label_are_checked_when_none_is_named(self):
        self.targets = [(None, FOUR_BIT, 'up')]
        self.check()
        self.targets = [(None, FOUR_BIT, 'down')]
        with self.assertRaisesRegex(AssertionError, 'unhealthy'):
            self.check()

    def test_only_named_profiles_are_required(self):
        self.check('--profile', '4bit')
        with self.assertRaisesRegex(AssertionError, 'unhealthy'):
            self.check('--profile', 'bf16')
        with self.assertRaisesRegex(AssertionError, 'unhealthy'):
            self.check('--profile', '4bit', '--profile', 'bf16')

    def test_a_named_profile_without_a_target_fails(self):
        self.targets = [('4bit', FOUR_BIT, 'up')]
        with self.assertRaisesRegex(AssertionError, 'bf16'):
            self.check('--profile', '4bit', '--profile', 'bf16')

    def test_expected_instances_are_compared_with_the_required_targets(self):
        self.check('--profile', '4bit', '--expected-instance', FOUR_BIT)
        with self.assertRaisesRegex(AssertionError, 'Unexpected'):
            self.check('--profile', '4bit', '--expected-instance', BF16)
        self.targets = [('4bit', FOUR_BIT, 'up'), ('bf16', BF16, 'up')]
        self.check('--expected-instance', FOUR_BIT, '--expected-instance', BF16)
        with self.assertRaisesRegex(AssertionError, 'Unexpected'):
            self.check('--expected-instance', FOUR_BIT)

    def test_an_unfiltered_panel_still_fails(self):
        target = self.dashboard['panels'][0]['targets'][0]
        target['expr'] = target['expr'].replace('instance="${pod}"', 'instance=~".*"')
        with self.assertRaisesRegex(AssertionError, 'Unfiltered metric'):
            self.check('--profile', '4bit')


if __name__ == '__main__':
    unittest.main()
