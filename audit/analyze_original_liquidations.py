"""Diagnose original recorded liquidation states without rerunning a strategy.

The proportional-only margin column conditions on the SAME historical fills;
subsequent corrected strategy paths must be established by separately frozen runs.
"""
from collections import Counter
import json
from pathlib import Path
import pandas as pd

ROOT=Path('results/external-factor-1y')


def analyze(root=ROOT):
    root=Path(root)
    if (root/'all_trials.json').exists():
        trials=json.loads((root/'all_trials.json').read_text())
    else:
        trials=[]
        for metric_path in sorted(root.rglob('metrics.json')):
            if metric_path.parent.parent.name not in ['base','stress']:continue
            metadata=json.loads(metric_path.with_name('metadata.json').read_text());params=metadata['parameters']
            trials.append({'family':params['policy'],'symbol':metric_path.parent.name,'scale':None,
                           'phase':params['phase'],'stress':params['stress'],'path':str(metric_path.parent),
                           'metrics':json.loads(metric_path.read_text())})
    rows=[]
    for trial in trials:
        if not trial['metrics'].get('liquidation_event_count',trial['metrics'].get('liquidation_count',0)):continue
        path=Path(trial['path']);metadata=json.loads((path/'metadata.json').read_text())
        specs=[spec for spec in metadata['instruments'] if spec['market_type']=='perpetual']
        assert len(specs)==1
        spec=specs[0];leverage=metadata['engine']['leverage']
        fills=pd.read_parquet(path/'fills.parquet');funding=pd.read_parquet(path/'funding.parquet')
        fills=fills[fills.instrument_id.eq(spec['id'])] if not fills.empty else fills
        funding=funding[funding.instrument_id.eq(spec['id'])] if not funding.empty else funding
        events=pd.read_parquet(path/'events.parquet');liquidations=events[events.type.eq('LIQUIDATION') & events.instrument_id.eq(spec['id'])]
        timeline=[(f.timestamp,1,int(f.fill_id),'fill',f) for f in fills.itertuples()]
        if not funding.empty:timeline += [(f.timestamp,0,0,'funding',f) for f in funding.itertuples()]
        timeline.sort(key=lambda x:x[:3])
        quantity=average=old_margin=proportional_margin=0.;prior=None
        for _,_,_,kind,event in timeline:
            if kind=='funding':
                assert abs(event.position_size-quantity)<max(1e-6,abs(quantity)*1e-10),'Funding/fill chronological ordering mismatch'
                old_margin+=event.funding_payment;proportional_margin+=event.funding_payment
                continue
            signed=event.side*event.quantity
            closing=min(abs(quantity),event.quantity) if quantity*signed<0 else 0.
            opening=event.quantity-closing
            fraction=closing/abs(quantity) if closing else 0.
            if event.exit_reason=='liquidation':
                recorded=liquidations[liquidations.timestamp.eq(event.timestamp)]
                assert len(recorded)==1
                mark=float(recorded.iloc[0].mark_price)
                unrealized=quantity*(mark-average)
                threshold=abs(quantity)*mark*(spec['maintenance_rate']+(spec['taker_bps']+spec['liquidation_bps'])/10000)
                rows.append({'cohort':root.name,'family':trial['family'],'symbol':trial['symbol'],'scale':trial['scale'],
                             'phase':trial['phase'],'stress':trial['stress'],'timestamp':str(event.timestamp),
                             'native_quantity_before_prior_fill':None if prior is None else prior['quantity_before'],
                             'preceding_fill_quantity':None if prior is None else prior['fill_quantity'],
                             'preceding_closed_fraction':None if prior is None else prior['closed_fraction'],
                             'preceding_fill_same_timestamp':prior is not None and prior['timestamp']==event.timestamp,
                             'remaining_native_quantity':quantity,'liquidated_native_quantity':event.quantity,
                             'remaining_marked_notional':abs(quantity)*mark,'entry_price':average,'mark_price':mark,
                             'old_recorded_margin':old_margin,'proportional_only_margin_same_fills':proportional_margin,
                             'remaining_unrealized_pnl':unrealized,'old_isolated_equity':old_margin+unrealized,
                             'proportional_isolated_equity_same_fills':proportional_margin+unrealized,
                             'maintenance_including_exit_costs':threshold,
                             'old_state_below_maintenance':old_margin+unrealized<=threshold+1e-7,
                             'same_fills_proportional_state_above_maintenance':proportional_margin+unrealized>threshold+1e-7,
                             'preceding_realized_pnl':None if prior is None else prior['realized_pnl'],
                             'liquidation_exit_fee':event.fee,'liquidation_penalty':event.quantity*event.price*spec['liquidation_bps']/10000})
            prior={'timestamp':event.timestamp,'quantity_before':quantity,'fill_quantity':event.quantity,
                   'closed_fraction':fraction,'realized_pnl':event.realized_pnl}
            old_margin*=1-fraction;proportional_margin*=1-fraction
            if closing and abs(quantity)-closing>1e-9:old_margin+=event.realized_pnl-event.fee*closing/event.quantity
            if opening:
                if closing or abs(quantity)<1e-9:
                    old_margin=proportional_margin=0.;average=event.price
                else:average=(abs(quantity)*average+opening*event.price)/(abs(quantity)+opening)
                old_margin+=opening*event.price/leverage;proportional_margin+=opening*event.price/leverage
            quantity+=signed
            if abs(quantity)<1e-9:quantity=average=old_margin=proportional_margin=0.
    counts=Counter((row['family'],row['phase'],'stress' if row['stress'] else 'base') for row in rows)
    summary={'original_liquidation_events':len(rows),
             'all_old_states_below_maintenance':all(row['old_state_below_maintenance'] for row in rows),
             'same_recorded_fills_healthy_under_proportional_reserve_count':sum(row['same_fills_proportional_state_above_maintenance'] for row in rows),
             'immediately_after_same_timestamp_partial_exit_count':sum(row['preceding_fill_same_timestamp'] and 0<row['preceding_closed_fraction']<1 for row in rows),
             'minimum_preceding_closed_fraction':min(row['preceding_closed_fraction'] for row in rows),
             'maximum_remaining_marked_notional':max(row['remaining_marked_notional'] for row in rows),
             'counts_by_family_phase':{'/'.join(key):value for key,value in counts.items()},
             'limitation':'Conditional state replay of unchanged observed fills; not corrected strategy trajectories, outcomes or proof every future liquidation disappears',
             'events':rows}
    summary['original_trial_count']=len(trials)
    return summary



def analyze_all():
    roots=['results/minute-carry-1y-v2','results/minute-directional-1y-v2','results/external-factor-1y']
    cohorts={Path(root).name:analyze(Path(root)) for root in roots}
    events=[row for cohort in cohorts.values() for row in cohort['events']]
    result={'original_derivative_trials':sum(c['original_trial_count'] for c in cohorts.values()),
            'original_liquidation_events':len(events),
            'conditional_same_fills_healthy_count':sum(e['same_fills_proportional_state_above_maintenance'] for e in events),
            'cohorts':{name:{k:v for k,v in cohort.items() if k!='events'} for name,cohort in cohorts.items()},
            'limitation':'Conditional same-recorded-fill state replay; corrected full strategy trajectories and final economics require independently frozen reruns.'}
    Path('audit/original_derivative_liquidation_states.json').write_text(json.dumps({**result,'events':events},indent=2)+'\n')
    pd.DataFrame(events).to_csv('docs/original_derivative_liquidation_states.csv',index=False)
    Path('docs/original_derivative_liquidation_review.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all',action='store_true',help='Scope all1000 original derivative trials and77 events')
    args=parser.parse_args()
    if args.all:
        print(analyze_all())
    else:
        result=analyze();Path('audit/original_liquidation_states.json').write_text(json.dumps(result,indent=2)+'\n')
        pd.DataFrame(result.pop('events')).to_csv('docs/original_liquidation_states.csv',index=False)
        Path('docs/original_liquidation_review.json').write_text(json.dumps(result,indent=2)+'\n')
        print(result)
