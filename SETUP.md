# Setup Guide

Everything you need to do, in order. Steps 1–2 have a multi-day approval wait,
so start them first. The app runs in **demo mode with a simulated feed** the
whole time you wait — no credentials needed.

## 0. Run it right now (demo mode)

```bash
cd ~/Projects/trade-copilot
.venv/bin/python run.py
```

Open http://127.0.0.1:8000. You'll see a simulated MNQ tape with live signals —
this is for getting familiar with the dashboard, not for trading.

## 1. Open a Schwab brokerage account (~15 min)

1. Go to schwab.com → Open an Account → **Individual Brokerage**.
2. Complete the identity/application flow.
3. **No deposit needed.** Skip funding.
4. You are a **non-professional** data subscriber (trading your own money,
   not a registered advisor, not employed by a financial firm).

## 2. Register the developer app (~15 min, then 2–5 business days wait)

1. Go to **developer.schwab.com**, create a developer account
   (separate login from brokerage).
2. Create an app:
   - Add **both** API products: **Accounts and Trading Production**
     (this unlocks the real-time streamer) and **Market Data Production**
     (historical bars).
   - **Callback URL: exactly** `https://127.0.0.1:8182`
3. Submit. Check daily until the app status reads **"Ready for Use"**.

## 3. Configure credentials (~2 min)

Once the app is Ready for Use, open it in the developer portal and copy the
**App Key** and **App Secret**:

```bash
cd ~/Projects/trade-copilot
cp .env.example .env
# edit .env and paste your key + secret
```

`.env` stays on your machine (it's gitignored).

## 4. One-time account link (~2 min)

```bash
.venv/bin/python scripts/schwab_login.py
```

A browser opens → log into Schwab → click **Allow**. The token saves to
`data/schwab_token.json`.

> Schwab refresh tokens expire every ~7 days. When the feed starts failing
> auth, just re-run this script.

## 5. Go live

```bash
.venv/bin/python run.py --feed schwab
```

Open http://127.0.0.1:8000 next to NinjaTrader Web. The top bar shows the
real front-month contract (e.g. `/MNQU26`) and `schwab feed`.

## Troubleshooting

- **"No Schwab token found"** → run step 4.
- **Feed shows stale / reconnecting** → check that the market is open;
  the feed auto-reconnects with backoff. If it persists, re-run step 4.
- **No historical warm-up bars** → the engine warms itself from live data
  in ~30 minutes; signals are blocked until indicators are warm.
- **No signals all day** → check the phase chip (RTH only by default), the
  chop filter line, and the circuit breaker banner. The engine standing
  aside is a feature, not a bug.
