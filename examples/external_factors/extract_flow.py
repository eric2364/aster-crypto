"""Recover authentic minute taker-buy volume from already verified futures ZIPs.

No network requests, extra assets, interpolation, or changes to Engine input.
This is aggregate aggressive trade flow, not limit-order-book OFI or depth.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from urllib.parse import urlparse
import numpy as np
import pandas as pd

START = pd.Timestamp('2025-10-05', tz='UTC')
END = pd.Timestamp('2026-10-05', tz='UTC')
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'DOGEUSDT', 'PEPEUSDT', 'SOLUSDT', 'XRPUSDT', 'LINKUSDT', 'ADAUSDT']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract(source_root, output_root, symbol, verify_only=False):
    source = Path(source_root)/symbol
    output = Path(output_root)/symbol
    original = json.loads((source/'source_manifest.json').read_text())
    native_symbol = '1000PEPEUSDT' if symbol == 'PEPEUSDT' else symbol
    expected_iid = f'binance:perpetual:{native_symbol}'
    if original.get('symbol') != native_symbol or original.get('market') != 'perpetual' or original.get('interval') != '1m':
        raise ValueError('Requested native perpetual symbol and one-minute source required')
    chunks = []
    archives = []
    for item in original['archives']:
        # The original manifest also includes valuation-only markPriceKlines.
        # Aggressive trade volume must come solely from actual trade klines.
        if '/klines/' not in item['url']:
            continue
        address = urlparse(item['url'])
        allowed = [f'/data/futures/um/{period}/klines/{native_symbol}/1m/' for period in ['daily', 'monthly']]
        if address.scheme != 'https' or address.netloc != 'data.binance.vision' or not any(address.path.startswith(prefix) for prefix in allowed):
            raise ValueError('Official native-symbol USD-M minute trade archive required')
        filename = address.path.rsplit('/', 1)[-1]
        if not filename.startswith(native_symbol+'-1m-') or not filename.endswith('.zip'):
            raise ValueError('Native trade archive filename identity mismatch')
        path = Path(item['cache_file'])
        if not item['checksum_verified'] or digest(path) != item['sha256']:
            raise ValueError('Original publisher-verified archive identity changed')
        with zipfile.ZipFile(path) as archive:
            csvs = [name for name in archive.namelist() if name.endswith('.csv')]
            if len(csvs) != 1:
                raise ValueError('Expected one official futures kline CSV')
            with archive.open(csvs[0]) as handle:
                frame = pd.read_csv(handle, usecols=['open_time', 'close_time', 'volume', 'taker_buy_volume', 'count'])
        frame['timestamp'] = pd.to_datetime(frame.open_time, unit='ms', utc=True).dt.as_unit('ns')
        frame = frame[(frame.timestamp >= START) & (frame.timestamp < END)].copy()
        if not (pd.to_numeric(frame.close_time) == frame.open_time + 59999).all():
            raise ValueError('Official minute duration/timestamp convention changed')
        chunks.append(frame)
        archives.append({key: item[key] for key in ['url', 'checksum_url', 'sha256', 'checksum_verified']})
    frame = pd.concat(chunks, ignore_index=True).sort_values('timestamp').reset_index(drop=True)
    expected = pd.date_range(START, END, freq='min', inclusive='left').as_unit('ns')
    if not frame.timestamp.is_unique or not pd.DatetimeIndex(frame.timestamp).equals(expected):
        raise ValueError('Exact continuous one-year minute observations required')
    numeric = frame[['volume', 'taker_buy_volume', 'count']].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (numeric < 0).any():
        raise ValueError('Finite nonnegative observed volumes/counts required')
    tolerance = np.maximum(1e-8, frame.volume.to_numpy()*1e-12)
    if (frame.taker_buy_volume.to_numpy() > frame.volume.to_numpy()+tolerance).any():
        raise ValueError('Aggressive buy volume cannot exceed total traded base volume')
    if not (frame['count'] == np.floor(frame['count'])).all():
        raise ValueError('Actual integer trade counts required')
    bars_path = source/'bars.parquet'
    bars = pd.read_parquet(bars_path, columns=['timestamp', 'instrument_id', 'volume']).sort_values('timestamp').reset_index(drop=True)
    if not pd.DatetimeIndex(bars.timestamp).as_unit('ns').equals(expected) or bars.instrument_id.nunique() != 1:
        raise ValueError('Native instrument and target minute grid mismatch')
    if set(bars.instrument_id) != {expected_iid}:
        raise ValueError('Native perpetual target instrument does not match requested symbol')
    if not np.allclose(frame.volume, bars.volume, rtol=1e-12, atol=1e-8):
        raise ValueError('Original Engine volumes differ from raw-source extraction')
    frame['instrument_id'] = bars.instrument_id.iloc[0]
    frame['available_at'] = frame.timestamp+pd.Timedelta(minutes=2)
    frame = frame.rename(columns={'volume': 'total_volume', 'count': 'trade_count'})[
        ['timestamp', 'available_at', 'instrument_id', 'total_volume', 'taker_buy_volume', 'trade_count']]
    identity = {'source_manifest_sha256': digest(source/'source_manifest.json'),
                'target_bars_sha256': digest(bars_path), 'archives': archives}
    if verify_only:
        prior = json.loads((output/'source_manifest.json').read_text())
        if prior['sources'] != identity or digest(output/'observations.parquet') != prior['normalized_sha256']:
            raise ValueError('Saved flow-source fingerprints changed')
        pd.testing.assert_frame_equal(frame, pd.read_parquet(output/'observations.parquet'))
    else:
        output.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(output/'observations.parquet', index=False)
        manifest = {'symbol': symbol, 'instrument_id': frame.instrument_id.iloc[0], 'rows': len(frame),
                    'start': str(START), 'end_exclusive': str(END), 'sources': identity,
                    'normalized_sha256': digest(output/'observations.parquet'),
                    'availability': 'completed minute plus one additional minute; no future backfill',
                    'units': 'native perpetual base units;1000PEPE quantity stays bundled',
                    'definition': 'taker_buy_volume is aggressive buyer base volume; sellers=total-buy',
                    'limitations': ['aggregate trade flow is not book OFI or executable depth',
                                    'contemporaneous price impact does not prove subsequent predictability'],
                    'field_documentation': 'https://github.com/binance/binance-public-data#klines-1'}
        (output/'source_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(symbol, len(frame), 'native minute taker-flow rows verified', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='data_cache/minute-perpetual-1y')
    parser.add_argument('--out', default='data_cache/external-factors-1y/flow')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    for symbol in SYMBOLS:
        extract(args.source, args.out, symbol, args.verify_only)


if __name__ == '__main__':
    main()
