# Aster user manual

Aster is a local Python research platform for crypto spot and linear perpetual backtests. Its vector layer screens signals; its event engine validates execution, fees, funding, margin and accounting. The included strategies are engineering demonstrations. Synthetic examples test software behavior and provide no evidence of historical profitability.

Read [execution assumptions](execution_model.md), [derivatives assumptions](derivatives_model.md), [metric definitions](metrics.md), [data sources](data_sources.md) and [audit findings](audit.md) alongside this manual. Named exchange adapters are offline normalization/research profiles, not live trading connectors or exact reproductions of current venue rules.

## 1. Install and verify

Use Python 3.12 or newer. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,research]'
.venv/bin/python -m pytest -q
```

If the checkout already contains the prepared `.venv`, use it directly. Run commands from the repository root so relative config/data/output paths resolve consistently. On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\streamlit.exe` instead. The platform has no requirement for exchange credentials, an account, or a live order permission to run backtests.

Dependencies include NumPy, Pandas, PyArrow, Plotly, Streamlit and PyYAML. Editable installation exposes the `aster` CLI; the equivalent explicit interpreter form is `.venv/bin/python -m aster.cli`.

## 2. Run three reproducible demonstrations

```bash
.venv/bin/python -m aster.cli backtest --config config/spot-buy_hold.yaml --out results/spot
.venv/bin/python -m aster.cli backtest --config config/perpetual-ma.yaml --out results/perpetual
.venv/bin/python -m aster.cli backtest --config config/perpetual-funding.yaml --out results/funding
```

All three configurations explicitly request synthetic hourly data. The console prints output directory, strategy, return, fill count, closed trades, funding events, final equity and quality warnings. Review the warnings even when the command succeeds. An output directory is overwritten on rerun; use a new name to preserve a historical experiment.

The `demo` command creates a two-venue BTC/ETH synthetic run:

```bash
.venv/bin/python -m aster.cli demo --market perpetual --strategy ma --periods 2160 --out results/demo
.venv/bin/python -m aster.cli demo --market spot --strategy buy_hold --out results/spot-demo
```

`--no-report` skips HTML generation while preserving ledgers and analytics. Existing strategy names are `buy_hold`, `ma`, `rsi`, `momentum`, `breakout`, `funding`, `cross_momentum`, `neutral`, and `relative_value`. `funding` trades only perpetual instruments. Negative targets from other examples become flat targets in spot mode because spot shorts are not implemented.

## 3. Open the report and inspect evidence

Open the run's `dashboard.html` in a browser. Plotly is bundled inside it and needs no network connection. For a ledger explorer:

```bash
.venv/bin/streamlit run dashboard.py
```

Select `results/` or an individual run path in the sidebar. The performance tab contains equity/benchmarks, drawdown, a reconciled cost bridge, leverage, exposures, symbol/exchange contribution, monthly returns, rolling statistics and trade distributions. The ledger tab filters by exchange/symbol when those columns exist and downloads the selected CSV rows. Filters do not recalculate portfolio metrics. The evidence tab shows configuration, source identity and data quality. Synthetic runs show a prominent source label.

Run outputs:

| File | How to use it |
|---|---|
| `equity.csv` / `.parquet` | Chronological portfolio snapshots, initial baseline, cash, exposure, P&L, costs and leverage |
| `fills.csv` / `.parquet` | Every executed piece, quantity, actual/reference price, fee, liquidity side and reason |
| `trades.csv` / `.parquet` | Closed portions/cycles with net and gross P&L, assigned costs/funding and holding time |
| `funding.csv` / `.parquet` | Actual settlement payments with signed position, rate and mark |
| `events.csv` / `.parquet` | Order lifecycle, fees, funding, cancellations/rejections and liquidation evidence |
| `positions.csv` / `.parquet` | Positions still open at the end, with unrealized P&L, funding and assigned entry fees |
| `metrics.json` | Strict JSON metrics; undefined ratios use `null` |
| `metadata.json` | Strategy/version/parameters, engine/instruments, software/dependency versions, source/data hashes, git commit, UTC period and quality |
| `quality.json` | Validation report and warnings |
| `config.yaml` | Exact CLI configuration used |
| `benchmark.csv` | Frictionless observed-price reference indices |
| `dashboard.html` | Interactive offline report |

There is no automatic final liquidation of healthy open positions. Equity includes their mark-to-market; closed-trade P&L alone therefore need not equal the portfolio profit. Use `positions.csv` before interpreting low trade counts or unmatched entries. The exporter checks equity conservation, fee/funding sums and closed-plus-open attribution; a failed identity raises an assertion instead of reporting a successful run.

## 4. Use actual historical data

The one-year historical demonstrations use the completed UTC interval **5 October 2025 00:00 through 5 October 2026 00:00 (exclusive)**, with 8,760 expected hourly candles per instrument. The fixed cutoff avoids using a currently incomplete candle. These commands retrieve actual source observations, not generated prices:

```bash
.venv/bin/python examples/download_binance.py --symbol BTCUSDT --interval 1h --start 2025-10-05 --end 2026-10-05 --out data_cache/btc-spot-1y
.venv/bin/python -m aster.cli backtest --config config/real-btc-1y.yaml --out results/real-btc-spot-1y

.venv/bin/python examples/download_binance.py --symbol BTCUSDT --interval 1h --market perpetual --start 2025-10-05 --end 2026-10-05 --out data_cache/btc-perpetual-1y
.venv/bin/python -m aster.cli backtest --config config/real-btc-perpetual-1y.yaml --out results/real-btc-perpetual-1y
```

The spot downloader saves `bars.parquet` and `source_manifest.json`. Perpetual mode additionally joins separate historical mark-price candles and saves realized settlements as `funding.parquet`. Raw archive and funding-response files remain under `raw/`. Archive SHA256 checksums are verified, boundaries are checked for complete hourly coverage, and missing funding/settlement marks fail rather than being replaced with zeros or future observations. Funding coverage still needs review: exchange intervals may change and the downloader does not invent a fixed cadence.

Read the manifest's requested bounds, observed rows, archive URLs/checksums, download time, funding page identities and quality report, together with [data_sources.md](data_sources.md). The downloader supports `1s`, `1m`, `5m`, `15m`, `1h`, `4h` and `1d`; an interval being accepted does not guarantee the vendor publishes it for every market/date. It currently supports alphanumeric USDT symbols and requires aligned UTC bounds. Network/region restrictions or an unpublished source file may fail a download; do not replace it with fabricated prices. A later download can receive vendor corrections, so preserving raw files and the manifest matters. A rerun on unchanged normalized files preserves their content hash.

These real-data examples still use explicit, simplified execution/margin and fee profiles. Actual downloaded prices and rates do not make venue modeling exact or a strategy validated out of sample.

For any normalized CSV or Parquet input, replace the synthetic data section with:

```yaml
data:
  bars: data/my_bars.parquet
  funding: data/my_funding.parquet
```

Omit `funding` for spot. Remove `synthetic: true` when using actual files so source labeling stays accurate. The CLI does not have a date-range flag; filter the input file to your desired dates before running. Paths are relative to the current working directory.

### Required candle schema

| Column | Meaning |
|---|---|
| `timestamp` | Timezone-aware **interval start**, e.g. `2025-10-06T00:00:00Z` |
| `instrument_id` | Exact ID of an entry in the configured catalog |
| `open`, `high`, `low`, `close` | Positive prices in quote currency per base asset unit |
| `volume` | Nonnegative base-asset traded quantity; not quote notional or raw derivative contracts |
| `duration_seconds` | Positive interval duration: 60, 300, 900, 3600, 14400 or 86400, for example |

Optional candle columns include `mark_open`, `mark_price`, and `index_price`. For perpetuals, supplying separate historical opening/closing marks avoids using trade prices as proxies. Missing marks generate warnings and do not magically reconstruct an intrabar liquidation path. Other vendor columns may be retained, but a column existing does not mean the execution engine uses it.

```csv
timestamp,instrument_id,open,high,low,close,volume,duration_seconds
2025-10-06T00:00:00Z,binance:spot:BTCUSDT,120000,120100,119900,120050,25,3600
```

A candle's full close/high/low/volume is unavailable until `timestamp + duration_seconds`. Importing inclusive exchange close timestamps as interval starts will shift the strategy incorrectly. Normalize milliseconds and timezone explicitly. The validator rejects timezone-naive timestamps rather than guessing UTC. For another source timezone, localize to that known zone first, then convert to UTC.

Funding files require `timestamp,instrument_id,funding_rate,mark_price`. The timestamp is the actual settlement time, not a candle start. Rates are decimal fractions: `0.0001` means one basis point. Positive rates debit longs and credit shorts. Do not insert a currently displayed predicted rate across historical timestamps. Funding callbacks expose a settled rate only after its payment; they cannot capture that same settlement by entering afterward. Missing coverage produces warnings and omitted payments, not a reconstruction. Funding interval metadata alone does not synthesize settlements.

### Validate before running

```python
from aster.data.loader import load
from aster.data.validation import normalize_bars

bars, quality = normalize_bars(load('data/my_bars.parquet'))
print(quality.to_dict())
```

Validation rejects duplicates, overlapping intervals, missing/nonfinite values, nonpositive prices, negative volume, invalid OHLC and malformed marks. It reports gaps, variable durations and large price jumps. Missing intervals are not filled with invented tradable candles. Inspect gaps against exchange maintenance and the historical listing universe. Configured `listed_at`/`delisted_at` bounds check supplied data but do not discover failed/delisted coins automatically.

CSV is convenient for inspection; Parquet is preferable for repeated large-file loading. `save_partitioned` can write catalog-enriched tables by exchange/market/symbol/year/month, but the simple `load` helper accepts a `.csv` or `.parquet` path. A production streaming/partition-selection layer is still future work.

## 5. Configure the account and market

Use existing YAML examples as your starting point. Each instrument needs an immutable internal `id`, `exchange`, exchange `symbol` and `market_type` (`spot` or `perpetual`). The engine keys positions by ID, so `binance:perpetual:BTCUSDT` and `bybit:perpetual:BTCUSDT` remain distinct.

| Setting | Operational meaning |
|---|---|
| `engine.initial_balances` | Separate quote-currency wallet per exchange; each configured venue needs a wallet |
| `leverage` | Initial margin denominator for perpetual position sizing/accounting; does not multiply equity or P&L directly |
| `margin_mode` | `isolated` or simplified single-currency `cross` within a venue |
| `max_gross_leverage` | Risk cap on gross exposure versus equity, enforced separately within each venue |
| `max_position_pct` | Spot notional cap is venue equity × this fraction; perpetual cap also multiplies by configured leverage |
| `fill_model` | `conservative`, `touch`, or `volume_aware`; no L2 matching mode |
| `participation` | Fraction of observed volume used as a shared capacity proxy, in `(0,1]` |
| `slippage_model` | `fixed`, `spread`, `volatility`, or `volume` |
| `slippage_bps` | Fixed adverse-price adjustment; 2 bps = 0.02% |
| `spread_bps`, `impact_bps` | Inputs to the corresponding deterministic slippage profiles |
| `latency_ms` | Submission/activation latency on the discrete observation clock |
| `execution_delay_bars` | Extra bar-duration delay; positive delay defers eligible observations |
| `funding_enabled` | Apply supplied historical settlements when true |
| `seed` | Synthetic input reproducibility |
| `record_every` | Portfolio snapshot sampling; increase to reduce output size, at the cost of analytics resolution |

Instrument fields include tick size, lot size, minimum quantity/notional, maker/taker bps (signed rebates supported), leverage limit, maintenance rate and liquidation penalty bps. These defaults are research assumptions; obtain dated historical rules before making venue-specific claims. A single profile does not model historical tier/VIP changes.

For a linear perpetual signed quantity `q`, trading P&L is `q × (exit - entry)`. Initial notional is not deducted like spot principal. Isolated collateral is allocated separately; cross margin shares eligible quote cash and derivative unrealized P&L only within its own venue. Spot inventory cannot collateralize derivatives in this implementation. A maintenance breach forces liquidation with taker execution and the configured penalty. Opening/closing marks drive checks; no intrabar mark path, exchange auction, insurance fund or ADL is modeled. See the implementation-specific section of [derivatives_model.md](derivatives_model.md).

All account amounts must use a consistent reporting currency. Multi-currency FX/stablecoin conversion, borrowing, collateral transfers, inverse/quanto contracts, non-unit multipliers, hedge mode, dated futures and options are unsupported. Do not assign USDT and USDC cash to one common unit without an explicit conversion model.

## 6. Execution and strategy programming

At a completed bar, the strategy can use that bar and earlier completed history. A new zero-latency market order executes at an eligible subsequent open, not the just-observed close. Positive millisecond delay can miss a boundary and wait for a later bar open because no sub-bar price is invented. Orders against opening prices use previous completed volume; resting close-time matching uses completed current volume with a shared capacity budget.

Conservative limits require strict penetration and a full resting interval. Touch is more optimistic; volume-aware remains a candle approximation. Marketable limits take liquidity; resting limits may make liquidity. Post-only rejects immediately marketable orders. Intrabar stop triggers are detected at completion and cannot manufacture a trigger-then-fill path within that same candle. IOC cancels remaining quantity after its first opportunity; FOK requires the full fill atomically; GTC market remainders retry later opens, a documented simulator convention. Cancellation callbacks take effect immediately.

The CLI accepts registered engineering strategies only. For a custom strategy, use the Python API or add your class deliberately to `STRATEGIES` in `aster/strategies/examples.py`.

```python
from aster.backtest.engine import Engine
from aster.backtest.models import Order, SimulationConfig
from aster.exchanges.adapters import ADAPTERS
from aster.data.loader import load
from aster.strategies.base import BaseStrategy
from aster.reproducibility import export_result
from aster.reports import write_html

class OneEntry(BaseStrategy):
    version = '1'
    def __init__(self):
        self.entered = False
    def on_bar(self, context, bar):
        if not self.entered:
            context.order(Order(bar['instrument_id'], side=1, quantity=0.001))
            self.entered = True

spec = ADAPTERS['binance'].instrument('BTCUSDT', 'spot', base='BTC')
config = SimulationConfig(initial_balances={'binance': 100000})
bars = load('data/my_bars.parquet')
result = Engine([spec], config).run(bars, OneEntry())
root, summary = export_result(result, 'results/custom', bars=bars,
                              data_source='user supplied; see source manifest')
write_html(result, root / 'dashboard.html', summary)
```

Order side is `1` for buy and `-1` for sell; quantity is positive base units. Use `context.target(instrument_id, signed_quantity)` to rebalance a position, `context.cancel(order_id)` to cancel, and `context.history(instrument_id, count)` for completed data. `on_bars(context, bars)` receives simultaneous completed bars for cross-sectional work; `on_funding(context, event)` receives settled funding. New class instances should be used for each run so indicator buffers and entry flags cannot leak between trials.

For explicit limits/stops, set `order_type='limit'/'stop_market'/'stop_limit'`, `limit_price`/`stop_price`, `post_only`, `reduce_only` and `tif='GTC'/'IOC'/'FOK'` as appropriate. `reduce_only` is for perpetuals and cannot grow or flip a position. Lot grids, min quantity/notional, available cash/margin and risk limits can reject candidates; inspect event reasons instead of assuming every strategy intent executed.

The vector helper `moving_average_signals(close, fast, slow)` expects a timezone-indexed close matrix. `VectorizedStrategy(signals, allocation=...)` requires signals indexed by their **availability/end timestamp**, with instrument IDs as columns. `screen_returns` is a lagged close-to-close diagnostic with simplified fees; it does not simulate derivatives, margin, funding or realistic fills.

## 7. Read P&L and statistics correctly

Executed-price trading P&L already contains simulated slippage. Reconcile:

`equity change = realized trading P&L + unrealized trading P&L + funding - trading fees - liquidation fees`

Slippage is separately visible as diagnostic implementation shortfall; subtracting it again would understate equity. The waterfall adds it back to construct a reference-price starting point and subtracts it once. Funding is a separate cash flow. Maker/taker fees are assigned per fill rather than inferred from the submitted order type. A trade can receive several partial fills and both maker/taker outcomes.

Returns and ratios in `metrics.json` are fractions. Daily returns use UTC calendar days and crypto's 365-day annualization. CAGR uses actual elapsed time; Sharpe uses sample volatility; undefined ratios are null. Duration-weighted exposure prevents event-heavy periods from dominating averages. Drawdown metrics are limited to recorded snapshots: sampling every 100 bars can hide interim drawdowns and change daily closes. Prefer `record_every: 1` for final analytics.

Profit factor and win rate use net closed-trade outcomes; portfolio equity includes open positions. Gross profit/loss use pre-fee gross trade outcomes. Fees/slippage over positive gross closed-trade profit can be undefined or misleading with few closed trades. Very short-sample CAGR/Sharpe can be enormous without being meaningful. See [metrics.md](metrics.md) for exact formulas.

Automatic BTC/ETH/equal-weight/cash benchmark columns are frictionless indices from the supplied bars, not independently sourced investment returns. Upload another benchmark via Streamlit or save `benchmark.csv` with timestamp and numeric columns. Alignment uses only already observed prices and leaves the pre-overlap period blank. `aster.analytics.benchmarks.denominate` converts equity with backward as-of observed denomination prices; missing initial conversion prices raise an error.

## 8. Research, walk-forward and sensitivity

Run the installed demonstrations:

```bash
.venv/bin/python examples/research.py
.venv/bin/python examples/compare.py
```

`examples/research.py` writes `results/research/grid.csv`, `walk_forward.csv` and `robustness.csv` using synthetic data. `examples/compare.py` runs all nine engineering strategies and writes per-strategy result folders plus `results/comparison/strategies.csv`.

The Python APIs are `grid_search`, `walk_forward`, and `robustness` from `aster.optimization.search`. Grid search accepts an instrument list, config, normalized bars, strategy factory, parameter-list dictionary, optional funding and objective (default `sharpe`). It sorts descending, so loss metrics such as max drawdown require explicit selection logic rather than treating the first row as best. Walk-forward trains/selects parameters then evaluates a later disjoint window; bars whose closes cross the boundary are excluded. It defaults to 180-day training and 30-day tests.

Every test fold starts a fresh account and strategy; fold P&L is not a compounded continuous trading record. It also restarts indicator warmup in the test segment. Funding is restricted by each engine run's period. Preserve an untouched final holdout, inspect stable parameter neighborhoods and compare cost sensitivity rather than selecting maximum historical return.

Built-in robustness scenarios are baseline, double fixed-slippage bps, half participation, one extra bar delay and double maker/taker rates. “Double slippage” changes `slippage_bps`; if you selected a different slippage profile, examine which parameters drive it rather than claiming all impact doubled. Random search, Optuna, bootstrap, Monte Carlo and automatic regime-based optimization are future extensions. Descriptive lagged regime labels are available in analytics but are not validated state classifications.

## 9. Measure performance responsibly

```bash
.venv/bin/python benchmarks/run.py --bars 10000 --mode noop
.venv/bin/python benchmarks/run.py --bars 100000 --mode ma --output benchmarks/my-run.json
.venv/bin/python benchmarks/run.py --bars 100000 --symbols 20 --mode noop
.venv/bin/python benchmarks/run.py --bars 100000 --duration 1 --mode noop
.venv/bin/python benchmarks/run.py --bars 10000 --mode ma --profile benchmarks/my-run.prof
```

`--bars` is the total row count across symbols and must be divisible by the symbol count. `--mode vector` measures signal cells, not execution. No-op runs emit no orders; active MA stresses ledgers. Memory includes input preparation, schedule and outputs. See [performance.md](performance.md) for actual measured datasets and unrun workloads. The current in-memory scheduler and audit dictionaries are the scaling limit; snapshot downsampling does not make full large universes memory-bounded.

## 10. Troubleshooting and maintenance

| Symptom | First checks |
|---|---|
| `No module named pytest/aster` | Use `.venv/bin/python`, install `-e '.[dev]'`, run from repository root |
| Unknown strategy | Use a registered name or the Python API; CLI does not import arbitrary classes |
| Timezone-aware timestamp error | Explicitly localize the known source timezone, then convert to UTC |
| Duplicate/overlap/invalid OHLC error | Repair source records with evidence; do not silently average incompatible candles |
| No fills | Warmup length, available future bars, previous volume, lot/notional grids, position/risk caps, min wallet and event rejection reasons |
| Funding P&L is zero | Perpetual instrument, supplied settlement coverage, funding enabled, position actually held before settlement |
| Null Sharpe/profit factor | Too few daily observations, zero volatility or no losing closed trades; not a crash |
| Dashboard blank rolling panel | Fewer than 30 complete daily returns |
| Closed trade sum differs from equity | Check open positions and their unrealized P&L/entry costs/funding |
| Unexpected liquidation | Supplied mark prices, margin mode, collateral, maintenance/penalty rates and extreme gaps |
| High memory usage | Start with shorter/smaller inputs; profile; use Parquet and limited sweeps; read benchmark limitations |
| Historical and rerun results differ | Compare data/source hashes, git commit, config, timestamps, fee profiles and software versions |

Before maintaining the private GitHub repository, keep raw credentials and personal data out of commits. Raw market datasets and generated reports can be large; review `.gitignore` and intentionally choose which manifests/example outputs to version. Once the repository has a verified remote, normal maintenance is:

```bash
git status --short
git pull --ff-only
.venv/bin/python -m pytest -q
# Make and review changes, rerun the affected examples and tests.
git diff --check
git diff --stat
git add <reviewed-files>
git commit -m "Describe the tested change"
git push
```

These are maintenance instructions, not evidence that a remote or upload succeeded. Repository visibility and the actual remote are reported separately. Preserve a new output directory and manifest for each meaningful experiment; do not replace old results while calling them reproducible. A null git commit is possible before the first commit; source hashes still identify local code.

## 11. Current limitations checklist for interpreting a run

- Candle mode provides conservative heuristics, not L2 queue rank, hidden liquidity or HFT accuracy. Quote/trade/book schema classes are future contracts rather than matching engines.
- Mark observations are discrete; an intrabar mark breach may be missed. Constant maintenance/penalty rates are not historical exchange risk tiers.
- Funding coverage and publication times are source responsibilities; no forecast feed or complete automatic historical coverage check exists.
- Cross margin is a simplified, single-currency, venue-local model. No insurance fund, ADL, hedge-mode account, transfer engine or multi-currency netting exists.
- Symbol/listing metadata can reject outside-lifetime bars, but the platform does not supply a complete historical universe or automatically cure survivorship bias.
- Float grid tolerances are tested but do not replace an exact decimal matching engine.
- Repeated parameter trials are serial and fresh-state; full multi-year active multi-symbol simulation is memory-intensive.
- Local tests and synthetic reconciliations demonstrate software behavior. Only appropriately sourced historical data, dated venue rules, realistic cost sensitivity and out-of-sample evidence can support a strategy assessment.

## Last-year minute and leading-factor study

For the eight-asset one-minute study, follow [the reproducible example guide](../examples/minute_research/README.md). It downloads only the fixed latest-complete-day year, including DOGE and PEPE, and uses training-only parameter selection followed by validation and a locked historical holdout. The guide explains costs, source hashes, all failure gates, bootstrap uncertainty and where to find each ledger. The [primary-paper review](leading_factor_research.md) distinguishes BTC lead–lag/funding hypotheses from demonstrated results; the [factor-source guide](leading_factor_sources.md) covers QQQ, inflation release vintages and historical X access.

A positive historical result is an example to investigate, not a promise of future profits. Treat the chosen survivor universe, current instrument rules, simulated execution and short holdout as practical limits on the evidence. Do not tune an unsuccessful strategy against this holdout and then describe the same period as untouched.

The [signed perpetual extension](../examples/minute_directional/README.md) tests
six slower long/short hypotheses on the same year, including a daily ranked
two-long/two-short basket. It is explicitly exploratory on reused historical
evaluation data. Native 1000PEPE bundle units, actual funding and isolated margin
are preserved. Open terminal positions remain marked; an indicative exit-cost
reserve is a diagnostic rather than a fabricated fill. See [combined results](minute_strategy_results.md)
for every failed gate and [the independent audit](minute_directional_audit.md)
for the tested timing, unit and source-integrity checks.

After all three studies finish, regenerate the combined results without changing
simulations using `.venv/bin/python examples/minute_research/combined_report.py`.
Its nineteen-comparison conditional uncertainty intervals use full-resolution
pooled equity and preserve the earlier cohort's results. They do not remove
adaptive research bias or establish non-overfitting.

## External-factor demonstration

The [external-factor guide](../examples/external_factors/README.md) provides the
commands to collect actual daily QQQ prices, reproduce eleven original BLS CPI
release records, and extract authentic taker-buy volume from verified Binance
perpetual archives. It then runs five fixed hypotheses over the same eight-asset
last-year minute dataset. The [source notes](leading_factor_sources.md) explain
where data can be obtained and which historical availability assumptions apply.
The bundled CPI snapshot reproduces the observed official-page rendered source
records offline; direct HTTP access was blocked in this environment.

Run `examples/external_factors/run.py --workers 4` with the project Python,
then `examples/external_factors/update_results.py` to update the combined report.
Open `docs/external_factor_results/report.html` via the local HTTP server for
all outcomes and activity counts. Preserve `source_lock.json`, `protocol.json`,
`selection.json` and the execution receipts when comparing reruns. Source or
input changes require a new output directory. The new combined report has
twenty-four cumulative disclosed candidates; the older nineteen-comparison
postprocessor alone does not include this extension.

Funding rates, premiums, QQQ and CPI are candidate predictors, not automatic
trading advantages. Sparse CPI announcements and correlated exposure across
coins limit statistical evidence. Current X searches are not used as historical
sentiment. Read each failed hurdle, joint cost stress and liquidation count
before treating a positive headline return as useful evidence.


## Partial-exit margin correction and historical reports

The original derivative studies used a margin-retention convention that could
force-liquidate a tiny remaining position after a losing partial close despite
healthy proportional collateral. Cash ledgers still reconciled; that alone did
not establish correct margin allocation. The corrected engine releases the
closed portion’s reserve and settles its P&L/fees in wallet cash. The remaining
reserve retains only its proportional collateral and accrued funding.

The original reports are preserved as dated evidence. All 1,000 identical
accounting-correction reruns are complete and independently audited. The
[corrected comparison](margin_correction_results/report.html) retains all 24
candidates and still reports zero complete hurdle passes. Actual derivative
liquidation fills across all phases fell from 77 to 23, all in carry cases. Use a fresh
folder with the corrected engine; attempting to resume an original frozen run
correctly rejects the changed engine hash. Original engine reports can be
reproduced from Git commit `8cd5f36`, with their legacy convention explicit.
Run `.venv/bin/python examples/research_review/rerun_margin_correction.py` to
reproduce the corrected 120 carry, 480 signed and 400 external-factor cases.
No thresholds, costs, selection rules, years, assets or hurdle definitions change.
This rerun does not add a new economic hypothesis to the count.

See the [correction workflow](../examples/research_review/README.md) for the
independent audit and guarded publication commands. Each trial has sixteen
sealed output files. Audits independently rebuild quantities, cash, funding,
reserves, marked equity, summary gates and training-only scale selection.
A new clone needs preserved original results or a separate legacy checkout to
reconstruct them; the workflow explains this requirement. Source-hash mismatch
is a reason to stop a cached resume, not to overwrite its original evidence.

## Fixed residual-convergence experiment

The [prospective protocol](../examples/residual_convergence/proposed_protocol.md)
defines one additional BTC/ETH-hedged altcoin family. Six altcoins share one
actual eight-instrument account. Return betas use the first three months and
residual calibration uses the next three; minute trading begins only after
calibration. Models stay frozen, pending hedge targets do not imply atomic fills,
and failed admission leaves cash. This is exploratory on the already examined
year. The protocol was committed at `ae9fbd4` before fitting. All six altcoins
failed its fixed admission rules: residual half-lives were 93–783 hours, above
the declared 1–24 hours, and all conditional ADF p-values exceeded 0.01.
All five actual simulations stayed in cash: zero trades and zero returns.
The cumulative research result at that stage was **0/25 historical hurdle passes**.
Read the [audited report](residual_convergence_results/report.html) and
[independent certificate](residual_execution_audit.md).

Install the pinned statistical research extra with `uv sync --locked --extra dev --extra research`, or install `.[dev,research]` using pip. Read the
[example guide](../examples/residual_convergence/README.md) for source freezing,
execution and independent audit requirements. Original24 results stay preserved.


## Cross-venue funding study

The [cross-venue guide](../examples/cross_venue/README.md) gives collector,
independent source-verification, freeze and execution commands for the same fixed
year and eight native pairs. This additional family has two separate venue cash
wallets; hedge gains cannot replenish the other wallet. Equal 1000PEPE quantities
remain bundle units. The funding predictor uses past available settlements and
actual observed interval lengths. Bybit funding cash uses an explicitly labeled
minute-mark proxy, with a predetermined alternative valuation replay.

Read the [protocol](../examples/cross_venue/proposed_protocol.md) and
[source integration review](cross_venue_preregistration_review.md) before running.
Freeze source/input/runtime in an empty output folder and retain its Git evidence
before creating historical features. Exact source and input mismatches stop a
resume. The seven fixed simulations are one candidate, not seven strategies.
The actual seven-run experiment and independent source, feature, financial and
cohort-specific entry checks are complete. All runs stayed in cash because none
of 78,720 pair decisions met the fixed cost filter. Read the
[audited report](cross_venue_results/report.html); cumulative research is
**0/26 historical hurdle passes**, with no fresh holdout on the reused year.

The publisher requires three separate receipts: causal features, financial/gates,
and zero-admission proof. The latter applies only to this inactive cohort and
must fail if an economic entry is eligible. It does not certify generic
admission/exit/cleanup or omitted-fill logic for a future trading study. A new
trading cohort requires a corresponding independent policy/execution audit.
The original audit commands pin the preserved input paths and exact pre-outcome
Git lock; relocated/reacquired inputs need explicit new provenance rather than
silently rewriting that receipt. See the [publication workflow](cross_venue_publication_preparation.md).

The full-year BTC spot/perpetual/funding examples were also rerun in fresh
folders with the corrected current engine. Returns remain −12.17%, −11.46%
and +5.14%; the positive single example is not a qualified robust strategy.
[Current outputs, source hashes and commands](real_data_demo.md#current-engine-verification).
