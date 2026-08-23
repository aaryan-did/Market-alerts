# Market Alerts

A free, personal market-news notifier. Sends priority pushes instantly for
RBA/Fed decisions, crisis-level headlines, and big index moves — and batches
everything else (general ASX/US headlines + longer "insight" reads) into a
digest a couple of times a day. Runs on GitHub Actions, so it works even when
your computer is off, and costs nothing.

## How it works

- `alerts.py` pulls a set of RSS feeds (RBA, the Fed, MarketWatch, CNBC, BBC,
  The Guardian, Yahoo Finance, ABC News Australia, plus a few finance/property
  "insight" sources and Equity Mates' daily headline), filters them, and
  pushes notifications to your phone via [ntfy.sh](https://ntfy.sh) — a free
  push-notification service that needs no account and no phone number.
- **Priority items** (RBA/Fed decisions, crisis-keyword headlines, big index
  moves) are pushed the moment they're found — the workflow checks every 30
  minutes, so worst case there's a 30-minute delay.
- **Everything else** is queued quietly and only sent as a batched digest
  notification at ~6:30am, a ~7:00am catch-up (only fires if something was
  genuinely still missing — e.g. Equity Mates posted a few minutes late),
  and ~6:00pm Sydney time (`DIGEST_SEND_TIMES_UTC` in `alerts.py`) — so it's
  two predictable pushes a day in the normal case, not a stream.
- `.github/workflows/market-alerts.yml` runs the script every 30 minutes on
  GitHub's servers, all day, checking priority items each time and only
  flushing the digest at the two configured times.
- `seen.json` keeps track of what's already been sent (and what's queued but
  not yet sent), so nothing repeats. The workflow commits it back to the
  repo after every run.
- **First run is special:** with an empty `seen.json`, the script silently
  records every existing item from every feed without sending a single
  notification — otherwise the first run would fire off years of old Fed
  press releases as "urgent" alerts all at once. Only items that appear
  *after* that first run will ever trigger a notification.

## Setup (about 10 minutes)

### 1. Install ntfy and pick a topic
1. Install the **ntfy** app: [iOS](https://apps.apple.com/app/ntfy/id1625396347) /
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) /
   or just use [ntfy.sh](https://ntfy.sh) in a browser.
2. Pick a private, hard-to-guess topic name — e.g. `jamie-market-alerts-8821`.
   Anyone who knows this name can see your alerts, so don't make it guessable
   and don't share it.
3. In the app, tap **+** and subscribe to that exact topic name.

### 2. Create the GitHub repo
1. Create a new **private** GitHub repository (e.g. `market-alerts`).
2. Upload all the files from this folder to it (keep the folder structure —
   `.github/workflows/market-alerts.yml` must stay in that exact path).

### 3. Add your topic as a secret
1. In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `NTFY_TOPIC`. Value: the topic name you picked in step 1.

### 4. Turn it on
1. Go to the **Actions** tab of your repo → you should see the "Market Alerts" workflow.
2. Click **Run workflow** to trigger it manually and confirm it works —
   check the run log, and check your phone for a digest notification if
   there was anything new.
3. After that, it runs automatically every 30 minutes.

## Customising

Everything you'd want to tweak is at the top of `alerts.py`:

- **`MARKET_NEWS_FEEDS`** / **`INSIGHT_FEEDS`** — add or remove RSS feeds.
  Any standard RSS/Atom feed URL works.
- **`CRISIS_KEYWORDS`** — words/phrases that trigger an instant push instead
  of waiting for the digest.
- **`INDEX_CHECKS`** — which indices to watch and the % move threshold.
- **`MAX_DIGEST_ITEMS_PER_SOURCE`** — cap on how many headlines per source
  go into one digest, so one noisy feed doesn't drown out the rest.

If you later want specific tickers (not just ASX/US market-wide), add a
`WATCHLIST` list of names/tickers and a check similar to `is_crisis_headline`
that scans for them — happy to add that for you if you want it now instead.

## Reading in Flipboard

If Flipboard is your preferred reader (and you're subscribed, so paywalls
aren't a problem), you can pull these same sources into a personal Flipboard
magazine and read everything there instead of tapping through from the
notification:

1. In Flipboard: **Search → paste an RSS URL** (or use "Add to Flipboard" if
   you have the browser extension) for each feed below.
2. Add them all to one magazine, e.g. "My Market Feed".

| Source | RSS URL |
|---|---|
| RBA Media Releases | `https://www.rba.gov.au/rss/rss-cb-media-releases.xml` |
| Fed — Monetary Policy | `https://www.federalreserve.gov/feeds/press_monetary.xml` |
| Fed — All Press Releases | `https://www.federalreserve.gov/feeds/press_all.xml` |
| Yahoo Finance | `https://finance.yahoo.com/news/rssindex` |
| MarketWatch | `https://feeds.content.dowjones.io/public/rss/mw_topstories` |
| CNBC Markets | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258` |
| BBC Business | `http://feeds.bbci.co.uk/news/business/rss.xml` |
| The Guardian Business | `https://www.theguardian.com/uk/business/rss` |
| ABC News Australia (Business) | `https://www.abc.net.au/news/feed/51892/rss.xml` |
| Motley Fool Australia | `https://www.fool.com.au/feed/` |
| Livewire Markets | `https://www.livewiremarkets.com/feeds/all.rss` |
| Firstlinks | `https://www.firstlinks.com.au/rss` |
| A Wealth of Common Sense | `https://awealthofcommonsense.com/feed/` |
| Of Dollars and Data | `https://ofdollarsanddata.com/feed/` |

This gives you the same coverage as the script, but browsable in Flipboard's
UI whenever you want to sit down and read rather than react to a push. It's
now deliberately all free/open-access outlets, so nothing here ever prompts
for a login or subscription.

## Notes on sources

- **RBA** and **Fed** feeds are official and always free.
- News-outlet feeds (Yahoo Finance, MarketWatch, CNBC, BBC, The Guardian,
  ABC News Australia) are all free/open-access — every link a notification
  sends will just open, with no login or subscription prompt. This was a
  deliberate choice: no paywalled outlets are included, so there's nothing
  that can fail or confuse whoever's reading the notifications.
- **Equity Mates** doesn't publish an RSS feed (beehiiv, the platform they're
  on, doesn't support one), so the script reads their public post-archive
  page directly instead and pulls the latest headline + link from there.
  It's their own free, public page — same idea as RSS, just read as a normal
  webpage. If beehiiv ever redesigns that page, this is the piece most
  likely to need updating (look for a `WARN: Equity Mates archive fetch
  failed` line in the Actions log).
- RSS feed URLs occasionally change or go stale. If a source stops showing
  up in your digest, check the Actions log for a `WARN:` line naming it —
  that means the feed needs updating.
