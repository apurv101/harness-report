#!/usr/bin/env python3
"""proxy.py — sits between the harness and the model and records every call.

Harness side:  POST /v1/chat/completions  (OpenAI shape)        POST /v1/messages  (Anthropic shape)
               GET  /v1/models            GET /health           POST /v1/messages/count_tokens
Model side:    routed per requested model name by $ROUTES (comma-separated pattern=target, fnmatch patterns, first
               match wins), falling back to $MODEL for everything else. Targets:
                 bedrock/<id>       Bedrock (boto3); a bare id with no prefix also means Bedrock
                 anthropic[/<id>]   api.anthropic.com with $ANTHROPIC_API_KEY ($ANTHROPIC_BASE_URL to override);
                                    no /<id> keeps the model the harness asked for
                 openai[/<id>]      $OPENAI_BASE_URL (default https://api.openai.com/v1) with $OPENAI_API_KEY; same rule
               e.g. ROUTES="claude-haiku*=anthropic,gpt-4o-mini=openai,*=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
               anthropic and openai targets only take requests already in their own API shape; Bedrock takes both.
               The harness never holds credentials: whatever key it sends is dropped and the proxy's own key is used.
Egress:        a forward proxy on :3128 (HTTP and CONNECT) is the sandbox's only way out (run.sh puts the harness on an
               --internal docker network with HTTP(S)_PROXY pointing here). $EGRESS: record (allow + log everything),
               none (refuse everything), allow:a.com,b.org (refuse the rest), inspect (record + TLS interception with
               a per-run CA written to /out/hr-ca.pem; request and response bodies land in /out/egress/). $BLOCK_URLS
               (newline-separated regexes) refuses matching URLs (or hosts, when only the host is visible). One line
               per connection or request in /out/egress.jsonl. POST /_hr/phase (X-HR-Token: $CONTROL_TOKEN) switches
               to the verify phase, where everything is allowed and still logged.
Policy:        policy.py reads each reply's tool calls and shell fences before the harness sees them. $POLICY: flag
               (default; findings in the record), enforce (flagged actions rewritten to fail), off. With $TESTS_DIR
               the requests are also checked for the task's test lines (verifier_leak).
Record:        one JSON line per call in $LOG: n, ts, route, latency_ms, model_requested, request, response,
               usage, stream, error, backend, model (the model that served it), flags, request_fixes (what the proxy
               changed so Bedrock would accept the call: max_tokens capped, refused fields dropped, ...), and on
               enforce rewrites + response_original. `stream: true` requests are answered with a synthesized event stream.
"""
import datetime, fnmatch, http.client, json, os, re, select, socket, ssl, sys, time, uuid, threading, traceback, urllib.error, urllib.request
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import boto3
from botocore.exceptions import ClientError
import policy

MODEL = os.environ["MODEL"]


def parse_target(t):
    """'bedrock/<id>' | '<id>' | 'anthropic[/<id>]' | 'openai[/<id>]' -> (backend, model or None = keep the requested one)"""
    t = t.strip()
    for b in ("anthropic", "openai"):
        if t == b or t.startswith(b + "/"): return b, t[len(b) + 1:] or None
    return "bedrock", t.removeprefix("bedrock/")


ROUTES = [(pat.strip(), parse_target(tgt)) for pat, _, tgt in
          (r.partition("=") for r in os.environ.get("ROUTES", "").split(",") if "=" in r)] + [("*", parse_target(MODEL))]


def route_for(requested):
    for pat, tgt in ROUTES:
        if fnmatch.fnmatchcase(requested or "", pat): return tgt
LOG = os.environ.get("LOG", "/out/calls.jsonl")
PORT = int(os.environ.get("PORT", "4000"))
brt = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_lock = threading.Lock()
_n = [0]
OUTDIR = os.path.dirname(LOG) or "."
POLICY = os.environ.get("POLICY", "flag")
NEEDLES = policy.leak_needles(os.environ["TESTS_DIR"], os.environ.get("ENV_DIR")) if os.environ.get("TESTS_DIR") else []
LEAKED = set()


def record(rec):
    with _lock:
        _n[0] += 1
        rec["n"] = _n[0]
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
    print(f"[{rec['n']:3d}] {rec['route']:9s} {rec.get('latency_ms', 0):6d}ms  in={rec['usage'].get('input_tokens')} out={rec['usage'].get('output_tokens')}"
          + (f"  ERROR {rec['error'][:120]}" if rec.get("error") else ""), flush=True)


# Bedrock refuses requests some harnesses send as a matter of course. These fixes make the smallest change that gets the
# call through, and each one is written to the call's record under request_fixes, so the recording shows what was changed.
MAX_OUT = [("haiku-4-5", 64000), ("sonnet-4", 64000), ("opus-4-5", 64000), ("opus-4", 32000), ("3-7-sonnet", 64000), ("3-5-haiku", 8192)]
BEDROCK_ANTHROPIC_KEYS = {"anthropic_version", "messages", "system", "max_tokens", "temperature", "top_p", "top_k", "stop_sequences",
                          "tools", "tool_choice", "thinking"}


def max_out(model):
    if os.environ.get("MAX_OUTPUT_TOKENS"): return int(os.environ["MAX_OUTPUT_TOKENS"])
    return next((n for pat, n in MAX_OUT if pat in (model or "")), None)


def fix_sampling(p, fixes, temp="temperature", top_p="top_p", thinking_on=False):
    """Anthropic's newer models take temperature or top_p, not both; with thinking on, neither may be changed."""
    if thinking_on:
        for k in (temp, top_p, "top_k"):
            if k in p: fixes.append(f"dropped {k}={p.pop(k)} (thinking is on)")
    elif p.get(temp) is not None and p.get(top_p) is not None:
        fixes.append(f"dropped {top_p}={p.pop(top_p)} (temperature is set)")


def with_retry(fn):
    for attempt in range(4):
        try:
            return fn()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException") and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise


# ----------------------------------------------------------------------------- OpenAI  →  Bedrock Converse
def _text_of(c):
    if c is None: return ""
    if isinstance(c, str): return c
    out = []
    for p in c:
        if isinstance(p, str): out.append(p)
        elif p.get("type") in ("text", "input_text"): out.append(p.get("text", ""))
        elif "text" in p: out.append(str(p["text"]))
    return "\n".join(out)


def _push(msgs, role, blocks):
    blocks = [b for b in blocks if not ("text" in b and not b["text"].strip())]
    if not blocks: blocks = [{"text": "(empty)"}]
    if msgs and msgs[-1]["role"] == role: msgs[-1]["content"].extend(blocks)
    else: msgs.append({"role": role, "content": blocks})


def openai_to_converse(body, model, fixes):
    system, msgs = [], []
    for m in body.get("messages", []):
        role, c = m.get("role"), m.get("content")
        if role in ("system", "developer"):
            t = _text_of(c)
            if t.strip(): system.append({"text": t})
        elif role == "user":
            _push(msgs, "user", [{"text": _text_of(c)}])
        elif role == "assistant":
            blocks = [{"text": _text_of(c)}]
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try: args = json.loads(args or "{}")
                    except Exception: args = {"raw": args}
                blocks.append({"toolUse": {"toolUseId": tc.get("id") or f"call_{uuid.uuid4().hex[:12]}", "name": fn.get("name", "tool"), "input": args}})
            _push(msgs, "assistant", blocks)
        elif role == "tool":
            _push(msgs, "user", [{"toolResult": {"toolUseId": m.get("tool_call_id", ""), "content": [{"text": _text_of(c) or "(empty)"}]}}])
    if msgs and msgs[0]["role"] != "user": msgs.insert(0, {"role": "user", "content": [{"text": "(start)"}]})
    kw = {"modelId": model, "messages": msgs}
    if system: kw["system"] = system
    inf = {"maxTokens": int(body.get("max_completion_tokens") or body.get("max_tokens") or 4096)}
    cap = max_out(model)
    if cap and inf["maxTokens"] > cap: fixes.append(f"max_tokens {inf['maxTokens']} -> {cap}"); inf["maxTokens"] = cap
    if body.get("temperature") is not None: inf["temperature"] = float(body["temperature"])
    if body.get("top_p") is not None: inf["topP"] = float(body["top_p"])
    fix_sampling(inf, fixes, "temperature", "topP")
    stop = body.get("stop")
    if stop: inf["stopSequences"] = [stop] if isinstance(stop, str) else list(stop)[:4]
    kw["inferenceConfig"] = inf
    tools = [t for t in body.get("tools") or [] if t.get("type", "function") == "function"]
    choice = body.get("tool_choice")
    specs = []
    if tools and choice != "none":
        for t in tools:
            f = t.get("function", t)
            schema = f.get("parameters") or {"type": "object", "properties": {}}
            if schema.get("type") != "object": schema = {"type": "object", "properties": {}}
            specs.append({"toolSpec": {"name": f["name"], "description": (f.get("description") or f["name"])[:2000], "inputSchema": {"json": schema}}})
    if not specs:
        # Converse refuses toolUse/toolResult blocks without a toolConfig, even when this turn offers no tools (nib does
        # this); declare the tools the history already used, and drop tool_choice so the model is not pushed to call one
        used = sorted({b["toolUse"]["name"] for m in msgs for b in m["content"] if "toolUse" in b})
        if not used and any("toolResult" in b for m in msgs for b in m["content"]): used = ["tool"]
        if used:
            fixes.append(f"toolConfig declared from history: {used}")
            specs = [{"toolSpec": {"name": n, "description": n, "inputSchema": {"json": {"type": "object", "properties": {}}}}} for n in used]
            choice = None
    if specs:
        tc = {"tools": specs}
        if choice == "required": tc["toolChoice"] = {"any": {}}
        elif isinstance(choice, dict) and choice.get("function", {}).get("name"): tc["toolChoice"] = {"tool": {"name": choice["function"]["name"]}}
        kw["toolConfig"] = tc
    return kw


def converse_to_openai(resp, body):
    out = resp["output"]["message"]
    text = "".join(b["text"] for b in out["content"] if "text" in b)
    tool_calls = [{"id": b["toolUse"]["toolUseId"], "type": "function",
                   "function": {"name": b["toolUse"]["name"], "arguments": json.dumps(b["toolUse"]["input"])}}
                  for b in out["content"] if "toolUse" in b]
    finish = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length", "stop_sequence": "stop"}.get(resp.get("stopReason"), "stop")
    msg = {"role": "assistant", "content": text if text else None}
    if tool_calls: msg["tool_calls"] = tool_calls
    u = resp.get("usage", {})
    return {"id": "chatcmpl-" + uuid.uuid4().hex[:24], "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model") or "model",
            "choices": [{"index": 0, "message": msg, "finish_reason": finish, "logprobs": None}],
            "usage": {"prompt_tokens": u.get("inputTokens", 0), "completion_tokens": u.get("outputTokens", 0), "total_tokens": u.get("totalTokens", 0)}}


def openai_stream(full, body):
    """One finished completion → the chunk sequence an OpenAI streaming client expects."""
    base = {"id": full["id"], "object": "chat.completion.chunk", "created": full["created"], "model": full["model"]}
    ch = full["choices"][0]; msg = ch["message"]
    def chunk(delta, finish=None):
        return "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"
    yield chunk({"role": "assistant", "content": msg.get("content") or ""})
    for i, tc in enumerate(msg.get("tool_calls") or []):
        yield chunk({"tool_calls": [{"index": i, **tc}]})
    yield chunk({}, ch["finish_reason"])
    if (body.get("stream_options") or {}).get("include_usage"):
        yield "data: " + json.dumps({**base, "choices": [], "usage": full["usage"]}) + "\n\n"
    yield "data: [DONE]\n\n"


# ----------------------------------------------------------------------------- Anthropic  →  Bedrock InvokeModel
def anthropic_call(body, model, fixes):
    # keep only the fields Bedrock's Messages API accepts (Claude Code sends context_management, newer SDKs output_config, ...)
    b = {k: v for k, v in body.items() if k in BEDROCK_ANTHROPIC_KEYS}
    dropped = sorted(k for k in body if k not in b and k not in ("model", "stream", "metadata", "service_tier", "betas"))
    if dropped: fixes.append(f"dropped fields Bedrock refuses: {dropped}")
    b["anthropic_version"] = "bedrock-2023-05-31"
    b.setdefault("max_tokens", 4096)
    cap = max_out(model)
    if cap and b["max_tokens"] > cap: fixes.append(f"max_tokens {b['max_tokens']} -> {cap}"); b["max_tokens"] = cap
    th = b.get("thinking")
    if isinstance(th, dict):
        if th.get("type") == "enabled":
            budget = min(int(th.get("budget_tokens") or 1024), b["max_tokens"] - 1)
            if budget < 1024: b.pop("thinking"); fixes.append("dropped thinking (max_tokens too small for a budget)")
            else: b["thinking"] = {"type": "enabled", "budget_tokens": budget}
        elif th.get("type") == "disabled": b["thinking"] = {"type": "disabled"}
        else: b.pop("thinking"); fixes.append(f"dropped thinking type {th.get('type')!r} (not on this model via Bedrock)")
    fix_sampling(b, fixes, thinking_on=(b.get("thinking") or {}).get("type") == "enabled")
    r = with_retry(lambda: brt.invoke_model(modelId=model, body=json.dumps(b), contentType="application/json", accept="application/json"))
    resp = json.loads(r["body"].read())
    resp["model"] = body.get("model") or model
    return resp


# ----------------------------------------------------------------------------- passthrough: the real provider, our key
class Upstream(Exception):
    def __init__(self, code, text): super().__init__(f"upstream HTTP {code}: {text[:500]}"); self.code = code


def post_json(url, body, headers):
    data = json.dumps(body).encode()
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, method="POST", headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=900) as r: return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 3: time.sleep(2 ** attempt); continue
            raise Upstream(e.code, e.read().decode(errors="replace"))


def need(var):
    v = os.environ.get(var)
    if not v: raise Upstream(500, f"route needs {var} in the proxy's environment (.env)")
    return v


def anthropic_direct(body, model, headers):
    """Anthropic messages API as-is. Asked non-streaming; the stream the harness wants is synthesized as for Bedrock."""
    b = {k: v for k, v in body.items() if k != "stream"}
    if model: b["model"] = model
    b.setdefault("max_tokens", 4096)
    h = {"x-api-key": need("ANTHROPIC_API_KEY"), "anthropic-version": headers.get("anthropic-version") or "2023-06-01"}
    if headers.get("anthropic-beta"): h["anthropic-beta"] = headers["anthropic-beta"]
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    return post_json(base + "/v1/messages", b, h)


def openai_direct(body, model):
    b = {k: v for k, v in body.items() if k not in ("stream", "stream_options")}
    if model: b["model"] = model
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    return post_json(base + "/chat/completions", b, {"authorization": "Bearer " + need("OPENAI_API_KEY")})


def anthropic_stream(full):
    def ev(name, data): return f"event: {name}\ndata: {json.dumps(data)}\n\n"
    usage = full.get("usage", {})
    head = {**full, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": usage.get("input_tokens", 0), "output_tokens": 0}}
    yield ev("message_start", {"type": "message_start", "message": head})
    for i, blk in enumerate(full.get("content", [])):
        t = blk.get("type")
        if t == "text":
            yield ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
            yield ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": blk.get("text", "")}})
        elif t == "tool_use":
            yield ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "tool_use", "id": blk["id"], "name": blk["name"], "input": {}}})
            yield ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(blk.get("input", {}))}})
        elif t == "thinking":
            yield ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": ""}})
            yield ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "thinking_delta", "thinking": blk.get("thinking", "")}})
            if blk.get("signature"):
                yield ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "signature_delta", "signature": blk["signature"]}})
        else:
            yield ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": blk})
        yield ev("content_block_stop", {"type": "content_block_stop", "index": i})
    yield ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": full.get("stop_reason"), "stop_sequence": full.get("stop_sequence")},
                               "usage": {"output_tokens": usage.get("output_tokens", 0)}})
    yield ev("message_stop", {"type": "message_stop"})


# ----------------------------------------------------------------------------- egress: the sandbox's only way out
EGRESS = os.environ.get("EGRESS", "record")
EGRESS_PORT = int(os.environ.get("EGRESS_PORT", "3128"))
EGRESS_LOG = os.path.join(OUTDIR, "egress.jsonl")
BLOCK_URLS = [re.compile(x) for x in os.environ.get("BLOCK_URLS", "").split("\n") if x.strip()]
SELF_HOSTS = {h for h in os.environ.get("SELF_HOSTS", "").split(",") if h} | {"localhost", "127.0.0.1"}
CONTROL_TOKEN = os.environ.get("CONTROL_TOKEN", "")
PHASE = ["agent"]
BODY_CAP = 2 * 1024 * 1024
HOP = {"connection", "proxy-connection", "keep-alive", "proxy-authorization", "proxy-authenticate", "te", "trailer", "transfer-encoding", "upgrade"}
_elock = threading.Lock()
_en = [0]


def decide(host, url=None):
    """(allowed, rule) for a destination; `url` is known for plain HTTP and for inspected HTTPS."""
    if host in SELF_HOSTS: return True, "self"
    for rx in BLOCK_URLS:
        if rx.search(url or host): return False, f"block-url {rx.pattern}"
    if PHASE[0] == "verify": return True, "verify phase"
    if EGRESS == "none": return False, "egress none"
    if EGRESS.startswith("allow:"):
        ok = any(host == h or host.endswith("." + h) for h in EGRESS[6:].split(",") if h)
        return ok, "allow-list" if ok else "not in allow-list"
    return True, EGRESS


def alloc():
    with _elock:
        _en[0] += 1
        return _en[0]


def elog(rec, n=None):
    rec = {"n": n or alloc(), "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "phase": PHASE[0], **rec}
    with _elock:
        with open(EGRESS_LOG, "a") as f: f.write(json.dumps(rec) + "\n")
    print(f"egress {rec['n']:3d} {rec.get('method', ''):7s} {'ALLOW' if rec.get('allowed') else 'BLOCK'} {rec.get('url') or rec.get('host')}"
          + (f"  ({rec['rule']})" if rec.get("rule") else "") + (f"  ERROR {rec['error'][:80]}" if rec.get("error") else ""), flush=True)
    return rec["n"]


def save_body(n, kind, data):
    if not data: return None
    os.makedirs(os.path.join(OUTDIR, "egress"), exist_ok=True)
    name = f"egress/{n:04d}.{kind}"
    with open(os.path.join(OUTDIR, name), "wb") as f: f.write(data[:BODY_CAP])
    return name


def read_body(h):
    """Request body from a handler: Content-Length or chunked."""
    if h.headers.get("Content-Length"): return h.rfile.read(int(h.headers["Content-Length"]))
    if "chunked" in (h.headers.get("Transfer-Encoding") or "").lower():
        out = b""
        while True:
            size = int(h.rfile.readline().split(b";")[0].strip() or b"0", 16)
            if size == 0: h.rfile.readline(); return out
            out += h.rfile.read(size); h.rfile.readline()
    return b""


def forward(h, scheme, host, port, path, inspect):
    """Relay one request upstream and the whole response back; log it (bodies too when inspecting)."""
    url = f"{scheme}://{host}{'' if port in (80, 443) else ':' + str(port)}{path}"
    allowed, rule = decide(host, url)
    t0 = time.time(); body = read_body(h)
    rec = {"kind": scheme, "method": h.command, "host": host, "port": port, "url": url, "allowed": allowed, "rule": rule,
           "bytes_up": len(body), "bytes_down": 0, "status": None, "error": None}
    if not allowed:
        rec["status"] = 403; n = elog(rec)
        msg = f"blocked by harness-report egress policy: {rule}\n".encode()
        h.send_response(403); h.send_header("Content-Type", "text/plain"); h.send_header("Content-Length", str(len(msg))); h.end_headers(); h.wfile.write(msg)
        return
    headers = {k: v for k, v in h.headers.items() if k.lower() not in HOP}
    try:
        conn = (http.client.HTTPSConnection(host, port, timeout=300, context=ssl.create_default_context()) if scheme == "https"
                else http.client.HTTPConnection(host, port, timeout=300))
        conn.request(h.command, path, body or None, headers)
        r = conn.getresponse(); data = r.read(); conn.close()
    except Exception as e:
        rec.update(status=502, error=f"{type(e).__name__}: {e}", ms=int((time.time() - t0) * 1000)); elog(rec)
        msg = f"upstream error: {e}\n".encode()
        h.send_response(502); h.send_header("Content-Length", str(len(msg))); h.end_headers(); h.wfile.write(msg)
        return
    rec.update(status=r.status, bytes_down=len(data), ms=int((time.time() - t0) * 1000))
    n = alloc()
    if inspect: rec["req_file"], rec["resp_file"] = save_body(n, "req", body), save_body(n, "resp", data)
    elog(rec, n)
    h.send_response(r.status, r.reason)
    for k, v in r.getheaders():
        if k.lower() not in HOP and k.lower() != "content-length": h.send_header(k, v)
    h.send_header("Content-Length", str(len(data))); h.end_headers(); h.wfile.write(data)


# --- per-run CA for inspect mode (leaf certificates minted per host on demand)
_ca = {}
_ctx = {}


def ca_setup():
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "harness-report interception CA (this run only)")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _ca.update(key=key, cert=cert, leaf_key=ec.generate_private_key(ec.SECP256R1()))
    with open(os.path.join(OUTDIR, "hr-ca.pem"), "wb") as f: f.write(cert.public_bytes(serialization.Encoding.PEM))
    os.makedirs("/tmp/hr-certs", exist_ok=True)


def host_ctx(host):
    with _elock:
        if host in _ctx: return _ctx[host]
    import ipaddress
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    now = datetime.datetime.now(datetime.timezone.utc); lk = _ca["leaf_key"]
    try: san = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError: san = x509.DNSName(host)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host[:64])]))
            .issuer_name(_ca["cert"].subject).public_key(lk.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([san]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(_ca["key"].public_key()), critical=False)
            .sign(_ca["key"], hashes.SHA256()))
    path = f"/tmp/hr-certs/{re.sub(r'[^A-Za-z0-9.-]', '_', host)}.pem"
    with open(path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
        f.write(lk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.set_alpn_protocols(["http/1.1"]); ctx.load_cert_chain(path)
    with _elock: _ctx[host] = ctx
    return ctx


class Inner(BaseHTTPRequestHandler):
    """HTTP/1.1 requests inside an intercepted TLS tunnel; `target` is set per tunnel."""
    protocol_version = "HTTP/1.1"
    target = ("", 443)
    def log_message(self, *a): pass
    def _any(self): forward(self, "https", self.target[0], self.target[1], self.path, True)
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _any


class Egress(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _plain(self):
        u = urlsplit(self.path)
        if not u.scheme or not u.hostname:
            return self.send_error(400, "this is a forward proxy; send absolute URLs or CONNECT")
        forward(self, u.scheme, u.hostname, u.port or (443 if u.scheme == "https" else 80), (u.path or "/") + (f"?{u.query}" if u.query else ""), EGRESS == "inspect")
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _plain

    def do_CONNECT(self):
        host, _, port = self.path.rpartition(":"); host = host.strip("[]"); port = int(port or 443)
        allowed, rule = decide(host)
        rec = {"kind": "connect", "method": "CONNECT", "host": host, "port": port, "url": None, "allowed": allowed, "rule": rule}
        if not allowed:
            elog({**rec, "status": 403}); self.send_error(403, f"blocked by harness-report egress policy: {rule}"); return
        if EGRESS == "inspect" and host not in SELF_HOSTS:
            self.send_response(200, "Connection Established"); self.end_headers(); self.close_connection = True
            try: tls = host_ctx(host).wrap_socket(self.connection, server_side=True)
            except Exception as e:   # the client refused our certificate (pinning, or it ignores the CA env): a finding
                elog({**rec, "kind": "tls", "status": None, "error": f"TLS interception failed: {type(e).__name__}: {e}"}); return
            type("Inner_" + host, (Inner,), {"target": (host, port)})(tls, self.client_address, self.server)
            return
        t0 = time.time(); up = down = 0
        try: upstream = socket.create_connection((host, port), timeout=30)
        except OSError as e:
            elog({**rec, "status": 502, "error": f"{type(e).__name__}: {e}"}); self.send_error(502, str(e)); return
        self.send_response(200, "Connection Established"); self.end_headers(); self.close_connection = True
        client = self.connection; client.setblocking(True)
        try:
            while True:
                r, _, _ = select.select([client, upstream], [], [], 600)
                if not r: break
                done = False
                for s in r:
                    data = s.recv(65536)
                    if not data: done = True; break
                    if s is client: upstream.sendall(data); up += len(data)
                    else: client.sendall(data); down += len(data)
                if done: break
        except OSError: pass
        finally:
            upstream.close()
            elog({**rec, "status": 200, "bytes_up": up, "bytes_down": down, "ms": int((time.time() - t0) * 1000)})


# ----------------------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a): pass  # our own log line per call instead

    def _send(self, code, obj=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_stream(self, gen, ctype="text/event-stream"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for piece in gen:
            b = piece.encode()
            self.wfile.write(f"{len(b):x}\r\n".encode() + b + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/health": return self._send(200, {"ok": True, "model": MODEL, "routes": os.environ.get("ROUTES", ""), "calls": _n[0]})
        if p.endswith("/models"): return self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "proxy"}]})
        self._send(404, {"error": {"message": f"no route {p}", "type": "invalid_request_error"}})

    def do_POST(self):
        p = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        if p == "/_hr/phase":
            body = self.rfile.read(n)
            if not CONTROL_TOKEN or self.headers.get("X-HR-Token") != CONTROL_TOKEN: return self._send(403, {"error": "bad token"})
            PHASE[0] = json.loads(body or b"{}").get("phase", "agent")
            print(f"egress phase -> {PHASE[0]}", flush=True)
            return self._send(200, {"phase": PHASE[0]})
        try: body = json.loads(self.rfile.read(n) or b"{}")
        except Exception: return self._send(400, {"error": {"message": "bad json", "type": "invalid_request_error"}})
        if p.endswith("/count_tokens"):
            return self._send(200, {"input_tokens": len(json.dumps(body.get("messages", []))) // 4})
        route = "openai" if p.endswith("/chat/completions") else "anthropic" if p.endswith("/messages") else None
        if not route: return self._send(404, {"error": {"message": f"no route {p}", "type": "invalid_request_error"}})
        stream = bool(body.get("stream"))
        backend, target = route_for(body.get("model"))
        served = target or body.get("model")
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "route": route, "path": p, "model_requested": body.get("model"), "model": served,
               "backend": backend, "stream": stream, "request": body, "response": None, "usage": {}, "error": None}
        t0 = time.time()
        fixes = []
        try:
            if backend != "bedrock" and backend != route:
                raise Upstream(400, f"model '{body.get('model')}' routes to {backend}, but the harness speaks the {route} API; route it to bedrock/<id> or {route}[/<id>]")
            if route == "openai":
                if backend == "openai": full = openai_direct(body, target)
                else: full = converse_to_openai(with_retry(lambda: brt.converse(**openai_to_converse(body, served, fixes))), body)
                u = full.get("usage") or {}; rec["usage"] = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}
            else:
                full = anthropic_direct(body, target, self.headers) if backend == "anthropic" else anthropic_call(body, served, fixes)
                u = full.get("usage", {}); rec["usage"] = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")}
            if backend != "bedrock" and full.get("model"): rec["model"] = full["model"]
            if POLICY != "off":
                flags = policy.check(route, full) + policy.leaks(body, NEEDLES, LEAKED)
                if flags: rec["flags"] = flags
                if POLICY == "enforce" and any(f["source"] != "request" for f in flags):
                    new, rewrites = policy.enforce(route, full)
                    if rewrites: rec["response_original"], rec["rewrites"], full = full, rewrites, new
            rec["response"] = full
            rec["latency_ms"] = int((time.time() - t0) * 1000)
            if fixes: rec["request_fixes"] = fixes
            record(rec)
            if stream: self._send_stream(openai_stream(full, body) if route == "openai" else anthropic_stream(full))
            else: self._send(200, full)
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"; rec["latency_ms"] = int((time.time() - t0) * 1000)
            if fixes: rec["request_fixes"] = fixes
            record(rec)
            traceback.print_exc()
            code = e.code if isinstance(e, Upstream) else 400 if isinstance(e, ClientError) and "ValidationException" in str(e) else 500
            if route == "openai": self._send(code, {"error": {"message": rec["error"], "type": "server_error"}})
            else: self._send(code, {"type": "error", "error": {"type": "api_error", "message": rec["error"]}})

if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG) or ".", exist_ok=True)
    if EGRESS == "inspect": ca_setup()
    if EGRESS != "open":
        threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", EGRESS_PORT), Egress).serve_forever, daemon=True).start()
    print(f"egress on :{EGRESS_PORT}  mode={EGRESS}  policy={POLICY}  test needles={len(NEEDLES)}", flush=True)
    print(f"proxy on :{PORT}  routes={[(pat, b + '/' + (m or '<as requested>')) for pat, (b, m) in ROUTES]}  log={LOG}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
