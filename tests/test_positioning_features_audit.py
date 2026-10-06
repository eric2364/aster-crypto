"""Independent hand-constructed timing/unit cases; no historical sources."""
import numpy as np
import pandas as pd
import pytest
from examples.positioning_research import signals as s

START=pd.Timestamp('2025-10-05',tz='UTC');END=START+pd.Timedelta(hours=3)
IID='binance:perpetual:1000PEPEUSDT'


def source():
    p=pd.date_range(START,END,freq='min',inclusive='left');m=p[::5]
    bars=pd.DataFrame(dict(timestamp=p,instrument_id=IID,duration_seconds=60,close=np.full(len(p),100.)))
    metrics=pd.DataFrame(dict(timestamp=m,instrument_id=IID,sum_open_interest=np.full(len(m),1000.),
        sum_open_interest_value=np.full(len(m),100000.),source_create_time=[str(t.tz_localize(None)) for t in m],original_row_index=np.arange(len(m))))
    return bars,metrics


def build(b,m,**kw):return s.build_features(b,m,instrument_id=IID,start=START,end=END,**kw)


@pytest.mark.parametrize('delay,first',[ (6,7),(11,12)])
def test_hand_known_stock_changes_strict_clock_not_value_change(delay,first):
    b,m=source();m.loc[12,'sum_open_interest']=900.;m.loc[11,'sum_open_interest']=850.
    m.loc[12,'sum_open_interest_value']=1. # Never a predictor
    f=build(b,m,metric_delay_minutes=delay);clock=START+pd.Timedelta(minutes=60+first)
    assert f.loc[clock-pd.Timedelta(minutes=1),'metric_source_label']==START+pd.Timedelta(minutes=55)
    row=f.loc[clock]
    assert row.metric_source_label==START+pd.Timedelta(hours=1) and row.valid
    assert row.quantity_change_1h==pytest.approx(-.1)
    assert row.quantity_change_5m==pytest.approx(900/850-1)
    assert row.price_return_1h==row.price_return_15m==0
    assert row.metric_available_at<clock and row.price_available_at<=clock


def test_value_and_ratios_cannot_create_position_contraction():
    b,m=source();old=build(b,m)
    m.sum_open_interest_value=np.linspace(1e9,1.,len(m))
    for name in ('count_toptrader_long_short_ratio','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio'):m[name]=np.linspace(.01,100.,len(m))
    new=build(b,m);pd.testing.assert_frame_equal(old,new)
    assert new.loc[new.valid,'quantity_change_1h'].eq(0).all()


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_timestamp_precision_and_nonUTC_display_preserve_exact_grid(unit):
    b,m=source();old=build(b,m)
    for frame in (b,m):frame.timestamp=frame.timestamp.dt.tz_convert('Asia/Hong_Kong').dt.as_unit(unit)
    new=build(b,m);pd.testing.assert_frame_equal(old,new)


def test_past_label_but_unpublished_quantity_does_not_change_earlier_features():
    b,m=source();old=build(b,m);m.loc[11,'sum_open_interest']=1e12
    new=build(b,m);cut=START+pd.Timedelta(minutes=61)
    pd.testing.assert_frame_equal(old.loc[:cut],new.loc[:cut])
    assert old.loc[cut+pd.Timedelta(minutes=1),'native_open_interest']!=new.loc[cut+pd.Timedelta(minutes=1),'native_open_interest']


def test_prefix_and_future_price_quantity_mutations():
    b,m=source();old=build(b,m);cut=START+pd.Timedelta(hours=2)
    prefix=s.build_features(b[b.timestamp<cut],m[m.timestamp<cut],instrument_id=IID,start=START,end=cut)
    expected=old[old.index<cut].copy();expected.attrs=prefix.attrs
    pd.testing.assert_frame_equal(expected,prefix)
    b.loc[b.timestamp>=cut,'close']=3.;m.loc[m.timestamp>=cut,'sum_open_interest']=11.
    new=build(b,m);pd.testing.assert_frame_equal(old[old.index<=cut],new[new.index<=cut])


def test_constant_bundle_scale_cancels_but_one_time_unit_break_not_repaired():
    b,m=source();m.sum_open_interest=np.linspace(1000.,500.,len(m));old=build(b,m)
    m.sum_open_interest*=1000;scaled=build(b,m)
    for field in ('quantity_change_1h','quantity_change_5m'):np.testing.assert_allclose(old[field],scaled[field],equal_nan=True,atol=1e-15)
    m.loc[12:,'sum_open_interest']*=1000;broken=build(b,m)
    assert broken.loc[START+pd.Timedelta(minutes=67),'quantity_change_1h']>100


@pytest.mark.parametrize('kind',['quantity_1h','quantity_5m','price_1h','price_15m'])
def test_finite_source_can_overflow_derived_ratio_without_becoming_valid(kind):
    b,m=source()
    if kind=='quantity_1h':m.loc[0,'sum_open_interest']=1e-300;m.loc[12,'sum_open_interest']=1e300
    elif kind=='quantity_5m':m.loc[11,'sum_open_interest']=1e-300;m.loc[12,'sum_open_interest']=1e300
    elif kind=='price_1h':b.loc[5,'close']=1e-300;b.loc[65,'close']=1e300
    else:b.loc[50,'close']=1e-300;b.loc[65,'close']=1e300
    f=build(b,m);row=f.loc[START+pd.Timedelta(minutes=67)]
    field={'quantity_1h':'quantity_change_1h','quantity_5m':'quantity_change_5m','price_1h':'price_return_1h','price_15m':'price_return_15m'}[kind]
    assert pd.isna(row[field]) and not row.valid
    derived=['quantity_change_1h','quantity_change_5m','price_return_1h','price_return_15m']
    assert not np.isinf(f[derived].to_numpy()).any()


@pytest.mark.parametrize('kind',['bool_quantity','text_quantity','bool_price','receipt'])
def test_typed_archive_contract_cannot_accept_invented_numeric_or_receipt_semantics(kind):
    b,m=source()
    if kind=='bool_quantity':m.sum_open_interest=True
    elif kind=='text_quantity':m.sum_open_interest=m.sum_open_interest.astype(str)
    elif kind=='bool_price':b.close=True
    else:m['historical_receipt']=m.timestamp+pd.Timedelta(days=2)
    with pytest.raises(ValueError):build(b,m)


def test_source_labels_rows_inputs_and_declared_assumptions_preserved():
    b,m=source();b0=b.copy(deep=True);m0=m.copy(deep=True);f=build(b,m)
    pd.testing.assert_frame_equal(b,b0);pd.testing.assert_frame_equal(m,m0)
    for k,v in s.ASSUMPTIONS.items():assert f.attrs[k]==v
    assert 'not verified historical delivery' in f.attrs['vintage']
    assert f.metric_source_label.dropna().isin(m.timestamp).all()
    assert f.index.min()==START+pd.Timedelta(minutes=2) and f.index.max()==END-pd.Timedelta(minutes=1)
    assert not f[f.index<START+pd.Timedelta(minutes=67)].valid.any()


@pytest.mark.parametrize('kind',['duplicate_metric','missing_metric','outside_warmup','offgrid','wrong_bundle','float_delay'])
def test_exact_source_and_fixed_timing_fail_closed(kind):
    b,m=source();kw={}
    if kind=='duplicate_metric':m.loc[1,'timestamp']=m.loc[0,'timestamp']
    elif kind=='missing_metric':m=m.drop(index=12)
    elif kind=='outside_warmup':m=pd.concat([m.iloc[:1].assign(timestamp=START-pd.Timedelta(minutes=5)),m])
    elif kind=='offgrid':b.loc[10,'timestamp']+=pd.Timedelta(microseconds=1)
    elif kind=='wrong_bundle':m.instrument_id='binance:perpetual:PEPEUSDT'
    else:kw['metric_delay_minutes']=6.
    with pytest.raises(ValueError):build(b,m,**kw)
