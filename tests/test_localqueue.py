import concurrent.futures
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from localqueue import Limit, Queue


class LocalQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = Queue(Path(self.tmp.name) / "queue.sqlite3")

    def job(self, n, user="alice"):
        import time
        return {"id": time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"-fixture-{n:012x}",
                "user": user, "repo": "fixture/agent", "status": "queued", "cancelled": False}

    def test_concurrent_workers_claim_each_job_once(self):
        for i in range(40): self.queue.enqueue(self.job(i))
        def claim(i):
            q = Queue(self.queue.path)
            return q.claim(str(i), per_user=100)
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            claimed = list(pool.map(claim, range(60)))
        ids = [j["id"] for j in claimed if j]
        self.assertEqual(len(ids), 40)
        self.assertEqual(len(set(ids)), 40)

    def test_busy_user_does_not_block_other_users(self):
        for n, user in enumerate(("alice", "alice", "bob", "charlie")):
            self.queue.enqueue(self.job(n, user))
        first = self.queue.claim("one")
        self.assertEqual(first["user"], "alice")
        self.assertEqual(self.queue.claim("two")["user"], "bob")
        self.assertEqual(self.queue.claim("three")["user"], "charlie")
        self.assertIsNone(self.queue.claim("four"))
        self.queue.update(first["id"], status="done")
        self.assertEqual(self.queue.claim("four")["user"], "alice")

    def test_daily_cap_is_atomic_during_simultaneous_submission(self):
        def submit(i):
            try: self.queue.enqueue(self.job(i), daily_cap=5); return True
            except Limit: return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(submit, range(30))), 5)

    def test_cancelled_waiting_job_is_never_claimed(self):
        ev = self.queue.enqueue(self.job(1))
        self.assertEqual(self.queue.cancel(ev["id"])["status"], "cancelled")
        self.assertIsNone(self.queue.claim("one"))

    def test_worker_updates_cannot_erase_cancellation(self):
        ev = self.queue.enqueue(self.job(1))
        self.queue.claim("one")
        self.queue.cancel(ev["id"])
        state = self.queue.update(ev["id"], status="done", cancelled=False)
        self.assertTrue(state["cancelled"])
        self.assertEqual(state["status"], "cancelled")

    def test_queue_survives_reopening_and_lists_only_owner(self):
        a = self.queue.enqueue(self.job(1, "alice"))
        self.queue.enqueue(self.job(2, "bob"))
        reopened = Queue(self.queue.path)
        self.assertEqual(reopened.recent("alice")[0]["id"], a["id"])
        self.assertEqual(len(reopened.recent("alice")), 1)
        self.assertEqual(reopened.get(a["id"])["queue_position"], 1)


if __name__ == "__main__": unittest.main()
