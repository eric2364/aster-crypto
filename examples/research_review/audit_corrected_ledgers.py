"""Read-only independent cash/quantity/isolated-reserve replay of corrected exports.

Does not import the trading engine or run a strategy. Safe to run during a cohort:
only trial folders containing metadata and all six parquet ledgers are inspected.
An interim report does not certify missing/not-yet-completed trials.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import math
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
COHORTS = [
    ('carry', 'minute-carry-margin-v3', 'minute-carry-1y-v2', 120),
    ('signed', 'minute-directional-margin-v3', 'minute-directional-1y-v2', 480),
]


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): value.update(chunk)
    return value.hexdigest()


def close(actual, expected, description):
    if not math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=2e-7):
        raise AssertionError(f'{description}: {actual} != {expected}')


def trial(path, lock, original):
    metadata = json.loads((path/'metadata.json').read_text())
    config = metadata['engine']
    assert config['margin_mode'] == 'isolated'
    specs = {s['id']: s for s in metadata['instruments']}
    frames = {name: pd.read_parquet(path/f'{name}.parquet')
              for name in ['fills', 'funding', 'trades', 'events', 'positions', 'equity']}
    parameters = metadata['parameters']
    fingerprints = parameters['fingerprints']
    assert fingerprints['package'] == lock['package'], 'wrong frozen package identity'
    original_exact = original
    selected_scale_changed = not (original/'metadata.json').exists()
    if selected_scale_changed:
        # Corrected training can select a different scale without changing the procedure.
        relative=original.relative_to(ROOT/'results'/'minute-directional-1y-v2')
        phase,family,scale,scenario,symbol=relative.parts
        candidates=sorted((original.parents[2]).glob(f'*/{scenario}/{symbol}/metadata.json'))
        assert candidates, 'no original comparable economic trial'
        original=candidates[0].parent
        selection=json.loads((ROOT/'results/minute-directional-margin-v3/selection.json').read_text())
        assert parameters['scale']==selection['chosen'][family], 'not corrected training-selected scale'
    previous = json.loads((original/'metadata.json').read_text())
    old_package=previous['parameters']['fingerprints']['package']
    assert {p for p in lock['package'] if old_package.get(p)!=lock['package'][p]}=={'aster/backtest/portfolio.py'}, 'unexpected core delta'
    assert previous['engine'] == config, 'economic engine configuration changed'
    assert previous['instruments'] == metadata['instruments'], 'instrument assumptions changed'
    # Actual safety exits and residual counts may legitimately change after the fix.
    for key in ['family', 'policy', 'symbol', 'scale', 'phase', 'stress',
                'requested_start', 'requested_end_exclusive']:
        if key=='scale' and selected_scale_changed: continue
        assert parameters.get(key) == previous['parameters'].get(key), f'changed trial {key}'
    old_fingerprints = previous['parameters']['fingerprints']
    if 'runner' in fingerprints:
        script = 'examples/minute_carry/run.py' if 'minute-carry' in str(path) else 'examples/minute_directional/run.py'
        assert fingerprints['runner'] == lock['models'][script], 'current runner differs from correction freeze'
    assert {k:v for k,v in fingerprints.items() if k not in ('package','runner','cross_feature_matrix','cross_feature_manifest')} == {
        k:v for k,v in old_fingerprints.items() if k not in ('package','runner','cross_feature_matrix','cross_feature_manifest')}, 'data/model fingerprint changed'

    states = {iid: dict(q=0., average=0., reserve=0., funding=0., entry_fees=0.) for iid in specs}
    cash = sum(config['initial_balances'].values())
    realized = fees = payments = liquidation_fees = 0.
    fills = list(frames['fills'].itertuples(index=False))
    settlements = list(frames['funding'].itertuples(index=False))
    fill_index = funding_index = partial_exits = 0
    # FEE is emitted once by every applied fill, including forced liquidations;
    # this event sequence disambiguates close/funding/open at the same timestamp.
    for event in frames['events'].itertuples(index=False):
        if event.type == 'FUNDING_PAYMENT':
            row = settlements[funding_index]; funding_index += 1
            assert row.timestamp == event.timestamp and row.instrument_id == event.instrument_id
            s = states[row.instrument_id]
            close(row.position_size, s['q'], 'settled native quantity')
            payment = -s['q'] * row.mark_price * row.funding_rate
            close(row.funding_payment, payment, 'funding cash')
            close(event.amount, payment, 'funding event')
            cash += payment; payments += payment
            s['reserve'] += payment; s['funding'] += payment
        elif event.type == 'FEE':
            row = fills[fill_index]; fill_index += 1
            assert row.timestamp == event.timestamp and row.instrument_id == event.instrument_id
            spec = specs[row.instrument_id]; s = states[row.instrument_id]
            old = s['q']; signed = row.side * row.quantity
            if row.exit_reason=='liquidation':
                local_equity=s['reserve']+old*(row.reference_price-s['average'])
                requirement=abs(old)*row.reference_price*(spec['maintenance_rate']+(spec['taker_bps']+spec['liquidation_bps'])/10000)
                assert local_equity<=requirement+2e-7, 'liquidation of independently healthy reserve'
            closing = min(abs(old), row.quantity) if old * signed < 0 else 0.
            fraction = closing / abs(old) if closing else 0.
            opening = row.quantity - closing
            pnl = closing * (1 if old>0 else -1) * (row.price-s['average'])
            close(row.realized_pnl, pnl, 'fill realized pnl')
            fee = row.quantity * row.price * spec[f'{row.liquidity_type}_bps'] / 10000
            close(row.fee, fee, 'fill fee'); close(event.amount, -fee, 'fee event')
            cash += pnl if spec['market_type']=='perpetual' else -signed * row.price
            cash -= fee; fees += fee; realized += pnl
            if closing:
                partial_exits += int(closing < abs(old)-1e-10)
                # Closed P&L and fees affect wallet, not the remaining allocation.
                s['reserve'] *= 1-fraction
                s['funding'] *= 1-fraction
                s['entry_fees'] *= 1-fraction
                if row.exit_reason == 'liquidation':
                    penalty = closing * row.price * spec['liquidation_bps'] / 10000
                    cash -= penalty; liquidation_fees += penalty
            if opening:
                if closing or abs(old)<1e-10:
                    s.update(average=row.price, reserve=0., funding=0., entry_fees=0.)
                else:
                    s['average'] = (abs(old)*s['average']+opening*row.price)/(abs(old)+opening)
                if spec['market_type']=='perpetual': s['reserve'] += opening*row.price/config['leverage']
                s['entry_fees'] += fee * opening/row.quantity
            s['q'] = old + signed
            if abs(s['q']) < 1e-10: s.update(q=0., average=0., reserve=0., funding=0., entry_fees=0.)
    assert fill_index == len(fills) and funding_index == len(settlements), 'incomplete event replay'
    final = frames['equity'].iloc[-1]
    for actual, expected, name in [(final.cash,cash,'wallet cash'), (final.realized_pnl,realized,'realized pnl'),
                                  (final.trading_fees,fees,'fees'), (final.funding_pnl,payments,'funding'),
                                  (final.liquidation_fees,liquidation_fees,'liquidation fees')]:
        close(actual,expected,name)
    positions = frames['positions']
    actual_ids = set(positions.instrument_id) if len(positions) else set()
    assert actual_ids == {iid for iid,s in states.items() if abs(s['q'])>1e-10}, 'terminal identity'
    inventory = total_upl = margin = 0.
    for row in positions.itertuples(index=False):
        s = states[row.instrument_id]; spec = specs[row.instrument_id]
        for actual,expected,name in [(row.quantity,s['q'],'quantity'),(row.average_price,s['average'],'average'),
                                    (row.collateral,s['reserve'],'isolated reserve'),(row.funding_pnl,s['funding'],'open funding'),
                                    (row.entry_fees,s['entry_fees'],'open entry fees')]: close(actual,expected,name)
        upl = s['q']*(row.mark_price-s['average'])
        close(row.unrealized_pnl,upl,'terminal upl'); total_upl += upl
        if spec['market_type']=='spot': inventory += s['q']*row.mark_price
        else: margin += s['reserve']
    close(frames['trades'].liquidation_fee.sum() if len(frames['trades']) else 0,liquidation_fees,'trade liquidation fees')
    closed_net=frames['trades'].net_pnl.sum() if len(frames['trades']) else 0
    open_net=sum(r.unrealized_pnl+r.funding_pnl-r.entry_fees for r in positions.itertuples(index=False))
    close(closed_net+open_net,final.equity-sum(config['initial_balances'].values()),'closed/open equity attribution')
    close(final.unrealized_pnl,total_upl,'total unrealized pnl')
    close(final.margin_used,margin,'terminal margin')
    close(final.equity,cash+inventory+sum(s['q']*(r.mark_price-s['average'])
          for r in positions.itertuples(index=False) for s in [states[r.instrument_id]]
          if specs[r.instrument_id]['market_type']=='perpetual'),'marked equity')
    return dict(path=str(path.relative_to(ROOT)), fills=len(fills), settlements=len(settlements),
                partial_exits=partial_exits, terminal_positions=len(positions),
                liquidation_fills=sum(r.exit_reason=='liquidation' for r in fills),
                equity=float(final.equity), metadata_sha256=digest(path/'metadata.json'), original_comparison=str(original.relative_to(ROOT)),
                selected_scale_changed=selected_scale_changed, original_runner_sha256=old_fingerprints.get('runner'),
                corrected_runner_sha256=fingerprints.get('runner'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seal', action='store_true', help='Hash all16 exported execution files for final publication guard')
    parser.add_argument('--report', default='results/margin-correction-rerun/independent_ledger_audit.json')
    args = parser.parse_args()
    lock = json.loads((ROOT/'results/margin-correction-rerun/rerun_lock.json').read_text())
    assert all(digest(ROOT/p)==h for p,h in lock['package'].items()), 'current core differs from freeze'
    assert all(digest(ROOT/p)==h for p,h in lock['models'].items()), 'current models differ from freeze'
    result = dict(scope='independent arithmetic replay, no engine imports or strategy execution',
                  complete=False, sealed=args.seal, planned_trials=600, trials=[], errors=[], cohorts={})
    original_carry=ROOT/'results/minute-carry-1y-v2/executed_runner.py'
    current_carry=ROOT/'examples/minute_carry/run.py'
    def definitions(path):
        return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text()).body
                if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    old_defs,new_defs=definitions(original_carry),definitions(current_carry)
    execution=['MatchedCarry','common_step','decisions','fingerprint','freeze','published_factors','rotation_signals','run_job','aggregate','summarize']
    assert all(old_defs[name]==new_defs[name] for name in execution), 'carry execution definitions changed'
    result['carry_source_comparison']={'execution_definitions_ast_equal':execution,
         'changed_definitions':[name for name in old_defs if old_defs[name]!=new_defs.get(name)],
         'added_definitions':sorted(set(new_defs)-set(old_defs)),
         'original_runner_sha256':digest(original_carry),'corrected_runner_sha256':digest(current_carry)}
    signed_old=ROOT/'results/minute-directional-1y-v2/executed_run.py'
    signed_new=ROOT/'examples/minute_directional/run.py'
    assert digest(signed_old)==digest(signed_new), 'signed execution runner changed'
    result['signed_source_comparison']={'byte_identical':True,'runner_sha256':digest(signed_new)}
    for name,new,old,expected in COHORTS:
        new_root = ROOT/'results'/new; old_root = ROOT/'results'/old
        assert json.loads((new_root/'protocol.json').read_text()) == json.loads((old_root/'protocol.json').read_text())
        completed = 0
        for path in sorted(new_root.rglob('metadata.json')):
            folder=path.parent
            if not all((folder/f'{n}.parquet').exists() for n in ['equity','fills','trades','funding','events','positions']): continue
            try:
                row=trial(folder,lock,old_root/folder.relative_to(new_root))
                if args.seal:
                    names=['metadata.json','metrics.json','source_manifest.json','quality.json']+[f'{name}.{ext}' for name in ['equity','fills','trades','funding','events','positions'] for ext in ['csv','parquet']]
                    row['output_sha256']={name:digest(folder/name) for name in names}
                result['trials'].append(row); completed += 1
            except Exception as exc: result['errors'].append(dict(path=str(folder.relative_to(ROOT)),error=str(exc)))
        result['cohorts'][name]=dict(passed=completed,expected=expected)
    result['complete'] = not result['errors'] and all(c['passed']==c['expected'] for c in result['cohorts'].values())
    target = ROOT/args.report; target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='trials'},indent=2))
    if result['errors']: raise SystemExit(1)


if __name__=='__main__': main()
