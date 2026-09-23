#!/usr/bin/env python3
"""proxy.py — sits between the harness and the model and records every call.

Harness side:  POST /v1/chat/completions  (OpenAI shape)        POST /v1/messages  (Anthropic shape)
               GET  /v1/models            GET /health           POST /v1/messages/count_tokens
Model side:    Bedrock (boto3), model id from $MODEL ("bedrock/" prefix tolerated). Whatever model name the
               harness sends is recorded and replaced. The harness never holds cloud credentials.
Record:        one JSON line per call in $LOG: n, ts, route, latency_ms, model_requested, request, response,
               usage, stream, error. `stream: true` requests are answered with a synthesized event stream.
"""
import json, os, sys, time, uuid, threading, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import boto3
from botocore.exceptions import ClientError

MODEL = os.environ["MODEL"].removeprefix("bedrock/")
LOG = os.environ.get("LOG", "/out/calls.jsonl")
PORT = int(os.environ.get("PORT", "4000"))
brt = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_lock = threading.Lock()
_n = [0]


def record(rec):
    with _lock:
        _n[0] += 1
        rec["n"] = _n[0]
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
    print(f"[{rec['n']:3d}] {rec['route']:9s} {rec.get('latency_ms', 0):6d}ms  in={rec['usage'].get('input_tokens')} out={rec['usage'].get('output_tokens')}"
          + (f"  ERROR {rec['error'][:120]}" if rec.get("error") else ""), flush=True)


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


def openai_to_converse(body):
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
    kw = {"modelId": MODEL, "messages": msgs}
    if system: kw["system"] = system
    inf = {"maxTokens": int(body.get("max_completion_tokens") or body.get("max_tokens") or 4096)}
    if body.get("temperature") is not None: inf["temperature"] = float(body["temperature"])
    if body.get("top_p") is not None: inf["topP"] = float(body["top_p"])
    stop = body.get("stop")
    if stop: inf["stopSequences"] = [stop] if isinstance(stop, str) else list(stop)[:4]
    kw["inferenceConfig"] = inf
    tools = [t for t in body.get("tools") or [] if t.get("type", "function") == "function"]
    choice = body.get("tool_choice")
    if tools and choice != "none":
        specs = []
        for t in tools:
            f = t.get("function", t)
            schema = f.get("parameters") or {"type": "object", "properties": {}}
            if schema.get("type") != "object": schema = {"type": "object", "properties": {}}
            specs.append({"toolSpec": {"name": f["name"], "description": (f.get("description") or f["name"])[:2000], "inputSchema": {"json": schema}}})
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
            "model": body.get("model", MODEL),
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
def anthropic_call(body):
    b = {k: v for k, v in body.items() if k not in ("model", "stream", "metadata", "service_tier", "betas")}
    b["anthropic_version"] = "bedrock-2023-05-31"
    b.setdefault("max_tokens", 4096)
    r = with_retry(lambda: brt.invoke_model(modelId=MODEL, body=json.dumps(b), contentType="application/json", accept="application/json"))
    resp = json.loads(r["body"].read())
    resp["model"] = body.get("model", MODEL)
    return resp


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
        if p == "/health": return self._send(200, {"ok": True, "model": MODEL, "calls": _n[0]})
        if p.endswith("/models"): return self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "proxy"}]})
        self._send(404, {"error": {"message": f"no route {p}", "type": "invalid_request_error"}})

    def do_POST(self):
        p = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        try: body = json.loads(self.rfile.read(n) or b"{}")
        except Exception: return self._send(400, {"error": {"message": "bad json", "type": "invalid_request_error"}})
        if p.endswith("/count_tokens"):
            return self._send(200, {"input_tokens": len(json.dumps(body.get("messages", []))) // 4})
        route = "openai" if p.endswith("/chat/completions") else "anthropic" if p.endswith("/messages") else None
        if not route: return self._send(404, {"error": {"message": f"no route {p}", "type": "invalid_request_error"}})
        stream = bool(body.get("stream"))
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "route": route, "path": p, "model_requested": body.get("model"), "model": MODEL,
               "stream": stream, "request": body, "response": None, "usage": {}, "error": None}
        t0 = time.time()
        try:
            if route == "openai":
                kw = openai_to_converse(body)
                resp = with_retry(lambda: brt.converse(**kw))
                full = converse_to_openai(resp, body)
                u = full["usage"]; rec["usage"] = {"input_tokens": u["prompt_tokens"], "output_tokens": u["completion_tokens"]}
            else:
                full = anthropic_call(body)
                u = full.get("usage", {}); rec["usage"] = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")}
            rec["response"] = full
            rec["latency_ms"] = int((time.time() - t0) * 1000)
            record(rec)
            if stream: self._send_stream(openai_stream(full, body) if route == "openai" else anthropic_stream(full))
            else: self._send(200, full)
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"; rec["latency_ms"] = int((time.time() - t0) * 1000)
            record(rec)
            traceback.print_exc()
            code = 400 if isinstance(e, ClientError) and "ValidationException" in str(e) else 500
            if route == "openai": self._send(code, {"error": {"message": rec["error"], "type": "server_error"}})
            else: self._send(code, {"type": "error", "error": {"type": "api_error", "message": rec["error"]}})


if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG) or ".", exist_ok=True)
    print(f"proxy on :{PORT}  model={MODEL}  log={LOG}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
