# Joint funding-rank results and independent reconstruction

6 October 2026. Candidate 27 is one fixed different-underlying funding basket in
one real simulated cash wallet. **It failed four of 15 historical gates.**
Compounded validation returned **−0.488%**, baseline final-quarter evaluation
**+0.884%**, and joint stress **−0.955%**. Cumulative disclosed research is
**0/27 historical hurdle passes**. The positive baseline is not a robust winner.

| Run | Net return | Completed baskets | Funding cash, USDT | Actual fees, USDT | Final actual flat |
|---|---:|---:|---:|---:|---|
| Validation April 5–May 5 | −0.155% | 4 | 38.22 | 101.10 | Yes |
| Validation May 5–June 5 | +0.223% | 3 | 25.22 | 73.74 | Yes |
| Validation June 5–July 5 | −0.556% | 2 | 42.48 | 73.31 | Yes |
| Evaluation July 5–October 5 | +0.884% | 9 | 36.40 | 298.25 | Yes |
| Same evaluation under stress | −0.955% | 6 | 39.27 | 510.46 | Yes |

Baseline daily Sharpe is 0.949 and complete minute/settlement-clock drawdown
1.795%; stress drawdown is 2.525%. All eight assets, including DOGE and native
1000PEPE, participated in completed baseline baskets. No actual liquidation
occurred in any phase. Entry proposals and incomplete baskets were not counted
as completed participation. Baseline generated 12 entry transactions but only 9
completed baskets; stress generated 11 and completed 6. These execution failures
remain in the account and diagnostics.

Baseline net profit is 883.71 USDT, including 1,145.56 trade-price P&L, 36.40 actual
funding and −298.25 fees. Slippage 513.36 is embedded in actual fill prices and
is not subtracted again. Funding alone did not cover fees. Different-underlying
price returns dominate the baseline profit; equal entry dollars do not cancel
coin-price or beta risk. Stress changes fills, incomplete baskets, delayed
execution and participation as well as fees, so its loss is not simply a fee
deduction from the baseline path.

## Evidence chronology

Reviewed economic source `ffa52d6b44bfed3f589389dd374719129b671771` was committed
and privately pushed before input freeze. The exact 36-source/308-input packet
was privately published at `22b21f12054dbde0895c94d1299a81025156ba92`, with
historical features/trials absent. The original
[receipt](funding_rank_preregistration/preregistration.json) remains unchanged.
Only then were 525,598×24 features generated; independent reconstruction of
4,204,784 prior-price values and 2,920 daily funding observations passed before
the first Engine simulation. All five fixed runs completed without changing
source, costs, thresholds, universe or gates. No fitted coefficients or parameter
search were used.

This chronology is pre-computation on a year already examined. It is not
prospective before the historical year or an untouched holdout.

## Actual audit scope

The [independent certificate](../audit/funding_rank_output_evidence.json) verifies
all five actual trajectories: **396,409 account snapshots, 595 fills, 1,956
funding cashflows, 321 closed trade records and 24 completed baskets**, across
**125 exported files plus five completion seals**. Basket and partial-close
counts do not represent independent economic observations.

The verifier imports no production engine, portfolio, signal or runner code.
It independently replays native linear quantities, price P&L, fees, funding
signs and exact source marks, cross-margin collateral, maintenance, equity,
actual tick/volume/activation execution and event ordering. It checks all
forty native leg rows, completed-basket quantities/deadlines, pre-cancellation
terminal orders, daily endpoint returns, metrics, 15 gates and the conditional
27-comparison block bootstrap. Source, runtime, inputs, common artifacts,
auditor and all phase seals were unchanged before/after verification.

The separate recorded-policy component verifies every exported valid proposal,
stable funding rank, fresh sizing/admission diagnostic, submitted target and
recorded normal-exit predicate against independently reconstructed inventory,
cash and certified causal features. Its certificate explicitly **does not
reconstruct omitted unlogged decisions or prove completeness of every abort
state transition**. Independent adversarial source/execution tests provide
additional checks; they are not historical proof of missing decisions.

All five endpoints have exactly zero actual observed native quantities and no
live orders before automatic end-of-data cancellation. Tiny dust would fail
even if omitted by the compact position ledger. There were no fabricated
terminal fills, capital transfers or funding-only synthetic equity.

## Statistical and data limits

The conditional seven-day circular-block return interval is −2.168% to +4.841%
at conventional 95% tails; the 27-comparison interval is −3.294% to +7.349%.
Both include zero and are diagnostic, not new success gates or a remedy for
adaptive research. The four failures are positive validation, validation after
exit reserve, positive stress and stress after exit reserve. All 15 definitions
stay frozen.

Historical receipt times are assumed where absent; downloaded archives are the
latest vendor vintage, not original delivery. Current lot/margin rules, fixed
fees and minute OHLC execution approximate the past; historical BBO/queues and
intraminute liquidation are not recovered. The eight-name survivor universe
and reused year limit inference. Raw observations remain confined to
2025-10-05 through 2026-10-05 UTC. Prior 26 protocols and outputs remain preserved.

[Interactive report](funding_rank_results/report.html) ·
[Source review](funding_rank_protocol_review.md) ·
[Causal feature audit](funding_rank_feature_audit.md) ·
[User manual](user_manual.md).
