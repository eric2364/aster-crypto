"""Independent hand-value and synthetic actual-Engine basket execution cases."""
from types import SimpleNamespace
import pandas as pd
import pytest
from dataclasses import replace
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from examples.residual_convergence.strategy import ALTS, SYMBOLS, ResidualPortfolio, entry_plan

START=pd.Timestamp('2026-05-01',tz='UTC')


def catalog():
    specs={}
    for symbol in SYMBOLS:
        native='1000PEPEUSDT' if symbol=='PEPEUSDT' else symbol
        specs[symbol]=Instrument(f'binance:perpetual:{native}','binance',native,'perpetual',
            base='1000PEPE' if symbol=='PEPEUSDT' else symbol[:-4],tick_size=.000001 if symbol=='PEPEUSDT' else .01,
            lot_size=1 if symbol=='PEPEUSDT' else .001,min_quantity=1 if symbol=='PEPEUSDT' else .001,
            min_notional=.001,maker_bps=5,taker_bps=5,liquidation_bps=50)
    return specs


def models(eligible=('DOGEUSDT',), beta=1., eth=0., sigma=.1, alpha=0.):
    return {'assets':{s:dict(eligible=s in eligible,beta_btc=beta,beta_eth=eth,
                            alpha=alpha,phi=.9,mu=0.,sigma=sigma) for s in ALTS}}


def features(minutes=12, z=None):
    frame=pd.DataFrame(index=pd.date_range(START+pd.Timedelta(minutes=1),periods=minutes,freq='min'))
    for s in SYMBOLS: frame[f'price_{s}']=100. if s in SYMBOLS[:2] else .01 if s=='PEPEUSDT' else 10.
    for s in ALTS: frame[f'z_{s}']=3. if s=='DOGEUSDT' else 0.
    if z:
        for (minute,symbol),value in z.items(): frame.loc[START+pd.Timedelta(minutes=minute),f'z_{symbol}']=value
    return frame


def candles(minutes=12, volumes=None, prices=None):
    specs=catalog();rows=[]
    for m in range(minutes):
        for symbol in SYMBOLS:
            price=(prices or {}).get((m,symbol),100. if symbol in SYMBOLS[:2] else .01 if symbol=='PEPEUSDT' else 10.)
            volume=(volumes or {}).get((m,symbol),1e8)
            rows.append(dict(timestamp=START+pd.Timedelta(minutes=m),instrument_id=specs[symbol].id,
                             open=price,high=price,low=price,close=price,mark_open=price,mark_price=price,
                             volume=volume,duration_seconds=60))
    return pd.DataFrame(rows)


def execute(frame=None, features_frame=None, model=None, delay=0, stop=None, funding=None, specs=None):
    specs=catalog() if specs is None else specs;model=models() if model is None else model
    strategy=ResidualPortfolio(model,features() if features_frame is None else features_frame,
                               START+pd.Timedelta(days=10) if stop is None else stop)
    config=SimulationConfig(initial_balances={'binance':100000},leverage=1,margin_mode='isolated',
        max_gross_leverage=1,max_position_pct=.5,slippage_bps=8,participation=.05,execution_delay_bars=delay)
    result=Engine(list(specs.values()),config).run(candles() if frame is None else frame,strategy,funding=funding)
    return result,strategy


def test_native_pepe_entry_plan_and_unnetted_stress_cost():
    specs=catalog();prices={s:100. if s in SYMBOLS[:2] else .01 if s=='PEPEUSDT' else 10. for s in SYMBOLS}
    plan,reason=entry_plan('PEPEUSDT',models(('PEPEUSDT',))['assets']['PEPEUSDT'],prices,1,specs,-3.)
    assert reason==''
    assert plan['quantities'][specs['PEPEUSDT'].id]==208333
    assert plan['quantities'][specs['BTCUSDT'].id]==pytest.approx(-20.833)
    assert plan['stress_roundtrip_cost']==pytest.approx(.0052*(2083.33+2083.3)/2083.33)
    assert plan['expected_recovery']==pytest.approx(.25*(1-.9**48))


@pytest.mark.parametrize('sigma,alpha,reason',[(.001,0,'stress_cost_filter'),(.1,.1,'stress_cost_filter')])
def test_no_funding_or_alpha_credit_rescues_stress_cost_filter(sigma,alpha,reason):
    specs=catalog();prices={s:100. for s in SYMBOLS}
    plan,error=entry_plan('DOGEUSDT',models(sigma=sigma,alpha=alpha)['assets']['DOGEUSDT'],prices,-1,specs,3)
    assert plan is None and error==reason


def test_required_rounded_hedge_below_opening_minimum_blocks_entry():
    specs=catalog();prices={s:100. for s in SYMBOLS};prices['BTCUSDT']=1e12
    plan,error=entry_plan('DOGEUSDT',models()['assets']['DOGEUSDT'],prices,-1,specs,3)
    assert plan is None and error=='opening_minimum:BTCUSDT'


def test_simultaneous_opposite_alts_net_shared_factor_without_fake_accounts():
    f=features();f['z_PEPEUSDT']=-3
    result,strategy=execute(features_frame=f,model=models(('DOGEUSDT','PEPEUSDT')))
    assert set(result.fills.symbol)=={'DOGEUSDT','1000PEPEUSDT'}
    assert result.fills[result.fills.symbol.eq('1000PEPEUSDT')].quantity.sum()==208333
    assert set(strategy.active)=={'DOGEUSDT','PEPEUSDT'}
    assert strategy.state=='HOLDING'
    assert result.equity.iloc[-1].cash==pytest.approx(100000-result.fills.fee.sum())


def test_actual_entry_does_not_read_same_open_future_volume():
    base=candles();mutated=base.copy()
    # Activation at minute1 consumes minute0's published volume.
    mutated.loc[mutated.timestamp.eq(START+pd.Timedelta(minutes=1)),'volume']=0
    a,_=execute(base);b,_=execute(mutated)
    assert a.fills.head(2)[['symbol','quantity','price']].to_dict('records')==b.fills.head(2)[['symbol','quantity','price']].to_dict('records')
    assert all(a.fills.timestamp.eq(START+pd.Timedelta(minutes=1)))


@pytest.mark.parametrize('delay,abort_minute,flat_minute',[(0,6,7),(1,7,9)])
def test_five_eligible_attempts_then_real_flatten_with_delay(delay,abort_minute,flat_minute):
    volumes={(m,'DOGEUSDT'):0 for m in range(12)}
    result,strategy=execute(candles(volumes=volumes),delay=delay)
    abort=[d for d in strategy.diagnostics if d['kind']=='ABORT']
    assert len(abort)==1 and abort[0]['reason']=='five_attempt_timeout'
    assert abort[0]['timestamp']==START+pd.Timedelta(minutes=abort_minute)
    assert [d['timestamp'] for d in strategy.diagnostics if d['kind']=='ABORT_FLAT']==[START+pd.Timedelta(minutes=flat_minute)]
    assert list(result.fills.symbol)==['BTCUSDT','BTCUSDT']
    assert list(result.fills.side)==[1,-1]
    assert result.positions.empty
    assert strategy.global_cooldown_until==START+pd.Timedelta(minutes=flat_minute,hours=24)
    assert result.equity.iloc[-1].cash==pytest.approx(100000+result.fills.realized_pnl.sum()-result.fills.fee.sum())
    # One immutable BTC order plus one cleanup order, not one replacement per minute.
    btc_submitted=result.events[result.events.type.eq('ORDER_SUBMITTED') & result.events.symbol.eq('BTCUSDT')]
    assert len(btc_submitted)==2


def test_gap_risk_rejection_aborts_other_filled_leg_before_timeout():
    # BTC opening gap fails actual margin admission after successful completed-price preflight.
    prices={(m,'BTCUSDT'):1e6 for m in range(1,12)}
    result,strategy=execute(candles(prices=prices))
    abort=[d for d in strategy.diagnostics if d['kind']=='ABORT']
    assert abort[0]['timestamp']==START+pd.Timedelta(minutes=2)
    assert abort[0]['reason']=='unmet_cancelled_target'
    assert list(result.fills.symbol)==['DOGEUSDT','DOGEUSDT']
    assert result.positions.empty
    assert result.trades.net_pnl.sum()<0


def test_partial_gtc_orders_retained_then_complete_without_target_shrinkage():
    # DOGE target208.333; prior volume permits50units each eligible open.
    volumes={(m,'DOGEUSDT'):1000 for m in range(12)}
    result,strategy=execute(candles(volumes=volumes))
    doge=result.fills[result.fills.symbol.eq('DOGEUSDT')]
    assert list(doge.quantity)==pytest.approx([50,50,50,50,8.333])
    assert len(doge.order_id.unique())==1
    assert not any(d['kind']=='ABORT' for d in strategy.diagnostics)
    assert strategy.state=='HOLDING'
    assert abs(result.positions[result.positions.symbol.eq('DOGEUSDT')].quantity.iloc[0])==pytest.approx(208.333)


def test_stop_precedes_equilibrium_and_local_cooldown_begins_after_exit():
    f=features(z={(4,'DOGEUSDT'):-4,(5,'DOGEUSDT'):-3,(6,'DOGEUSDT'):-3})
    result,strategy=execute(features_frame=f)
    exit_event=next(d for d in strategy.diagnostics if d['kind']=='EXIT_INTENT')
    assert exit_event['reasons']=={'DOGEUSDT':'stop'}
    assert strategy.local_cooldown_until['DOGEUSDT']==START+pd.Timedelta(minutes=5,hours=24)
    assert result.positions.empty
    assert len(result.fills)==4


def test_final_48_hours_and_ineligible_models_remain_cash():
    for stop,model in [(START+pd.Timedelta(hours=48,minutes=1),models()),(START+pd.Timedelta(days=10),models(()))]:
        result,strategy=execute(stop=stop,model=model)
        assert result.fills.empty and result.equity.iloc[-1].equity==100000


def test_funding_charges_actual_native_quantity_during_failed_leg_cleanup():
    volumes={(m,'DOGEUSDT'):0 for m in range(12)}
    iid=catalog()['BTCUSDT'].id
    funding=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=6),instrument_id=iid,
                               funding_rate=.01,mark_price=100.)])
    result,strategy=execute(candles(volumes=volumes),funding=funding)
    assert result.funding.iloc[0].funding_payment==pytest.approx(-20.833)
    assert result.equity.iloc[-1].cash==pytest.approx(100000+result.fills.realized_pnl.sum()-result.fills.fee.sum()-20.833)
    assert result.positions.empty


def test_slow_cleanup_cannot_consume_the_flat_plus_24hour_cooldown():
    minutes=1448
    volumes={(m,'DOGEUSDT'):0 for m in range(minutes)}
    volumes.update({(m,'BTCUSDT'):0 for m in range(5,25)})
    result,strategy=execute(candles(minutes,volumes),features_frame=features(minutes))
    flat=next(d for d in strategy.diagnostics if d['kind']=='ABORT_FLAT')
    assert flat['timestamp']==START+pd.Timedelta(minutes=27)
    assert strategy.global_cooldown_until==START+pd.Timedelta(minutes=27,hours=24)
    assert len(result.fills)==2
    assert result.positions.empty
    assert len(result.events[result.events.type.eq('ORDER_SUBMITTED') & result.events.symbol.eq('BTCUSDT')])==2


def test_causal_strategy_prefix_does_not_observe_future_feature_changes():
    f=features();future=f.copy();future.loc[future.index>=START+pd.Timedelta(minutes=6),'z_DOGEUSDT']=100
    # Execute only first five complete minutes; appended future features cannot alter these fills.
    a,_=execute(candles(5),features_frame=f);b,_=execute(candles(5),features_frame=future)
    pd.testing.assert_frame_equal(a.fills,b.fills)
    pd.testing.assert_frame_equal(a.equity,b.equity)


def test_small_shared_hedge_partial_reduction_uses_reduce_only_not_opening_minimum():
    specs=catalog();specs['BTCUSDT']=replace(specs['BTCUSDT'],min_notional=100)
    m=models(('DOGEUSDT','SOLUSDT','ADAUSDT'));m['assets']['SOLUSDT']['beta_btc']=1.01
    f=features();f['z_DOGEUSDT']=-3
    f.loc[f.index>=START+pd.Timedelta(minutes=4),'z_SOLUSDT']=3
    f.loc[f.index>=START+pd.Timedelta(minutes=4),'z_ADAUSDT']=-3
    result,strategy=execute(features_frame=f,model=m,specs=specs)
    btc=result.fills[result.fills.symbol.eq('BTCUSDT')]
    assert len(btc)==2
    assert list(btc.side)==[-1,1]
    assert btc.iloc[1].quantity==pytest.approx(.103)
    assert btc.iloc[1].quantity*btc.iloc[1].price<100
    second=result.events[result.events.type.eq('ORDER_SUBMITTED') & result.events.order_id.eq(btc.iloc[1].order_id)].iloc[0]
    assert bool(second.reduce_only)
    assert strategy.state=='HOLDING' and len(strategy.active)==3
    assert not any(d['kind']=='ABORT' for d in strategy.diagnostics)


def test_cleanup_subminimum_dust_stays_marked_and_blocks_all_reentry():
    specs=catalog();specs['DOGEUSDT']=replace(specs['DOGEUSDT'],min_quantity=.01)
    volumes={(m,'BTCUSDT'):0 for m in range(12)}
    # Entry short208.333; cleanup can close208.332, leaving real.001 native units.
    volumes[(5,'DOGEUSDT')]=208.332/.05
    result,strategy=execute(candles(volumes=volumes),specs=specs)
    assert len(result.positions)==1
    position=result.positions.iloc[0]
    assert position.symbol=='DOGEUSDT'
    assert position.quantity==pytest.approx(-.001)
    assert strategy.state=='ABORT'
    assert specs['DOGEUSDT'].id in strategy.blocked
    assert any(d['kind']=='BLOCKED_RESIDUAL' for d in strategy.diagnostics)
    assert len(result.fills)==2
    assert result.equity.iloc[-1].equity==pytest.approx(100000+result.trades.net_pnl.sum()+position.unrealized_pnl-position.entry_fees)


def test_actual_isolated_liquidation_aborts_surviving_hedge_on_next_observable_minute():
    prices={(m,'DOGEUSDT'):25 for m in range(2,12)}
    result,strategy=execute(candles(prices=prices))
    forced=result.fills[result.fills.exit_reason.eq('liquidation')]
    assert len(forced)==1 and forced.iloc[0].symbol=='DOGEUSDT'
    abort=next(d for d in strategy.diagnostics if d['kind']=='ABORT')
    assert abort['timestamp']==START+pd.Timedelta(minutes=3)
    assert abort['reason']=='actual_liquidation'
    btc=result.fills[result.fills.symbol.eq('BTCUSDT')]
    assert len(btc)==2 and btc.iloc[-1].timestamp==START+pd.Timedelta(minutes=3)
    assert result.positions.empty
    assert result.equity.iloc[-1].liquidation_fees>0


def test_invalid_availability_index_rejected():
    f=features();f.index=f.index.tz_localize(None)
    with pytest.raises(ValueError,match='availability'):
        ResidualPortfolio(models(),f,START+pd.Timedelta(days=10))


def test_native_overshoot_aborts_instead_of_shrinking_or_reversing_target():
    class SyntheticInterference(ResidualPortfolio):
        def on_bars(self,context,bars):
            if context.now==START+pd.Timedelta(minutes=2):
                # A public synthetic account fill models an unexpected extra unit;
                # it must remain a real fee-paying ledger entry during cleanup.
                iid=catalog()['DOGEUSDT'].id
                assert context.portfolio.apply_fill(iid,-1,1,10,context.now,'taker','market')[0]
            super().on_bars(context,bars)
    strategy=SyntheticInterference(models(),features(),START+pd.Timedelta(days=10))
    config=SimulationConfig(initial_balances={'binance':100000},leverage=1,max_gross_leverage=1,
                            max_position_pct=.5,slippage_bps=8,participation=.05)
    result=Engine(list(catalog().values()),config).run(candles(),strategy)
    assert any(d['kind']=='ABORT' and d['reason']=='quantity_overshoot' for d in strategy.diagnostics)
    assert result.positions.empty
    closing=result.fills[result.fills.symbol.eq('DOGEUSDT') & result.fills.side.eq(1)]
    assert closing.quantity.sum()==pytest.approx(209.333)
