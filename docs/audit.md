# Independent adversarial core audit

Audit date: 6 October 2026. Auditor authored execution research and this separate
test module, and did **not** author or modify core simulation/accounting code.
The instruction was to assume subtle bugs capable of fake profitability.
Review included `engine.py`, `portfolio.py`, `execution.py`, `models.py`, and
data normalization, with manually calculated synthetic regression scenarios.

## Confirmed findings and verified corrections

| Finding | Original severity | Observed failure | Correction verified by independent regression |
| --- | --- | --- | --- |
| Cross reversal counted unrealized profit twice | High | Cash100, long1 at100, mark200; reversing to short2.4 was accepted although realized cash200 cannot fund margin240 | Validate projected cross cash, new UPL and marked margin atomically; reversal is rejected without mutating the position |
| Delayed stop-limit incorrectly retained resting priority | Medium | Untriggered buy stop110/limit150 at100 later triggers at120; charged maker and filled150; post-only variant also executed | Trigger resets first-seen activation; new crossing fills taker120 and crossing post-only cancels |
| Simultaneous hedge marks caused false liquidation | High | Long1 and short1 at100, both marks fall40; long mark applied first, liquidating both against stale short mark and losing60 | Batch all same-time market marks before venue liquidation; equity remains100 and maintenance24, no liquidation |
| Same-time funding charged debit before offsetting credit | High | Cross equity100, maintenance90; simultaneous long payment-20 and short receipt+20 liquidated after debit, losing the credit | Settle same-time payments before risk; both ledger items recorded, net funding0, equity100 |
| Adverse sell execution could become nonpositive | High | Slippage15000bps on100 yielded negative execution price and invalid notional/margin arithmetic | Reject nonpositive/nonfinite adverse execution and fill values |
| Gross leverage cap ignored execution fees | Medium | Equity1000, quantity10 at100, fee10, max leverage1 passed despite post-fill equity990/gross1000 | Validate post-fill equity, including fees and execution-vs-mark price change; reject atomically |

All six confirmed findings were fixed by the core author and independently
retested. The independent module now has **20 passing tests**. No known unresolved
high/medium defect from this audit remains; this is not an assurance that all
possible defects or exchange differences have been eliminated.

## Independent scenarios verified

- Closed-bar signal executes at next open120, never its own old close100.
- A positive 1ms delay misses the next opening boundary and fills at later140.
- Mutating upcoming completed volume1000 to0 leaves opening IOC quantity1,
  derived only from previously published volume10 and participation10%.
- Two concurrent IOC orders share that one-unit budget.
- Nonmarketable IOC cannot wait for later intrabar penetration.
- Insufficient FOK capacity produces no partial fill.
- Newly marketable limits take liquidity, and crossing post-only cancels.
- Equal low/limit touches never fill conservative limits.
- Ambiguous OHLC stop-limit cannot invent trigger-before-fill ordering.
- Stop-market gaps fill150 instead of the historical stop110.
- Competing reduce-only closes cannot flip a long into a short.
- Buy101/sell108.90 with reference100/110 yields actual trading P&L7.90,
  fees0.10495, final equity10007.79505 from10000. Reported slippage2.10
  is already embedded in those prices and is not deducted again.

Execute independent cases:

```bash
.venv/bin/python -m pytest tests/test_execution_audit.py -q
```

## Residual limitations and review boundaries

Candle replay cannot validate queue position, actual available depth, hidden
orders, true maker eligibility from quotes, intrabar mark liquidation, or
sub-bar reaction. A strict resting/trade-through rule and volume proxy reduce
optimism but do not establish executable liquidity. The supplied historical
data must independently be checked for listing/universe completeness and
funding coverage; synthetic example profitability is not historical evidence.

Conditional triggers use trade OHLC in this MVP. Mark/index-trigger selection,
exchange price bands, historical tiered fees, insurance/ADL and exact exchange
liquidation waterfalls remain absent. Cancellation latency is zero; GTC partial
markets retry; fixed slippage does not automatically include bid/ask spread.
These are explicit model boundaries documented in `execution_model.md`.

The audit focused causal execution and accounting. Dashboard correctness,
performance benchmarks, packaging, and independent analytics formula checks
are separate workstreams. The root task runs the complete integrated test suite
and example commands after the fixes; its final verification record controls
the overall repository completion status.
