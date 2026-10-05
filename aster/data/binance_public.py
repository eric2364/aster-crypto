"""Checksum-verified official Binance archive ingestion and funding pagination.

No account, credentials or trade endpoints are used. Bars are UTC [start,end).
Funding includes a settlement exactly at the terminal valuation boundary end.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import hashlib
import json
import re
import urllib.request
import urllib.parse
import urllib.error
import zipfile
import pandas as pd
from aster.data.validation import normalize_bars, normalize_funding
from aster.backtest.models import Instrument

INTERVALS={'1s':1,'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400}
ORIGIN='https://data.binance.vision/data'

def utc_bound(value):
    stamp=pd.Timestamp(value)
    return stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')

def fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':'Aster-Crypto-Research/0.1'})
    with urllib.request.urlopen(request,timeout=45) as response:return response.read()

def decode_timestamp(values):
    values=pd.to_numeric(values,errors='raise').astype('int64')
    # Spot archive unit changed in Jan 2025; handle each row rather than guessing per file.
    ms=values.where(values.abs()<10**14)
    us=values.where(values.abs()>=10**14)
    return pd.to_datetime(ms,unit='ms',utc=True).fillna(pd.to_datetime(us,unit='us',utc=True))

def parse_archive(payload):
    with zipfile.ZipFile(BytesIO(payload)) as z:
        members=[n for n in z.namelist() if n.endswith('.csv') and not n.endswith('/')]
        if len(members)!=1:raise ValueError('Expected one CSV member per archive')
        frame=pd.read_csv(z.open(members[0]),header=None,dtype=str)
    if not len(frame):raise ValueError('Empty archive')
    # Futures archives may have an explicit documented header; never silently skip data rows.
    if frame.iloc[0,0] in ('open_time','openTime','Open time'):frame=frame.iloc[1:].reset_index(drop=True)
    if len(frame.columns)<6:raise ValueError('Incomplete archive schema')
    frame.columns=range(len(frame.columns))
    result=pd.DataFrame({'timestamp':decode_timestamp(frame[0]),'open':pd.to_numeric(frame[1]),
        'high':pd.to_numeric(frame[2]),'low':pd.to_numeric(frame[3]),'close':pd.to_numeric(frame[4]),
        'volume':pd.to_numeric(frame[5])})
    if 7 in frame:result['quote_volume']=pd.to_numeric(frame[7])
    if 8 in frame:result['trade_count']=pd.to_numeric(frame[8])
    return result

def get_archive(url,cache):
    checksum_url=url+'.CHECKSUM'
    expected=fetch(checksum_url).decode().split()[0].lower()
    if not re.fullmatch(r'[0-9a-f]{64}',expected):raise ValueError('Malformed SHA256 checksum')
    path=Path(cache)/(Path(urllib.parse.urlparse(url).path).name+'.'+expected)
    payload=path.read_bytes() if path.exists() else fetch(url)
    actual=hashlib.sha256(payload).hexdigest()
    if actual!=expected:raise ValueError(f'Checksum mismatch for {url}')
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():path.write_bytes(payload)
    return parse_archive(payload),{'url':url,'checksum_url':checksum_url,'sha256':actual,
        'checksum_verified':True,'bytes':len(payload),'cache_file':str(path)}

def archive_series(symbol,interval,market,kind,start,end,cache):
    frames=[];manifest=[]
    prefix='spot' if market=='spot' else 'futures/um'
    month=start.normalize().replace(day=1)
    while month<end:
        following=month+pd.offsets.MonthBegin(1)
        period=month.strftime('%Y-%m')
        url=f'{ORIGIN}/{prefix}/monthly/{kind}/{symbol}/{interval}/{symbol}-{interval}-{period}.zip'
        try:
            frame,entry=get_archive(url,cache);frames.append(frame);manifest.append(entry)
        except urllib.error.HTTPError as error:
            if error.code!=404:raise
            # An incomplete/unpublished monthly archive falls back to the requested daily files.
            days=pd.date_range(max(start.normalize(),month),min(end,following).ceil('1D')-pd.Timedelta(days=1),freq='1D')
            urls=[f'{ORIGIN}/{prefix}/daily/{kind}/{symbol}/{interval}/{symbol}-{interval}-{day:%Y-%m-%d}.zip' for day in days]
            with ThreadPoolExecutor(max_workers=4) as pool:
                for frame,entry in pool.map(lambda u:get_archive(u,cache),urls):frames.append(frame);manifest.append(entry)
        month=following
    if not frames:raise ValueError('No archives')
    joined=pd.concat(frames,ignore_index=True).sort_values('timestamp')
    duration=INTERVALS[interval]
    joined=joined[(joined.timestamp>=start)&(joined.timestamp+pd.Timedelta(seconds=duration)<=end)].reset_index(drop=True)
    if joined.timestamp.duplicated().any():raise ValueError('Duplicate archived candles')
    expected=pd.date_range(start,end-pd.Timedelta(seconds=duration),freq=f'{duration}s')
    missing=expected.difference(pd.DatetimeIndex(joined.timestamp))
    if len(missing):
        # A published monthly archive may omit a day that exists in the official daily archive.
        # Request only recorded missing observations; never interpolate or duplicate overlap.
        for day in missing.normalize().unique():
            url=f'{ORIGIN}/{prefix}/daily/{kind}/{symbol}/{interval}/{symbol}-{interval}-{day:%Y-%m-%d}.zip'
            try:
                repair,entry=get_archive(url,cache)
            except urllib.error.HTTPError as error:
                if error.code==404:continue
                raise
            repair=repair[repair.timestamp.isin(missing)]
            entry['purpose']='repair observed monthly omissions from official daily archive'
            if len(repair):
                joined=pd.concat([joined,repair],ignore_index=True)
                manifest.append(entry)
        joined=joined.sort_values('timestamp').reset_index(drop=True)
    if not pd.DatetimeIndex(joined.timestamp).equals(expected):
        raise ValueError(f'Incomplete interval coverage: expected {len(expected)} bars, received {len(joined)}')
    return joined,manifest

def funding_history(symbol,start,end,cache):
    cursor=int(start.timestamp()*1000);stop=int(end.timestamp()*1000);rows=[];manifest=[]
    while cursor<=stop:
        query=urllib.parse.urlencode({'symbol':symbol,'startTime':cursor,'endTime':stop,'limit':1000})
        url='https://fapi.binance.com/fapi/v1/fundingRate?'+query
        payload=fetch(url);page=json.loads(payload)
        if not isinstance(page,list):raise ValueError('Invalid funding response')
        digest=hashlib.sha256(payload).hexdigest();path=Path(cache)/f'funding-{symbol}-{cursor}-{digest}.json'
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
        manifest.append({'url':url,'sha256':digest,'cache_file':str(path),'rows':len(page)})
        if not page:break
        next_cursor=max(int(r['fundingTime']) for r in page)+1
        if next_cursor<=cursor:raise ValueError('Funding cursor did not advance')
        rows.extend(page);cursor=next_cursor
        if len(page)<1000:break
    if not rows:raise ValueError('No historical funding returned; refusing synthetic zero substitution')
    frame=pd.DataFrame({'timestamp':pd.to_datetime([int(r['fundingTime']) for r in rows],unit='ms',utc=True),
        'instrument_id':f'binance:perpetual:{symbol}',
        'funding_rate':[float(r['fundingRate']) for r in rows],'mark_price':[float(r['markPrice']) for r in rows]})
    if (frame.mark_price<=0).any():raise ValueError('Settlement mark missing; do not substitute future mark')
    return frame,manifest

def download(symbol,interval,start,end,destination,market='spot'):
    start,end=utc_bound(start),utc_bound(end)
    duration=INTERVALS[interval]
    if not re.fullmatch(r'[A-Z0-9]+USDT',symbol):raise ValueError('Currently only alphanumeric USDT symbols supported')
    if market not in ('spot','perpetual'):raise ValueError('Unsupported market')
    if start>=end or start!=start.floor(f'{duration}s') or end!=end.floor(f'{duration}s'):
        raise ValueError('Aligned UTC bounds with start < end required')
    root=Path(destination);root.mkdir(parents=True,exist_ok=True);cache=root/'raw'
    frame,archives=archive_series(symbol,interval,market,'klines',start,end,cache)
    iid=f'binance:{market}:{symbol}'
    frame['instrument_id']=iid;frame['duration_seconds']=duration
    frame['exchange']='binance';frame['symbol']=symbol;frame['market_type']=market
    funding=pd.DataFrame();funding_sources=[]
    if market=='perpetual':
        mark,mark_sources=archive_series(symbol,interval,market,'markPriceKlines',start,end,cache)
        frame=frame.merge(mark[['timestamp','open','close']].rename(columns={'open':'mark_open','close':'mark_price'}),
            on='timestamp',how='left',validate='one_to_one')
        archives.extend(mark_sources)
        funding,funding_sources=funding_history(symbol,start,end,cache)
    spec=Instrument(iid,'binance',symbol,market,base=symbol[:-4])
    frame,quality=normalize_bars(frame,{iid:spec})
    if market=='perpetual':funding=normalize_funding(funding,{iid:spec})
    frame.to_parquet(root/'bars.parquet',index=False)
    if market=='perpetual':funding.to_parquet(root/'funding.parquet',index=False)
    manifest={'source':'Binance official historical archives + public funding API' if market=='perpetual' else 'Binance official historical spot archives',
        'downloaded_at':datetime.now(timezone.utc).isoformat(),'market':market,'symbol':symbol,'interval':interval,
        'requested_start':start.isoformat(),'requested_end_exclusive':end.isoformat(),'first_bar':str(frame.timestamp.iloc[0]),
        'last_bar_end':str(frame.end.iloc[-1]),'rows':len(frame),'expected_rows':int((end-start).total_seconds()/duration),
        'quality':quality.to_dict(),'archives':archives,'funding_pages':funding_sources,'funding_rows':len(funding),
        'funding_interval_observed_hours':sorted((funding.timestamp.diff().dropna().dt.total_seconds()/3600).unique().tolist()) if len(funding) else [],
        'bars_sha256':hashlib.sha256((root/'bars.parquet').read_bytes()).hexdigest(),
        'funding_coverage_note':'Historical API returned events; no fixed cadence synthesized. Review gaps for dynamic intervals.'}
    (root/'source_manifest.json').write_text(json.dumps(manifest,indent=2))
    return manifest
