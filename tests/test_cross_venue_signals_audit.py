"""Independent funding-intensity arithmetic; all fixtures synthetic."""
import numpy as np
import pandas as pd
import pytest
from examples.cross_venue import signals as s

START=pd.Timestamp('2025-10-05',tz='UTC')
IID='bybit:perpetual:1000PEPEUSDT'


def history(intervals=22,hours=8,iid=IID):
    stamps=[START+pd.Timedelta(hours=hours*i) for i in range(intervals+1)]
    return pd.DataFrame({'timestamp':stamps,'funding_rate':[.001*hours]*(intervals+1),
                         'instrument_id':iid})


def result(frame,now):
    return s.yield_at(s.prepare_funding(frame),now)


def test_overlap_weights_and_per_hour_normalization():
    frame=history(); frame.loc[22,'funding_rate']=.016
    now=frame.timestamp.iloc[-1]+pd.Timedelta(minutes=2)
    value=result(frame,now)
    covered=168-2/60
    expected=(.001*(covered-8)+.002*8)/covered
    assert value['valid'] and value['covered_hours']==pytest.approx(covered)
    assert value['intensity']==pytest.approx(expected,abs=1e-14)
    assert value['latest_interval_hours']==8
    for cadence in (1,2,4,8):
        f=history(intervals=176//cadence,hours=cadence)
        assert result(f,f.timestamp.iloc[-1]+pd.Timedelta(minutes=2))['intensity']==pytest.approx(.001)


def test_known_sequence_excludes_unpublished_past_settlement():
    frame=history();now=frame.timestamp.iloc[-1]+pd.Timedelta(minutes=2)
    frame['available_at']=frame.timestamp
    base=result(frame,now)
    hidden=pd.DataFrame({'timestamp':[frame.timestamp.iloc[-1]-pd.Timedelta(hours=4)],
        'funding_rate':[99.], 'instrument_id':[IID], 'available_at':[now+pd.Timedelta(minutes=1)]})
    combined=pd.concat([frame,hidden],ignore_index=True)
    assert result(combined,now)==base
    combined.loc[len(frame),'funding_rate']=-99.
    assert result(combined,now)==base
    # Once known, the 4h predecessor splits one8h interval: mixed cadence must suppress.
    later=result(combined,now+pd.Timedelta(minutes=2,microseconds=1))
    assert later['valid'] is False and later['intensity'] is None


def test_publication_is_strictly_past_and_receipt_processing_lagged():
    frame=history();last=frame.timestamp.iloc[-1]
    frame['available_at']=frame.timestamp
    frame.loc[len(frame)-1,'available_at']=last+pd.Timedelta(minutes=5)
    prepared=s.prepare_funding(frame)
    assert prepared.available_at.iloc[-1]==last+pd.Timedelta(minutes=6)
    boundary=last+pd.Timedelta(minutes=6)
    before=s.yield_at(prepared,boundary)
    after=s.yield_at(prepared,boundary+pd.Timedelta(microseconds=1))
    assert before['latest_settlement']==frame.timestamp.iloc[-2]
    assert after['latest_settlement']==last
    assert prepared.availability_is_assumed.eq(False).all()


def test_no_historical_receipt_is_explicit_assumption():
    frame=history();prepared=s.prepare_funding(frame)
    assert prepared.availability_is_assumed.eq(True).all()
    assert (prepared.available_at-prepared.timestamp==pd.Timedelta(minutes=1)).all()
    frame['available_at']=frame.timestamp-pd.Timedelta(microseconds=1)
    with pytest.raises(ValueError):s.prepare_funding(frame)


def test_prefix_and_future_rate_perturbation_invariance():
    frame=history(intervals=30);now=frame.timestamp.iloc[22]+pd.Timedelta(minutes=2)
    baseline=result(frame,now)
    prefix=frame.iloc[:23].copy()
    assert result(prefix,now)==baseline
    future=frame.copy();future.loc[23:,'funding_rate']=[-1000,1000]*4
    assert result(future,now)==baseline
    # A future cadence error cannot globally invalidate earlier features.
    future.loc[25,'timestamp']+=pd.Timedelta(minutes=30)
    assert result(future,now)==baseline


def test_coverage_startup_first_rate_ignored_and_no_previous_year():
    frame=history(intervals=19)
    now=frame.timestamp.iloc[-1]+pd.Timedelta(minutes=2)
    value=result(frame,now)
    assert value['valid'] and value['covered_hours']==pytest.approx(152)
    frame.loc[0,'funding_rate']=9000
    assert result(frame,now)==value
    shorter=frame.iloc[:19]
    insufficient=result(shorter,shorter.timestamp.iloc[-1]+pd.Timedelta(minutes=2))
    assert insufficient['valid'] is False and insufficient['intensity'] is None
    outside=frame.copy();outside.loc[0,'timestamp']=START-pd.Timedelta(hours=8)
    with pytest.raises(ValueError):s.prepare_funding(outside)


def test_exact_expiry_boundary():
    frame=history();last=frame.timestamp.iloc[-1]
    assert result(frame,last+pd.Timedelta(hours=8,minutes=10))['valid']
    assert not result(frame,last+pd.Timedelta(hours=8,minutes=10,microseconds=1))['valid']


def test_invalid_overlap_suppresses_then_ages_out():
    frame=history(intervals=24)
    extra=pd.DataFrame({'timestamp':[START+pd.Timedelta(minutes=30)],'funding_rate':[.0005],'instrument_id':[IID]})
    frame=pd.concat([frame,extra],ignore_index=True)
    assert not result(frame,START+pd.Timedelta(hours=160,minutes=2))['valid']
    assert result(frame,START+pd.Timedelta(hours=192,minutes=2))['valid']


@pytest.mark.parametrize('seconds,valid',[(5,True),(-5,True),(5.000001,False),(-5.000001,False)])
def test_interval_tolerance_uses_actual_elapsed_duration(seconds,valid):
    frame=history();frame.loc[22,'timestamp']+=pd.Timedelta(seconds=seconds)
    delta=8+seconds/3600
    frame.loc[22,'funding_rate']=.001*delta
    value=result(frame,frame.timestamp.iloc[-1]+pd.Timedelta(minutes=2))
    assert value['valid']==valid
    if valid:
        assert value['latest_interval_hours']==pytest.approx(delta)
        assert value['intensity']==pytest.approx(.001,abs=1e-14)


@pytest.mark.parametrize('bad',['mixed_iid','duplicate','naive','nan_rate','after_year'])
def test_reject_invalid_source_identity_and_clocks(bad):
    frame=history()
    if bad=='mixed_iid':frame.loc[2,'instrument_id']='binance:perpetual:1000PEPEUSDT'
    elif bad=='duplicate':frame.loc[2,'timestamp']=frame.timestamp.iloc[1]
    elif bad=='naive':frame.timestamp=frame.timestamp.dt.tz_localize(None)
    elif bad=='nan_rate':frame.loc[2,'funding_rate']=np.nan
    else:frame.loc[22,'timestamp']=pd.Timestamp('2026-10-05T00:00:01Z')
    with pytest.raises(ValueError):s.prepare_funding(frame)


def test_separate_venue_native_sequences_and_naive_decision():
    bybit=history();binance=history(iid='binance:perpetual:1000PEPEUSDT')
    binance.funding_rate*=2
    now=bybit.timestamp.iloc[-1]+pd.Timedelta(minutes=2)
    assert result(binance,now)['intensity']==pytest.approx(2*result(bybit,now)['intensity'])
    with pytest.raises(ValueError):result(bybit,now.tz_localize(None))


@pytest.fixture
def minute_inputs(monkeypatch):
    stop=START+pd.Timedelta(minutes=12)
    monkeypatch.setattr(s,'END',stop)
    grid=pd.date_range(START,stop,freq='min',inclusive='left')
    bars={};fund={}
    for venue in s.VENUES:
        for label in s.SYMBOLS:
            iid=s.native_id(venue,label)
            bars[iid]=pd.DataFrame({'timestamp':grid,'instrument_id':iid,'duration_seconds':60,
                'close':np.arange(12,dtype=float)+100})
            fund[iid]=pd.DataFrame({'timestamp':[START],'instrument_id':[iid],'funding_rate':[.001]})
    return bars,fund


def test_price_availability_two_minutes_native_units_and_decision_clock(minute_inputs):
    bars,fund=minute_inputs;features=s.build_features(bars,fund)
    assert features.index[0]==START+pd.Timedelta(minutes=2)
    assert features.index[-1]==START+pd.Timedelta(minutes=11)
    assert features.price_bybit_PEPEUSDT.tolist()==list(range(100,110))
    assert not features.filter(like='valid_').any().any()  # one known settlement has no predecessor
    assert features.filter(like='yield_').isna().all().all()
    mutated={iid:f.copy() for iid,f in bars.items()}
    for f in mutated.values():f.loc[9:,'close']=999999
    pd.testing.assert_frame_equal(s.build_features(mutated,fund).iloc[:9],features.iloc[:9])


@pytest.mark.parametrize('bad',['missing_native','wrong_price_id','price_gap','wrong_funding_id','bad_duration','bad_close','naive_price_clock'])
def test_full_grid_native_price_source_guards(minute_inputs,bad):
    bars,fund=minute_inputs;iid=s.native_id('bybit','PEPEUSDT')
    if bad=='missing_native':bars.pop(iid)
    elif bad=='wrong_price_id':bars[iid].loc[0,'instrument_id']='bybit:perpetual:PEPEUSDT'
    elif bad=='price_gap':bars[iid]=bars[iid].iloc[1:]
    elif bad=='wrong_funding_id':fund[iid].loc[0,'instrument_id']='binance:perpetual:1000PEPEUSDT'
    elif bad=='bad_duration':bars[iid].loc[0,'duration_seconds']=120
    elif bad=='naive_price_clock':bars[iid].timestamp=bars[iid].timestamp.dt.tz_localize(None)
    else:bars[iid].loc[0,'close']=0
    with pytest.raises(ValueError):s.build_features(bars,fund)


def test_preparation_cannot_apply_processing_lag_twice():
    prepared=s.prepare_funding(history())
    with pytest.raises(ValueError):s.prepare_funding(prepared)
    with pytest.raises(ValueError):s.yield_at(history(),START+pd.Timedelta(days=8))


def test_warmed_feature_validity_only_hourly_five_and_prefix(monkeypatch):
    stop=START+pd.Timedelta(days=8)
    monkeypatch.setattr(s,'END',stop)
    grid=pd.date_range(START,stop,freq='min',inclusive='left')
    bars={};fund={}
    for venue in s.VENUES:
        for label in s.SYMBOLS:
            iid=s.native_id(venue,label)
            bars[iid]=pd.DataFrame({'timestamp':grid,'instrument_id':iid,'duration_seconds':60,'close':100.})
            fund[iid]=history(intervals=24,iid=iid)
    features=s.build_features(bars,fund)
    valid=features.valid_bybit_PEPEUSDT
    assert valid.any()
    assert (features.index[valid].minute==5).all()
    assert not valid[features.index.minute!=5].any()
    assert features.yield_bybit_PEPEUSDT[valid].eq(.001).all() or np.allclose(features.yield_bybit_PEPEUSDT[valid],.001,rtol=0,atol=1e-14)
    # A shorter declared synthetic source window must preserve every common feature row.
    prefix_stop=START+pd.Timedelta(days=7)
    monkeypatch.setattr(s,'END',prefix_stop)
    pb={iid:f[f.timestamp<prefix_stop].copy() for iid,f in bars.items()}
    pf={iid:f[f.timestamp<=prefix_stop].copy() for iid,f in fund.items()}
    prefix=s.build_features(pb,pf)
    pd.testing.assert_frame_equal(prefix,features.loc[prefix.index])


def test_unknown_native_funding_identity_rejected():
    with pytest.raises(ValueError):s.prepare_funding(history(iid='bybit:perpetual:PEPEUSDT'))
