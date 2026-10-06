"""Synthetic actual-Engine tests; no historical datasets or economic fitting."""
from dataclasses import replace
import pandas as pd
import pytest
from aster.backtest.models import Instrument, SimulationConfig
from aster.backtest.engine import Engine
from aster.reproducibility import verify_ledgers
from examples.cross_venue.strategy import CrossVenueCarry, SYMBOLS, VENUES

START=pd.Timestamp('2026-05-01',tz='UTC')


def specs():
    items=[]
    for venue in VENUES:
        for symbol in SYMBOLS:
            native='1000PEPEUSDT' if symbol=='PEPEUSDT' else symbol
            items.append(Instrument(f'{venue}:perpetual:{native}',venue,native,'perpetual',
                base='1000PEPE' if symbol=='PEPEUSDT' else symbol[:-4],
                tick_size=.000001 if symbol=='PEPEUSDT' else .01,
                lot_size=(100 if venue=='bybit' else 1) if symbol=='PEPEUSDT' else (.002 if venue=='bybit' else .001),
                min_quantity=100 if symbol=='PEPEUSDT' and venue=='bybit' else 1 if symbol=='PEPEUSDT' else .002,
                min_notional=.01,taker_bps=6 if venue=='bybit' else 5,maker_bps=6 if venue=='bybit' else 5))
    return items


def features(minutes=12,active='DOGEUSDT',gap=.001):
    index=pd.date_range(START,periods=minutes+1,freq='min')
    frame=pd.DataFrame(index=index)
    for symbol in SYMBOLS:
        for venue in VENUES:
            frame[f'price_{venue}_{symbol}']=.01 if symbol=='PEPEUSDT' else 100.
            frame[f'valid_{venue}_{symbol}']=[t.minute==5 for t in index]
            frame[f'yield_{venue}_{symbol}']=[gap if symbol==active and venue=='bybit' and t.minute==5
                                            else 0. if t.minute==5 else float('nan') for t in index]
    return frame


def bars(minutes=12,volume=None,price=None):
    rows=[]
    for minute in range(minutes):
        for spec in specs():
            px=(price or {}).get((minute,spec.exchange,spec.symbol),.01 if spec.symbol=='1000PEPEUSDT' else 100.)
            vol=(volume or {}).get((minute,spec.exchange,spec.symbol),1e9)
            rows.append(dict(timestamp=START+pd.Timedelta(minutes=minute),instrument_id=spec.id,
                open=px,high=px,low=px,close=px,mark_open=px,mark_price=px,volume=vol,duration_seconds=60))
    return pd.DataFrame(rows)


def execute(minutes=12,feature=None,volume=None,price=None,delay=0,funding=None,catalog=None,strategy_type=CrossVenueCarry):
    strategy=strategy_type(features(minutes) if feature is None else feature,START+pd.Timedelta(days=30))
    config=SimulationConfig(initial_balances={'binance':50000.,'bybit':50000.},margin_mode='cross',leverage=1,
        max_gross_leverage=.5,max_position_pct=.25,slippage_bps=8,participation=.05,
        execution_delay_bars=delay,fill_model='volume_aware')
    engine=Engine(specs() if catalog is None else catalog,config)
    result=engine.run(bars(minutes,volume,price),strategy,funding=funding)
    verify_ledgers(result)
    return result,strategy,engine


@pytest.mark.parametrize('delay,minute',[(0,5),(1,6)])
def test_matched_native_entry_retains_delay_and_offhour_nan_is_not_an_exit(delay,minute):
    result,strategy,_=execute(delay=delay)
    assert len(result.fills)==2
    assert set(result.fills.timestamp)=={START+pd.Timedelta(minutes=minute)}
    assert set(result.fills.quantity)=={12.5}
    assert dict(zip(result.fills.exchange,result.fills.side))=={'binance':1,'bybit':-1}
    assert strategy.pairs['DOGEUSDT']['state']=='HOLDING'
    assert len(strategy.matched_entries)==1
    assert strategy.pairs['DOGEUSDT']['basket']['entry_cost']==pytest.approx(13.5)
    assert not any(event['type']=='PAIR_ABORT' for event in strategy.diagnostics)


def test_stress_cost_gate_rejects_small_positive_yield_without_invented_arbitrage():
    result,strategy,_=execute(feature=features(gap=.00001))
    assert result.fills.empty
    assert any(e.get('reason')=='stress_cost_filter' for e in strategy.diagnostics)
    assert result.equity.iloc[-1].equity==100000


def test_actual_sameclock_settlement_is_not_paid_to_later_entry():
    funding=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=m),instrument_id='bybit:perpetual:DOGEUSDT',
                              funding_rate=.001,mark_price=100.) for m in (5,7)])
    result,_,engine=execute(funding=funding)
    assert len(result.funding)==1 and result.funding.iloc[0].timestamp==START+pd.Timedelta(minutes=7)
    assert result.funding.iloc[0].funding_payment==pytest.approx(1.25)
    assert engine.portfolio.cash['bybit']==pytest.approx(50000-result.fills.loc[result.fills.exchange.eq('bybit'),'fee'].sum()+1.25)
    assert engine.portfolio.cash['binance']==pytest.approx(50000-result.fills.loc[result.fills.exchange.eq('binance'),'fee'].sum())


def test_pepe_both_venues_stay_native_bundle_quantities_and_funding_cash():
    funding=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=7),instrument_id='bybit:perpetual:1000PEPEUSDT',
                              funding_rate=.001,mark_price=.01)])
    result,strategy,_=execute(feature=features(active='PEPEUSDT'),funding=funding)
    assert set(result.fills.symbol)=={'1000PEPEUSDT'}
    assert set(result.fills.quantity)=={125000.}
    assert result.funding.funding_payment.sum()==pytest.approx(1.25)
    assert strategy.pairs['PEPEUSDT']['basket']['quantity']==125000


@pytest.mark.parametrize('delay,timeout',[(0,10),(1,11)])
def test_five_attempt_partial_leg_timeout_cancels_then_persistently_cleans(delay,timeout):
    # Each eligible Bybit opening attempt supplies2native units; fifth is incomplete.
    first=4+delay
    volume={(m,'bybit','DOGEUSDT'):40. for m in range(first,first+5)}
    result,strategy,_=execute(minutes=16,feature=features(16),volume=volume,delay=delay)
    failures=[e for e in strategy.diagnostics if e['type']=='PAIR_ABORT']
    assert len(failures)==1 and failures[0]['reason']=='five_minute_timeout'
    assert failures[0]['timestamp']==START+pd.Timedelta(minutes=timeout)
    assert result.positions.empty
    assert strategy.pairs['DOGEUSDT']['state']=='IDLE'
    assert strategy.unmatched
    assert len(result.fills[(result.fills.exchange=='bybit')&(result.fills.side==-1)])==5
    assert strategy.pairs['DOGEUSDT']['cooldown']>=START+pd.Timedelta(minutes=timeout,hours=24)


def test_one_leg_cancelled_after_submission_closes_only_actual_inventory():
    class CancelLeg(CrossVenueCarry):
        def on_bars(self,ctx,slice):
            super().on_bars(ctx,slice)
            if ctx.now==START+pd.Timedelta(minutes=5):
                ctx.cancel(self.pairs['DOGEUSDT']['orders']['bybit:perpetual:DOGEUSDT'].id)
    result,strategy,_=execute(strategy_type=CancelLeg)
    assert set(result.fills.exchange)=={'binance'}
    assert list(result.fills.side)==[1,-1]
    assert result.positions.empty
    assert any(e.get('reason')=='unmet_terminal_order' for e in strategy.diagnostics)


def test_normal_reversal_uses_actual_reduce_only_exit_without_sameclock_reopen():
    feature=features(75); feature.loc[START+pd.Timedelta(minutes=65),'yield_bybit_DOGEUSDT']=-.001
    result,strategy,_=execute(minutes=75,feature=feature)
    assert len(result.fills)==4 and result.positions.empty
    assert set(result.fills.iloc[2:].timestamp)=={START+pd.Timedelta(minutes=65)}
    assert len(strategy.matched_entries)==1
    assert strategy.pairs['DOGEUSDT']['cooldown']==START+pd.Timedelta(minutes=66,hours=24)
    assert any(e.get('reason')=='differential_reversal' for e in strategy.diagnostics)


def test_closing_subminimum_dust_is_marked_and_does_not_magic_flatten():
    feature=features(75);feature.loc[START+pd.Timedelta(minutes=65),'valid_bybit_DOGEUSDT']=False
    catalog=[replace(s,min_quantity=.01) if s.exchange=='bybit' and s.symbol=='DOGEUSDT' else s for s in specs()]
    result,strategy,_=execute(minutes=75,feature=feature,catalog=catalog,
        volume={(64,'bybit','DOGEUSDT'):249.96})
    assert len(result.positions)==1
    assert result.positions.iloc[0].quantity==pytest.approx(-.002)
    assert any(e['type']=='BLOCKED_DUST' for e in strategy.diagnostics)
    assert strategy.pairs['DOGEUSDT']['state']=='CLOSING'


def test_one_venue_liquidates_despite_other_venue_offsetting_profit():
    price={(m,v,'DOGEUSDT'):5000. for m in range(6,12) for v in VENUES}
    result,strategy,engine=execute(price=price)
    liquidations=result.events[result.events.type.eq('LIQUIDATION')]
    assert len(liquidations)==1 and liquidations.iloc[0].exchange=='bybit'
    assert engine.portfolio.cash['bybit']<0 and engine.portfolio.cash['binance']>50000
    assert result.positions.empty
    assert any(e.get('reason')=='actual_liquidation' for e in strategy.diagnostics)


def test_future_feature_suffix_cannot_change_earlier_fills():
    original=features();changed=original.copy()
    changed.loc[changed.index>=START+pd.Timedelta(minutes=8),'price_bybit_DOGEUSDT']=1e10
    a,_,_=execute(feature=original);b,_,_=execute(feature=changed)
    assert a.fills.to_dict('records')==b.fills.to_dict('records')


def test_later_market_price_margin_rejection_cannot_borrow_other_wallet_cash():
    # Admission knows only completed100; Bybit's next executable open gaps to10000.
    result,strategy,_=execute(price={(5,'bybit','DOGEUSDT'):10000.})
    assert set(result.fills.exchange)=={'binance'}
    assert list(result.fills.side)==[1,-1]
    assert result.positions.empty
    assert any(e.get('reason')=='unmet_terminal_order' for e in strategy.diagnostics)
    assert any(str(r).startswith('risk_') for r in result.events.loc[result.events.type.eq('ORDER_CANCELLED'),'reason'])


def test_venue_equity_risk_exit_happens_before_liquidation_with_no_free_transfer():
    price={(m,v,'DOGEUSDT'):2000. for m in range(6,12) for v in VENUES}
    result,strategy,engine=execute(price=price)
    assert not result.events.type.eq('LIQUIDATION').any()
    assert result.positions.empty
    assert engine.portfolio.cash['bybit']<40000 and engine.portfolio.cash['binance']>60000
    assert any(e['type']=='ACCOUNT_ABORT' and e['reason']=='venue_equity_bybit' for e in strategy.diagnostics)
    assert strategy.global_cooldown==START+pd.Timedelta(minutes=8,hours=24)


def test_maximum_holding_uses_submission_clock_even_off_hour_with_nan_yield():
    result,strategy,engine=execute(delay=1)
    submitted=strategy.pairs['DOGEUSDT']['basket']['submitted_at']
    # Advance the synthetic callback clock only: no historic bars or invented fills.
    engine.now=submitted+pd.Timedelta(hours=168,minutes=1)
    slice=bars(1).to_dict('records')
    strategy.on_bars(engine.context,slice)
    assert strategy.pairs['DOGEUSDT']['state']=='CLOSING'
    assert any(e.get('reason')=='maximum_hold' for e in strategy.diagnostics)
    assert all(order.reduce_only for order in strategy.pairs['DOGEUSDT']['cleanup'].values())
    assert not result.positions.empty  # An exit request is not a fabricated executed exit.


def test_both_core_liquidated_flat_legs_still_reset_baskets_and_global_cooldown():
    # Adversarial synthetic charges deplete both independent wallets at one clock.
    funding=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=7),
        instrument_id=f'{venue}:perpetual:DOGEUSDT',funding_rate=100 if venue=='binance' else -100,
        mark_price=100.) for venue in VENUES])
    result,strategy,_=execute(funding=funding)
    assert result.events.type.eq('LIQUIDATION').sum()==2
    assert result.positions.empty
    assert strategy.pairs['DOGEUSDT']['state']=='IDLE'
    assert 'basket' not in strategy.pairs['DOGEUSDT']
    assert strategy.global_cooldown==START+pd.Timedelta(minutes=7,hours=24)
    assert any(e['type']=='ACCOUNT_ABORT' and e['reason']=='actual_liquidation' for e in strategy.diagnostics)
    assert len(strategy.matched_entries)==1


def test_reverse_orientation_and_asynchronous_funding_keep_each_wallet_credit():
    funding=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=7,milliseconds=ms),
        instrument_id=f'{venue}:perpetual:DOGEUSDT',funding_rate=rate,mark_price=100.)
        for venue,ms,rate in [('binance',1,.001),('bybit',3,-.001)]])
    result,_,engine=execute(feature=features(gap=-.001),funding=funding)
    assert dict(zip(result.fills.exchange,result.fills.side))=={'binance':-1,'bybit':1}
    assert len(result.funding)==2
    assert list(result.funding.funding_payment)==pytest.approx([1.25,1.25])
    for venue in VENUES:
        fees=result.fills.loc[result.fills.exchange.eq(venue),'fee'].sum()
        assert engine.portfolio.cash[venue]==pytest.approx(50000-fees+1.25)
    assert {START+pd.Timedelta(minutes=7,milliseconds=ms) for ms in (1,3)}<=set(result.equity.timestamp)


def test_positive_but_decayed_carry_exits_at_fixed_entry_cost_hurdle():
    feature=features(75);feature.loc[START+pd.Timedelta(minutes=65),'yield_bybit_DOGEUSDT']=.00002
    result,strategy,_=execute(minutes=75,feature=feature)
    assert result.positions.empty and len(result.fills)==4
    assert any(e.get('reason')=='carry_decay' for e in strategy.diagnostics)


def test_later_prices_do_not_rebalance_native_quantity_or_entry_cost():
    feature=features(75)
    for venue in VENUES:feature.loc[feature.index>=START+pd.Timedelta(minutes=60),f'price_{venue}_DOGEUSDT']=150.
    prices={(m,v,'DOGEUSDT'):150. for m in range(60,75) for v in VENUES}
    result,strategy,_=execute(minutes=75,feature=feature,price=prices)
    assert len(result.fills)==2
    assert set(abs(result.positions.quantity))=={12.5}
    basket=strategy.pairs['DOGEUSDT']['basket']
    assert basket['quantity']==12.5 and basket['entry_cost']==pytest.approx(13.5)
