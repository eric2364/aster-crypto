# Independent positioning financial-verifier source review

Reviewed `audit/verify_positioning_outputs.py` SHA-256 `3a02bce3e6d4f142200484d3833faff9ce0c85025583efcb2d81830516739d95` against the candidate-28 source anchor `290c9b755290a382d696ac86f83a1fbec7ee1fe5` and input anchor `7aa7830878821ed4819f2b2feac51cbd9fe1e82c`. This is a preparation/source review, not a certificate of the actual historical study. The reviewer did not read historical outcomes, generate real features, run historical strategies, or modify frozen economic sources.

The verifier independently reconstructs recorded fills against native minute bars, prior volume, order activation/cancellation, costs and funding; replays wallet cash, current-mark cross margin, positions, trades and the 63-field observer; and checks actual completed entry-and-flat-exit episodes rather than counting entry intents as activity. It binds all five exact phases, 26 exports and each completion seal, source/runtime/input bytes, the independent feature certificate, descriptive metrics, exit reserves, all fifteen gates and the fixed candidate-28 conditional bootstrap. Native PEPE remains `1000PEPEUSDT`; no implicit quantity rescaling is permitted.

A material initial-validation gap was found and repaired by the author: evidence hashes originally followed the first provenance guard. The final implementation captures all evidence before that guard, checks it immediately afterward and preserves the original capture through the end. Independent adversaries change the auditor itself, arithmetic helper, publication receipt, feature receipt and a feature file during that first call; all fail before certificate/numeric verification. Later-phase and final output mutation checks also remain in place.

The new reconstruction loop was compared by Python AST with the previously reviewed independent financial helper (`audit/verify_funding_rank_outputs.py`, SHA-256 `e1190736baf95ab59ae9712401057b1caa82c8e863426ca94393ae66357d14ef`). Its sole arithmetic-loop addition captures pre-callback marks, entry averages and whether liquidation already occurred for a future policy audit. Three synthetic differential cases, including stress/native PEPE and volume-limited DOGE, produce identical quantities, cash, trades and pre-callback account states. There are no imports from production strategy, runner, feature or engine modules in the financial verifier or its arithmetic helper.

Independent tests in `tests/test_positioning_financial_review.py` use a tiny manufactured Engine/export cohort as test input, then independently reparse it. A valid positive baseline is established before adversaries reseal changed metrics, closure aliases, proposal/rejection exports, native legs, minute equity, terminal sub-epsilon inventory and executed identity. The tests also reject changes made during reconstruction. Joint verification command:

```sh
.venv/bin/python -m pytest tests/test_positioning_financial_review.py tests/test_positioning_financial_audit.py -q
```

Result: **84 passed in 8.60 seconds** (29 independent-review cases plus 55 author cases). No remaining material blocker was identified for the explicitly financial scope of these reviewed bytes.

The author subsequently added nine provenance/certificate adversaries without
changing the reviewed auditor bytes. Root reran the combined suite:
**93 passed in 8.96 seconds** (29 independent and 64 author cases).

This scope does **not** reconstruct whether every eligible decision was logged, whether unlogged admissions were omitted, or whether all recorded intentions follow the economic policy. Accordingly, `policy_reconstruction_complete`, `recorded_policy_reconstruction_complete` and `publication_ready` remain false even when the financial certificate passes. Actual financial reconstruction and a separately reviewed policy audit are still required before publication. Historical metric units, delivery/vintage and latency remain declared limitations; a financial audit cannot establish a profitable or unexamined-year result.
