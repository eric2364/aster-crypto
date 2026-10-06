import numpy as np
import pandas as pd
import pytest
from examples.positioning_research.signals import build_features

IID = 'binance:perpetual:1000PEPEUSDT'
START = pd.Timestamp('2025-10-05', tz='UTC')
END = START + pd.Timedelta(hours=3)


def data():
    p = pd.date_range(START, END, freq='min', inclusive='left')
    m = pd.date_range(START, END, freq='5min', inclusive='left')
    bars = pd.DataFrame({'timestamp': p, 'instrument_id': IID,
                         'duration_seconds': 60, 'close': np.exp(np.arange(len(p))/1000)})
    metrics = pd.DataFrame({'timestamp': m, 'instrument_id': IID,
                            'sum_open_interest': 1000 * np.exp(-np.arange(len(m))/100)})
    return bars, metrics


def build(b, m, **kwargs):
    return build_features(b, m, instrument_id=IID, start=START, end=END, **kwargs)


def test_strict_availability_and_actual_source_labels():
    b, m = data(); f = build(b, m)
    assert pd.isna(f.loc[START + pd.Timedelta(minutes=6), 'metric_source_label'])
    assert f.loc[START + pd.Timedelta(minutes=7), 'metric_source_label'] == START
    assert not f.loc[START + pd.Timedelta(minutes=66), 'valid']
    row = f.loc[START + pd.Timedelta(minutes=67)]
    assert row.valid
    assert row.metric_source_label == START + pd.Timedelta(hours=1)
    assert row.price_source_label == START + pd.Timedelta(minutes=65)
    assert row.quantity_change_1h == pytest.approx(np.exp(-.12)-1)
    assert row.quantity_change_5m == pytest.approx(np.exp(-.01)-1)
    assert row.price_return_1h == pytest.approx(np.exp(.06)-1)
    assert row.price_return_15m == pytest.approx(np.exp(.015)-1)


def test_longer_delay_is_fixed_sensitivity_and_no_future():
    b, m = data(); f = build(b, m, metric_delay_minutes=11)
    assert not f.loc[START + pd.Timedelta(minutes=71), 'valid']
    assert f.loc[START + pd.Timedelta(minutes=72), 'valid']
    assert (f.metric_available_at.dropna() < f.index[f.metric_available_at.notna()]).all()


def test_future_source_perturbations_leave_prior_features_unchanged():
    b, m = data(); original = build(b, m)
    cutoff = START + pd.Timedelta(minutes=90)
    b.loc[b.timestamp >= cutoff, 'close'] *= 7
    m.loc[m.timestamp >= cutoff, 'sum_open_interest'] *= 11
    modified = build(b, m)
    pd.testing.assert_frame_equal(original.loc[:cutoff], modified.loc[:cutoff])


def test_native_constant_scaling_changes_levels_not_returns():
    b, m = data(); old = build(b, m)
    b.close *= 1000; m.sum_open_interest *= .001
    new = build(b, m)
    for key in ('price_return_1h', 'price_return_15m', 'quantity_change_1h', 'quantity_change_5m'):
        np.testing.assert_allclose(old[key], new[key], equal_nan=True, atol=1e-15)
    assert old.valid.equals(new.valid)


@pytest.mark.parametrize('kind', ['missing_price', 'missing_metric', 'duplicate', 'unordered',
                                 'outside', 'native', 'nan', 'zero', 'duration', 'naive'])
def test_bad_sources_fail_closed(kind):
    b, m = data()
    if kind == 'missing_price': b = b.iloc[1:]
    elif kind == 'missing_metric': m = m.iloc[1:]
    elif kind == 'duplicate': m.loc[1, 'timestamp'] = m.loc[0, 'timestamp']
    elif kind == 'unordered': m = m.iloc[::-1]
    elif kind == 'outside': m.loc[0, 'timestamp'] -= pd.Timedelta(minutes=5)
    elif kind == 'native': m.loc[0, 'instrument_id'] = 'binance:perpetual:PEPEUSDT'
    elif kind == 'nan': m.loc[0, 'sum_open_interest'] = np.nan
    elif kind == 'zero': b.loc[0, 'close'] = 0
    elif kind == 'duration': b.loc[0, 'duration_seconds'] = 300
    elif kind == 'naive': m.timestamp = m.timestamp.dt.tz_localize(None)
    with pytest.raises(ValueError): build(b, m)


@pytest.mark.parametrize('delay', [0, 5, 7, True])
def test_unregistered_latency_fails(delay):
    b, m = data()
    with pytest.raises(ValueError): build(b, m, metric_delay_minutes=delay)
