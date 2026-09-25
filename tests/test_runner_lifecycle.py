import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class ClientError(Exception):
    def __init__(self, code, message=""):
        self.response = {"Error": {"Code": code}}
        super().__init__(message)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "infra/runner-lifecycle.py"
        spec = importlib.util.spec_from_file_location("hr_lifecycle_test", path)
        self.module = importlib.util.module_from_spec(spec)
        sdk = SimpleNamespace(client=Mock())
        with patch.dict(sys.modules, {"boto3": sdk, "botocore.exceptions": SimpleNamespace(ClientError=ClientError)}):
            spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module.READY = Path(self.tmp.name) / "ready"
        self.sdk = sdk
        self.asg = Mock()
        self.ssm = Mock()
        self.ssm.get_parameter.side_effect = ClientError("ParameterNotFound")
        sdk.client.side_effect = lambda service: self.asg if service == "autoscaling" else self.ssm

    def states(self, *states):
        self.asg.describe_auto_scaling_instances.side_effect = [
            {"AutoScalingInstances": [{"AutoScalingGroupName": "test", "LifecycleState": s}]} for s in states]

    def test_warmup_completes_hook_without_consuming_work(self):
        self.states("Warmed:Pending:Wait", "Warmed:Pending:Proceed")
        with patch.object(self.module, "instance_id", return_value="i-test"), \
                patch.dict(self.module.os.environ, {"HR_ASG_NAME": "test"}), \
                patch.object(self.module.time, "sleep", side_effect=[None, SystemExit("OS stopped warm instance")]):
            with self.assertRaises(SystemExit): self.module.ready()
        self.asg.complete_lifecycle_action.assert_called_once()
        self.assertFalse(self.module.READY.exists())
        self.module.retire()
        self.ssm.invoke.assert_not_called()

    def test_resumed_worker_waits_for_inservice_before_execution(self):
        self.states("Pending:Wait", "Pending:Proceed", "InService")
        with patch.object(self.module, "instance_id", return_value="i-test"), \
                patch.dict(self.module.os.environ, {"HR_ASG_NAME": "test", "HR_SECRET_PREFIX": "/test/"}), \
                patch.object(self.module.time, "sleep"), patch.object(self.module.subprocess, "run") as run:
            self.module.ready()
        self.assertEqual(self.module.READY.read_text(), "i-test")
        run.assert_called_once()
        self.ssm.get_parameter.assert_called_once()

    def test_stale_lifecycle_response_is_harmless(self):
        self.states("Pending:Wait", "Pending:Wait", "InService")
        self.asg.complete_lifecycle_action.side_effect = [None, ClientError("ValidationError", "No active Lifecycle Action")]
        with patch.object(self.module, "instance_id", return_value="i-test"), \
                patch.dict(self.module.os.environ, {"HR_ASG_NAME": "test", "HR_SECRET_PREFIX": "/test/"}), \
                patch.object(self.module.time, "sleep"), patch.object(self.module.subprocess, "run"):
            self.module.ready()
        self.assertTrue(self.module.READY.exists())

    def test_retirement_calls_controller_instead_of_blind_replacement(self):
        self.module.READY.write_text("i-test")
        self.ssm.invoke.return_value = {"StatusCode": 200}
        with patch.dict(self.module.os.environ, {"HR_SCALER_FUNCTION": "capacity"}):
            self.module.retire()
        call = self.ssm.invoke.call_args.kwargs
        self.assertEqual(call["InvocationType"], "RequestResponse")
        self.assertEqual(call["Payload"], b'{"retire": "i-test"}')

    def test_service_path_includes_linux_administration_tools(self):
        script = Path(__file__).resolve().parents[1] / "infra/runner-init.sh"
        path = next(line.removeprefix("PATH=") for line in script.read_text().splitlines() if line.startswith("PATH="))
        self.assertIn("/usr/sbin", path.split(":"))

    def test_retirement_preserves_diagnostics_even_without_a_claimed_job(self):
        self.module.READY.write_text("i-test")
        self.ssm.invoke.return_value = {"StatusCode": 200}
        with patch.dict(self.module.os.environ, {"HR_SCALER_FUNCTION": "capacity", "HR_RUNS_BUCKET": "results"}), \
                patch.object(self.module.subprocess, "run", return_value=SimpleNamespace(stdout=b"startup failed")):
            self.module.retire()
        self.ssm.put_object.assert_called_once_with(Bucket="results", Key="workers/i-test/service.log",
                                                   Body=b"startup failed", ContentType="text/plain")


if __name__ == "__main__": unittest.main()
