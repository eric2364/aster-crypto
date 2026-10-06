"""Independent verifier hand cases. No market archives or production imports."""
import ast
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from audit import verify_positioning_features as a

START=pd.Timestamp('2025-10-05',tz='UTC');END=START+pd.Timedelta(hours=3)
IID=a.iid('1000PEPEUSDT')


def source():
    p=pd.date_range(START,END,freq='min',inclusive='left')
    bars=pd.DataFrame({'timestamp':p,'instrument_id':IID,'duration_seconds':60,'close':100.})
    metrics=pd.DataFrame({'timestamp':p[::5],'instrument_id':IID,'sum_open_interest':1000.})
    return bars,metrics


def ref(b,m,d=6):return a.reference_frame(b,m,IID,d,START,END)


@pytest.mark.parametrize('delay,first',[(6,7),(11,12)])
def test_known_unpublished_boundary_and_completed_returns(delay,first):
    b,m=source();b.loc[60,'close']=110.;b.loc[45,'close']=105.;m.loc[12,'sum_open_interest']=900.;m.loc[11,'sum_open_interest']=800.
    f=ref(b,m,delay);t=START+pd.Timedelta(minutes=60+first)
    assert f.loc[t-pd.Timedelta(minutes=1),'metric_source_label']==START+pd.Timedelta(minutes=55)
    row=f.loc[t];assert row.metric_source_label==START+pd.Timedelta(minutes=60)
    assert row.quantity_change_1h==900/1000-1 and row.quantity_change_5m==900/800-1
    assert row.metric_age_seconds==60 and row.valid
    r=f.loc[START+pd.Timedelta(minutes=62)]
    assert r.price_return_1h==110/100-1 and r.price_return_15m==110/105-1
    assert r.price_source_label==START+pd.Timedelta(minutes=60) and r.price_available_at==r.name


@pytest.mark.parametrize('delay',[6,11])
def test_age_sawtooth_and_no_outside_year_warmup(delay):
    b,m=source();f=ref(b,m,delay)
    assert f.index[0]==START+pd.Timedelta(minutes=2) and f.index[-1]==END-pd.Timedelta(minutes=1)
    assert f.loc[f.index<START+pd.Timedelta(minutes=delay+1),'metric_source_label'].isna().all()
    assert not f.loc[f.index<START+pd.Timedelta(minutes=60+delay+1),'valid'].any()
    t=START+pd.Timedelta(minutes=60+delay+1)
    assert f.loc[t:t+pd.Timedelta(minutes=4),'metric_age_seconds'].tolist()==[60.,120.,180.,240.,300.]


@pytest.mark.parametrize('delay',[6,11])
def test_past_but_not_yet_available_and_future_mutation(delay):
    b,m=source();old=ref(b,m,delay);m.loc[12,'sum_open_interest']=99999.
    new=ref(b,m,delay);cut=START+pd.Timedelta(minutes=60+delay)
    pd.testing.assert_frame_equal(old.loc[:cut],new.loc[:cut])
    b,m=source();old=ref(b,m,delay);cut=START+pd.Timedelta(minutes=120)
    b.loc[b.timestamp>=cut,'close']=.1;m.loc[m.timestamp>=cut,'sum_open_interest']=7.
    new=ref(b,m,delay);pd.testing.assert_frame_equal(old.loc[:cut],new.loc[:cut])


def test_prefix_and_native_constant_scale_preserve_causal_ratios():
    b,m=source();b.close=np.arange(len(b),dtype=float)+100.;m.sum_open_interest=np.arange(len(m),dtype=float)+1000.
    old=ref(b,m);end=START+pd.Timedelta(hours=2)
    prefix=a.reference_frame(b[b.timestamp<end],m[m.timestamp<end],IID,6,START,end)
    expected=old[old.index<end].copy();expected.attrs=prefix.attrs;pd.testing.assert_frame_equal(prefix,expected)
    m.sum_open_interest*=1000;scaled=ref(b,m)
    np.testing.assert_allclose(old.quantity_change_1h,scaled.quantity_change_1h,equal_nan=True)
    np.testing.assert_allclose(old.quantity_change_5m,scaled.quantity_change_5m,equal_nan=True)
    assert scaled.native_open_interest.max()>1e6


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_clock_precision_roundtrip(unit,tmp_path):
    b,m=source();f=ref(b,m)
    for frame in (b,m):frame.timestamp=frame.timestamp.dt.tz_convert('Asia/Hong_Kong').dt.as_unit(unit)
    pd.testing.assert_frame_equal(f,ref(b,m))
    p=tmp_path/'features.parquet';f.to_parquet(p);loaded=pd.read_parquet(p)
    result=a.verify_stream(loaded,b,m,IID,6,START,END)
    assert result['full_reconstruction'] and result['maximum_absolute_error']==0


@pytest.mark.parametrize('kind',['duplicate','gap','outside','naive','wrongnative','bool','infinite','zero','duration','receipt'])
def test_reject_malformed_or_silently_repaired_source(kind):
    b,m=source()
    if kind=='duplicate':m.loc[2,'timestamp']=m.loc[1,'timestamp']
    if kind=='gap':m=m.drop(index=2)
    if kind=='outside':m.loc[0,'timestamp']=START-pd.Timedelta(minutes=5)
    if kind=='naive':b.timestamp=b.timestamp.dt.tz_localize(None)
    if kind=='wrongnative':m.loc[0,'instrument_id']=a.iid('PEPEUSDT')
    if kind=='bool':m.sum_open_interest=True
    if kind=='infinite':m.loc[0,'sum_open_interest']=np.inf
    if kind=='zero':b.loc[0,'close']=0.
    if kind=='duration':b.loc[0,'duration_seconds']=300
    if kind=='receipt':m['available_at']=m.timestamp
    with pytest.raises(AssertionError):ref(b,m)


def test_finite_sources_overflow_is_missing_and_ineligible():
    b,m=source();b.close=1e-300;b.loc[60:,'close']=1e300;m.sum_open_interest=1e-300;m.loc[12:,'sum_open_interest']=1e300
    f=ref(b,m);t=START+pd.Timedelta(minutes=67)
    assert pd.isna(f.loc[t,'quantity_change_1h']) and pd.isna(f.loc[t,'price_return_1h']) and not f.loc[t,'valid']
    assert not np.isinf(f.select_dtypes('number').to_numpy()).any()


@pytest.mark.parametrize('kind',['value','derived','sourceclock','availability','valid','native','attrs','columns','index','boolnumeric'])
def test_resealed_feature_content_tamper_rejected(kind):
    b,m=source();f=ref(b,m);t=f.index[80]
    if kind=='value':f.loc[t,'native_open_interest']+=1
    if kind=='derived':f.loc[t,'quantity_change_5m']=.123
    if kind=='sourceclock':f.loc[t,'metric_source_label']+=pd.Timedelta(minutes=5)
    if kind=='availability':f.loc[t,'metric_available_at']=t
    if kind=='valid':f.loc[t,'valid']=not f.loc[t,'valid']
    if kind=='native':f.loc[t,'instrument_id']=a.iid('PEPEUSDT')
    if kind=='attrs':f.attrs['vintage']='verified historical delivery'
    if kind=='columns':f=f[list(reversed(f.columns))]
    if kind=='index':f.index=f.index.tz_convert('Asia/Hong_Kong')
    if kind=='boolnumeric':f['price']=True
    with pytest.raises(AssertionError):a.verify_stream(f,b,m,IID,6,START,END)


@pytest.mark.parametrize('extra',['third','extra_file','symlink','wrongnative'])
def test_exact_feature_namespace_before_deserialization(tmp_path,extra):
    root=tmp_path/'features'
    for variant in a.DELAYS:
        d=root/variant;d.mkdir(parents=True)
        for n in a.SYMBOLS:(d/(n+'.parquet')).write_bytes(b'fixture')
    if extra=='third':(root/'other').mkdir()
    if extra=='extra_file':(root/'baseline'/'secret').write_bytes(b'fixture')
    if extra=='symlink':
        p=root/'baseline'/'BTCUSDT.parquet';p.unlink();p.symlink_to(root/'delayed'/'BTCUSDT.parquet')
    if extra=='wrongnative':(root/'baseline'/'1000PEPEUSDT.parquet').rename(root/'baseline'/'PEPEUSDT.parquet')
    with pytest.raises(AssertionError):a.feature_hashes(tmp_path)


def test_no_production_imports_and_git_anchor_full_identity():
    tree=ast.parse(Path(a.__file__).read_text())
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(n and (n.startswith('aster') or n.startswith('examples')) for n in imports)
    with pytest.raises(AssertionError):a.git_bytes('290c9b7','file')
    assert len(a.expected_sources('290c9b755290a382d696ac86f83a1fbec7ee1fe5'))==43
