"""Offline vendor provenance and exact-session completeness regressions."""
import copy
import hashlib
import json
import sys

import pandas as pd
import pytest

from examples.external_factors import download_qqq as q


@pytest.fixture
def payload():
    # Independent fixture calendar, including early-close sessions.
    closed = {'2025-11-27', '2025-12-25', '2026-01-01', '2026-01-19',
              '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19',
              '2026-07-03', '2026-09-07'}
    dates = [d for d in pd.date_range('2025-10-05', '2026-10-04', freq='B')
             if d.strftime('%Y-%m-%d') not in closed]
    stamps = [(d + pd.Timedelta(hours=9, minutes=30)).tz_localize('America/New_York')
              for d in dates]
    series = {'meta': {'symbol': 'QQQ', 'instrumentType': 'ETF', 'currency': 'USD',
                      'exchangeTimezoneName': 'America/New_York'},
              'timestamp': [int(d.timestamp()) for d in stamps],
              'indicators': {'quote': [{'close': [100.+i/100 for i in range(len(dates))],
                                        'volume': [1000]*len(dates)}],
                             'adjclose': [{'adjclose': [999999]*len(dates)}]}}
    return {'chart': {'error': None, 'result': [series]}}


def raw(payload):
    return json.dumps(payload).encode()


def test_exact_calendar_dst_publication_and_adjusted_future_unused(payload):
    frame = q.normalize(raw(payload))
    assert len(frame) == 250
    assert {'2025-11-28', '2025-12-24'} <= set(frame.session_date)
    assert frame.source_timestamp.dt.hour.nunique() == 2  # DST UTC labels differ.
    assert str(frame.available_at.dtype) == 'datetime64[ns, UTC]'
    assert (frame.available_at > frame.source_timestamp).all()
    assert frame.available_at.iloc[0] == pd.Timestamp('2025-10-07', tz='UTC')
    revised = copy.deepcopy(payload)
    revised['chart']['result'][0]['indicators']['adjclose'][0]['adjclose'] = [-1]*250
    pd.testing.assert_frame_equal(frame, q.normalize(raw(revised)))


@pytest.mark.parametrize('defect', ['missing', 'holiday', 'extra', 'bad_minute', 'bad_second',
                                   'milliseconds', 'split', 'currency', 'nan'])
def test_rejects_bad_source(payload, defect):
    s = payload['chart']['result'][0]
    if defect == 'missing':
        s['timestamp'].pop(20)
        for values in s['indicators']['quote'][0].values():
            values.pop(20)
    elif defect == 'holiday':
        # Same row count, replacing a valid session with closed Thanksgiving.
        i = next(i for i, ts in enumerate(s['timestamp'])
                 if pd.Timestamp(ts, unit='s', tz='UTC').strftime('%Y-%m-%d') == '2025-11-26')
        s['timestamp'][i] = int(pd.Timestamp('2025-11-27 09:30', tz='America/New_York').timestamp())
    elif defect == 'extra':
        s['timestamp'].append(int(pd.Timestamp('2026-10-05 09:30', tz='America/New_York').timestamp()))
        for values in s['indicators']['quote'][0].values():
            values.append(1000)
    elif defect in ('bad_minute', 'bad_second'):
        s['timestamp'][0] += 60 if defect == 'bad_minute' else 1
    elif defect == 'milliseconds':
        s['timestamp'] = [ts*1000 for ts in s['timestamp']]
    elif defect == 'split':
        s['events'] = {'splits': {'a': {'numerator': 2, 'denominator': 1}}}
    elif defect == 'currency':
        s['meta']['currency'] = 'HKD'
    elif defect == 'nan':
        s['indicators']['quote'][0]['close'][0] = float('nan')
    with pytest.raises((ValueError, OverflowError, pd.errors.OutOfBoundsDatetime)):
        q.normalize(raw(payload))


def seed_cache(tmp_path, payload, monkeypatch):
    (tmp_path/'raw_chart.json').write_bytes(raw(payload))
    monkeypatch.setattr(q.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('Network forbidden'))
    monkeypatch.setattr(sys, 'argv', ['qqq', '--out', str(tmp_path)])
    q.main()
    return tmp_path/'source_manifest.json'


def test_cached_roundtrip_and_raw_tamper_fail_closed(tmp_path, payload, monkeypatch):
    manifest_path = seed_cache(tmp_path, payload, monkeypatch)
    manifest = json.loads(manifest_path.read_text())
    assert manifest['calendar']['official_sources'] == q.CALENDAR['official_sources']
    original = q.normalize(raw(payload))
    pd.testing.assert_frame_equal(original, pd.read_parquet(tmp_path/'observations.parquet'))
    monkeypatch.setattr(sys, 'argv', ['qqq', '--out', str(tmp_path), '--verify-only'])
    q.main()
    (tmp_path/'raw_chart.json').write_bytes(raw(payload)+b' ')
    with pytest.raises(ValueError, match='Pinned vendor response changed'):
        q.main()
    monkeypatch.setattr(sys, 'argv', ['qqq', '--out', str(tmp_path)])
    with pytest.raises(ValueError, match='Pinned vendor response changed'):
        q.main()


@pytest.mark.parametrize('tamper', ['parquet_bytes', 'semantic_rehash', 'calendar'])
def test_normalized_and_calendar_tamper_rejected(tmp_path, payload, monkeypatch, tamper):
    manifest_path = seed_cache(tmp_path, payload, monkeypatch)
    manifest = json.loads(manifest_path.read_text())
    parquet = tmp_path/'observations.parquet'
    if tamper == 'calendar':
        manifest['calendar']['full_day_closures'].pop()
        manifest_path.write_text(json.dumps(manifest))
    elif tamper == 'parquet_bytes':
        parquet.write_bytes(parquet.read_bytes()+b'changed')
    else:
        frame = pd.read_parquet(parquet)
        frame.loc[0, 'close'] *= 2
        frame.to_parquet(parquet, index=False)
        manifest['normalized_sha256'] = hashlib.sha256(parquet.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(sys, 'argv', ['qqq', '--out', str(tmp_path), '--verify-only'])
    with pytest.raises((ValueError, AssertionError, OSError)):
        q.main()
