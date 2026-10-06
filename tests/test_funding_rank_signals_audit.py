"""Independent causal wrapper tests, synthetic native inputs only."""
import numpy as np
import pandas as pd
import pytest
from examples.funding_rank import signals as s

END=pd.Timestamp('2026-10-05T00:00Z')
START=END-pd.Timedelta(days=10)


@pytest.fixture
def inputs(monkeypatch):
    monkeypatch.setattr(s,'START',START);monkeypatch.setattr(s,'END',END)
    grid=pd.date_range(START,END,freq='min',inclusive='left').as_unit('ns')
    bars={};funding={}
    for j,label in enumerate(s.SYMBOLS):
        iid=s.native_id('binance',label)
        price=(.01 if label=='PEPEUSDT' else 100)+np.arange(len(grid))*0.000001
        bars[iid]=pd.DataFrame(dict(timestamp=grid,instrument_id=iid,duration_seconds=60,close=price))
        settles=pd.date_range(START,END,freq='8h').as_unit('ns')
        funding[iid]=pd.DataFrame(dict(timestamp=settles,instrument_id=iid,funding_rate=(j+1)*.00008))
    return bars,funding


def test_native_prices_are_exact_two_minutes_prior_and_yields_daily_only(inputs):
    bars,funding=inputs;result=s.build_features(bars,funding)
    assert len(result)==14398 and len(result.columns)==24
    assert result.index[0]==START+pd.Timedelta(minutes=2) and result.index[-1]==END-pd.Timedelta(minutes=1)
    daily=(result.index.hour==0)&(result.index.minute==5)
    for j,label in enumerate(s.SYMBOLS):
        iid=s.native_id('binance',label)
        np.testing.assert_array_equal(result[f'price_{label}'],bars[iid].close.iloc[:-2])
        assert result[f'yield_{label}'].loc[~daily].isna().all() and not result[f'valid_{label}'].loc[~daily].any()
        assert result[f'valid_{label}'].loc[daily][-3:].all()
        np.testing.assert_allclose(result[f'yield_{label}'].loc[daily].dropna(),(j+1)*.00001,rtol=1e-13)
    assert bars[s.native_id('binance','PEPEUSDT')].instrument_id.unique().tolist()==['binance:perpetual:1000PEPEUSDT']


def test_future_price_and_unpublished_past_settlement_do_not_change_earlier_features(inputs):
    bars,funding=inputs;original=s.build_features(bars,funding);cut=START+pd.Timedelta(days=7,hours=12)
    revised={i:f.copy() for i,f in funding.items()};newbars={i:b.copy() for i,b in bars.items()}
    for iid,frame in revised.items():
        frame['historical_receipt']=frame.timestamp
        late=frame.timestamp.eq(START+pd.Timedelta(days=7)-pd.Timedelta(hours=8))
        frame.loc[late,'historical_receipt']=START+pd.Timedelta(days=7,hours=10)
        frame.loc[late,'funding_rate']=987.
        # For the comparison baseline, late receipt is fixed before changing value.
    delayed={i:f.copy() for i,f in revised.items()}
    for frame in delayed.values():frame.loc[frame.timestamp.eq(START+pd.Timedelta(days=7)-pd.Timedelta(hours=8)),'funding_rate']=.000001
    baseline=s.build_features(bars,delayed)
    for frame in newbars.values():frame.loc[frame.timestamp>=cut,'close']*=1000
    changed=s.build_features(newbars,revised)
    pd.testing.assert_frame_equal(baseline.loc[baseline.index<START+pd.Timedelta(days=7,hours=10)],changed.loc[changed.index<START+pd.Timedelta(days=7,hours=10)])
    pd.testing.assert_frame_equal(original.filter(like='price_').loc[original.index<cut],changed.filter(like='price_').loc[changed.index<cut])


def test_prefix_end_cut_does_not_reset_past_funding_history(inputs,monkeypatch):
    bars,funding=inputs;full=s.build_features(bars,funding);cut=START+pd.Timedelta(days=8,hours=2)
    clipped={i:f.loc[f.timestamp<cut].copy() for i,f in bars.items()}
    monkeypatch.setattr(s,'END',cut)
    prefix=s.build_features(clipped,funding)
    pd.testing.assert_frame_equal(prefix,full.loc[prefix.index])


def test_exclusive_end_plus_two_millisecond_funding_is_not_prepared_as_predictor(inputs):
    bars,funding=inputs
    for iid,frame in funding.items():
        frame.loc[len(frame)]=dict(timestamp=END+pd.Timedelta(milliseconds=2),instrument_id=iid,funding_rate=999.)
    result=s.build_features(bars,funding)
    assert result.index.max()<END and result.filter(like='yield_').max().max()<1


def test_wrong_native_end_boundary_row_cannot_be_hidden_by_exclusive_clip(inputs):
    bars,funding=inputs;iid=s.native_id('binance','PEPEUSDT')
    funding[iid].loc[len(funding[iid])]=dict(timestamp=END+pd.Timedelta(milliseconds=2),instrument_id='binance:perpetual:PEPEUSDT',funding_rate=.001)
    with pytest.raises(ValueError,match='identity'):s.build_features(bars,funding)


@pytest.mark.parametrize('defect',['wrong_id','duplicate','gap','naive','nan_price','nonminute'])
def test_native_price_grid_defects_cannot_be_aligned_or_interpolated(inputs,defect):
    bars,funding=inputs;iid=s.native_id('binance','PEPEUSDT');frame=bars[iid]
    if defect=='wrong_id':frame.loc[4,'instrument_id']='binance:perpetual:PEPEUSDT'
    elif defect=='duplicate':frame.loc[4,'timestamp']=frame.loc[3,'timestamp']
    elif defect=='gap':bars[iid]=frame.drop(index=4)
    elif defect=='naive':frame['timestamp']=frame.timestamp.dt.tz_localize(None)
    elif defect=='nan_price':frame.loc[4,'close']=np.nan
    else:frame.loc[4,'duration_seconds']=300
    with pytest.raises(ValueError):s.build_features(bars,funding)


def test_original_receipt_before_settlement_rejected(inputs):
    bars,funding=inputs;iid=s.native_id('binance','BTCUSDT')
    funding[iid]['historical_receipt']=funding[iid].timestamp-pd.Timedelta(seconds=1)
    with pytest.raises(ValueError,match='precedes settlement'):s.build_features(bars,funding)
