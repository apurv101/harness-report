#!/usr/bin/env python3
"""The operator's console: a local page over the live AWS account, never deployed.

    AWS_PROFILE=operator python3 admin/serve.py      # http://127.0.0.1:8790

It binds to loopback and holds no secret of its own — every read is signed with the laptop's operator keys, so
there is no admin surface on harnessreport.com to protect.  Pages so far:

  Visits  every request CloudFront answered (infra/logs.tf), read with CloudWatch Logs Insights.

Stdlib only, like serve.py: the signer is lib/ddb.sigv4.
"""
import concurrent.futures
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
os.environ.setdefault("AWS_PROFILE", "operator")
import ddb  # noqa: E402

PORT = int(os.environ.get("HR_ADMIN_PORT", "8790"))
LOG_GROUP = os.environ.get("HR_VISIT_LOG_GROUP", "/harness-report/cloudfront")
LOG_REGION = "us-east-1"  # CloudFront's vended logs are delivered here whatever region the stack is in

# CloudFront's field names carry dashes and parentheses, which Insights only accepts in backticks.  Renamed once
# here so the page and every query below speak plain names.
FIELDS = {
    "ip": "c-ip", "country": "c-country", "method": "cs-method", "path": "cs-uri-stem", "query": "cs-uri-query",
    "status": "sc-status", "referer": "cs(Referer)", "agent": "cs(User-Agent)", "edge": "x-edge-location",
    "result": "x-edge-result-type", "bytes": "sc-bytes", "seconds": "time-taken", "host": "x-host-header", "asn": "asn",
    "protocol": "cs-protocol-version", "request_id": "x-edge-request-id",
}
PARSE = "fields @timestamp as time, " + ", ".join(f"`{src}` as {name}" for name, src in FIELDS.items())

# Not a visitor: crawlers, uptime checks, scripts.  Deliberately loose; the page says "bots hidden", not "humans".
BOT = r"/(?i)(bot|crawl|spider|slurp|curl|wget|python|go-http|httpclient|okhttp|headless|lighthouse|monitor|preview|facebookexternalhit|scan|axios|node-fetch|java\/|libwww)/"
# Hits that are part of a page rather than a page: the SPA shell's assets, icons, and the API it calls.
ASSET = r"/^\/(assets\/|favicon|robots\.txt|sitemap|site\.webmanifest|.*\.(js|css|png|jpg|jpeg|svg|ico|woff2?|map|webp|txt|xml)$)/"
API = r"/^\/(api|auth|raw|mcp)\b/"


# ---------------------------------------------------------------- CloudWatch Logs
def logs(op, payload):
    body = json.dumps(payload).encode()
    key, secret, token = ddb.real_credentials()
    host = f"logs.{LOG_REGION}.amazonaws.com"
    headers = ddb.sigv4(host, "logs", f"Logs_20140328.{op}", body, key, secret, token,
                        region_name=LOG_REGION, content_type="application/x-amz-json-1.1")
    req = urllib.request.Request(f"https://{host}/", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read() or b"{}")
        raise RuntimeError(f"{op}: {detail.get('__type', e.code)} {detail.get('message') or detail.get('Message', '')}")


def insights(query, since, until, limit=1000):
    """Run one Logs Insights query to completion and return its rows as dicts."""
    started = logs("StartQuery", {"logGroupName": LOG_GROUP, "startTime": int(since), "endTime": int(until),
                                  "queryString": query, "limit": limit})
    for _ in range(240):
        out = logs("GetQueryResults", {"queryId": started["queryId"]})
        if out["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            if out["status"] != "Complete": raise RuntimeError(f"query {out['status'].lower()}: {query}")
            return [{c["field"]: c["value"] for c in row if not c["field"].startswith("@ptr")}
                    for row in out.get("results", [])]
        time.sleep(0.4)
    raise RuntimeError("query did not finish in 100 s")


def where(params):
    """The filter lines every query shares, from the page's toggles and drill-downs."""
    lines = []
    if params.get("bots") != "1": lines.append(f"filter not isblank(agent) and agent not like {BOT}")
    view = params.get("view", "pages")
    if view == "pages": lines.append(f"filter path not like {ASSET} and path not like {API}")
    elif view == "api": lines.append(f"filter path like {API}")
    for name in ("ip", "path", "country", "referer", "agent", "asn"):
        if params.get(name):
            lines.append(f"filter {name} = {json.dumps(params[name])}")
    return "\n| ".join([PARSE] + lines)


def window(params):
    until = int(time.time())
    return until - int(float(params.get("hours", "24")) * 3600), until


def bucket(hours):
    return "5m" if hours <= 6 else "1h" if hours <= 72 else "1d"


STEP = {"5m": 300, "1h": 3600, "1d": 86400}


def fill(rows, since, until, size):
    """Insights returns only the buckets that had traffic; the chart needs the quiet ones too or its x axis lies."""
    seen = {r["t"][:19]: r for r in rows}
    step = STEP[size]
    out, t = [], since - since % step
    while t <= until:
        key = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))
        out.append(seen.get(key) or {"t": key, "requests": "0", "visitors": "0"})
        t += step
    return out


def summary(params):
    since, until = window(params)
    base = where(params)
    queries = {
        "totals": f"{base} | stats count(*) as requests, count_distinct(ip) as visitors, "
                  f"count_distinct(country) as countries, count_distinct(path) as paths",
        "timeline": f"{base} | stats count(*) as requests, count_distinct(ip) as visitors "
                    f"by bin({bucket((until - since) / 3600)}) as t | sort t asc",
        "ips": f"{base} | stats count(*) as requests, count_distinct(path) as paths, min(@timestamp) as first, "
               f"max(@timestamp) as last, latest(country) as ip_country, latest(asn) as ip_asn, latest(agent) as ip_agent by ip "
               f"| sort requests desc | limit 100",
        "paths": f"{base} | stats count(*) as requests, count_distinct(ip) as visitors by path "
                 f"| sort requests desc | limit 50",
        "referers": f"{base} | filter referer != '-' and referer not like /harnessreport\\.com/ "
                    f"| stats count(*) as requests, count_distinct(ip) as visitors by referer "
                    f"| sort requests desc | limit 30",
        "countries": f"{base} | stats count(*) as requests, count_distinct(ip) as visitors by country "
                     f"| sort visitors desc | limit 60",
        "statuses": f"{base} | stats count(*) as requests by status | sort requests desc",
    }
    with concurrent.futures.ThreadPoolExecutor(len(queries)) as pool:
        futures = {k: pool.submit(insights, q, since, until) for k, q in queries.items()}
        out = {k: f.result() for k, f in futures.items()}
    out["totals"] = out["totals"][0] if out["totals"] else {}
    size = bucket((until - since) / 3600)
    out["timeline"] = fill(out["timeline"], since, until, size)
    out["window"] = {"since": since, "until": until, "bucket": size}
    return out


def requests_log(params):
    since, until = window(params)
    rows = insights(f"{where(params)} | sort @timestamp desc | limit 1000", since, until)
    return {"rows": rows}


_names = {}


def reverse_dns(ips):
    """Hostnames for addresses, looked up from this laptop and cached for the life of the process.  Nothing is
    sent to a third party: this is the same PTR lookup `host <ip>` does."""
    def one(ip):
        if ip not in _names:
            try: _names[ip] = socket.gethostbyaddr(ip)[0]
            except OSError: _names[ip] = None
        return ip, _names[ip]
    socket.setdefaulttimeout(2)
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        return dict(pool.map(one, ips[:200]))


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a): sys.stderr.write("admin %s\n" % (fmt % a))

    def send(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        params = dict(urllib.parse.parse_qsl(url.query))
        routes = {
            "/api/visits/summary": lambda: summary(params),
            "/api/visits/requests": lambda: requests_log(params),
            "/api/rdns": lambda: reverse_dns([ip for ip in params.get("ips", "").split(",") if ip]),
            "/api/whoami": lambda: {"profile": os.environ.get("AWS_PROFILE"), "log_group": LOG_GROUP,
                                    "region": LOG_REGION},
        }
        if url.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if url.path not in routes: return self.send(404, {"error": "not found"})
        try:
            self.send(200, routes[url.path]())
        except Exception as e:  # the page shows the AWS error verbatim; this is a console, not a product
            self.send(502, {"error": str(e)})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"admin: http://127.0.0.1:{PORT}  (AWS_PROFILE={os.environ['AWS_PROFILE']}, {LOG_GROUP} in {LOG_REGION})")
    server.serve_forever()
