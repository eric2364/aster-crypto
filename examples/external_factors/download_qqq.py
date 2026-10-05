"""Acquire one fixed year of unadjusted QQQ daily closes from Yahoo Finance.

This is an end-of-day vendor series, not a verified historical intraday feed.
Availability is conservatively assumed at the next UTC midnight. Raw vendor
timestamps label sessions; they do not establish historical delivery latency.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import pandas as pd
import numpy as np

START = pd.Timestamp('2025-10-05', tz='UTC')
END = pd.Timestamp('2026-10-05', tz='UTC')
URL = (f'https://query1.finance.yahoo.com/v8/finance/chart/QQQ?period1={int(START.timestamp())}'
       f'&period2={int(END.timestamp())}&interval=1d&events=div%2Csplits')

# Pinned full-day closures applicable to this exact research window. Early
# closing sessions are included. This is not a general future calendar service.
CALENDAR = {
    'coverage_start': str(START), 'coverage_end_exclusive': str(END),
    'full_day_closures': ['2025-11-27', '2025-12-25', '2026-01-01',
                          '2026-01-19', '2026-02-16', '2026-04-03',
                          '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07'],
    'official_sources': [
        'https://www.nasdaq.com/docs/2025/01/06/2025holidayandtradinghours.pdf',
        'https://nasdaqtrader.com/Trader.aspx?id=Calendar'],
    'assumptions': 'Weekdays minus published full-day closures; early closes included; no unscheduled closure assumed; vendor labels must be 09:30 America/New_York',
}


def expected_session_dates() -> list[str]:
    days = pd.date_range(START.normalize(), END.normalize(), freq='B', inclusive='left')
    return [day.strftime('%Y-%m-%d') for day in days
            if day.strftime('%Y-%m-%d') not in CALENDAR['full_day_closures']]


def normalize(raw: bytes) -> pd.DataFrame:
    payload = json.loads(raw)
    if payload['chart'].get('error') is not None:
        raise ValueError('Vendor returned a chart error')
    series = payload['chart']['result']
    if len(series) != 1:
        raise ValueError('Expected one QQQ series')
    series = series[0]
    metadata = series['meta']
    if (metadata['symbol'], metadata['instrumentType'], metadata['currency']) != ('QQQ', 'ETF', 'USD'):
        raise ValueError('QQQ ETF identity and USD quote required')
    if metadata['exchangeTimezoneName'] != 'America/New_York':
        raise ValueError('Expected a New York session timezone')
    if series.get('events', {}).get('splits'):
        raise ValueError('A split needs separately dated unit handling before signals can be built')
    quote = series['indicators']['quote'][0]
    sessions = pd.to_datetime(series['timestamp'], unit='s', utc=True)
    frame = pd.DataFrame({'source_timestamp': sessions, 'close': quote['close'],
                          'volume': quote['volume']})
    if not frame.source_timestamp.is_unique or not frame.source_timestamp.is_monotonic_increasing:
        raise ValueError('Unique chronological vendor observations required')
    if not frame.source_timestamp.between(START, END, inclusive='left').all():
        raise ValueError('Real observations must remain within the requested one-year window')
    if not np.isfinite(frame[['close', 'volume']]).all().all() or not (frame.close > 0).all() or not (frame.volume >= 0).all():
        raise ValueError('Finite positive closes and nonnegative actual volume required')
    local = frame.source_timestamp.dt.tz_convert('America/New_York')
    if not ((local.dt.hour == 9) & (local.dt.minute == 30) &
            (local.dt.second == 0) & (local.dt.microsecond == 0)).all():
        raise ValueError('Vendor daily session labels must be exactly 09:30 America/New_York')
    dates = local.dt.strftime('%Y-%m-%d')
    frame['session_date'] = dates
    if dates.duplicated().any() or (frame.source_timestamp.dt.tz_convert('America/New_York').dt.dayofweek >= 5).any():
        raise ValueError('One observation per weekday session required')
    expected = set(expected_session_dates())
    actual = set(dates)
    if actual != expected:
        raise ValueError(f'Incomplete Nasdaq session calendar: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}')
    frame['available_at'] = pd.to_datetime(dates, utc=True) + pd.Timedelta(days=1)
    for name in ['source_timestamp', 'available_at']:
        frame[name] = frame[name].dt.as_unit('ns')
    if not (frame.available_at > frame.source_timestamp).all() or not (frame.available_at < END).all():
        raise ValueError('Availability must follow observation and remain inside the research window')
    frame['instrument_id'] = 'yahoo:etf:QQQ'
    frame['price_basis'] = 'vendor unadjusted quote.close; adjclose deliberately unused'
    frame['availability_basis'] = 'assumed next UTC midnight; original vendor receipt not observed'
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='data_cache/external-factors-1y/qqq')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root = Path(args.out)
    raw_path = root/'raw_chart.json'
    manifest_path = root/'source_manifest.json'
    if args.verify_only:
        manifest = json.loads(manifest_path.read_text())
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest['raw_sha256']:
            raise ValueError('Pinned vendor response changed')
    else:
        root.mkdir(parents=True, exist_ok=True)
        if raw_path.exists():
            raw = raw_path.read_bytes()
            if manifest_path.exists():
                previous = json.loads(manifest_path.read_text())
                if hashlib.sha256(raw).hexdigest() != previous['raw_sha256']:
                    raise ValueError('Pinned vendor response changed')
        else:
            request = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            raw_path.write_bytes(raw)
    frame = normalize(raw)
    if args.verify_only:
        if manifest.get('calendar') != CALENDAR or manifest.get('url') != URL or manifest.get('start') != str(START) or manifest.get('end_exclusive') != str(END):
            raise ValueError('Pinned calendar or source/window provenance changed')
        stored = pd.read_parquet(root/'observations.parquet')
        pd.testing.assert_frame_equal(frame, stored)
        if hashlib.sha256((root/'observations.parquet').read_bytes()).hexdigest() != manifest['normalized_sha256']:
            raise ValueError('Normalized vendor observations changed')
    else:
        frame.to_parquet(root/'observations.parquet', index=False)
        manifest = {'source': 'Yahoo Finance vendor chart; not an official exchange tape', 'url': URL,
                    'start': str(START), 'end_exclusive': str(END), 'observations': len(frame),
                    'raw_sha256': hashlib.sha256(raw).hexdigest(),
                    'normalized_sha256': hashlib.sha256((root/'observations.parquet').read_bytes()).hexdigest(),
                    'first_session': frame.session_date.iloc[0], 'last_session': frame.session_date.iloc[-1],
                    'calendar': CALENDAR,
                    'availability': 'assumed next UTC midnight; original historical delivery time unavailable',
                    'price_basis': 'unadjusted quote.close; dividends not retroactively applied; splits reject',
                    'retrieved_at': str(pd.Timestamp.now(tz='UTC')),
                    'limitations': ['historical vendor corrections/vintages unverified', 'no intraday QQQ lead claim',
                                    'weekends and holidays remain absent; no synthesized sessions',
                                    'research uses only source dates in the fixed year']}
        manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'QQQ: {len(frame)} actual daily observations; identity/range/availability checks passed.')


if __name__ == '__main__':
    main()
