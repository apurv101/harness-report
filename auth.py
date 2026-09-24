#!/usr/bin/env python3
"""auth.py — "Sign in with GitHub" for serve.py.  No dependencies beyond python3 and openssl.

One GitHub App does both halves: the user-to-server OAuth dance identifies the person, and an
installation token (minted from the app's private key) is what clones their repositories. The
browser never sees a GitHub token: the cookie holds a signed session id, the tokens stay in
SESSIONS on the server.

    configured()                   -> False when the env is unset; serve.py then runs open (local use)
    authorize_url(state)           -> where to send the browser
    exchange(code)                 -> {login, id, name, avatar, token, refresh, exp}
    session_of(header)             -> the session dict for a Cookie: header, or None
    login(user) / logout(sid)      -> create / destroy a session, returns the Set-Cookie value
    sign(value, ttl) / unsign(s)   -> the short-lived signed state nonce (CSRF)
    installations(sess)            -> the app installations the signed-in user can see
    repositories(sess, inst_id)    -> the repositories one installation grants
    clone_token(inst_id)           -> a ~1 h installation token for `git clone`

Env (all four required before any of this turns on):
    GITHUB_CLIENT_ID      the GitHub App's client id (Iv23li...)
    GITHUB_CLIENT_SECRET  its client secret
    SESSION_SECRET        any random string; signs the cookies (`openssl rand -hex 32`)
    BASE_URL              public origin of this server, e.g. https://app.harnessreport.com
Optional, only needed to clone private repos:
    GITHUB_APP_ID         the app's numeric id
    GITHUB_APP_KEY        path to the app's .pem private key
    GITHUB_APP_SLUG       the app's url slug, so the frontend can offer "install it on a repository"
"""
import base64, hashlib, hmac, json, os, secrets, subprocess, threading, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

def _dotenv(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    """run.sh reads .env; so does this, so `python3 serve.py` needs no exports.  Real env wins."""
    try: lines = open(path, encoding="utf-8").read().splitlines()
    except OSError: return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_dotenv()

CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
SECRET = os.environ.get("SESSION_SECRET", "").encode()
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8789").rstrip("/")
APP_ID = os.environ.get("GITHUB_APP_ID", "")
APP_KEY = os.path.expanduser(os.environ.get("GITHUB_APP_KEY", ""))
APP_SLUG = os.environ.get("GITHUB_APP_SLUG", "")

COOKIE = "hr_session"
STATE_COOKIE = "hr_state"
SESSION_TTL = 30 * 24 * 3600            # a month; the GitHub token inside may expire sooner
STATE_TTL = 600
API = "https://api.github.com"
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".auth", "sessions.json")

SESSIONS, LOCK = {}, threading.Lock()


def configured():
    """Auth is on only when every piece is present; otherwise serve.py serves everything open."""
    return bool(CLIENT_ID and CLIENT_SECRET and SECRET and BASE_URL)


def install_url(state=""):
    """Where a signed-in user picks which repositories the app may read.  Empty until the slug is set.

    GitHub echoes `state` back to the callback from the install page exactly as it does from the
    authorize page, so the install redirect gets the same CSRF check as sign-in.  Without it the
    callback arrives with an empty state and check_state() rejects it.
    """
    if not APP_SLUG: return ""
    url = f"https://github.com/apps/{APP_SLUG}/installations/new"
    return f"{url}?{urlencode({'state': state})}" if state else url


def can_clone():
    return bool(APP_ID and APP_KEY and os.path.isfile(APP_KEY))


# ---------------------------------------------------------------- signing

def _b64(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def _unb64(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(value, ttl):
    """value.expiry.mac — a tamper-proof string safe to hand the browser."""
    body = f"{value}.{int(time.time()) + ttl}"
    return f"{body}.{_b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())}"


def unsign(signed):
    try: value, exp, mac = signed.rsplit(".", 2)
    except (AttributeError, ValueError): return None
    good = _b64(hmac.new(SECRET, f"{value}.{exp}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, good) or int(exp) < time.time(): return None
    return value


# ---------------------------------------------------------------- sessions

def _load():
    with LOCK:
        if SESSIONS: return
        try:
            with open(STORE, encoding="utf-8") as f: SESSIONS.update(json.load(f))
        except (OSError, ValueError): return
        for sid in [s for s, v in SESSIONS.items() if v.get("expires", 0) < time.time()]: SESSIONS.pop(sid)


def _save():
    os.makedirs(os.path.dirname(STORE), mode=0o700, exist_ok=True)
    tmp = STORE + ".tmp"
    with open(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(SESSIONS, f)
    os.replace(tmp, STORE)


def _cookie(name, value, ttl):
    secure = "; Secure" if BASE_URL.startswith("https://") else ""
    age = f"; Max-Age={ttl}" if ttl else "; Max-Age=0"
    return f"{name}={value}; Path=/; HttpOnly; SameSite=Lax{secure}{age}"


def state_cookie():
    """A fresh CSRF nonce: the value goes to GitHub, the signed copy goes to the browser."""
    nonce = secrets.token_urlsafe(16)
    return nonce, _cookie(STATE_COOKIE, sign(nonce, STATE_TTL), STATE_TTL)


def clear_state():
    return _cookie(STATE_COOKIE, "", 0)


def check_state(header, sent):
    """The nonce GitHub echoed back must match the signed one in the browser's cookie."""
    mine = unsign(cookies(header).get(STATE_COOKIE, ""))
    return bool(mine) and bool(sent) and hmac.compare_digest(mine, sent)


def login(user):
    _load()
    sid = secrets.token_urlsafe(32)
    with LOCK:
        SESSIONS[sid] = {**user, "expires": time.time() + SESSION_TTL}
        _save()
    return _cookie(COOKIE, sign(sid, SESSION_TTL), SESSION_TTL)


def logout(sid):
    _load()
    with LOCK:
        if SESSIONS.pop(sid, None) is not None: _save()
    return _cookie(COOKIE, "", 0)


def cookies(header):
    out = {}
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k: out[k] = v
    return out


def session_id(header):
    return unsign(cookies(header).get(COOKIE, ""))


def session_of(header):
    """The signed-in user for a request's Cookie: header, or None."""
    sid = session_id(header)
    if not sid: return None
    _load()
    sess = SESSIONS.get(sid)
    if not sess: return None
    if sess.get("expires", 0) < time.time():
        with LOCK: SESSIONS.pop(sid, None); _save()
        return None
    return sess


def public(sess):
    """What the frontend is allowed to know about the session — never the token."""
    return {k: sess.get(k) for k in ("login", "id", "name", "avatar")} if sess else None


# ---------------------------------------------------------------- github

def _api(url, token=None, method="GET", data=None, accept="application/vnd.github+json"):
    body = urlencode(data).encode() if data else None
    req = Request(url, data=body, method=method, headers={
        "Accept": accept, "User-Agent": "harness-report", "X-GitHub-Api-Version": "2022-11-28",
        **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urlopen(req, timeout=20) as r: return json.loads(r.read() or b"{}")
    except HTTPError as e:
        raise RuntimeError(f"github {url.split('github.com')[-1]} -> {e.code} {e.read()[:200].decode('utf-8', 'replace')}")


def authorize_url(state):
    return "https://github.com/login/oauth/authorize?" + urlencode(
        {"client_id": CLIENT_ID, "redirect_uri": f"{BASE_URL}/auth/callback", "state": state})


def exchange(code):
    """Authorization code -> the GitHub identity behind it, plus the user-to-server token."""
    tok = _api("https://github.com/login/oauth/access_token", method="POST", accept="application/json",
               data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": code,
                     "redirect_uri": f"{BASE_URL}/auth/callback"})
    if "access_token" not in tok: raise RuntimeError(tok.get("error_description") or tok.get("error") or "no access_token")
    me = _api(f"{API}/user", tok["access_token"])
    return {"login": me["login"], "id": me["id"], "name": me.get("name") or me["login"],
            "avatar": me.get("avatar_url"), "token": tok["access_token"], "refresh": tok.get("refresh_token"),
            "token_expires": time.time() + int(tok["expires_in"]) - 60 if tok.get("expires_in") else None}


def _fresh(sess):
    """GitHub App user tokens expire after 8 h when expiring tokens are on; refresh in place."""
    if not sess.get("token_expires") or sess["token_expires"] > time.time(): return sess["token"]
    if not sess.get("refresh"): raise RuntimeError("github token expired, sign in again")
    tok = _api("https://github.com/login/oauth/access_token", method="POST", accept="application/json",
               data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                     "grant_type": "refresh_token", "refresh_token": sess["refresh"]})
    if "access_token" not in tok: raise RuntimeError("github token expired, sign in again")
    with LOCK:
        sess.update(token=tok["access_token"], refresh=tok.get("refresh_token", sess["refresh"]),
                    token_expires=time.time() + int(tok.get("expires_in", 28800)) - 60)
        _save()
    return sess["token"]


def installations(sess):
    """Where the user has installed the app — each one is a set of repositories we may clone."""
    got = _api(f"{API}/user/installations", _fresh(sess))
    return [{"id": i["id"], "account": (i.get("account") or {}).get("login"),
             "selection": i.get("repository_selection")} for i in got.get("installations", [])]


def repositories(sess, inst_id):
    got = _api(f"{API}/user/installations/{int(inst_id)}/repositories?per_page=100", _fresh(sess))
    return [{"name": r["full_name"], "url": r["clone_url"], "private": r["private"],
             "language": r.get("language"), "description": r.get("description") or ""}
            for r in got.get("repositories", [])]


def _app_jwt():
    """RS256, signed by openssl so this file keeps its no-dependency promise."""
    now = int(time.time())
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps({"iat": now - 60, "exp": now + 540, "iss": APP_ID}, separators=(",", ":")).encode())
    p = subprocess.run(["openssl", "dgst", "-sha256", "-sign", APP_KEY],
                       input=f"{head}.{body}".encode(), capture_output=True)
    if p.returncode: raise RuntimeError(f"openssl could not sign with {APP_KEY}: {p.stderr.decode()[:200]}")
    return f"{head}.{body}.{_b64(p.stdout)}"


def clone_token(inst_id):
    """A short-lived token for `git clone https://x-access-token:<token>@github.com/owner/repo`."""
    if not can_clone(): raise RuntimeError("set GITHUB_APP_ID and GITHUB_APP_KEY to clone private repos")
    got = _api(f"{API}/app/installations/{int(inst_id)}/access_tokens", _app_jwt(), method="POST")
    return got["token"], got.get("expires_at")
