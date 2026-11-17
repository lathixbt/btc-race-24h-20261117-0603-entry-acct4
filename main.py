"""LongRide - BTC race bot for make.fun btc-race-24h-20261117-0603 (account 4).

Long only, $1,000 paper, 1-minute CBBTC bars. Two setups:

Setup B - capitulation-bounce sniper. A deep fall (60-bar close-to-close
>= 150 bps or 120-bar >= 250 bps) plus a >= 550 bps drawdown from the
720-bar high, a long lower-wick bar in the last 20 bars, a reversal bar
closing up >= 60 bps above the previous bar's high, RSI(14) turning up,
and reward/risk >= 2:1 to the 720-bar high. Stop under the capitulation
low (clamped 50-100 bps below the entry). Trailing arms at +80 bps and
trails the peak by 80 bps. Max hold 300 bars. Max 2 entries.

Setup D - sharp-drop dip-buy. >= 120 bps off the 120-bar high, NOT a
capitulation (< 550 bps off the 720-bar high), RSI(14) < 50, a fast
close-to-close fall >= 150 bps over 60 bars, and the current bar closing
up. One dip trade per window. Stop 60 bps below the entry. Trailing
arms at +80 bps and trails the peak by 80 bps. Max hold 400 bars
(a long hold, riding the bounce toward the peak).

Guards: at most 3 trades total, a 2% daily-loss guard, 60 bars of
cooldown after any exit, no entries after bar 1320, max slippage
200 bps. Stops are fixed at decision time from the decision bar's
close, never recomputed from the fill price.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

BPS = 10_000
SYMBOL = "CBBTC"
MAX_SLIPPAGE_BPS = 200
MAX_TRADES = 3
MAX_DIP_TRADES = 1
MAX_BOUNCE_TRADES = 2
COOLDOWN_BARS = 60
LAST_ENTRY_SEQ = 1320
MIN_HISTORY = 200  # at least 200 closes before any entry; the 720-bar windows use
# whatever history is available up to 720 bars (Python slicing)
WICK_LOOKBACK = 20
WICK_MIN_RANGE_BPS = 20
WICK_TOP_PCT = 6000  # close in the top 40% of its range <=> (close-low)/range >= 60%

# Module state, fresh on import/reload (the harness runs the bot twice).
closes = []
highs = []
lows = []
rsi_values = []
_avg_gain = None
_avg_loss = None
_last_t = None
_start_capital = None
_dip_trades = 0
_bounce_trades = 0
_last_exit_seq = -10 ** 9
_pending_buy = None
_pending_sell = None
_position = None


def _rsi_value():
    if _avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + _avg_gain / _avg_loss)


def _update_rsi():
    """Wilder's RSI(14) from the closes list; one value per close from the 15th on."""
    global _avg_gain, _avg_loss
    n = len(closes)
    if n < 15:
        return
    if _avg_gain is None:
        # Seed: plain mean of the first 14 bar-to-bar changes.
        gains = 0.0
        losses = 0.0
        for i in range(1, 15):
            ch = closes[i] - closes[i - 1]
            if ch > 0:
                gains += ch
            else:
                losses -= ch
        _avg_gain = gains / 14.0
        _avg_loss = losses / 14.0
    else:
        ch = closes[-1] - closes[-2]
        gain = float(ch) if ch > 0 else 0.0
        loss = float(-ch) if ch < 0 else 0.0
        _avg_gain = (_avg_gain * 13.0 + gain) / 14.0
        _avg_loss = (_avg_loss * 13.0 + loss) / 14.0
    rsi_values.append(_rsi_value())


def _fall_below(ref, px):
    """How far px sits below ref, in bps (integer math)."""
    return (ref - px) * BPS // ref


def _fall60():
    """Close-to-close fall over 60 bars: the close 60 bars ago vs the previous close."""
    return _fall_below(closes[-62], closes[-2])


def _fall120():
    """Close-to-close fall over 120 bars: the close 120 bars ago vs the previous close."""
    return _fall_below(closes[-122], closes[-2])


def _drop_from_high(lookback):
    """Fall of the previous close from the highest high of the `lookback` bars before it.
    Positive when the price has dropped below that high (same sign convention as
    _fall_below: (reference - price) * BPS // reference)."""
    window = highs[-lookback - 1:-1]
    hi = max(window)
    prev = closes[-2]
    return (hi - prev) * BPS // hi


def _high720():
    return max(highs[-721:-1])


def _low720():
    return min(lows[-721:-1])


def _has_wick():
    """A long lower-wick bar in the last 20 bars: range >= 20 bps and its close
    in the top 40% of its range (lower wick >= 60% of the range)."""
    start = len(closes) - WICK_LOOKBACK
    if start < 0:
        start = 0
    for i in range(start, len(closes)):
        h = highs[i]
        l = lows[i]
        c = closes[i]
        if h <= l:
            continue
        rng = h - l
        if rng * BPS // l < WICK_MIN_RANGE_BPS:
            continue
        if (c - l) * BPS // rng >= WICK_TOP_PCT:
            return True
    return False


def _bounce_stop(cur):
    """Setup B stop: 20 bps under the 720-bar capitulation low, clamped to
    50-100 bps below the entry (the decision bar's close)."""
    stop0 = _low720() * (BPS - 20) // BPS
    lo = cur * (BPS - 100) // BPS
    hi = cur * (BPS - 50) // BPS
    return min(max(stop0, lo), hi)


def _buy_order(state):
    return [{"side": "buy", "symbol": SYMBOL,
             "notional_quote_units": state.cash,
             "max_slippage_bps": MAX_SLIPPAGE_BPS}]


def _sell_order(state):
    holding = state.positions.get(SYMBOL)
    if holding is None:
        return []
    return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
             "max_slippage_bps": MAX_SLIPPAGE_BPS}]


def on_batch(state, batch):
    global _last_t, _start_capital, _dip_trades, _bounce_trades
    global _last_exit_seq, _pending_buy, _pending_sell, _position

    if _start_capital is None:
        _start_capital = int(state.hello["capital"]["quote_units"])

    # Duplicate-bar guard: skip a batch when no new CBBTC bar arrived.
    # (A bar carries no field "t"; the time is batch["t"].)
    t = batch.get("t")
    if t is not None and t == _last_t:
        return []
    bar = None
    for b in batch.get("bars", []):
        if b.get("symbol") == SYMBOL:
            bar = b
            break
    if bar is None:
        return []
    _last_t = t
    if state.warming_up:
        return []

    cur = int(bar["c"])
    closes.append(cur)
    highs.append(int(bar["h"]))
    lows.append(int(bar["l"]))
    _update_rsi()
    prev = closes[-2] if len(closes) >= 2 else cur

    # Confirm a buy decided on the previous batch (it fills at this bar's open).
    if _pending_buy is not None:
        if SYMBOL in state.positions:
            _position = dict(_pending_buy)
            _position["fill_seq"] = state.seq
            _position["peak"] = cur
            if _pending_buy["setup"] == "D":
                _dip_trades += 1
            else:
                _bounce_trades += 1
        _pending_buy = None

    # Confirm a sell decided on the previous batch.
    if _pending_sell is not None:
        if SYMBOL not in state.positions:
            _position = None
            _last_exit_seq = _pending_sell
        _pending_sell = None

    # Manage an open position: fixed stop, trailing stop, max hold.
    if _position is not None and SYMBOL in state.positions:
        if cur > _position["peak"]:
            _position["peak"] = cur
        order = []
        if cur <= _position["stop"]:
            order = _sell_order(state)
        else:
            arm = _position["entry"] * (BPS + 80) // BPS
            if _position["peak"] >= arm:
                trail = _position["peak"] * (BPS - 80) // BPS
                if cur <= trail:
                    order = _sell_order(state)
            if not order and state.seq - _position["fill_seq"] >= _position["max_hold"]:
                order = _sell_order(state)
        if order:
            _pending_sell = state.seq
            return order
        return []

    # Flat: consider an entry.
    if _position is not None or _pending_buy is not None:
        return []
    if len(closes) < MIN_HISTORY:
        return []
    if state.seq > LAST_ENTRY_SEQ:
        return []
    if state.seq - _last_exit_seq < COOLDOWN_BARS:
        return []
    if state.equity < _start_capital * 98 // 100:
        return []
    if _dip_trades + _bounce_trades >= MAX_TRADES:
        return []
    if len(rsi_values) < 2:
        return []

    rsi_cur = rsi_values[-1]
    rsi_prev = rsi_values[-2]
    d120 = _drop_from_high(120)
    d720 = _drop_from_high(720)

    # Setup B - capitulation-bounce sniper.
    if _bounce_trades < MAX_BOUNCE_TRADES:
        f60 = _fall60()
        f120 = _fall120()
        if (f60 >= 150 or f120 >= 250) and d720 >= 550 and _has_wick():
            rev_bps = (cur - prev) * BPS // prev
            if rev_bps >= 60 and cur > highs[-2] and rsi_cur > rsi_prev:
                stop = _bounce_stop(cur)
                if _high720() - cur >= 2 * (cur - stop):
                    _pending_buy = {"setup": "B", "entry": cur, "stop": stop,
                                    "max_hold": 300}
                    return _buy_order(state)

    # Setup D - sharp-drop dip-buy (close-to-close fall, long hold).
    if _dip_trades < MAX_DIP_TRADES:
        if d120 >= 120 and d720 < 550 and rsi_cur < 50 and _fall60() >= 150 and cur > prev:
            stop = cur * (BPS - 60) // BPS
            _pending_buy = {"setup": "D", "entry": cur, "stop": stop,
                            "max_hold": 400}
            return _buy_order(state)

    return []


if __name__ == "__main__":
    makefun_bars.run(on_batch)
