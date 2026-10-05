"""Read-only corrected external cohort audit, including isolated reserve states."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audit.verify_external_outputs import audit,close,sha


def reserve_replay(metadata,tables):
    spec=metadata['instruments'][0];config=metadata['engine'];assert spec['market_type']=='perpetual'
    fills=list(tables['fills'].itertuples(index=False));fund=list(tables['funding'].itertuples(index=False))
    events=tables['events']
    liquidation_events=events[events['type'].eq('LIQUIDATION')] if not events.empty else events
    q=average=reserve=0.;fi=ui=partials=liquidations=0;states=[]
    for event in tables['events'].itertuples(index=False):
        if event.type=='FUNDING_PAYMENT':
            row=fund[ui];ui+=1
            assert row.timestamp==event.timestamp and row.instrument_id==event.instrument_id
            close(row.position_size,q,'Funding position for reserve replay')
            close(row.funding_payment,-q*row.mark_price*row.funding_rate,'Reserve funding cash')
            reserve+=row.funding_payment
        elif event.type=='FEE':
            row=fills[fi];fi+=1
            assert row.timestamp==event.timestamp and row.instrument_id==event.instrument_id
            closing=min(abs(q),row.quantity) if q*row.side<0 else 0.
            opening=row.quantity-closing;fraction=closing/abs(q) if closing else 0.
            close(row.realized_pnl,closing*(1 if q>0 else -1)*(row.price-average),'Reserve replay realized PnL')
            if row.exit_reason=='liquidation':
                liquidation_events_at_time=liquidation_events[liquidation_events.timestamp.eq(row.timestamp)]
                assert len(liquidation_events_at_time)==1
                mark=float(liquidation_events_at_time.iloc[0].mark_price)
                maintenance=abs(q)*mark*(spec['maintenance_rate']+(spec['taker_bps']+spec['liquidation_bps'])/10000)
                assert reserve+q*(mark-average)<=maintenance+1e-7,'Liquidation of healthy corrected reserve'
                liquidations+=1
            if closing:
                partials+=int(closing<abs(q)-1e-9)
                reserve*=1-fraction
            if opening:
                if closing or abs(q)<1e-9:reserve=0.;average=row.price
                else:average=(abs(q)*average+opening*row.price)/(abs(q)+opening)
                reserve+=opening*row.price/config['leverage']
            q+=row.side*row.quantity
            if abs(q)<1e-9:q=reserve=average=0.
        else:continue
        states.append((event.timestamp,reserve))
    assert fi==len(fills) and ui==len(fund),'Incomplete reserve event replay'
    e=tables['equity']
    if states:
        history=pd.DataFrame(states,columns=['timestamp','reserve']).groupby('timestamp',sort=True).reserve.last()
        union=history.index.union(pd.DatetimeIndex(e.timestamp)).sort_values()
        expected=history.reindex(union).ffill().reindex(pd.DatetimeIndex(e.timestamp)).fillna(0.)
    else:expected=pd.Series(0.,index=pd.DatetimeIndex(e.timestamp))
    close(e.margin_used.to_numpy(),expected.to_numpy(),'Every-snapshot proportional isolated reserve')
    positions=tables['positions']
    if abs(q)>1e-9:
        assert len(positions)==1 and positions.instrument_id.iloc[0]==spec['id']
        close(positions.quantity.iloc[0],q,'Corrected terminal native quantity')
        close(positions.average_price.iloc[0],average,'Corrected terminal entry price')
        close(positions.collateral.iloc[0],reserve,'Corrected terminal reserve')
    else:assert positions.empty,'Unexpected residual position'
    return {'partial_exits':partials,'liquidations':liquidations}


def verify(root):
    root=Path(root);result=audit(root);rows=[]
    old=Path('results/external-factor-1y')
    assert json.loads((root/'protocol.json').read_text())==json.loads((old/'protocol.json').read_text()),'Economic protocol changed'
    for trial in result['trials']:
        path=root/trial['phase']/trial['family']/f"{trial['scale']:g}"/('stress' if trial['stress'] else 'base')/trial['symbol']
        metadata=json.loads((path/'metadata.json').read_text())
        tables={name:pd.read_parquet(path/f'{name}.parquet') for name in ['equity','fills','funding','events','positions']}
        rows.append(reserve_replay(metadata,tables))
    return {key:value for key,value in result.items() if key not in ['trials','missing']} | {
        'reserve_replay_trials':len(rows),'partial_exits_replayed':sum(row['partial_exits'] for row in rows),
        'corrected_liquidation_events':sum(row['liquidations'] for row in rows),
        'economic_protocol_identical_to_original':True,'source_lock_sha256':sha(root/'source_lock.json')}


def final_receipt(root):
    root=Path(root);result=verify(root)
    assert result['all400_complete'] and result['reserve_replay_trials']==400,'Incomplete corrected external cohort'
    from examples.external_factors.update_results import validate_completed
    summary,trials,_=validate_completed(root)
    identities=sorted((row['family'],row['symbol'],row['scale'],row['phase'],row['stress']) for row in trials)
    assert len(identities)==len(set(identities))==400
    outputs=[]
    for row in trials:
        path=Path(row['path'])
        sealed=json.loads((path/'execution_outputs.json').read_text())
        outputs.append({'path':str(path.resolve()),
                        'identity':[row[key] for key in ['family','symbol','scale','phase','stress']],
                        'output_sha256':sealed['sha256'],'seal_sha256':sha(path/'execution_outputs.json')})
    manifest_path=Path('results/margin-correction-rerun/external_output_seal_manifest.json')
    manifest_path.write_text(json.dumps({'version':1,'cohort':'external','root':str(root.resolve()),'trials':outputs},indent=2)+'\n')
    result.update({'complete':True,'errors':[],'cohort':'external','expected_trials':400,
                   'summary_reconstruction_passed':True,'training_selection_reconstruction_passed':True,
                   'pooled_equity_reconstruction_passed':True,'external_hurdle_pass_count':summary['pass_count'],
                   'rerun_lock_sha256':sha(Path('results/margin-correction-rerun/rerun_lock.json')),
                   'summary_sha256':sha(root/'summary.json'),'selection_sha256':sha(root/'selection.json'),
                   'all_trials_sha256':sha(root/'all_trials.json'),
                   'metadata_identity_digest':hashlib.sha256(json.dumps(identities,separators=(',',':')).encode()).hexdigest(),
                   'output_manifest_path':str(manifest_path.resolve()),'output_manifest_sha256':sha(manifest_path),
                   'root':str(root.resolve())})
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='results/external-factor-margin-v2');parser.add_argument('--evidence',default='audit/corrected_external_evidence.json');parser.add_argument('--final',action='store_true');args=parser.parse_args()
    result=final_receipt(args.root) if args.final else verify(args.root)
    Path(args.evidence).write_text(json.dumps(result,indent=2)+'\n');print(result)
