"""Append disclosed exploratory evidence without changing the original cohort."""
from pathlib import Path
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd
from examples.minute_directional.run import bootstrap
from examples.minute_research import summarize as original


def main():
    summary_path = Path('results/minute-directional-1y-v2/summary.json')
    current = json.loads(summary_path.read_text())
    if len(current['families']) != 6:
        raise ValueError('Expected all six exploratory hypotheses')
    trials = json.loads(Path('results/minute-directional-1y-v2/all_trials.json').read_text())
    identities = {(x['family'], x['symbol'], x['scale'], x['phase'], x['stress']) for x in trials}
    if len(trials) != 480 or len(identities) != 480:
        raise ValueError('Expected 480 distinct completed simulations')
    # Regenerate the unchanged thirteen-policy cohort first.
    saved_args = sys.argv
    try:
        sys.argv = [saved_args[0]]
        original.main()
    finally:
        sys.argv = saved_args
    destination = Path('docs/minute_strategy_results.md')
    lines = [destination.read_text(), '\n## Exploratory extension: six signed perpetual hypotheses\n',
             'These six models were designed after viewing the original thirteen policies on this same year. Their final-quarter evaluation is **reused historical data**, not an untouched holdout. There are now **nineteen disclosed policies and hypotheses**; several are economically correlated. The original cohort above remains unchanged.\n',
             '| Hypothesis | Validation net | Evaluation net | Joint stress net | Daily Sharpe | Minute drawdown | Positive assets | Exploratory hurdles |',
             '|---|---:|---:|---:|---:|---:|---:|---|']
    for row in current['families']:
        result = row['holdout']
        sharpe = 'undefined' if result['sharpe'] is None else f"{result['sharpe']:.2f}"
        passed = 'PASS' if row['historical_hurdles_passed'] else 'FAIL'
        lines.append(f"| {row['family']} | {row['validation_compounded_return']:.2%} | {result['total_return']:.2%} | {row['stress']['total_return']:.2%} | {sharpe} | {result['max_drawdown']:.2%} | {row['positive_symbols']}/8 | {passed} |")
    passes = sum(row['historical_hurdles_passed'] for row in current['families'])
    lines.extend(['', f'**{passes} of six passed the declared exploratory historical hurdles.** A pass cannot establish absence of overfitting or supply an independent successful strategy.', '',
                  'Each model uses eight segregated $12,500 sleeves, 25% entry notional, native perpetual units and isolated leverage one. Quantities stay fixed between direction changes. Actual settlement funding is included. Base taker fees are 5 bps; the same liquidity-class slippage and joint cost/delay/participation stress apply. Open positions stay marked, and an indicative fee/slippage exit reserve is a separate diagnostic rather than an invented fill. Positive reserve-adjusted validation, evaluation, stress and neighbors, plus zero simulated liquidations, are additional gates.', '',
                  'Scalar models require five profitable sleeves. The cross-sectional portfolio instead requires actual fills across at least four assets, with all losing hedge legs retained in pooled P&L. It holds two ranked longs and two ranked shorts; beta and subsequent notional drift are not neutralized. These rules were frozen before this batch produced outcomes.', '',
                  'Failed gates for every exploratory hypothesis:', ''])
    for row in current['families']:
        failed = ', '.join(name for name, passed in row['checks'].items() if not passed)
        lines.append(f"- `{row['family']}`: {failed or 'all exploratory gates passed'}.")
    diagnostics = {}
    for root in ['results/minute-study-1y', 'results/minute-carry-1y-v2', 'results/minute-directional-1y-v2']:
        for path in sorted((Path(root)/'pooled').glob('*/equity.parquet')):
            key = path.parent.name
            if key in diagnostics:
                raise ValueError('Duplicate hypothesis identity')
            diagnostics[key] = {**bootstrap(pd.read_parquet(path)), 'source': str(path),
                                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    if len(diagnostics) != 19:
        raise ValueError('Expected nineteen full-resolution pooled equity sources')
    output = Path('docs/minute_directional_results/combined_selection_diagnostic19.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(diagnostics, indent=2, allow_nan=False)+'\n')
    # Presentation clarification only; the frozen runner and metrics stay intact.
    report_path = Path('docs/minute_directional_results/report.html')
    if report_path.exists():
        html = report_path.read_text().replace('<th>liquidations</th>', '<th>evaluation liquidations</th>')
        marker = 'Table liquidation counts cover the selected evaluation only;'
        if marker not in html:
            note = ('<p>' + marker + ' the no-liquidation hurdle also checks validation, '
                    'neighboring scales and joint stress. Every phase count remains in summary.json.</p>')
            html = html.replace('<h2>Accounting and execution assumptions</h2>',
                                '<h2>Accounting and execution assumptions</h2>' + note)
        report_path.write_text(html)
    lines.extend(['', 'A separate conditional seven-day block-bootstrap diagnostic now uses Bonferroni adjustment across all nineteen comparisons. It uses full-resolution pooled ledgers and records their hashes. This adjustment does not correct the adaptive design process, regime change, survivors or execution uncertainty. The earlier thirteen-policy diagnostic is retained as cohort-specific evidence.', '',
                  '[Exploratory report](minute_directional_results/report.html) · [All nineteen conditional intervals](minute_directional_results/combined_selection_diagnostic19.json) · [Reproduction guide](../examples/minute_directional/README.md) · [Independent audit](minute_directional_audit.md)', ''])
    destination.write_text('\n'.join(lines))
    print(f'Original cohort unchanged; exploratory hurdle passes: {passes}/6; nineteen diagnostics saved.')


if __name__ == '__main__':
    main()
