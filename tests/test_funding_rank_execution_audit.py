"""Independent control/real-Engine adversaries; no historical prices or outcomes."""
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from examples.funding_rank.strategy import FundingRankPortfolio
from test_funding_rank_execution import controller,catalog,candles,feature_frame,config,START


@pytest.mark.parametrize('delay',[0,1])
def test_terminal_preserves_valid_closing_order_ids_and_original_deadline(delay):
    ctx,strategy=controller(delay=delay);strategy._catalog(ctx)
    iid=catalog()['BTCUSDT'].id;ctx.positions[iid].quantity=-1;ctx.positions[iid].average_price=100
    ctx.now=strategy.stop-pd.Timedelta(minutes=12)
    strategy._close(ctx,'preexisting_exit')
    original=strategy.transaction;orders=dict(original['orders']);deadline=original['deadline'];count=len(ctx.orders)
    ctx.tick(strategy,strategy.stop-pd.Timedelta(minutes=10))
    assert strategy.terminal_requested and strategy.transaction is original
    assert strategy.transaction['deadline']==deadline and len(ctx.orders)==count
    assert all(order.status=='accepted' and order.reduce_only for order in orders.values())
    ctx.tick(strategy,strategy.stop-pd.Timedelta(minutes=9))
    assert len(ctx.orders)==count and strategy.transaction is original


@pytest.mark.parametrize('status',['cancelled','rejected'])
def test_failed_cleanup_is_not_automatically_recreated(status):
    ctx,strategy=controller();strategy._catalog(ctx);iid=catalog()['BTCUSDT'].id
    ctx.positions[iid].quantity=1;ctx.positions[iid].average_price=100
    strategy._abort(ctx,'independent_failure');order=strategy.cleanup_orders[iid];order.status=status
    count=len(ctx.orders);ctx.tick(strategy,ctx.now+pd.Timedelta(minutes=1))
    assert len(ctx.orders)==count and strategy.cleanup_orders[iid] is order
    assert iid in strategy.blocked and strategy.cooldown_until is None
    ctx.tick(strategy,ctx.now+pd.Timedelta(hours=48))
    assert len(ctx.orders)==count and not strategy._flat(ctx)


def test_held_ranks_and_fresh_sizing_are_distinct_even_after_new_rates_arrive():
    clocks=[START+pd.Timedelta(minutes=5),START+pd.Timedelta(minutes=6),
            START+pd.Timedelta(days=7,minutes=5),START+pd.Timedelta(days=7,minutes=6),START+pd.Timedelta(days=7,minutes=7)]
    ctx,strategy=controller(clocks);ctx.tick(strategy);ctx.reach(strategy);ctx.tick(strategy,clocks[1])
    ctx.tick(strategy,clocks[2]);frozen=dict(strategy.proposal)
    ctx.reach(strategy);ctx.tick(strategy,clocks[3]);assert strategy.transaction is None
    # Updated rates would choose different assets if ranks were recomputed.
    strategy.features.loc[clocks[4],'yield_DOGEUSDT']=100
    strategy.features.loc[clocks[4],'yield_BTCUSDT']=-100
    strategy.features.loc[clocks[4],'price_PEPEUSDT']=.02
    ctx.portfolio.marks[catalog()['PEPEUSDT'].id]=.02
    ctx.portfolio.cash['binance']=96000
    ctx.tick(strategy,clocks[4])
    assert strategy.transaction['plan']['proposal']['ranks']==frozen['ranks']
    assert strategy.transaction['plan']['proposal']['yields']==frozen['yields']
    assert strategy.transaction['plan']['per_leg_budget']==6000
    assert strategy.transaction['targets'][catalog()['PEPEUSDT'].id]==300000
    assert strategy.transaction['targets'][catalog()['BTCUSDT'].id]<0
    assert strategy.cooldown_until is None


def test_offday_flat_account_cannot_open_from_daily_valid_features():
    ctx,strategy=controller();ctx.tick(strategy,START+pd.Timedelta(days=1,minutes=5))
    assert not ctx.orders and strategy.proposal is None


def test_actual_engine_funding_before_open_and_half_second_after_is_not_retroactive():
    specs=catalog();chosen=('DOGEUSDT','PEPEUSDT','BTCUSDT','ETHUSDT');rows=[]
    rates={'DOGEUSDT':.001,'PEPEUSDT':.001,'BTCUSDT':.002,'ETHUSDT':.002}
    for at in (START+pd.Timedelta(minutes=5),START+pd.Timedelta(minutes=5,milliseconds=500)):
        for label in chosen:
            rows.append(dict(timestamp=at,instrument_id=specs[label].id,funding_rate=rates[label],
                             mark_price=.01 if label=='PEPEUSDT' else 100))
    strategy=FundingRankPortfolio(feature_frame(),START+pd.Timedelta(days=30))
    result=Engine(list(specs.values()),config()).run(candles(),strategy,pd.DataFrame(rows))
    payments=result.funding
    assert payments.loc[payments.timestamp.eq(START+pd.Timedelta(minutes=5)),'funding_payment'].sum()==0
    assert payments.loc[payments.timestamp.eq(START+pd.Timedelta(minutes=5,milliseconds=500)),'funding_payment'].sum()==pytest.approx(12.5)
    assert result.equity.iloc[-1].cash==pytest.approx(100000-result.fills.fee.sum()+12.5)
    assert len(result.fills)==4 and len(strategy.completed_baskets)==1
    assert result.fills.loc[result.fills.instrument_id.eq(specs['PEPEUSDT'].id),'quantity'].iloc[0]==625000


def test_price_suffix_cannot_alter_real_engine_entries_before_suffix():
    original=feature_frame();modified=original.copy();cut=START+pd.Timedelta(minutes=12)
    modified.loc[modified.index>=cut,modified.columns.str.startswith('price_')]*=10
    first=FundingRankPortfolio(original,START+pd.Timedelta(days=30));second=FundingRankPortfolio(modified,START+pd.Timedelta(days=30))
    engine=lambda strategy:Engine(list(catalog().values()),config()).run(candles(),strategy)
    a,b=engine(first),engine(second)
    pd.testing.assert_frame_equal(a.fills.loc[a.fills.timestamp<cut].reset_index(drop=True),b.fills.loc[b.fills.timestamp<cut].reset_index(drop=True))


def test_cleanup_deadline_and_abort_latch_do_not_move_while_live_gtc_remains_pending():
    ctx,strategy=controller();strategy._catalog(ctx);iid=catalog()['BTCUSDT'].id
    ctx.positions[iid].quantity=1;ctx.positions[iid].average_price=100
    strategy._abort(ctx,'initial_failure');order=strategy.cleanup_orders[iid];deadline=strategy.cleanup_deadline
    ctx.now+=pd.Timedelta(minutes=2);strategy._abort(ctx,'repeated_risk')
    assert strategy.cleanup_deadline==deadline and strategy.cleanup_orders[iid] is order
    ctx.tick(strategy,deadline+pd.Timedelta(minutes=1));ctx.tick(strategy,deadline+pd.Timedelta(minutes=10))
    assert strategy.cleanup_deadline==deadline and len(ctx.orders)==1 and order.status=='accepted'
    assert strategy.cleanup_deadline_exceeded and strategy.state=='BLOCKED'
    assert len([d for d in strategy.diagnostics if d['type']=='ACCOUNT_ABORT'])==1
    assert len([d for d in strategy.diagnostics if d['type']=='CLEANUP_DEADLINE_EXCEEDED'])==1
    assert strategy.cooldown_until is None
    ctx.positions[iid].quantity=0;ctx.tick(strategy,deadline+pd.Timedelta(minutes=11))
    assert strategy.cooldown_until==ctx.now+pd.Timedelta(hours=24) and strategy.state=='COOLDOWN'


def test_real_fourth_fill_time_is_distinct_from_later_strategy_completion_observation():
    strategy=FundingRankPortfolio(feature_frame(),START+pd.Timedelta(days=30))
    result=Engine(list(catalog().values()),config()).run(candles(),strategy)
    completion=strategy.completed_baskets[0]
    assert completion['completed_at']==result.fills.timestamp.max()==START+pd.Timedelta(minutes=5)
    assert completion['observed_completed_at']==START+pd.Timedelta(minutes=6)


def test_sub_epsilon_native_dust_is_not_flat_and_cannot_start_cooldown():
    ctx,strategy=controller();strategy._catalog(ctx);iid=catalog()['BTCUSDT'].id
    ctx.positions[iid].quantity=1e-12;ctx.positions[iid].average_price=100
    strategy._abort(ctx,'dust')
    assert not strategy._flat(ctx) and strategy.state=='BLOCKED' and strategy.cooldown_until is None
    count=len(ctx.orders);ctx.tick(strategy,ctx.now+pd.Timedelta(days=2))
    assert len(ctx.orders)==count and strategy.cooldown_until is None
