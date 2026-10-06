"""Independent logged-intent adversaries, entirely synthetic."""
import copy
import pandas as pd
import pytest
from audit import verify_funding_rank_policy as p


def packet():
    begin=pd.Timestamp('2026-04-05',tz='UTC');select=begin+pd.Timedelta(minutes=5);entry=select+pd.Timedelta(minutes=3);stop=begin+pd.Timedelta(days=30)
    rates=dict(zip(p.SYMBOLS,[-.00004,-.00003,.00003,-.00002,0,.00001,.00002,.00004]))
    ranks=sorted(p.SYMBOLS,key=lambda s:(rates[s],p.SYMBOLS.index(s)));longs=ranks[:2];shorts=ranks[-2:]
    feature=pd.DataFrame(index=[select,entry])
    for s in p.SYMBOLS:
        feature[f'price_{s}']=[100.,200.];feature[f'yield_{s}']=[rates[s],float('nan')];feature[f'valid_{s}']=[True,False]
    specs=[dict(id=p.iid('binance',s),lot_size=.001,min_quantity=.001,min_notional=1,taker_bps=5) for s in p.SYMBOLS]
    proposal=dict(longs=longs,shorts=shorts,ranks=ranks,yields=rates,gap=.00007,selected_at=str(select),expires=str(select+pd.Timedelta(minutes=15)))
    targets={s['id']:0. for s in specs};notionals={}
    for s in longs+shorts:targets[p.iid('binance',s)]=(1 if s in longs else -1)*25.;notionals[s]=5000.
    forecast=-sum((1 if s in longs else -1)*5000*rates[s]*168 for s in longs+shorts)
    plan=dict(timestamp=str(entry),type='ADMISSION_DIAGNOSTIC',proposal=copy.deepcopy(proposal),targets=targets,notionals=notionals,
              entry_equity=80000.,per_leg_budget=5000.,indicative_funding_168h=forecast,indicative_roundtrip_cost=52.)
    cfg=dict(latency_ms=0,execution_delay_bars=1,slippage_bps=8)
    orders=[];ids=[]
    for k,s in enumerate(longs+shorts):
        oid='O'+str(k);ids.append(oid);orders.append(dict(type='ORDER_SUBMITTED',order_id=oid,instrument_id=p.iid('binance',s),
            timestamp=entry,active_at=entry+pd.Timedelta(minutes=1),side=1 if s in longs else -1,quantity=25.,tif='GTC',order_type='market',reduce_only=False))
    tx=dict(type='TARGET_SUBMITTED',timestamp=str(entry),transition='ENTERING',targets=targets,order_ids=ids,deadline=str(entry+pd.Timedelta(minutes=6)))
    diag={'events':[dict(type='WEEKLY_PROPOSAL',timestamp=str(select),**proposal),plan,tx]}
    pre={entry:{s['id']:0. for s in specs}};accounts={entry:{'equity':80000.}}
    return feature,diag,pre,accounts,specs,pd.DataFrame(orders),begin,stop,cfg


def test_delayed_entry_sizes_fresh_equity_prices_but_retains_original_ranks():
    result=p.verify_intents(*packet())
    assert result['recorded_proposals']==result['admission_diagnostics']==result['entry_transactions']==1


@pytest.mark.parametrize('kind',['rerank','old_equity','future_price','wrong_clock','expired','old_position','deadline','unresolved_order'])
def test_independent_recorded_intent_adversaries(kind):
    args=list(packet());feature,diag,pre,accounts,specs,events,begin,stop,cfg=args
    proposal,plan,tx=diag['events'];clock=pd.Timestamp(plan['timestamp'])
    if kind=='rerank':plan['proposal']['longs']=list(reversed(plan['proposal']['longs']))
    elif kind=='old_equity':plan['entry_equity']=100000.
    elif kind=='future_price':feature.loc[clock,'price_BTCUSDT']=100.
    elif kind=='wrong_clock':proposal['timestamp']=str(pd.Timestamp(proposal['timestamp'])+pd.Timedelta(minutes=1))
    elif kind=='expired':plan['proposal']['expires']=plan['timestamp']
    elif kind=='old_position':pre[clock][specs[0]['id']]=1e-13
    elif kind=='deadline':tx['deadline']=str(pd.Timestamp(tx['deadline'])+pd.Timedelta(minutes=1))
    else:args[5]=pd.concat([pd.DataFrame([dict(type='ORDER_ACCEPTED',order_id='OLD',timestamp=clock-pd.Timedelta(minutes=1))]),events],ignore_index=True)
    with pytest.raises(AssertionError):p.verify_intents(*args)


def test_unpublished_price_suffix_cannot_change_recorded_intent_verification():
    args=list(packet());clock=pd.Timestamp(args[1]['events'][1]['timestamp'])
    later=args[0].iloc[-1:].copy();later.index=[clock+pd.Timedelta(minutes=1)]
    for s in p.SYMBOLS:later[f'price_{s}']=1e9
    args[0]=pd.concat([args[0],later]);assert p.verify_intents(*args)['recorded_policy_reconstruction_passed']


@pytest.mark.parametrize('kind',['early_safety','positive_daily','offclock_weekly','early_terminal'])
def test_recorded_exit_cannot_invent_clock_or_invalid_held_gap(kind):
    args=list(packet());proposal=args[1]['events'][0];start=pd.Timestamp(args[1]['events'][1]['timestamp'])
    clock=start+pd.Timedelta(days=1)
    later=args[0].iloc[:1].copy();later.index=[clock.normalize()+pd.Timedelta(minutes=5)]
    args[0]=pd.concat([args[0],later]);clock=later.index[0]
    reason={'early_safety':'seven_day_safety','positive_daily':'daily_invalid_or_nonpositive_gap','offclock_weekly':'scheduled_weekly_roll','early_terminal':'terminal_ten_minutes'}[kind]
    args[1]['events'].append(dict(type='BASKET_EXIT',timestamp=str(clock),generation=1,reason=reason))
    completed=[dict(generation=1,completed_at=str(start),proposal={k:proposal[k] for k in ('longs','shorts')})]
    with pytest.raises(AssertionError):p.verify_intents(*args,completed=completed)
