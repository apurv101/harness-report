import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import validate_corpus as validation


class ValidationAdmissionTests(unittest.TestCase):
    def test_only_numeric_reference_success_is_accepted(self):
        self.assertTrue(validation.reference_passed({'reward': 1, 'solution_rc': 0, 'verifier_rc': 0}))
        for value in (True, '1', None, .9, 0):
            self.assertFalse(validation.reference_passed({'reward': value}))

    def test_a_reward_does_not_hide_a_broken_reference_or_backend(self):
        for key, value in [('solution_rc', 1), ('verifier_rc', 1), ('rc', 124), ('backend_rc', 1), ('error', {'message': 'failure'})]:
            self.assertFalse(validation.reference_passed({'reward': 1, key: value}))

    def test_expected_negative_grader_exit_is_allowed_but_infrastructure_errors_are_not(self):
        self.assertTrue(validation.empty_passed({'reward': 0, 'verifier_rc': 1}))
        self.assertFalse(validation.empty_passed({'reward': 0, 'backend_rc': 1}))
        self.assertFalse(validation.empty_passed({'reward': 0, 'error': 'missing container'}))
        self.assertFalse(validation.empty_passed({'reward': False}))

    def test_publication_cannot_target_aws(self):
        with patch('ddb.local', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'local catalog only'):
                validation.publish([{'status': 'passed', 'reference': {'reward': 1}, 'empty': {'reward': 0}}])

    def test_publication_requires_both_controls(self):
        with self.assertRaisesRegex(ValueError, 'evidence'):
            validation.publish([{'status': 'passed', 'reference': {'reward': 1}}])

    def test_missing_reward_and_boolean_reward_are_not_numeric_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(validation.read_reward(root))
            (root / 'reward.json').write_text('{"reward":true}')
            self.assertIsNone(validation.read_reward(root))

    def test_summary_counts_only_requested_tasks(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(validation, 'WORK', Path(folder)), patch.object(validation, 'REPO', Path(folder)):
            report = validation.summary([{'taskset': 'ds1000', 'task': 'x'}],
                {('ds1000', 'x'): {'taskset': 'ds1000', 'status': 'passed'},
                 ('kumo', 'y'): {'taskset': 'kumo', 'status': 'passed'}}, 'running')
            self.assertEqual(report['completed'], 1)
            self.assertEqual(report['by_taskset']['kumo']['pending'], 0)
            self.assertEqual(report['by_taskset']['ds1000']['pending'], 0)

    def test_gpu_and_missing_reference_have_explicit_blockers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIn('reference', validation.preflight(root, {}, 8000))
            (root/'solution').mkdir(); (root/'solution/solve.sh').touch()
            (root/'tests').mkdir(); (root/'tests/test.sh').touch()
            self.assertIn('GPU', validation.preflight(root, {'environment': {'gpus': 1}}, 8000))
