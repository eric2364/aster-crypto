"""Synthetic native positioning-event coordinator tests; no historical reads."""
from dataclasses import replace
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from examples.positioning_research.strategy import PositioningPortfolio,SYMBOLS,native_quantity
from tests.test_funding_rank_execution import START,catalog,candles,config,Control


def features(minutes=30,eligible=('BTCUSDT',)):
    result={};index=pd.date_range(START+pd.Timedelta(minutes=1),periods=minutes,freq='min')
    for s,spec in catalog().items():
        frame=pd.DataFrame(index=index)
        frame['instrument_id']=spec.id;frame['price']=.01 if s=='PEPEUSDT' else 100.
        frame['price_return_1h']=-.02 if s in eligible else 0.
        frame['price_return_15m']=.004;frame['quantity_change_1h']=-.03;frame['quantity_change_5m']=0.
        frame['valid']=True;frame['metric_available_at']=index-pd.Timedelta(minutes=1)
        frame['price_available_at']=index;frame['metric_age_seconds']=60.
        result[spec.id]=frame
    return result


def controller(eligible=('BTCUSDT',),delay=0,stop=None,specs=None):
    c=Control(specs=specs,delay=delay);s=PositioningPortfolio(features(eligible=eligible),stop or START+pd.Timedelta(days=2));return c,s


def reach(c,s,time=None):
    if time is not None:c.now=time
    tx=s.transaction
    for i,q in tx['targets'].items():c.positions[i].quantity=q;c.positions[i].average_price=c.portfolio.marks[i] if q else 0.
    for o in tx['orders'].values():
        o.status='filled';c.portfolio.fills.append({'instrument_id':o.instrument_id,'order_id':o.id,'timestamp':c.now,'side':o.side,'quantity':o.quantity})


def test_real_engine_only_one_native_long_and_actual_completion():
    s=PositioningPortfolio(features(eligible=('DOGEUSDT','PEPEUSDT')),START+pd.Timedelta(days=2))
    result=Engine(list(catalog().values()),config()).run(candles(minutes=20),s)
    assert len(result.fills)==1 and result.fills.symbol.iloc[0]=='DOGEUSDT'
    assert result.fills.quantity.iloc[0]==100 and result.fills.side.iloc[0]==1
    assert s.completed_entries[0]['completed_at']==result.fills.timestamp.iloc[0]
    assert s.completed_entries[0]['observed_completed_at']>s.completed_entries[0]['completed_at']
    assert not s.completed_episodes and result.equity.iloc[-1].cash==pytest.approx(100000-result.fills.fee.sum())


def test_native_pepe_quantity_and_budget_floor():
    c,s=controller(eligible=('PEPEUSDT',));c.tick(s)
    assert c.orders[0].quantity==1000000 and c.orders[0].instrument_id.endswith('1000PEPEUSDT')
    assert native_quantity(1,.3,.1)*.3<=1


@pytest.mark.parametrize('field,value',[('quantity_change_1h',-.019),('quantity_change_5m',-.00001),
 ('price_return_1h',-.0149),('price_return_15m',.0029),('valid',False),('metric_age_seconds',301),
 ('price',float('nan'))])
def test_each_condition_and_stale_information_fail_closed(field,value):
    c,s=controller();s.features[catalog()['BTCUSDT'].id].loc[c.now,field]=value
    c.tick(s);assert not c.orders


def test_metric_strict_and_price_inclusive_availability():
    c,s=controller();frame=s.features[catalog()['BTCUSDT'].id]
    frame.loc[c.now,'metric_available_at']=c.now;c.tick(s);assert not c.orders
    frame.loc[c.now,'metric_available_at']=c.now-pd.Timedelta(seconds=1)
    frame.loc[c.now,'price_available_at']=c.now+pd.Timedelta(seconds=1);c.tick(s);assert not c.orders
    frame.loc[c.now,'price_available_at']=c.now;c.tick(s);assert len(c.orders)==1


def test_only_five_minute_review_and_no_later_price_lookup():
    c,s=controller();c.tick(s,START+pd.Timedelta(minutes=4));assert not c.orders
    s.features[catalog()['BTCUSDT'].id].loc[START+pd.Timedelta(minutes=6),'price']=1
    c.tick(s,START+pd.Timedelta(minutes=5));assert c.orders[0].quantity==100


def test_pending_entry_does_not_change_when_other_assets_qualify():
    c,s=controller();c.tick(s);tx=s.transaction;target=dict(tx['targets']);c.positions[catalog()['BTCUSDT'].id].quantity=1
    c.positions[catalog()['BTCUSDT'].id].average_price=100;c.orders[0].status='partial'
    s.features[catalog()['PEPEUSDT'].id].loc[:,'price_return_1h']=-.02
    c.tick(s,START+pd.Timedelta(minutes=6))
    assert s.transaction is tx and s.last_targets==target and len(c.orders)==1


@pytest.mark.parametrize('delay,minute',[(0,10),(1,11)])
def test_actual_volume_limited_entry_aborts_without_completed_episode(delay,minute):
    volumes={(m,'BTCUSDT'):40 for m in range(30)}
    s=PositioningPortfolio(features(),START+pd.Timedelta(days=2))
    result=Engine(list(catalog().values()),config(delay)).run(candles(volumes,30),s)
    abort=next(d for d in s.diagnostics if d['type']=='ACCOUNT_ABORT')
    assert abort['timestamp']==START+pd.Timedelta(minutes=minute)
    assert not s.completed_entries and not s.completed_episodes and result.positions.empty
    assert all(result.fills.loc[result.fills.side.eq(-1),'reduce_only']) if 'reduce_only' in result.fills else all(o.reduce_only for o in s.cleanup_orders.values())
    assert result.equity.iloc[-1].cash==pytest.approx(100000+result.fills.realized_pnl.sum()-result.fills.fee.sum())
    flat=next(d for d in s.diagnostics if d['type']=='ABORT_FLAT')
    assert flat['cooldown_until']==flat['timestamp']+pd.Timedelta(hours=1)


def test_stop_during_partial_entry_cancels_open_and_cleans_actual_quantity():
    c,s=controller();c.tick(s);iid=catalog()['BTCUSDT'].id;c.positions[iid].quantity=2;c.positions[iid].average_price=100
    c.orders[0].status='partial';s.features[iid].loc[START+pd.Timedelta(minutes=6),'price']=97
    c.tick(s,START+pd.Timedelta(minutes=6))
    assert c.orders[0].status=='cancelled' and c.orders[1].reduce_only and c.orders[1].quantity==2
    assert s.state=='ABORTING' and not s.completed_entries


def test_four_hour_clock_uses_actual_final_entry_fill_not_observation():
    c,s=controller();c.tick(s);fill=START+pd.Timedelta(minutes=7);reach(c,s,fill);c.tick(s,fill+pd.Timedelta(minutes=1))
    assert s.active['completed_at']==fill
    for frame in s.features.values():
        frame.loc[fill+pd.Timedelta(hours=4)]=frame.iloc[-1].copy()
        frame.loc[fill+pd.Timedelta(hours=4),'metric_available_at']=fill+pd.Timedelta(hours=4)-pd.Timedelta(minutes=1)
        frame.loc[fill+pd.Timedelta(hours=4),'price_available_at']=fill+pd.Timedelta(hours=4)
    c.tick(s,fill+pd.Timedelta(hours=4));assert s.state=='EXITING'
    assert s.episode['exit_reason']=='four_hour_hold'


def test_invalid_held_feature_exits_immediately_not_waiting_review():
    c,s=controller();c.tick(s);reach(c,s);c.tick(s,START+pd.Timedelta(minutes=6))
    s.features[catalog()['BTCUSDT'].id].loc[START+pd.Timedelta(minutes=7),'valid']=False
    c.tick(s,START+pd.Timedelta(minutes=7));assert s.state=='EXITING' and c.orders[-1].reduce_only
    tx=s.transaction;c.tick(s,START+pd.Timedelta(minutes=8));assert s.transaction is tx and len(c.orders)==2


def test_fully_closed_episode_and_cooldown_start_at_observed_flat():
    c,s=controller();c.tick(s);reach(c,s);c.tick(s,START+pd.Timedelta(minutes=6))
    s.features[catalog()['BTCUSDT'].id].loc[START+pd.Timedelta(minutes=7),'price']=97
    c.tick(s,START+pd.Timedelta(minutes=7));reach(c,s,START+pd.Timedelta(minutes=8));c.tick(s,START+pd.Timedelta(minutes=9))
    assert len(s.completed_episodes)==1 and s.completed_episodes[0]['closed_at']==START+pd.Timedelta(minutes=8)
    assert s.cooldown_until==START+pd.Timedelta(minutes=69)
    c.tick(s,START+pd.Timedelta(minutes=10));assert len(c.orders)==2


def test_terminal_retains_existing_exit_ids_and_deadline():
    stop=START+pd.Timedelta(days=2);c,s=controller(stop=stop);c.tick(s);reach(c,s);c.tick(s,START+pd.Timedelta(minutes=6))
    c.now=stop-pd.Timedelta(minutes=11);s._close(c,'test_existing_exit');tx=s.transaction
    c.tick(s,stop-pd.Timedelta(minutes=10))
    assert s.transaction is tx and len(c.orders)==2 and s.terminal_requested


def test_sub_epsilon_native_dust_never_claims_flat_or_retries():
    c,s=controller();s._catalog(c);iid=catalog()['BTCUSDT'].id;c.positions[iid].quantity=1e-12;c.positions[iid].average_price=100
    c.tick(s);assert s.state=='BLOCKED' and not s._flat(c)
    deadline=s.cleanup_deadline;c.tick(s,START+pd.Timedelta(minutes=6))
    assert s.cleanup_deadline==deadline and not c.orders and not s.completed_episodes


@pytest.mark.parametrize('status',['rejected','cancelled'])
def test_cleanup_failure_blocks_without_order_stacking(status):
    c,s=controller();c.tick(s);iid=catalog()['BTCUSDT'].id;c.positions[iid].quantity=2;c.positions[iid].average_price=100
    s._abort(c,'synthetic_failure');old=c.orders[-1];old.status=status
    c.tick(s,START+pd.Timedelta(minutes=6));c.tick(s,START+pd.Timedelta(minutes=7))
    assert s.state=='BLOCKED' and len(c.orders)==2


def test_liquidation_while_flat_latches_one_hour_cooldown():
    c,s=controller();c.portfolio.events.append({'type':'LIQUIDATION'})
    c.tick(s);assert s.state=='COOLDOWN' and s.cooldown_until==c.now+pd.Timedelta(hours=1)
    assert not s.active and not c.orders


def test_minimum_admission_consumes_proposal_and_applies_cooldown():
    specs=catalog();specs['BTCUSDT']=replace(specs['BTCUSDT'],min_notional=20000)
    c,s=controller(specs=specs);c.tick(s)
    assert not c.orders and s.state=='COOLDOWN' and s.rejections[-1]['reason']=='opening_minimum'
    c.tick(s,START+pd.Timedelta(minutes=10));assert len(s.proposals)==1


def test_no_entry_in_final_four_hours_ten_minutes():
    stop=START+pd.Timedelta(hours=4,minutes=15)
    c,s=controller(stop=stop);c.tick(s);assert not c.orders


def test_bad_native_or_unsynchronized_features_fail_before_any_orders():
    source=features();source.pop(catalog()['PEPEUSDT'].id)
    with pytest.raises(ValueError):PositioningPortfolio(source,START+pd.Timedelta(days=2))
    source=features();source[catalog()['BTCUSDT'].id]=source[catalog()['BTCUSDT'].id].iloc[1:]
    with pytest.raises(ValueError):PositioningPortfolio(source,START+pd.Timedelta(days=2))


def test_unowned_live_order_is_cancelled_before_admission_using_public_events():
    from aster.backtest.models import Order
    c,s=controller();spec=catalog()['ADAUSDT'];old=Order(spec.id,1,1)
    c.order(old);c.portfolio.events.append({'type':'ORDER_ACCEPTED','order_id':old.id})
    c.tick(s)
    assert old.status=='cancelled' and len(c.orders)==1 and not s.completed_entries
    assert any(row.get('reason')=='unowned_live_order' for row in s.diagnostics)
    c.portfolio.events.append({'type':'ORDER_CANCELLED','order_id':old.id})
    c.tick(s,START+pd.Timedelta(minutes=6));assert s.state=='COOLDOWN'


def test_live_partial_near_target_cannot_count_as_full_entry():
    c,s=controller();c.tick(s);iid=catalog()['BTCUSDT'].id
    c.positions[iid].quantity=s.transaction['targets'][iid]-1e-10;c.positions[iid].average_price=100
    c.orders[0].status='partial'
    c.tick(s,START+pd.Timedelta(minutes=6))
    assert s.state=='ENTERING' and c.orders[0].status=='partial' and not s.completed_entries


def test_actual_metric_age_is_recomputed_from_decision_not_saved_old_row():
    c,s=controller();iid=catalog()['BTCUSDT'].id;frame=s.features[iid]
    frame.loc[c.now,'metric_age_seconds']=60
    frame.loc[c.now,'metric_available_at']=c.now-pd.Timedelta(minutes=6)
    c.tick(s);assert not c.orders


def test_completed_episode_alias_excludes_open_complete_entries():
    c,s=controller();c.tick(s);reach(c,s);c.tick(s,START+pd.Timedelta(minutes=6))
    assert len(s.completed_entries)==1 and s.completed_baskets is s.completed_episodes and not s.completed_baskets
