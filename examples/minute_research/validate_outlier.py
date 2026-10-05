"""Reconstruct pinned 2026-08-22 Bybit LINK/SOL trades and compare Binance caches.

No downloads, interpolation or market actions. See docs/minute_outlier_evidence/README.md.
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
import pandas as pd

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, help='Directory containing the two pinned Bybit gzip files')
    parser.add_argument('--workspace', type=Path, help='Repository containing the frozen Binance data_cache inputs')
    parser.add_argument('--out', type=Path, help='Derived output directory; defaults to --cache')
    args = parser.parse_args()
    WORK = (args.workspace or Path(__file__).resolve().parents[2]).resolve()
    EVIDENCE = Path(__file__).resolve().parents[2] / 'docs/minute_outlier_evidence'
    ROOT = (args.cache or WORK / 'data_cache/outlier-validation').resolve()
    OUT = (args.out or ROOT).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    comparisons = []
    manifest = json.loads((EVIDENCE / 'source_manifest.json').read_text())
    for reference in manifest['binance_reference_inputs']:
        path = WORK / reference['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != reference['sha256']:
            raise ValueError(f'Binance comparison cache hash mismatch: {path}')
    for item in manifest['archives']:
        s = item['symbol']
        path = ROOT / Path(item['path']).name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
        parts = []
        hashes = []
        prev = None
        first = None
        last = None
        count = 0
        unit_bad = 0
        order_bad = 0
        rpi_counts = {}
        for chunk in pd.read_csv(path, compression='gzip', chunksize=100000, usecols=['timestamp', 'symbol', 'size', 'price', 'trdMatchID', 'homeNotional', 'foreignNotional', 'RPI'], dtype={'timestamp': str}):
            assert chunk.symbol.eq(s).all()
            split = chunk.timestamp.str.partition('.')
            assert split[2].str.len().le(9).all()
            sec = split[0].astype('int64')
            nano = split[2].str.pad(9, side='right', fillchar='0').astype('int64')
            ns = sec * 1000000000 + nano
            assert ((chunk.price > 0) & (chunk['size'] > 0)).all()
            order_bad += int((ns.diff().dropna() < 0).sum()) + int(prev is not None and ns.iloc[0] < prev)
            prev = int(ns.iloc[-1])
            first = int(ns.iloc[0]) if first is None else first
            last = prev
            count += len(chunk)
            unit_bad += int((~np.isclose(chunk.homeNotional, chunk['size'], rtol=1e-10, atol=1e-10)).sum()) + int((~np.isclose(chunk.foreignNotional, chunk['size'] * chunk.price, rtol=1e-10, atol=1e-08)).sum())
            hashes.append(pd.util.hash_pandas_object(chunk.trdMatchID, index=False).to_numpy())
            for k, v in chunk.RPI.value_counts().items():
                rpi_counts[str(k)] = rpi_counts.get(str(k), 0) + int(v)
            chunk['timestamp'] = pd.to_datetime(ns // 60000000000 * 60000000000, utc=True)
            chunk['first_trade_ns'] = ns
            chunk['last_trade_ns'] = ns
            parts.append(chunk.groupby('timestamp', sort=False).agg(open=('price', 'first'), high=('price', 'max'), low=('price', 'min'), close=('price', 'last'), base_volume=('homeNotional', 'sum'), quote_volume=('foreignNotional', 'sum'), trades=('price', 'size'), first_trade_ns=('first_trade_ns', 'first'), last_trade_ns=('last_trade_ns', 'last')))
        bars = pd.concat(parts).groupby(level=0, sort=True).agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'), base_volume=('base_volume', 'sum'), quote_volume=('quote_volume', 'sum'), trades=('trades', 'sum'), first_trade_ns=('first_trade_ns', 'first'), last_trade_ns=('last_trade_ns', 'last'))
        expected = pd.date_range('2026-08-22', periods=1440, freq='1min', tz='UTC')
        assert bars.index.equals(expected), 'Missing or extra minute: refusing interpolation'
        assert order_bad == unit_bad == 0
        ids = np.concatenate(hashes)
        duplicates = len(ids) - len(np.unique(ids))
        assert duplicates == 0
        bars['minute_return'] = bars.close.pct_change(fill_method=None)
        bars.to_parquet(OUT / (s + '_2026-08-22_1m.parquet'))
        summary.append(dict(symbol=s, product='Bybit LinearPerpetual USDT-settled', base_coin=s[:-4], quote_coin='USDT', rows=count, minutes=len(bars), first_trade=str(pd.Timestamp(first, tz='UTC')), last_trade=str(pd.Timestamp(last, tz='UTC')), out_of_order=order_bad, duplicate_id_hashes=duplicates, notional_unit_mismatches=unit_bad, RPI_counts=rpi_counts, source_sha256=item['sha256']))
        spot = pd.read_parquet(WORK / f'data_cache/minute-1y/{s}/bars.parquet').set_index('timestamp')
        perp = pd.read_parquet(WORK / f'data_cache/minute-perpetual-1y/{s}/bars.parquet').set_index('timestamp')
        for t, a in bars.loc['2026-08-22 05:08':'2026-08-22 05:16'].iterrows():
            b = spot.loc[t]
            c = perp.loc[t]
            comparisons.append(dict(symbol=s, timestamp=str(t), bybit_open=a.open, bybit_high=a.high, bybit_low=a.low, bybit_close=a.close, bybit_return=a.minute_return, bybit_base_volume=a.base_volume, bybit_quote_volume=a.quote_volume, bybit_trades=int(a.trades), binance_spot_close=b.close, binance_spot_return=spot.close.pct_change().loc[t], binance_perp_close=c.close, binance_perp_return=perp.close.pct_change().loc[t], binance_mark_close=c.mark_price, binance_mark_return=perp.mark_price.pct_change().loc[t], bybit_close_vs_binance_perp=a.close / c.close - 1))
    pd.DataFrame(comparisons).to_csv(OUT / 'focus_comparison.csv', index=False)
    (OUT / 'validation_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    print(pd.DataFrame(comparisons).to_string(index=False))
if __name__ == '__main__':
    main()
