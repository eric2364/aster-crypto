"""Rerun unchanged derivative experiments under corrected partial-exit reserves.

Uses fresh folders. Original outcomes, cohorts and economic protocols stay fixed.
This is an accounting correction, not 16 additional research hypotheses.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results' / 'margin-correction-rerun'
COHORTS = [
    ('carry', 'examples/minute_carry/run.py', 'results/minute-carry-1y-v2',
     'results/minute-carry-margin-v3', 'docs/minute_carry_margin_results', 120),
    ('signed', 'examples/minute_directional/run.py', 'results/minute-directional-1y-v2',
     'results/minute-directional-margin-v3', 'docs/minute_directional_margin_results', 480),
    ('external', 'examples/external_factors/run.py', 'results/external-factor-1y',
     'results/external-factor-margin-v2', 'docs/external_factor_margin_results', 400)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(script, *args):
    subprocess.run([sys.executable, script, *args], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-only', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    package = {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT/'aster').rglob('*.py'))}
    models = {str(p): sha(ROOT/p) for _, script, *_ in COHORTS for p in [Path(script), Path(script).with_name('signals.py')] if (ROOT/p).exists()}
    original = {old: {'protocol_sha256': sha(ROOT/old/'protocol.json'),
                      'summary_sha256': sha(ROOT/old/'summary.json')} for _, _, old, *_ in COHORTS}
    lock = {'package': package, 'models': models, 'originals': original,
            'planned_trials': 1000, 'candidate_count_unchanged': 24,
            'reason': 'proportional isolated reserve release; no closed-leg PnL/fee reassignment to residual',
            'cohorts': COHORTS}
    packet = OUT/'rerun_lock.json'
    if packet.exists():
        if json.loads(packet.read_text()) != json.loads(json.dumps(lock)):
            raise RuntimeError('Rerun source, original results or plan changed')
    else:
        packet.write_text(json.dumps(lock, indent=2)+'\n')
    for _, script, old, new, _, _ in COHORTS:
        command(script, '--out', new, '--freeze-only')
        if json.loads((ROOT/old/'protocol.json').read_text()) != json.loads((ROOT/new/'protocol.json').read_text()):
            raise RuntimeError('Economic protocol changed; accounting-only rerun prohibited')
    if args.freeze_only:
        print('All three fresh protocols equal originals; 1000 accounting-correction trials frozen.', flush=True)
        return
    for name, script, _, new, publish, _ in COHORTS:
        if any(sha(ROOT/p) != value for p, value in package.items()):
            raise RuntimeError('Engine source changed after correction freeze')
        if name == 'carry':
            command(script, '--out', new, '--workers', '4', '--phase', 'validation', '--review-out', publish)
            command(script, '--out', new, '--workers', '4', '--phase', 'holdout', '--review-out', publish)
        else:
            command(script, '--out', new, '--workers', '4', '--publish', publish)
    (OUT/'execution_complete.json').write_text(json.dumps({'all_batches_finished': True,
               'planned_trials': 1000, 'rerun_lock_sha256': sha(packet)}, indent=2)+'\n')
    print('All1000 accounting-correction trials finished; independent audit/publication still required.', flush=True)


if __name__ == '__main__':
    main()
