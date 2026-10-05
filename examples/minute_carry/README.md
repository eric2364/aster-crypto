# Actual minute funding carry

**Margin correction:** use the [correction workflow](../research_review/README.md) for current audited derivative comparisons. The original report paths below preserve the legacy margin convention at commit `8cd5f36`. Resuming their frozen outputs under the corrected engine rejects the changed source hash; use fresh output folders.

Five fixed policies test **one funding-carry economic family** across BTC, ETH,
DOGE, PEPE, SOL, XRP, LINK and ADA. The only real-data window is
5 October 2025–5 October 2026 UTC, end exclusive. Policies are always hedged,
positive trailing funding, funding rotation, hysteresis and risk controlled.
Their correlation means five policy names are not five independent edges.

```bash
.venv/bin/python examples/minute_research/download.py --workers 2
.venv/bin/python examples/minute_research/downloadcarry.py --workers 2
.venv/bin/python -m pytest -q tests/test_minute_carry.py
.venv/bin/python examples/minute_carry/run.py --out results/minute-carry-reproduction --freeze-only
.venv/bin/python examples/minute_carry/run.py --out results/minute-carry-reproduction --phase validation --workers 2
.venv/bin/python examples/minute_carry/run.py --out results/minute-carry-reproduction --phase holdout --workers 2 --review-out results/minute-carry-reproduction/compact
```

The two phases generate 120 sleeve simulations: 40 validation, 40 final-quarter
baseline and 40 joint stress. Validation is a continuous fresh-account quarter;
there is no parameter selection. Funding decisions use only published settlements
with an extra minute lag. Trading uses actual separate spot/perpetual/mark streams.
Each $12,500 sleeve enters $3,750 per leg, with spot long and equivalent native
perpetual short, fixed units and isolated leverage two. A 1000PEPE perpetual unit
hedges 1,000 spot PEPE. Fees, slippage, capacity and asynchronous leg fills matter.

Inspect the [saved report](../../docs/minute_carry_results/report.html), funding
and trading ledgers, source provenance and terminal-position CSV. All five
policies failed their historical hurdles. The declared close window retained
actual inventory in 63 of 120 cases; constrained unfilled legs are never silently
closed, and residual inventory fails the terminal-flat gate.

The original simulations completed before a timestamp-unit postprocessing error.
The exact executed source and output hashes are saved in the evidence directory.
Analysis recovery repaired timestamp precision without rerunning or retuning the
models. The current runner includes that repair; fresh reproductions use a new
output folder. Existing original caches remain tied to their executed fingerprint.
Only the original complete local cache supports `--analysis-only` recovery; it
must contain the preserved executed-runner snapshot and matching ledgers.

Official archives and settled funding need no account API key. Raw data and full
minute results stay outside Git. Current rules approximate historical exchange
rules, and a survivor universe and OHLCV execution cannot establish durable
profitability or atomic hedging. Consult the [manual](../../docs/user_manual.md)
and [combined results](../../docs/minute_strategy_results.md).
