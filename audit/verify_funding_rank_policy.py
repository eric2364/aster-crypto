"""Independent recorded-intent checks; no production model/Engine imports.

This component consumes already independently reconstructed pre-callback
accounts. It checks logged proposals/admissions, not completeness of unlogged
skips or a full coordinator-state reconstruction.
"""
from fractions import Fraction
import math
import numpy as np
import pandas as pd
from audit.verify_funding_rank_outputs import SYMBOLS, iid, check, close


def feature_at(features,clock):
    j=features.index.searchsorted(clock,side='right')-1
    check(j>=0 and clock-features.index[j]<=pd.Timedelta(minutes=2),'Policy lacks then-available prices')
    return features.iloc[j]


def ranked_proposal(features,event,begin,stop):
    clock=pd.Timestamp(event['timestamp']);selected=pd.Timestamp(event['selected_at'])
    check(begin<=clock<stop-pd.Timedelta(days=7),'Proposal outside permitted phase entry window')
    check(clock==selected and clock.dayofweek==6 and clock.hour==0 and clock.minute==5
          and clock.second==clock.microsecond==clock.nanosecond==0,'Proposal is not exact Sunday00:05')
    check(pd.Timestamp(event['expires'])==clock+pd.Timedelta(minutes=15),'Proposal expiry changed')
    row=feature_at(features,clock);rates={}
    for symbol in SYMBOLS:
        check(row[f'valid_{symbol}'] is True or isinstance(row[f'valid_{symbol}'],np.bool_) and bool(row[f'valid_{symbol}']), 'Proposal has invalid universe member')
        value=float(row[f'yield_{symbol}']);check(math.isfinite(value),'Invalid proposal yield')
        check(math.isfinite(float(row[f'price_{symbol}'])) and row[f'price_{symbol}']>0,'Invalid proposal price')
        rates[symbol]=value
    ranks=sorted(SYMBOLS,key=lambda s:(rates[s],SYMBOLS.index(s)))
    check(event['ranks']==ranks and event['longs']==ranks[:2] and event['shorts']==ranks[-2:],'Recorded ranks differ from known yields/stable ties')
    check(set(event['yields'])==set(SYMBOLS),'Proposal yield identity differs')
    for s in SYMBOLS:close(event['yields'][s],rates[s],'Frozen proposal yield')
    gap=sum(rates[s] for s in ranks[-2:])/2-sum(rates[s] for s in ranks[:2])/2
    check(gap>0,'Nonpositive proposal rank gap');close(event['gap'],gap,'Proposal gap')
    return {k:event[k] for k in ('longs','shorts','ranks','yields','gap','selected_at','expires')}


def quantity(budget,price,lot):
    b,p,s=map(lambda x:Fraction(str(x)),(budget,price,lot))
    check(min(b,p,s)>0,'Nonpositive sizing input')
    count=(b/p)//s;q=float(count*s)
    if Fraction(str(q))*p>b or q*float(price)>float(budget):q=float(max(0,count-1)*s)
    return q


def verify_intents(features,diagnostics,preopen,accounts,specs,events,begin,stop,config,completed=()):
    """Check every logged proposal and admission; financial replay verifies fills."""
    by_id={s['id']:s for s in specs};ids={iid('binance',s) for s in SYMBOLS}
    check(set(by_id)==ids,'Policy catalog not exact eight native identities')
    proposals={};plans={};entries=0;records=diagnostics['events']
    completed_by_generation={b['generation']:b for b in completed}
    order_records=events.to_dict('records');submitted={e['order_id']:e for e in order_records if e['type']=='ORDER_SUBMITTED'}
    for event in records:
        clock=pd.Timestamp(event['timestamp']);check(begin<=clock<stop,'Intent outside phase')
        if event['type']=='BASKET_EXIT':
            reason=event['reason']
            if reason=='scheduled_weekly_roll':
                check(clock.dayofweek==6 and clock.hour==0 and clock.minute==5 and clock.second==clock.microsecond==clock.nanosecond==0,'Weekly exit outside Sunday00:05')
            elif reason=='terminal_ten_minutes':check(clock==stop-pd.Timedelta(minutes=10),'Terminal close latch clock differs')
            else:
                check(event['generation'] in completed_by_generation,'Held exit lacks an actual completed generation')
                basket=completed_by_generation[event['generation']]
                if reason=='seven_day_safety':check(clock>=pd.Timestamp(basket['completed_at'])+pd.Timedelta(days=7),'Seven-day safety exit precedes actual fourth-fill holding period')
                elif reason=='daily_invalid_or_nonpositive_gap':
                    check(clock.hour==0 and clock.minute==5 and clock.second==clock.microsecond==clock.nanosecond==0,'Daily exit outside00:05')
                    row=feature_at(features,clock);proposal=basket['proposal'];chosen=proposal['longs']+proposal['shorts']
                    valid=all(bool(row[f'valid_{s}']) and math.isfinite(float(row[f'yield_{s}'])) for s in chosen)
                    gap=sum(float(row[f'yield_{s}']) for s in proposal['shorts'])/2-sum(float(row[f'yield_{s}']) for s in proposal['longs'])/2 if valid else None
                    check(not valid or gap<=0,'Daily exit despite valid positive retained-basket gap')
                else:check(False,'Unreviewed basket exit reason')
        elif event['type']=='WEEKLY_PROPOSAL':
            check(clock not in proposals,'Repeated same-clock proposal')
            proposals[clock]=ranked_proposal(features,event,begin,stop)
        elif event['type']=='ADMISSION_DIAGNOSTIC':
            proposal=event['proposal'];selected=pd.Timestamp(proposal['selected_at'])
            check(selected in proposals and proposal==proposals[selected],'Admission reranked or changed frozen Sunday proposal')
            check(selected<=clock<pd.Timestamp(proposal['expires']) and clock<stop-pd.Timedelta(days=7),'Admission expired/final-week')
            check(clock in preopen and all(q==0 for q in preopen[clock].values()),'Admission before actual old inventory flat')
            row=feature_at(features,clock);eq=accounts[clock]['equity'];budget=eq*.25/4
            close(event['entry_equity'],eq,'Fresh pre-callback sizing equity');close(event['per_leg_budget'],budget,'Fresh per-leg budget')
            targets={i:0. for i in ids};notionals={};forecast=cost=0.
            for s in proposal['longs']+proposal['shorts']:
                i=iid('binance',s);spec=by_id[i];price=float(row[f'price_{s}']);q=quantity(budget,price,spec['lot_size']);side=1 if s in proposal['longs'] else -1
                check(q>0 and q>=spec['min_quantity']-1e-9 and q*price>=spec['min_notional']-1e-9,'Opening target below native minimum')
                targets[i]=side*q;notionals[s]=q*price
                forecast-=side*q*price*proposal['yields'][s]*168
                cost+=2*q*price*(spec['taker_bps']+config['slippage_bps'])/10000
            check(set(event['targets'])==ids and set(event['notionals'])==set(notionals),'Plan identities differ')
            for i in ids:close(event['targets'][i],targets[i],'Frozen fresh native target')
            for s in notionals:close(event['notionals'][s],notionals[s],'Rounded entry reference notional')
            close(event['indicative_funding_168h'],forecast,'Frozen-yield funding diagnostic')
            close(event['indicative_roundtrip_cost'],cost,'Unnetted cost diagnostic')
            check(clock not in plans,'Repeated admission sizing clock');plans[clock]=event
        elif event['type']=='TARGET_SUBMITTED':
            delay=pd.Timedelta(milliseconds=config['latency_ms'])+pd.Timedelta(minutes=config['execution_delay_bars'])
            check(pd.Timestamp(event['deadline'])==clock+delay+pd.Timedelta(minutes=5),'Immutable transaction deadline changed')
            orders=event['order_ids'];check(len(set(orders))==len(orders),'Repeated transaction order IDs')
            if event['transition']=='ENTERING':
                entries+=1;check(clock in plans,'Entry lacks causal fresh sizing diagnostic')
                check(event['targets']==plans[clock]['targets'] and len(orders)==4,'Entry targets differ from frozen four-leg plan')
                # Live orders from the prior basket must be resolved before the first new submission.
                positions=[j for j,e in enumerate(order_records) if e.get('order_id') in orders and e['type']=='ORDER_SUBMITTED']
                check(len(positions)==4,'Missing actual four-leg submitted orders');live=set()
                for e in order_records[:min(positions)]:
                    if e['type']=='ORDER_ACCEPTED':live.add(e['order_id'])
                    elif e['type'] in ('ORDER_FILLED','ORDER_CANCELLED','ORDER_REJECTED'):live.discard(e['order_id'])
                check(not live,'Entry while prior live orders unresolved')
            else:check(event['transition']=='EXITING' and all(q==0 for q in event['targets'].values()),'Exit target is not actual-flat intent')
            for oid in orders:
                check(oid in submitted,'Intent lacks actual submitted order');o=submitted[oid];i=o['instrument_id']
                check(pd.Timestamp(o['timestamp'])==clock and pd.Timestamp(o['active_at'])==clock+delay,'Intent order clocks differ')
                check(o['tif']=='GTC' and o['order_type']=='market' and bool(o['reduce_only'])==(event['transition']=='EXITING'),'Intent execution policy differs')
                delta=event['targets'][i]-preopen[clock][i]
                check(o['side']==(1 if delta>0 else -1),'Intent order native side differs');close(o['quantity'],abs(delta),'Immutable order target quantity')
    return dict(recorded_proposals=len(proposals),admission_diagnostics=len(plans),entry_transactions=entries,
                recorded_policy_reconstruction_passed=True,
                scope='Logged proposals/admissions/submitted targets only; omitted unlogged skips and full abort-state completeness not reconstructed')
