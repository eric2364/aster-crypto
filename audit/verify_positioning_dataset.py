"""Independent offline archive reconstruction. No collector or predictor imports."""
from __future__ import annotations
import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import zipfile
import numpy as np
import pandas as pd
import pyarrow

REPO=Path(__file__).resolve().parents[1]
SOURCE_ANCHOR='241a6502a939a4bfe27dea938bdb5ef151808f46'
COLLECTOR='examples/positioning/collect_archives.py'
START=date(2025,10,5)
END=date(2026,10,5)
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','1000PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
SCHEMA=['create_time','symbol','sum_open_interest','sum_open_interest_value',
        'count_toptrader_long_short_ratio','sum_toptrader_long_short_ratio',
        'count_long_short_ratio','sum_taker_long_short_vol_ratio']
BASE='https://data.binance.vision/data/futures/um/daily/metrics'


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(data):return hashlib.sha256(data).hexdigest()


def read_json(path):return json.loads(path.read_bytes())


def runtime():return dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,pyarrow=pyarrow.__version__)


def anchored_collector():
    body=subprocess.run(['git','show',f'{SOURCE_ANCHOR}:{COLLECTOR}'],cwd=REPO,check=True,capture_output=True).stdout
    require((REPO/COLLECTOR).read_bytes()==body,'Current collector differs from pre-acquisition Git anchor')
    return body


def dates():return [START+timedelta(days=k) for k in range((END-START).days)]


def page_identity(symbol,day):
    name=f'{symbol}-metrics-{day.isoformat()}.zip';url=f'{BASE}/{symbol}/{name}'
    return dict(symbol=symbol,day=day.isoformat(),name=name,url=url,checksum_url=url+'.CHECKSUM')


def parse_zip(raw,symbol,day):
    """Independent scalar CSV interpretation; retained labels, never predictor timing."""
    require(symbol in SYMBOLS and day in dates(),'Native identity/day outside declared window')
    member=f'{symbol}-metrics-{day.isoformat()}.csv'
    with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
        require(zipped.namelist()==[member] and zipped.getinfo(member).file_size<=5_000_000,'ZIP identity/size mismatch')
        body=zipped.read(member)
    reader=csv.reader(io.StringIO(body.decode('utf-8-sig')))
    require(next(reader,None)==SCHEMA,'CSV schema mismatch')
    observations=[];labels=[]
    lower=datetime.combine(day,datetime.min.time(),tzinfo=timezone.utc)
    for position,row in enumerate(reader):
        require(len(row)==8 and row[1]==symbol,'CSV width/native identity mismatch')
        label=row[0]
        require(bool(re.match(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}',label)),'CSV timestamp has no explicit time')
        timestamp=datetime.fromisoformat(label)
        if timestamp.tzinfo is None:timestamp=timestamp.replace(tzinfo=timezone.utc)
        timestamp=timestamp.astimezone(timezone.utc)
        require(lower<=timestamp<=lower+timedelta(days=1),'CSV timestamp outside archive bounds')
        numeric=[float(value) for value in row[2:]]
        require(all(np.isfinite(value) and value>0 for value in numeric),'Nonfinite/nonpositive required observation')
        observations.append(dict(timestamp=timestamp,instrument_id=f'binance:perpetual:{symbol}',
                                 source_symbol=symbol,source_day=day.isoformat(),source_create_time=label,
                                 original_row_index=position,**dict(zip(SCHEMA[2:],numeric))))
        labels.append(timestamp)
    start_grid={lower+timedelta(minutes=5*k) for k in range(288)}
    end_grid={lower+timedelta(minutes=5*(k+1)) for k in range(288)}
    actual=set(labels)
    require(len(labels)==288 and len(actual)==288 and (actual==start_grid or actual==end_grid),'Missing/duplicate/off-grid archive labels')
    frame=pd.DataFrame(observations).sort_values('timestamp').reset_index(drop=True)
    frame['timestamp']=pd.DatetimeIndex(frame.timestamp).as_unit('ns')
    diagnostic=dict(schema=SCHEMA,csv_sha256=sha(body),rows=288,
                    original_first=labels[0].isoformat(),original_last=labels[-1].isoformat(),
                    original_strictly_increasing=all(a<b for a,b in zip(labels,labels[1:])),
                    sorted_for_normalization=True,five_minute_grid_assumption=True,
                    observed_label_grid='file-day-start-grid' if actual==start_grid else 'file-day-end-grid')
    return frame,diagnostic


def expected_manifest(symbol,records):
    return dict(symbol=symbol,instrument_id=f'binance:perpetual:{symbol}',rows=len(dates())*288,
                start=START.isoformat(),end_exclusive=END.isoformat(),schema=SCHEMA,
                archives=records,grid='Explicit assumed complete 300-second UTC grid; missing observations fail closed',
                timestamp='UTC assumed for offset-free create_time; raw labels/file date/order retained; no period-label shifts',
                original_delivery_availability_verified=False,available_at_not_supplied=True,
                units='Source-native OI quantity and reported OI value preserved; no historical contract/unit guarantee',
                interpretation='OI value changes are not quantity changes; no prices/features/outcomes constructed',
                native_pepe='1000PEPEUSDT retained without rescaling',interpolation=False,
                source_documentation='https://github.com/binance/binance-public-data')


def expected_collection(source):
    return dict(start=START.isoformat(),end_exclusive=END.isoformat(),native_symbols=list(SYMBOLS),
                rows_per_symbol=len(dates())*288,archives=len(dates())*len(SYMBOLS),source_sha256=source,
                runtime=runtime(),availability_verified=False,economic_features_or_outcomes=False)


def namespace(folder,names):
    require(folder.is_dir() and not folder.is_symlink(),'Expected real directory absent')
    require({p.name for p in folder.iterdir()}==set(names),'Unexpected/missing dataset namespace')
    require(all(not p.is_symlink() for p in folder.iterdir()),'Symlink source/output unsupported')


def verify_dataset(root):
    root=Path(root)
    auditor_bytes=Path(__file__).read_bytes();collector_bytes=anchored_collector();source_sha=sha(collector_bytes)
    versions=runtime();before={}
    def capture(path):
        require(path.is_file() and not path.is_symlink(),'Missing/symlink evidence file')
        body=path.read_bytes();before[path]=sha(body);return body
    namespace(root,{'raw','complete.json','collection.json','executed_source.py',*SYMBOLS})
    seal_bytes=capture(root/'complete.json');seal=json.loads(seal_bytes)
    expected_files={f'{s}/{name}' for s in SYMBOLS for name in ('observations.parquet','source_manifest.json')}|{'collection.json','executed_source.py'}
    require(set(seal)=={'complete','source_sha256','runtime','files','raw_receipts'} and seal['complete'] is True,'Incomplete/unknown completion seal')
    require(isinstance(seal['files'],dict) and set(seal['files'])==expected_files,'Seal file namespace/traversal mismatch')
    require(seal['source_sha256']==source_sha and seal['runtime']==versions,'Frozen collector/runtime mismatch')
    expected_raw={f'{s}/{day.isoformat()}' for s in SYMBOLS for day in dates()}
    require(isinstance(seal['raw_receipts'],dict) and set(seal['raw_receipts'])==expected_raw,'Raw receipt namespace mismatch')
    for name,digest in seal['files'].items():require(sha(capture(root/name))==digest,'Sealed normalized/source bytes changed')
    require((root/'executed_source.py').read_bytes()==collector_bytes,'Executed collector archive differs from Git anchor')
    require(read_json(root/'collection.json')==expected_collection(source_sha),'Collection metadata mismatch')
    namespace(root/'raw',SYMBOLS)
    expected_index=pd.date_range(pd.Timestamp(START,tz='UTC'),pd.Timestamp(END,tz='UTC'),freq='5min',inclusive='left').as_unit('ns')
    checks=[]
    for symbol in SYMBOLS:
        namespace(root/symbol,('observations.parquet','source_manifest.json'))
        namespace(root/'raw'/symbol,[day.isoformat() for day in dates()])
        chunks=[];records=[];unordered=0;regimes={}
        for day in dates():
            page=root/'raw'/symbol/day.isoformat();namespace(page,('archive.zip','checksum.txt','receipt.json'))
            raw=capture(page/'archive.zip');checksum=capture(page/'checksum.txt');receipt_bytes=capture(page/'receipt.json')
            record=json.loads(receipt_bytes);identity=page_identity(symbol,day)
            require(set(record)=={'identity','retrieved_at','checksum_retrieved_at','response_headers',
                                 'checksum_response_headers','archive_sha256','checksum_sha256','archive_bytes',
                                 'diagnostic','acquisition_source_sha256','parse_status','parse_error'},'Unknown/missing raw receipt fields')
            require(record.get('identity')==identity,'Raw URL/native/day identity mismatch')
            require(record.get('acquisition_source_sha256')==source_sha,'Raw acquisition source differs from frozen collector')
            for key in ('retrieved_at','checksum_retrieved_at'):
                clock=datetime.fromisoformat(record[key])
                require(clock.tzinfo is not None and clock.utcoffset()==timedelta(0),'Retrieval receipt is not explicit UTC')
            require(isinstance(record.get('response_headers'),dict) and isinstance(record.get('checksum_response_headers'),dict),'Raw headers absent')
            require(record.get('archive_sha256')==sha(raw) and record.get('checksum_sha256')==sha(checksum)
                    and type(record.get('archive_bytes')) is int and record['archive_bytes']==len(raw),'Raw source hashes/size mismatch')
            fields=checksum.decode('ascii').split()
            require(len(fields)==2 and bool(re.fullmatch('[a-fA-F0-9]{64}',fields[0]))
                    and fields[1] in (identity['name'],'*'+identity['name']) and fields[0].lower()==sha(raw),'Official CHECKSUM identity/content mismatch')
            frame,diagnostic=parse_zip(raw,symbol,day)
            require(record.get('parse_status')=='verified' and record.get('parse_error') is None and record.get('diagnostic')==diagnostic,'Raw parser receipt differs from independent interpretation')
            require(seal['raw_receipts'][f'{symbol}/{day.isoformat()}']==sha(receipt_bytes),'Raw receipt completion seal differs')
            chunks.append(frame);records.append(record)
            unordered+=not diagnostic['original_strictly_increasing']
            grid=diagnostic['observed_label_grid'];regimes[grid]=regimes.get(grid,0)+1
        rebuilt=pd.concat(chunks,ignore_index=True).sort_values('timestamp').reset_index(drop=True)
        require(pd.DatetimeIndex(rebuilt.timestamp).equals(expected_index),'Annual label grid has duplicate/gap/outside-year observations')
        actual=pd.read_parquet(root/symbol/'observations.parquet')
        require('available_at' not in actual.columns,'Collector must not fabricate historical availability')
        pd.testing.assert_frame_equal(rebuilt,actual,check_exact=True)
        require(read_json(root/symbol/'source_manifest.json')==expected_manifest(symbol,records),'Native source manifest differs from raw reconstruction')
        checks.append(dict(native_symbol=symbol,instrument_id=f'binance:perpetual:{symbol}',archives=len(records),rows=len(actual),
                           numeric_values_checked=len(actual)*6,unordered_source_archives=int(unordered),observed_label_grid_counts=regimes,
                           exact_normalization_reconstruction_passed=True))
    require(anchored_collector()==collector_bytes and runtime()==versions,'Collector/runtime changed during audit')
    for path,digest in before.items():require(sha(path.read_bytes())==digest,'Evidence changed during audit')
    require(Path(__file__).read_bytes()==auditor_bytes,'Independent auditor source changed during audit')
    return dict(complete=True,errors=[],source_anchor=SOURCE_ANCHOR,collector_sha256=source_sha,
                auditor_sha256=sha(auditor_bytes),source_unchanged_during_audit=True,
                auditor_source_unchanged=True,completed_at_utc=datetime.now(timezone.utc).isoformat(),
                complete_seal_sha256=sha(seal_bytes),exact_normalization_reconstruction_passed=True,
                source_and_runtime_reconstruction_passed=True,evidence_unchanged_during_audit=True,
                normalized_source_file_count=len(expected_files),raw_archive_count=len(expected_raw),
                raw_source_files_checked=3*len(expected_raw),numeric_values_checked=sum(c['numeric_values_checked'] for c in checks),
                original_delivery_availability_verified=False,historical_units_verified=False,
                utc_and_five_minute_grid_are_explicit_assumptions=True,economic_features_or_outcomes_inspected=False,
                checks=checks,runtime=versions)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=Path('data_cache/positioning-metrics-1y'))
    parser.add_argument('--output',type=Path,default=Path('audit/positioning_dataset_evidence.json'))
    args=parser.parse_args()
    require(not args.output.exists(),'Preserve existing audit evidence; choose a fresh output path')
    evidence=verify_dataset(args.dataset)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as file:json.dump(evidence,file,indent=2,allow_nan=False);file.write('\n')
    print(json.dumps({k:evidence[k] for k in ('complete','raw_archive_count','numeric_values_checked','auditor_sha256')}))


if __name__=='__main__':main()
