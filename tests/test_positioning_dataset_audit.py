"""Independent dataset auditor tests; no production collector imported or invoked."""
import csv
from datetime import date,timedelta
import io
import json
from pathlib import Path
import zipfile
import pandas as pd
import pytest
from audit import verify_positioning_dataset as a

DAY=date(2025,10,5)
SYMS=('BTCUSDT','1000PEPEUSDT')


def encoded(value):return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()


def csv_zip(native,values,day=DAY):
    text=io.StringIO();writer=csv.writer(text);writer.writerow(a.SCHEMA);writer.writerows(values)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(f'{native}-metrics-{day}.csv',text.getvalue())
    return out.getvalue(),text.getvalue().encode()


def source_rows(native):
    return [[(pd.Timestamp(DAY)+pd.Timedelta(minutes=5*k)).strftime('%Y-%m-%d %H:%M:%S'),native,
             str(10+k),str(900+3*k),'1.1','1.2','1.3','1.4'] for k in range(288)][::-1]


@pytest.fixture
def packet(tmp_path,monkeypatch):
    monkeypatch.setattr(a,'START',DAY);monkeypatch.setattr(a,'END',DAY+timedelta(days=1));monkeypatch.setattr(a,'SYMBOLS',SYMS)
    source=b'known-synthetic-acquisition-source';monkeypatch.setattr(a,'anchored_collector',lambda:source)
    out=tmp_path/'observations';out.mkdir();(out/'executed_source.py').write_bytes(source)
    raw_seals={}
    for native in SYMS:
        values=source_rows(native);raw,body=csv_zip(native,values);identity=a.page_identity(native,DAY)
        diagnostic=dict(schema=a.SCHEMA,csv_sha256=a.sha(body),rows=288,
                        original_first='2025-10-05T23:55:00+00:00',original_last='2025-10-05T00:00:00+00:00',
                        original_strictly_increasing=False,sorted_for_normalization=True,
                        five_minute_grid_assumption=True,observed_label_grid='file-day-start-grid')
        checksum=(a.sha(raw)+' '+identity['name']).encode()
        receipt=dict(identity=identity,retrieved_at='2026-10-06T00:00:00+00:00',checksum_retrieved_at='2026-10-06T00:00:01+00:00',
                     response_headers={},checksum_response_headers={},archive_sha256=a.sha(raw),checksum_sha256=a.sha(checksum),
                     archive_bytes=len(raw),diagnostic=diagnostic,acquisition_source_sha256=a.sha(source),parse_status='verified',parse_error=None)
        page=out/'raw'/native/str(DAY);page.mkdir(parents=True)
        (page/'archive.zip').write_bytes(raw);(page/'checksum.txt').write_bytes(checksum);(page/'receipt.json').write_bytes(encoded(receipt))
        raw_seals[f'{native}/{DAY}']=a.sha((page/'receipt.json').read_bytes())
        normalized=[]
        for original_index,row in enumerate(values):
            normalized.append(dict(timestamp=pd.Timestamp(row[0],tz='UTC'),instrument_id=f'binance:perpetual:{native}',source_symbol=native,
                                   source_day=str(DAY),source_create_time=row[0],original_row_index=original_index,
                                   **dict(zip(a.SCHEMA[2:],map(float,row[2:])))))
        frame=pd.DataFrame(normalized).sort_values('timestamp').reset_index(drop=True)
        frame.timestamp=pd.DatetimeIndex(frame.timestamp).as_unit('ns')
        destination=out/native;destination.mkdir();frame.to_parquet(destination/'observations.parquet',index=False)
        (destination/'source_manifest.json').write_bytes(encoded(a.expected_manifest(native,[receipt])))
    (out/'collection.json').write_bytes(encoded(a.expected_collection(a.sha(source))))
    names=['executed_source.py','collection.json']+[f'{s}/{name}' for s in SYMS for name in ('observations.parquet','source_manifest.json')]
    seal=dict(complete=True,source_sha256=a.sha(source),runtime=a.runtime(),files={n:a.sha((out/n).read_bytes()) for n in names},raw_receipts=raw_seals)
    (out/'complete.json').write_bytes(encoded(seal))
    return out


def reseal(out,name):
    seal=a.read_json(out/'complete.json');seal['files'][name]=a.sha((out/name).read_bytes());(out/'complete.json').write_bytes(encoded(seal))


def test_reference_reconstructs_known_source_values_native_order_and_provenance(packet):
    before={str(p.relative_to(packet)):p.read_bytes() for p in packet.rglob('*') if p.is_file()}
    certificate=a.verify_dataset(packet)
    assert certificate['complete'] and certificate['raw_archive_count']==2
    assert certificate['numeric_values_checked']==2*288*6 and certificate['raw_source_files_checked']==6
    assert all(record['rows']==288 and record['unordered_source_archives']==1 for record in certificate['checks'])
    assert certificate['original_delivery_availability_verified'] is False and certificate['historical_units_verified'] is False
    frame=pd.read_parquet(packet/'1000PEPEUSDT/observations.parquet')
    assert frame.original_row_index.tolist()==list(range(287,-1,-1)) and frame.sum_open_interest.tolist()==list(range(10,298))
    assert before=={str(p.relative_to(packet)):p.read_bytes() for p in packet.rglob('*') if p.is_file()}


@pytest.mark.parametrize('column',['sum_open_interest','source_create_time','original_row_index','instrument_id','timestamp'])
def test_resealed_normalized_changes_still_rejected_by_independent_archive_reconstruction(packet,column):
    name='1000PEPEUSDT/observations.parquet';path=packet/name;frame=pd.read_parquet(path)
    if column=='timestamp':frame.loc[0,column]+=pd.Timedelta(minutes=5)
    elif column=='instrument_id':frame.loc[0,column]='binance:perpetual:PEPEUSDT'
    elif column=='source_create_time':frame.loc[0,column]='2025-10-05 00:05:00'
    else:frame.loc[0,column]+=1
    frame.to_parquet(path,index=False);reseal(packet,name)
    with pytest.raises(AssertionError):a.verify_dataset(packet)


@pytest.mark.parametrize('defect',['duplicate','offgrid','missing','negative','infinite','wrong_native','outside','date_only'])
def test_independent_csv_parser_fails_invalid_source_without_repair(packet,defect):
    rows=source_rows('BTCUSDT')
    if defect=='duplicate':rows[10]=rows[11].copy()
    elif defect=='offgrid':rows[10][0]='2025-10-05 12:01:00'
    elif defect=='missing':rows.pop(10)
    elif defect=='negative':rows[10][2]='-1'
    elif defect=='infinite':rows[10][2]='nan'
    elif defect=='wrong_native':rows[10][1]='ETHUSDT'
    elif defect=='outside':rows[10][0]='2025-10-04 23:55:00'
    else:rows[10][0]='2025-10-05'
    raw,_=csv_zip('BTCUSDT',rows)
    with pytest.raises(ValueError):a.parse_zip(raw,'BTCUSDT',DAY)


@pytest.mark.parametrize('field',['url','retrieval','source_sha','diagnostic','checksum'])
def test_raw_receipt_reseal_does_not_hide_source_identity_or_semantic_tamper(packet,field):
    page=packet/'raw/BTCUSDT'/str(DAY);path=page/'receipt.json';record=a.read_json(path)
    if field=='url':record['identity']['url']='https://example.com/fake.zip'
    elif field=='retrieval':record['retrieved_at']='2026-10-06T00:00:00'
    elif field=='source_sha':record['acquisition_source_sha256']='0'*64
    elif field=='diagnostic':record['diagnostic']['original_strictly_increasing']=True
    else:
        wrong=(record['archive_sha256']+' ETHUSDT-metrics-2025-10-05.zip').encode()
        (page/'checksum.txt').write_bytes(wrong);record['checksum_sha256']=a.sha(wrong)
    path.write_bytes(encoded(record));seal=a.read_json(packet/'complete.json');seal['raw_receipts'][f'BTCUSDT/{DAY}']=a.sha(path.read_bytes())
    (packet/'complete.json').write_bytes(encoded(seal))
    with pytest.raises(ValueError):a.verify_dataset(packet)


@pytest.mark.parametrize('where',['root','native','raw_native','raw_page'])
def test_extra_unsealed_namespaces_rejected(packet,where):
    parent={'root':packet,'native':packet/'BTCUSDT','raw_native':packet/'raw/BTCUSDT','raw_page':packet/'raw/BTCUSDT'/str(DAY)}[where]
    (parent/'unexpected').mkdir()
    with pytest.raises(ValueError,match='namespace'):a.verify_dataset(packet)


def test_seal_traversal_rejected_before_access(packet):
    seal=a.read_json(packet/'complete.json');seal['files']['../../private']='0'*64
    (packet/'complete.json').write_bytes(encoded(seal))
    with pytest.raises(ValueError,match='namespace/traversal'):a.verify_dataset(packet)


def test_resealed_manifest_cannot_claim_original_availability(packet):
    name='BTCUSDT/source_manifest.json';manifest=a.read_json(packet/name);manifest['original_delivery_availability_verified']=True
    (packet/name).write_bytes(encoded(manifest));reseal(packet,name)
    with pytest.raises(ValueError,match='manifest'):a.verify_dataset(packet)


def test_source_anchor_runtime_and_archived_bytes_guard(packet,monkeypatch):
    monkeypatch.setattr(a,'anchored_collector',lambda:b'different-pre-acquisition-source')
    with pytest.raises(ValueError,match='collector/runtime'):a.verify_dataset(packet)


def test_raw_mutation_during_normalized_comparison_detected_before_certificate(packet,monkeypatch):
    original=a.pd.read_parquet;mutated=[]
    def changing(path,*args,**kwargs):
        frame=original(path,*args,**kwargs)
        if not mutated:
            raw=packet/'raw/BTCUSDT'/str(DAY)/'archive.zip';raw.write_bytes(raw.read_bytes()+b'changed-after-reparse');mutated.append(True)
        return frame
    monkeypatch.setattr(a.pd,'read_parquet',changing)
    with pytest.raises(ValueError,match='Evidence changed during audit'):a.verify_dataset(packet)


def test_assumed_end_label_grid_retained_without_shift(packet):
    values=source_rows('BTCUSDT')
    for row in values:row[0]=(pd.Timestamp(row[0])+pd.Timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    raw,_=csv_zip('BTCUSDT',values);frame,diagnostic=a.parse_zip(raw,'BTCUSDT',DAY)
    assert diagnostic['observed_label_grid']=='file-day-end-grid'
    assert frame.timestamp.iloc[0]==pd.Timestamp('2025-10-05T00:05Z')
    assert frame.timestamp.iloc[-1]==pd.Timestamp('2025-10-06T00:00Z')


def test_resealed_extra_availability_column_is_rejected(packet):
    name='BTCUSDT/observations.parquet';frame=pd.read_parquet(packet/name)
    frame['available_at']=frame.timestamp+pd.Timedelta(minutes=1);frame.to_parquet(packet/name,index=False);reseal(packet,name)
    with pytest.raises(ValueError,match='fabricate historical availability'):a.verify_dataset(packet)


def test_symlink_page_evidence_is_rejected(packet,tmp_path):
    path=packet/'raw/BTCUSDT'/str(DAY)/'archive.zip';external=tmp_path/'external.zip'
    external.write_bytes(path.read_bytes());path.unlink();path.symlink_to(external)
    with pytest.raises(ValueError,match='Symlink'):a.verify_dataset(packet)


def test_auditor_source_changed_mid_reconstruction_cannot_issue_certificate(packet,tmp_path,monkeypatch):
    source=tmp_path/'audit.py';source.write_bytes(b'independent-source-before')
    monkeypatch.setattr(a,'__file__',str(source));original=a.pd.read_parquet
    def change(path,*args,**kwargs):
        result=original(path,*args,**kwargs);source.write_bytes(b'changed-auditor-source');return result
    monkeypatch.setattr(a.pd,'read_parquet',change)
    with pytest.raises(ValueError,match='auditor source changed'):a.verify_dataset(packet)


def test_runtime_changed_during_reconstruction_cannot_issue_certificate(packet,monkeypatch):
    original=a.runtime();counter=[]
    def change():
        counter.append(True)
        return original if len(counter)<=2 else {**original,'pyarrow':'changed-mid-audit'}
    monkeypatch.setattr(a,'runtime',change)
    with pytest.raises(ValueError,match='changed during audit'):a.verify_dataset(packet)
