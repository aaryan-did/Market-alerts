#!/usr/bin/env python3
"""
VIX Lookout Alert
------------------
Checks the CBOE Volatility Index (VIX) via Yahoo Finance's free public
chart API and sends a single push notification (via ntfy.sh) the moment
VIX crosses above a threshold -- a "fear gauge lookout."

It does NOT re-alert every run while VIX stays elevated. It resets once
VIX drops back below the threshold, so a future spike will alert again.

Requires no API key. Needs only the NTFY_TOPIC environment variable.
"""

import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ---- Config ----
VIX_ALERT_THRESHOLD = 20.0
STATE_FILE = "vix_seen.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            log(f"WARN: couldn't read state file, starting fresh: {e}")
    return {"vix_above_threshold": False}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_vix():
    """Returns the latest daily-close VIX value, or None on failure."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/^VIX?range=5d&interval=1d"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    result = data["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    valid = [c for c in closes if c is not None]
    if not valid:
        return None
    return valid[-1]


def zone_for(vix):
    if vix < 15:
        return "Complacency / Calm"
    elif vix < 25:
        return "Typical Market Noise"
    elif vix < 35:
        return "High Fear -- historically a heavy-buying zone"
    else:
        return "Absolute Panic -- rare crisis territory"


def send_ntfy(title, message, priority="urgent", tags=None):
    if not NTFY_TOPIC:
        log("ERROR: NTFY_TOPIC environment variable not set -- can't send notification.")
        return
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    headers = {
        "Title": title,
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)
    req = Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=15) as resp:
            resp.read()
        log(f"Sent notification: {title}")
    except (URLError, HTTPError) as e:
        log(f"ERROR: failed to send notification: {e}")


def main():
    state = load_state()

    try:
        vix = fetch_vix()
    except Exception as e:
        log(f"ERROR: VIX fetch failed: {e}")
        return 1

    if vix is None:
        log("WARN: no valid VIX data returned this run.")
        return 0

    log(f"Current VIX: {vix:.2f} (threshold: {VIX_ALERT_THRESHOLD:.0f})")

    was_above = state.get("vix_above_threshold", False)

    if vix >= VIX_ALERT_THRESHOLD and not was_above:
        state["vix_above_threshold"] = True
        zone = zone_for(vix)
        send_ntfy(
            title="👁️ VIX Lookout",
            message=f"VIX is at {vix:.1f}, crossed above {VIX_ALERT_THRESHOLD:.0f}.\nZone: {zone}",
            priority="urgent",
            tags=["eye", "chart_with_downwards_trend"],
        )
    elif vix < VIX_ALERT_THRESHOLD and was_above:
        log("VIX dropped back below threshold -- resetting, ready to alert on next spike.")
        state["vix_above_threshold"] = False
    else:
        log("No state change -- no notification sent.")

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
