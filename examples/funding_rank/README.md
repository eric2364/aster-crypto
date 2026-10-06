# Joint cross-sectional perpetual funding rank

Candidate 27 is one prospective exploratory experiment, not a winning strategy.
Its [fixed protocol](proposed_protocol.md) uses only the same 365-day window,
eight native Binance perpetuals including DOGE and `1000PEPEUSDT`, and one
actual 100,000-USDT cross-margin wallet. Sunday proposals buy the two lowest
known trailing funding intensities and short the two highest. Quantities are
fixed, execution is non-atomic, and all four legs must actually fill. Initial
dollar balance does not hedge coin-price or market-beta risk.

The first six months supply causal history only. There is no fitting or parameter
grid. Three fresh monthly validation accounts and two evaluation accounts
(baseline and stress) comprise one candidate. All 15 gates must pass. See the
[independent prospective review](../../docs/funding_rank_protocol_review.md).
Uniform slippage is 8/16bps and taker fees 5/10bps; historical publication times
and exchange rules remain approximations. Existing 26 outcomes stay preserved.

From the repository root:

```bash
.venv/bin/python examples/funding_rank/run.py --freeze-only
# Publish the fixed source and input preregistration before generating features.
.venv/bin/python examples/funding_rank/run.py --execute
.venv/bin/python examples/funding_rank/run.py --analysis-only
```

`--freeze-only` verifies all eight existing native datasets, hashes raw responses,
normalized data, catalogs, imported source and runtime, and archives source. It
does not build historical predictors or calculate returns. Execution refuses
changed or incomplete packets and retains partial trials for explicit diagnosis.
Outputs remain in ignored `results/funding-rank-1y-v1`; raw data is not uploaded.

Each phase exports six CSV/Parquet ledgers, post-fill account/native exposures,
all eight leg contributions, proposals/refusals, actual completed baskets and
terminal orders captured **before** automatic end-of-data cancellation. End
flatness requires exactly zero actual observed quantities, including tiny dust,
and no unresolved live orders. A cost reserve cannot substitute for liquidation
or executable closure.

Independent feature and financial auditors take the recorded full source/input
Git anchors. They reconstruct causal funding, native prices, cash, costs,
collateral, execution, actual completion and gates without production model
imports. Policy-intent coverage is separately disclosed; a financial certificate
alone does not prove that every strategy decision was correct. A conditional
27-comparison bootstrap cannot turn this repeatedly examined year into a fresh
holdout or establish non-overfitting.
