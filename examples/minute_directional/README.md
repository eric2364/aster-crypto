# Exploratory signed perpetual strategies

**Margin correction:** use the [correction workflow](../research_review/README.md) for current audited derivative comparisons. The original report paths below preserve the legacy margin convention at commit `8cd5f36`. Resuming their frozen outputs under the corrected engine rejects the changed source hash; use fresh output folders.

This extension tests six hypotheses on actual one-minute BTC, ETH, DOGE,
1000PEPE, SOL, XRP, LINK and ADA perpetual observations. It uses only
**5 October 2025–5 October 2026 UTC**, end exclusive.

The same historical year was already examined in thirteen earlier policies.
This extension is **exploratory on reused data**. A historical hurdle pass
cannot establish that a strategy avoids overfitting. All six models and all
three duration scales are retained, including losses.

## Reproduce

From the repository root, after installing the environment:

```bash
.venv/bin/python examples/minute_research/downloadcarry.py --workers 2
.venv/bin/python examples/minute_research/downloadcarry.py --verify-only
.venv/bin/python -m pytest -q tests/test_minute_directional.py
.venv/bin/python examples/minute_directional/run.py --freeze-only
.venv/bin/python examples/minute_directional/run.py --workers 4
```

The collector confines real data to this fixed year. Trade candles and separate
mark candles come from checksum-verified official Binance archives; funding
comes from the official timestamped settlement API. No account key is needed.
Current instrument rules approximate historical rules. The raw data cache and
full result folders are intentionally excluded from Git.

The runner writes `results/minute-directional-1y-v2/` and publishes compact
evidence to `docs/minute_directional_results/`. Its offline HTML report includes
all results, equity curves, drawdowns, costs and limitations. Each simulation
has source fingerprints, reconciled ledgers and actual terminal positions.
Resume with the same command and source files: cached results with mismatched
fingerprints are rejected. Use a new output folder for changed experiments.

## Models and selection

- Slow EMA trend: three-day and fourteen-day trends with hysteresis.
- Weekly Donchian: seven-day entry and three-day exit channels.
- Time-series momentum: three-day and seven-day return agreement.
- Signed mean reversion: twenty-four-hour deviation, observed-close stop and
  bounded holding time; orders execute only at a later eligible candle open.
- BTC-conditioned alt lag: published BTC direction, target lag and slower trend.
- Cross-sectional momentum: daily seven-day ranks, top two long, bottom two
  short, middle four in cash. Both losing and winning legs enter portfolio P&L.

The first six months choose one common duration scale per family by pooled
training Sharpe. Three subsequent monthly validation folds start fresh accounts.
The final quarter is a continuous historical evaluation with the selected scale,
both neighboring scales and joint execution stress. There are 480 simulations.
Nineteen cumulative policies and hypotheses are disclosed; their conditional
bootstrap adjustment does not remove adaptive research bias.

## Accounting and interpretation

Eight independent $12,500 sleeves provide $100,000 total initial capital.
Entry notional is 25% of current sleeve equity, with fixed native contract
quantity between direction changes. Isolated leverage is one. 1000PEPE prices
and quantities remain in native bundle units. Actual funding is a separate
signed cash flow; positive rates cost longs and benefit shorts.

Base taker fees are 5 bps per side. Adverse slippage is 2 bps for BTC/ETH,
8 for DOGE/PEPE and 5 for the other assets, plus adverse tick rounding.
Stress doubles fees/slippage, adds one minute delay and halves prior-volume
participation. Terminal open positions stay marked. An indicative exit reserve
is reported separately and never fabricated as a trade or cash flow.

Hurdles include positive validation, evaluation, stress and neighboring-scale
returns; positive reserve-adjusted diagnostics; at least two positive evaluation
months; Sharpe at least 0.5; drawdown at most 20%; and no simulated liquidation.
Scalar models require five profitable sleeves. The ranked long/short portfolio
instead requires actual fills across at least four assets, while retaining all
eight asset P&Ls. Balanced initial long/short directions do not imply beta
neutrality or neutral notionals after prices drift.

Minute observations cannot establish tick-level execution, intraminute margin
safety or queue priority. These are slower strategies simulated on minute data,
not evidence of profitable one-minute scalping. The selected surviving universe,
current exchange rules and reused year limit every conclusion.
