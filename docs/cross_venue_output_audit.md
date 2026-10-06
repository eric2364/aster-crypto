# Independent two-venue financial and summary audit

Status: all seven completed historical runs passed the independent financial and summary audit on October 6, 2026. The financial certificate has `complete: true`, `errors: []`, and all four reconstruction flags true. All seven accounts remained inactive at initial equity 100,000 USDT, with two separate 50,000 USDT wallets. This is **no trading evidence or successful strategy**. Publication also requires the independent causal feature and cohort-specific no-admission certificates.

After root confirms completion of all seven historical runs, execute:

```sh
.venv/bin/python audit/verify_cross_venue_outputs.py \
  --binance data_cache/minute-perpetual-1y \
  --bybit data_cache/minute-bybit-1y \
  --out results/cross-venue-funding-1y-v1 \
  --certificate audit/cross_venue_output_evidence.json
```

The verifier imports no engine, portfolio, strategy, signal module, or frozen runner. It independently requires the seven declared phase identities and 25 sealed outputs per phase (175 files). The complete source-lock and input-verification bytes must equal their pre-outcome committed artifacts at `1820b8278bfae8a3775fce3b0ee15be8ac2a5448`. Source files must match reviewed commit `98fe45a55866ccfd1fa5a4e68deb52a127ff7ff2`, the archive, and the current source; all locked inputs and runtime versions are checked before and after reconstruction. The auditor's own bytes are likewise pinned before and after execution.

For each source close, actual settlement and opening clock, independent arithmetic reconstructs all sixteen native linear positions, weighted entry price, proportional closed-trade entry fees and funding, realized P&L, cross-margin wallet cash, initial margin, maintenance margin and marked equity. Opening a perpetual does not debit principal. Funding payment is `-native_quantity × sourced_mark × actual_rate`; funding occurs before new opening fills at an identical timestamp. Binance and Bybit cash remain separate. A liquidation must arise from that venue's own equity relative to its maintenance plus closing-fee reserve; another wallet cannot rescue it.

Every ordinary fill must have an immutable submitted and accepted GTC order, its actual activation delay, correct side/native quantity and remaining size, a source minute-open reference, adverse configured slippage rounded to the native tick, and capacity bounded by **previously completed** volume. Ordered event rows distinguish a cancellation before a fill from a cancellation after it even at an identical timestamp. Reduce-only fills cannot increase or flip inventory. Fee, funding, order-fill and liquidation events must reconcile with their corresponding cash/fill records.

The verifier compares every field in the 127-column post-fill exposure ledger, all global equity fields and each venue's cash/equity, every closed trade, and every final marked open position. It reconstructs all sixteen leg and eight pair contributions, and the indicative exit fee/slippage reserve without inventing an executed close or subtracting slippage twice. Actual matched entries must correspond to equal opposite native quantities observed after preceding fills, before the callback's new opening fills; diagnostic targets alone do not establish completion.

It independently calculates all exported descriptive metrics, compounded validation, the three July-5-anchored evaluation month returns, every declared hurdle, endpoint daily Sharpe, and the conditional circular seven-day bootstrap (10,000 draws, seed 42, 26 comparisons, tails `0.05/52`). Midnight endpoints are assigned to the preceding day after explicit nanosecond conversion. The original summary must match this reconstruction. Bootstrap diagnostics do not undo adaptive reuse of the year.

The final financial certificate binds source lock, feature bytes, feature receipt, original summary and all 175 output hashes. Required flags are `trajectory_reconstruction_passed`, `summary_reconstruction_passed`, `execution_fill_reconstruction_passed`, `separate_wallet_reconstruction_passed`, and auditor source unchanged. This financial certificate alone does **not** establish causal feature correctness: publication additionally requires the separate independent `audit/verify_cross_venue_features.py` certificate and a cohort-specific independent no-admission certificate for the same source/features/feature-receipt hashes. This financial verifier checks recorded executable fills and financial trajectories; it does not claim generic reproduction of all strategy decisions or prove that eligible orders were not omitted. The no-admission certificate must establish the actual inactive cohort's entry-rule rejection before publication.

Synthetic tests in `tests/test_cross_venue_output_audit.py` exercise real Engine exports with native PEPE bundle quantities, asynchronous millisecond settlements, baseline/stressed delay, partial failures/cleanup, actual venue-local liquidation, closed trade allocations and retained inventory. Adversaries alter fill quantity/fee/reference/price/capacity, funding signs/timestamps, activation/reduce-only, same-clock event ordering, cash, margins, collateral fields, marks, closed trades, final positions, resealed metadata, core identity and file seals. Independent tests also cover all descriptive formulas, ms/us/ns bootstrap endpoints, economic breadth, strict positive gates, committed input-byte drift and auditor-source drift.

## Completed financial evidence

Certificate: [audit/cross_venue_output_evidence.json](../audit/cross_venue_output_evidence.json). The audit bound all 175 output files, 40 executed source files, 8,814 locked inputs, immutable feature/receipt bytes and the original provisional summary. All 127 observer fields and every global/venue equity field reconciled at every source clock.

| Fixed phase | Audited equity snapshots | Fills / closed trades | Funding cash flows | Final positions / matched entries | Liquidations |
|---|---:|---:|---:|---:|---:|
| validation1 | 43,250 | 0 / 0 | 0 | 0 / 0 | 0 |
| validation2 | 44,697 | 0 / 0 | 0 | 0 / 0 | 0 |
| validation3 | 43,244 | 0 / 0 | 0 | 0 / 0 | 0 |
| evaluation | 132,609 | 0 / 0 | 0 | 0 / 0 | 0 |
| evaluation_stress | 132,609 | 0 / 0 | 0 | 0 / 0 | 0 |
| evaluation_alternative | 132,609 | 0 / 0 | 0 | 0 / 0 | 0 |
| evaluation_alternative_stress | 132,609 | 0 / 0 | 0 | 0 / 0 | 0 |

The independent summary reconstruction confirms zero validation/evaluation/stress returns, zero indicative exit reserves, no participating pairs, undefined Sharpe, zero drawdown and three zero anchored monthly returns. Thirteen of fifteen frozen hurdles fail; only drawdown and absence of liquidation pass. The cash-only conditional bootstrap intervals are `[0, 0]`, a consequence of no activity rather than evidence of an edge.

This certificate explicitly has `strategy_policy_reconstruction_passed: false`: it certifies recorded executable fills and financial/statistical reconstruction, not general strategy decision completeness. The separate no-admission audit must establish why no entry qualified.

Pinned hashes:

- Financial certificate SHA-256: `c9c27f43c19ad322a3a1ee1c39b7c4429fd9bb3364ad0e0ee0dfedc0a9152c71`.
- Financial auditor source SHA-256: `be674335c6921d1fbfd7ddb422e206f88cf6844766a04af71ff691419eb1c244`.
- Source lock SHA-256: `a2e3a341a84e49fd2a4b1a09533dbd3b69e65aca0e8b9cc783879ccbad6b6919`.
- Features SHA-256: `04500be0fa13f39e401e519978123fa81d60b3592ea6f6a61ccb287d2e9d1c74`.
- Feature receipt SHA-256: `78e15478a4a1ea78e0f782ec011daae634b3cb6ff19f3567d190362d243936eb`.
- Original summary SHA-256: `ffd040f412d4f16441f1f1cd05198bada0d0da7eaa3d967c90803032c11b4302`.

The first audit attempt stopped because pandas union retained shared settlement timestamp duplicates across instruments. Only the auditor was corrected to union unique timestamps, with a simultaneous minute/subminute settlement regression added. The final audit used unchanged auditor bytes throughout and did not rerun Engine or alter any execution artifact, source input, frozen economic rule or summary. Thirty-seven targeted synthetic tests passed; the preceding full repository run passed 664 tests.
