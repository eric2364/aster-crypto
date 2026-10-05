"""Independent causal factor tests with synthetic observations only."""
import numpy as np
import pandas as pd
import pytest
from examples.external_factors import signals as s

IID='binance:perpetual:1000PEPEUSDT'
START=pd.Timestamp('2026-01-01',tz='UTC')


def bars(n=600):
    return pd.DataFrame({'timestamp':pd.date_range(START,periods=n,freq='min'),
                         'close':1.01,'duration_seconds':60,'instrument_id':IID})


def inputs(family):
    if family=='qqq_risk_transmission':
        dates=pd.date_range(START-pd.Timedelta(days=40),START+pd.Timedelta(days=1),freq='B')
        return {'qqq':pd.DataFrame({'session_date':dates.strftime('%Y-%m-%d'),
                                   'available_at':dates+pd.Timedelta(days=1),
                                   'close':100*np.exp(np.arange(len(dates))*.004)})}
    if family=='cpi_acceleration_event':
        release=pd.DatetimeIndex([START-pd.Timedelta(days=30),START+pd.Timedelta(hours=2)])
        return {'cpi':pd.DataFrame({'release_time':release,'available_at':release+pd.Timedelta(minutes=1),
                                   'reference_month':['2025-11','2025-12'],
                                   'headline_yoy':[2.,2.2],'core_yoy':[2.,2.2]})}
    if family=='funding_crowding_fade':
        return {'funding':pd.DataFrame({'timestamp':pd.DatetimeIndex([START-pd.Timedelta(hours=16),START-pd.Timedelta(hours=8),START]),
                                       'funding_rate':.001,'instrument_id':IID})}
    if family=='perpetual_premium_fade':
        spot=bars();spot['instrument_id']='binance:spot:PEPEUSDT';spot['close']=.001
        return {'spot_bars':spot,'spot_units_per_perpetual_unit':1000.}
    b=bars()
    return {'flow':pd.DataFrame({'timestamp':b.timestamp,'available_at':b.timestamp+pd.Timedelta(minutes=2),
                                'instrument_id':IID,'total_volume':100.,'taker_buy_volume':75.})}


@pytest.mark.parametrize('family',list(s.FAMILIES))
def test_prefix_and_future_perturbation(family):
    b=bars();kw=inputs(family);cut=b.timestamp.iloc[300]
    full=s.build_signals(b,family,**kw)
    prefix=s.build_signals(b.iloc[:300],family,**kw)
    pd.testing.assert_series_equal(full.iloc[:300],prefix)
    changed={k:v.copy() if isinstance(v,pd.DataFrame) else v for k,v in kw.items()}
    table=next(v for v in changed.values() if isinstance(v,pd.DataFrame))
    clock=table['available_at'] if 'available_at' in table else table.timestamp+pd.Timedelta(minutes=1)
    for column in ['close','funding_rate','headline_yoy','core_yoy','taker_buy_volume']:
        if column in table:
            table.loc[clock>cut,column] = 0. if column=='taker_buy_volume' else 10000.
    out=s.build_signals(b,family,**changed)
    pd.testing.assert_series_equal(full.iloc[:300],out.iloc[:300])
    assert set(full.unique()) <= {-1,0,1}


def test_delayed_funding_receipt_never_trades_before_available_processing():
    kw=inputs('funding_crowding_fade')
    f=kw['funding']
    f['available_at']=f.timestamp
    f.loc[2,'available_at']=START+pd.Timedelta(hours=2)
    out=s.build_signals(bars(),'funding_crowding_fade',**kw)
    assert out.loc[:START+pd.Timedelta(hours=2)].eq(0).all()
    assert out.loc[START+pd.Timedelta(hours=2,minutes=1)] == -1


def test_cpi_exact_publication_minute_and_nonfinite_reject():
    kw=inputs('cpi_acceleration_event')
    out=s.build_signals(bars(),'cpi_acceleration_event',**kw)
    assert out.loc[:START+pd.Timedelta(hours=2)].eq(0).all()
    assert out.loc[START+pd.Timedelta(hours=2,minutes=1)] == -1
    kw['cpi'].loc[1,'headline_yoy']=float('inf')
    with pytest.raises(ValueError):
        s.build_signals(bars(),'cpi_acceleration_event',**kw)


def test_pepe_unit_mapping_and_flow_bounds_identity():
    kw=inputs('perpetual_premium_fade')
    out=s.build_signals(bars(),'perpetual_premium_fade',**kw)
    assert out.iloc[60] == -1
    kw['spot_units_per_perpetual_unit']=1.
    with pytest.raises(ValueError):s.build_signals(bars(),'perpetual_premium_fade',**kw)
    kw=inputs('taker_flow_drift');kw['flow'].loc[0,'taker_buy_volume']=101.
    with pytest.raises(ValueError):s.build_signals(bars(),'taker_flow_drift',**kw)
    kw=inputs('taker_flow_drift');kw['flow']['instrument_id']='binance:perpetual:BTCUSDT'
    with pytest.raises(ValueError):s.build_signals(bars(),'taker_flow_drift',**kw)


@pytest.mark.parametrize('family',['perpetual_premium_fade','taker_flow_drift'])
def test_minute_gap_resets_rolling_warmup(family):
    b=bars();kw=inputs(family)
    key='spot_bars' if family=='perpetual_premium_fade' else 'flow'
    kw[key]=kw[key].drop(index=120)
    out=s.build_signals(b,family,**kw)
    assert out.iloc[121:181].eq(0).all()


def test_qqq_declared_next_midnight_availability_required():
    kw=inputs('qqq_risk_transmission');kw['qqq']['available_at']-=pd.Timedelta(hours=1)
    with pytest.raises(ValueError):s.build_signals(bars(),'qqq_risk_transmission',**kw)


def test_delayed_oldest_funding_rate_does_not_leak_through_rolling_mean():
    kw=inputs('funding_crowding_fade');f=kw['funding']
    f['available_at']=f.timestamp
    f.loc[0,'available_at']=START+pd.Timedelta(hours=2)
    out=s.build_signals(bars(),'funding_crowding_fade',**kw)
    assert out.loc[:START+pd.Timedelta(hours=2)].eq(0).all()
    assert out.loc[START+pd.Timedelta(hours=2,minutes=1)] == -1


def test_funding_receipt_before_settlement_rejected():
    kw=inputs('funding_crowding_fade')
    kw['funding']['available_at']=kw['funding'].timestamp-pd.Timedelta(seconds=1)
    with pytest.raises(ValueError):s.build_signals(bars(),'funding_crowding_fade',**kw)
