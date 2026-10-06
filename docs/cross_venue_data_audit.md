# Independent Bybit dataset audit

Status: the completed full-year sealed dataset passed the independent offline audit on October 6, 2026. The certificate has `complete: true` and `errors: []`. This establishes exact reconstruction of the cached candle grid and returned funding events; it does not register candidate 26 or prove historical funding completeness.

Run the independent, offline auditor after completion:

```sh
.venv/bin/python audit/verify_bybit_dataset.py --root data_cache/minute-bybit-1y --out audit/bybit_dataset_evidence.json
```

The auditor imports neither the collector nor its parsers, normalizer, verifier, or engine. It checks the collector and instrument model against committed source anchor `7d01b3e`, pins the recorded Python/NumPy/pandas/PyArrow runtime, and requires precisely the 25 expected normalized/catalog/manifest file hashes. It streams raw pages one market at a time, verifies envelope and HTTP-body hashes, exact canonical URLs, native identities, pagination bounds and progress, source schemas, and an uninterrupted minute grid from October 5, 2025 through October 5, 2026 (exclusive).

Every normalized OHLCV, turnover, mark OHLC, timestamp, duration, end, native instrument identity, funding rate, and boundary field must equal the independently reconstructed source. Native `1000PEPEUSDT` quantities and prices remain in bundle units. Funding source milliseconds are preserved exactly. Interior settlements must align to a source minute and use that minute's mark **open**; a present END settlement uses the final within-year completed mark close. No interpolation or outside-year warmup is permitted.

Current tick/lot/minimum rules come from the cached native metadata. Fee, maintenance, leverage, liquidation and nominal funding-interval defaults in the catalog are simulator assumptions, not historical exchange rules. Observed funding interval histograms report differences between actual returned timestamps; they cannot prove missing settlements are absent, establish historical cadence, or recover unpublished receipt times. Hashes establish consistency of the cached evidence with its seal, not independent authentication of vendor responses. Full candle coverage establishes only the exact returned candle grid.

The audit writes nothing inside the dataset and rechecks normalized files, the seal and raw envelopes before completing. Its compact certificate contains:

- `complete: true`, `errors: []`, the exact year, eight symbols and source commit;
- source/runtime hashes, auditor hash, 25 normalized file hashes, dataset seal hash and a digest of all raw envelope identities;
- each symbol's native identity, trade/mark/funding row counts, raw page counts by endpoint, first/last funding timestamps, observed interval histogram and proxy counts.

No mean rate, yield, signal, fit, return or profit is computed. Publication should pin the certificate bytes and retain its dataset seal hash.

Synthetic adversaries in `tests/test_bybit_dataset_independent.py` include recomputed seals over altered prices, volume units, duration/end, native identity, funding rate/millisecond/proxy/boundary fields, forged raw response identities and schemas, duplicate/out-of-grid candles, unsafe paths, missing/extra pages, changed native rules and source provenance. Synthetic fixture construction may call the collector offline; audit execution always calls the separate independent implementation.

## Completed source reconstruction

The certificate is [audit/bybit_dataset_evidence.json](../audit/bybit_dataset_evidence.json). All 25 normalized/catalog/manifest hashes, source/runtime provenance, 8,480 raw envelopes, raw HTTP-body hashes, canonical bounded requests, and every normalized source value passed. Dataset and raw evidence were rechecked at completion. The audited normalized data and collector were not modified.

Each of the eight native markets has 525,600 trade candles, 525,600 mark candles, and 1,096 returned funding events. Across all markets this is 4,204,800 trade candles, 4,204,800 mark candles, and 8,768 funding events. The candle grid covers October 5, 2025 00:00 UTC through October 4, 2026 23:59 UTC, with END excluded.

| Underlying label | Native contract | Trade / mark rows | Funding events | Raw pages | Interior / END proxies |
|---|---|---:|---:|---:|---:|
| BTCUSDT | BTCUSDT | 525,600 / 525,600 | 1,096 | 1,060 | 1,095 / 1 |
| ETHUSDT | ETHUSDT | 525,600 / 525,600 | 1,096 | 1,060 | 1,095 / 1 |
| DOGEUSDT | DOGEUSDT | 525,600 / 525,600 | 1,096 | 1,060 | 1,095 / 1 |
| PEPEUSDT | 1000PEPEUSDT | 525,600 / 525,600 | 1,096 | 1,060 | 1,095 / 1 |
| SOLUSDT | SOLUSDT | 525,600 / 525,600 | 1,096 | 1,060 | 1,095 / 1 |
| XRPUSDT | XRPUSDT | 525,600 / 525,600 | 1,096 | 1,060 | 1,095 / 1 |
| LINKUSDT | LINKUSDT | 525,600 / 525,600 | 1,096 | 1,060 | 1,095 / 1 |
| ADAUSDT | ADAUSDT | 525,600 / 525,600 | 1,096 | 1,060 | 1,095 / 1 |

For every market, the first returned settlement is October 5, 2025 00:00 UTC and the last is October 5, 2026 00:00 UTC. Each observed interval histogram is `{480.0 minutes: 1,095}`. This is a statement about returned event differences, not proof of a complete historical payment schedule. Per market, the raw receipts contain one current instrument response, 526 trade pages, 526 mark pages and seven funding pages including the explicit END request. Native PEPE remains `1000PEPEUSDT` with current source lot size 100 and multiplier 1.

Pinned evidence:

- Certificate SHA-256: `e62cd5a9ca3222fa1dbdac7467f9b45051495415d60d3a98c0c124deae2c8d45`.
- Dataset seal SHA-256: `298565174c6d9bc580d93a24412b285c80e526578ca7502c284ce45a6fee534c`.
- Auditor source SHA-256: `5a9d04b7d3f2a4bd83bcb2cff3b35b9318d8ce2b265a1dce1223028bffef7edd`.
- Raw envelope identity digest: `b0b8f9f7194736bd94c86f85455b73db18d6ba087f931ffa872198c5360035d1`.
- Collector and instrument model were checked against committed source `7d01b3e`; their exact hashes and runtime versions are recorded in the certificate.
- Independent auditor plus existing collector synthetic suite: 64 tests passed.

The research result remains 0/25 qualifying candidate families. This source audit performs no economic evaluation and adds no successful strategy.
