"""A reward is shown as its verifier wrote it, never turned into pass/fail, and a run too big for one Lambda
response still answers."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve
import store


def card(reward, started, **extra):
    return {"run": f"r{started}", "started": started, "finished": started, "status": "done", "reward": reward, **extra}


class ScoringTests(unittest.TestCase):
    def test_a_reward_is_scored_not_passed(self):
        self.assertEqual(store._outcome(card(1, "1")), "scored")
        self.assertEqual(store._outcome(card(0, "1")), "scored")
        self.assertEqual(store._outcome(card(None, "1")), "error")
        self.assertEqual(store._outcome({"status": "running"}), "running")

    def test_verifier_says_what_it_reported(self):
        c = card(1.0, "1", verifier_rc=1, tests={"passed": 1, "failed": 2, "total": 3, "summary": "2 failed, 1 passed"})
        self.assertEqual(store.verifier_says(c), "reward 1.0 · 2 failed, 1 passed · verifier exited 1")
        self.assertEqual(store.verifier_says(card(None, "1")), "no reward written")

    def test_results_keep_latest_and_best_reward_per_task(self):
        res = store.results_of([card(0.5, "1"), card(2.5, "2"), card(1.0, "3"), card(None, "4")], lambda c: "t")
        self.assertEqual(res["t"]["runs"], 4)
        self.assertEqual(res["t"]["scored"], 3)
        self.assertEqual(res["t"]["best_reward"], 2.5)
        self.assertIsNone(res["t"]["last_reward"])
        self.assertNotIn("passes", res["t"])


class FitBundleTests(unittest.TestCase):
    def bundle(self, n=30):
        history = [{"role": "user", "content": "x" * 5000}]
        calls = []
        for i in range(n):
            history = history + [{"role": "assistant", "content": f"step {i} " + "y" * 5000}]
            calls.append({"n": i + 1, "request": {"model": "m", "messages": list(history)}, "response": {"id": i}})
        return {"run": "r", "calls": calls}

    def test_small_bundles_are_untouched(self):
        b = self.bundle(2)
        self.assertIs(serve.fit_bundle(b, 10_000_000), b)
        self.assertIs(serve.fit_bundle(b, 0), b)

    def test_big_bundles_fit_and_keep_the_last_call_whole(self):
        b = self.bundle()
        out = serve.fit_bundle(b, 500_000)
        self.assertLessEqual(len(json.dumps(out)), 500_000)
        self.assertEqual(out["calls"][-1], b["calls"][-1])
        first = out["calls"][0]
        self.assertEqual(first["request"], {"model": "m"})
        self.assertEqual(first["request_trimmed"]["fields"], ["messages"])
        self.assertEqual(first["request_trimmed"]["messages"], 2)
        self.assertEqual(out["calls_trimmed"], len(b["calls"]) - 1)
        self.assertIn("messages", b["calls"][0]["request"])     # the caller's bundle is not changed


if __name__ == "__main__":
    unittest.main()
