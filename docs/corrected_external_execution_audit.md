# Independent corrected external execution audit

**PASS for all 400 corrected external executions, dated 2026-10-06. None of the five hypotheses meets its unchanged historical hurdles.** The [compact certificate](corrected_external_execution_audit.json) pins the complete receipt, frozen sources, economic protocol, summaries, training selection and full execution-seal manifest. Original external outputs remain preserved separately.

The read-only audit checked 37 frozen source files, 79 frozen inputs, exactly 400 distinct requested trajectory identities and 6,400 sealed exports. Every cash/equity snapshot, native signed quantity, actual funding payment and its original settlement mark/rate, execution fee, realized/open PnL attribution, terminal inventory, liquidation count and indicative exit reserve reconciled. PEPE perpetual quantities remain native 1000PEPE units.

An independent event-order replay reconstructed the proportional isolated reserve at every equity snapshot and terminal position. All 5,742 partial exits passed. There were zero actual liquidation events across the corrected external training, validation, evaluation neighbors and joint stress cases. This is the corrected external cohort's observed result; it does not erase the 23 genuinely unhealthy corrected carry liquidation fills or imply all original derivative liquidations were artifacts.

Training-only common-scale selection was recomputed from sealed training results. A temporary-directory rebuild reproduced the complete published summary, event deduplication, metrics, unchanged gates and baseline/stress pooled equity exactly. No new simulations, threshold tuning, substituted fills or artificial terminal close were used by this audit. Final publication must recheck the pinned 16-file seal for every trajectory.

Reproduce from the repository root:

```bash
.venv/bin/python audit/verify_corrected_external.py --final
.venv/bin/python -m pytest -q
```

The completed test run passed 295 tests. Focused regressions verify proportional reserve arithmetic, rejection of cash-conserving residual-margin artifacts, rejection of liquidation while modeled margin is healthy, and inactive trials with empty-schema ledgers. Publication guards also preserve the original eight spot summaries and pooled histories against their previously published anchors.

This certificate verifies the declared model and exported arithmetic. It does not establish exact historical exchange liquidation rules, intraminute liquidity, queue priority, true historical data receipt times, absence of overfitting or prospective profitability. The examined year remains reused exploratory evidence; the requested four or five robust successful examples have not been established.
