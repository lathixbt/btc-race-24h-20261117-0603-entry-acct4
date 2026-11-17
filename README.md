# LongRide

A BTC trading bot for the make.fun race "Race a BTC trading bot live for 24 hours" (btc-race-24h-20261117-0603).

[![make.fun](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/lathixbt/btc-race-24h-20261117-0603-entry-acct4/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/lathixbt/btc-race-24h-20261117-0603-entry-acct4/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603)

## Strategy

Long-only, two setups on 1-minute CBBTC bars, $1,000 paper money:

- **Setup B — capitulation-bounce sniper.** A washout of at least 550 bps from the 720-bar high, then a reversal bar closing up at least 60 bps with RSI(14) under 35. Max 2 entries, 60 bps stop, trailing stop arming at +80 bps and trailing 80 bps under the peak close, max hold 300 bars.
- **Setup D — sharp-drop dip-buy.** The dip must be a fast fall: at least 120 bps off the 120-bar high and at least 150 bps down over the last 60 bars, while staying under a 550 bps drawdown from the 720-bar high, with RSI(14) under 50 and the current bar closing up. One dip trade per window, held long (max 400 bars) to ride the bounce toward the peak.

Guards: at most 3 trades total, two consecutive Setup B losses stop further entries, a 2% daily-loss guard, 60 bars of cooldown after any exit, no entries after bar 1320.

## Backtests

- Dev window (16 Nov 06:03 UTC → 17 Nov 06:03 UTC): +$16.76, maxDD ~0.63%.
- Race window (Binance 14 Nov 05:29 UTC → 15 Nov 05:29 UTC): +$28.69.
- Held-out (11 Binance 24h windows, 1–11 Nov): +$18.23 total, 3/11 profitable.

## Files

- `main.py` — the bot (Python 3.13, standard library only).
- `vendor/makefun_bars.py` — the kit's bars-replay shim, byte-identical.
- `LICENSE` — MIT.
