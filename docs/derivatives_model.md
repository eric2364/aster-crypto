# Linear perpetual accounting and risk model

Research checked 6 October 2026. This is a simulator specification; named exchange adapters provide configurable research profiles, not complete replicas of the venues' liquidation engines.

## Scope and contract identity

The implemented target is one-way, linear, quote-collateralized perpetuals. Normalize contracts to signed base-asset quantity `q = signed_contracts × contract_size × multiplier`. Retain exchange, instrument ID, settlement currency, base/quote, tick/lot rules, listing dates and contract multiplier in metadata. A perpetual long and short are derivatives: opening one exchanges no principal notional. Isolated margin and single-currency cross margin are separate risk policies. Cross collateral never travels between exchanges.

Inverse, quanto, hedge-mode legs, options, expiry settlement and multi-currency portfolio margin require separate valuation and risk implementations. They must be rejected until implemented. USDT and USDC balances cannot be silently combined without an explicit valuation/conversion model. Configurable constant maintenance rates are research assumptions, not historically reconstructed risk tiers.

## Valuation and cash identities

Let `q` be signed base quantity, `e` average entry, `m` contemporaneous mark, `p` execution price, `L` configured leverage and `r` maintenance rate.

```text
unrealized_pnl = q × (m − e)
notional = abs(q) × m
initial_margin_reference = abs(q) × e / L
mark_based_initial_margin = abs(q) × m / L   # if selected by risk policy
maintenance_margin = max(0, notional × r − tier_deduction)
equity = cash + marked_spot_inventory + sum(perpetual_unrealized_pnl)
cash = deposits + realized_pnl + funding_cashflow − trading_fees − liquidation_fees
```

Margin reserves are allocations of cash; they are never added to equity as another asset or subtracted from equity as another expense. Buying spot does debit principal, whereas opening either direction of a perpetual debits only fees and earmarks margin.

For a same-direction add, weighted entry is `(abs(q_old)×e_old + abs(delta_q)×p) / abs(q_new)`. For opposite-direction execution, `c=min(abs(q_old),abs(delta_q))` closes inventory and realizes `sign(q_old)×c×(p−e_old)`. Remaining old-side entry is unchanged; a flipped remainder has entry `p`. Charge execution fee on all executed quantity exactly once. Reduction releases the corresponding margin allocation. Enforce reduce-only before accounting: reject an increase and cap reduction to existing quantity so no remainder reverses the position.

Slippage is embedded in execution prices and therefore in realized P&L. Store signed adverse execution cost relative to a declared reference for diagnostics. Subtracting that diagnostic again from realized P&L is double counting. If showing pre-slippage trading P&L, add execution cost back before subtracting it as a separate attribution line.

## Funding as settlement events

```text
funding_cashflow = −q_at_settlement × mark_at_settlement × settled_rate
```

Positive cash flow means received. Positive rates debit longs and credit shorts; negative rates reverse this direction. Rates are per settlement, not annual rates, and are not multiplied by leverage or divided again by funding interval. Funding neither changes quantity nor entry price. It changes cash and the relevant risk equity. Store instrument, exchange, exact UTC settlement time, position quantity, mark, rate and cash flow. Key settlement identity by `(exchange, instrument_id, settlement_timestamp)` and settle it once even when several data events share that timestamp.

Historical realized rates are available to the accounting engine only at their recorded publication/settlement time. A strategy cannot read the next realized settlement rate in advance. Predicted rates require their own observed-time series. Do not forward fill a realized settlement rate into strategy information before publication. The final settlement event may lie after the final candle; either process it through the requested run end or explicitly exclude it.

At simultaneous events declare a reproducible ordering: update contemporaneous mark; perform risk checks on previously open positions; assess funding for positions held immediately before settlement; perform another risk check after funding; then handle newly activating orders. A close executed strictly before settlement owes nothing; a close at the same simulated timestamp follows the declared funding priority. Exact venue microsecond races are beyond bar-data resolution.

The default isolated funding policy can debit/credit the position allocation along with total wallet cash. This resembles OKX isolated settlement. A Bybit-style available-balance-first policy needs a separate adapter policy; simply copying fees and intervals is insufficient to replicate the venue. Funding times must come from historical events: current venues can change intervals dynamically. [Bybit funding documentation](https://www.bybit.com/en/help-center/article/Funding-fee-calculation) documents variable intervals, available-balance-first debits and settlement uncertainty near the boundary. [OKX funding documentation](https://www.okx.com/en-gb/help/perps-funding-fee-mechanism) documents contract multipliers and mode-dependent debits.

## Isolated and cross risk

For isolated positions track an explicit allocated collateral balance `C`; total account cash already includes this balance. Local risk equity is `C + q×(m−e)`. Funding and explicitly assigned costs adjust `C`; opening/adding positions transfers allocation internally from free cash; partial reduction releases allocation proportionally. Unrelated free cash must not rescue an isolated position unless auto-add-margin is an explicit policy.

Current implementation policy: opening execution fees are paid from unallocated wallet cash; opening position collateral is entry notional divided by configured leverage. Partial reduction releases the closed quantity’s proportional share of the existing collateral, including accrued funding adjustments. Closed-leg realized P&L and execution fees change wallet cash once and are not automatically reassigned to the remaining position reserve; full closure releases the entire remaining allocation. Earlier reports used a declared retention convention that could deplete a tiny residual reserve after a losing partial exit. That convention was corrected, and all 1,000 identical derivative experiments were rerun in separate folders and independently audited; see the [comparison](margin_correction_results/report.html). This allocation policy remains a simulator assumption, not a complete historical exchange replica. Funding debits/credits allocation directly. Cross risk uses mark-based initial margin.

For single-currency cross, pool wallet collateral and UPL only within `(exchange, settlement_currency, account)`, excluding collateral locked to isolated positions. Aggregate maintenance over cross positions. Spot collateral is excluded unless a haircut policy explicitly admits it. Admission checks cover prospective margin and fees; fill-time revalidation is necessary because price and collateral can change after acceptance. Reserving pending order margin prevents several simultaneously accepted orders spending the same available collateral. Orders that reduce risk must remain possible under stressed accounts.

```text
margin_ratio = maintenance_requirement / risk_equity
liquidate when risk_equity <= maintenance_requirement + configured_close_cost_reserve
available_margin = eligible_risk_equity − used_initial_margin − pending_order_reserves
gross_leverage = sum(abs(marked_exposure)) / account_equity
net_leverage = sum(signed_marked_exposure) / account_equity
```

When equity is nonpositive, margin ratio/leverage is infinite or explicitly undefined, never reassuringly zero. Initial margin is an admission constraint; falling below it alone is not liquidation. Maintenance is the ongoing liquidation constraint. [Bybit contract FAQ](https://www.bybit.com/en/help-center/article/FAQ-USDT-Perpetual-and-Expiry-Contracts) distinguishes account modes and initial/maintenance margin. [Binance liquidation protocols](https://www.binance.com/en-ZA/support/faq/detail/360033525271) uses mark for liquidation and describes mechanisms more complex than a flat maintenance-rate simulation.

## Liquidation boundary and execution

Under constant `r`, zero tier deduction and zero close-cost reserve, isolated boundaries solve `C+q×(m−e)=abs(q)×m×r`:

```text
long:  liquidation_mark = (abs(q)×e − C) / (abs(q)×(1−r))
short: liquidation_mark = (abs(q)×e + C) / (abs(q)×(1+r))
```

With a close reserve `f×abs(q)×m`, replace `r` by `r+f`. The long formula may yield a nonpositive boundary for sufficiently collateralized positions; this indicates no positive-price boundary under that model. Tiered rates require piecewise solving and validation against the selected tier. A cross account generally has no stable single-symbol liquidation price because every position and collateral change affects it.

Trigger from observed mark, not last trade, index or fill price. Index is reference metadata, not a replacement mark. Execute forced closure using the configured executable-market/slippage approximation; never invent a favorable boundary fill after an adverse gap. Cancel risk-increasing orders at liquidation. Log trigger mark, local/account equity, maintenance, execution, realized P&L and separate penalty. Trading loss from forced exit already enters realized trading P&L; report it as a tagged subset rather than subtracting it twice as another liquidation loss.

A gap can produce negative equity. Preserve and disclose deficits unless an explicit insurance/limited-liability policy transfers the debt with a balancing ledger item. Full-position liquidation is an MVP approximation. Real venues can cancel orders, reduce risk tiers, partially liquidate, apply bankruptcy transfers, use insurance funds and perform ADL. No claim of exact venue liquidation should be made without those policies and historical tiers.

With close-only mark samples, liquidation between observations is unobservable. Do not treat trade-candle low/high as a mark path. Mark OHLC or higher-frequency mark events can improve risk resolution; expose the risk sampling limitation in reports.

## Manually computed verification scenarios

All examples use quote currency, unit contract multiplier and no hidden financing or fees.

| Scenario | Hand calculation | Expected |
|---|---|---|
| Long 2 units at 100, cash 1,000, mark 110 | UPL `2×10`; opening principal unchanged | Cash 1,000; equity 1,020 |
| Short 2 at 100, mark 90 | UPL `−2×(90−100)` | Cash 1,000; equity 1,020 |
| Close short 2 at 90, taker rate 0.001, entry fee 0.2 | RP 20; exit fee 0.18 | Final cash/equity 1,019.62 |
| Long 2, mark 100, funding 0.001 | `−2×100×0.001` | Cash decreases 0.2 |
| Short 2, mark 100, funding 0.001 | `−(−2)×100×0.001` | Cash increases 0.2 |
| Long 2, mark 100, funding −0.001 | `−2×100×(−0.001)` | Cash increases 0.2 |
| Buy 2 at 100 then add 1 at 130 | `(200+130)/3` | Entry 110 |
| Then sell 2 at 120 | `2×(120−110)` | Realized 20; remaining long 1, entry 110 |
| Then sell 3 at 90 | Close 1: `90−110`; excess opens short 2 | Realized −20; short entry 90 |
| Isolated long 1 at 100, C=10, r=0.005 | `(100−10)/0.995` | Boundary 90.4522613065 |
| Isolated short 1 at 100, C=10, r=0.005 | `(100+10)/1.005` | Boundary 109.4527363184 |
| Long at mark 90 with C=10 | Local equity 0; maintenance 0.45 | Liquidate even with unrelated wallet cash |
| Short at mark 110 with C=10 | Local equity 0; maintenance 0.55 | Liquidate; long/short boundary asymmetric |
| Gap long 1 at 100, C=10, next mark/fill 80 | RP −20; local ending equity −10 | No invented fill at 90.45; deficit disclosed |
| Cross long 1 at 100, short 1 at 100, mark 90 | UPL −10 +10; gross notional 180 | Net UPL 0; both require maintenance |
| Accounts A and B each cash 10; A long 1 at 100 mark 90 | A risk equity 0 | B cash cannot rescue A |

Additional adversarial checks: no funding when flat; duplicate event cannot debit twice; mark versus trade divergence; close at boundary obeys event precedence; liquidation immediately after a funding debit; reduce-only does not reverse; fees included in admission; partial close releases only proportional margin; fills cannot draw on another exchange's cash; sum of account equity reconciles portfolio equity; all ledger debits reconcile cumulative realized/funding/fee balances.

Simultaneous marks must be applied as a batch before aggregate cross risk. Likewise, simultaneous funding marks and cash flows must be processed atomically before a cross liquidation check. Sequentially updating a long leg before its offsetting short can manufacture an insolvent intermediate state that never existed. Cross reversal admission must release current mark-based initial margin and replace existing unrealized P&L with execution-realized P&L once; adding the full realized close to equity already containing unrealized close double counts the gain or loss.

## Independent verification outcome

`tests/test_derivatives.py` contains 38 passing hand-computed/adversarial checks. The author of this specification and test file did not implement the portfolio or event engine. Review found two material defects: cross reversal admission counted existing unrealized gains/losses twice, and cross risk observed inconsistent intermediate marks during simultaneous multi-symbol candle/funding updates. Both were fixed by the engine author; regression tests now verify profitable and losing reversals, simultaneous hedges and funding marks. Additional passing integration checks verify mark/last-price divergence, funding-before-new-entry priority, duplicate-settlement rejection and immediate funding-induced liquidation. Reported liquidation boundaries are checked independently for both directions, close-cost reserves, funding changes and fully collateralized longs; maintenance reporting excludes exit reserves and sums correctly by venue. This supports the implemented scope; it does not validate exchange-specific ADL, insurance funds, historical risk tiers or unobserved intrabar mark behavior.
