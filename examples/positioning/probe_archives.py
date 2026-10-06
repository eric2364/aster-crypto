"""Small official archive coverage probe. No predictors, prices or trading outcomes.

Raw downloads stay local; this probe does not establish full-year coverage or
historical delivery time. It records exact schemas, native symbols and clocks.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SYMBOLS = ('BTCUSDT','ETHUSDT','DOGEUSDT','1000PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
DATES = ('2025-10-05','2026-04-05','2026-10-04')
BASE = 'https://data.binance.vision/data/futures/um/daily/metrics'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def request(url):
    req = urllib.request.Request(url, headers={'User-Agent':'aster-crypto-archive-feasibility/1'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(), dict(r.headers), datetime.now(timezone.utc).isoformat()

def inspect(raw, symbol, day):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        expected = f'{symbol}-metrics-{day}.csv'
        if z.namelist() != [expected]:
            raise ValueError('Unexpected ZIP members')
        data = z.read(expected)
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    schema = reader.fieldnames
    if not schema or not {'create_time','symbol','sum_open_interest','sum_open_interest_value'} <= set(schema):
        raise ValueError('Missing core positioning fields')
    rows = list(reader)
    clocks = []
    for row in rows:
        if None in row or None in row.values() or row['symbol'] != symbol:
            raise ValueError('Malformed row or native symbol mismatch')
        # Official create_time is a textual archive clock. UTC is an explicit
        # parser assumption when no offset is supplied, not a delivery receipt.
        t = datetime.fromisoformat(row['create_time'])
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        t = t.astimezone(timezone.utc)
        if t.date().isoformat() != day:
            raise ValueError('Archive day mismatch')
        clocks.append(t)
    if not clocks:
        raise ValueError('Empty metrics archive')
    gaps = [(b-a).total_seconds() for a,b in zip(clocks, clocks[1:])]
    expected_clocks = {datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()+300*k for k in range(288)}
    actual = {t.timestamp() for t in clocks}
    return dict(schema=schema,rows=len(rows),csv_sha256=sha(data),
                first=clocks[0].isoformat(),last=clocks[-1].isoformat(),
                strictly_increasing=all(d>0 for d in gaps),duplicate_timestamps=len(clocks)-len(actual),
                observed_spacing_seconds=sorted(set(gaps)),
                missing_assumed_five_minute_clocks=len(expected_clocks-actual),
                extra_assumed_five_minute_clocks=len(actual-expected_clocks),
                original_delivery_time_provided=False,
                timestamp_timezone_interpretation='UTC assumed for offset-free archive create_time')

def one(cache, symbol, day):
    name=f'{symbol}-metrics-{day}.zip'
    url=f'{BASE}/{symbol}/{name}'
    record=dict(symbol=symbol,day=day,url=url,checksum_url=url+'.CHECKSUM')
    try:
        raw,headers,at=request(url)
        check,checkheaders,cat=request(url+'.CHECKSUM')
        fields=check.decode('ascii').split()
        if len(fields)!=2 or not re.fullmatch('[a-fA-F0-9]{64}',fields[0]) or fields[1].lstrip('*')!=name:
            raise ValueError('Malformed official checksum')
        if sha(raw)!=fields[0].lower():
            raise ValueError('Official checksum mismatch')
        parent=cache/symbol
        parent.mkdir(parents=True,exist_ok=True)
        for target,body in [(parent/name,raw),(parent/(name+'.CHECKSUM'),check)]:
            if target.exists() and target.read_bytes()!=body:
                raise ValueError('Existing response differs; preserve previous evidence')
            if not target.exists():
                target.write_bytes(body)
        record.update(status='verified_archive',retrieved_at=at,checksum_retrieved_at=cat,
                      archive_sha256=sha(raw),checksum_sha256=sha(check),archive_bytes=len(raw),
                      response_headers=headers,checksum_response_headers=checkheaders,
                      **inspect(raw,symbol,day))
    except urllib.error.HTTPError as e:
        record.update(status='http_error',http_status=e.code,checked_at=datetime.now(timezone.utc).isoformat())
    except Exception as e:
        record.update(status='verification_error',error=f'{type(e).__name__}: {e}')
    return record

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cache',type=Path,default=Path('data_cache/positioning-probe-1y'))
    ap.add_argument('--receipt',type=Path,default=Path('docs/positioning_archive_probe.json'))
    args=ap.parse_args()
    if args.receipt.exists():
        raise FileExistsError('Use a fresh receipt path; earlier probe must remain preserved')
    tasks=[(s,d) for s in SYMBOLS for d in DATES]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records=list(pool.map(lambda sd:one(args.cache,*sd),tasks))
    result=dict(scope='24 tiny sampled daily archives, not complete year or strategy evidence',
                window_start='2025-10-05T00:00:00+00:00',window_end_exclusive='2026-10-05T00:00:00+00:00',
                source_sha256=sha(Path(__file__).read_bytes()),
                outcomes_inspected=False,receipt_time_is_historical_availability=False,
                records=records,verified_count=sum(r['status']=='verified_archive' for r in records))
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'verified_count':result['verified_count'],'attempted':len(records),
                      'statuses':[(r['symbol'],r['day'],r['status']) for r in records if r['status']!='verified_archive']}))

if __name__=='__main__':
    main()
