import logging
import os
import subprocess
import sys
import time

import requests

logger = logging.getLogger(__name__)

PLEX_PRODUCT = "Plex MCP Server"
PLEX_VERSION = "1.0.0"
PLEX_CLIENT_ID = "plex-mcp-server-001"
PLEX_PINS_URL = "https://plex.tv/api/v2/pins"
PLEX_RESOURCES_URL = "https://plex.tv/api/v2/resources"
AUTH_TIMEOUT = 300
POLL_INTERVAL = 2

_HEADERS = {
    "Accept": "application/json",
    "X-Plex-Product": PLEX_PRODUCT,
    "X-Plex-Version": PLEX_VERSION,
    "X-Plex-Client-Identifier": PLEX_CLIENT_ID,
}


def _resolve_server(oauth_token: str) -> tuple[str, str] | None:
    """Exchange plex.tv OAuth token for a server-specific access token + best URL.

    Returns (server_token, server_url) or None if no owned server is found.
    Prefers a local HTTP connection over HTTPS plex.direct or relay URLs.
    """
    try:
        r = requests.get(
            PLEX_RESOURCES_URL,
            headers={**_HEADERS, "X-Plex-Token": oauth_token},
            params={"includeHttps": 1, "includeRelay": 1, "includeIPv6": 0},
            timeout=15,
        )
        r.raise_for_status()
        resources = r.json()
    except Exception as exc:
        logger.warning("Failed to fetch plex.tv resources: %s", exc)
        return None

    for res in resources:
        if not isinstance(res, dict):
            continue
        if res.get("product") != "Plex Media Server" or not res.get("owned"):
            continue
        server_token = res.get("accessToken")
        if not server_token:
            continue
        connections = res.get("connections", [])
        # Prefer local connections; within those prefer http over https
        local = [c for c in connections if c.get("local")]
        remote = [c for c in connections if not c.get("local")]
        for conn in local + remote:
            uri = conn.get("uri", "")
            # Try plain http first (strip https plex.direct to raw IP if local)
            try:
                test_r = requests.get(
                    f"{uri}/identity",
                    headers={"X-Plex-Token": server_token},
                    timeout=5,
                    verify=False,
                )
                if test_r.status_code == 200:
                    logger.info("Resolved Plex server at %s", uri)
                    return server_token, uri
            except Exception:
                continue
        logger.warning("No reachable connection found for Plex server '%s'", res.get("name"))
    return None


def validate_token(token: str, plex_url: str) -> bool:
    if not token:
        return False
    try:
        r = requests.get(
            f"{plex_url}/identity",
            headers={**_HEADERS, "X-Plex-Token": token},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as exc:
        logger.warning("Token validation error: %s", exc)
        return False


def _request_pin() -> tuple[str, str]:
    r = requests.post(PLEX_PINS_URL, headers=_HEADERS, data={"strong": "true"})
    r.raise_for_status()
    data = r.json()
    return str(data["id"]), data["code"]


def _build_auth_url(pin_code: str) -> str:
    return (
        "https://app.plex.tv/auth#?"
        f"clientID={PLEX_CLIENT_ID}"
        f"&code={pin_code}"
        "&context%5Bdevice%5D%5Bproduct%5D=Plex+MCP+Server"
    )


def _poll_for_token(pin_id: str) -> str | None:
    deadline = time.time() + AUTH_TIMEOUT
    while time.time() < deadline:
        try:
            r = requests.get(f"{PLEX_PINS_URL}/{pin_id}", headers=_HEADERS, timeout=10)
            data = r.json()
            if data.get("authToken"):
                return data["authToken"]
        except Exception as exc:
            logger.warning("Poll error: %s", exc)
        time.sleep(POLL_INTERVAL)
    return None


def _detect_display() -> str | None:
    display = os.environ.get("DISPLAY")
    if display:
        return display
    for candidate in (":0", ":1"):
        try:
            result = subprocess.run(
                ["xdpyinfo", "-display", candidate],
                capture_output=True,
                timeout=2,
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            continue
    return None


def _launch_chromium(url: str, display: str) -> subprocess.Popen:
    env = {**os.environ, "DISPLAY": display}
    for binary in ("chromium-browser", "chromium", "google-chrome", "google-chrome-stable"):
        try:
            return subprocess.Popen(
                [binary, "--new-window", url],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            continue
    raise FileNotFoundError("No Chromium/Chrome browser found on PATH")


def do_oauth_flow(config: dict) -> str:
    from config import save_config

    logger.info("Starting Plex OAuth flow")
    pin_id, pin_code = _request_pin()
    auth_url = _build_auth_url(pin_code)

    chromium_proc = None
    display = _detect_display()

    if display:
        try:
            chromium_proc = _launch_chromium(auth_url, display)
            logger.info("Browser opened for Plex authentication on display %s", display)
        except FileNotFoundError:
            logger.warning("No browser found; falling back to URL printing")
            display = None

    if not display:
        logger.info("Auth URL written to journal (no display available)")

    print(
        f"\n[PLEX AUTH] Open this URL to authenticate:\n{auth_url}\n",
        file=sys.stderr,
        flush=True,
    )

    logger.info("Waiting for Plex authentication (timeout: %ds)...", AUTH_TIMEOUT)
    token = _poll_for_token(pin_id)

    if chromium_proc:
        try:
            chromium_proc.terminate()
        except Exception:
            pass

    if not token:
        raise RuntimeError("Plex OAuth timed out — no token received within 5 minutes")

    logger.info("Plex token received and stored: [REDACTED]")
    config["token"] = token
    save_config(config)
    return token


def ensure_token(config: dict) -> str:
    from config import get_plex_url, save_config

    plex_url = get_plex_url(config)
    token = config.get("token")
    if token and validate_token(token, plex_url):
        logger.info("Plex token validated successfully")
        return token
    logger.info("Token missing or invalid — initiating OAuth flow")
    oauth_token = do_oauth_flow(config)
    resolved = _resolve_server(oauth_token)
    if resolved:
        server_token, server_url = resolved
        config["token"] = server_token
        config["plex_url"] = server_url
        save_config(config)
        logger.info("Stored server-specific token and URL: %s", server_url)
        return server_token
    return oauth_token
