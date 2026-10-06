# Independent paired-venue coordinator review

The prospective coordinator in `examples/cross_venue/strategy.py` passes the independent synthetic execution review. This is coordinator signoff; real-data coverage, the assembled runner/freeze/receipt protocol, and eventual trajectory/publication reconstruction require separate review. No historical signals, fits, or economic simulations were run. Candidate26 remains prospective, and the existing result is 0/25.

The independent file `tests/test_cross_venue_execution_audit.py` contains 12 passing cases using actual Engine execution and synthetic sixteen-instrument minute markets. Together with the coordinator author's suite, 31 focused tests passed in 2.38 seconds:

```bash
.venv/bin/python -m pytest tests/test_cross_venue_execution.py tests/test_cross_venue_execution_audit.py -q
```

## Independently established behavior

One fixture opens all eight pairs, retaining sixteen native positions and eight actual completed entries. Asynchronous funding facts include a millisecond event clock. Both venue cash balances independently equal initial cash minus their own actual fees plus their own signed funding cash. Venue equity independently equals that cash plus the unrealized P&L on its native positions. The synthetic long payments total -10 USDT on Binance and short receipts total +20 on Bybit; no margin reserve is falsely deducted as a cash expense. Native 1000PEPE positions remain equal 125,000 native units on each venue, with no second bundle multiplier. Actual opening fees are taker fees.

Other adversarial tests establish:

- A zero-capacity Bybit DOGE leg times out without disturbing the other seven matched pairs. Only the actually opened Binance DOGE inventory is closed; the absent leg is never invented. Each pair is submitted once.
- A normal closing order remains GTC through seven unavailable minute opens, then closes at minute72. The coordinator observes actual flat inventory at minute73 and begins its 24-hour cooldown there. A next-day decision before that cooldown ends cannot reopen; the following eligible hourly decision can. No exit request or elapsed deadline is mistaken for an executed flat position.
- A native PEPE close leaving 100 units below the 200-unit fixture minimum remains marked inventory in CLOSING state. It does not receive a flat event or cooldown.
- Initial entry is prohibited in the final seven days. An existing terminal pair remains honestly marked with actual positions; there is no manufactured terminal exit.
- A profitable Binance price jump breaches that venue's .5 gross/equity cap and triggers actual cleanup even while pooled P&L is positive. Both cash wallets retain their own resulting gains/losses. Cross margin at leverage one is enforced; isolated margin and leverage two are rejected.
- Simultaneous funding depletion can liquidate both legs before the coordinator callback. Even when all positions are already flat, the actual-liquidation event triggers the account abort and 24-hour global cooldown. The pre-review missing-cooldown branch was repaired by the coordinator author before this test passed; no economic parameter or core behavior was changed.
- Funding before, or exactly at, a delayed opening is not credited to intended positions. Funding 500 milliseconds after the actual opening is applied to the existing position. Funding callbacks cannot create same-clock entries from the newly settled rate.
- Future feature rows with extreme yields cannot create an earlier pair intent. Offhour invalid/NaN yield fields do not themselves create normal exits; normal feature decisions remain hourly at UTC `:05`.

The synthetic factories are shared with the author's tests; the adversarial scenarios and cash, native-quantity, funding-clock, and cooldown assertions above were independently authored. The tests exercise the corrected existing Engine; no core or frozen earlier model source was edited by this reviewer.

## Interpretation limits

Pair order submission is not atomic execution. Actual partially matched inventory and cleanup dust remain exposed and must be shown by the runner's post-fill observations. Callback unmatched diagnostics explicitly precede current open fills and cannot replace a post-fill trajectory audit. Venue gains never rescue the other venue's wallet. Account risk exits are executable requests, not guaranteed drawdown bounds.

The Engine's disclosed mark-derived emergency liquidation fills do not obey normal volume participation. Global slippage/delay/participation assumptions and current native contract rules remain approximations. Historical publication lag and settlement-mark uncertainty remain in [the signal review](cross_venue_signal_review.md) and [the collector review](cross_venue_collector_review.md). These tests do not establish profitability, recovered historical funding schedules, or untouched out-of-sample evidence.
