"""Read-only fee attribution of the 24 disclosed historical candidates.

Fee addback holds executions and funding fixed. It is not a zero-cost backtest,
new strategy, hypothetical maker fill, or attainable return.
"""
from pathlib import Path
import hashlib
import json
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [('spot', 'minute-study-1y', 'families', 'family'),
           ('carry', 'minute-carry-1y-v2', 'policies', 'policy'),
           ('signed', 'minute-directional-1y-v2', 'families', 'family'),
           ('external', 'external-factor-1y', 'families', 'family')]


def main():
    rows, fingerprints = [], {}
    for cohort, directory, collection, name in SOURCES:
        source = ROOT / 'results' / directory / 'summary.json'
        fingerprints[str(source.relative_to(ROOT))] = hashlib.sha256(source.read_bytes()).hexdigest()
        summary = json.loads(source.read_text())
        for candidate in summary[collection]:
            identity = candidate[name]
            metrics = candidate['holdout']
            initial, final = metrics['initial_equity'], metrics['final_equity']
            net = final - initial
            if abs(net - metrics['net_profit']) > 1e-6 or abs(final / initial - 1 - metrics['total_return']) > 1e-10:
                raise ValueError(f'Published net identity mismatch: {identity}')
            fees = (metrics.get('trading_fees') or 0) + (metrics.get('liquidation_fees') or 0)
            if fees < 0:
                raise ValueError('These experiments assume positive taker fees')
            rows.append({'cohort': cohort, 'candidate': identity,
                         'evaluation_net_return': net / initial,
                         'evaluation_net_profit': net, 'actual_trading_and_liquidation_fees': fees,
                         'same_fills_net_with_fees_added_back': net + fees,
                         'same_fills_fee_addback_return': (net + fees) / initial,
                         'recorded_slippage_cost_diagnostic': metrics.get('slippage_cost'),
                         'actual_funding_pnl': metrics.get('funding_pnl'),
                         'completed_trades': metrics.get('trade_count'),
                         'actual_fills': metrics.get('fill_count'),
                         'historical_hurdles_passed': candidate['historical_hurdles_passed'],
                         'failed_gates': ', '.join(k for k, v in candidate['checks'].items() if not v)})
    if len(rows) != 24 or len({x['candidate'] for x in rows}) != 24:
        raise ValueError('Require all 24 unique disclosed candidates')
    out = ROOT / 'docs' / 'research_review'
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(out / 'failure_attribution.csv', index=False)
    manifest = {'source_summary_sha256': fingerprints, 'candidate_count': 24,
                'fee_addback_definition': 'net profit + actual trading and liquidation fees; executions, signed inventory and funding held fixed',
                'not_a_counterfactual_backtest': True,
                'slippage_is_not_subtracted_twice': True,
                'historical_hurdle_pass_count': int(frame.historical_hurdles_passed.sum()),
                'negative_evaluation_net_count': int((frame.evaluation_net_profit < 0).sum()),
                'negative_after_same_fills_fee_addback_count': int((frame.same_fills_net_with_fees_added_back < 0).sum())}
    (out / 'failure_attribution.json').write_text(json.dumps(manifest, indent=2, allow_nan=False) + '\n')
    lines = ['# Why the disclosed historical candidates did not qualify', '',
             'These are original-engine reports, now provisional after the partial-exit margin correction. They describe recorded outcomes, not corrected-engine performance. This is a read-only attribution of the published final-quarter evaluations. It neither retunes a rule nor changes its fills, funding, inventory, accounting or hurdle. All source summaries are hashed.', '',
             f"Of 24 candidates, {manifest['negative_evaluation_net_count']} had negative evaluation net P&L. Even adding back their actual trading and liquidation fees while holding executions fixed leaves {manifest['negative_after_same_fills_fee_addback_count']} with negative evaluation P&L. The zero-return premium rule had no evaluation trades. All 24 failed at least one declared hurdle.", '',
             'Fee addback is an accounting diagnostic, **not a realizable return or a rerun without costs**. Fill prices already contain adverse slippage and rounding. Slippage is separately reported and is not deducted again. Removing execution costs, changing to maker orders or relaxing thresholds would change fills and exposure; these tables do not simulate that counterfactual.', '',
             '| Candidate | Evaluation net | Same fills, fees added back | Completed trades | Hurdles |',
             '|---|---:|---:|---:|---|']
    for row in rows:
        count = 'undefined' if row['completed_trades'] is None else str(row['completed_trades'])
        lines.append(f"| {row['candidate']} | {row['evaluation_net_return']:.3%} | {row['same_fills_fee_addback_return']:.3%} | {count} | {'PASS' if row['historical_hurdles_passed'] else 'FAIL'} |")
    lines += ['', 'The funding-crowding rule earned a small positive evaluation result through three PEPE trades with seven idle sleeves. That is concentration rather than multi-asset validation. CPI had just two directional evaluation releases; correlated coin positions do not create more independent macro events. Previous positive price-breakout examples failed validation or stress and were sensitive to concentrated episodes.', '',
              'The current perpetual assumptions imply a simple two-sided taker fee/slippage floor of 14 bps for BTC/ETH, 20 bps for ordinary altcoins and 26 bps for DOGE/PEPE, before tick rounding, market impact and funding. These are this project’s assumed costs, not a verified historical fee tier. A minute signal must exceed those costs or hold long enough to accumulate a larger move. Maker profitability needs independent quote/book evidence; a touched candle is not a guaranteed fill.', '',
              '[Complete outcomes](../minute_strategy_results.md) · [Attribution CSV](failure_attribution.csv) · [Source hashes and definitions](failure_attribution.json)', '']
    (out / 'failure_attribution.md').write_text('\n'.join(lines))
    print(json.dumps({k: v for k, v in manifest.items() if k != 'source_summary_sha256'}, indent=2))


if __name__ == '__main__':
    main()
