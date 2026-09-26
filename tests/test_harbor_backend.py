import copy
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import harbor_backend as hb


class HarborBackendTests(unittest.TestCase):
    def setUp(self):
        self.config = {"services": {
            "main": {"image": "original", "build": {"context": "/source"}, "environment": {},
                     "depends_on": {"db": {"condition": "service_healthy"}}, "networks": {"tasknet": None}},
            "db": {"image": "db-image", "container_name": "shared-db", "environment": {
                "OPENAI_API_KEY": "worker-secret", "OPENAI_BASE_URL": "https://provider"},
                "healthcheck": {"test": ["CMD", "true"]}, "networks": {"tasknet": {"aliases": ["database"]}}}},
            "networks": {"tasknet": {"name": "shared-net"}}, "volumes": {"data": {"name": "shared-data"}}}

    def runtime(self, **kwargs):
        return hb.runtime_compose(self.config, image="overlay", project="hr-hb-test", evaluation="eval-1",
            network="run-internal", proxy="http://recorder:4000", egress=kwargs.get("egress", "record"), out=Path("/out"))

    def test_preserves_dependencies_and_isolates_task_resources(self):
        before = copy.deepcopy(self.config)
        config, bypass = self.runtime()
        self.assertEqual(self.config, before)
        self.assertEqual(config['services']['main']['depends_on'], before['services']['main']['depends_on'])
        self.assertNotIn('build', config['services']['main'])
        self.assertEqual(config['services']['main']['image'], 'overlay')
        self.assertNotIn('name', config['networks']['tasknet'])
        self.assertTrue(config['networks']['tasknet']['internal'])
        self.assertNotIn('name', config['volumes']['data'])
        self.assertNotIn('container_name', config['services']['db'])
        self.assertEqual(config['services']['db']['networks']['hr_gateway']['aliases'], ['shared-db'])
        self.assertEqual(config['volumes']['data']['labels']['hr.evaluation'], 'eval-1')
        self.assertIn('database', bypass.split(','))
        self.assertIn('shared-db', bypass.split(','))

    def test_sidecar_model_traffic_uses_proxy_and_main_verifier_does_not_inherit_agent_proxy(self):
        config, _ = self.runtime()
        db = config['services']['db']['environment']
        self.assertEqual(db['OPENAI_API_KEY'], 'proxy')
        self.assertEqual(db['OPENAI_BASE_URL'], 'http://recorder:4000/v1')
        self.assertEqual(db['HTTP_PROXY'], 'http://recorder:3128')
        self.assertNotIn('HTTP_PROXY', config['services']['main']['environment'])

    def test_sidecar_key_without_endpoint_still_routes_to_recorder(self):
        values = self.config['services']['db']['environment']
        values.pop('OPENAI_BASE_URL')
        values['ANTHROPIC_API_KEY'] = 'worker-secret'
        config, _ = self.runtime()
        env = config['services']['db']['environment']
        self.assertEqual(env['OPENAI_BASE_URL'], 'http://recorder:4000/v1')
        self.assertEqual(env['OPENAI_API_BASE'], 'http://recorder:4000/v1')
        self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://recorder:4000')

    def test_external_state_and_host_network_are_not_silently_shared(self):
        self.config['volumes']['data']['external'] = True
        with self.assertRaisesRegex(ValueError, 'External volumes'): self.runtime()
        self.config['volumes']['data'].pop('external')
        self.config['services']['db']['network_mode'] = 'host'
        with self.assertRaisesRegex(ValueError, 'network_mode'): self.runtime()

    def test_json_rewards_are_not_arbitrarily_aggregated(self):
        self.assertEqual(hb.scalar_reward({'reward': .25, 'accuracy': .5}), .25)
        self.assertIsNone(hb.scalar_reward({'latency': 10, 'accuracy': .5}))
        self.assertIsNone(hb.scalar_reward(None))

    def test_wrong_runtime_version_fails_before_execution(self):
        with patch.object(importlib.metadata, 'version', return_value='0.99.0'):
            with self.assertRaisesRegex(RuntimeError, '0.23.0 is required'): hb.check_version()

    def test_empty_metadata_does_not_shift_resource_or_timeout_fields(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, 'task.toml').write_text('[agent]\ntimeout_sec=60\n[verifier]\ntimeout_sec=30\n[environment]\ncpus=1\nmemory_mb=256\n')
            result = subprocess.run(['bash','-c', 'IFS="|" read -r a b agent verifier cpus mem image compose < <(python3 "$1/lib/task.py" "$2"); printf "%s|%s|%s|%s" "$agent" "$verifier" "$cpus" "$mem"',
                                     'test',str(ROOT),td], text=True,capture_output=True,check=True)
            self.assertEqual(result.stdout,'60|30|1|256m')

    def test_worker_release_includes_dependency_pin(self):
        self.assertIn('requirements-harbor.txt', (ROOT/'infra/runner-assets.tf').read_text())
        self.assertIn('harbor=='+hb.HARBOR_VERSION, (ROOT/'requirements-harbor.txt').read_text())
        self.assertIn('harbor=='+hb.HARBOR_VERSION, (ROOT/'infra/runner-install.sh').read_text())


if __name__ == '__main__': unittest.main()
