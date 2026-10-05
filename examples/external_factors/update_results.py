"""Disclose this complete cohort alongside all earlier results, without retuning."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aster.analytics import daily_returns
from audit.verify_external_outputs import audit
from examples.external_factors import run as frozen_runner
from aster.analytics import json_safe


def validate_completed(root):
    """Reconcile immutable executions before touching any published artifact."""
    root = Path(root)
    evidence = audit(root)
    if not evidence['all400_complete']:
        raise ValueError('All 400 expected sealed trajectories must pass independent execution audit')
    protocol = json.loads((root/'protocol.json').read_text())
    summary = json.loads((root/'summary.json').read_text())
    trials = json.loads((root/'all_trials.json').read_text())
    selection = json.loads((root/'selection.json').read_text())
    expected = {(x['family'], x['symbol'], x['scale'], x['phase'], x['stress']) for x in evidence['trials']}
    actual = [(x['family'], x['symbol'], x['scale'], x['phase'], x['stress']) for x in trials]
    if len(actual) != 400 or len(set(actual)) != 400 or set(actual) != expected:
        raise ValueError('Published trial table differs from exact audited trajectories')
    for row in trials:
        path = root/row['phase']/row['family']/f"{row['scale']:g}"/('stress' if row['stress'] else 'base')/row['symbol']
        if Path(row['path']).resolve() != path.resolve() or row['metrics'] != json.loads((path/'metrics.json').read_text()):
            raise ValueError('Trial table path or metrics differ from sealed execution')
    recomputed_selection = json_safe(frozen_runner.choose_training(trials))
    if selection != recomputed_selection:
        raise ValueError('Selection does not reproduce from training-only sealed trajectories')
    if set(selection['chosen']) != set(protocol['families']):
        raise ValueError('Selection cohort mismatch')
    # Recompute every pooled metric, event deduplication and unchanged gate in a
    # disposable directory. Original ledgers, summaries and earlier cohorts stay
    # untouched; no Engine, signals, fitting or parameter selection rerun occurs.
    with tempfile.TemporaryDirectory(prefix='external-summary-audit-') as directory:
        temporary = Path(directory)
        (temporary/'source_lock.json').write_bytes((root/'source_lock.json').read_bytes())
        rebuilt = json_safe(frozen_runner.summarize(trials, selection, temporary, protocol))
        if rebuilt != summary:
            raise ValueError('Summary, pooled outcomes or historical gates do not reconcile')
        for family in protocol['families']:
            for name in ['equity.parquet', 'stress_equity.parquet']:
                pd.testing.assert_frame_equal(pd.read_parquet(root/'pooled'/family/name),
                                              pd.read_parquet(temporary/'pooled'/family/name))
    return summary, trials, evidence


def interval(frame):
    dated = frame.copy()
    dated['timestamp'] = pd.to_datetime(dated.timestamp, utc=True).dt.as_unit('ns')
    end = dated.timestamp.max()
    if end == end.normalize():
        dated.loc[dated.timestamp == end, 'timestamp'] = end-pd.Timedelta(microseconds=1)
    returns = daily_returns(dated).dropna().to_numpy()
    n = len(returns)
    if n < 7 or not np.isfinite(returns).all() or (returns <= -1).any():
        raise ValueError('Finite positive-equity history required for conditional bootstrap')
    rng = np.random.default_rng(42)
    starts = rng.integers(0, n, (10000, int(np.ceil(n/7))))
    indices = ((starts[:, :, None]+np.arange(7)) % n).reshape(10000, -1)[:, :n]
    totals = np.expm1(np.log1p(returns[indices]).sum(axis=1))
    return {'method': 'conditional circular7dayblockbootstrap;10000draws;seed42;adaptive reused year',
            'comparison_count': 24,
            'return_interval_bonferroni24policies': np.quantile(totals, [.05/48, 1-.05/48]).tolist()}


def combined_diagnostics(root):
    diagnostics = {}
    prior = json.loads(Path('docs/minute_directional_results/combined_selection_diagnostic19.json').read_text())
    if len(prior) != 19:
        raise ValueError('Require the previously published nineteen-source fingerprint anchor')
    directories = ['results/minute-study-1y', 'results/minute-carry-1y-v2',
                   'results/minute-directional-1y-v2', str(root)]
    for directory in directories:
        protocol = json.loads((Path(directory)/'protocol.json').read_text())
        names = set(protocol.get('families', protocol.get('candidate_policies', {})))
        observed = {path.parent.name for path in (Path(directory)/'pooled').glob('*/equity.parquet')}
        if names != observed:
            raise ValueError('Combined diagnostics require exact protocol policy identities')
        for equity in sorted((Path(directory)/'pooled').glob('*/equity.parquet')):
            key = equity.parent.name
            if key in diagnostics:
                raise ValueError('Duplicate policy identity')
            source_hash = hashlib.sha256(equity.read_bytes()).hexdigest()
            if str(directory) != str(root):
                if key not in prior or Path(prior[key]['source']).resolve() != equity.resolve() or prior[key]['sha256'] != source_hash:
                    raise ValueError('Previously published policy source changed')
            diagnostics[key] = {**interval(pd.read_parquet(equity)), 'source': str(equity),
                                'source_sha256': source_hash}
    if len(diagnostics) != 24:
        raise ValueError('Require every full-resolution twenty-four-policy source')
    return diagnostics


def main():
    root = Path('results/external-factor-1y')
    summary, trials, evidence = validate_completed(root)
    identities = {(x['family'], x['symbol'], x['scale'], x['phase'], x['stress']) for x in trials}
    if len(summary['families']) != 5 or len(trials) != 400 or len(identities) != 400:
        raise ValueError('Require five complete hypotheses and 400 distinct simulations')
    diagnostics = combined_diagnostics(root)
    path = Path('docs/minute_strategy_results.md')
    # Preserve previously published cohorts byte-for-byte. Replace only this
    # extension on rerun; never regenerate earlier diagnostic/report files.
    marker = '\n## External-factor extension: five further exploratory hypotheses\n'
    previous = path.read_text().split('\n'+marker, 1)[0]
    lines = [previous, marker,
             'This new cohort follows the nineteen outcomes above and reuses the same evaluated year. It introduces actual QQQ daily closes, eleven original CPI releases and authentic aggressive trade flow. Funding-crowding and premium mechanisms overlap earlier carry research. There are **twenty-four cumulative disclosed policies and hypotheses**, not twenty-four independent demonstrated edges.', '',
             '| Hypothesis | Validation net | Evaluation net | Joint stress net | Daily Sharpe | Minute drawdown | Positive sleeves | Exploratory hurdles |',
             '|---|---:|---:|---:|---:|---:|---:|---|']
    passes = sum(row['historical_hurdles_passed'] for row in summary['families'])
    for row in summary['families']:
        result = row['holdout']
        sharpe = 'undefined' if result['sharpe'] is None else f"{result['sharpe']:.2f}"
        flag = 'PASS' if row['historical_hurdles_passed'] else 'FAIL'
        lines.append(f"| {row['family']} | {row['validation_compounded_return']:.2%} | {result['total_return']:.2%} | {row['stress']['total_return']:.2%} | {sharpe} | {result['max_drawdown']:.2%} | {row['positive_symbols']}/8 | {flag} |")
    lines.extend(['', f'**{passes} of five passed the unchanged exploratory historical hurdles.** No pass can restore an untouched evaluation or establish absence of overfitting.', '',
                  'QQQ unadjusted closes use conservative assumed next-UTC-day availability and calendar coverage checks. CPI uses actual first-release availability plus a minute, skips the unpublished October reference month and carries no consensus surprise. One announcement produces correlated exposure across eight sleeves, not eight independent events. Flow uses native trade-kline taker-buy volume, not mark volume or order-book depth. All signals and orders remain causal; no pre-year external initialization was added.', '',
                  'Capital, native quantities, actual funding, fees, slippage, joint execution stress, marked terminal positions and diagnostic exit reserves follow the signed-perpetual experiment above. Every failure, zero-activity case and phase event count is retained in the full summary. No previous model or result was retuned.', '',
                  'Failed gates:', ''])
    for row in summary['families']:
        failed = ', '.join(name for name, passed in row['checks'].items() if not passed)
        lines.append(f"- `{row['family']}`: {failed or 'all exploratory gates passed'}.")
    output = Path('docs/external_factor_results/combined_selection_diagnostic24.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    provenance = {key: value for key, value in evidence.items() if key not in ['trials', 'missing']}
    provenance['summary_sha256'] = hashlib.sha256((root/'summary.json').read_bytes()).hexdigest()
    provenance['all_trials_sha256'] = hashlib.sha256((root/'all_trials.json').read_bytes()).hexdigest()
    provenance['source_lock_sha256'] = hashlib.sha256((root/'source_lock.json').read_bytes()).hexdigest()
    provenance['publication_verification'] = '400 exact sealed trajectories audited; training-only selection, pooled equity, summary, event counts, gates and all24 diagnostic identities reconciled before publication'
    (output.parent/'publication_verification.json').write_text(json.dumps(provenance, indent=2)+'\n')
    output.write_text(json.dumps(diagnostics, indent=2, allow_nan=False)+'\n')
    lines.extend(['', 'The separate twenty-four-comparison conditional bootstrap retains source hashes and leaves earlier cohort diagnostics intact. It does not correct the full adaptive design process or uncertain historical execution. No confidence interval proves durable profitability.', '',
                  '[External-factor report](external_factor_results/report.html) · [Data and reproduction](../examples/external_factors/README.md) · [Collector and signal audit](external_factor_audit.md) · [CPI source coverage](cpi_factor_sources.md)', ''])
    path.write_text('\n'.join(lines))
    print(f'Previous nineteen results unchanged; external exploratory passes {passes}/5.')


if __name__ == '__main__':
    main()
