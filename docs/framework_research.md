# Crypto backtesting framework research

Research date: **6 October 2026, Asia/Hong_Kong**. GitHub API retrieval began at 2026-10-05 19:38 UTC (2026-10-06 03:38 HKT). This is a point-in-time snapshot, not an ongoing monitor. No source project was cloned or incorporated into this repository.

## Recommendation

Build an original hybrid platform: array-oriented signal research, followed by deterministic event-driven execution and explicit accounting. NautilusTrader supplies the strongest execution architecture reference; VectorBT supplies array/broadcasting ideas; LEAN supplies replaceable reality models; Hummingbot supplies exchange connectors and executor/controller separation; HftBacktest supplies queue and latency concepts. Crypto funding and margin need their own ledger and causal event timeline.

This recommendation is an engineering inference from the primary documentation below, not a claim that a custom Python implementation matches the performance or production maturity of those frameworks. No cross-framework runtime benchmark was performed. Stars indicate visibility, not simulation correctness.

## GitHub maintenance snapshot

Values were fetched from `https://api.github.com/repos/{owner}/{repo}` plus `/commits?per_page=1`, `/contributors?per_page=1`, and `/releases?per_page=5`. Contributor counts use the pagination last-page index with one result per page, exclude anonymous contributors, and reflect GitHub's cached contributor representation. Default-branch commit time differs from repository push time (which can include other branches). Open counts include pull requests; they are not issue-only counts. Release dates are UTC dates. Empty release lists mean no GitHub Releases returned, not no package releases. License identifiers are GitHub metadata, not legal interpretation.

| Project / primary repository | Stars | Contributors | Latest default commit | Open issues + PRs | Latest GitHub release | License |
|---|---:|---:|---|---:|---|---|
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | 29,639 | 208 | 2026-10-05 | 156 | v2.0.0rc6 / 2026-10-05 | LGPL-3.0 |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 9,277 | 22 | 2026-09-26 | 139 | v1.1.1 / 2026-09-26 | NOASSERTION |
| [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | 21,864 | 217 | 2026-10-05 | 260 | v2.4.0.1 / 2017-08-08 | Apache-2.0 |
| [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | 20,309 | 234 | 2026-09-22 | 182 | v2.17.0 / 2026-09-22 | Apache-2.0 |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | 55,050 | 341 | 2026-10-05 | 29 | 2026.9 / 2026-09-29 | GPL-3.0 |
| [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | 8,612 | 51 | 2026-10-01 | 16 | None returned | MIT |
| [mementum/backtrader](https://github.com/mementum/backtrader) | 23,400 | 48 | 2023-04-19 | 63 | None returned | GPL-3.0 |
| [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | 9,011 | 45 | 2026-08-05 | 93 | None returned | AGPL-3.0 |
| [stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | 1,952 | 118 | 2025-11-13 | 48 | 3.1.1 / 2025-07-23 | Apache-2.0 |
| [mhallsmoore/qstrader](https://github.com/mhallsmoore/qstrader) | 3,472 | 14 | 2024-06-24 | 16 | v0.3.0 / 2024-06-24 | MIT |
| [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest) | 4,857 | 22 | 2025-12-23 | 22 | rust-v0.9.4 / 2025-12-10 | MIT |
| [Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot) | 6,679 | 20 | 2026-09-21 | 171 | 3.0.0-beta2 / 2026-08-06 | GPL-3.0 |

All repositories returned `archived=false`. Observed release cadence from the latest five GitHub releases: Nautilus 12–20 days between recent release candidates; VectorBT roughly one to three months; Freqtrade approximately monthly; Hummingbot roughly six to eight weeks; Zipline-reloaded uneven, months apart; QSTrader's last releases clustered in 2024; HftBacktest's latest releases clustered in August–December 2025. LEAN's GitHub Releases stop in 2017 despite current commits, so that endpoint is a poor maintenance proxy. Jesse, Backtrader, and Backtesting.py returned no GitHub Releases: inspect package indexes/tags before choosing a pinned dependency. OctoBot's cadence is shown by its release endpoint and latest date above.

Issue activity was sampled using `/issues?state=all&sort=updated&direction=desc&per_page=5`; this includes PRs and closed items. It measures most recent discussion/update, not maintainer responsiveness or resolution rate. Latest sampled activity:

| Repository | Most recently updated sampled issue or PR | Updated UTC | State | Kind |
|---|---|---|---|---|
| nautechsystems/nautilus_trader | [#5236](https://github.com/nautechsystems/nautilus_trader/pull/5236) | 2026-10-05T19:17:22Z | open | PR |
| polakowo/vectorbt | [#862](https://github.com/polakowo/vectorbt/pull/862) | 2026-10-05T11:35:21Z | open | PR |
| QuantConnect/Lean | [#9868](https://github.com/QuantConnect/Lean/pull/9868) | 2026-10-05T19:08:03Z | closed | PR |
| hummingbot/hummingbot | [#8496](https://github.com/hummingbot/hummingbot/pull/8496) | 2026-10-05T16:10:17Z | open | PR |
| freqtrade/freqtrade | [#13639](https://github.com/freqtrade/freqtrade/pull/13639) | 2026-10-05T18:05:51Z | closed | PR |
| jesse-ai/jesse | [#626](https://github.com/jesse-ai/jesse/pull/626) | 2026-10-01T15:03:22Z | closed | PR |
| mementum/backtrader | [#525](https://github.com/mementum/backtrader/pull/525) | 2026-10-05T11:28:05Z | open | PR |
| kernc/backtesting.py | [#1419](https://github.com/kernc/backtesting.py/pull/1419) | 2026-10-05T18:48:56Z | open | PR |
| stefan-jansen/zipline-reloaded | [#330](https://github.com/stefan-jansen/zipline-reloaded/pull/330) | 2026-10-05T10:38:35Z | open | PR |
| mhallsmoore/qstrader | [#407](https://github.com/mhallsmoore/qstrader/pull/407) | 2026-10-05T10:34:44Z | open | PR |
| nkaz001/hftbacktest | [#319](https://github.com/nkaz001/hftbacktest/pull/319) | 2026-10-05T10:09:50Z | open | PR |
| Drakkar-Software/OctoBot | Not sampled | Unavailable | Unavailable | Unavailable |


Maintenance conclusion: Nautilus, LEAN, Freqtrade, Hummingbot, Jesse, and VectorBT have recent default-branch commits. Backtrader and QSTrader have materially older core activity. HftBacktest has current community PR/issue discussion but its default branch last changed in December 2025; this is a maintenance caveat, not evidence of abandonment. Zipline-reloaded is maintained as a compatibility fork, with slower recent core change. Pin versions and rerun compatibility checks; documentation can describe newer branches than an installed wheel.

## Architecture and capability comparison

“Extension” means the reviewed public interface does not establish a complete native model suitable for this requirement; it does not mean implementation is impossible. Live connectivity does not establish historical replay accuracy. Exchange support depends on the adapter, instrument and version.

| Framework | Architecture / API | Markets and data | Execution / derivatives considerations | Analytics and research | Fit here |
|---|---|---|---|---|---|
| NautilusTrader | Deterministic events; Rust-native v2 core, Python control plane; strategy callbacks | Multi-venue/multi-asset; bars, quotes, trades, books; crypto adapters including Binance, Bybit, OKX | Rich orders/TIF; fill, fee, latency and margin components; live/backtest code reuse; venue rules must be validated | Accounting and reports; dashboard separate | Primary domain/event-loop reference |
| VectorBT (public OSS) | NumPy/Pandas arrays, Numba simulation loops; `Portfolio.from_signals/from_orders` | Large multi-asset/time/parameter arrays; user-supplied data | Fees/slippage and order records; funding/venue liquidation require explicit custom modelling | Broadcasting, sweeps, trade/drawdown records and plots | Research layer, not execution authority |
| LEAN | C# event engine with Python algorithms; `initialize`, `on_data` | Multi-asset subscriptions; crypto and crypto futures; trades/quotes/bars | Brokerage, fill, fee, slippage, buying-power and settlement model interfaces; live reuse | Rich stats, optimization ecosystem and reporting | Replaceable model interfaces |
| Hummingbot | Async/Cython/Python connectors; V2 controllers, finite executors, market-data provider | Crypto CEX/DEX; candles, order books and trades; multiple connectors | Strong live order lifecycle/perpetual connectivity; backtest realism must be established per controller/executor | Dashboard and Quants Lab ecosystem | Connector boundary and executor patterns |
| Freqtrade | Python/Pandas candle bot; strategy dataframes and callbacks | Crypto spot/futures and multiple pairs; CCXT exchanges | Fees, leverage and historical funding support; cross-margin simulation caveats; detail timeframe improves candle resolution | Hyperopt, lookahead analysis, web UI and result exports | Research workflow and adversarial tooling |
| Jesse | Candle replay; `should_long/short`, `go_long/short`, position callbacks | Crypto spot/perpetual routes; multiple symbols/timeframes | Leverage and liquidation; documented backtest funding=0 and mark=trade price; one exchange/data source per run | Optimization, metric panels, interactive trade charts | Strategy API and dashboard ideas |
| Backtrader | Python `Cerebro`, `Strategy.next`; indicators optionally batch-evaluated | Multiple feeds/timeframes and assets; futures-like commission schemes | Orders/slippage/volume-fill hooks; crypto funding, venue margins and liquidation require extensions | Analyzers, optimization, matplotlib | Readable broker decomposition; old core maintenance |
| Backtesting.py | Precomputed indicators + `Strategy.next`; `Backtest.run/optimize` | Primarily single OHLCV stream; fractional extension | Spread, commission, generic margin, market/limit/stop orders; no demonstrated crypto funding/book simulator | Compact stats and interactive charts; SAMBO optimization | Simple strategy ergonomics |
| Zipline-reloaded | Event-driven Python/Cython; `initialize`, `handle_data`, bundles | Equity-oriented calendars, asset metadata and Pandas research | Commission/slippage model architecture; crypto derivatives need extensions | Factor research/PyData performance outputs | Historical identity/universe concepts |
| QSTrader | Modular schedule-driven portfolio construction | Long/short equities and ETF portfolios, generally lower frequency | Signal, risk, portfolio and brokerage modules separate; no reviewed native perpetual/book stack | Tearsheet and JSON statistics | Allocation/risk separation |
| HftBacktest | Rust/Python/Numba specialist tick replay | L2/L3, trades; Binance/Bybit examples | Explicit feed/order latency, queue and partial-fill models; replay has no endogenous impact | HFT/MM notebooks and recorder analysis | Future microstructure model reference |
| OctoBot | Python crypto bot, modular packages and visual interface | 15+ exchange integrations; automated/live/paper/backtest workflows | Current beta has a new node/interface architecture; complete funding/liquidation replay not verified | Strategy optimizer and visual workflow | Additional actively evolving crypto candidate; not accounting authority |

Sources for the table are the linked repositories above and specific primary documentation below. Proprietary VectorBT Pro features were not assumed to exist in the public OSS repository; no Pro code or subscription was inspected.

## Documentation assessment

These are reviewer judgments based on the pages inspected, not measured quality scores. Nautilus and LEAN have extensive concept/API references, but Nautilus's release transition makes version matching essential. VectorBT has deep API and array examples, with a learning curve around broadcasting and Numba callbacks. Freqtrade provides unusually useful operational caveats, CLI examples and backtest bias tooling. Hummingbot explains its component hierarchy clearly; live and historical capabilities still require separate verification. Jesse provides accessible strategy and dashboard references with explicit backtest field restrictions. Backtrader has broad tutorials whose age warrants compatibility checking. Backtesting.py has a concise navigable API. Zipline-reloaded documents dependency migration and PyData integration; QSTrader is readable but equities-focused. HftBacktest is candid about replay assumptions and has specialist queue/latency material. OctoBot's public docs emphasize workflow and deployment; exchange-accounting details need a deeper code audit.

## Findings that affect correctness

### NautilusTrader: best execution reference, evolving version boundary

The current README describes a Rust-native v2 engine and Python orchestration. The latest release is `v2.0.0rc6`; v1/v2 APIs and available models must not be conflated. Multi-venue instrument identity and deterministic event replay are the architectural ideas to adopt. A strategy shared with live execution still needs reconciliation and venue-specific validation. [Repository architecture](https://github.com/nautechsystems/nautilus_trader), [accounting](https://nautilustrader.io/docs/latest/concepts/accounting/).

Limit-touch eligibility is configurable; default eligibility is optimistic for a conservative candle engine. Recorded order-book replay also needs explicit consumed-liquidity assumptions. L2/L3 observed depth cannot answer how the world would respond to our order. Therefore conservative crossing eligibility and aggregate volume budgets belong in our simulator, with separate labels for synthetic and recorded books. [Fill models](https://nautilustrader.io/docs/latest/concepts/backtesting/fill-models/).

### VectorBT: arrays for research, explicit time alignment

The public portfolio implementation broadcasts data and sends NumPy arrays into Numba loops, then derives reports from order and trade records. Its own examples shift signals to avoid future information. Adopt this array pipeline for causal indicators and parameter screening; pass approved signals to the event simulator. A fees/slippage parameter does not establish a historical funding or exchange liquidation model. Dense parameter tensors can consume substantial RAM, so batch sweeps. [Portfolio implementation documentation](https://vectorbt.dev/api/portfolio/base/), [Numba interfaces](https://vectorbt.dev/api/portfolio/nb/).

### LEAN: model contracts over engine conditionals

LEAN exposes separate models for brokerage constraints, fills, fees, slippage, buying power, and settlement. This supports replaceable venue behavior and isolated tests. Crypto futures are a supported security type, but instrument support does not prove that all exchange funding and insurance-fund behavior is represented. Check the pinned brokerage/security models. The C# engine also introduces an operational stack larger than a compact local Python MVP. [Reality models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts), [crypto futures subscriptions](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/crypto-futures/requesting-data).

### Hummingbot: live order management and venue boundaries

V2 separates continuous controllers from finite execution workflows and gives them a common market-data provider. This is useful for cross-exchange hedging and eventual live adapters. Keep market-data normalization outside accounting and preserve exchange-specific errors and order acknowledgements. A controller being backtestable should not imply that its historical simulation reconstructs queue position, funding settlement or liquidation tiers. [V2 architecture](https://hummingbot.org/strategies/v2-strategies/).

### Freqtrade: mature workflow, documented approximations

Futures mode uses historical funding and mark data, but substituting missing funding makes results inaccurate. Cross-position collateral influence may not be fully represented during dry-run/backtesting. Candle-based fills and intrabar order sequencing remain assumptions; detailed lower-timeframe data reduces ambiguity without supplying actual book priority. Adopt funding availability checks, static reproducible historical universes and lookahead audits. [Leverage and funding limitations](https://www.freqtrade.io/en/stable/leverage/), [backtesting and dynamic pairlist limitations](https://www.freqtrade.io/en/stable/backtesting/).

### Jesse: strong UX, funding backtest gap

Its documented strategy API returns zero for backtest funding rate, `None` for next funding time, and uses strategy price for mark price. Consequently a profitable funding strategy cannot be validated by that interface alone. The candle strategy API and performance chart design remain useful. Its documentation also states that multiple exchanges/data sources in one run are unsupported. [Strategy API](https://docs.jesse.trade/docs/strategies/api), [traditional-market/multi-route limitations](https://docs.jesse.trade/docs/traditional-markets/), [result charts](https://docs.jesse.trade/docs/charts/).

### HftBacktest: specialist replay with explicit limits

This is the most relevant additional specialist for market making: queue, feed latency, order latency, and tick/book replay. Its docs explicitly state that replay cannot alter the market; taking large liquidity can be unrealistic even under a partial-fill model. A risk-averse queue model advances on trades rather than assuming cancellations ahead. These assumptions should inform future L2 models, not be claimed for an OHLC engine. [Fill and queue models](https://hftbacktest.readthedocs.io/en/latest/order_fill.html), [latency models](https://hftbacktest.readthedocs.io/en/latest/latency_models.html).

### Legacy and supplementary frameworks

Backtrader provides broad order and commission hooks and multi-feed handling, but its old default-branch commit is a dependency risk. Avoid importing its optional cheat-on-close behavior into the default causal model. [README](https://github.com/mementum/backtrader).

Backtesting.py offers accessible `init/next` strategy methods and clear reports; generic margin is not perpetual collateral/funding accounting. Its single-series orientation is a poor core for multiple venue wallets. [API](https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html).

Zipline-reloaded retains useful event/data-bundle integration and asset handling while updating PyData compatibility. QSTrader explicitly separates allocation, risk, execution and brokerage; its schedule-driven equities scope differs from HFT crypto replay. Borrow the modularity and historical instrument identity ideas. [Zipline README](https://github.com/stefan-jansen/zipline-reloaded), [QSTrader README](https://github.com/mhallsmoore/qstrader).

OctoBot is an additional crypto-native candidate with current development, exchange connectivity, optimization and a visual interface. Its newest node/interface release is beta, and this review did not independently establish exchange-accurate derivatives replay. [OctoBot README](https://github.com/Drakkar-Software/OctoBot).

## Original architecture decisions derived from research

1. **Causal timeline:** data has exchange/event time and availability time; bar close signals cannot fill at that same historical close. Stable event ordering must define mark updates, funding eligibility, liquidation and order activation at coincident timestamps.
2. **Exchange isolation:** instrument identity includes venue and market type. Each venue has independent cash/collateral, fee schedules and margin rules. No implicit instant transfer or cross-venue collateral sharing.
3. **Distinct accounting:** spot exchanges cash for inventory; linear perpetuals realize signed quantity × price change without buying the full notional. Funding is a dated cash flow, separate from trade execution and fees.
4. **Replaceable models:** fill, latency, slippage, fee, margin and liquidation models receive typed state/events. Profile files describe assumptions; they are not representations of an exchange's current complete rulebook.
5. **Two strategy paths:** array signals and event callbacks share instrument identifiers and availability rules. Screening results require event simulation before execution-sensitive conclusions.
6. **Conservative candle mode:** do not infer queue priority from OHLC. Require an order to be active before the eligible interval, separate touch/cross rules, and share participation capacity across orders. Report uncertainty for intrabar stops and mark-price liquidation.
7. **Append-only evidence:** event/fill/funding ledgers plus run configuration, data fingerprint and seed feed accounting reconciliation and reports. Report gross trading P&L, execution costs, funding and liquidation fees separately.
8. **Performance after correctness:** arrays and columnar Parquet storage first; then measured hot loops, optional Numba/Polars, chunked sweeps and processes. No unmeasured “millions of events per second” promise.
9. **Honest MVP boundary:** implement spot and linear isolated perpetuals first. Cross margin, inverse contracts, exchange liquidation tiers, actual L2 queue replay and live connectivity require additional verified work.

These are new design decisions, not copied source implementations. License metadata is recorded for dependency evaluation; no framework is a mandatory runtime dependency. Metrics and benchmark results for this repository must be independently verified rather than inherited from framework marketing claims.
