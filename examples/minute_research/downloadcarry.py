"""Collect paired linear perpetual trade/mark/funding data for the fixed year.

First collect spot: .venv/bin/python examples/minute_research/download.py
Then collect perps: .venv/bin/python examples/minute_research/downloadcarry.py
Append --verify-only for pinned-cache validation without network/data writes.
Monthly raw archives can overlap the window; normalized bars contain only it.
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

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aster.backtest.models import Instrument
from aster.data.binance_public import download, fetch
from aster.data.validation import normalize_bars, normalize_funding
from examples.minute_research.download import (
    START, END, SYMBOLS, FUTURES, EXPECTED_ROWS, cached_path, check,
    read_json, save_json, sha256)


def catalog(root, verify_only):
    raw_path = root / 'exchange_info_current.json'
    records_path = root / 'instruments.json'
    source_path = root / 'instrument_source_manifest.json'
    flags = [p.exists() for p in (raw_path, records_path, source_path)]
    check(not any(flags) or all(flags), 'Incomplete perpetual instrument cache')
    if all(flags):
        raw = raw_path.read_bytes()
        check(sha256(raw_path) == read_json(source_path)['sha256'], 'Exchange-info hash mismatch')
        records = read_json(records_path)
    else:
        check(not verify_only, 'Perpetual instrument cache missing')
        url = 'https://fapi.binance.com/fapi/v1/exchangeInfo'
        raw = fetch(url)
        native = {x['symbol']: x for x in json.loads(raw)['symbols']}
        records = []
        for spot in SYMBOLS:
            item = native[FUTURES[spot]]
            filters = {x['filterType']: x for x in item['filters']}
            notional = filters.get('MIN_NOTIONAL', filters.get('NOTIONAL'))
            records.append(asdict(Instrument(
                id='binance:perpetual:' + item['symbol'], exchange='binance',
                symbol=item['symbol'], market_type='perpetual', base=item['baseAsset'],
                quote=item['quoteAsset'], multiplier=1,
                tick_size=float(filters['PRICE_FILTER']['tickSize']),
                lot_size=float(filters['LOT_SIZE']['stepSize']),
                min_quantity=float(filters['LOT_SIZE']['minQty']),
                min_notional=float(notional.get('notional', notional.get('minNotional'))))))
        raw_path.write_bytes(raw)
        save_json(records_path, records)
        save_json(source_path, {
            'source_url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'sha256': hashlib.sha256(raw).hexdigest(), 'historical_rules': False,
            'mapping': FUTURES,
            'note': 'Current tick/lot/minimums approximate historical specifications. '
                    'Fees, leverage maximum, maintenance and liquidation fields remain '
                    'configurable simulator assumptions, not verified account risk tiers.'})
    native = {x['symbol']: x for x in json.loads(raw)['symbols']}
    check(len(records) == len(SYMBOLS) and {x['symbol'] for x in records} == set(FUTURES.values()),
          'Wrong perpetual universe')
    instruments = {}
    for row in records:
        spec = Instrument(**row)
        item = native[spec.symbol]
        filters = {x['filterType']: x for x in item['filters']}
        notional = filters.get('MIN_NOTIONAL', filters.get('NOTIONAL'))
        check(spec.id == 'binance:perpetual:' + spec.symbol and spec.market_type == 'perpetual'
              and spec.base == item['baseAsset'] and spec.multiplier == 1,
              'Wrong perpetual identity/units')
        check(spec.tick_size == float(filters['PRICE_FILTER']['tickSize'])
              and spec.lot_size == float(filters['LOT_SIZE']['stepSize'])
              and spec.min_quantity == float(filters['LOT_SIZE']['minQty'])
              and spec.min_notional == float(notional.get('notional', notional.get('minNotional'))),
              'Instrument rules differ from pinned official response')
        instruments[spec.id] = spec
    mapping = {
        'mapping': [{'spot_symbol': s, 'source_futures_symbol': FUTURES[s],
                     'spot_instrument_id': 'binance:spot:' + s,
                     'perpetual_instrument_id': 'binance:perpetual:' + FUTURES[s],
                     'spot_base_units_per_perpetual_quantity_unit': 1000 if s == 'PEPEUSDT' else 1,
                     'perpetual_base_asset': native[FUTURES[s]]['baseAsset'], 'multiplier': 1}
                    for s in SYMBOLS],
        'quantity_rule': 'Perpetual 1 unit of 1000PEPE matches 1000 spot PEPE. '
                         'The engine multiplier stays 1; the source base asset is 1000PEPE.',
        'requested_start': START.isoformat(), 'requested_end_exclusive': END.isoformat()}
    mapping_path = root / 'cross_mapping.json'
    if mapping_path.exists():
        check(read_json(mapping_path)['mapping'] == mapping['mapping'], 'Cached hedge mapping differs')
    else:
        check(not verify_only, 'Cross mapping missing')
        save_json(mapping_path, mapping)
    return instruments


def verify(root, spot, instruments):
    folder = root / spot
    manifest = read_json(folder / 'source_manifest.json')
    check(pd.Timestamp(manifest['requested_start']) == START
          and pd.Timestamp(manifest['requested_end_exclusive']) == END
          and manifest['symbol'] == FUTURES[spot] and manifest['market'] == 'perpetual'
          and manifest['interval'] == '1m', 'Wrong cached perpetual source/range')
    check(sha256(folder / 'bars.parquet') == manifest['bars_sha256'], 'Perpetual Parquet hash mismatch')
    frame = pd.read_parquet(folder / 'bars.parquet')
    _, quality = normalize_bars(frame, instruments)
    grid = pd.date_range(START, END, freq='1min', inclusive='left')
    check(len(frame) == EXPECTED_ROWS and (pd.DatetimeIndex(frame.timestamp) == grid).all(),
          'Incomplete perpetual minute grid')
    check(frame.instrument_id.eq('binance:perpetual:' + FUTURES[spot]).all()
          and frame.duration_seconds.eq(60).all()
          and frame.end.eq(frame.timestamp + pd.Timedelta(minutes=1)).all(),
          'Wrong perpetual normalized identity/time')
    check({'mark_open', 'mark_price'} <= set(frame)
          and np.isfinite(frame[['mark_open', 'mark_price']]).all().all()
          and frame[['mark_open', 'mark_price']].gt(0).all().all()
          and not quality.errors and not quality.gaps, 'Invalid/missing independent marks')
    for entry in manifest['archives']:
        check(entry['url'].startswith('https://data.binance.vision/data/futures/um/')
              and entry['checksum_verified']
              and sha256(cached_path(entry['cache_file'])) == entry['sha256'],
              'Unverified perpetual/mark archive')
    funding = normalize_funding(pd.read_parquet(folder / 'funding.parquet'), instruments)
    check(len(funding) == manifest['funding_rows'] and len(funding) > 0
          and funding.instrument_id.eq('binance:perpetual:' + FUTURES[spot]).all()
          and funding.timestamp.ge(START).all() and funding.timestamp.le(END).all(),
          'Invalid perpetual funding identity/range')
    source_funding = []
    for page in manifest['funding_pages']:
        check(page['url'].startswith('https://fapi.binance.com/fapi/v1/fundingRate?')
              and sha256(cached_path(page['cache_file'])) == page['sha256'],
              'Invalid funding response hash')
        source_funding.extend(json.loads(cached_path(page['cache_file']).read_bytes()))
    original = pd.DataFrame({
        'timestamp': pd.to_datetime([int(x['fundingTime']) for x in source_funding], unit='ms', utc=True),
        'funding_rate': [float(x['fundingRate']) for x in source_funding],
        'mark_price': [float(x['markPrice']) for x in source_funding]})
    original = original[original.timestamp.ge(START) & original.timestamp.le(END)].sort_values('timestamp')
    check(len(original) == len(funding)
          and (pd.DatetimeIndex(original.timestamp) == pd.DatetimeIndex(funding.timestamp)).all()
          and np.array_equal(original[['funding_rate', 'mark_price']].to_numpy(),
                             funding[['funding_rate', 'mark_price']].to_numpy()),
          'Normalized funding differs from pinned original API responses')
    return {'spot_symbol': spot, 'futures_symbol': FUTURES[spot], 'rows': len(frame),
            'funding_rows': len(funding), 'minute_grid_exact': True,
            'independent_marks_present': True, 'official_checksums_verified': True,
            'funding_parquet_sha256': sha256(folder / 'funding.parquet'),
            'first_bar': str(frame.timestamp.iloc[0]), 'last_bar_end': str(frame.end.iloc[-1]),
            'spot_base_units_per_perpetual_quantity_unit': 1000 if spot == 'PEPEUSDT' else 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='data_cache/minute-perpetual-1y')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root = Path(args.out).resolve()
    check(root.exists() or not args.verify_only, 'Perpetual cache missing')
    root.mkdir(parents=True, exist_ok=True)
    instruments = catalog(root, args.verify_only)

    def collect(spot):
        folder = root / spot
        flags = [p.exists() for p in (folder / 'bars.parquet', folder / 'funding.parquet',
                                     folder / 'source_manifest.json')]
        check(not any(flags) or all(flags), f'Incomplete perpetual cache: {spot}')
        if not all(flags):
            check(not args.verify_only, f'Perpetual cache missing: {spot}')
            download(FUTURES[spot], '1m', START, END, folder, market='perpetual')
        report = verify(root, spot, instruments)
        print(f'{spot}/{FUTURES[spot]}: {report["rows"]} paired trade/mark bars; '
              f'{report["funding_rows"]} funding events', flush=True)
        return report

    reports = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(collect, s): s for s in SYMBOLS}
        for future in as_completed(futures):
            reports[futures[future]] = future.result()
    if not args.verify_only:
        save_json(root / 'coverage_report.json', {
            'start': START.isoformat(), 'end_exclusive': END.isoformat(),
            'instruments': [reports[s] for s in SYMBOLS],
            'total_trade_bars': sum(reports[s]['rows'] for s in SYMBOLS),
            'total_mark_bars': sum(reports[s]['rows'] for s in SYMBOLS),
            'outer_workers': args.workers, 'internal_daily_fallback_workers_per_symbol': 4,
            'funding_terminal_boundary': 'A settlement exactly at END is retained for terminal valuation.',
            'no_interpolation': True, 'verified_cache_is_pinned': True})
    print('Verified paired one-year perpetual data:', root, flush=True)


if __name__ == '__main__':
    main()
