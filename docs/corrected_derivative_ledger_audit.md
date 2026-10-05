# Independent corrected derivative ledger audit

The accounting correction releases only the closed quantity's proportional isolated reserve. Closed-leg realized P&L and execution fees already affect wallet cash; they do not additionally alter the remaining position's allocated reserve. Funding remains a cash payment and a change in the position's isolated allocation, with the closed fraction released proportionally. A reversal creates a new reserve for the new leg. Cross margin continues to use wallet equity and mark-based margin.

Independent hand and actual Engine volume-limited IOC cases cover long/short, partial wins/losses, execution fees, accrued funding, reversal, genuine residual liquidation and unchanged cross margin. The independent Engine tests are [test_partial_exit_engine_audit.py](../tests/test_partial_exit_engine_audit.py); these synthetic cases do not select a model or inspect new historical profitability.

## Historical rerun scope

The driver reruns the declared carry120, signed480 and external400 trials in fresh folders, preserving original results and the 24-candidate search count. Each new economic protocol equals its original protocol. The corrected training procedure can legitimately choose a different common scale; retaining an old scale despite changed training accounting would change that procedure. The reused final-quarter evaluation remains exploratory.

Carry's original executed runner hash is `b7ed468bd3803aef96a34a046aa99cd39b0d6a482ccc95b76b080e5b80190c3f`; current rerun hash is `8c88696b8af0e1db76009bd3362e51273725359438922b7aa91b4734fe168b2a`. Independent AST comparison confirms identical `MatchedCarry`, `common_step`, `decisions`, `published_factors`, `rotation_signals`, `freeze`, `run_job`, `aggregate` and `summarize` definitions. Changed definitions are `interval` (copied timestamps cast to nanoseconds for the bootstrap endpoint), `report` and `main`; `analyze_existing` was added for the previously documented postprocessing repair. Execution and economic model definitions are unchanged; the carry runner file is not byte-identical to the original. The signed runner is byte-identical to its original executed snapshot (`d49a353c9fe3ef1904d9c58da246cd1a0c8b58f55ae6b84dc5f183f014f0dd67`). In inspected original/current trial metadata, the package hash change is confined to `aster/backtest/portfolio.py`.

## Independent arithmetic replay

Run from the repository root:

```bash
.venv/bin/python examples/research_review/audit_corrected_ledgers.py
```

The read-only [auditor](../examples/research_review/audit_corrected_ledgers.py) imports no engine or strategy. Its [machine-readable progress report](../results/margin-correction-rerun/independent_ledger_audit.json) owns carry120 and signed480; a separate independent reviewer owns external400. A report with `complete=false` certifies only listed completed trials, not the eventual full cohort. Final publication additionally requires `sealed=true`, generated with `--seal`; each trial then has `output_sha256` covering all six CSV/Parquet ledgers plus metadata, metrics, source manifest and quality JSON (16 files).

For each exported trial it compares economic config, instruments, trial identity and dataset fingerprints to the corresponding original. Current package/model hashes must match the correction freeze. A legitimate corrected-training selection change is explicitly recorded rather than silently forced to match the original scale. Same-timestamp events are replayed in original event order, using each `FEE` event to associate its actual fill and each `FUNDING_PAYMENT` event to associate its settlement.

Independent arithmetic reconstructs native quantities, weighted entry prices, realized P&L, cash fees, funding cash and allocation, proportional isolated reserves, reversal resets and liquidation penalties. Every actual forced fill must have independently unhealthy local margin at its recorded reference mark. Terminal quantities, collateral, accrued funding, retained entry fees, marked equity and closed/open P&L attribution must reconcile. No counterfactual fill, interpolation, collateral transfer or artificial terminal close is introduced.

This audit does not prove exchange-realistic intraminute liquidity, queue fills or historical fee tiers. It verifies the declared minute model's ledgers and the specific corrected reserve semantics. All 1,000 trials and independent cohort audits are complete. The [published comparison](margin_correction_results/report.html) retains original and corrected outcomes; zero of 24 candidates passes every unchanged historical hurdle. The separate [external audit](corrected_external_execution_audit.md) covers the remaining 400 trials.

## Final600-trial certificate — 2026-10-06

**PASS for carry120 and signed480 independent arithmetic replay.** The final receipt has `complete=true`, `sealed=true`, `errors=[]`, all600 unique trial paths and16 execution-file hashes per trial (9,600 sealed exports). Receipt SHA-256: `716f58087aa8c044707bf9da0d2c3ee00d299e5681442005b3e501b058b85759`. The [compact certificate](corrected_derivative_ledger_audit.json) also records the auditor and rerun-lock hashes.

| Cohort | Passed trials | Partial exits | Actual liquidation fills | Trials retaining terminal inventory | Sealed files |
|---|---:|---:|---:|---:|---:|
| Carry |120|6,704|23|63|1,920|
| Signed |480|2,312|0|203|7,680|

All23 carry forced fills were independently below the modeled isolated requirement at their recorded reference marks. Signed has no forced fills in these480 corrected trials. These counts cover all training/validation/evaluation/stress cases in each cohort, not just selected final evaluation. Terminal positions are real marked inventory; a retained position is not a fabricated close. No selected-scale comparison fallback was needed: corrected selected scale paths match original selections.

The external400 cohort is excluded and still requires its separate independent certificate. This accounting pass does not assert profitable policy hurdles, future robustness, untouched evaluation or exact real exchange liquidation/fill behavior. The publisher must recheck all sealed hashes before copying these corrected results.
