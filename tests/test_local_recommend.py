import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import recommend


class LocalRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for context in (patch.dict(os.environ, {"HR_EVALS": "local-queue"}),
                        patch.object(recommend, "PROFILES", self.tmp.name),
                        patch.object(recommend.store, "harness", return_value={"commit": "new"}),
                        patch.object(recommend, "rank", return_value={})):
            context.start(); self.addCleanup(context.stop)

    def test_old_job_clone_is_not_profiled_as_a_newer_commit(self):
        with patch.object(recommend.store, "harness_profile", return_value={}), \
             patch.object(recommend.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "old\n")), \
             patch.object(recommend, "profile") as profile:
            recommend.refresh("fixture-agent", src="/old-job/repo")
            profile.assert_not_called()

    def test_parallel_completions_only_analyze_the_same_commit_once(self):
        profile_state = {}
        def analyze(*args, **kwargs):
            time.sleep(0.05)
            profile_state.update(commit="new", source="claude -p")
        barrier = threading.Barrier(2)
        def refresh(_):
            barrier.wait(timeout=5)
            return recommend.refresh("fixture-agent", src="/job/repo")
        with patch.object(recommend.store, "harness_profile", side_effect=lambda _: dict(profile_state)), \
             patch.object(recommend.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "new\n")), \
             patch.object(recommend, "profile", side_effect=analyze) as profile:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(refresh, range(2)))
            self.assertEqual(profile.call_count, 1)


if __name__ == "__main__": unittest.main()
