import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import cooperbench
from task_mcp import Client
from unittest.mock import patch
from io import BytesIO


class CooperBenchTests(unittest.TestCase):
    def test_selected_harness_runs_in_both_isolated_workers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ('agent1', 'agent2'):
                folder = root / 'task/environment' / name
                folder.mkdir(parents=True)
                (folder / 'instruction.md').write_text('Feature for ' + name)
            wrapper = root / 'selected.sh'; wrapper.write_text('echo selected-harness')
            config = {'services': {'main': {}, 'redis': {}}}
            for name in ('agent1', 'agent2'):
                config['services'][name] = {'build': {'context': name}, 'environment': {'AGENT_TIMEOUT': '20'},
                    'volumes': [{'type': 'volume', 'source': name + '_out', 'target': '/agent_output'}]}
            original = copy.deepcopy(config)
            work = root / 'work'; work.mkdir()
            result = cooperbench.configure(config, task=root / 'task', work=work, out=root / 'out',
                image='selected-overlay', wrapper=wrapper,
                env={'OPENAI_BASE_URL': 'http://recorder:4000/v1'}, oracle=False)
            self.assertTrue(result.is_file())
            self.assertEqual(config['services']['main'], original['services']['main'])
            for name in ('agent1', 'agent2'):
                worker = config['services'][name]
                self.assertEqual(worker['image'], 'selected-overlay')
                self.assertNotIn('build', worker)
                self.assertEqual(worker['environment']['OPENAI_BASE_URL'], 'http://recorder:4000/v1')
                self.assertEqual(worker['environment']['BASH_ENV'], '')
                self.assertEqual(worker['volumes'][0], original['services'][name]['volumes'][0])
                assets = work / 'cooperbench' / name
                self.assertEqual((assets / 'run-harness').read_text(), wrapper.read_text())
                self.assertIn('Feature for ' + name, (assets / 'instruction.md').read_text())
                self.assertNotIn('Feature for ' + ('agent2' if name == 'agent1' else 'agent1'), (assets / 'instruction.md').read_text())

    def test_reference_trial_does_not_launch_background_harnesses(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = {'services': {'main': {}, 'redis': {}}}
            for name in ('agent1', 'agent2'):
                config['services'][name] = {'build': '.', 'environment': {}, 'volumes': [{'target': '/agent_output'}]}
            cooperbench.configure(config, task=root, work=root, out=root, image='reference', wrapper=None, env={}, oracle=True)
            for name in ('agent1', 'agent2'):
                self.assertEqual(config['services'][name]['entrypoint'], ['sleep', 'infinity'])


class Response(BytesIO):
    def __init__(self, body, headers):
        super().__init__(body)
        self.headers = headers


class MCPTests(unittest.TestCase):
    def test_initialization_session_and_sse_tool_response(self):
        responses = [
            Response(b'{"result":{"protocolVersion":"2025-03-26"}}', {'Mcp-Session-Id': 'session'}),
            Response(b'', {}),
            Response(b'event: message\ndata: {"jsonrpc":"2.0","id":3,"result":{"tools":[{"name":"get_status"}]}}\n\n',
                     {'Content-Type': 'text/event-stream'})]
        with patch('urllib.request.urlopen', side_effect=responses) as send:
            client = Client('http://task:8000/mcp'); client.initialize()
            result = client.request('tools/list', {})
            self.assertEqual(result['tools'][0]['name'], 'get_status')
            request = send.call_args.args[0]
            self.assertEqual(request.get_header('Mcp-session-id'), 'session')
            self.assertEqual(request.get_header('Mcp-protocol-version'), '2025-03-26')
            self.assertEqual(json.loads(request.data)['method'], 'tools/list')

    def test_protocol_error_is_not_reported_as_tool_success(self):
        response = Response(b'{"error":{"code":-32601,"message":"No such tool"}}', {})
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'No such tool'):
                Client('http://task/mcp').request('tools/call', {})
