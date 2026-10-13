# Getting an ENTSO-E token, and what it unlocks

The live carbon-intensity path (`app/entsoe.py`, `USE_LIVE_DATA=true`) needs a free
ENTSO-E Transparency Platform security token. It has been tested against recorded
XML fixtures but **never against the real endpoint**, because no token has been
issued. The token is requested by the account holder; it cannot be requested on
someone's behalf.

## Steps

1. Register at <https://transparency.entsoe.eu> (top right: Login, then Register).
2. Email **transparency@entsoe.eu** from the registered address.
3. When they reply (typically a few working days), the token appears under
   *My Account Settings, Web API Security Token*.

## Email to send

> **To:** transparency@entsoe.eu
> **Subject:** Restful API access
>
> Dear Transparency Platform team,
>
> Please enable RESTful API access for my account, registered with the address
> below. I am using it for a non-commercial research project on carbon-aware
> electric-vehicle charging, reading actual generation per production type for
> Spain (document type A75).
>
> Registered email: *(your address)*
>
> Thank you,
> *(your name)*

## Then

```powershell
$env:ENTSOE_TOKEN = "your-token"
cd ml
python live_check_entsoe.py            # three days ago; or --day 2026-10-01
```

The script fetches a Spanish day through the client and compares it, hour by hour,
with the same day from Energy-Charts. It prints a table and exits 0 on PASS, 1 on
FAIL, 2 if no token is set. To serve live data, set `USE_LIVE_DATA=true` and
`ENTSOE_TOKEN` in the environment (never commit the token; `.env` is gitignored).

## What the token is not needed for

The Spanish **day-ahead solar, wind and load forecasts** the forecaster depends on
are published by Energy-Charts without a key, so the modern-grid forecaster
(`ml/fetch_spain_forecasts_ec.py`, `ml/train_modern.py`) does not wait on this.
