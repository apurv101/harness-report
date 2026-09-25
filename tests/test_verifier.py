import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import verifier


class VerifierTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'verifier').mkdir()
            (root / 'verifier' / 'stdout.log').write_text(text)
            return verifier.parse(directory, full=True)

    def test_complete_failure_includes_captured_output_and_last_block(self):
        result = self.parse('''test_solution.py::test_answer FAILED [100%]
================ FAILURES ================
________________ test_answer ________________
    assert answer == 42
E   AssertionError: got 41
---------------- Captured stdout call ----------------
input: 6 * 7
---------------- Captured stderr call ----------------
warning: wrong answer
''')
        detail = result['cases'][0]['detail']
        self.assertIn('AssertionError: got 41', detail)
        self.assertIn('input: 6 * 7', detail)
        self.assertIn('warning: wrong answer', detail)

    def test_classes_do_not_share_a_traceback(self):
        result = self.parse('''test_solution.py::TestA::test_answer FAILED
test_solution.py::TestB::test_answer FAILED
================ FAILURES ================
________________ TestA.test_answer ________________
E   AssertionError: A failed
________________ TestB.test_answer ________________
E   AssertionError: B failed
================ 2 failed in 0.01s ================
''')
        a, b = result['cases']
        self.assertIn('A failed', a['detail'])
        self.assertNotIn('B failed', a['detail'])
        self.assertIn('B failed', b['detail'])
        self.assertNotEqual(a['id'], b['id'])

    def test_setup_and_teardown_errors_are_both_retained(self):
        result = self.parse('''test_solution.py::test_answer ERROR
================ ERRORS ================
________________ ERROR at setup of test_answer ________________
E   RuntimeError: fixture failed
________________ ERROR at teardown of test_answer ________________
E   RuntimeError: cleanup failed
================ 2 errors in 0.01s ================
''')
        self.assertEqual(result['failed'], 1)
        self.assertIn('fixture failed', result['cases'][0]['detail'])
        self.assertIn('cleanup failed', result['cases'][0]['detail'])

    def test_parameter_ids_keep_spaces_and_dots(self):
        result = self.parse('''test_solution.py::test_answer[hello world.txt] FAILED
================ FAILURES ================
________________ test_answer[hello world.txt] ________________
E   AssertionError: parameter failed
================ 1 failed in 0.01s ================
''')
        self.assertEqual(result['total'], 1)
        self.assertIn('parameter failed', result['cases'][0]['detail'])

    def test_ambiguous_failure_is_not_assigned_to_wrong_file(self):
        result = self.parse('''a/test_a.py::test_answer FAILED
b/test_b.py::test_answer FAILED
================ FAILURES ================
________________ test_answer ________________
E   AssertionError: unknown origin
''')
        self.assertTrue(all(case['detail'] is None for case in result['cases']))

    def test_traceback_file_disambiguates_same_named_tests(self):
        result = self.parse('''a/test_a.py::test_answer FAILED
b/test_b.py::test_answer FAILED
================ FAILURES ================
________________ test_answer ________________
b/test_b.py:10: AssertionError
E   AssertionError: B failed
''')
        self.assertIsNone(result['cases'][0]['detail'])
        self.assertIn('B failed', result['cases'][1]['detail'])

    def test_passing_output_is_shown_when_verifier_records_it(self):
        result = self.parse('''test_solution.py::test_answer PASSED
================ PASSES ================
________________ test_answer ________________
---------------- Captured stdout call ----------------
answer: 42
================ 1 passed in 0.01s ================
''')
        self.assertIn('answer: 42', result['cases'][0]['detail'])

    def test_collection_error_and_partial_interruption_are_distinct(self):
        collection = self.parse('''================ ERRORS ================
________________ ERROR collecting test_solution.py ________________
E   ImportError: missing dependency
!!!!!!!! Interrupted: 1 error during collection !!!!!!!!
''')
        self.assertEqual(collection['total'], 0)
        self.assertIn('test_solution.py', collection['aborted'])
        partial = self.parse('''test_solution.py::test_first PASSED
!!!!!!!! Interrupted: KeyboardInterrupt !!!!!!!!
''')
        self.assertEqual(partial['total'], 1)
        self.assertEqual(partial['aborted'], 'KeyboardInterrupt')

    def test_parameterized_source_and_agent_written_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / 'tasks' / 'example' / 'tests'
            task.mkdir(parents=True)
            (task / 'test_solution.py').write_text('def test_answer(value):\n    assert value == 42\n')
            (root / 'run.json').write_text(json.dumps({'task': {'taskset_dir': str(root / 'tasks'), 'name': 'example'}}))
            (root / 'verifier').mkdir()
            (root / 'verifier' / 'stdout.log').write_text(
                '\x1b[32mtest_solution.py::test_answer[42] PASSED\x1b[0m\n'
                'test_agent.py::test_own PASSED\n')
            result = verifier.parse(directory, full=True)
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['agent_written'], 1)
            self.assertIn('assert value == 42', result['cases'][0]['source'])
            self.assertFalse(result['cases'][1]['own'])

    def test_non_pytest_output_is_not_invented_as_test_cases(self):
        self.assertIsNone(self.parse('Custom benchmark score: 0.75\n'))


    def test_short_summary_lines_count_when_pytest_ran_without_v(self):
        # AlgoTune's test.sh: dots, not -v lines, and a -rA short summary
        result = self.parse('''collected 3 items

../tests/test_outputs.py .FF
=========================== short test summary info ============================
PASSED ../tests/test_outputs.py::test_solver_exists
FAILED ../tests/test_outputs.py::test_solver_validity - Failed: Solver produced invalid solutions on the test set.
FAILED ../tests/test_outputs.py::test_solver_speedup - AssertionError: Solver was not faster than baseline
========================= 2 failed, 1 passed in 0.32s ==========================
''')
        self.assertEqual((result['passed'], result['failed'], result['total']), (1, 2, 3))
        self.assertEqual(result['failed_names'], ['test_solver_speedup', 'test_solver_validity'])
        self.assertEqual(result['summary'], '2 failed, 1 passed')

    def test_v_line_and_short_summary_are_one_test(self):
        result = self.parse('''../tests/test_outputs.py::test_fix PASSED [100%]
=========================== short test summary info ============================
PASSED ../tests/test_outputs.py::test_fix
============================== 1 passed in 0.08s ===============================
''')
        self.assertEqual(result['total'], 1)


if __name__ == '__main__':
    unittest.main()
