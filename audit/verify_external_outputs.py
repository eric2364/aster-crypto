"""Independent read-only execution audit; outside frozen experiment sources.

Only sealed trials are read. Outputs and original data are never changed.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

REPO=Path(__file__).resolve().parents[1]


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def close(a,b,label,atol=1e-7):
    if not np.allclose(a,b,rtol=1e-10,atol=atol,equal_nan=False):
        raise AssertionError(label)


def audit(root):
    lock=json.loads((root/'source_lock.json').read_text())
    protocol=json.loads((root/'protocol.json').read_text())
    for path,value in lock['modules'].items():assert sha(REPO/path)==value,f'Frozen module changed: {path}'
    for path,value in lock['data'].items():assert sha(path)==value,f'Frozen dataset changed: {path}'
    assert sha(root/'protocol.json')==lock['protocol'],'Frozen protocol changed'
    snapshots={'executed_run.py':'examples/external_factors/run.py',
               'executed_signals.py':'examples/external_factors/signals.py',
               'executed_shared_kernel.py':'examples/minute_directional/run.py',
               'executed_shared_signals.py':'examples/minute_directional/signals.py',
               'executed_proposed_protocol.md':'examples/external_factors/proposed_protocol.md'}
    for saved,source in snapshots.items():assert sha(root/saved)==lock['modules'][source],saved
    selection=json.loads((root/'selection.json').read_text()) if (root/'selection.json').exists() else None
    expected=set()
    for family in protocol['families']:
        for scale in protocol['scales']:
            for symbol in protocol['symbols']:expected.add((family,symbol,scale,'training',False))
        if selection:
            scale=selection['chosen'][family]
            for symbol in protocol['symbols']:
                for phase in ['validation1','validation2','validation3']:expected.add((family,symbol,scale,phase,False))
                for neighbor in protocol['scales']:expected.add((family,symbol,neighbor,'holdout',False))
                expected.add((family,symbol,scale,'holdout',True))
    rows=[];seen=set();settlements={}
    for seal_path in sorted(root.rglob('execution_outputs.json')):
        trial=seal_path.parent
        seal=json.loads(seal_path.read_text())
        files={f'{ledger}.{suffix}' for ledger in ['equity','fills','trades','funding','events','positions'] for suffix in ['csv','parquet']} | {'metrics.json','metadata.json','quality.json','source_manifest.json'}
        assert seal['version']==1 and set(seal['sha256'])==files,'Incomplete seal'
        for name,value in seal['sha256'].items():assert sha(trial/name)==value,f'Execution file changed: {trial/name}'
        metadata=json.loads((trial/'metadata.json').read_text());p=metadata['parameters']
        identity=(p['family'],p['symbol'],p['scale'],p['phase'],p['stress'])
        assert identity in expected and identity not in seen,f'Unexpected or duplicate trial: {identity}'
        seen.add(identity)
        expected_path=root/p['phase']/p['family']/f"{p['scale']:g}"/('stress' if p['stress'] else 'base')/p['symbol']
        assert trial==expected_path,'Trial path/metadata mismatch'
        assert p['fingerprints']['modules']==lock['modules'],'Worker model fingerprints mismatch'
        assert p['fingerprints']['runtime']==lock['runtime'],'Worker runtime mismatch'
        for path,value in p['fingerprints']['data'].items():assert lock['data'][path]==value,'Worker data mismatch'
        begin=pd.Timestamp(p['requested_start']);stop=pd.Timestamp(p['requested_end_exclusive'])
        if p['phase']=='training':bounds=(pd.Timestamp(protocol['start']),pd.Timestamp(protocol['training_end']))
        elif p['phase']=='holdout':bounds=(pd.Timestamp(protocol['evaluation_start']),pd.Timestamp(protocol['end_exclusive']))
        else:
            k=int(p['phase'][-1])-1;b=pd.Timestamp(protocol['training_end'])
            bounds=(b+pd.DateOffset(months=k),b+pd.DateOffset(months=k+1))
        assert (begin,stop)==bounds,'Wrong requested interval'
        iid='binance:perpetual:'+('1000PEPEUSDT' if p['symbol']=='PEPEUSDT' else p['symbol'])
        assert metadata['instruments'][0]['id']==iid,'Wrong native identity'
        config=metadata['engine'];spec=metadata['instruments'][0]
        assert config['leverage']==1 and config['margin_mode']=='isolated'
        assert config['execution_delay_bars']==int(p['stress'])
        assert config['participation']==(.025 if p['stress'] else .05)
        assert spec['taker_bps']==(10 if p['stress'] else 5)
        baseline_slip=2 if p['symbol'] in ['BTCUSDT','ETHUSDT'] else 8 if p['symbol'] in ['DOGEUSDT','PEPEUSDT'] else 5
        assert config['slippage_bps']==baseline_slip*(2 if p['stress'] else 1),'Wrong baseline/stress slippage'
        assert config['max_gross_leverage']==1 and config['max_position_pct']==.5
        tables={name:pd.read_parquet(trial/f'{name}.parquet') for name in ['equity','fills','funding','trades','positions','events']}
        e,f,u,t,o,v=(tables[x] for x in ['equity','fills','funding','trades','positions','events'])
        initial=sum(config['initial_balances'].values());last=e.iloc[-1]
        assert initial==12500 and p['terminal_open_position_count']==len(o)
        assert e.timestamp.between(begin,stop).all() and e.timestamp.iloc[-1]==stop,'Equity interval mismatch'
        close(e.equity,initial+e.realized_pnl+e.unrealized_pnl+e.funding_pnl-e.trading_fees-e.liquidation_fees,'Every-snapshot equity conservation')
        close(0 if f.empty else f.fee.sum(),last.trading_fees,'Fill fee reconciliation')
        close(0 if u.empty else u.funding_payment.sum(),last.funding_pnl,'Funding reconciliation')
        closed=0 if t.empty else t.net_pnl.sum()
        opened=0 if o.empty else (o.unrealized_pnl+o.funding_pnl-o.entry_fees).sum()
        close(closed+opened,last.equity-initial,'Closed/open PnL conservation')
        signed=0 if f.empty else (f.quantity*f.side).sum()
        close(signed,0 if o.empty else o.quantity.sum(),'Native signed-fill inventory')
        if not f.empty:
            assert f.instrument_id.eq(iid).all() and f.timestamp.ge(begin).all() and f.timestamp.lt(stop).all()
            assert f.quantity.gt(0).all() and f.price.gt(0).all()
            close(f.fee,f.quantity*f.price*spec['taker_bps']/10000,'Native fill fee calculation')
        if not u.empty:
            assert u.instrument_id.eq(iid).all() and u.timestamp.between(begin,stop).all()
            close(u.funding_payment,-u.position_size*u.mark_price*u.funding_rate,'Native settled funding calculation')
            source_path=next(path for path in p['fingerprints']['data'] if path.endswith('/funding.parquet'))
            if source_path not in settlements:settlements[source_path]=pd.read_parquet(source_path)
            matched=u.merge(settlements[source_path][['timestamp','instrument_id','funding_rate','mark_price']],on=['timestamp','instrument_id'],how='left',validate='many_to_one',suffixes=('','_source'))
            close(matched.funding_rate,matched.funding_rate_source,'Actual source settlement rate')
            close(matched.mark_price,matched.mark_price_source,'Actual source settlement mark')
        metrics=json.loads((trial/'metrics.json').read_text())
        close(metrics['total_return'],last.equity/initial-1,'Metrics terminal return')
        series=e.set_index('timestamp').equity
        close(metrics['max_drawdown'],-float((series/series.cummax()-1).min()),'Recorded-clock drawdown')
        daily=series.resample('1D').last().ffill()
        previous=daily.shift(1);previous.iloc[0]=series.iloc[0]
        returns=daily/previous-1
        if len(series)==1 or (series.index[1:].normalize()!=series.index[0].normalize()).all():returns=returns.iloc[1:]
        deviation=returns.std(ddof=1)
        if np.isfinite(deviation) and deviation>0:close(metrics['sharpe'],returns.mean()*np.sqrt(365)/deviation,'Daily Sharpe')
        else:assert metrics['sharpe'] is None,'Undefined Sharpe fabricated'
        notional=0. if o.empty else float((o.quantity.abs()*o.mark_price).sum())
        reserve_fee=notional*spec['taker_bps']/10000
        reserve_slip=notional*config['slippage_bps']/10000
        close(metrics['indicative_exit_fee_reserve'],reserve_fee,'Indicative fee reserve')
        close(metrics['indicative_exit_slippage_reserve'],reserve_slip,'Indicative slippage reserve')
        close(metrics['return_after_indicative_exit_reserve'],(last.equity-reserve_fee-reserve_slip)/initial-1,'Reserve-adjusted terminal return')
        liquidation_count=int(v.type.eq('LIQUIDATION').sum()) if 'type' in v else 0
        assert metrics['liquidation_event_count']==liquidation_count,'Liquidation count mismatch'
        rows.append({'family':p['family'],'symbol':p['symbol'],'scale':p['scale'],'phase':p['phase'],'stress':p['stress'],
                     'return':metrics['total_return'],'funding_pnl':float(last.funding_pnl),
                     'trading_fees':float(last.trading_fees),'open_positions':len(o),'fills':len(f),'liquidations':liquidation_count,
                     'seal_sha256':sha(seal_path),'equity_sha256':seal['sha256']['equity.parquet']})
    return {'completed_sealed_trials':len(rows),'expected_current_trials':len(expected),'all400_complete':len(seen)==400 and seen==expected,
            'missing':sorted(expected-seen),'frozen_sources_checked':len(lock['modules']),'frozen_inputs_checked':len(lock['data']),
            'checks':'Every sealed trial: output seals, exact identity and bounds, code/runtime/data, every-snapshot equity, fees, native funding/source marks, closed/open PnL, signed inventory, terminal returns and liquidation counts',
            'trials':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='results/external-factor-1y');parser.add_argument('--evidence',default='audit/external_factor_execution_evidence.json')
    args=parser.parse_args();result=audit(Path(args.root))
    compact={key:value for key,value in result.items() if key not in ['trials','missing']}
    compact['trial_evidence_sha256']=hashlib.sha256(json.dumps(result['trials'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    compact['phase_counts']=dict(Counter('stress' if row['stress'] else row['phase'] for row in result['trials']))
    compact['liquidation_events_all_trials']=sum(row['liquidations'] for row in result['trials'])
    compact['source_lock_sha256']=sha(Path(args.root)/'source_lock.json')
    compact['missing_trial_count']=len(result['missing'])
    Path(args.evidence).write_text(json.dumps(compact,indent=2)+'\n')
    print({key:value for key,value in result.items() if key not in ['trials','missing']},flush=True)
