import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import pages
import store


class HarnessProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            'repo': 'https://github.com/example/agent', 'commit': 'a' * 40,
            'use_case': 'Answers questions in a workspace.',
            'compatibility': {'status': 'blocked', 'summary': 'Needs a task adapter.',
                              'blockers': ['No task entrypoint.'],
                              'checks': [{'name': 'Build', 'status': 'passed', 'detail': 'Dry run completed.'}]},
        }
        for context in (patch.object(store, 'harness_runs', return_value=[]),
                        patch.object(store.ddb, 'query', return_value=[]),
                        patch.object(store.ddb, 'get', side_effect=lambda pk, sk: self.profile if sk == 'PROFILE' else None)):
            context.start(); self.addCleanup(context.stop)

    def test_reviewed_harness_is_listed_without_inventing_runs_or_recipes(self):
        with patch.object(store.ddb, 'batch_put', return_value=2) as publish:
            self.assertEqual(store.publish_harness('example-agent'), 2)
        card = publish.call_args.args[0][0]
        self.assertEqual(card['repo'], self.profile['repo'])
        self.assertEqual(card['commit'], self.profile['commit'])
        self.assertEqual(card['compatibility']['status'], 'blocked')
        self.assertEqual((card['runs'], card['recipes'], card['scored'], card['tasks_tried']), (0, 0, 0, 0))
        self.assertEqual(card['results'], {})

    def test_no_evidence_does_not_create_a_harness(self):
        self.profile.clear()
        with patch.object(store.ddb, 'batch_put') as publish:
            self.assertEqual(store.publish_harness('unknown'), 0)
            publish.assert_not_called()

    def test_a_newer_run_does_not_inherit_old_compatibility(self):
        run = {'run': 'r', 'started': '2026-09-27', 'finished': '2026-09-27',
               'harness': {'commit': 'b' * 40, 'repo': self.profile['repo']}}
        with patch.object(store, 'harness_runs', return_value=[run]):
            card = store.harness_card('example-agent')
        self.assertIsNone(card['compatibility'])
        self.assertEqual(card['commit'], 'b' * 40)
        self.assertEqual(card['runs'], 1)

    def test_saved_profile_can_restore_an_unrun_harness(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'PROFILES', folder):
            Path(folder, 'example-agent@' + self.profile['commit'] + '.json').write_text(json.dumps(self.profile))
            self.assertEqual(list(store.saved_profiles('example-agent')), [('example-agent', self.profile)])
            self.assertEqual(list(store.saved_profiles('unrelated')), [])

    def test_restore_preserves_the_evaluated_revision(self):
        run = {'harness': {'commit': 'b' * 40}, 'started': '2026-09-27', 'finished': '2026-09-27'}
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'PROFILES', folder), \
             patch.object(store, 'harness_runs', return_value=[run]):
            Path(folder, 'example-agent@' + self.profile['commit'] + '.json').write_text(json.dumps(self.profile))
            self.assertEqual(list(store.saved_profiles()), [])

    def test_markdown_exposes_compatibility_without_task_recommendations(self):
        card = store.harness_card('example-agent')
        markdown = pages.md_harness({'harness': card, 'profile': self.profile, 'runs': [],
                                     'recommendations': {'recs': [{'taskset': 'fixture', 'task': 'one'}]}})
        self.assertIn('Needs integration', markdown)
        self.assertIn('No task entrypoint.', markdown)
        self.assertIn('Dry run completed.', markdown)
        self.assertNotIn('Tests to run next', markdown)


if __name__ == '__main__': unittest.main()
