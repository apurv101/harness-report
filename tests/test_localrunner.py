from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evals
from localrunner import Runner


class LocalRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(evals, "EVALS", str(Path(self.tmp.name) / "evals"))
        p.start(); self.addCleanup(p.stop)

    def test_second_pool_cannot_exceed_configured_capacity(self):
        first, second = Runner(), Runner(workers=10)
        first.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "already owns"): second.acquire()
        finally: first.lock.close()
        second.acquire(); second.lock.close()

    def test_recovery_fails_interrupted_attempt_and_keeps_waiting_job(self):
        runner = Runner()
        for n in (1, 2):
            runner.queue.enqueue({"id": str(n), "user": "alice", "status": "queued", "pid": None})
        runner.queue.claim("old-worker")
        with patch("localrunner.cleanup") as cleanup, patch.object(evals, "_save"):
            runner.recover()
            cleanup.assert_called_once_with("1")
        self.assertEqual(runner.queue.get("1")["status"], "failed")
        self.assertEqual(runner.queue.get("2")["status"], "queued")


if __name__ == "__main__": unittest.main()
