import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve
import store


class Request(serve.H):
    def __init__(self, path):
        self.rfile = io.BytesIO(f'GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n'.encode())
        self.wfile = io.BytesIO()
        self.client_address = ('127.0.0.1', 0)
        self.connection = self.request = self.server = None
        self.handle_one_request()

    def log_message(self, *args): pass


class RunLogTests(unittest.TestCase):
    def test_raw_log_prefers_original_archive_to_shortened_preview(self):
        with patch.object(serve, 'find_run', return_value=None), \
             patch.object(store, 'archived_file_url', return_value='https://archive.example/full-log') as archive, \
             patch.object(store, 'file_text') as preview:
            response = Request('/raw/run-1/verifier/stdout.log').wfile.getvalue()
        self.assertIn(b'302', response.splitlines()[0])
        self.assertIn(b'Location: https://archive.example/full-log', response)
        archive.assert_called_once_with('run-1', 'verifier/stdout.log')
        preview.assert_not_called()

    def test_old_table_only_runs_still_open(self):
        with patch.object(serve, 'find_run', return_value=None), \
             patch.object(store, 'archived_file_url', return_value=None), \
             patch.object(serve, 'from_table', return_value='stored output'):
            response = Request('/raw/run-1/verifier/stdout.log').wfile.getvalue()
        self.assertIn(b'200', response.splitlines()[0])
        self.assertTrue(response.endswith(b'stored output'))

    def test_archive_errors_are_visible_instead_of_silently_returning_preview(self):
        with patch.object(serve, 'find_run', return_value=None), \
             patch.object(store, 'archived_file_url', side_effect=RuntimeError('unavailable')):
            response = Request('/raw/run-1/verifier/stdout.log').wfile.getvalue()
        self.assertIn(b'503', response.splitlines()[0])

    def test_encoded_traversal_never_reaches_archive(self):
        with patch.object(store, 'archived_file_url') as archive:
            for path in ('/raw/run-1/%2e%2e/secret', '/raw/run-1%2Fother/stdout.log', '/raw/run-1/a%5Cb'):
                with self.subTest(path=path):
                    response = Request(path).wfile.getvalue()
                    self.assertIn(b'400', response.splitlines()[0])
            archive.assert_not_called()

    def test_local_api_returns_test_cases_and_uncut_log(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(serve, 'RUNS', directory), \
             patch.object(serve, 'STORE', 'files'):
            root = Path(directory) / 'run-1'
            (root / 'verifier').mkdir(parents=True)
            (root / 'run.json').write_text(json.dumps({'kind': 'harbor', 'finished': '2026-09-25T00:00:00Z'}))
            log = 'test_sample.py::test_answer FAILED\n==== FAILURES ====\n____ test_answer ____\nE   AssertionError: answer was 41\n'
            (root / 'verifier' / 'stdout.log').write_text(log)
            response = Request('/api/run/run-1').wfile.getvalue()
            bundle = json.loads(response.split(b'\r\n\r\n', 1)[1])
            self.assertIn('answer was 41', bundle['verifier']['tests']['cases'][0]['detail'])
            response = Request('/raw/run-1/verifier/stdout.log').wfile.getvalue()
            self.assertEqual(response.split(b'\r\n\r\n', 1)[1].decode(), log)

    def test_archive_signs_only_requested_run_file_with_short_expiry(self):
        class ClientError(Exception):
            def __init__(self, code): self.response = {'Error': {'Code': code}}

        client = Mock()
        client.generate_presigned_url.return_value = 'https://archive.example/full-log'
        modules = {'boto3': SimpleNamespace(client=lambda service: client),
                   'botocore.exceptions': SimpleNamespace(ClientError=ClientError)}
        with patch.dict(sys.modules, modules), patch.dict(store.os.environ, {'HR_RUNS_BUCKET': 'test-archive'}):
            self.assertEqual(store.archived_file_url('run-1', 'verifier/stdout.log'), 'https://archive.example/full-log')
            client.head_object.assert_called_once_with(Bucket='test-archive', Key='runs/run-1/verifier/stdout.log')
            client.generate_presigned_url.assert_called_once_with('get_object', Params={
                'Bucket': 'test-archive', 'Key': 'runs/run-1/verifier/stdout.log',
                'ResponseContentType': 'text/plain; charset=utf-8',
            }, ExpiresIn=300)
            client.head_object.side_effect = ClientError('404')
            self.assertIsNone(store.archived_file_url('run-1', 'verifier/stdout.log'))
            client.head_object.side_effect = ClientError('AccessDenied')
            with self.assertRaises(ClientError): store.archived_file_url('run-1', 'verifier/stdout.log')


if __name__ == '__main__':
    unittest.main()
