"""Independent reference verifier adversaries; no production model imports/data."""
import numpy as np
import pandas as pd
import pytest
from audit import verify_funding_rank_features as a

START=pd.Timestamp('2026-09-25T00:00Z');END=START+pd.Timedelta(days=10)


def inputs():
    times=pd.date_range(START,END,freq='min',inclusive='left').as_unit('ns');clock=times[:-2]+pd.Timedelta(minutes=2)
    features=pd.DataFrame(index=clock);bars={};funding={};daily=(clock.hour==0)&(clock.minute==5)
    admissible=daily&(clock>=START+pd.Timedelta(days=7))
    for j,symbol in enumerate(a.SYMBOLS):
        native=a.native(symbol);price=(.01 if symbol=='PEPEUSDT' else 100)+np.arange(len(times))*.000001
        bars[symbol]=pd.DataFrame(dict(timestamp=times,instrument_id=native,duration_seconds=60,close=price))
        events=pd.date_range(START,END,freq='8h').as_unit('ns')
        funding[symbol]=pd.DataFrame(dict(timestamp=events,instrument_id=native,funding_rate=(j+1)*.00008))
        features[f'price_{symbol}']=price[:-2]
        features[f'yield_{symbol}']=np.where(admissible,(j+1)*.00001,np.nan)
        features[f'valid_{symbol}']=admissible
    features.attrs=a.ASSUMPTIONS.copy()
    return features,bars,funding


def test_complete_known_constant_reference_and_native_prior_prices():
    features,bars,funding=inputs();a.verify_grid(features,START,END)
    for symbol in a.SYMBOLS:
        evidence=a.verify_stream(features,bars[symbol],funding[symbol],symbol,START,END)
        assert evidence['daily_decisions_checked']==10 and evidence['decision_status_counts']=={'insufficient_history':1,'insufficient_coverage':6,'valid':3}
        assert evidence['maximum_intensity_absolute_error']<1e-18
    assert a.native('PEPEUSDT')=='binance:perpetual:1000PEPEUSDT'


@pytest.mark.parametrize('defect',['price','yield','valid','offday','columns','attrs','naive'])
def test_feature_tampering_rejected_by_static_schema_or_independent_math(defect):
    features,bars,funding=inputs();time=START+pd.Timedelta(days=8,minutes=5)
    if defect=='price':features.loc[time,'price_BTCUSDT']+=1
    elif defect=='yield':features.loc[time,'yield_BTCUSDT']=.123
    elif defect=='valid':features.loc[time,'valid_BTCUSDT']=False
    elif defect=='offday':features.loc[time+pd.Timedelta(minutes=1),'yield_BTCUSDT']=.01
    elif defect=='columns':features=features[features.columns[::-1]]
    elif defect=='attrs':features.attrs['decision_clock']='weekly only'
    else:features.index=features.index.tz_localize(None)
    with pytest.raises(RuntimeError):
        a.verify_grid(features,START,END);a.verify_stream(features,bars['BTCUSDT'],funding['BTCUSDT'],'BTCUSDT',START,END)


def test_unpublished_record_with_past_settlement_cannot_modify_known_predecessors_or_validity():
    _,_,streams=inputs();frame=streams['BTCUSDT'];now=START+pd.Timedelta(days=8,minutes=5)
    baseline=a.reference.reference_at(a.sequence(frame,a.native('BTCUSDT'),START,END),now)
    changed=frame.copy();changed['historical_receipt']=changed.timestamp
    changed.loc[len(changed)]=dict(timestamp=START+pd.Timedelta(days=7,hours=4),instrument_id=a.native('BTCUSDT'),funding_rate=999.,historical_receipt=now+pd.Timedelta(hours=1))
    result=a.reference.reference_at(a.sequence(changed,a.native('BTCUSDT'),START,END),now)
    assert result==baseline and result['valid']
    after=a.reference.reference_at(a.sequence(changed,a.native('BTCUSDT'),START,END),now+pd.Timedelta(hours=1,minutes=2))
    assert not after['valid'] and after['reason']=='mixed_cadence_window'


def test_exact_receipt_processing_clock_is_strictly_excluded_until_next_nanosecond():
    _,_,streams=inputs();frame=streams['BTCUSDT'].copy();now=START+pd.Timedelta(days=8,minutes=5)
    frame['historical_receipt']=frame.timestamp
    latest=frame.timestamp.eq(START+pd.Timedelta(days=8));frame.loc[latest,'historical_receipt']=now-pd.Timedelta(minutes=1)
    frame.loc[latest,'funding_rate']=.008
    fund=a.sequence(frame,a.native('BTCUSDT'),START,END)
    exact=a.reference.reference_at(fund,now);next_ns=a.reference.reference_at(fund,now+pd.Timedelta(nanoseconds=1))
    assert exact['valid'] and exact['intensity']==pytest.approx(.00001)
    assert next_ns['valid'] and next_ns['intensity']>exact['intensity']*2


def test_end_plus_milliseconds_source_is_validated_but_excluded_from_predictor():
    _,_,streams=inputs();frame=streams['BTCUSDT'].copy();base=a.sequence(frame,a.native('BTCUSDT'),START,END)
    frame.loc[len(frame)]=dict(timestamp=END+pd.Timedelta(milliseconds=2),instrument_id=a.native('BTCUSDT'),funding_rate=999.)
    changed=a.sequence(frame,a.native('BTCUSDT'),START,END)
    for field in ('settlement','availability','rates'):np.testing.assert_array_equal(base[field],changed[field])
    frame.loc[len(frame)-1,'instrument_id']='binance:perpetual:ETHUSDT'
    with pytest.raises(RuntimeError,match='identity'):a.sequence(frame,a.native('BTCUSDT'),START,END)


def test_outside_year_predecessor_rejected_instead_of_warmup():
    _,_,streams=inputs();frame=streams['BTCUSDT'].copy()
    frame.loc[len(frame)]=dict(timestamp=START-pd.Timedelta(hours=8),instrument_id=a.native('BTCUSDT'),funding_rate=.00008)
    with pytest.raises(RuntimeError,match='outside-year'):a.sequence(frame,a.native('BTCUSDT'),START,END)


def test_resealed_receipt_cannot_change_static_assumptions_or_math(tmp_path,monkeypatch):
    features,bars,funding=inputs();root=tmp_path/'experiment';root.mkdir();cache=tmp_path/'cache';cache.mkdir()
    monkeypatch.setattr(a,'START',START);monkeypatch.setattr(a,'END',END)
    # Direct component tests use explicit bounds; the full verifier's defaults
    # are intentionally the original year. Stub only source provenance here.
    for symbol in a.SYMBOLS:
        folder=cache/symbol;folder.mkdir();bars[symbol].to_parquet(folder/'bars.parquet');funding[symbol].to_parquet(folder/'funding.parquet')
    bad=features.copy();bad.attrs['availability']='same minute close with no lag';bad.to_parquet(root/'features.parquet')
    import json
    lock={'inputs':{}}
    for name in ('source_lock.json','input_verification.json'): (root/name).write_text('{}')
    prereg=tmp_path/a.PREREG_PATH;prereg.mkdir(parents=True);(prereg/'preregistration.json').write_text('{}')
    monkeypatch.setattr(a,'REPO',tmp_path)
    receipt={'rows':len(bad),'columns':list(bad.columns),'availability_assumptions':bad.attrs,'features_sha256':a.sha(root/'features.parquet')}
    (root/'feature_receipt.json').write_text(json.dumps(receipt))
    monkeypatch.setattr(a,'verify_provenance',lambda *args:(lock,receipt))
    # The new receipt is internally self-consistent but must not redefine the
    # reviewed public availability policy. Force only grid bounds for fixture.
    original=a.verify_grid;monkeypatch.setattr(a,'verify_grid',lambda f:original(f,START,END))
    with pytest.raises(RuntimeError,match='static protocol'):a.verify_features(root,cache,'a'*40,'b'*40)
