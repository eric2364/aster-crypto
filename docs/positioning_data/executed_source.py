"""Strict native Binance daily positioning archives; observations, not predictors.

Fixed last year only. Archive create_time without an offset is interpreted as UTC;
original publication/delivery availability and historical OI units are unverified.
No interpolation, minute filling, economic features or strategy execution.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tempfile
import time
import urllib.request
import zipfile
import numpy as np
import pandas as pd
import pyarrow

START=date(2025,10,5)
END=date(2026,10,5)
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','1000PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
BASE='https://data.binance.vision/data/futures/um/daily/metrics'
SCHEMA=['create_time','symbol','sum_open_interest','sum_open_interest_value',
        'count_toptrader_long_short_ratio','sum_toptrader_long_short_ratio',
        'count_long_short_ratio','sum_taker_long_short_vol_ratio']
NUMERIC=SCHEMA[2:]


def sha(body):
    return hashlib.sha256(body).hexdigest()


def encode(value):
    return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()


def runtime():
    return dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,pyarrow=pyarrow.__version__)


def days():
    return [START+timedelta(days=k) for k in range((END-START).days)]


def identity(symbol,day):
    if symbol not in SYMBOLS or day not in days():
        raise ValueError('Native symbol/date outside fixed window')
    name=f'{symbol}-metrics-{day.isoformat()}.zip'
    url=f'{BASE}/{symbol}/{name}'
    return dict(symbol=symbol,day=day.isoformat(),name=name,url=url,checksum_url=url+'.CHECKSUM')


def check_checksum(raw,check,name):
    fields=check.decode('ascii').split()
    if len(fields)!=2 or not re.fullmatch('[0-9a-fA-F]{64}',fields[0]) or fields[1].lstrip('*')!=name:
        raise ValueError('Malformed official checksum identity')
    if sha(raw)!=fields[0].lower():
        raise ValueError('Official checksum mismatch')


def parse_archive(raw,symbol,day):
    """Return sorted native point observations and original-order diagnostics."""
    ident=identity(symbol,day)
    member=ident['name'][:-4]+'.csv'
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.namelist()!=[member] or z.getinfo(member).file_size>5_000_000:
            raise ValueError('Unexpected/oversized ZIP member')
        body=z.read(member)
    reader=csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
    if reader.fieldnames!=SCHEMA:
        raise ValueError('Positioning schema drift')
    parsed=[];clocks=[]
    for idx,row in enumerate(reader):
        if None in row or None in row.values() or row['symbol']!=symbol:
            raise ValueError('Malformed row/native symbol mismatch')
        if not re.match(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}',row['create_time']):
            raise ValueError('Archive create_time must include explicit time')
        t=datetime.fromisoformat(row['create_time'])
        if t.tzinfo is None:
            t=t.replace(tzinfo=timezone.utc)
        t=t.astimezone(timezone.utc)
        if not (datetime.combine(day,datetime.min.time(),tzinfo=timezone.utc)<=t<=datetime.combine(day+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)):
            raise ValueError('Archive UTC file-date bounds mismatch')
        values={key:float(row[key]) for key in NUMERIC}
        if any(not np.isfinite(v) or v<=0 for v in values.values()):
            raise ValueError('Missing/nonfinite/nonpositive OI or ratio; fail closed')
        parsed.append(dict(timestamp=t,instrument_id=f'binance:perpetual:{symbol}',
                           source_symbol=symbol,source_day=day.isoformat(),source_create_time=row['create_time'],
                           original_row_index=idx,**values))
        clocks.append(t)
    expected=pd.date_range(pd.Timestamp(day,tz='UTC'),periods=288,freq='5min')
    end_labelled=expected+pd.Timedelta(minutes=5)
    actual=pd.DatetimeIndex(clocks)
    if len(clocks)!=288 or actual.has_duplicates or set(actual) not in (set(expected),set(end_labelled)):
        raise ValueError('Missing/extra/duplicate assumed five-minute clocks')
    label_grid='file-day-start-grid' if set(actual)==set(expected) else 'file-day-end-grid'
    # These are observed label sets only: no historical interval/publication claim.
    frame=pd.DataFrame(parsed).sort_values('timestamp').reset_index(drop=True)
    frame['timestamp']=pd.DatetimeIndex(frame.timestamp).as_unit('ns')
    diagnostic=dict(schema=SCHEMA,csv_sha256=sha(body),rows=288,
                    original_first=clocks[0].isoformat(),original_last=clocks[-1].isoformat(),
                    original_strictly_increasing=all(a<b for a,b in zip(clocks,clocks[1:])),
                    sorted_for_normalization=True,five_minute_grid_assumption=True,observed_label_grid=label_grid)
    return frame,diagnostic


def request(url):
    for attempt in range(4):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'aster-positioning-archive/1'})
            with urllib.request.urlopen(req,timeout=40) as response:
                body=response.read(10_000_001)
                if len(body)>10_000_000:
                    raise ValueError('Oversized archive response')
                return body,dict(response.headers),datetime.now(timezone.utc).isoformat()
        except (OSError,TimeoutError):
            if attempt==3:
                raise
            time.sleep(min(8,2**attempt))


def receipt_time(value):
    t=datetime.fromisoformat(value)
    if t.tzinfo is None or t.utcoffset()!=timedelta(0):
        raise ValueError('Retrieval receipt must be explicit UTC')


def read_raw(out,symbol,day):
    ident=identity(symbol,day)
    folder=out/'raw'/symbol/day.isoformat()
    if not folder.is_dir() or {p.name for p in folder.iterdir()}!={'archive.zip','checksum.txt','receipt.json'}:
        raise ValueError('Incomplete/unexpected immutable raw page')
    record=json.loads((folder/'receipt.json').read_text())
    if record.get('identity')!=ident:
        raise ValueError('Raw receipt identity/URL mismatch')
    for key in ['retrieved_at','checksum_retrieved_at']:
        receipt_time(record[key])
    raw=(folder/'archive.zip').read_bytes();check=(folder/'checksum.txt').read_bytes()
    if record.get('archive_sha256')!=sha(raw) or record.get('checksum_sha256')!=sha(check) or record.get('archive_bytes')!=len(raw):
        raise ValueError('Raw bytes/receipt hash mismatch')
    if not isinstance(record.get('response_headers'),dict) or not isinstance(record.get('checksum_response_headers'),dict):
        raise ValueError('Missing response headers')
    check_checksum(raw,check,ident['name'])
    if not re.fullmatch('[a-f0-9]{64}',record.get('acquisition_source_sha256','')):
        raise ValueError('Missing acquisition source provenance')
    frame,diagnostic=parse_archive(raw,symbol,day)
    if record.get('parse_status')!='verified' or record.get('diagnostic')!=diagnostic:
        raise ValueError('Raw diagnostic differs from independent parse')
    return frame,record


def download_one(out,symbol,day):
    ident=identity(symbol,day)
    folder=out/'raw'/symbol/day.isoformat()
    if folder.exists():
        return read_raw(out,symbol,day)
    acquisition_source=Path(__file__).read_bytes()
    raw,headers,at=request(ident['url']);check,cheaders,cat=request(ident['checksum_url'])
    check_checksum(raw,check,ident['name'])
    failure=None
    try:
        frame,diagnostic=parse_archive(raw,symbol,day)
    except Exception as error:
        failure=error;frame=None;diagnostic=None
    if Path(__file__).read_bytes()!=acquisition_source:
        raise ValueError('Collector source changed during page acquisition')
    record=dict(identity=ident,retrieved_at=at,checksum_retrieved_at=cat,
                response_headers=headers,checksum_response_headers=cheaders,
                archive_sha256=sha(raw),checksum_sha256=sha(check),archive_bytes=len(raw),diagnostic=diagnostic,
                acquisition_source_sha256=sha(acquisition_source),parse_status='rejected' if failure else 'verified',
                parse_error=f'{type(failure).__name__}: {failure}' if failure else None)
    folder.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.staging-',dir=folder.parent))
    try:
        for name,body in [('archive.zip',raw),('checksum.txt',check),('receipt.json',encode(record))]:
            (staging/name).write_bytes(body)
        if folder.exists():
            raise ValueError('Raw page appeared during acquisition; preserve it')
        os.rename(staging,folder)
    finally:
        if staging.exists():shutil.rmtree(staging)
    if failure is not None:
        raise ValueError(f'Checksum-valid raw evidence preserved at {folder}; source parse failed: {failure}') from failure
    return frame,record


def write_immutable(path,body):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=body:
            raise ValueError(f'Existing normalized evidence differs: {path}')
        return
    temporary=path.with_name('.'+path.name+'.tmp')
    with temporary.open('xb') as f:f.write(body)
    try:
        if path.exists():raise ValueError('Output appeared during acquisition')
        os.rename(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def full_frame(chunks):
    frame=pd.concat(chunks,ignore_index=True).sort_values('timestamp').reset_index(drop=True)
    expected=pd.date_range(pd.Timestamp(START,tz='UTC'),pd.Timestamp(END,tz='UTC'),freq='5min',inclusive='left').as_unit('ns')
    if not pd.DatetimeIndex(frame.timestamp).equals(expected):
        raise ValueError('Missing/duplicate/conflicting cross-day full-year clocks; no shifts or deduplication allowed')
    return frame


def provenance(symbol,records):
    return dict(symbol=symbol,instrument_id=f'binance:perpetual:{symbol}',rows=len(days())*288,
                start=START.isoformat(),end_exclusive=END.isoformat(),schema=SCHEMA,
                archives=records,grid='Explicit assumed complete 300-second UTC grid; missing observations fail closed',
                timestamp='UTC assumed for offset-free create_time; raw labels/file date/order retained; no period-label shifts',
                original_delivery_availability_verified=False,available_at_not_supplied=True,
                units='Source-native OI quantity and reported OI value preserved; no historical contract/unit guarantee',
                interpretation='OI value changes are not quantity changes; no prices/features/outcomes constructed',
                native_pepe='1000PEPEUSDT retained without rescaling',interpolation=False,
                source_documentation='https://github.com/binance/binance-public-data')


def expected_files():
    return {f'{s}/{name}' for s in SYMBOLS for name in ['observations.parquet','source_manifest.json']}|{'collection.json','executed_source.py'}


def verify(out,seal=None):
    """Offline raw reparse and exact normalized/source/runtime seal verification."""
    seal=json.loads((out/'complete.json').read_text()) if seal is None else seal
    if seal.get('complete') is not True or set(seal.get('files',{}))!=expected_files():
        raise ValueError('Incomplete/incorrect sealed output namespace')
    allowed_root=set(SYMBOLS)|{'raw','collection.json','executed_source.py','complete.json'}
    if {p.name for p in out.iterdir()}-allowed_root:
        raise ValueError('Unexpected collection root namespace')
    for symbol in SYMBOLS:
        if {p.name for p in (out/symbol).iterdir()}!={'observations.parquet','source_manifest.json'}:
            raise ValueError('Unexpected normalized symbol namespace')
    current=sha(Path(__file__).read_bytes())
    if seal.get('source_sha256')!=current or seal.get('runtime')!=runtime():
        raise ValueError('Collector source/runtime drift')
    for relative,digest in seal['files'].items():
        if sha((out/relative).read_bytes())!=digest:raise ValueError('Normalized/source seal drift')
    if (out/'executed_source.py').read_bytes()!=Path(__file__).read_bytes():
        raise ValueError('Archived collector mismatch')
    expected_raw={f'{s}/{d.isoformat()}' for s in SYMBOLS for d in days()}
    observed={f'{p.parent.name}/{p.name}' for p in (out/'raw').glob('*/*') if not p.name.startswith('.staging-')}
    if observed!=expected_raw or set(seal.get('raw_receipts',{}))!=expected_raw:
        raise ValueError('Raw date/symbol namespace mismatch')
    for symbol in SYMBOLS:
        chunks=[];records=[]
        for day in days():
            frame,record=read_raw(out,symbol,day);chunks.append(frame);records.append(record)
            key=f'{symbol}/{day.isoformat()}'
            if sha((out/'raw'/key/'receipt.json').read_bytes())!=seal['raw_receipts'][key]:
                raise ValueError('Raw receipt seal drift')
        reconstructed=full_frame(chunks)
        pd.testing.assert_frame_equal(reconstructed,pd.read_parquet(out/symbol/'observations.parquet'))
        if json.loads((out/symbol/'source_manifest.json').read_text())!=provenance(symbol,records):
            raise ValueError('Source manifest differs from raw reconstruction')
    if json.loads((out/'collection.json').read_text())!=collection(current):raise ValueError('Collection metadata drift')
    if sha(Path(__file__).read_bytes())!=current or runtime()!=seal['runtime']:
        raise ValueError('Collector source/runtime changed during verification')
    return seal


def collection(source):
    return dict(start=START.isoformat(),end_exclusive=END.isoformat(),native_symbols=list(SYMBOLS),
                rows_per_symbol=len(days())*288,archives=len(days())*len(SYMBOLS),source_sha256=source,
                runtime=runtime(),availability_verified=False,economic_features_or_outcomes=False)


def run(out,workers=4,verify_only=False):
    out=Path(out)
    if not 1<=workers<=4:raise ValueError('Workers must be between one and four')
    if verify_only:return verify(out)
    if (out/'complete.json').exists():return verify(out)
    source=Path(__file__).read_bytes();source_hash=sha(source);initial_runtime=runtime()
    write_immutable(out/'executed_source.py',source)
    page_results={};tasks=[(s,d) for s in SYMBOLS for d in days()]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(download_one,out,s,d):(s,d) for s,d in tasks}
        for n,future in enumerate(as_completed(futures),1):
            try:
                page_results[futures[future]]=future.result()
            except Exception:
                for pending in futures:pending.cancel()
                raise
            if n%50==0 or n==len(tasks):print(f'positioning archives verified {n}/{len(tasks)}',flush=True)
    raw_receipts={}
    for symbol in SYMBOLS:
        pages=[page_results[(symbol,day)] for day in days()]
        frame=full_frame([p[0] for p in pages]);records=[p[1] for p in pages]
        buf=io.BytesIO();frame.to_parquet(buf,index=False)
        write_immutable(out/symbol/'observations.parquet',buf.getvalue())
        write_immutable(out/symbol/'source_manifest.json',encode(provenance(symbol,records)))
        for day in days():
            key=f'{symbol}/{day.isoformat()}'
            raw_receipts[key]=sha((out/'raw'/key/'receipt.json').read_bytes())
    write_immutable(out/'collection.json',encode(collection(source_hash)))
    if Path(__file__).read_bytes()!=source or runtime()!=initial_runtime:
        raise ValueError('Collector source/runtime changed during acquisition')
    seal=dict(complete=True,source_sha256=source_hash,runtime=initial_runtime,
              files={name:sha((out/name).read_bytes()) for name in sorted(expected_files())},raw_receipts=raw_receipts)
    verify(out,seal)
    write_immutable(out/'complete.json',encode(seal))
    return seal


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('data_cache/positioning-metrics-1y'))
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    seal=run(args.out,args.workers,args.verify_only)
    print(json.dumps(dict(complete=seal['complete'],archives=len(seal['raw_receipts']),network_used=not args.verify_only)))

if __name__=='__main__':main()
