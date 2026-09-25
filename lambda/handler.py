#!/usr/bin/env python3
"""handler.py — serve.py on a Lambda function URL.

The site's API is the same `serve.py` that runs on the laptop.  Nothing here reimplements a route:
the event is turned back into the bytes of an HTTP request, `serve.H` answers it exactly as it
answers a socket, and the bytes it wrote become the Lambda response.  One routing table, one set of
behaviours, and `python3 serve.py` stays the way to reproduce anything this returns.

    event (function url, payload 2.0)  ->  raw HTTP/1.1 request  ->  serve.H  ->  raw response  ->  event

Three things differ from the laptop and all three are environment, not code:

    HR_SESSIONS=ddb    sessions are rows in the run store; Lambda has no disk to share between
                       instances, and .auth/sessions.json would be read-only anyway
    HR_EVALS=off       POST /api/evals starts run.sh, which needs a Docker daemon.  It comes back
                       with the run plane (RUN-PLANE.md); until then it answers 503, not a traceback
    HR_PUBLIC_HOST     CloudFront cannot forward the viewer's Host header to a function url origin,
                       so the host is configured.  The edge function 301s www to the apex, which is
                       what makes one configured value correct for every request

boto3 is used for exactly one thing — reading the SecureStrings at cold start — and it is in the
runtime, so the repo's "python3 and nothing else" promise still holds for every file it imports.
"""
import base64, hmac, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC_HOST = os.environ.get("HR_PUBLIC_HOST", "")
ORIGIN_SECRET = os.environ.get("HR_ORIGIN_SECRET", "")


def _secrets():
    """The GitHub client secret, the session secret and the app's .pem, out of Parameter Store and
    into the environment — before serve.py is imported, because auth.py reads its env at import.

    A parameter still holding the placeholder Terraform created it with is left unset, so a stack
    whose secrets have not been filled in serves the runs read-only instead of failing to boot."""
    prefix = os.environ.get("HR_SECRET_PREFIX", "")
    if not prefix: return
    import boto3
    ssm = boto3.client("ssm")
    page = ssm.get_paginator("get_parameters_by_path")
    for batch in page.paginate(Path=prefix, WithDecryption=True):
        for p in batch.get("Parameters", []):
            name, value = p["Name"].rsplit("/", 1)[1], p["Value"]
            if not value or value == "unset": continue
            if name == "GITHUB_APP_KEY":
                # auth.py signs the app JWT by shelling out to openssl, so the key has to be a file.
                path = "/tmp/github-app.pem"
                with open(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
                    f.write(value if value.endswith("\n") else value + "\n")
                os.environ[name] = path
            else:
                os.environ[name] = value


_secrets()

sys.path.insert(0, HERE)
import serve  # noqa: E402  — after _secrets(), on purpose


class Request(serve.H):
    """serve.H against two BytesIO buffers instead of a socket.

    BaseHTTPRequestHandler.__init__ is setup/handle/finish over self.connection; none of that has
    anything to do with routing, so it is skipped and handle_one_request is called directly."""

    # HEAD is answered by the same code as GET; the body is dropped when the response is built.
    do_HEAD = serve.H.do_GET

    def __init__(self, raw, peer):
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.client_address = (peer, 0)
        self.connection = self.request = self.server = None
        self.directory = serve.DIST
        self.handle_one_request()

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.client_address[0], fmt % a))


def _request_bytes(event):
    """The event as the bytes a socket would have delivered."""
    http = event["requestContext"]["http"]
    target = event.get("rawPath") or "/"
    if event.get("rawQueryString"): target += "?" + event["rawQueryString"]

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    headers.pop("x-hr-origin", None)

    # Payload 2.0 lifts cookies out of the headers and into their own list.
    if event.get("cookies"): headers["cookie"] = "; ".join(event["cookies"])

    body = event.get("body") or ""
    body = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()

    # The Host the viewer asked for, not the function url's own name.  serve.py compares Origin
    # against it on POST, and CloudFront never forwards it to this kind of origin.
    headers["host"] = PUBLIC_HOST or headers.get("host", "")
    headers["content-length"] = str(len(body))

    head = f"{http['method']} {target} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    return head.encode() + b"\r\n" + body


def _response(raw, head_only):
    """The bytes serve.H wrote, as a function url response."""
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = int(lines[0].split()[1]) if lines and lines[0] else 500

    headers, cookies = {}, []
    for line in lines[1:]:
        key, _, value = line.decode("latin-1").partition(":")
        key, value = key.strip(), value.strip()
        if not key: continue
        if key.lower() == "set-cookie": cookies.append(value)
        else: headers[key] = value

    out = {"statusCode": status, "headers": headers, "isBase64Encoded": True,
           "body": base64.b64encode(b"" if head_only else body).decode()}
    if cookies: out["cookies"] = cookies
    return out


def lambda_handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    # The function url is unauthenticated; CloudFront adds this header and nothing else knows it.
    # Checked before the request is parsed, so a direct caller costs one string compare.
    if ORIGIN_SECRET and not hmac.compare_digest(headers.get("x-hr-origin", ""), ORIGIN_SECRET):
        refused = json.dumps({"error": "direct access to the origin is not allowed"}).encode()
        return {"statusCode": 403, "headers": {"Content-Type": "application/json"},
                "isBase64Encoded": True, "body": base64.b64encode(refused).decode()}

    peer = (http.get("sourceIp") or headers.get("x-forwarded-for", "-").split(",")[0]).strip()
    handled = Request(_request_bytes(event), peer or "-")
    return _response(handled.wfile.getvalue(), http.get("method") == "HEAD")
