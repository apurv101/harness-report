#!/usr/bin/env python3
"""leases.py — the lease queue, over the standard library.

One evaluation started on the site is one message here: the API writes it, a runner leases it, runs it, and
deletes it.  The queue is the whole coupling between the two — the API never learns where a run happens, and
the runner never learns who asked.  That is what lets the same daemon run on the laptop today and on an EC2
runner later without either side changing (RUN-PLANE.md).

Not named queue.py: `queue` is a standard-library module, and on any host that imports boto3 before
this one is on sys.path — every Lambda, because the runtime does it — stdlib wins and the calls here vanish
behind an AttributeError that names no file of ours.

SQS's JSON protocol is the same shape as DynamoDB's — POST / with an x-amz-target and a JSON body — so this
borrows ddb.sigv4 rather than carrying a second copy of SigV4.  It borrows ddb.real_credentials, not
ddb.credentials: a laptop with HR_DDB=local still talks to the real SQS, and signing that with DynamoDB
Local's constants fails in a way that reads like a permissions problem.

    HR_QUEUE_URL=https://sqs.us-west-2.amazonaws.com/<account>/harness-report-leases

    configured()                 -> False when HR_QUEUE_URL is unset; the caller then runs or refuses locally
    send(body)                   -> put one lease on the queue, returns its message id
    receive(wait=20, visibility) -> lease one, or None.  Long-polls, so an idle runner costs one request a minute
    delete(receipt)              -> done with it; without this it comes back when the visibility window ends
    extend(receipt, seconds)     -> still working.  A run outlasting its window is how a task runs twice

A lease that is never deleted is redelivered up to the queue's maxReceiveCount and then goes to the dead-letter
queue, so a runner that dies mid-run loses the run but not the record of it.
"""
import hashlib, json, os, urllib.error, urllib.parse, urllib.request

import ddb

TIMEOUT = 30        # seconds for the HTTP call itself, which must outlast the long poll


class Error(Exception):
    pass


def url():
    return (os.environ.get("HR_QUEUE_URL") or "").strip()


def configured():
    return bool(url())


def call(op, payload):
    """One SQS operation against the queue in HR_QUEUE_URL."""
    q = url()
    if not q: raise Error("HR_QUEUE_URL is not set")
    host = urllib.parse.urlsplit(q).netloc
    body = json.dumps({"QueueUrl": q, **payload}).encode()
    key, secret, token = ddb.real_credentials()
    headers = ddb.sigv4(host, "sqs", f"AmazonSQS.{op}", body, key, secret, token)
    req = urllib.request.Request(f"https://{host}/", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r: return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try: err = json.loads(raw)
        except ValueError: err = {}
        kind = (err.get("__type") or f"HTTP {e.code}").split("#")[-1]
        raise Error(f"{kind}: {err.get('message') or err.get('Message') or raw[:300]}") from None
    except urllib.error.URLError as e:
        raise Error(f"{host}: {e.reason}") from None


def send(body):
    """One lease onto the queue.  `body` is a dict; it travels as JSON."""
    request = {"MessageBody": json.dumps(body)}
    if url().endswith(".fifo"):
        request.update(MessageGroupId=hashlib.sha256(body["user"].lower().encode()).hexdigest(),
                       MessageDeduplicationId=body["eval"])
    return call("SendMessage", request).get("MessageId")


def receive(wait=20, visibility=None):
    """Lease one message, or None if the queue stayed empty for `wait` seconds.

    Long-polling is not an optimisation here — a runner polling in a tight loop bills a request every time
    round, and 20 s of waiting is one request per 20 s whether or not anything arrives."""
    req = {"MaxNumberOfMessages": 1, "WaitTimeSeconds": wait}
    if visibility is not None: req["VisibilityTimeout"] = visibility
    got = call("ReceiveMessage", req).get("Messages") or []
    if not got: return None
    m = got[0]
    try: body = json.loads(m.get("Body") or "{}")
    except ValueError: body = {}
    return {"receipt": m["ReceiptHandle"], "id": m.get("MessageId"), "body": body}


def delete(receipt):
    call("DeleteMessage", {"ReceiptHandle": receipt})


def extend(receipt, seconds):
    """Push the visibility window out while a long run is still going.  A run that outlives its window is
    handed to a second runner while the first is still working on it — which is how one task runs twice."""
    call("ChangeMessageVisibility", {"ReceiptHandle": receipt, "VisibilityTimeout": int(seconds)})


def depth():
    """Roughly what is waiting and what is in flight — for `hr-agentd --status` and nothing load-bearing."""
    a = call("GetQueueAttributes", {"AttributeNames": ["ApproximateNumberOfMessages",
                                                       "ApproximateNumberOfMessagesNotVisible"]})
    at = a.get("Attributes") or {}
    return {"waiting": int(at.get("ApproximateNumberOfMessages") or 0),
            "in_flight": int(at.get("ApproximateNumberOfMessagesNotVisible") or 0)}
