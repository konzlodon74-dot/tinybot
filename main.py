"""TinyBot: trend-following rotation bot for agent-fun/bars-replay/v1.

Strategy (long-only, hourly bars, 7 Solana symbols):
- Score every symbol with a multi-horizon momentum blend (6h/12h/24h returns).
- A symbol is "in trend" when its close sits above its 12-bar EMA and its
  momentum score is positive.
- Hold the top 4 in-trend symbols, equal weight up to the 25% per-symbol cap;
  stay in USDC cash for the rest. When few symbols trend, exposure shrinks
  automatically, which preserves cash in downtrends.
- Rebalance every 4 bars; exit immediately on trend break or a -5% stop.
  A symbol must clear a small positive momentum hurdle to be bought, top-ups
  smaller than 2% of equity are skipped, and a held symbol is only rotated
  out when it falls below the top 5, which keeps turnover (and fees) low.
- A 3-bar cooldown after selling a symbol avoids whipsaw re-entries.
- Drawdown guard: halve target exposure past 10% drawdown from peak equity,
  go fully defensive (cash) past 16%.

Deterministic: no clock, no environment, no randomness. Python stdlib only.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

MAX_SLIPPAGE_BPS = 500
REBALANCE_EVERY = 4
TOP_N = 4
HOLD_BUFFER = 5          # rotate out only below this rank
ENTRY_HURDLE = 0.002     # minimum momentum to open a new position
MIN_TRADE_FRAC = 0.02    # skip top-ups under 2% of equity
EMA_LEN = 12
STOP_LOSS = -0.05
COOLDOWN_BARS = 4
MIN_HISTORY = 6

history = {}          # symbol -> list of closes (ints, price_scale units)
last_sold_seq = {}    # symbol -> seq when we last decided to sell it
peak_equity = 0
fills_seen = 0


def ema(values, length):
    if not values:
        return None
    k = 2.0 / (length + 1)
    out = float(values[0])
    for v in values[1:]:
        out = float(v) * k + out * (1.0 - k)
    return out


def ret_n(values, n):
    if len(values) <= n or values[-1 - n] == 0:
        return None
    return values[-1] / values[-1 - n] - 1.0


def momentum(values):
    parts = []
    for n, w in ((6, 0.5), (12, 0.3), (24, 0.2)):
        r = ret_n(values, n)
        if r is not None:
            parts.append((r, w))
    if not parts:
        return None
    total_w = sum(w for _, w in parts)
    return sum(r * w for r, w in parts) / total_w


def on_batch(state, batch):
    global peak_equity, fills_seen

    for bar in batch["bars"]:
        history.setdefault(bar["symbol"], []).append(int(bar["c"]))
    fills_seen += sum(1 for f in batch["fills"] if f.get("status") == "filled")
    if state.equity > peak_equity:
        peak_equity = state.equity

    if state.warming_up:
        return []

    symbols = sorted(state.symbols)
    min_notional = int(state.hello["fees"]["min_notional_quote_units"])
    max_orders = state.hello["caps"]["max_orders_per_bar"]

    # --- score the universe -------------------------------------------------
    scores = {}
    in_trend = {}
    for sym in symbols:
        vals = history.get(sym, [])
        if len(vals) < MIN_HISTORY or state.close(sym) is None:
            continue
        mom = momentum(vals)
        trend_line = ema(vals[-EMA_LEN * 2:], EMA_LEN)
        if mom is None or trend_line is None:
            continue
        scores[sym] = mom
        in_trend[sym] = vals[-1] > trend_line and mom > 0.0

    if not scores:
        return []

    ranked = sorted(scores, key=lambda s: (-scores[s], s))
    median_mom = sorted(scores.values())[len(scores) // 2]

    # Drawdown guard scales overall exposure.
    drawdown = 0.0 if peak_equity == 0 else 1.0 - state.equity / peak_equity
    exposure_scale = 1.0
    if drawdown > 0.16:
        exposure_scale = 0.0
    elif drawdown > 0.10:
        exposure_scale = 0.5

    # --- decide targets -----------------------------------------------------
    # In a crashing market (median momentum deeply negative) only genuinely
    # positive-trend symbols qualify; otherwise the best-ranked names may be
    # held even with slightly negative momentum so the bot stays active.
    if median_mom <= -0.02:
        candidates = [s for s in ranked if in_trend.get(s)]
    else:
        candidates = [s for s in ranked if in_trend.get(s) or scores[s] > -0.01]
    targets = candidates[:TOP_N] if exposure_scale > 0 else []
    keep = set(candidates[:HOLD_BUFFER]) if exposure_scale > 0 else set()

    orders = []
    is_rebalance = state.seq % REBALANCE_EVERY == 0

    # --- exits: checked every bar ------------------------------------------
    for sym in symbols:
        held = state.positions.get(sym)
        if not held or held.qty == 0:
            continue
        vals = history.get(sym, [])
        trend_line = ema(vals[-EMA_LEN * 2:], EMA_LEN) if len(vals) >= MIN_HISTORY else None
        cur_value = state.value(sym, held.qty)
        pnl = (cur_value / held.cost - 1.0) if held.cost > 0 else 0.0
        trend_broken = trend_line is not None and vals and vals[-1] < trend_line * 0.99
        mom = scores.get(sym)
        should_sell = (
            pnl <= STOP_LOSS
            or trend_broken
            or (is_rebalance and mom is not None and mom < -0.005)
            or (is_rebalance and sym not in keep)
        )
        if should_sell and len(orders) < max_orders:
            orders.append({"side": "sell", "symbol": sym, "qty": held.qty,
                           "max_slippage_bps": MAX_SLIPPAGE_BPS})
            last_sold_seq[sym] = state.seq

    # --- entries: only on rebalance bars ------------------------------------
    if is_rebalance and targets:
        sold_now = {o["symbol"] for o in orders}
        cash_left = state.cash
        per_symbol_cap = state.hello["caps"]["max_weight_bps"] * state.equity // 10_000
        for sym in targets:
            if len(orders) >= max_orders:
                break
            if sym in sold_now:
                continue
            if state.seq - last_sold_seq.get(sym, -10_000) < COOLDOWN_BARS:
                continue
            held = state.positions.get(sym)
            if not held and scores.get(sym, 0.0) < ENTRY_HURDLE and median_mom <= 0:
                continue
            held_value = state.value(sym, held.qty) if held else 0
            want = int(per_symbol_cap * exposure_scale) - held_value
            room = state.weight_room(sym)
            spend = min(want, room, cash_left)
            if spend < min_notional or spend <= 0:
                continue
            if held and spend < state.equity * MIN_TRADE_FRAC:
                continue
            impact = state.impact_bps(sym, spend)
            if impact is not None and impact > 80:
                continue
            orders.append({"side": "buy", "symbol": sym,
                           "notional_quote_units": spend,
                           "max_slippage_bps": MAX_SLIPPAGE_BPS})
            cash_left -= spend

    return orders


makefun_bars.run(on_batch)
