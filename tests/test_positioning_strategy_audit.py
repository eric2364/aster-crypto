"""Independent coordinator adversaries, with actual tiny Engine executions."""
from dataclasses import replace
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from aster.backtest.models import Order
from aster.strategies.base import BaseStrategy
from examples.positioning_research.strategy import PositioningPortfolio
from tests.test_positioning_strategy import controller,features,reach
from tests.test_funding_rank_execution import START,catalog,candles,config


@pytest.mark.parametrize('label',['BTCUSDT','ADAUSDT'])
@pytest.mark.parametrize('inject_minute',[5,6])
def test_actual_engine_unowned_selected_or_dormant_order_aborts_and_resolves(label,inject_minute):
    strategy=PositioningPortfolio(features(),START+pd.Timedelta(days=2));unexpected=[]
    class Inject(BaseStrategy):
        def on_bars(self,ctx,bars):
            if ctx.now==START+pd.Timedelta(minutes=inject_minute):
                order=Order(catalog()[label].id,1,1.,tif='GTC');ctx.order(order)
                unexpected.append(order.id)
            strategy.on_bars(ctx,bars)
    result=Engine(list(catalog().values()),config()).run(candles(minutes=20),Inject())
    assert len(unexpected)==1
    abort=[x for x in strategy.diagnostics if x['type']=='ACCOUNT_ABORT']
    assert len(abort)==1 and abort[0]['reason']=='unowned_live_order'
    assert not result.fills.order_id.isin(unexpected).any() if len(result.fills) else True
    assert result.positions.empty and strategy.state=='COOLDOWN'
    flat=next(x for x in strategy.diagnostics if x['type']=='ABORT_FLAT')
    assert flat['cooldown_until']==flat['timestamp']+pd.Timedelta(hours=1)
    assert not strategy.completed_episodes


def test_fresh_rejected_admission_has_one_hour_cooldown_without_queued_alternative():
    specs=catalog();specs['BTCUSDT']=replace(specs['BTCUSDT'],min_notional=20000)
    c,s=controller(eligible=('BTCUSDT','PEPEUSDT'),specs=specs);c.tick(s)
    assert s.state=='COOLDOWN' and s.cooldown_until==c.now+pd.Timedelta(hours=1)
    c.tick(s,START+pd.Timedelta(minutes=10));assert not c.orders and len(s.proposals)==1
    # All former candidates have disappeared by the end of cooldown. There is no queued PEPE retry.
    s.features=features(minutes=80,eligible=())
    c.tick(s,START+pd.Timedelta(minutes=65));assert not c.orders and not s.episode


def test_previous_valid_frame_cannot_extend_actual_metric_expiry():
    c,s=controller();iid=catalog()['BTCUSDT'].id
    for frame in s.features.values():
        frame.drop(index=[START+pd.Timedelta(minutes=x) for x in (6,7)],inplace=True)
        frame.loc[c.now,'metric_available_at']=c.now-pd.Timedelta(minutes=5)
        frame.loc[c.now,'metric_age_seconds']=300.
    c.tick(s);assert len(c.orders)==1
    c.tick(s,START+pd.Timedelta(minutes=6))
    assert c.orders[0].status=='cancelled' and not s.completed_entries
    assert any(x['type']=='ACCOUNT_ABORT' and x['reason']=='partial_entry_invalid_or_stale_feature' for x in s.diagnostics)


@pytest.mark.parametrize('field',['metric_available_at','price_available_at'])
def test_missing_causal_clock_fails_before_entry(field):
    source=features()
    for frame in source.values():frame.drop(columns=[field],inplace=True)
    with pytest.raises(ValueError):PositioningPortfolio(source,START+pd.Timedelta(days=2))


def test_filled_target_with_unresolved_partial_order_is_not_completed_entry():
    c,s=controller();c.tick(s);reach(c,s)
    c.orders[0].status='partial'
    c.tick(s,START+pd.Timedelta(minutes=6))
    assert not s.completed_entries and not s.completed_baskets
    c.tick(s,START+pd.Timedelta(minutes=10))
    assert any(x['type']=='ACCOUNT_ABORT' for x in s.diagnostics)


def test_real_partial_entry_four_hour_clock_and_closed_episode_breadth():
    volume={(m,'BTCUSDT'):1000. for m in range(270)} #50 native/min: entry target100 takes two actual fills
    s=PositioningPortfolio(features(minutes=270),START+pd.Timedelta(days=2))
    result=Engine(list(catalog().values()),config()).run(candles(volume,270),s)
    opening=result.fills.loc[result.fills.side.eq(1)];closing=result.fills.loc[result.fills.side.eq(-1)]
    assert len(opening)==2 and opening.quantity.sum()==100
    actual=opening.timestamp.max();assert actual==START+pd.Timedelta(minutes=6)
    assert s.completed_entries[0]['completed_at']==actual
    exit_event=next(x for x in s.diagnostics if x['type']=='EPISODE_EXIT')
    assert exit_event['reason']=='four_hour_hold' and exit_event['timestamp']==actual+pd.Timedelta(hours=4)
    assert len(s.completed_baskets)==len(s.completed_episodes)==1 and result.positions.empty
    assert s.completed_episodes[0]['closed_at']==closing.timestamp.max()
    assert result.equity.iloc[-1].cash==pytest.approx(100000+result.fills.realized_pnl.sum()-result.fills.fee.sum())


def test_entry_only_does_not_count_as_completed_episode():
    s=PositioningPortfolio(features(eligible=('PEPEUSDT',)),START+pd.Timedelta(days=2))
    result=Engine(list(catalog().values()),config()).run(candles(minutes=20),s)
    assert len(s.completed_entries)==1 and not s.completed_baskets and not s.completed_episodes
    assert result.fills.quantity.iloc[0]==1000000 and result.fills.symbol.iloc[0]=='1000PEPEUSDT'


@pytest.mark.parametrize('delay',[0,1])
def test_terminal_keeps_valid_exit_order_ids_and_original_deadline(delay):
    c,s=controller(delay=delay);c.tick(s);reach(c,s);c.tick(s,START+pd.Timedelta(minutes=6))
    c.now=START+pd.Timedelta(minutes=7);s._close(c,'synthetic_existing_exit');tx=s.transaction
    original=tx['deadline'];s.stop=START+pd.Timedelta(minutes=18)
    c.tick(s,START+pd.Timedelta(minutes=8))
    assert s.terminal_requested and s.transaction is tx and tx['deadline']==original and len(c.orders)==2


def test_abort_deadline_remains_immutable_while_actual_cleanup_partial():
    c,s=controller();c.tick(s);iid=catalog()['BTCUSDT'].id;c.positions[iid].quantity=1.;c.positions[iid].average_price=100.
    s._abort(c,'synthetic');deadline=s.cleanup_deadline;order=c.orders[-1];order.status='partial'
    for minute in (6,8,10,12):c.tick(s,START+pd.Timedelta(minutes=minute))
    assert s.cleanup_deadline==deadline and c.orders[-1] is order and len(c.orders)==2
    assert s.state=='BLOCKED' and s.cooldown_until is None and not s.completed_baskets
    assert sum(x['type']=='CLEANUP_DEADLINE_EXCEEDED' for x in s.diagnostics)==1


@pytest.mark.parametrize('offset_ms,expected',[ (0,0.),(500,-10.)])
def test_actual_native_pepe_funding_at_entry_boundary_never_retroactive(offset_ms,expected):
    s=PositioningPortfolio(features(eligible=('PEPEUSDT',)),START+pd.Timedelta(days=2))
    funding=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=5,milliseconds=offset_ms),
        instrument_id=catalog()['PEPEUSDT'].id,funding_rate=.001,mark_price=.01)])
    result=Engine(list(catalog().values()),config()).run(candles(minutes=20),s,funding=funding)
    amount=result.funding.funding_payment.sum() if len(result.funding) else 0.
    assert amount==pytest.approx(expected)
    assert result.equity.iloc[-1].cash==pytest.approx(100000-result.fills.fee.sum()+amount)
    assert result.fills.quantity.iloc[0]==1000000


def test_actual_observer_retains_pending_exit_before_automatic_cancellation():
    from examples.funding_rank.run import SnapshotObserver,terminal_status
    source=features();iid=catalog()['BTCUSDT'].id
    source[iid].loc[START+pd.Timedelta(minutes=7):,'price']=97.
    s=PositioningPortfolio(source,START+pd.Timedelta(days=2))
    engine=Engine(list(catalog().values()),config());observer=SnapshotObserver(engine);engine.portfolio.snapshot=observer
    volume={(m,'BTCUSDT'):0. for m in range(6,20)}
    result=engine.run(candles(volume,20),s)
    assert len(result.positions)==1 and result.positions.quantity.iloc[0]==100.
    assert len(observer.last_orders)==1 and observer.last_orders[0]['reduce_only']
    assert not engine.orders
    assert not terminal_status(observer.rows[-1],observer.last_orders)['terminal_flat_resolved']


def test_full_native_observer_does_not_hide_subEPS_blocked_dust():
    from examples.funding_rank.run import SnapshotObserver,terminal_status
    s=PositioningPortfolio(features(),START+pd.Timedelta(days=2));iid=catalog()['ADAUSDT'].id
    class Inject(BaseStrategy):
        def on_bars(self,ctx,bars):
            if ctx.now==START+pd.Timedelta(minutes=5):
                ctx.positions[iid].quantity=1e-12;ctx.positions[iid].average_price=100.
            s.on_bars(ctx,bars)
    engine=Engine(list(catalog().values()),config());observer=SnapshotObserver(engine);engine.portfolio.snapshot=observer
    result=engine.run(candles(minutes=20),Inject())
    assert result.positions.empty and s.state=='BLOCKED' and not s.completed_baskets
    assert observer.rows[-1]['quantity_ADAUSDT']==1e-12
    assert not terminal_status(observer.rows[-1],observer.last_orders)['terminal_flat_resolved']


def test_unowned_already_filled_order_cannot_silently_increase_selected_holding():
    c,s=controller();c.tick(s);reach(c,s);c.tick(s,START+pd.Timedelta(minutes=6))
    iid=catalog()['BTCUSDT'].id;assert s.active and c.positions[iid].quantity==100.
    clock=START+pd.Timedelta(minutes=7)
    c.portfolio.events.extend([
        dict(type='ORDER_ACCEPTED',timestamp=clock,instrument_id=iid,order_id='UNOWNED_FILLED'),
        dict(type='ORDER_FILLED',timestamp=clock,instrument_id=iid,order_id='UNOWNED_FILLED')])
    c.positions[iid].quantity+=1.
    c.tick(s,clock)
    assert s.state in ('ABORTING','BLOCKED')
    assert any(x['type']=='ACCOUNT_ABORT' for x in s.diagnostics)
    assert c.orders[-1].reduce_only and c.orders[-1].quantity==101.
    assert not s.completed_episodes


@pytest.mark.parametrize('delta',[1.,-1.,-100.])
def test_selected_holding_quantity_must_stay_at_immutable_native_target(delta):
    c,s=controller();c.tick(s);reach(c,s);c.tick(s,START+pd.Timedelta(minutes=6))
    iid=catalog()['BTCUSDT'].id;c.positions[iid].quantity+=delta
    c.tick(s,START+pd.Timedelta(minutes=7))
    assert s.state in ('ABORTING','BLOCKED','COOLDOWN') and not s.completed_episodes
    assert any(x['type']=='ACCOUNT_ABORT' for x in s.diagnostics)
    if delta==-100.:assert s.cooldown_until==c.now+pd.Timedelta(hours=1)


def test_unowned_accepted_then_cancelled_roundtrip_events_still_latch_failure_while_flat():
    c,s=controller();clock=c.now
    c.portfolio.events.extend([
        dict(type='ORDER_ACCEPTED',timestamp=clock,instrument_id=catalog()['ADAUSDT'].id,order_id='FOREIGN_CANCELLED'),
        dict(type='ORDER_CANCELLED',timestamp=clock,instrument_id=catalog()['ADAUSDT'].id,order_id='FOREIGN_CANCELLED')])
    c.tick(s)
    assert not c.orders and s.state=='COOLDOWN' and s.cooldown_until==clock+pd.Timedelta(hours=1)
    assert any(x['type']=='ACCOUNT_ABORT' for x in s.diagnostics)


def test_own_accepted_filled_events_do_not_trigger_foreign_order_failure():
    c,s=controller();c.tick(s);reach(c,s);oid=c.orders[0].id;iid=catalog()['BTCUSDT'].id
    c.portfolio.events.extend([
        dict(type='ORDER_ACCEPTED',timestamp=c.now,instrument_id=iid,order_id=oid),
        dict(type='ORDER_FILLED',timestamp=c.now,instrument_id=iid,order_id=oid)])
    c.tick(s,START+pd.Timedelta(minutes=6))
    assert s.state=='HOLDING' and len(s.completed_entries)==1
    assert not any(x['type']=='ACCOUNT_ABORT' for x in s.diagnostics)
