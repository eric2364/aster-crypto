"""Adversarial standalone reference tests, without production signal imports."""
import ast
import copy
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from audit import verify_cross_venue_features as a


def history(n=22,hours=8):
    return pd.DataFrame({'timestamp':pd.date_range(a.START,periods=n+1,freq=pd.Timedelta(hours=hours)),
        'instrument_id':a.iid('bybit','PEPEUSDT'),'funding_rate':hours*.001})


def calculate(frame,now):return a.reference_at(a.funding_sequence(frame),now)


def test_no_production_module_import_or_execution():
    tree=ast.parse(Path(a.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):assert all(not n.name.startswith(('examples','aster')) for n in node.names)
        if isinstance(node,ast.ImportFrom):assert not (node.module or '').startswith(('examples','aster'))


def test_overlap_weighted_arithmetic_and_first_rate_no_interval():
    frame=history();frame.loc[22,'funding_rate']=.016;frame.loc[0,'funding_rate']=1e6
    result=calculate(frame,frame.timestamp.iloc[-1]+pd.Timedelta(minutes=2))
    covered=168-2/60
    assert result['valid'] and result['covered_hours']==pytest.approx(covered)
    assert result['intensity']==pytest.approx((.001*(covered-8)+.002*8)/covered)


@pytest.mark.parametrize('cadence',[1,2,4,8])
def test_actual_per_hour_rate_consistent_across_cadences(cadence):
    frame=history(n=176//cadence,hours=cadence)
    assert calculate(frame,frame.timestamp.iloc[-1]+pd.Timedelta(minutes=2))['intensity']==pytest.approx(.001)


def test_unpublished_past_record_cannot_alter_predecessor_or_validity():
    frame=history();now=frame.timestamp.iloc[-1]+pd.Timedelta(minutes=2);frame['historical_receipt']=frame.timestamp
    baseline=calculate(frame,now)
    hidden=pd.DataFrame({'timestamp':[frame.timestamp.iloc[-1]-pd.Timedelta(hours=4)],'instrument_id':[a.iid('bybit','PEPEUSDT')],
        'funding_rate':[1000.],'historical_receipt':[now+pd.Timedelta(minutes=1)]})
    altered=pd.concat([frame,hidden],ignore_index=True)
    assert calculate(altered,now)==baseline
    altered.loc[len(frame),'funding_rate']=-1000.
    assert calculate(altered,now)==baseline
    assert calculate(altered,now+pd.Timedelta(minutes=2))==calculate(frame,now+pd.Timedelta(minutes=2))
    assert calculate(altered,now+pd.Timedelta(minutes=2,microseconds=1))['reason']=='mixed_cadence_window'


def test_future_unknown_gap_does_not_poison_earlier_prefix():
    frame=history(n=30);now=frame.timestamp.iloc[22]+pd.Timedelta(minutes=2)
    baseline=calculate(frame,now)
    frame.loc[25,'timestamp']+=pd.Timedelta(minutes=30);frame.loc[23:,'funding_rate']=10000
    assert calculate(frame,now)==baseline
    assert calculate(frame.iloc[:23],now)==baseline


def test_strict_receipt_boundary_and_expiry():
    frame=history();last=frame.timestamp.iloc[-1]
    seq=a.funding_sequence(frame)
    assert seq['availability_assumed']
    assert not a.reference_at(seq,last+pd.Timedelta(hours=8,minutes=10,microseconds=1))['valid']
    assert a.reference_at(seq,last+pd.Timedelta(hours=8,minutes=10))['valid']
    frame['available_at']=frame.timestamp;frame.loc[22,'available_at']=last+pd.Timedelta(minutes=5)
    seq=a.funding_sequence(frame)
    assert seq['availability'][-1]==(last+pd.Timedelta(minutes=6)).value
    assert not seq['availability_assumed']
    frame.loc[22,'available_at']=last-pd.Timedelta(microseconds=1)
    with pytest.raises(AssertionError):a.funding_sequence(frame)


@pytest.mark.parametrize('jitter,valid',[(5,True),(-5,True),(5.000001,False),(-5.000001,False)])
def test_recognition_tolerance_actual_elapsed_denominator(jitter,valid):
    frame=history();frame.loc[22,'timestamp']+=pd.Timedelta(seconds=jitter)
    frame.loc[22,'funding_rate']=.001*(8+jitter/3600)
    result=calculate(frame,frame.timestamp.iloc[-1]+pd.Timedelta(minutes=2))
    assert result['valid']==valid
    if valid:assert result['intensity']==pytest.approx(.001)


def test_coverage_first_predecessor_and_invalid_interval_aging():
    frame=history(n=19)
    assert calculate(frame,frame.timestamp.iloc[-1]+pd.Timedelta(minutes=2))['valid']
    assert not calculate(frame.iloc[:19],frame.timestamp.iloc[18]+pd.Timedelta(minutes=2))['valid']
    frame=history(n=24)
    bad=pd.DataFrame({'timestamp':[a.START+pd.Timedelta(minutes=30)],'instrument_id':[a.iid('bybit','PEPEUSDT')],'funding_rate':[.0005]})
    frame=pd.concat([frame,bad])
    assert not calculate(frame,a.START+pd.Timedelta(hours=160,minutes=2))['valid']
    assert calculate(frame,a.START+pd.Timedelta(hours=192,minutes=2))['valid']


@pytest.mark.parametrize('bad',['duplicate','outside_year','wrong_id','naive','nonfinite'])
def test_invalid_source_rejected(bad):
    frame=history()
    if bad=='duplicate':frame.loc[1,'timestamp']=frame.timestamp.iloc[0]
    elif bad=='outside_year':frame.loc[0,'timestamp']=a.START-pd.Timedelta(hours=1)
    elif bad=='wrong_id':frame.loc[1,'instrument_id']='bybit:perpetual:PEPEUSDT'
    elif bad=='naive':frame.timestamp=frame.timestamp.dt.tz_localize(None)
    else:frame.loc[1,'funding_rate']=np.nan
    with pytest.raises(AssertionError):a.funding_sequence(frame)


@pytest.fixture
def tiny():
    start=a.START;end=start+pd.Timedelta(minutes=12)
    grid=pd.date_range(start+pd.Timedelta(minutes=2),end,freq='min',inclusive='left')
    frame=pd.DataFrame(index=grid)
    for v in a.VENUES:
        for s in a.SYMBOLS:
            frame[f'price_{v}_{s}']=np.arange(10,dtype=float)+100
            frame[f'yield_{v}_{s}']=np.nan;frame[f'valid_{v}_{s}']=False
    frame.attrs=a.RECEIPT_ASSUMPTIONS.copy()
    bars=pd.DataFrame({'timestamp':pd.date_range(start,end,freq='min',inclusive='left'),
        'instrument_id':a.iid('bybit','PEPEUSDT'),'duration_seconds':60,'close':np.arange(12,dtype=float)+100})
    fund=history(n=0)
    return start,end,frame,bars,fund


def test_full_48_grid_and_two_minute_prior_price_mapping(tiny):
    start,end,frame,bars,fund=tiny
    assert len(a.verify_grid(frame,start,end))==10
    result=a.verify_stream(frame,bars,fund,'bybit','PEPEUSDT',start,end)
    assert result['decision_count']==1 and result['native_id']=='bybit:perpetual:1000PEPEUSDT'
    assert result['decision_status_counts']=={'insufficient_history':1}


@pytest.mark.parametrize('bad',['future_price','offhour_valid','offhour_yield','decision_valid','extra_column','missing_grid','assumptions'])
def test_feature_tampering_cannot_pass_reference(tiny,bad):
    start,end,frame,bars,fund=tiny
    if bad=='future_price':frame.iloc[0,frame.columns.get_loc('price_bybit_PEPEUSDT')]=101
    elif bad=='offhour_valid':frame.iloc[0,frame.columns.get_loc('valid_bybit_PEPEUSDT')]=True
    elif bad=='offhour_yield':frame.iloc[0,frame.columns.get_loc('yield_bybit_PEPEUSDT')]=.001
    elif bad=='decision_valid':frame.loc[start+pd.Timedelta(minutes=5),'valid_bybit_PEPEUSDT']=True
    elif bad=='extra_column':frame['unregistered']=0
    elif bad=='missing_grid':frame.drop(frame.index[0],inplace=True)
    else:frame.attrs['availability']='same candle close'
    with pytest.raises(AssertionError):
        a.verify_grid(frame,start,end);a.verify_stream(frame,bars,fund,'bybit','PEPEUSDT',start,end)


@pytest.mark.parametrize('changed',[False,True])
def test_before_after_auditor_hash_guard(tiny,monkeypatch,tmp_path,changed):
    start,end,frame,bars,fund=tiny
    receipt={'rows':len(frame),'columns':list(frame),'availability_assumptions':frame.attrs}
    monkeypatch.setattr(a,'verify_provenance',lambda *args:({'fixture':True},receipt))
    monkeypatch.setattr(a,'verify_grid',lambda f:f.index)
    monkeypatch.setattr(a,'verify_stream',lambda *args:{'synthetic':True})
    monkeypatch.setattr(a.pd,'read_parquet',lambda path,**kwargs:frame if str(path).endswith('features.parquet') else bars)
    calls=[]
    def digest(path):
        if str(path)==a.__file__:
            calls.append(path)
            return 'before' if len(calls)==1 or not changed else 'changed'
        return 'fixture-hash'
    monkeypatch.setattr(a,'sha',digest)
    if changed:
        with pytest.raises(AssertionError,match='auditor changed'):a.verify_features(tmp_path,'binance','bybit')
    else:
        cert=a.verify_features(tmp_path,'binance','bybit')
        assert cert['auditor_sha256']=='before' and cert['source_unchanged_during_audit'] and cert['auditor_source_unchanged']
    assert len(calls)==2


def test_published_input_anchor_rejects_resealed_shortened_lock(tmp_path,monkeypatch):
    import json
    root=tmp_path/'results';root.mkdir();repo=tmp_path/'repo';docs=repo/'docs/cross_venue_preregistration';docs.mkdir(parents=True)
    lock={'sources':{'fixture.py':'sha'},'inputs':{'/fixture':'sha'}}
    verification={'fixture':True}
    def raw(value):return json.dumps(value).encode()
    original={'source_lock.json':raw(lock),'input_verification.json':raw(verification)}
    for name,value in original.items():(root/name).write_bytes(value)
    prereg={'source_commit':a.ANCHOR,'proposed_candidate_number':26,'historical_features_exist':False,
        'trial_directory_exists':False,'source_lock_sha256':a.sha(root/'source_lock.json'),
        'input_verification_sha256':a.sha(root/'input_verification.json'),'input_files':1,'source_files':1}
    original['preregistration.json']=raw(prereg);(docs/'preregistration.json').write_bytes(raw(prereg))
    monkeypatch.setattr(a,'REPO',repo)
    def git(args,**kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(stdout=original[args[-1].split('/')[-1]])
    monkeypatch.setattr(a.subprocess,'run',git)
    a.verify_input_anchor(root)
    lock['inputs']={};(root/'source_lock.json').write_bytes(raw(lock))
    # Updating a local hash cannot rewrite the previously published Git bytes.
    with pytest.raises(AssertionError,match='anchor differs'):a.verify_input_anchor(root)
