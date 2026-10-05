"""Fixed-year public Bybit collector; no account APIs or strategy calculations."""
from __future__ import annotations
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import sys
import threading
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
import pyarrow
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aster.backtest.models import Instrument

START = pd.Timestamp('2025-10-05', tz='UTC')
END = pd.Timestamp('2026-10-05', tz='UTC')
START_MS, END_MS = START.value // 1_000_000, END.value // 1_000_000
SYMBOLS = ('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
NATIVE = {s: '1000PEPEUSDT' if s == 'PEPEUSDT' else s for s in SYMBOLS}
BASE = 'https://api.bybit.com/v5/market/'


def check(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()


def atomic(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.partial')
    with temporary.open('wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def page_url(endpoint, native, start_ms=None, end_ms=None):
    check(native in NATIVE.values(), 'Unknown native symbol')
    check(endpoint in ('instruments-info','kline','mark-price-kline','funding/history'), 'Unknown endpoint')
    params = {'category':'linear','symbol':native}
    if endpoint != 'instruments-info':
        check(isinstance(start_ms, int) and isinstance(end_ms, int), 'Integer page bounds required')
        check(START_MS <= start_ms <= end_ms <= END_MS, 'Page outside fixed year/boundary')
        if endpoint == 'funding/history':
            params.update(startTime=start_ms,endTime=end_ms,limit=200)
        else:
            check(end_ms < END_MS, 'Candle END is excluded')
            params.update(interval='1',start=start_ms,end=end_ms,limit=1000)
    return BASE + endpoint + '?' + urllib.parse.urlencode(params)


class RateLimiter:
    """One global gate shared by both workers, including retries."""
    def __init__(self, interval=.11):
        check(interval >= .1, 'Request pacing must be <=10 requests/sec')
        self.interval, self.last, self.lock = interval, None, threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.monotonic()
            if self.last is not None:
                time.sleep(max(0, self.last + self.interval - now))
            self.last = time.monotonic()


class Pages:
    def __init__(self, root, offline=False):
        self.root, self.offline, self.limiter = Path(root), offline, RateLimiter()

    def get(self, endpoint, native, start_ms=None, end_ms=None):
        url = page_url(endpoint,native,start_ms,end_ms)
        path = self.root / 'raw' / (digest(url.encode()) + '.json')
        if path.exists():
            envelope = json.loads(path.read_bytes())
        else:
            check(not self.offline, f'Missing sealed raw page: {url}')
            last_error = None
            for attempt in range(6):
                try:
                    self.limiter.acquire()
                    with urllib.request.urlopen(url,timeout=30) as response:
                        check(response.status == 200, 'Non-200 response')
                        raw = response.read()
                    payload = json.loads(raw)
                    check(payload.get('retCode') == 0, f"Bybit API error: {payload.get('retCode')}")
                    envelope = {'url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat(),
                                'raw_sha256':digest(raw),'raw_base64':base64.b64encode(raw).decode()}
                    # Validate before committing a resumable page.
                    validate_payload(payload,native,endpoint,start_ms,end_ms)
                    atomic(path,encoded(envelope))
                    break
                except (OSError,ValueError,json.JSONDecodeError) as exc:
                    last_error = exc
                    if attempt == 5:
                        raise ValueError(f'Public request failed: {url}') from last_error
                    time.sleep(min(60, 2 ** attempt))
            else:
                raise last_error
        check(envelope.get('url') == url, 'Cached page URL mismatch')
        retrieved = pd.Timestamp(envelope['retrieved_utc'])
        check(retrieved.tzinfo is not None and retrieved.utcoffset().total_seconds() == 0, 'Missing UTC retrieval time')
        raw = base64.b64decode(envelope['raw_base64'],validate=True)
        check(digest(raw) == envelope['raw_sha256'], 'Raw page hash mismatch')
        payload = json.loads(raw)
        validate_payload(payload,native,endpoint,start_ms,end_ms)
        receipt = {'url':url,'retrieved_utc':envelope['retrieved_utc'],'raw_sha256':digest(raw),
                   'raw_bytes':len(raw),'cache_file':str(path.relative_to(self.root)),
                   'envelope_sha256':digest(path.read_bytes())}
        return payload, receipt


def result(payload, native):
    check(payload.get('retCode') == 0, 'API retCode is not zero')
    data = payload.get('result',{})
    check(data.get('category') == 'linear', 'Wrong category')
    check(isinstance(data.get('list'),list), 'Missing observation list')
    # Funding history carries identity in each row; candles carry it in result.
    if 'symbol' in data:
        check(data['symbol'] == native, 'Wrong result symbol')
    return data


def catalog_record(payload, native):
    rows = result(payload,native)['list']
    check(len(rows) == 1, 'Instrument response must be singleton')
    item = rows[0]
    check(item['symbol'] == native and item['contractType'] == 'LinearPerpetual'
          and item['quoteCoin'] == item['settleCoin'] == 'USDT'
          and item['baseCoin'] == native[:-4] and item['status'] == 'Trading', 'Wrong native contract')
    lot,price = item['lotSizeFilter'],item['priceFilter']
    values = [float(price['tickSize']),float(lot['qtyStep']),float(lot['minOrderQty']),float(lot['minNotionalValue'])]
    check(all(math.isfinite(x) and x > 0 for x in values),'Invalid current rules')
    return asdict(Instrument(id='bybit:perpetual:'+native,exchange='bybit',symbol=native,
                  market_type='perpetual',base=item['baseCoin'],quote='USDT',tick_size=values[0],
                  lot_size=values[1],min_quantity=values[2],min_notional=values[3],multiplier=1))


def milliseconds(value):
    check(type(value) is int or (isinstance(value,str) and value.isascii() and value.isdecimal()),
          'Timestamp must be exact integer milliseconds')
    return int(value)


def parse_candles(payload,native,endpoint,start_ms,end_ms):
    data = result(payload,native)
    check(data.get('symbol') == native, 'Candle symbol missing/wrong')
    rows = []
    for item in data['list']:
        check(len(item) == (7 if endpoint == 'kline' else 5), 'Wrong candle schema')
        stamp = milliseconds(item[0])
        check(start_ms <= stamp <= end_ms and START_MS <= stamp < END_MS and stamp % 60000 == 0,'Candle outside page/grid')
        nums = [float(v) for v in item[1:]]
        check(all(math.isfinite(v) for v in nums), 'Nonfinite candle')
        o,h,l,c = nums[:4]
        check(0 < l <= min(o,c) <= max(o,c) <= h, 'Corrupt OHLC')
        check(endpoint != 'kline' or all(v >= 0 for v in nums[4:]), 'Negative volume/turnover')
        rows.append((stamp,*nums))
    check(len(rows) <= 1000,'Oversized candle page')
    return rows


def parse_funding(payload,native,start_ms,end_ms):
    rows = []
    for item in result(payload,native)['list']:
        check(item['symbol'] == native,'Wrong funding native identity')
        stamp,rate = milliseconds(item['fundingRateTimestamp']),float(item['fundingRate'])
        check(start_ms <= stamp <= end_ms and START_MS <= stamp <= END_MS,'Funding outside page/year')
        check(math.isfinite(rate),'Nonfinite funding')
        rows.append((stamp,rate))
    check(len(rows) <= 200,'Oversized funding page')
    return rows


def validate_payload(payload,native,endpoint,start_ms,end_ms):
    if endpoint == 'instruments-info':
        return catalog_record(payload,native)
    if endpoint == 'funding/history':
        return parse_funding(payload,native,start_ms,end_ms)
    return parse_candles(payload,native,endpoint,start_ms,end_ms)


def unique(rows, label):
    values = {}
    for row in rows:
        stamp = row[0]
        # Page windows are disjoint; every duplicate is an error, even identical.
        check(stamp not in values, f'Duplicate/conflicting {label} timestamp')
        values[stamp] = row
    return [values[k] for k in sorted(values)]


def normalize(native,trade_rows,mark_rows,funding_rows,start=START,end=END):
    trade_rows,mark_rows = unique(trade_rows,'trade'),unique(mark_rows,'mark')
    grid = pd.date_range(start,end,freq='1min',inclusive='left')
    expected = grid.as_unit("ns").asi8 // 1_000_000
    for rows,label in ((trade_rows,'trade'),(mark_rows,'mark')):
        check(len(rows) == len(grid) and np.array_equal([x[0] for x in rows],expected),f'Missing/extraneous {label} minute grid')
    for rows, width in ((trade_rows,7),(mark_rows,5)):
        check(all(len(row) == width for row in rows),'Normalized source row width mismatch')
        values = np.asarray(rows,dtype=float)[:,1:]
        check(np.isfinite(values).all(),'Nonfinite normalized source')
        o,h,l,c = (values[:,i] for i in range(4))
        check(((l > 0) & (l <= np.minimum(o,c)) & (h >= np.maximum(o,c))).all(),'Corrupt normalized OHLC')
        check(width != 7 or (values[:,4:] >= 0).all(),'Negative normalized volume/turnover')
    bars = pd.DataFrame(trade_rows,columns=['event_ms','open','high','low','close','volume','turnover'])
    bars['timestamp'] = pd.to_datetime(bars.pop('event_ms'),unit='ms',utc=True)
    bars['instrument_id'] = 'bybit:perpetual:'+native
    bars['duration_seconds'] = 60
    bars['end'] = bars.timestamp + pd.Timedelta(minutes=1)
    marks = pd.DataFrame(mark_rows,columns=['event_ms','mark_open','mark_high','mark_low','mark_price'])
    for col in ('mark_open','mark_high','mark_low','mark_price'):
        bars[col] = marks[col].to_numpy()
    settled = unique(funding_rows,'funding')
    check(len(settled) > 0, 'Empty entire funding history')
    lookup = dict(zip(expected,bars.mark_open))
    funding = []
    start_ms,end_ms = start.value // 1_000_000,end.value // 1_000_000
    for stamp,rate in settled:
        check(math.isfinite(rate),'Nonfinite normalized funding')
        check(start_ms <= stamp <= end_ms,'Funding outside normalized interval')
        if stamp == end_ms:
            proxy,label = float(bars.mark_price.iloc[-1]),'END_last_completed_mark_close_proxy'
        else:
            check(stamp in lookup,'Funding not aligned to observed minute mark open')
            proxy,label = float(lookup[stamp]),'settlement_minute_mark_open_proxy'
        funding.append({'timestamp':pd.Timestamp(stamp,unit='ms',tz='UTC'),
                        'instrument_id':'bybit:perpetual:'+native,'funding_rate':rate,
                        'mark_price':proxy,'mark_price_source':label,'boundary':stamp==end_ms})
    frame = pd.DataFrame(funding,columns=['timestamp','instrument_id','funding_rate','mark_price','mark_price_source','boundary'])
    if len(frame):
        frame['timestamp'] = pd.to_datetime(frame.timestamp,utc=True)
    else:
        frame['timestamp'] = pd.Series([],dtype='datetime64[ns, UTC]')
    gaps = [{'previous':a['timestamp'].isoformat(),'next':b['timestamp'].isoformat(),
             'elapsed_minutes':(b['timestamp']-a['timestamp']).total_seconds()/60}
            for a,b in zip(funding,funding[1:])]
    return bars,frame,{'settlement_count':len(frame),'intervals_observed':gaps,
                      'interval_minutes_counts':{str(k):int(v) for k,v in pd.Series([x['elapsed_minutes'] for x in gaps],dtype=float).astype(str).value_counts().sort_index().items()},
                      'longest_observed_interval_minutes':max((x['elapsed_minutes'] for x in gaps),default=None),
                      'missing_settlements':'Not inferable from interval differences alone; no assumed cadence or interpolation'}


def collect_symbol(pages,spot):
    native = NATIVE[spot]
    spec,receipt = pages.get('instruments-info',native)
    catalog = catalog_record(spec,native)
    receipts = [receipt]
    streams = {}
    for endpoint in ('kline','mark-price-kline'):
        rows = []
        for page_count,lower in enumerate(range(START_MS,END_MS,1000*60000),1):
            upper = min(lower+1000*60000,END_MS)-1
            payload,r = pages.get(endpoint,native,lower,upper)
            receipts.append(r)
            rows.extend(parse_candles(payload,native,endpoint,lower,upper))
            if not pages.offline and (page_count % 50 == 0 or upper == END_MS-1):
                print(native,endpoint,'pages',page_count,'rows',len(rows),flush=True)
        streams[endpoint] = rows
    funding = []
    # Scan the bounded full year backwards; actual cadence is neither imposed nor inferred.
    lower,upper = START_MS,END_MS-1
    page_count = 0
    while upper >= lower:
        payload,r = pages.get('funding/history',native,lower,upper)
        receipts.append(r)
        rows = parse_funding(payload,native,lower,upper)
        funding.extend(rows)
        page_count += 1
        if not pages.offline and page_count % 10 == 0:
            print(native,'funding pages',page_count,'observations',len(funding),flush=True)
        if len(rows) < 200:
            break
        next_upper = min(x[0] for x in rows)-1
        check(next_upper < upper,'Funding pagination made no progress')
        upper = next_upper
    boundary,r = pages.get('funding/history',native,END_MS,END_MS)
    receipts.append(r)
    funding.extend(parse_funding(boundary,native,END_MS,END_MS))
    bars,settled,diagnostics = normalize(native,streams['kline'],streams['mark-price-kline'],funding)
    manifest = {'spot_label':spot,'native_symbol':native,'start':START.isoformat(),'end_exclusive':END.isoformat(),
                'rows':len(bars),'raw_pages':receipts,'funding_diagnostics':diagnostics,
                'metadata_historical_rules':False,'metadata_note':'Current official rules approximate historical rules. Instrument fee/risk defaults are simulator assumptions.',
                'funding_proxy_note':'Actual rates/timestamps, approximate settlement valuation from minute mark; END uses last completed close. No predictor availability field is asserted as fact.'}
    return catalog,bars,settled,manifest


def source_provenance():
    return {'collector_sha256':digest(Path(__file__).read_bytes()),
            'instrument_model_sha256':digest((Path(__file__).resolve().parents[2]/'aster/backtest/models.py').read_bytes()),
            'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
            'pyarrow':pyarrow.__version__,'purpose':'Data reconstruction provenance, not strategy preregistration'}


def run(out,workers=2,verify_only=False):
    check(workers in (1,2),'Workers must be 1 or 2')
    root = Path(out)
    provenance = source_provenance()
    allowed_files = {'instruments.json'} | {f'{symbol}/{name}' for symbol in SYMBOLS
                    for name in ('bars.parquet','funding.parquet','source_manifest.json')}
    seal_path = root/'dataset_seal.json'
    if seal_path.exists():
        seal = json.loads(seal_path.read_bytes())
        check(seal['start']==START.isoformat() and seal['end_exclusive']==END.isoformat(),'Wrong dataset seal interval')
        check(seal['symbols']==list(SYMBOLS),'Wrong dataset seal universe')
        check(isinstance(seal.get('files'),dict) and set(seal['files']) == allowed_files,'Seal must contain exactly allowed 25 relative paths')
        check(seal.get('source_provenance') == provenance,'Collector/runtime provenance differs from completed seal')
        for name,hash_value in seal['files'].items():
            check(digest((root/name).read_bytes())==hash_value,f'Normalized/manifest tamper: {name}')
        verify_only = True
    elif verify_only:
        raise ValueError('Completed dataset seal missing')
    pages = Pages(root,offline=verify_only)
    catalog = []
    files = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset in range(0,len(SYMBOLS),workers):
            batch = SYMBOLS[offset:offset+workers]
            for spot,output in zip(batch,pool.map(lambda s:collect_symbol(pages,s),batch)):
                spec,bars,funding,manifest = output
                catalog.append(spec)
                folder = root/spot
                for name,frame in (('bars.parquet',bars),('funding.parquet',funding)):
                    target = folder/name
                    if verify_only:
                        pd.testing.assert_frame_equal(pd.read_parquet(target),frame,check_exact=True)
                    else:
                        # Parquet writes atomically via a temporary sibling.
                        folder.mkdir(parents=True,exist_ok=True)
                        temp = target.with_name(target.name+'.partial')
                        frame.to_parquet(temp,index=False)
                        os.replace(temp,target)
                    files[str(target.relative_to(root))] = digest(target.read_bytes())
                target = folder/'source_manifest.json'
                if verify_only:
                    check(json.loads(target.read_bytes())==manifest,'Manifest differs from raw reconstruction')
                else:
                    atomic(target,encoded(manifest))
                files[str(target.relative_to(root))]=digest(target.read_bytes())
    target=root/'instruments.json'
    if verify_only:
        check(json.loads(target.read_bytes())==catalog,'Catalog differs from raw reconstruction')
        check(files|{'instruments.json':digest(target.read_bytes())} == seal['files'],'Seal file set mismatch')
    else:
        atomic(target,encoded(catalog))
        files['instruments.json']=digest(target.read_bytes())
        atomic(seal_path,encoded({'start':START.isoformat(),'end_exclusive':END.isoformat(),'symbols':list(SYMBOLS),'files':files,'source_provenance':provenance}))
    print('Offline reconstructed and verified' if verify_only else 'Collected and sealed',len(SYMBOLS),'native contracts')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('data_cache/minute-bybit-1y'))
    parser.add_argument('--workers',type=int,choices=(1,2),default=2)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    run(args.out,args.workers,args.verify_only)
