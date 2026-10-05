"""Collect the fixed last-year research universe from official public sources.

Run: .venv/bin/python examples/minute_research/download.py
Verify existing files without network/writes: append --verify-only.
No credentials, trade endpoints, interpolated bars or older warmup observations.
Existing verified files are pinned; remove a symbol's outputs to reacquire it.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.parse

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aster.backtest.models import Instrument
from aster.data.binance_public import download, fetch, funding_history
from aster.data.validation import normalize_bars

START = pd.Timestamp('2025-10-05', tz='UTC')
END = pd.Timestamp('2026-10-05', tz='UTC')
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'DOGEUSDT', 'PEPEUSDT',
           'SOLUSDT', 'XRPUSDT', 'LINKUSDT', 'ADAUSDT']
FUTURES = {s: '1000PEPEUSDT' if s == 'PEPEUSDT' else s for s in SYMBOLS}
EXPECTED_ROWS = int((END - START).total_seconds() / 60)


def read_json(path):
    return json.loads(Path(path).read_text())


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cached_path(path):
    """Manifest paths from the original collector were relative to repo root."""
    path = Path(path)
    if path.exists():
        return path
    repository_path = Path(__file__).resolve().parents[2] / path
    if repository_path.exists():
        return repository_path
    raise ValueError(f'Missing original source file: {path}')


def check(condition, message):
    if not condition:
        raise ValueError(message)


def instrument_catalog(root, verify_only):
    catalog_path = root / 'instruments.json'
    provenance_path = root / 'instrument_source_manifest.json'
    raw_path = root / 'exchange_info_current.json'
    exists = [p.exists() for p in (catalog_path, provenance_path, raw_path)]
    if any(exists) and not all(exists):
        raise ValueError('Incomplete instrument cache; restore/remove its three files')
    if all(exists):
        provenance = read_json(provenance_path)
        check(sha256(raw_path) == provenance['sha256'], 'Exchange-info hash mismatch')
        raw = json.loads(raw_path.read_bytes())
        records = read_json(catalog_path)
    else:
        if verify_only:
            raise ValueError('Instrument cache is missing')
        query = urllib.parse.urlencode({'symbols': json.dumps(SYMBOLS, separators=(',', ':'))})
        url = 'https://data-api.binance.vision/api/v3/exchangeInfo?' + query
        payload = fetch(url)
        raw = json.loads(payload)
        records = []
        for item in raw['symbols']:
            filters = {x['filterType']: x for x in item['filters']}
            notional = filters.get('NOTIONAL', filters.get('MIN_NOTIONAL'))
            records.append(asdict(Instrument(
                id='binance:spot:' + item['symbol'], exchange='binance',
                symbol=item['symbol'], market_type='spot', base=item['baseAsset'],
                quote=item['quoteAsset'], tick_size=float(filters['PRICE_FILTER']['tickSize']),
                lot_size=float(filters['LOT_SIZE']['stepSize']),
                min_quantity=float(filters['LOT_SIZE']['minQty']),
                min_notional=float(notional['minNotional']))))
        provenance = {
            'source_url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'sha256': hashlib.sha256(payload).hexdigest(), 'historical_rules': False,
            'universe': SYMBOLS,
            'note': 'Current official instrument rules approximate the historical period. '
                    'Fee defaults are simulator assumptions, not verified account tiers. '
                    'LOT_SIZE imported; raw MARKET_LOT_SIZE and dynamic price filters '
                    'are retained but not exhaustively reproduced by the engine.'}
        raw_path.write_bytes(payload)
        save_json(catalog_path, records)
        save_json(provenance_path, provenance)
    check(len(records) == len(SYMBOLS) and {x['symbol'] for x in records} == set(SYMBOLS),
          'Instrument universe differs from the fixed research universe')
    native = {x['symbol']: x for x in raw['symbols']}
    catalog = {}
    for row in records:
        spec = Instrument(**row)
        item = native[spec.symbol]
        filters = {x['filterType']: x for x in item['filters']}
        notional = filters.get('NOTIONAL', filters.get('MIN_NOTIONAL'))
        check(spec.id == 'binance:spot:' + spec.symbol and spec.market_type == 'spot'
              and spec.exchange == 'binance', 'Wrong catalog instrument identity')
        check(spec.tick_size == float(filters['PRICE_FILTER']['tickSize'])
              and spec.lot_size == float(filters['LOT_SIZE']['stepSize'])
              and spec.min_quantity == float(filters['LOT_SIZE']['minQty'])
              and spec.min_notional == float(notional['minNotional']),
              f'Catalog rules differ from pinned official response: {spec.symbol}')
        catalog[spec.id] = spec
    return catalog


def verify_bars(root, symbol, catalog):
    folder = root / symbol
    path = folder / 'bars.parquet'
    manifest = read_json(folder / 'source_manifest.json')
    check(pd.Timestamp(manifest['requested_start']) == START and
          pd.Timestamp(manifest['requested_end_exclusive']) == END,
          f'Cached range differs: {symbol}')
    check(manifest['symbol'] == symbol and manifest['interval'] == '1m'
          and manifest['market'] == 'spot', f'Wrong bar source identity: {symbol}')
    check(sha256(path) == manifest['bars_sha256'], f'Parquet hash mismatch: {symbol}')
    frame = pd.read_parquet(path)
    _, quality = normalize_bars(frame, catalog)
    grid = pd.date_range(START, END, freq='1min', inclusive='left')
    check(len(frame) == EXPECTED_ROWS and
          (pd.DatetimeIndex(frame.timestamp) == grid).all(),
          f'Incomplete/unsorted minute grid: {symbol}')
    check(frame.instrument_id.eq('binance:spot:' + symbol).all()
          and frame.duration_seconds.eq(60).all(), f'Wrong normalized identity: {symbol}')
    check((frame.end == frame.timestamp + pd.Timedelta(minutes=1)).all(),
          f'Wrong exclusive candle end: {symbol}')
    check(not quality.errors and not quality.gaps, f'Invalid candle data: {symbol}')
    check(bool(manifest['archives']), f'Missing archive provenance: {symbol}')
    for entry in manifest['archives']:
        check(entry['url'].startswith('https://data.binance.vision/data/spot/')
              and entry['checksum_verified'], f'Unofficial/unverified archive: {symbol}')
        check(sha256(cached_path(entry['cache_file'])) == entry['sha256'],
              f'Raw archive hash mismatch: {symbol}')
    return {
        'symbol': symbol, 'rows': len(frame), 'first_bar_start': str(frame.timestamp.iloc[0]),
        'last_bar_start': str(frame.timestamp.iloc[-1]), 'last_bar_end': str(frame.end.iloc[-1]),
        'minute_grid_exact': True, 'zero_volume_rows': int(frame.volume.eq(0).sum()),
        'archived_files': len(manifest['archives']), 'official_checksums_verified': True,
        'parquet_sha256_verified': True, 'bars_bytes': path.stat().st_size}


def collect_funding(root, symbol, verify_only):
    folder = root / 'funding'
    folder.mkdir(parents=True, exist_ok=True)
    path, metadata_path = folder / (symbol + '.parquet'), folder / (symbol + '_manifest.json')
    check(path.exists() == metadata_path.exists(), f'Incomplete funding cache: {symbol}')
    if not path.exists():
        if verify_only:
            raise ValueError(f'Funding cache missing: {symbol}')
        frame, pages = funding_history(FUTURES[symbol], START, END, folder / 'raw' / symbol)
        frame = frame[(frame.timestamp >= START) & (frame.timestamp < END)].copy()
        frame['source_instrument_id'] = frame.instrument_id
        frame['spot_instrument_id'] = 'binance:spot:' + symbol
        frame['spot_symbol'] = symbol
        frame['source_futures_symbol'] = FUTURES[symbol]
        frame['available_at'] = frame.timestamp
        frame['source_base_units_per_contract'] = 1000 if symbol == 'PEPEUSDT' else 1
        check(len(frame) > 0, f'No historical funding: {symbol}')
        frame.to_parquet(path, index=False)
        intervals = frame.timestamp.diff().dropna().dt.total_seconds() / 3600
        metadata = {
            'source': 'Official Binance USD-M funding history API',
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'requested_start': START.isoformat(), 'requested_end_exclusive': END.isoformat(),
            'source_futures_symbol': FUTURES[symbol],
            'source_instrument_id': 'binance:perpetual:' + FUTURES[symbol],
            'spot_symbol': symbol, 'spot_instrument_id': 'binance:spot:' + symbol,
            'source_base_units_per_contract': 1000 if symbol == 'PEPEUSDT' else 1,
            'rows': len(frame), 'first_timestamp': frame.timestamp.iloc[0].isoformat(),
            'last_timestamp': frame.timestamp.iloc[-1].isoformat(),
            'observed_interval_hours': sorted(intervals.unique().tolist()),
            'nominal_observed_interval_hours': sorted(set(np.round(intervals, 4).tolist())),
            'interval_counts': {str(k): int(v) for k, v in intervals.value_counts().items()},
            'pages': pages, 'parquet_sha256': sha256(path),
            'predictor_only': True, 'spot_cash_flow': False,
            'availability_policy': 'Realized rate becomes visible at original fundingTime; '
                                   'zero publication delay is an explicit approximation.',
            'coverage_policy': 'No fixed cadence or pre-start warmup synthesized. '
                               'Before the first settlement the predictor remains missing.',
            'source_mark_units': 'Futures quote price; 1000PEPEUSDT is per 1000 PEPE. '
                                 'Never silently attach this raw mark to spot prices.',
            'current_instrument_rules_approximation': True}
        save_json(metadata_path, metadata)
    metadata = read_json(metadata_path)
    frame = pd.read_parquet(path)
    check(pd.Timestamp(metadata['requested_start']) == START and
          pd.Timestamp(metadata['requested_end_exclusive']) == END,
          f'Cached funding range differs: {symbol}')
    check(sha256(path) == metadata['parquet_sha256'], f'Funding Parquet hash mismatch: {symbol}')
    check(len(frame) > 0 and frame.timestamp.is_unique and frame.timestamp.is_monotonic_increasing,
          f'Invalid funding chronology: {symbol}')
    check(frame.timestamp.ge(START).all() and frame.timestamp.lt(END).all()
          and frame.available_at.eq(frame.timestamp).all(), f'Funding availability/bounds: {symbol}')
    check(frame.spot_instrument_id.eq('binance:spot:' + symbol).all()
          and frame.source_instrument_id.eq('binance:perpetual:' + FUTURES[symbol]).all(),
          f'Wrong funding identity mapping: {symbol}')
    check(np.isfinite(frame[['funding_rate', 'mark_price']]).all().all()
          and frame.mark_price.gt(0).all(), f'Invalid rate/source mark: {symbol}')
    check(bool(metadata['pages']), f'Missing API provenance: {symbol}')
    for page in metadata['pages']:
        check(page['url'].startswith('https://fapi.binance.com/fapi/v1/fundingRate?')
              and sha256(cached_path(page['cache_file'])) == page['sha256'],
              f'Invalid funding response/hash: {symbol}')
    return {'spot_symbol': symbol, 'rows': len(frame),
            'first': frame.timestamp.iloc[0].isoformat(), 'last': frame.timestamp.iloc[-1].isoformat(),
            'nominal_observed_interval_hours': sorted(set(np.round(
                frame.timestamp.diff().dropna().dt.total_seconds() / 3600, 4).tolist()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='data_cache/minute-1y')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root = Path(args.out).resolve()
    check(root.exists() or not args.verify_only, 'Cache directory missing')
    root.mkdir(parents=True, exist_ok=True)
    catalog = instrument_catalog(root, args.verify_only)
    began = time.perf_counter()

    def collect(symbol):
        folder = root / symbol
        check((folder / 'bars.parquet').exists() == (folder / 'source_manifest.json').exists(),
              f'Incomplete bar cache: {symbol}')
        if not (folder / 'bars.parquet').exists():
            if args.verify_only:
                raise ValueError(f'Bar cache missing: {symbol}')
            download(symbol, '1m', START, END, folder, market='spot')
        bars = verify_bars(root, symbol, catalog)
        funding = collect_funding(root, symbol, args.verify_only)
        print(f'{symbol}: {bars["rows"]} exact minute bars; {funding["rows"]} funding observations', flush=True)
        return bars, funding

    reports = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(collect, s): s for s in SYMBOLS}
        for future in as_completed(futures):
            reports[futures[future]] = future.result()
    if not args.verify_only:
        save_json(root / 'coverage_report.json', {
            'range_start': START.isoformat(), 'range_end_exclusive': END.isoformat(),
            'total_rows': sum(reports[s][0]['rows'] for s in SYMBOLS),
            'instruments': [reports[s][0] for s in SYMBOLS]})
        save_json(root / 'collector_manifest.json', {
            'start': START.isoformat(), 'end_exclusive': END.isoformat(), 'universe': SYMBOLS,
            'funding_mapping': FUTURES, 'outer_symbol_concurrency': args.workers,
            'existing_downloader_daily_fallback_workers': 4,
            'concurrency_note': 'Each symbol can use four internal daily archive fallback workers.',
            'no_interpolation': True, 'verified_cache_is_pinned': True,
            'elapsed_seconds': time.perf_counter() - began, 'funding_predictor_only': True,
            'sources': [reports[s][1] for s in SYMBOLS]})
    print('Verified fixed one-year universe:', root, flush=True)


if __name__ == '__main__':
    main()
