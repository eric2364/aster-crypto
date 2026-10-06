"""Independent synthetic Engine economics and paired-order lifecycle audit."""
from dataclasses import replace
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from aster.backtest.models import SimulationConfig
from examples.cross_venue.strategy import CrossVenueCarry, SYMBOLS, VENUES
# Shared synthetic market factory only; the assertions below are independently derived.
from test_cross_venue_execution import execute, features, specs, bars, START


def all_pair_features(minutes=12):
    frame=features(minutes)
    for symbol in SYMBOLS:
        mask=frame.index.minute==5
        frame.loc[mask,f'yield_bybit_{symbol}']=.001
    return frame


def test_all_sixteen_native_positions_async_funding_and_separate_cash_conservation():
    facts=[]
    for spec in specs():
        stamp=START+pd.Timedelta(minutes=7,milliseconds=500 if spec.exchange=='bybit' else 0)
        facts.append(dict(timestamp=stamp,instrument_id=spec.id,funding_rate=.002 if spec.exchange=='bybit' else .001,
                          mark_price=.01 if spec.symbol=='1000PEPEUSDT' else 100.))
    output,strategy,engine=execute(feature=all_pair_features(),funding=pd.DataFrame(facts))
    assert len(output.fills)==16 and len(strategy.matched_entries)==8 and len(output.positions)==16
    assert len(output.funding)==16
    assert output.funding.funding_payment.sum()==pytest.approx(10.)
    for venue in VENUES:
        fills=output.fills[output.fills.exchange.eq(venue)]
        payments=output.funding[output.funding.instrument_id.str.startswith(venue+':')]
        expected=50000-fills.fee.sum()+payments.funding_payment.sum()
        assert engine.portfolio.cash[venue]==pytest.approx(expected)
        assert engine.portfolio.venue_equity(venue)==pytest.approx(expected+sum(
            p.quantity*(engine.portfolio.marks[iid]-p.average_price) for iid,p in engine.portfolio.positions.items()
            if engine.instruments[iid].exchange==venue))
        assert payments.funding_payment.sum()==pytest.approx(-10. if venue=='binance' else 20.)
    assert set(output.fills.liquidity_type)=={'taker'}
    assert set(output.fills[output.fills.symbol.eq('1000PEPEUSDT')].quantity)=={125000.}
    assert engine.config.margin_mode=='cross' and engine.config.leverage==1


def test_independent_zero_capacity_pair_failure_does_not_cancel_seven_other_pairs():
    zero={(m,'bybit','DOGEUSDT'):0. for m in range(4,10)}
    output,strategy,_=execute(minutes=16,feature=all_pair_features(16),volume=zero)
    assert len(strategy.matched_entries)==7
    assert strategy.pairs['DOGEUSDT']['state']=='IDLE'
    assert len(output.positions)==14
    doge=output.fills[output.fills.symbol.eq('DOGEUSDT')]
    assert doge.exchange.eq('binance').all() and doge.side.tolist()==[1,-1]
    for symbol in set(SYMBOLS)-{'DOGEUSDT'}:
        assert strategy.pairs[symbol]['state']=='HOLDING'
    assert sum(e['type']=='PAIR_SUBMITTED' for e in strategy.diagnostics)==8
    assert sum(e['type']=='PAIR_ABORT' for e in strategy.diagnostics)==1


def test_cleanup_keeps_gtc_order_and_cooldown_starts_after_actual_flat():
    frame=features(80);frame.loc[START+pd.Timedelta(minutes=65),'yield_bybit_DOGEUSDT']=-.001
    zero={(m,'bybit','DOGEUSDT'):0. for m in range(64,71)}
    output,strategy,_=execute(minutes=80,feature=frame,volume=zero)
    exits=output.fills[(output.fills.exchange=='bybit')&(output.fills.side==1)]
    assert exits.timestamp.tolist()==[START+pd.Timedelta(minutes=72)]
    assert output.positions.empty
    flat=next(e for e in strategy.diagnostics if e['type']=='PAIR_FLAT')
    assert flat['timestamp']==START+pd.Timedelta(minutes=73)
    assert strategy.pairs['DOGEUSDT']['cooldown']==flat['timestamp']+pd.Timedelta(hours=24)
    assert sum(e['type']=='PAIR_EXIT' for e in strategy.diagnostics)==1
    cleanup=output.events[(output.events.type=='ORDER_ACCEPTED')&(output.events.instrument_id=='bybit:perpetual:DOGEUSDT')]
    assert len(cleanup)==2  # one opening and one persistent cleanup; no repeated submissions


def test_no_reentry_until_actual_flat_cooldown_then_next_hourly_decision():
    frame=features(1570);frame.loc[START+pd.Timedelta(minutes=65),'yield_bybit_DOGEUSDT']=-.001
    zero={(m,'bybit','DOGEUSDT'):0. for m in range(64,71)}
    output,strategy,_=execute(minutes=1570,feature=frame,volume=zero)
    submissions=[e['timestamp'] for e in strategy.diagnostics if e['type']=='PAIR_SUBMITTED']
    assert submissions==[START+pd.Timedelta(minutes=5),START+pd.Timedelta(minutes=1565)]
    assert len(output.fills)==6 and len(strategy.matched_entries)==2


def test_last_seven_days_block_entry_and_terminal_position_remains_marked():
    class LateStart(CrossVenueCarry):
        def __init__(self,feature,stop):super().__init__(feature,START+pd.Timedelta(days=7,minutes=5))
    idle,_,_=execute(strategy_type=LateStart)
    assert idle.fills.empty
    output,strategy,engine=execute()
    assert len(output.positions)==2 and strategy.pairs['DOGEUSDT']['state']=='HOLDING'
    assert sum(abs(p.quantity) for p in engine.portfolio.positions.values())==25.
    assert not any(e['type']=='PAIR_EXIT' for e in strategy.diagnostics)


def test_one_venue_gross_cap_triggers_despite_positive_pooled_gain():
    price={(m,'binance','DOGEUSDT'):5000. for m in range(6,12)}
    output,strategy,engine=execute(price=price)
    assert not output.events.type.eq('LIQUIDATION').any()
    assert any(e['type']=='ACCOUNT_ABORT' and e['reason']=='venue_gross_binance' for e in strategy.diagnostics)
    assert output.positions.empty and engine.portfolio.cash['binance']>100000
    assert engine.portfolio.cash['bybit']<50000


def test_liquidation_of_both_legs_already_flat_still_latches_cooldown():
    funding=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=7),instrument_id=v+':perpetual:DOGEUSDT',
        funding_rate=50. if v=='binance' else -50.,mark_price=100.) for v in VENUES])
    output,strategy,engine=execute(funding=funding)
    assert output.events.type.eq('LIQUIDATION').sum()==2
    assert output.positions.empty
    assert strategy.global_cooldown==START+pd.Timedelta(minutes=7,hours=24)
    assert any(e['type']=='ACCOUNT_ABORT' and e['reason']=='actual_liquidation' for e in strategy.diagnostics)
    assert len(strategy.matched_entries)==1
    assert all(engine.portfolio.cash[v]<0 for v in VENUES)


@pytest.mark.parametrize('margin,leverage',[('isolated',1),('cross',2)])
def test_coordinator_rejects_wrong_margin_configuration(margin,leverage):
    config=SimulationConfig(initial_balances={'binance':50000,'bybit':50000},margin_mode=margin,leverage=leverage)
    with pytest.raises(ValueError,match='cross margin'):
        Engine(specs(),config).run(bars(),CrossVenueCarry(features(),START+pd.Timedelta(days=30)))


def test_pending_exit_dust_retains_inventory_and_blocks_actual_flat():
    # Closing125000PEPE at capacity124900 leaves100native units below a200-native close minimum.
    catalog=[replace(x,min_quantity=200) if x.exchange=='bybit' and x.symbol=='1000PEPEUSDT' else x for x in specs()]
    frame=features(75,active='PEPEUSDT');frame.loc[START+pd.Timedelta(minutes=65),'valid_bybit_PEPEUSDT']=False
    output,strategy,_=execute(minutes=75,feature=frame,catalog=catalog,
        volume={(64,'bybit','1000PEPEUSDT'):2498000.})
    assert len(output.positions)==1 and output.positions.iloc[0].quantity==-100.
    assert strategy.pairs['PEPEUSDT']['state']=='CLOSING'
    assert strategy.pairs['PEPEUSDT']['cooldown'] is None
    assert not any(e['type']=='PAIR_FLAT' for e in strategy.diagnostics)


def test_funding_between_opens_uses_actual_delayed_position_not_intended_hedge():
    funding=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=minute,milliseconds=millis),
        instrument_id='bybit:perpetual:DOGEUSDT',funding_rate=.001,mark_price=100.)
        for minute,millis in [(5,0),(6,500),(7,0),(7,500)]])
    output,strategy,engine=execute(delay=2,funding=funding)
    assert set(output.fills.timestamp)=={START+pd.Timedelta(minutes=7)}
    assert output.funding.timestamp.tolist()==[START+pd.Timedelta(minutes=7,milliseconds=500)]
    assert output.funding.funding_payment.sum()==pytest.approx(1.25)
    assert len(strategy.matched_entries)==1
    assert engine.portfolio.cash['bybit']==pytest.approx(50000-output.fills[output.fills.exchange.eq('bybit')].fee.sum()+1.25)


def test_future_feature_rows_never_create_earlier_pair_intents():
    frame=features();frame.loc[:START+pd.Timedelta(minutes=5),'yield_bybit_DOGEUSDT']=0.
    frame.loc[START+pd.Timedelta(minutes=6):,'yield_bybit_DOGEUSDT']=10000.
    output,strategy,_=execute(feature=frame)
    assert output.fills.empty and not strategy.matched_entries
    assert not any(e['type']=='PAIR_SUBMITTED' for e in strategy.diagnostics)
