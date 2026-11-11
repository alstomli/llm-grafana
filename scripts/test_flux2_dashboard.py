"""Validate image query isolation and the existing chat-dashboard contract."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

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

    def test_promql_fixtures_cover_every_current_dashboard_query(self):
        fixture = json.loads((ROOT / 'scripts/flux2-queries.test.json').read_text())
        expected = [t['expr'].replace('${pod}', 'flux.example').replace('$__rate_interval', '5m')
                    for p in self.dashboard['panels'] for t in p['targets']]
        self.assertEqual([q['expr'] for q in fixture['tests'][0]['promql_expr_test']], expected)


if __name__ == '__main__':
    unittest.main()
