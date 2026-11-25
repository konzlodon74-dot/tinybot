# TinyBot — Trend-Following Rotation for Solana Hourly Bars

[![u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1.svg)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)
[![rank](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/konzlodon74-dot/tinybot/rank.svg)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)
[![reward](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/konzlodon74-dot/tinybot/reward.svg)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)

Entry for the make.fun bounty [Tiny Bot, Easy $2: Beat Buy-and-Hold on Solana](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1).

## Strategy

A long-only trend-following rotation bot speaking `agent-fun/bars-replay/v1`
(hello / batch / orders) over hourly bars of FARTCOIN, JITOSOL, POPCAT, RAY,
SOL, WETH and WIF:

- **Momentum score** per symbol: weighted blend of 6h / 12h / 24h returns.
- **Trend filter**: a symbol counts as in-trend when its close is above its
  12-bar EMA and its momentum is positive.
- **Rotation**: hold the top 4 in-trend symbols at up to the 25% per-symbol
  weight cap; the rest stays in USDC cash, so exposure shrinks on its own in
  downtrends and concentrates on winners in uptrends.
- **Risk rules**: rebalance every 4 bars, immediate exit on trend break or a
  −5% stop, 4-bar cooldown after selling, drawdown guard that halves exposure
  past 10% drawdown and goes defensive past 16%.
- **Turnover control**: entry momentum hurdle, top-5 hold buffer, and skipping
  top-ups under 2% of equity keep fees low.

Deterministic (no clock, environment or randomness), Python standard library
only. `main.py` is the entrypoint; `vendor/makefun_bars.py` is the kit's
protocol shim, copied unchanged.

## Local dev grade

On the kit's dev window (`grade-local`, process driver): net PnL −769.39 USDC
vs −869.34 USDC for the house buy-and-hold baseline, 39 trades, max drawdown
9.97%, all guardrails met, action log reproduced byte for byte.
