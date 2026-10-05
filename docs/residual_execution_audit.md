# Independent residual-convergence execution certificate

2026-10-06. **The audit passes; the trading hypothesis does not. No asset was admissible, and all five accounts stayed in cash.** This is the 25th disclosed candidate, not a successful strategy or untouched evaluation. The [compact certificate](residual_execution_audit.json) pins the full receipt and source/model/summary identities.

The independent auditor verified 34 source files and 307 inputs, including official raw archives and funding responses, runtime versions, the pre-fit input verification, archived executed code and immutable estimation receipt. All executed source blobs match preregistration commit `ae9fbd4ca48fac2b56c9c3ad0bdffc76fbf8ea44`, pushed before fitting. Later descendant documentation/publication commits may reproduce identical source; the auditor checks source content and ancestry rather than requiring the original commit label on a replication.

Separate arithmetic reconstructed every frozen beta/intercept, native origin price, disjoint calibration residual, AR1 coefficient, innovation/equilibrium variance, mean, half-life, fixed-lag ADF statistic/p-value/critical values, chronological half statistic, eligibility check and failed-check list. No strategy fitting helper or Engine rerun was used. The prescribed half-life interval was 1–24 hours and ADF eligibility cutoff 0.01.

| Target | Fitted half-life, hours | Conditional ADF p-value | Admitted |
|---|---:|---:|---|
| DOGE | 428.041 | 0.666191 | No |
| PEPE, native 1000PEPE | 278.000 | 0.384628 | No |
| SOL | 93.406 | 0.088542 | No |
| XRP | 94.068 | 0.054436 | No |
| LINK | 518.502 | 0.721970 | No |
| ADA | 783.421 | 0.764086 | No |

Every target failed both the half-life and ADF limits; several also failed chronological mean/variance stability. These failures remain in the model file. No coefficient, factor, cutoff, asset subset, direction or cost assumption was changed to generate trades.

All five exact phases and 100 sealed exports reconciled. The three independent monthly validation accounts, evaluation account and joint-stress account each began and ended at $100,000. Across **396,409 actual minute/settlement-clock snapshots**, cash/equity stayed unchanged, every native quantity/reserve/exposure was zero, and no order, fill, funding payment, trade, residual position or liquidation was exported. Observer marks nevertheless reconcile with actual independent mark opens/closes and sourced funding marks at the original settlement clocks; a flat wallet was not substituted for a simulated path. Native PEPE quote/quantity semantics remain intact.

Every frozen analytics metric was recomputed from the exported ledgers, alongside independent cash-only conservation, reserve, quantity, exposure and leg-PnL assertions. A temporary-directory summary rebuild reproduced all scores, monthly returns, gates and conditional intervals exactly. Only the non-liquidation and drawdown limits passed; the required positive-return, Sharpe and participation gates failed. The zero-width return interval is a property of remaining in cash, not statistical evidence of a profitable edge.

Reproduce from the repository root with the pinned research dependencies installed:

```bash
.venv/bin/python audit/verify_residual_outputs.py --final
.venv/bin/python -m pytest -q
```

The full independently pinned receipt is `audit/residual_independent_audit.json`; it contains the exact 20-file hash map for each phase. The publisher must recheck that receipt and mandatory training-model/trajectory/summary reconstruction flags before writing a fresh report. Auditor regressions reject invented inactive-account activity, hidden reserve/native exposure, changed model-admissibility diagnostics, altered preregistered source and missing/unrelated execution commits.

The final full test run passed **367 tests**, including 10 final-auditor regressions.

This confirms a valid no-trade result under the fixed design. It does not prove the model's exchange realism, cointegration, prospective profitability or absence of research adaptation. The prior year remains repeatedly examined; the requested four or five robust successful examples are still unsupported.
