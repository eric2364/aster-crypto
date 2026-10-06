# Positioning data: source preparation, no strategy outcomes

This input adds actual reported open interest and trader ratios to the minute
research platform. It does not implement a trading strategy or establish any
new successful family. The fixed year is 5 October 2025–5 October 2026 UTC,
exclusive at the end. It uses the same eight native Binance perpetual symbols;
PEPE stays `1000PEPEUSDT`.

## Verified reconnaissance

Root preserved 24 first/middle/last-day daily metrics ZIPs and a separate
24-file June transition sample. Every official checksum passed. An independent
review checked all 48 ZIPs, checksums and CSVs: 13,824 unique observations,
complete sampled five-minute clock sets and eight physically unordered files.
This is approximately 0.53 MiB compressed, not a claim of full-year coverage.

- [First/middle/last sample](../../docs/positioning_archive_probe.json)
- [Transition sample](../../docs/positioning_transition_probe.json)
- [Independent sample review](../../docs/positioning_probe_review.json)
- [Source feasibility and unit/timing hazards](../../docs/next_positioning_feasibility.md)
- [Next-factor decision](../../docs/next_factor_decision.md)

The original probe refuses to overwrite its receipt. Repeating it requires a
fresh `--receipt` path; a changed server body cannot overwrite captured raw data.
It inspects source integrity, schemas and clocks only, not numeric validity or
trading returns.

## Full-year collector

After source review, use:

```sh
.venv/bin/python examples/positioning/collect_archives.py \
  --out data_cache/positioning-metrics-1y --workers 4

.venv/bin/python examples/positioning/collect_archives.py \
  --out data_cache/positioning-metrics-1y --verify-only
```

The target corpus is 2,920 daily archives, with 105,120 five-minute observations
per native contract. Only a successfully checked `complete.json` establishes
completion. A command or partially populated directory is insufficient. Verified
raw pages may resume; existing source evidence and completed collections may
not silently change. Keep rejected, missing or conflicting data visible rather
than filling holes or altering timestamps to make the clock count match.

Reported `create_time` is retained alongside source file date and original row
index; normalization sorts observations after duplicate checks. Offset-free
labels use an explicit UTC interpretation. The collector makes no minute-grid
interpolation, feature, signal or execution. A five-minute factor can later be
used by a one-minute decision engine with explicit stale/availability handling;
this does not turn it into one-minute observations.

An archive downloaded now is a present vendor vintage. Its response retrieval
clock does not establish when its historical contents were public. REST timestamp
documentation does not independently establish the archive label's information
period. Historical revisions, clock semantics and historical unit definitions
remain constraints before causal predictions can be claimed. OI quantity and
OI value differ; aggregate OI contractions do not identify actual forced
liquidations. Ratio-based samples cannot identify individual traders.

Raw archives and full normalized evidence stay in ignored `data_cache`; source,
compact receipts, tests and limitations are versioned in the private repository.
No original source cache, frozen experiment, fee model or hurdle is modified.

## Actual complete acquisition

The reviewed collector was committed and uploaded privately at `241a650` before
full acquisition. The command completed all 2,920 archives and eight full-year
normalized streams. A separate `--verify-only` reconstruction passed with no
network requests. The independent auditor then checked all 840,960 observations,
5,045,760 numeric values, 8,760 raw files and 18 normalized/source files exactly.
There are 837 physically unordered source archives; their original labels and
row indices remain retained. Raw ZIPs total 33,686,440 bytes, and the local
dataset occupies 111,822,925 bytes excluding filesystem overhead.

[Compact evidence](../../docs/positioning_data/summary.json) ·
[Independent audit](../../docs/positioning_dataset_audit.md) ·
[Complete source seal](../../docs/positioning_data/complete.json).
No historical receipt or unit-definition certainty, predictor, trading result
or successful candidate is established by this acquisition.
