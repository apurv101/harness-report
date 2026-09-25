"""Durable, single-machine evaluation queue. SQLite transactions claim jobs atomically.

Only job metadata lives here. Logs/results remain in evals/ and runs/, and DynamoDB
remains the optional browsing index. No provider or GitHub tokens enter this queue.
"""
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import time


class Limit(Exception):
    pass


class Queue:
    def __init__(self, path=None):
        root = Path(os.environ.get("HR_DATA_DIR") or Path(__file__).resolve().parents[1])
        self.path = Path(path or root / "evals" / "queue.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL,
                created REAL NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0,
                data TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created)")

    @contextlib.contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            if write: db.execute("BEGIN IMMEDIATE")
            yield db
            if write: db.commit()
        except BaseException:
            if write: db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def record(row):
        if row is None: return None
        return {**json.loads(row["data"]), "status": row["status"], "cancelled": bool(row["cancelled"])}

    def enqueue(self, ev, daily_cap=0):
        owner = ev.get("user") or "local"
        with self.connect(write=True) as db:
            if daily_cap > 0:
                day = time.strftime("%Y%m%d", time.gmtime()) + "%"
                count = db.execute("SELECT count(*) FROM jobs WHERE owner=? AND id LIKE ? AND status!='cancelled'",
                                   (owner, day)).fetchone()[0]
                if count >= daily_cap: raise Limit(f"{owner} has reached the daily limit of {daily_cap} evaluations")
            db.execute("INSERT INTO jobs(id,owner,status,created,data) VALUES(?,?,?,?,?)",
                       (ev["id"], owner, "queued", time.time(), json.dumps(ev)))
        return self.get(ev["id"])

    def get(self, eid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (eid,)).fetchone()
            ev = self.record(row)
            if ev and ev["status"] == "queued":
                ev["queue_position"] = db.execute(
                    "SELECT count(*) FROM jobs WHERE status='queued' AND (created < ? OR (created=? AND id<=?))",
                    (row["created"], row["created"], eid)).fetchone()[0]
            return ev

    def active(self, owner=None):
        with self.connect() as db:
            sql = "SELECT * FROM jobs WHERE status IN ('queued','running')"
            args = ()
            if owner is not None: sql += " AND owner=?"; args = (owner,)
            return [self.record(r) for r in db.execute(sql + " ORDER BY created,id", args)]

    def recent(self, owner, limit=100):
        with self.connect() as db:
            return [self.record(r) for r in db.execute(
                "SELECT * FROM jobs WHERE owner=? ORDER BY created DESC,id DESC LIMIT ?", (owner, limit))]

    def claim(self, worker, per_user=1):
        """Oldest eligible job; a user's busy slot does not block other users."""
        with self.connect(write=True) as db:
            row = db.execute("""SELECT * FROM jobs AS candidate WHERE status='queued' AND cancelled=0
                AND (SELECT count(*) FROM jobs AS active
                     WHERE active.owner=candidate.owner AND active.status='running') < ?
                ORDER BY created,id LIMIT 1""", (per_user,)).fetchone()
            if row is None: return None
            ev = self.record(row)
            ev.update(status="running", worker=worker, execution_started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            db.execute("UPDATE jobs SET status='running', data=? WHERE id=?", (json.dumps(ev), ev["id"]))
            return ev

    def update(self, eid, **changes):
        """Merge against current state so worker writes cannot erase a cancellation."""
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (eid,)).fetchone()
            ev = self.record(row)
            if ev is None: return None
            ev.update(changes)
            ev["cancelled"] = bool(row["cancelled"])
            if ev["cancelled"] and ev.get("status") in ("done", "failed"):
                ev["status"] = "cancelled"
            db.execute("UPDATE jobs SET status=?,data=? WHERE id=?", (ev["status"], json.dumps(ev), eid))
        return self.get(eid)

    def cancel(self, eid):
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (eid,)).fetchone()
            ev = self.record(row)
            if ev is None: return None
            if ev["status"] not in ("queued", "running"): return ev
            ev["cancelled"] = True
            if ev["status"] == "queued":
                ev.update(status="cancelled", finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            db.execute("UPDATE jobs SET status=?,cancelled=1,data=? WHERE id=?", (ev["status"], json.dumps(ev), eid))
        return self.get(eid)
