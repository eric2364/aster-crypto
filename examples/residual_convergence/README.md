# BTC/ETH-factor residual convergence

One exploratory economic family, the 25th disclosed candidate on an already
examined year. A successful historical case would not establish four independent
edges or a fresh holdout. Zero admissible assets and zero trades are valid results.

The authoritative [prospective protocol](proposed_protocol.md) fits hourly return
betas during October–January, then calibrates cumulative residual mean reversion
on a disjoint January–April block. These models stay fixed during the three
monthly validation runs and July–October baseline/stress evaluation. There is no
parameter search or training-profit selection.

All eight instruments trade in one actual Engine account. Six equal altcoin
budgets share net BTC/ETH targets. Native 1000PEPE prices and quantities remain
native; no spot-unit conversion is appropriate. Orders can fill independently
and partially. Immutable pending targets, abort cleanup, funding, liquidation,
opening minima and residual inventory remain visible.

Source preparation and independent synthetic review must precede execution:

```bash
.venv/bin/python examples/residual_convergence/run.py --freeze-only
# Only after review of the frozen packet:
.venv/bin/python examples/residual_convergence/run.py --execute
# Rebuild analysis from the identical sealed five trials:
.venv/bin/python examples/residual_convergence/run.py --analysis-only
```

Defaults use `data_cache/minute-perpetual-1y` and
`results/residual-convergence-1y-v1`. The freeze validates official cached archive
checksums, actual funding responses, the complete minute grid and independent
marks. It pins all model/coordinator/runner/core source, source inputs and numerical
runtime before any fit, and archives executed source. A changed source, input or
runtime fails closed. Runs are sequential to keep memory bounded.

Each trial retains six financial ledgers in CSV and Parquet, minute/funding-clock
native quantity, mark, isolated reserve and approximate frozen-factor exposure,
all eight leg P&L contributions, coordinator diagnostics and a completion seal.
The exposure observer calls the original snapshot once and returns it unchanged;
it records the same post-fill state as equity, without changing execution.
Terminal positions are marked. Indicative exit fee/slippage reserves are analysis
only, not invented fills or a claim of executable volume.

The provisional summary retains every hurdle and failure. Its circular seven-day
conditional bootstrap uses 25-comparison tails and full-resolution evaluation
equity. These intervals cannot remove adaptive reuse of this year. Publication
requires an independent financial/source/summary audit; this runner emits no
unaudited public result or strategy recommendation.

After the final independent audit supplies a complete, source-pinned receipt:

```bash
.venv/bin/python examples/residual_convergence/publish.py \
  --audit-receipt results/residual-convergence-1y-v1/independent_audit.json
```

This separate presentation helper verifies the model, summary and all 20 files
per trial against that receipt before producing a self-contained HTML report,
comparison CSV and compact audited JSON. It never fits a model or runs Engine.
Its display plots sample observations; all reported risk and interval calculations
use the complete recorded ledgers.
