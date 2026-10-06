"""Independent positioning source/clock audit. Synthetic official-shaped ZIPs only."""
import csv
from datetime import date, timedelta
import io
import json
import zipfile

import pandas as pd
import pytest

from examples.positioning import collect_archives as c

DAY=date(2025,10,5)
NATIVE='1000PEPEUSDT'
FIELDS=['create_time','symbol','sum_open_interest','sum_open_interest_value',
        'count_toptrader_long_short_ratio','sum_toptrader_long_short_ratio',
        'count_long_short_ratio','sum_taker_long_short_vol_ratio']


def rows(day=DAY,native=NATIVE,end_labels=False):
    start=pd.Timestamp(day,tz='UTC')
    return [[(start+pd.Timedelta(minutes=5*(k+int(end_labels)))).strftime('%Y-%m-%d %H:%M:%S'),
             native,str(100+k),str(100000+7*k),'1.1','1.2','1.3','1.4'] for k in range(288)]


def archive(values,day=DAY,native=NATIVE,fields=FIELDS,member=None):
    text=io.StringIO();writer=csv.writer(text);writer.writerow(fields);writer.writerows(values)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(member or f'{native}-metrics-{day}.csv',text.getvalue())
    return out.getvalue()


@pytest.fixture
def short_window(monkeypatch):
    monkeypatch.setattr(c,'START',DAY);monkeypatch.setattr(c,'END',DAY+timedelta(days=1))
    monkeypatch.setattr(c,'SYMBOLS',(NATIVE,))


@pytest.fixture
def collected(short_window,tmp_path,monkeypatch):
    out=tmp_path/'data';raw=archive(rows()[::-1]);name=f'{NATIVE}-metrics-{DAY}.zip'
    check=(c.sha(raw)+'  '+name+'\n').encode();calls=[]
    def response(url):
        calls.append(url)
        return (check if url.endswith('.CHECKSUM') else raw),{'content-type':'application/octet-stream'},'2026-10-06T00:00:00+00:00'
    monkeypatch.setattr(c,'request',response)
    c.run(out,workers=1)
    assert calls==[c.identity(NATIVE,DAY)['url'],c.identity(NATIVE,DAY)['checksum_url']]
    def no_network(*args):raise AssertionError('Offline path invoked network')
    monkeypatch.setattr(c,'request',no_network)
    return out


def reseal_file(out,name):
    seal=json.loads((out/'complete.json').read_text());seal['files'][name]=c.sha((out/name).read_bytes())
    (out/'complete.json').write_bytes(c.encode(seal))


def test_unordered_complete_archive_preserves_native_units_and_original_source_order(short_window):
    original=rows()[::-1];frame,diagnostic=c.parse_archive(archive(original),NATIVE,DAY)
    assert frame.sum_open_interest.tolist()==list(range(100,388))
    assert frame.original_row_index.tolist()==list(range(287,-1,-1))
    assert frame.source_create_time.iloc[0]==original[-1][0]
    assert set(frame.instrument_id)=={'binance:perpetual:1000PEPEUSDT'}
    assert 'available_at' not in frame and not diagnostic['original_strictly_increasing']
    assert frame.timestamp.iloc[0]==pd.Timestamp('2025-10-05T00:00Z')
    assert frame.timestamp.iloc[-1]==pd.Timestamp('2025-10-05T23:55Z')


@pytest.mark.parametrize('kind',['missing','duplicate','extra','offgrid','earlier','later','wrong_native','blank','nan','infinite','negative'])
def test_source_observation_defects_fail_before_normalization(short_window,kind):
    values=rows()
    if kind=='missing':values.pop(14)
    elif kind=='duplicate':values[14]=values[13].copy()
    elif kind=='extra':values.append(values[0].copy())
    elif kind=='offgrid':values[14][0]='2025-10-05 01:11:00'
    elif kind=='earlier':values[0][0]='2025-10-04 23:55:00'
    elif kind=='later':values[-1][0]='2025-10-06 00:05:00'
    elif kind=='wrong_native':values[14][1]='PEPEUSDT'
    else:values[14][3]={'blank':'','nan':'NaN','infinite':'inf','negative':'-1'}[kind]
    with pytest.raises(ValueError):c.parse_archive(archive(values),NATIVE,DAY)


def test_end_labelled_day_retained_but_not_silently_shifted_into_year(short_window):
    frame,diagnostic=c.parse_archive(archive(rows(end_labels=True)),NATIVE,DAY)
    assert diagnostic['observed_label_grid']=='file-day-end-grid'
    assert frame.timestamp.iloc[-1]==pd.Timestamp('2025-10-06T00:00Z')
    with pytest.raises(ValueError,match='no shifts or deduplication'):c.full_frame([frame])


def test_cross_day_label_transition_duplicate_is_not_deduplicated(short_window,monkeypatch):
    monkeypatch.setattr(c,'END',DAY+timedelta(days=2))
    old,_=c.parse_archive(archive(rows(end_labels=True)),NATIVE,DAY)
    following=DAY+timedelta(days=1)
    new,_=c.parse_archive(archive(rows(following),following),NATIVE,following)
    assert old.timestamp.iloc[-1]==new.timestamp.iloc[0]
    assert old.sum_open_interest.iloc[-1]!=new.sum_open_interest.iloc[0]
    with pytest.raises(ValueError):c.full_frame([old,new])


@pytest.mark.parametrize('bad',['wrong_name','wrong_digest','malformed'])
def test_official_checksum_identity_and_bytes_are_both_required(short_window,bad):
    raw=archive(rows());name=f'{NATIVE}-metrics-{DAY}.zip'
    check={'wrong_name':c.sha(raw)+' another.zip','wrong_digest':'0'*64+' '+name,'malformed':c.sha(raw)}[bad]
    with pytest.raises(ValueError):c.check_checksum(raw,check.encode(),name)


def test_offline_replay_and_completed_restart_leave_all_evidence_bytes_unchanged(collected):
    before={str(p.relative_to(collected)):p.read_bytes() for p in collected.rglob('*') if p.is_file()}
    assert c.run(collected,verify_only=True)['complete'] is True
    assert c.run(collected,workers=1)['complete'] is True
    assert {str(p.relative_to(collected)):p.read_bytes() for p in collected.rglob('*') if p.is_file()}==before
    manifest=json.loads((collected/NATIVE/'source_manifest.json').read_text())
    assert manifest['original_delivery_availability_verified'] is False and manifest['available_at_not_supplied'] is True


def test_resealed_normalized_value_cannot_override_source_archive(collected):
    name=f'{NATIVE}/observations.parquet';path=collected/name
    frame=pd.read_parquet(path);frame.loc[0,'sum_open_interest']+=500;frame.to_parquet(path,index=False)
    reseal_file(collected,name)
    with pytest.raises(AssertionError):c.verify(collected)


def test_resealed_manifest_cannot_claim_historical_receipt(collected):
    name=f'{NATIVE}/source_manifest.json';path=collected/name
    manifest=json.loads(path.read_text());manifest['original_delivery_availability_verified']=True
    path.write_bytes(c.encode(manifest));reseal_file(collected,name)
    with pytest.raises(ValueError,match='Source manifest'):c.verify(collected)


@pytest.mark.parametrize('field',['identity','retrieved_at','diagnostic','archive_sha256'])
def test_raw_receipt_tampering_rejected_even_after_outer_receipt_reseal(collected,field):
    path=collected/'raw'/NATIVE/str(DAY)/'receipt.json';receipt=json.loads(path.read_text())
    if field=='identity':receipt[field]['url']='https://example.com/metrics.zip'
    elif field=='retrieved_at':receipt[field]='2026-10-06T08:00:00+08:00'
    elif field=='diagnostic':receipt[field]['rows']=287
    else:receipt[field]='0'*64
    path.write_bytes(c.encode(receipt));seal=json.loads((collected/'complete.json').read_text())
    seal['raw_receipts'][f'{NATIVE}/{DAY}']=c.sha(path.read_bytes())
    (collected/'complete.json').write_bytes(c.encode(seal))
    with pytest.raises(ValueError):c.verify(collected)


def test_seal_path_escape_rejected_before_arbitrary_file_read(collected):
    seal=json.loads((collected/'complete.json').read_text())
    seal['files']['../../unrelated-private-file']='0'*64
    with pytest.raises(ValueError,match='namespace'):c.verify(collected,seal)


def test_runtime_drift_rejected(collected,monkeypatch):
    original=c.runtime();monkeypatch.setattr(c,'runtime',lambda:{**original,'pandas':'different'})
    with pytest.raises(ValueError,match='runtime drift'):c.verify(collected)


def test_partial_raw_page_resume_never_redownloads_or_overwrites(collected):
    path=collected/'raw'/NATIVE/str(DAY)/'checksum.txt';path.unlink()
    before=(path.parent/'archive.zip').read_bytes()
    with pytest.raises(ValueError,match='Incomplete'):c.download_one(collected,NATIVE,DAY)
    assert not path.exists() and (path.parent/'archive.zip').read_bytes()==before


@pytest.mark.parametrize('defect',['missing_numeric','date_only'])
def test_checksum_valid_rejected_source_is_preserved_and_restart_cannot_refresh(short_window,tmp_path,monkeypatch,defect):
    values=rows()
    if defect=='missing_numeric':values[100][2]='NaN'
    else:values[0][0]='2025-10-05'
    raw=archive(values);name=f'{NATIVE}-metrics-{DAY}.zip';check=(c.sha(raw)+' '+name).encode()
    def response(url):return (check if url.endswith('.CHECKSUM') else raw),{},'2026-10-06T00:00:00+00:00'
    monkeypatch.setattr(c,'request',response);out=tmp_path/'rejected'
    with pytest.raises(ValueError,match='raw evidence preserved'):c.run(out,workers=1)
    page=out/'raw'/NATIVE/str(DAY)
    assert (page/'archive.zip').read_bytes()==raw and (page/'checksum.txt').read_bytes()==check
    receipt=json.loads((page/'receipt.json').read_text())
    assert receipt['parse_status']=='rejected' and receipt['parse_error'] and receipt['diagnostic'] is None
    assert receipt['acquisition_source_sha256']==c.sha(c.Path(c.__file__).read_bytes())
    assert not (out/'complete.json').exists() and not (out/NATIVE/'observations.parquet').exists()
    before={p.name:p.read_bytes() for p in page.iterdir()}
    def prohibited(*args):raise AssertionError('Rejected source silently refreshed')
    monkeypatch.setattr(c,'request',prohibited)
    with pytest.raises(ValueError):c.run(out,workers=1)
    assert {p.name:p.read_bytes() for p in page.iterdir()}==before
