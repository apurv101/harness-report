#!/usr/bin/env python3
"""ddb.py — DynamoDB over the standard library: no boto3, like every other file on this side of the fence.

proxy.py has boto3 because it runs inside the proxy image; run.sh, serve.py and lib/ are python3 and nothing else,
and a store that only works after a pip install would be a store nobody turns on.  DynamoDB's API is one POST of
JSON with a SigV4 signature, which is ~80 lines of hmac — so that is what this is.  The same code talks to
DynamoDB Local on the laptop and to a real table in a region; only the endpoint and the credentials differ.

Where the data goes (resolved once here, never in a caller):

    HR_DDB_ENDPOINT=http://…   an explicit address — another port, another host
    HR_DDB=local               shorthand for http://127.0.0.1:8001 (./run.sh ddb starts it)
    neither                    the real table in AWS_REGION, credentials from the environment or ~/.aws

`target()` is one line naming which of those is in force.  Every command that touches the table prints it, because
the sibling repo's local switch was silently inert for two sessions and both of them wrote to production.

Types: numbers, strings, bools, null, lists and maps marshal the obvious way.  Floats keep their repr.  Empty
strings are fine (DynamoDB allows them everywhere except in a key).  Sets and binary are not used and not supported.
"""
import configparser, datetime, hashlib, hmac, json, os, time, urllib.error, urllib.parse, urllib.request

LOCAL_ENDPOINT = "http://127.0.0.1:8001"
# DynamoDB Local checks that a request is signed, never who signed it — but without -sharedDb it shards tables by
# access key, so these are constants rather than throwaways: every process must land on the same shard.
LOCAL_CREDENTIALS = ("hrlocal", "hrlocal", None)
DEFAULT_TABLE = "harness-report"
TRUTHY = ("1", "true", "yes", "on", "local")


def dotenv(path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")):
    """run.sh reads .env, and so does auth.py for its own keys — this reads it for HR_DDB/HR_TABLE/AWS_*, so
    `python3 lib/store.py …` from a terminal lands on the same table as everything else.  The real environment wins."""
    try:
        with open(path) as f: lines = f.readlines()
    except OSError: return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


dotenv()


class Error(Exception):
    """A DynamoDB error, carrying the API's own __type so a caller can match on it."""
    def __init__(self, kind, message, status=None):
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind, self.message, self.status = kind, message, status


def endpoint():
    """The address to talk to, or None for the real thing in AWS."""
    explicit = (os.environ.get("HR_DDB_ENDPOINT") or "").strip()
    if explicit: return explicit
    return LOCAL_ENDPOINT if (os.environ.get("HR_DDB") or "").strip().lower() in TRUTHY else None


def local(): return endpoint() is not None
def region(): return os.environ.get("AWS_REGION") or "us-west-2"
def table(override=None): return override or os.environ.get("HR_TABLE") or DEFAULT_TABLE


def target(name=None):
    """One line saying where the data is going.  Printed by everything that writes."""
    ep = endpoint()
    return f"{table(name)} on local DynamoDB ({ep})" if ep else f"{table(name)} in {region()}"


def credentials():
    """(key, secret, token).  Local needs a signature, not an identity, so it gets the constants above; a real
    table takes the environment first, then the named profile in ~/.aws/credentials.  SSO and credential_process
    are not resolved here — export the keys, or use a profile with static ones."""
    if local(): return LOCAL_CREDENTIALS
    return real_credentials()


def real_credentials():
    """The account's own keys, never the DynamoDB Local constants.  Anything that is not DynamoDB wants these:
    a laptop with HR_DDB=local still talks to the real SQS, and signing that with "hrlocal" fails in a way that
    reads like a permissions problem."""
    k, s = os.environ.get("AWS_ACCESS_KEY_ID"), os.environ.get("AWS_SECRET_ACCESS_KEY")
    if k and s: return k, s, os.environ.get("AWS_SESSION_TOKEN")
    profile = os.environ.get("AWS_PROFILE") or "default"
    cfg = configparser.ConfigParser()
    cfg.read([os.path.expanduser("~/.aws/credentials")])
    for section in (profile, f"profile {profile}"):
        if cfg.has_option(section, "aws_access_key_id"):
            return (cfg.get(section, "aws_access_key_id"), cfg.get(section, "aws_secret_access_key"),
                    cfg.get(section, "aws_session_token", fallback=None))
    raise Error("NoCredentials", f"no keys in the environment and no static keys for profile '{profile}' in "
                                 f"~/.aws/credentials (or set HR_DDB=local to use the laptop's DynamoDB)")


# ------------------------------------------------------------------ SigV4
def _sign(key, msg): return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sigv4(host, service, amz_target, body, key, secret, token):
    """Signed headers for one POST / of an x-amz-json-1.0 API.  DynamoDB and SQS differ only in the host, the
    service name in the scope, and the target — so both go through here rather than through two copies of the
    same eighty lines of hmac."""
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp, date = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    headers = {"content-type": "application/x-amz-json-1.0", "host": host,
               "x-amz-date": stamp, "x-amz-target": amz_target}
    if token: headers["x-amz-security-token"] = token
    signed = ";".join(sorted(headers))
    # The canonical request is exact to the byte: each header line ends in a newline, then ONE blank line, then the
    # signed-header list and the payload hash.  A join that puts a newline between already-terminated lines signs
    # something the service will not agree with, and the only symptom is InvalidSignatureException.
    canonical = ("POST\n/\n\n" + "".join(f"{k}:{headers[k].strip()}\n" for k in sorted(headers))
                 + f"\n{signed}\n" + hashlib.sha256(body).hexdigest())
    scope = f"{date}/{region()}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = _sign(_sign(_sign(_sign(("AWS4" + secret).encode(), date), region()), service), "aws4_request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (f"AWS4-HMAC-SHA256 Credential={key}/{scope}, SignedHeaders={signed}, Signature={sig}")
    return headers


def _auth_headers(op, body, key, secret, token):
    host = urllib.parse.urlsplit(endpoint() or f"https://dynamodb.{region()}.amazonaws.com").netloc
    return sigv4(host, "dynamodb", f"DynamoDB_20120810.{op}", body, key, secret, token)


# Throttling and a table that is still being created are normal, not failures; everything else is raised at once.
RETRY = ("ProvisionedThroughputExceededException", "ThrottlingException", "RequestLimitExceeded",
         "InternalServerError", "ServiceUnavailable", "LimitExceededException")


def call(op, payload, attempts=5):
    """One DynamoDB operation.  Raises Error on anything the API refuses."""
    body = json.dumps(payload).encode()
    url = endpoint() or f"https://dynamodb.{region()}.amazonaws.com"
    key, secret, token = credentials()
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=body, headers=_auth_headers(op, body, key, secret, token))
        try:
            with urllib.request.urlopen(req, timeout=20) as r: return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try: err = json.loads(raw)
            except ValueError: err = {}
            kind = (err.get("__type") or f"HTTP {e.code}").split("#")[-1]
            if kind in RETRY and attempt < attempts - 1: time.sleep(0.2 * 2 ** attempt); continue
            raise Error(kind, err.get("message") or err.get("Message") or raw[:400], e.code) from None
        except urllib.error.URLError as e:
            if attempt < attempts - 1: time.sleep(0.2 * 2 ** attempt); continue
            hint = "  (is it running?  ./run.sh ddb start)" if local() else ""
            raise Error("Unreachable", f"{target()}: {e.reason}{hint}") from None


# ------------------------------------------------------------------ types
def marshal(v):
    if v is None: return {"NULL": True}
    if isinstance(v, bool): return {"BOOL": v}
    if isinstance(v, (int, float)): return {"N": repr(v) if isinstance(v, float) else str(v)}
    if isinstance(v, str): return {"S": v}
    if isinstance(v, (list, tuple)): return {"L": [marshal(x) for x in v]}
    if isinstance(v, dict): return {"M": {k: marshal(x) for k, x in v.items()}}
    return {"S": str(v)}


def unmarshal(a):
    (t, v), = a.items()
    if t == "NULL": return None
    if t == "N": return float(v) if ("." in v or "e" in v.lower()) else int(v)
    if t == "L": return [unmarshal(x) for x in v]
    if t == "M": return {k: unmarshal(x) for k, x in v.items()}
    return v                                     # S, BOOL


def item_of(row): return {k: unmarshal(v) for k, v in row.items()}
# A null is a fact: run.json says reward: null for a prompt run, and a reader that got nothing back instead of a
# null would be reading a different record.  DynamoDB's NULL type carries it, so nothing here is dropped.
def row_of(item): return {k: marshal(v) for k, v in item.items()}


# ------------------------------------------------------------------ the five things a caller does
def put(item, name=None):
    call("PutItem", {"TableName": table(name), "Item": row_of(item)})


def batch_put(items, name=None):
    """PutItem in batches of 25, retrying whatever the service hands back unprocessed."""
    t, n = table(name), 0
    for i in range(0, len(items), 25):
        pending = {t: [{"PutRequest": {"Item": row_of(x)}} for x in items[i:i + 25]]}
        for attempt in range(6):
            res = call("BatchWriteItem", {"RequestItems": pending})
            pending = res.get("UnprocessedItems") or {}
            if not pending.get(t): break
            time.sleep(0.2 * 2 ** attempt)
        n += len(items[i:i + 25])
    return n


def get(pk, sk, name=None, consistent=True):
    res = call("GetItem", {"TableName": table(name), "Key": {"pk": {"S": pk}, "sk": {"S": sk}},
                           "ConsistentRead": consistent})
    return item_of(res["Item"]) if res.get("Item") else None


# Each index's own key attributes.  An index name not listed here is a bug, not a new index.
INDEX_KEYS = {None: ("pk", "sk"), "harness": ("gsi1pk", "gsi1sk"), "task": ("gsi2pk", "gsi2sk")}


def query(pk, prefix=None, index=None, desc=False, limit=None, name=None, attributes=None, after=None):
    """Every item in one partition, optionally narrowed to a sort-key prefix.  Pages until the partition is done
    (or `limit` items are in hand), which is what every read in this repo wants.  `after` (a base-table sort key)
    starts the read just past that row — the cursor a paged list hands back to its caller."""
    key, sort = INDEX_KEYS[index]
    cond, values = f"{key} = :k", {":k": {"S": pk}}
    if prefix: cond, values[":p"] = f"{cond} AND begins_with({sort}, :p)", {"S": prefix}
    req = {"TableName": table(name), "KeyConditionExpression": cond, "ExpressionAttributeValues": values,
           "ScanIndexForward": not desc}
    if index: req["IndexName"] = index
    if after and not index: req["ExclusiveStartKey"] = {"pk": {"S": pk}, "sk": {"S": after}}
    if attributes:
        req["ProjectionExpression"] = ", ".join(f"#a{i}" for i, _ in enumerate(attributes))
        req["ExpressionAttributeNames"] = {f"#a{i}": a for i, a in enumerate(attributes)}
    out = []
    while True:
        if limit: req["Limit"] = min(limit - len(out), 1000)
        res = call("Query", req)
        out += [item_of(r) for r in res.get("Items", [])]
        if not res.get("LastEvaluatedKey") or (limit and len(out) >= limit): return out[:limit] if limit else out
        req["ExclusiveStartKey"] = res["LastEvaluatedKey"]


def delete_partition(pk, name=None):
    """Every item under one pk, removed 25 at a time — for re-publishing a run whose shape changed."""
    keys = [{"pk": i["pk"], "sk": i["sk"]} for i in query(pk, name=name, attributes=["pk", "sk"])]
    t = table(name)
    for i in range(0, len(keys), 25):
        call("BatchWriteItem", {"RequestItems": {t: [{"DeleteRequest": {"Key": row_of(k)}} for k in keys[i:i + 25]]}})
    return len(keys)


def indexes(name=None):
    """The names of the table's global secondary indexes, and each one's status."""
    t = call("DescribeTable", {"TableName": table(name)})["Table"]
    return {g["IndexName"]: g.get("IndexStatus") for g in t.get("GlobalSecondaryIndexes") or []}


def exists(name=None):
    try: return call("DescribeTable", {"TableName": table(name)})["Table"]["TableStatus"]
    except Error as e:
        if e.kind in ("ResourceNotFoundException",): return None
        raise
