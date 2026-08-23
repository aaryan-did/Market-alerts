#!/usr/bin/env python3
"""
Personal market alert bot.

Pulls RBA / Fed announcements, ASX + US market headlines, and a curated set
of "insightful reads" (finance + property, AU + global). Sends:
  - PRIORITY pushes instantly for rate decisions, crisis-keyword headlines,
    and big index moves.
  - A batched DIGEST push (everything else) at most twice a run-schedule,
    so you don't get bombarded.

Delivery is via ntfy.sh (free, no account, no phone number needed).
State (which articles have already been sent) is kept in seen.json so the
same headline never fires twice.

Edit the CONFIG section below to add/remove sources, tickers, or keywords.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request

import feedparser
from bs4 import BeautifulSoup

# ============================== CONFIG ======================================

# --- ntfy.sh delivery ---
# Install the ntfy app (iOS/Android/desktop) and subscribe to this exact topic.
# Treat the topic name like a shared secret -- anyone who knows it can see
# your notifications. Set it as the NTFY_TOPIC secret in your GitHub repo.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "CHANGE-ME-jamies-market-alerts-8821")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# --- Priority sources: always sent instantly, never batched ---
# Deliberately just the Monetary Policy feed, not "All Press Releases" --
# the all-press feed includes routine enforcement actions, staff
# appointments, etc. that aren't actually rate-decision-relevant and would
# just be noise here.
RATE_DECISION_FEEDS = {
    "RBA": "https://www.rba.gov.au/rss/rss-cb-media-releases.xml",
    "Fed (Monetary Policy)": "https://www.federalreserve.gov/feeds/press_monetary.xml",
}

# --- General market headlines (ASX + US): filtered for crisis keywords
#     (instant) vs everything else (digest).
#     Deliberately all free/open-access outlets -- no paywalls, so every
#     link always just opens. No login, no subscription check, ever. ---
MARKET_NEWS_FEEDS = {
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "CNBC Markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "BBC Business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "The Guardian Business": "https://www.theguardian.com/uk/business/rss",
    "ABC News Australia (Business)": "https://www.abc.net.au/news/feed/51892/rss.xml",
}

# --- "Insightful reads" -- longer-form finance + property, AU + global.
#     Always digest, never priority. Swap these out for whatever you like. ---
INSIGHT_FEEDS = {
    "Motley Fool Australia": "https://www.fool.com.au/feed/",
    "Livewire Markets": "https://www.livewiremarkets.com/feeds/all.rss",
    "Firstlinks": "https://www.firstlinks.com.au/rss",
    "A Wealth of Common Sense": "https://awealthofcommonsense.com/feed/",
    "Of Dollars and Data": "https://ofdollarsanddata.com/feed/",
}

# --- Equity Mates daily newsletter -- their site is beehiiv-hosted, which
#     doesn't publish a real RSS feed, but their post archive page is fully
#     public (no login/paywall), so we read the latest post straight off it. ---
EQUITYMATES_ARCHIVE_URL = "https://equitymates.beehiiv.com/"

# --- Crisis keywords: any headline (from ANY feed) matching these fires
#     immediately instead of waiting for the digest. Case-insensitive. ---
CRISIS_KEYWORDS = [
    "recession", "market crash", "plunge", "plunges", "sell-off", "selloff",
    "bank collapse", "bank failure", "bailout", "contagion", "default",
    "credit downgrade", "downgraded", "circuit breaker", "emergency rate",
    "black swan", "systemic risk", "bank run", "liquidity crisis",
    "war", "invasion", "sanctions", "oil shock", "supply shock",
    "inflation surge", "hyperinflation", "currency crisis", "debt crisis",
]

# --- Index-move check (via Stooq, free, no key) ---
# symbol -> (Stooq ticker, friendly name, % move threshold)
INDEX_CHECKS = [
    ("^spx", "S&P 500", 2.0),
    ("^ndq", "Nasdaq", 2.0),
    ("^dji", "Dow Jones", 2.0),
    ("^axjo", "ASX 200", 2.0),
]

STATE_FILE = Path(__file__).parent / "seen.json"
MAX_DIGEST_ITEMS_PER_SOURCE = 6

# --- Digest batching ---
# The digest is NOT sent every run. New non-priority items are queued in
# seen.json's "pending_digest", and only actually sent (as one notification)
# when the workflow runs at one of these UTC times. Priority items (rate
# decisions, crisis keywords, index moves) still go out instantly, every run.
#
# Defaults below aim for ~6:30am, a ~7:00am catch-up (in case something --
# like Equity Mates' post -- was still a few minutes late for the first
# check), and ~6:00pm Sydney time (AEST, UTC+10). The catch-up is a safe
# no-op if there's nothing new: it only sends if something's actually
# waiting, so it won't duplicate the 6:30am digest.
#
# NOTE: Sydney shifts to AEDT (UTC+11) for daylight saving (roughly
# Oct-Apr) -- during that period these will land about an hour earlier
# Sydney time. Adjust if that matters to you.
DIGEST_SEND_TIMES_UTC = ["20:30", "21:00", "08:00"]

# ============================================================================


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def load_state():
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            state.setdefault("pending_digest", {})
            return state
        except json.JSONDecodeError:
            pass
    return {"seen_ids": [], "last_index_check": {}, "pending_digest": {}}


def save_state(state):
    # Keep the seen-list from growing forever
    state["seen_ids"] = state["seen_ids"][-2000:]
    STATE_FILE.write_text(json.dumps(state, indent=2))


def entry_id(source, entry):
    return f"{source}:{entry.get('id') or entry.get('link') or entry.get('title')}"


def is_crisis_headline(title, summary=""):
    text = f"{title} {summary}".lower()
    return any(kw in text for kw in CRISIS_KEYWORDS)


def fetch_feed(name, url):
    try:
        parsed = feedparser.parse(url)
        if parsed.bozo and not parsed.entries:
            log(f"WARN: '{name}' feed failed to parse ({url})")
            return []
        return parsed.entries
    except Exception as e:
        log(f"WARN: '{name}' feed error: {e}")
        return []


def fetch_equitymates_latest():
    """Read the latest post straight off Equity Mates' public archive page.
    No RSS feed exists for beehiiv publications, but the archive itself is
    a normal public webpage -- this just reads it, same as a browser would.
    Returns (title, link) or None if it can't find one."""
    try:
        req = Request(EQUITYMATES_ARCHIVE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            html = resp.read()
        soup = BeautifulSoup(html, "html.parser")
        link_tag = soup.find("a", href=re.compile(r"^https://equitymates\.beehiiv\.com/p/"))
        if not link_tag:
            return None
        title = link_tag.get_text(strip=True)
        link = link_tag["href"]
        if not title:
            return None
        return title, link
    except Exception as e:
        log(f"WARN: Equity Mates archive fetch failed: {e}")
        return None


def send_ntfy(title, message, priority="default", tags=None, click_url=None):
    if NTFY_TOPIC.startswith("CHANGE-ME"):
        log("NTFY_TOPIC not configured -- skipping send. Message was:")
        log(f"  {title}\n  {message}")
        return
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)
    if click_url:
        headers["Click"] = click_url
    req = Request(NTFY_URL, data=message.encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=15) as resp:
            resp.read()
        log(f"Sent: {title}")
    except Exception as e:
        log(f"ERROR sending ntfy notification: {e}")
    time.sleep(1)  # be gentle, avoid rate limiting if several fire at once


def check_index_moves(state):
    """Free, no-key daily % change check via Stooq CSV endpoint."""
    alerts = []
    for symbol, name, threshold in INDEX_CHECKS:
        try:
            url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as resp:
                lines = resp.read().decode("utf-8").strip().splitlines()
            if len(lines) < 3:
                continue
            # CSV: Date,Open,High,Low,Close,Volume -- last two rows
            last = lines[-1].split(",")
            prev = lines[-2].split(",")
            last_close = float(last[4])
            prev_close = float(prev[4])
            pct = (last_close - prev_close) / prev_close * 100
            key = f"{symbol}:{last[0]}"
            if abs(pct) >= threshold and state["last_index_check"].get(symbol) != key:
                direction = "up" if pct > 0 else "down"
                alerts.append(
                    f"{name} is {direction} {abs(pct):.1f}% (close {last_close:,.1f} on {last[0]})"
                )
                state["last_index_check"][symbol] = key
        except Exception as e:
            log(f"WARN: index check failed for {name}: {e}")
    return alerts


def main():
    state = load_state()
    seen = set(state["seen_ids"])
    first_run = len(seen) == 0  # nothing recorded yet -- this is a cold start
    if first_run:
        log("First run detected: seeding known items silently, no alerts will "
            "be sent this run. Future runs will only alert on genuinely new items.")
    new_seen = []

    priority_items = []   # list of (title, link, source)
    digest_items = {}     # source -> list of (title, link)

    # 1. Rate-decision feeds -- ALWAYS priority (unless this is the first run)
    for source, url in RATE_DECISION_FEEDS.items():
        for entry in fetch_feed(source, url):
            eid = entry_id(source, entry)
            if eid in seen:
                continue
            new_seen.append(eid)
            if not first_run:
                priority_items.append((entry.get("title", "Untitled"), entry.get("link", ""), source))

    # 2. General market feeds -- crisis keywords go priority, rest go digest
    #    (nothing is sent on the first run -- see note above)
    for source, url in MARKET_NEWS_FEEDS.items():
        count = 0
        for entry in fetch_feed(source, url):
            eid = entry_id(source, entry)
            if eid in seen:
                continue
            new_seen.append(eid)
            if first_run:
                continue
            title = entry.get("title", "Untitled")
            link = entry.get("link", "")
            summary = entry.get("summary", "")
            if is_crisis_headline(title, summary):
                priority_items.append((title, link, f"{source} — important"))
            else:
                if count < MAX_DIGEST_ITEMS_PER_SOURCE:
                    digest_items.setdefault(source, []).append((title, link))
                    count += 1

    # 3. Insight/long-read feeds -- always digest (skipped on first run)
    for source, url in INSIGHT_FEEDS.items():
        count = 0
        for entry in fetch_feed(source, url):
            eid = entry_id(source, entry)
            if eid in seen:
                continue
            new_seen.append(eid)
            if first_run:
                continue
            if count < MAX_DIGEST_ITEMS_PER_SOURCE:
                digest_items.setdefault(source, []).append(
                    (entry.get("title", "Untitled"), entry.get("link", ""))
                )
                count += 1

    # 4. Equity Mates daily newsletter -- always digest, one post per run
    #    (skipped on first run)
    em_latest = fetch_equitymates_latest()
    if em_latest:
        title, link = em_latest
        eid = f"Equity Mates:{link}"
        if eid not in seen:
            new_seen.append(eid)
            if not first_run:
                digest_items.setdefault("Equity Mates Daily", []).append((title, link))

    # 5. Index-move check -- priority (skipped on first run, but the
    #    baseline close is still recorded so tomorrow's comparison works)
    index_alerts = [] if first_run else check_index_moves(state)
    if first_run:
        check_index_moves(state)  # still record today's closes as baseline, discard alerts

    # ---- Send priority notifications, one per item, immediately ----
    for title, link, source in priority_items:
        send_ntfy(
            title=f"🔴 {source}",
            message=f"{title}\n{link}",
            priority="urgent",
            tags=["rotating_light"],
            click_url=link or None,
        )

    for msg in index_alerts:
        send_ntfy(
            title="🔴 Index move",
            message=msg,
            priority="urgent",
            tags=["chart_with_upwards_trend"],
        )

    # ---- Queue digest items into pending_digest (merge with anything
    #      already waiting from earlier runs today) ----
    pending = state["pending_digest"]
    for source, items in digest_items.items():
        pending.setdefault(source, [])
        pending[source].extend([list(i) for i in items])
        pending[source] = pending[source][:MAX_DIGEST_ITEMS_PER_SOURCE]

    # ---- Only actually SEND the digest at the configured times ----
    now_hm = datetime.now(timezone.utc).strftime("%H:%M")
    if now_hm in DIGEST_SEND_TIMES_UTC:
        if pending:
            lines = []
            for source, items in pending.items():
                lines.append(f"— {source} —")
                for title, link in items:
                    lines.append(f"{title}\n{link}")
                lines.append("")
            digest_text = "\n".join(lines).strip()
            if len(digest_text) > 3800:
                digest_text = digest_text[:3800] + "\n…(truncated, more in future digests)"
            send_ntfy(
                title="📰 Market digest",
                message=digest_text,
                priority="default",
                tags=["newspaper"],
            )
            pending.clear()
        else:
            log("Digest send-time reached, but nothing new to report.")
    else:
        log(f"Not a digest send-time ({now_hm} UTC) -- queued "
            f"{sum(len(v) for v in digest_items.values())} new item(s) for later.")

    # ---- Persist state ----
    state["seen_ids"] = list(seen) + new_seen
    save_state(state)
    log(f"Done. {len(priority_items)} priority items sent, "
        f"{len(index_alerts)} index alerts, digest queue now has "
        f"{sum(len(v) for v in pending.values())} pending source-groups.")


if __name__ == "__main__":
    sys.exit(main())
