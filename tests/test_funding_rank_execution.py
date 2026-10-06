"""Synthetic execution/control adversaries; no historical datasets or outcomes."""
from dataclasses import replace
from types import SimpleNamespace
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument,SimulationConfig
from aster.backtest.portfolio import Portfolio
from examples.funding_rank.strategy import FundingRankPortfolio,SYMBOLS,native_quantity

START=pd.Timestamp('2026-04-05',tz='UTC') # Sunday


def catalog():
    return {s:Instrument(f'binance:perpetual:{"1000PEPEUSDT" if s=="PEPEUSDT" else s}',
             'binance','1000PEPEUSDT' if s=='PEPEUSDT' else s,'perpetual',
             base='1000PEPE' if s=='PEPEUSDT' else s[:-4],
             lot_size=1 if s=='PEPEUSDT' else .001,min_quantity=1 if s=='PEPEUSDT' else .001,
             min_notional=1,tick_size=.000001 if s=='PEPEUSDT' else .01,taker_bps=5) for s in SYMBOLS}


def feature_frame(times=None):
    index=pd.date_range(START+pd.Timedelta(minutes=1),periods=20,freq='min') if times is None else pd.DatetimeIndex(times)
    frame=pd.DataFrame(index=index)
    rates={'DOGEUSDT':-.000001,'PEPEUSDT':0,'LINKUSDT':.000005,'ADAUSDT':.000004,
           'BTCUSDT':.000008,'ETHUSDT':.000007,'SOLUSDT':.000002,'XRPUSDT':.000003}
    for s in SYMBOLS:
        frame[f'price_{s}']=.01 if s=='PEPEUSDT' else 100
        frame[f'yield_{s}']=rates[s];frame[f'valid_{s}']=True
    return frame


def config(delay=0):
    return SimulationConfig(initial_balances={'binance':100000},margin_mode='cross',leverage=1,
                            max_gross_leverage=.5,max_position_pct=.25,slippage_bps=8,
                            participation=.05,execution_delay_bars=delay)


class Control:
    def __init__(self,specs=None,delay=0):
        self.instruments={s.id:s for s in (specs or catalog()).values()}
        self.portfolio=Portfolio(list(self.instruments.values()),config(delay));self.positions=self.portfolio.positions
        self.portfolio.marks={s.id:.01 if s.symbol=='1000PEPEUSDT' else 100 for s in self.instruments.values()}
        self.now=START+pd.Timedelta(minutes=5);self.orders=[]
    def order(self,o):
        o.id=str(len(self.orders));o.submitted_at=self.now;o.active_at=self.now+pd.Timedelta(minutes=self.portfolio.config.execution_delay_bars)
        o.status='accepted';self.orders.append(o);return o
    def cancel(self,i):
        self.orders[int(i)].status='cancelled'
    def tick(self,strategy,t=None):
        if t is not None:self.now=pd.Timestamp(t)
        strategy.on_bars(self,[{'instrument_id':i} for i in self.instruments])
    def reach(self,strategy):
        for i,q in strategy.transaction['targets'].items():
            self.positions[i].quantity=q;self.positions[i].average_price=self.portfolio.marks[i]
        for o in strategy.transaction['orders'].values():o.status='filled'


def controller(times=None,delay=0,stop=None):
    c=Control(delay=delay);s=FundingRankPortfolio(feature_frame(times),stop or START+pd.Timedelta(days=30));return c,s


def candles(volumes=None,minutes=16):
    rows=[];specs=catalog()
    for m in range(minutes):
        for label,spec in specs.items():
            price=.01 if label=='PEPEUSDT' else 100
            rows.append(dict(timestamp=START+pd.Timedelta(minutes=m),instrument_id=spec.id,
                             open=price,high=price,low=price,close=price,mark_open=price,mark_price=price,
                             volume=(volumes or {}).get((m,label),1e12),duration_seconds=60))
    return pd.DataFrame(rows)


def test_native_floor_never_overbudget_including_float_boundary():
    assert native_quantity(6250,.01,1)==625000
    assert native_quantity(6250,3,.03)*3<=6250
    assert native_quantity(1,.3,.1)*.3<=1
    with pytest.raises(ValueError):native_quantity(0,1,1)


def test_real_engine_four_native_legs_tiny_gap_no_cost_filter():
    strategy=FundingRankPortfolio(feature_frame(),START+pd.Timedelta(days=30))
    result=Engine(list(catalog().values()),config()).run(candles(),strategy)
    assert set(result.fills.symbol)=={'DOGEUSDT','1000PEPEUSDT','BTCUSDT','ETHUSDT'}
    assert len(result.fills)==4 and len(strategy.completed_baskets)==1
    assert result.fills.loc[result.fills.symbol.eq('1000PEPEUSDT'),'quantity'].iloc[0]==625000
    assert result.equity.iloc[-1].cash==pytest.approx(100000-result.fills.fee.sum())
    assert strategy.active['indicative_funding_168h']<strategy.active['indicative_roundtrip_cost']


def test_partial_leg_immutable_order_and_no_rebalance():
    c,s=controller();c.tick(s);tx=s.transaction;targets=dict(tx['targets'])
    iid=catalog()['DOGEUSDT'].id;c.positions[iid].quantity=10;c.positions[iid].average_price=100
    tx['orders'][iid].status='partial'
    c.tick(s,START+pd.Timedelta(minutes=6))
    assert s.transaction is tx and s.last_targets==targets and len(c.orders)==4
    c.reach(s);c.tick(s,START+pd.Timedelta(minutes=7))
    assert s.state=='HOLDING' and len(s.completed_baskets)==1
    c.tick(s,START+pd.Timedelta(minutes=8));assert len(c.orders)==4


@pytest.mark.parametrize('delay,minute',[(0,10),(1,11)])
def test_actual_volume_failed_leg_closes_filled_siblings_with_delay(delay,minute):
    volumes={(m,'DOGEUSDT'):0 for m in range(16)}
    strategy=FundingRankPortfolio(feature_frame(),START+pd.Timedelta(days=30))
    result=Engine(list(catalog().values()),config(delay)).run(candles(volumes),strategy)
    abort=[d for d in strategy.diagnostics if d['type']=='ACCOUNT_ABORT']
    assert abort[0]['timestamp']==START+pd.Timedelta(minutes=minute)
    assert abort[0]['reason']=='five_minute_timeout'
    assert result.positions.empty and len(result.fills)==6
    assert len(strategy.completed_baskets)==0
    assert result.equity.iloc[-1].cash==pytest.approx(100000+result.fills.realized_pnl.sum()-result.fills.fee.sum())


def test_ties_use_declared_order_and_zero_gap_stays_cash():
    c,s=controller();row=s.features.loc[c.now]
    for sym in SYMBOLS:row[f'yield_{sym}']=0
    row['yield_ADAUSDT']=.001
    p=s._select(c,row);assert p['longs']==list(SYMBOLS[:2]) and p['shorts']==['LINKUSDT','ADAUSDT']
    row['yield_ADAUSDT']=0
    assert s._select(c,row) is None


def test_sunday_all_eight_valid_required_no_replacement():
    c,s=controller();s.features.loc[c.now,'valid_LINKUSDT']=False
    c.tick(s);assert not c.orders and s.state=='IDLE'


def test_rank_mutation_while_pending_cannot_change_targets():
    c,s=controller();c.tick(s);targets=dict(s.transaction['targets'])
    s.features.loc[START+pd.Timedelta(minutes=6),'yield_DOGEUSDT']=100
    c.tick(s,START+pd.Timedelta(minutes=6))
    assert s.transaction['targets']==targets and len(c.orders)==4


def test_whole_wallet_admission_not_individual_leg_checks(monkeypatch):
    c,s=controller();s._catalog(c);s.proposal=s._select(c,s._row(c.now))
    monkeypatch.setattr(c.portfolio,'admissible',lambda *args:(True,''))
    monkeypatch.setattr(c.portfolio,'available',lambda venue:20000)
    plan,reason=s._plan(c,s._row(c.now))
    assert plan is None and reason=='joint_available_margin'


def test_one_opening_minimum_declines_entire_basket():
    specs=catalog();specs['PEPEUSDT']=replace(specs['PEPEUSDT'],min_quantity=1000000)
    c=Control(specs);s=FundingRankPortfolio(feature_frame(),START+pd.Timedelta(days=30))
    c.tick(s);assert not c.orders
    assert s.diagnostics[-1]['reason']=='opening_minimum:PEPEUSDT'


def test_unmet_terminal_order_and_overshoot_abort_all():
    for mode in ('cancelled','overshoot'):
        c,s=controller();c.tick(s);iid=catalog()['DOGEUSDT'].id
        if mode=='cancelled':s.transaction['orders'][iid].status='cancelled'
        else:c.positions[iid].quantity=s.last_targets[iid]+1;c.positions[iid].average_price=100
        c.tick(s,START+pd.Timedelta(minutes=6))
        assert any(d['type']=='ACCOUNT_ABORT' for d in s.diagnostics)
        assert not any(o.status in ('accepted','partial') and not o.reduce_only for o in c.orders)


def test_dust_blocks_cleanup_and_cooldown_begins_only_actual_flat():
    c,s=controller();s._catalog(c);iid=catalog()['DOGEUSDT'].id
    c.positions[iid].quantity=.0001;c.positions[iid].average_price=100
    s._abort(c,'synthetic_failure');assert s.state=='BLOCKED' and s.cooldown_until is None
    c.tick(s,START+pd.Timedelta(days=2));assert s.state=='BLOCKED' and not s.cooldown_until
    c.positions[iid].quantity=0;c.tick(s,START+pd.Timedelta(days=3))
    assert s.cooldown_until==c.now+pd.Timedelta(hours=24)


def test_liquidation_all_flat_still_latches_failure_cooldown():
    c,s=controller();c.portfolio.event('LIQUIDATION',c.now)
    c.tick(s);assert s.cooldown_until==c.now+pd.Timedelta(hours=24)
    assert any(d.get('reason')=='actual_liquidation' for d in s.diagnostics)
    assert not c.orders


def test_daily_review_chosen_invalid_exits_unused_invalid_does_not():
    clocks=[START+pd.Timedelta(minutes=5),START+pd.Timedelta(minutes=6),START+pd.Timedelta(days=1,minutes=5)]
    for symbol,closing in [('SOLUSDT',False),('PEPEUSDT',True)]:
        c,s=controller(clocks);c.tick(s);c.reach(s);c.tick(s,clocks[1])
        s.features.loc[clocks[2],f'valid_{symbol}']=False;c.tick(s,clocks[2])
        assert (s.state=='EXITING')==closing


def test_absent_nondecision_funding_does_not_exit_and_seven_day_age_does():
    c,s=controller();c.tick(s);c.reach(s);c.tick(s,START+pd.Timedelta(minutes=6))
    c.tick(s,START+pd.Timedelta(days=2,minutes=13));assert s.state=='HOLDING'
    c.tick(s,START+pd.Timedelta(days=7,minutes=6));assert s.state=='EXITING'
    assert s.diagnostics[-2]['reason']=='seven_day_safety'


def test_normal_weekly_roll_actual_flat_separate_callback_fresh_budget_prices():
    clocks=[START+pd.Timedelta(minutes=k) for k in (5,6)]+[START+pd.Timedelta(days=7,minutes=k) for k in (5,6,7)]
    c,s=controller(clocks);c.tick(s);c.reach(s);c.tick(s,clocks[1]);old=s.active['targets']
    c.tick(s,clocks[2]);assert s.state=='EXITING' and all(o.reduce_only for o in s.transaction['orders'].values())
    c.reach(s);c.tick(s,clocks[3]);assert s.state=='IDLE' and len(c.orders)==8
    s.features.loc[clocks[4],'price_DOGEUSDT']=200;c.portfolio.marks[catalog()['DOGEUSDT'].id]=200
    c.portfolio.cash['binance']=90000
    c.tick(s,clocks[4]);assert s.state=='ENTERING' and s.cooldown_until is None
    assert s.last_targets[catalog()['DOGEUSDT'].id]<old[catalog()['DOGEUSDT'].id]
    assert s.transaction['plan']['per_leg_budget']==5625


def test_expired_roll_proposal_never_opens_or_reselects():
    c,s=controller();s._catalog(c);s.proposal=s._select(c,s._row(c.now));s.state='IDLE'
    c.tick(s,START+pd.Timedelta(minutes=20));assert not c.orders and s.proposal is None


def test_no_final_week_entry_and_terminal_actual_inventory_exit_request():
    c,s=controller(stop=START+pd.Timedelta(days=7,minutes=5));c.tick(s);assert not c.orders
    c,s=controller(stop=START+pd.Timedelta(days=30));c.tick(s);c.reach(s);c.tick(s,START+pd.Timedelta(minutes=6))
    c.tick(s,s.stop-pd.Timedelta(minutes=10))
    assert s.terminal_requested and s.state=='EXITING'
    assert all(o.reduce_only for o in s.transaction['orders'].values())
    c.reach(s);c.tick(s,s.stop-pd.Timedelta(minutes=9));assert s._flat(c)
    count=len(c.orders);c.tick(s,s.stop);assert len(c.orders)==count


def test_equity_risk_floor_aborts_entry_intents():
    c,s=controller();c.tick(s);c.portfolio.cash['binance']=80000
    c.tick(s,START+pd.Timedelta(minutes=6))
    assert any(d.get('reason')=='equity_floor' for d in s.diagnostics)
    assert all(o.status=='cancelled' for o in c.orders)


@pytest.mark.parametrize('status',['cancelled','rejected','filled'])
def test_failed_cleanup_never_restored(status):
    c,s=controller();s._catalog(c);iid=catalog()['DOGEUSDT'].id
    c.positions[iid].quantity=1;c.positions[iid].average_price=100
    s._abort(c,'failure');old=s.cleanup_orders[iid];deadline=s.cleanup_deadline
    old.status=status;c.tick(s,START+pd.Timedelta(minutes=6))
    assert s.state=='BLOCKED' and s.cleanup_orders[iid] is old and len(c.orders)==1
    assert s.cleanup_deadline==deadline


def test_cleanup_deadline_failure_once_retains_valid_live_order():
    c,s=controller();s._catalog(c);iid=catalog()['DOGEUSDT'].id
    c.positions[iid].quantity=1;c.positions[iid].average_price=100;s._abort(c,'failure')
    old=s.cleanup_orders[iid];deadline=s.cleanup_deadline
    c.tick(s,deadline);c.tick(s,deadline+pd.Timedelta(minutes=10));s._abort(c,'repeated_risk')
    assert s.cleanup_orders[iid] is old and old.status=='accepted' and len(c.orders)==1
    assert s.cleanup_deadline==deadline and s.state=='BLOCKED'
    assert len([d for d in s.diagnostics if d['type']=='CLEANUP_DEADLINE_EXCEEDED'])==1
    assert len([d for d in s.diagnostics if d['type']=='ACCOUNT_ABORT'])==1


def test_terminal_retains_existing_exit_and_cleanup_deadlines():
    for cleanup in (False,True):
        c,s=controller(stop=START+pd.Timedelta(days=30));c.tick(s);c.reach(s);c.tick(s,START+pd.Timedelta(minutes=6))
        c.now=s.stop-pd.Timedelta(minutes=12)
        if cleanup:s._abort(c,'failure');orders=dict(s.cleanup_orders);deadline=s.cleanup_deadline
        else:s._close(c,'daily_exit');orders=dict(s.transaction['orders']);deadline=s.transaction['deadline']
        c.tick(s,s.stop-pd.Timedelta(minutes=10))
        assert s.terminal_requested and len(c.orders)==8
        assert all(o.status=='accepted' for o in orders.values())
        assert (s.cleanup_deadline if cleanup else s.transaction['deadline'])==deadline


def test_sub_epsilon_nonzero_dust_is_not_actual_flat():
    c,s=controller();s._catalog(c);iid=catalog()['DOGEUSDT'].id
    c.positions[iid].quantity=1e-12;c.positions[iid].average_price=100
    assert not s._flat(c)
    s._abort(c,'failure');assert s.state=='BLOCKED' and s.cooldown_until is None
    c.tick(s,c.now+pd.Timedelta(minutes=1));assert s.unmatched[-1]['quantities'][iid]==1e-12


def test_actual_marked_single_position_limit_triggers_cleanup():
    c,s=controller();s._catalog(c);iid=catalog()['DOGEUSDT'].id
    c.positions[iid].quantity=300;c.positions[iid].average_price=100
    c.tick(s);assert any(d.get('reason')=='position_limit' for d in s.diagnostics)
    assert c.orders and c.orders[0].reduce_only


def test_completed_at_uses_actual_final_fill_not_later_callback():
    strategy=FundingRankPortfolio(feature_frame(),START+pd.Timedelta(days=30))
    result=Engine(list(catalog().values()),config()).run(candles(),strategy)
    assert strategy.completed_baskets[0]['completed_at']==result.fills.timestamp.max()
    assert strategy.completed_baskets[0]['observed_completed_at']==result.fills.timestamp.max()+pd.Timedelta(minutes=1)
