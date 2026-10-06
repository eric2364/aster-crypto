"""Independent offline Bybit reconstruction. Does not import the collector or engine."""
from __future__ import annotations
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from urllib.parse import urlencode
import numpy as np
import pandas as pd
import pyarrow

REPO = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = '7d01b3e'
START = pd.Timestamp('2025-10-05', tz='UTC')
END = pd.Timestamp('2026-10-05', tz='UTC')
SYMBOLS = ('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
BAR_COLUMNS = ['open','high','low','close','volume','turnover','timestamp','instrument_id','duration_seconds','end','mark_open','mark_high','mark_low','mark_price']
FUND_COLUMNS = ['timestamp','instrument_id','funding_rate','mark_price','mark_price_source','boundary']


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_file(root, relative):
    require(isinstance(relative, str) and not Path(relative).is_absolute() and '..' not in Path(relative).parts, 'Unsafe cache path')
    path = root / relative
    require(path.is_file() and path.resolve().is_relative_to(root.resolve()) and not path.is_symlink(), 'Missing/escaped cache file')
    return path


def ms(value):
    require(type(value) is int or (isinstance(value, str) and value.isascii() and value.isdecimal()), 'Noninteger source milliseconds')
    return int(value)


def numbers(values):
    require(all(not isinstance(v, bool) for v in values), 'Boolean numeric source')
    result = np.asarray([float(v) for v in values], dtype=float)
    require(np.isfinite(result).all(), 'Nonfinite source numbers')
    return result


def url(endpoint, native, lower=None, upper=None):
    params = {'category':'linear','symbol':native}
    if endpoint == 'funding/history':
        params.update(startTime=lower,endTime=upper,limit=200)
    elif endpoint != 'instruments-info':
        params.update(interval='1',start=lower,end=upper,limit=1000)
    return 'https://api.bybit.com/v5/market/'+endpoint+'?'+urlencode(params)


def provenance():
    paths = {'collector_sha256':'examples/cross_venue/download_bybit.py', 'instrument_model_sha256':'aster/backtest/models.py'}
    result = {}
    for key, relative in paths.items():
        current = (REPO/relative).read_bytes()
        committed = subprocess.run(['git','show',SOURCE_COMMIT+':'+relative], cwd=REPO, check=True, capture_output=True).stdout
        require(sha(current) == sha(committed), 'Executed source differs from committed anchor: '+relative)
        result[key] = sha(current)
    result.update(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,pyarrow=pyarrow.__version__,purpose='Data reconstruction provenance, not strategy preregistration')
    return result


def timestamps(series):
    require(isinstance(series.dtype, pd.DatetimeTZDtype) and str(series.dt.tz) == 'UTC', 'Normalized timestamps must be UTC aware')
    return series.dt.as_unit('ns').array.asi8


def verify_dataset(root):
    root = Path(root)
    seal_path = safe_file(root, 'dataset_seal.json')
    seal_bytes = seal_path.read_bytes()
    seal = json.loads(seal_bytes)
    require(set(seal) == {'start','end_exclusive','symbols','files','source_provenance'}, 'Wrong seal schema')
    require(seal['start'] == START.isoformat() and seal['end_exclusive'] == END.isoformat() and seal['symbols'] == list(SYMBOLS), 'Wrong sealed year/universe')
    expected_files = {'instruments.json'} | {s+'/'+n for s in SYMBOLS for n in ('bars.parquet','funding.parquet','source_manifest.json')}
    require(set(seal['files']) == expected_files, 'Seal must contain exactly 25 prescribed files')
    require(seal['source_provenance'] == provenance(), 'Source/runtime provenance mismatch')
    def verify_files():
        for relative, expected in seal['files'].items():
            require(sha(safe_file(root, relative).read_bytes()) == expected, 'Sealed file hash mismatch: '+relative)
    verify_files()
    catalog = json.loads(safe_file(root,'instruments.json').read_bytes())
    require(isinstance(catalog,list) and len(catalog) == 8, 'Wrong catalog universe')
    lower, end = START.value//10**6, END.value//10**6
    count = (end-lower)//60000
    require(count > 0 and (end-lower)%60000 == 0, 'Invalid minute interval')
    grid = np.arange(lower,end,60000,dtype=np.int64)
    raw_hashes = {}
    certificates = []
    for spot, spec in zip(SYMBOLS,catalog):
        native = '1000PEPEUSDT' if spot == 'PEPEUSDT' else spot
        iid = 'bybit:perpetual:'+native
        manifest = json.loads(safe_file(root,spot+'/source_manifest.json').read_bytes())
        require(set(manifest) == {'spot_label','native_symbol','start','end_exclusive','rows','raw_pages','funding_diagnostics','metadata_historical_rules','metadata_note','funding_proxy_note'}, 'Wrong manifest schema')
        require((manifest['spot_label'],manifest['native_symbol'],manifest['start'],manifest['end_exclusive'],manifest['rows']) == (spot,native,START.isoformat(),END.isoformat(),count), 'Wrong manifest identity/grid')
        require(manifest['metadata_historical_rules'] is False, 'Historical metadata claim unsupported')
        require(manifest['metadata_note'] == 'Current official rules approximate historical rules. Instrument fee/risk defaults are simulator assumptions.', 'Wrong metadata assumption disclosure')
        require(manifest['funding_proxy_note'] == 'Actual rates/timestamps, approximate settlement valuation from minute mark; END uses last completed close. No predictor availability field is asserted as fact.', 'Wrong funding proxy disclosure')
        receipts = iter(manifest['raw_pages'])
        page_counts = Counter()
        def page(endpoint, a=None, b=None):
            receipt = next(receipts, None)
            require(isinstance(receipt,dict) and set(receipt) == {'url','retrieved_utc','raw_sha256','raw_bytes','cache_file','envelope_sha256'}, 'Missing/wrong page receipt')
            expected_url = url(endpoint,native,a,b)
            relative = 'raw/'+sha(expected_url.encode())+'.json'
            require(receipt['url'] == expected_url and receipt['cache_file'] == relative, 'Noncanonical URL/page identity')
            path = safe_file(root,relative)
            encoded = path.read_bytes()
            require(sha(encoded) == receipt['envelope_sha256'], 'Envelope hash mismatch')
            envelope = json.loads(encoded)
            require(set(envelope) == {'url','retrieved_utc','raw_sha256','raw_base64'}, 'Wrong envelope schema')
            require(all(envelope[k] == receipt[k] for k in ('url','retrieved_utc','raw_sha256')), 'Envelope/receipt identity mismatch')
            retrieved = pd.Timestamp(envelope['retrieved_utc'])
            require(retrieved.tzinfo is not None and retrieved.utcoffset().total_seconds() == 0, 'Retrieval timestamp not UTC')
            raw = base64.b64decode(envelope['raw_base64'],validate=True)
            require(sha(raw) == receipt['raw_sha256'] and type(receipt['raw_bytes']) is int and len(raw) == receipt['raw_bytes'], 'Raw bytes/hash mismatch')
            body = json.loads(raw)
            require(type(body.get('retCode')) is int and body['retCode'] == 0, 'API error/schema')
            result = body.get('result',{})
            require(result.get('category') == 'linear' and isinstance(result.get('list'),list), 'Wrong native response category/list')
            require(('symbol' not in result or result['symbol'] == native) and (endpoint not in ('kline','mark-price-kline') or result.get('symbol') == native), 'Wrong native response identity')
            require(relative not in raw_hashes, 'Repeated raw page identity')
            raw_hashes[relative] = sha(encoded)
            page_counts[endpoint] += 1
            return result['list']
        items = page('instruments-info')
        require(len(items) == 1, 'Catalog response not singleton')
        item = items[0]
        require((item['symbol'],item['contractType'],item['quoteCoin'],item['settleCoin'],item['baseCoin'],item['status']) == (native,'LinearPerpetual','USDT','USDT',native[:-4],'Trading'), 'Wrong native catalog contract')
        rules = numbers([item['priceFilter']['tickSize'],item['lotSizeFilter']['qtyStep'],item['lotSizeFilter']['minOrderQty'],item['lotSizeFilter']['minNotionalValue']])
        require((rules > 0).all(), 'Nonpositive native rules')
        expected_spec = dict(id=iid,exchange='bybit',symbol=native,market_type='perpetual',base=native[:-4],quote='USDT',tick_size=rules[0],lot_size=rules[1],min_quantity=rules[2],min_notional=rules[3],maker_bps=2.,taker_bps=5.,max_leverage=20.,maintenance_rate=.005,liquidation_bps=50.,funding_interval_hours=8,contract_type='linear',multiplier=1.,listed_at=None,delisted_at=None)
        require(spec == expected_spec, 'Catalog differs from source/current simulator assumptions')
        streams = []
        for endpoint,width in (('kline',7),('mark-price-kline',5)):
            array = np.empty((count,width-1),dtype=float)
            seen = np.zeros(count,dtype=bool)
            for a in range(lower,end,1000*60000):
                b = min(a+1000*60000,end)-1
                rows = page(endpoint,a,b)
                require(len(rows) <= 1000, 'Oversized candle page')
                for row in rows:
                    require(isinstance(row,list) and len(row) == width, 'Wrong source candle width')
                    stamp = ms(row[0])
                    require(a <= stamp <= b and lower <= stamp < end and stamp%60000 == 0, 'Source candle outside page/minute grid')
                    index = (stamp-lower)//60000
                    require(not seen[index], 'Duplicate source candle')
                    values = numbers(row[1:])
                    o,h,l,c = values[:4]
                    require(0 < l <= min(o,c) <= max(o,c) <= h and (width == 5 or (values[4:] >= 0).all()), 'Invalid source OHLC/volume')
                    array[index], seen[index] = values, True
            require(seen.all(), 'Incomplete source candle grid')
            streams.append(array)
        settled = {}
        def funding_page(a,b):
            rows = page('funding/history',a,b)
            require(len(rows) <= 200, 'Oversized funding page')
            stamps = []
            for row in rows:
                require(isinstance(row,dict) and row.get('symbol') == native, 'Wrong funding row native identity')
                stamp = ms(row['fundingRateTimestamp'])
                require(a <= stamp <= b and lower <= stamp <= end, 'Funding outside exact page/year')
                require(stamp not in settled, 'Duplicate funding settlement')
                settled[stamp] = numbers([row['fundingRate']])[0]
                stamps.append(stamp)
            return stamps
        upper = end-1
        while upper >= lower:
            stamps = funding_page(lower,upper)
            if len(stamps) < 200:
                break
            following = min(stamps)-1
            require(following < upper, 'Funding page made no progress')
            upper = following
        funding_page(end,end)
        require(next(receipts,None) is None and settled, 'Extra receipts/empty funding stream')
        bars = pd.read_parquet(safe_file(root,spot+'/bars.parquet'))
        require(list(bars) == BAR_COLUMNS and len(bars) == count, 'Wrong normalized bar schema/grid')
        require(np.array_equal(timestamps(bars.timestamp),grid*10**6) and np.array_equal(timestamps(bars.end),(grid+60000)*10**6), 'Wrong normalized start/end grid')
        require((bars.instrument_id == iid).all() and (bars.duration_seconds == 60).all(), 'Wrong normalized identity/duration')
        for columns,array in ((BAR_COLUMNS[:6],streams[0]),(['mark_open','mark_high','mark_low','mark_price'],streams[1])):
            require(np.array_equal(bars[columns].to_numpy(),array), 'Normalized OHLCV/mark values differ from raw source')
        fund = pd.read_parquet(safe_file(root,spot+'/funding.parquet'))
        events = sorted(settled)
        require(list(fund) == FUND_COLUMNS and len(fund) == len(events), 'Wrong normalized funding schema/count')
        require(np.array_equal(timestamps(fund.timestamp),np.asarray(events,dtype=np.int64)*10**6), 'Normalized funding timestamps differ from source milliseconds')
        require((fund.instrument_id == iid).all() and np.array_equal(fund.funding_rate.to_numpy(),[settled[s] for s in events]), 'Normalized funding identity/rates differ from raw')
        prices, labels = [], []
        for stamp in events:
            if stamp == end:
                prices.append(streams[1][-1,3]); labels.append('END_last_completed_mark_close_proxy')
            else:
                require(stamp%60000 == 0, 'Unaligned funding has no observed minute-open proxy')
                prices.append(streams[1][(stamp-lower)//60000,0]); labels.append('settlement_minute_mark_open_proxy')
        require(np.array_equal(fund.mark_price.to_numpy(),prices) and fund.mark_price_source.tolist() == labels and fund.boundary.dtype == bool and fund.boundary.tolist() == [s == end for s in events], 'Incorrect funding proxy/boundary')
        gaps = [{'previous':pd.Timestamp(a,unit='ms',tz='UTC').isoformat(),'next':pd.Timestamp(b,unit='ms',tz='UTC').isoformat(),'elapsed_minutes':(b-a)/60000} for a,b in zip(events,events[1:])]
        histogram = dict(Counter(str(x['elapsed_minutes']) for x in gaps))
        diagnostics = dict(settlement_count=len(events),intervals_observed=gaps,interval_minutes_counts=histogram,longest_observed_interval_minutes=max((x['elapsed_minutes'] for x in gaps),default=None),missing_settlements='Not inferable from interval differences alone; no assumed cadence or interpolation')
        require(manifest['funding_diagnostics'] == diagnostics, 'Funding interval diagnostics differ from exact source events')
        certificates.append(dict(spot_label=spot,native_symbol=native,trade_rows=count,mark_rows=count,funding_rows=len(events),raw_pages=dict(page_counts),first_funding_timestamp=pd.Timestamp(events[0],unit='ms',tz='UTC').isoformat(),last_funding_timestamp=pd.Timestamp(events[-1],unit='ms',tz='UTC').isoformat(),source_interval_minutes_histogram=histogram,proxy_counts=dict(Counter(labels))))
        del bars, fund, streams
    verify_files()
    require(seal_path.read_bytes() == seal_bytes, 'Seal changed during audit')
    for relative, expected in raw_hashes.items():
        require(sha(safe_file(root,relative).read_bytes()) == expected, 'Raw envelope changed during audit')
    return dict(complete=True,errors=[],dataset_root=str(root.resolve()),start=START.isoformat(),end_exclusive=END.isoformat(),source_commit=SOURCE_COMMIT,dataset_seal_sha256=sha(seal_bytes),source_provenance=seal['source_provenance'],auditor_sha256=sha(Path(__file__).read_bytes()),normalized_files_sha256=seal['files'],raw_pages=len(raw_hashes),raw_envelope_identity_digest=sha(json.dumps(raw_hashes,sort_keys=True).encode()),symbols=certificates,scope='Exact cached source reconstruction; funding cadence completeness and historical metadata are not established. No yield or performance calculation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=REPO/'data_cache/minute-bybit-1y')
    parser.add_argument('--out',type=Path,default=REPO/'audit/bybit_dataset_evidence.json')
    args = parser.parse_args()
    receipt = verify_dataset(args.root)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(receipt,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'complete':True,'symbols':len(receipt['symbols']),'raw_pages':receipt['raw_pages'],'certificate':str(args.out)}))

if __name__ == '__main__':
    main()
