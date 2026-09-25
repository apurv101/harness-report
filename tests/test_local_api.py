import concurrent.futures
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import evals
import serve


class LocalAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for obj, name, value in ((evals, "LOCAL_QUEUED", True), (evals, "LOCAL_USERS", True),
                                 (evals, "QUEUED", False), (evals, "DAILY_CAP", 0),
                                 (evals, "EVALS", str(Path(self.tmp.name) / "evals")),
                                 (evals, "RUNS", str(Path(self.tmp.name) / "runs"))):
            p = patch.object(obj, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(evals, "pick_task", return_value=evals.DEFAULT)
        p.start(); self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), serve.H)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True); thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, user="alice", body=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Cookie": f"hr_local_user={user}", "Content-Type": "application/json"})
        try: response = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e: response = e
        with response: return response.status, json.load(response)

    def test_parallel_submissions_same_repo_have_unique_ids_and_owners(self):
        def submit(user): return self.request("/api/evals", user, {"repo": "fixture/agent", "user": "someone-else"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, ["alice", "bob"] * 10))
        self.assertTrue(all(status == 201 for status, _ in results))
        self.assertEqual(len({r["eval"]["id"] for _, r in results}), 20)
        self.assertEqual(len(self.request("/api/evals", "alice")[1]["evals"]), 10)
        self.assertEqual(len(self.request("/api/evals", "bob")[1]["evals"]), 10)

    def test_another_user_cannot_follow_or_cancel_a_job(self):
        _, data = self.request("/api/evals", "alice", {"repo": "fixture/agent"})
        eid = data["eval"]["id"]
        for suffix in ("", "/console"):
            self.assertEqual(self.request(f"/api/evals/{eid}{suffix}", "bob")[0], 403)
        self.assertEqual(self.request(f"/api/evals/{eid}/cancel", "bob", {})[0], 403)
        self.assertEqual(self.request("/api/evals/current", "bob")[1], None)
        self.assertEqual(self.request(f"/api/evals/{eid}/cancel", "alice", {})[0], 200)
        self.assertEqual(evals.get(eid)["status"], "cancelled")

    def test_invalid_local_identity_is_not_authenticated(self):
        self.assertEqual(self.request("/api/evals", "mallory", {"repo": "fixture/agent"})[0], 401)


if __name__ == "__main__": unittest.main()
