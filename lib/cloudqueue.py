"""Authoritative cloud job state. SQS FIFO orders each user's jobs; DynamoDB fences workers.

JOB rows are separate from the derived EVAL/report rows so publishing logs cannot
overwrite cancellation or let an expired worker finish a newer state transition.
"""
import hashlib
import os
import time
import uuid

import ddb


class Limit(Exception): pass
class LostLease(Exception): pass


def owner_key(user):
    return "JOBS#" + hashlib.sha256(user.lower().encode()).hexdigest()


def clean(row):
    return {k: v for k, v in row.items() if k not in ("pk", "sk")} if row else None


def get(eid): return clean(ddb.get("JOB#" + eid, "META"))


def recent(user, limit=100):
    return [clean(r) for r in ddb.query(owner_key(user), "EVAL#", desc=True, limit=limit)]


def active():
    """Strongly consistent, paginated scheduling index; never scan historical reports."""
    return [clean(r) for r in ddb.query("JOBS#ACTIVE", consistent=True)]


def wake():
    """Wake capacity immediately. A scheduled reconciler repairs a failed notification."""
    function = os.environ.get("HR_SCALER_FUNCTION")
    if not function: return
    try:
        import boto3
        boto3.client("lambda").invoke(FunctionName=function, InvocationType="Event", Payload=b"{}")
    except Exception as e:
        print(f"worker wake-up failed; scheduled reconciliation will retry: {e}", flush=True)


def _active_write(ev):
    key = {"pk": "JOBS#ACTIVE", "sk": ev["id"]}
    if ev["status"] in ("queued", "running"):
        return _put({**key, **{k: ev[k] for k in ("id", "user", "status", "lease_until") if k in ev}})
    return {"Delete": {"TableName": ddb.table(), "Key": ddb.row_of(key)}}


def _put(row, condition=None, values=None):
    request = {"TableName": ddb.table(), "Item": ddb.row_of(row)}
    if condition: request["ConditionExpression"] = condition
    if values: request["ExpressionAttributeValues"] = ddb.row_of(values)
    return {"Put": request}


def _rows(ev):
    return [{**ev, "pk": "JOB#" + ev["id"], "sk": "META"},
            {**ev, "pk": owner_key(ev["user"]), "sk": "EVAL#" + ev["id"]}]


def enqueue(ev, daily_cap=5):
    ev = {**ev, "revision": 1, "cap_counted": daily_cap > 0}
    operations = [_put(row, "attribute_not_exists(pk)") for row in _rows(ev)]
    operations.append(_active_write(ev))
    if daily_cap > 0:
        operations.append({"Update": {
            "TableName": ddb.table(), "Key": ddb.row_of({"pk": owner_key(ev["user"]), "sk": "DAY#" + ev["id"][:8]}),
            "UpdateExpression": "ADD used :one", "ConditionExpression": "attribute_not_exists(used) OR used < :cap",
            "ExpressionAttributeValues": ddb.row_of({":one": 1, ":cap": daily_cap})}})
    for attempt in range(12):
        try:
            ddb.call("TransactWriteItems", {"TransactItems": operations, "ClientRequestToken": str(uuid.uuid4())})
            return ev
        except ddb.Error as e:
            if e.kind != "TransactionCanceledException": raise
            count = ddb.get(owner_key(ev["user"]), "DAY#" + ev["id"][:8]) or {}
            if daily_cap > 0 and count.get("used", 0) >= daily_cap:
                raise Limit(f"{ev['user']} has reached the daily limit of {daily_cap} evaluations") from e
            if get(ev["id"]): raise
            time.sleep(min(0.01 * 2 ** attempt, 0.2))
    raise RuntimeError("submission conflicted too often; retry the request")


def update(eid, changes, *, token=None, expected=None):
    """Compare-and-swap both authoritative copies; cancellation always wins."""
    for attempt in range(12):
        old = get(eid)
        if not old: return None
        if expected and not expected(old): return old
        if token and (old.get("claim") != token or old["status"] != "running"):
            raise LostLease(eid)
        ev = {**old, **changes, "revision": old["revision"] + 1}
        ev["cancelled"] = bool(old.get("cancelled") or changes.get("cancelled"))
        if ev["cancelled"] and ev["status"] in ("queued", "done", "failed"):
            ev.update(status="cancelled", finished=ev.get("finished") or stamp())
        a, b = _rows(ev)
        operations = [_put(a, "revision = :old", {":old": old["revision"]}), _put(b), _active_write(ev)]
        if ev["status"] == "cancelled" and old["status"] != "cancelled" and old.get("cap_counted"):
            operations.append({"Update": {
                "TableName": ddb.table(), "Key": ddb.row_of({"pk": owner_key(ev["user"]), "sk": "DAY#" + eid[:8]}),
                "UpdateExpression": "ADD used :minus", "ExpressionAttributeValues": ddb.row_of({":minus": -1})}})
        try:
            ddb.call("TransactWriteItems", {"TransactItems": operations, "ClientRequestToken": str(uuid.uuid4())})
            if not token and (ev["status"] != old["status"] or ev["cancelled"] != old.get("cancelled", False)):
                wake()
            return ev
        except ddb.Error as e:
            if e.kind != "TransactionCanceledException": raise
            time.sleep(min(0.01 * 2 ** attempt, 0.2))
    raise RuntimeError("job changed too often; retry the request")


def stamp(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def claim(eid, worker, seconds=900):
    token = uuid.uuid4().hex
    ev = update(eid, {"status": "running", "claim": token, "worker": worker,
                      "lease_until": int(time.time()) + seconds, "execution_started": stamp()},
                expected=lambda e: e["status"] == "queued" and not e.get("cancelled"))
    return ev if ev and ev.get("claim") == token else None


def expire(eid):
    return update(eid, {"status": "failed", "finished": stamp(),
                        "error": "worker lease expired; submit a new evaluation to retry"},
                  expected=lambda e: e["status"] == "running" and e.get("lease_until", 0) < time.time())


def cancel(eid):
    return update(eid, {"cancelled": True}, expected=lambda e: e["status"] in ("queued", "running"))
