# Measured performance and capacity limits

Measured 6 October 2026 on Intel Core i9-13900H, Linux x86_64, Python 3.12.3, Pandas 3.0.6, NumPy 2.5.3. The machine reported 30 GiB physical RAM and approximately 19 GiB available before testing. Each benchmark is a separate process; one measurement per scenario, so these are reproducible observations, not statistical confidence intervals or throughput guarantees.

`benchmarks/run.py` generates deterministic synthetic data (seed 42). Event timing includes normalization, the full event schedule, mark/risk processing, strategy callbacks, execution/accounting, history retention and result DataFrames. Data generation is timed separately. Peak RSS includes interpreter, inputs, generation and all results; Linux `/proc/self/status` VmHWM is used. `resource.ru_maxrss` retained a 602 MiB pre-exec launcher high-water value even in a 9 MiB Python process, so it would have overstated small runs.

The no-op strategy submits no orders. Active MA observes every bar and trades the supplied engineering example with fees, slippage and margin accounting. Hourly MA observes/rebalances once per hour on minute input. All use linear perpetual instruments, cross margin, no funding input, and `record_every=100` except the full five-year run (`1000`). The retained snapshot cadence affects memory and analytics resolution. Performance runs are synthetic capacity checks; accounting/funding correctness is covered separately by tests and example backtests.

## Actual completed runs

| Workload | Mode | Rows / signal cells | Wall seconds | Bars/s or cells/s | Peak RSS MiB | Fills |
|---|---|---:|---:|---:|---:|---:|
| 1 symbol, minute | No-op | 10,000 | 0.147 | 68,170 | 135.9 | 0 |
| 1 symbol, minute | No-op | 100,000 | 1.628 | 61,417 | 345.6 | 0 |
| 20 symbols, minute | No-op | 100,000 total | 1.124 | 89,002 | 307.6 | 0 |
| 100 symbols, minute | No-op | 100,000 total | 1.140 | 87,736 | 310.6 | 0 |
| 1 symbol, second bars | No-op | 100,000 | 1.703 | 58,718 | 345.7 | 0 |
| 1 symbol, minute | Active MA | 10,000 | 0.718 | 13,918 | 175.6 | 9,914 |
| 1 symbol, minute | Active MA | 100,000 | 7.339 | 13,626 | 708.5 | 97,193 |
| 1 symbol, minute | Hourly MA | 100,000 | 2.034 | 49,167 | 353.2 | 1,642 |
| 1 symbol, 2020–2025 minute | No-op | 2,630,880 | 42.625 | 61,721 | 6,071.4 | 0 |
| 20 symbols, 2020–2025 minute | Vector MA signals | 52,617,600 | 1.318 | 39,918,822 | 2,536.8 | — |
| 100 symbols, 2020–2022 minute | Vector MA signals | 105,264,000 | 2.911 | 36,165,020 | 4,934.4 | — |

All counts above were actually executed. Five years includes both leap days: 1 January 2020 through 1 January 2025. Two years includes 731 days. Raw JSON and cProfile artifacts are in `benchmarks/results/`; later results include engine and portfolio SHA256 identities. Early results precede that metadata addition. Small initial no-op and active measurements preceded a baseline-snapshot adjustment; snapshot count can differ by one. This does not change their bar/fill workloads.

Vector runs time only two causal rolling means and comparison; input matrix construction takes another 1.011 seconds for 20×5 years and 2.046 seconds for 100×2 years. They do not run execution, cash accounting, fees, funding, margin, liquidation or portfolios. Their rates cannot be interpreted as event-engine throughput. The vector generator avoids constructing a redundant candle table to measure the intended matrix research layer.

The JSON reports `market_observations_per_second = 2 × rows / seconds`, representing each candle's opening and completion observations. For the five-year no-op this is 123,442 observations/s; active 100k is 27,251 observations/s. Distinct clock timestamps and emitted ledger-event counts are reported separately: active 100k emits 393,639 ledger rows (approximately 53,636 rows/s), while no-op emits none. These denominators must not be interchanged or presented as real exchange ticks.

## Independent profile finding and fixed bottleneck

Initial every-bar MA took 7.243 seconds for 10k bars. cProfile measured 7.924 seconds with `_eligible` at 4.024 cumulative seconds and `Context.target` at 2.575 seconds. Both scanned the complete historical order registry, giving quadratic growth even though nearly all historical orders were terminal.

The engine author removed filled/cancelled orders from the active registry while preserving audit ledgers. The same unprofiled scenario now takes 0.718 seconds, approximately 10.1× faster, with the exact same 9,914 fills and 5,301 completed trade records. A post-fix profile takes 1.325 seconds; strategy callbacks, filling and liquidation checks now dominate. Profiled and unprofiled runtimes are kept separate because instrumentation changes timing. Regression tests passed after this change.

## Explicitly unrun workloads

- Full **20 symbols × five years × minute** event simulation was not run. Its 52.6 million candle rows exceed the chosen 10 GiB process limit with the current dictionary schedule. The vector signal counterpart was executed above.
- Full **100 symbols × two years × minute** event simulation was not run. Its 105.3 million candle rows likewise exceed that limit. The vector signal counterpart was executed above.
- Full five-year every-bar active trading, seconds over multiple years, real ticks, and L2 queue matching were not benchmarked. The system does not implement L2 matching.
- No timings are extrapolated into claimed completed results. Full five-year no-op peak RSS demonstrates the current in-memory scheduler is the dominant scale limit; order-intensive ledgers add substantial additional memory.

## How to reproduce

From the repository root after installation:

```bash
python benchmarks/run.py --bars 10000 --mode noop
python benchmarks/run.py --bars 100000 --mode ma
python benchmarks/run.py --bars 100000 --symbols 100 --mode noop
python benchmarks/run.py --bars 100000 --duration 1 --mode noop
python benchmarks/run.py --bars 2630880 --mode noop --record-every 1000
python benchmarks/run.py --bars 52617600 --symbols 20 --mode vector
python benchmarks/run.py --bars 105264000 --symbols 100 --mode vector
python benchmarks/run.py --bars 10000 --mode ma --profile benchmarks/ma.prof
python -c 'import pstats; pstats.Stats("benchmarks/ma.prof").sort_stats("cumulative").print_stats(20)'
```

The large runs used `ulimit -v 10485760` before launching, capping virtual memory at 10 GiB; comparable memory headroom is needed to reproduce them.

## Next engineering work justified by measurements

1. Replace full DataFrame-to-dictionary event scheduling with a streaming merge of instrument/time iterators. Retain exact simultaneous timestamp batching and settlement priority tests.
2. Make strategy history bounded/opt-in and stream audit ledgers to Parquet instead of retaining every row as a Python dictionary. Snapshot downsampling alone does not bound current memory.
3. Keep causal factor/indicator research in matrix/array form. Use Pandas/NumPy now; evaluate Polars/Arrow storage and Numba kernels only where profiles demonstrate a benefit. Compiling the accounting state machine prematurely risks weakening tested event semantics.
4. Maintain a registry per instrument for active orders, benchmark active portfolios across 20/100 symbols, and test throughput with frequent funding and realistic pending limits. Cross-account risk scans can become the next scaling constraint.
5. Compare CSV versus partitioned Parquet loader latency and peak memory separately from simulation. Cached normalized datasets and content hashes preserve reproducibility without repeated parsing. Multiprocess parameter sweeps require measured per-worker RAM limits; naive duplication of six-GiB scenarios is unsafe on this machine.
