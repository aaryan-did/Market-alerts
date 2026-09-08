# VIX Lookout Alert

A minimal, free, personal alert that pings your phone the moment the VIX
(CBOE Volatility Index -- the market's "fear gauge") crosses above 20.
Nothing else -- no news feeds, no digest, no index-move tracking. Just
this one lookout.

| VIX Level | Sentiment | What Investors Usually Do |
|---|---|---|
| Below 15 | Complacency / Calm | Standard automated investing; accumulate cash on the side. |
| 15 to 25 | Typical Market Noise | Normal pullbacks. Some long-term investors start nibbling. |
| 25 to 35 | High Fear | Heavy buying: severe corrections/shocks, historically strong long-term entry points. |
| Above 35 | Absolute Panic | All-in / max deployment -- reserved for rare crises (2008, 2020, Aug 2024). |

## How it works

- `alerts.py` fetches VIX's latest daily close from Yahoo Finance's free
  public chart API (no key needed) and sends a push via
  [ntfy.sh](https://ntfy.sh) (free, no account needed) if VIX has just
  crossed above 20.
- It only fires **once per crossing** -- it won't re-alert every 30
  minutes while VIX stays elevated. It resets automatically once VIX
  drops back under 20, so a future spike will alert again.
- `.github/workflows/vix-alert.yml` runs it every 30 minutes on GitHub's
  servers, for free, even when your computer is off.
- `seen.json` stores one flag (whether VIX is currently above threshold)
  and gets committed back to the repo after each run.

## Setup

### 1. ntfy topic
If you already have an ntfy topic from a previous alert tool, you can
reuse it, or pick a new private one at [ntfy.sh](https://ntfy.sh) /
the ntfy app.

### 2. Create the repo
Create a new (private is fine) GitHub repo and upload these three files,
keeping the folder structure:
```
alerts.py
seen.json
.github/workflows/vix-alert.yml
```

### 3. Add your ntfy topic as a secret
In the repo: **Settings -> Secrets and variables -> Actions -> New
repository secret**
- Name: `NTFY_TOPIC`
- Value: your topic name (just the word, not the full URL)

### 4. Trigger a run
Go to the **Actions** tab -> **VIX Lookout Alert** -> **Run workflow**.
Check the log: it'll print the current VIX level. If VIX happens to
already be above 20 right now, you'll get an alert immediately -- that's
correct behavior, not a bug (unlike a news feed, there's no backlog to
silence on the first run).

From then on, it checks every 30 minutes and stays quiet unless VIX
crosses the line.

## Changing the threshold

Edit `VIX_ALERT_THRESHOLD = 20.0` near the top of `alerts.py` to whatever
level you want to be alerted at.
