# Independent positioning policy scope

`audit/verify_positioning_policy.py` is separate from the frozen candidate 28 model and financial auditor. It imports no production strategy, signals, runner or Engine. Its reference uses already independently reconstructed pre-callback quantities, venue accounts, source marks and actual average entry prices. This matters because callbacks occur after completed-price marks and funding settlement, before the current minute's open fills. A same-clock future open fill cannot justify an earlier completed entry.

The actual preserved [scoped certificate](../audit/positioning_policy_evidence.json)
now passes all five fixed phases. It examines **395,995 actionable in-phase
minute callback clocks**, 76,344 resolved idle review clocks, and all 49 recorded
proposals. Those produced 48 completed entries and 44 successfully closed
episodes across the five separate accounts. Opening a complete entry alone
does not establish a completed successful episode. The callback domain is
`phase_begin < clock < phase_stop`: no prior close triggers a start callback,
and the coordinator returns at the stop boundary. The financial certificate
separately covers all 396,409 minute/settlement equity snapshots and actual
terminal inventory/orders. The original economic and execution sources remain
unchanged; no strategy simulation was rerun to alter these checks.

The pure `verify_policy` helper examines every actual minute callback in each phase. At five-minute review clocks, it recomputes eligibility from certified quantity and price features and the fixed native priority. In independently accounted, resolved, non-cooldown idle windows it rejects omitted eligible proposals. Every recorded proposal must have exactly one genuine admission outcome: either a correctly reasoned rejection and no entry, or a correctly sized entry and no rejection. Native quantity uses exact decimal fractions and the fresh 10% equity budget; current-mark cross-margin, tick-rounded adverse execution, fees, minima and reserve checks are recalculated. The submitted actual order IDs, native target vector, market GTC/reduce-only status, direction, activation and immutable five-minute deadline must agree.

Recorded entry completion requires actual fully filled order evidence visible before that callback, the immutable target quantities, actual last-fill completion time and actual fill VWAP. Four-hour holding uses the last actual entry fill, rather than intent or callback observation. Validity, stale age, adverse known closed price and mandatory holding exits are checked every minute while the recorded position is active. An exit diagnostic must link to actual same-callback immutable reduce-only targets; early or invented exit reasons fail. Actual resolved flat plus a full one-hour cooldown is required. A normal-flat declaration requires an actual exit transaction, and abort-flat requires a recorded abort/blocked state; invented cooldowns cannot mask idle eligibility. A normal successful closure must export its completed episode, and an opening completion cannot substitute for a fully closed successful episode. Terminal request timing is checked at exactly stop minus ten minutes.

The wrapper `verify_cohort` composes a separate passing financial certificate and causal feature certificate. It retains the financial certificate's policy and publication flags as false. All five phases' 26 outputs and completion receipts, both sixteen-file feature variants, all source/input/summary packet hashes, financial and reference-helper implementations, its own implementation, and certificate bytes are pinned before validation and checked again after the final provenance guard. The wrapper repeats independent ledger arithmetic, not an Engine simulation. Its CLI writes only a fresh certificate path.

```bash
.venv/bin/python audit/verify_positioning_policy.py \
  --perp-cache data_cache/minute-perpetual-1y \
  --metrics-cache data_cache/positioning-metrics-1y \
  --out results/positioning-rebound-1y-v1 \
  --source-anchor 290c9b755290a382d696ac86f83a1fbec7ee1fe5 \
  --input-anchor 7aa7830878821ed4819f2b2feac51cbd9fe1e82c \
  --feature-audit audit/positioning_feature_evidence.json \
  --financial-audit audit/positioning_output_evidence.json \
  --certificate audit/positioning_policy_evidence.json
```

This command is for separately authorized completed outputs after synthetic review. No historical output has been read during preparation.

The scope is deliberately bounded. The helper does not independently simulate every ABORTING/BLOCKED cleanup-state transition. Omission completeness outside resolved audited idle windows is not proved. Its certificate therefore keeps `policy_reconstruction_complete`, `full_cleanup_state_reconstruction_passed`, `all_unlogged_abort_transitions_proved` and `publication_ready` false, while distinguishing successful scoped recorded-policy reconstruction. The publisher must preserve these limitations when composing financial, causal and policy evidence; it must not relabel the result a complete lifecycle proof.

Twenty-five author hand cases and twenty-five independent reviewer cases pass (50 targeted tests). The standalone CLI is tested from an unrelated working directory with only missing inputs, reaching a file guard without producing evidence. Author hand cases cover idle omissions, strict source clocks, exact native lot floors, corrupted eligibility/priority/targets/deadlines/order attributes, absent actual close orders, pre-fill completion claims, missed immutable timeouts, early or absent mandatory exits, target drift, counterfeit completed episodes, mandatory terminal requests and a successful actual-fill-to-full-close lifecycle. Separate reviewer cases found and closed contradictory admission outcomes, unjustified early exits, missing completed closures, exit-log/order linkage and a final guard mutation window. No economic thresholds or frozen model source changed.

Passing these checks cannot establish original OI delivery, vintage or historical unit definitions, and cannot make the repeatedly studied year an untouched holdout or guarantee a profitable strategy.
