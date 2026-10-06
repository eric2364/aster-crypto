import csv
from datetime import date,timedelta
import io
import json
import zipfile
import pandas as pd
import pytest
from examples.positioning import collect_archives as c

DAY=date(2025,10,5)
SYMBOL='1000PEPEUSDT'


def archive(symbol=SYMBOL,day=DAY,mutate=None,end_labels=False,reverse=False):
    times=pd.date_range(pd.Timestamp(day,tz='UTC'),periods=288,freq='5min')
    if end_labels:times+=pd.Timedelta(minutes=5)
    rows=[dict(create_time=t.strftime('%Y-%m-%d %H:%M:%S'),symbol=symbol,
               **{k:'1.25' for k in c.NUMERIC}) for t in times]
    if mutate:mutate(rows)
    if reverse:rows.reverse()
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=c.SCHEMA)
    writer.writeheader();writer.writerows(rows)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:z.writestr(f'{symbol}-metrics-{day}.csv',stream.getvalue())
    return output.getvalue()


@pytest.fixture
def tiny(monkeypatch):
    monkeypatch.setattr(c,'START',DAY);monkeypatch.setattr(c,'END',DAY+timedelta(days=1))
    monkeypatch.setattr(c,'SYMBOLS',(SYMBOL,))


def fake_request(url):
    raw=archive(reverse=True)
    if url.endswith('.CHECKSUM'):
        name=url.rsplit('/',1)[-1][:-9]
        return f'{c.sha(raw)}  {name}\n'.encode(),{'fixture':'checksum'},'2026-10-06T00:00:00+00:00'
    return raw,{'fixture':'zip'},'2026-10-06T00:00:00+00:00'


def test_unsorted_native_points_preserved():
    frame,diag=c.parse_archive(archive(reverse=True),SYMBOL,DAY)
    assert len(frame)==288 and frame.timestamp.is_monotonic_increasing
    assert frame.original_row_index.iloc[0]==287
    assert frame.instrument_id.iloc[0]=='binance:perpetual:1000PEPEUSDT'
    assert frame.sum_open_interest.iloc[0]==1.25
    assert not diag['original_strictly_increasing']
    assert 'available_at' not in frame
    assert frame.source_create_time.iloc[0]=='2025-10-05 00:00:00'


@pytest.mark.parametrize('key,value',[('sum_open_interest','NaN'),('sum_open_interest_value','inf'),
                                    ('count_long_short_ratio','0'),('sum_taker_long_short_vol_ratio','-1'),
                                    ('sum_toptrader_long_short_ratio','')])
def test_missing_invalid_values_fail_closed(key,value):
    with pytest.raises(ValueError):c.parse_archive(archive(mutate=lambda rows:rows[1].update({key:value})),SYMBOL,DAY)


@pytest.mark.parametrize('kind',['missing','duplicate','symbol','outside','offgrid'])
def test_identity_grid_corruption(kind):
    def mutate(rows):
        if kind=='missing':rows.pop()
        elif kind=='duplicate':rows[1]['create_time']=rows[0]['create_time']
        elif kind=='symbol':rows[1]['symbol']='PEPEUSDT'
        elif kind=='outside':rows[1]['create_time']='2025-10-04 23:55:00'
        else:rows[1]['create_time']='2025-10-05 00:06:00'
    with pytest.raises(ValueError):c.parse_archive(archive(mutate=mutate),SYMBOL,DAY)


def test_end_labelled_kept_but_not_shifted(tiny):
    frame,diag=c.parse_archive(archive(end_labels=True),SYMBOL,DAY)
    assert diag['observed_label_grid']=='file-day-end-grid'
    assert frame.timestamp.iloc[-1]==pd.Timestamp('2025-10-06',tz='UTC')
    with pytest.raises(ValueError,match='cross-day'):c.full_frame([frame])


def test_checksum_native_name_and_body():
    raw=archive();name=f'{SYMBOL}-metrics-{DAY}.zip'
    c.check_checksum(raw,f'{c.sha(raw)} *{name}'.encode(),name)
    with pytest.raises(ValueError):c.check_checksum(raw,f'{c.sha(raw)} PEPEUSDT.zip'.encode(),name)
    with pytest.raises(ValueError):c.check_checksum(raw,b'0'*64+b' '+name.encode(),name)


def test_bounded_symbols_dates_workers(tmp_path,tiny):
    for symbol,day in [('PEPEUSDT',DAY),(SYMBOL,DAY-timedelta(days=1))]:
        with pytest.raises(ValueError):c.identity(symbol,day)
    for workers in [0,5]:
        with pytest.raises(ValueError):c.run(tmp_path,workers)


def test_complete_offline_and_resume(tmp_path,tiny,monkeypatch):
    calls=[]
    monkeypatch.setattr(c,'request',lambda url:(calls.append(url) or fake_request(url)))
    seal=c.run(tmp_path,2)
    assert len(calls)==2 and len(seal['raw_receipts'])==1
    monkeypatch.setattr(c,'request',lambda _:pytest.fail('No network allowed for sealed/offline verification'))
    assert c.run(tmp_path,verify_only=True)==seal
    assert c.run(tmp_path)==seal
    manifest=json.loads((tmp_path/SYMBOL/'source_manifest.json').read_text())
    assert manifest['original_delivery_availability_verified'] is False
    assert manifest['archives'][0]['diagnostic']['original_strictly_increasing'] is False


def test_download_interruption_does_not_claim_page(tmp_path,tiny,monkeypatch):
    def fail(url):
        if url.endswith('.CHECKSUM'):raise TimeoutError('Interrupted')
        return fake_request(url)
    monkeypatch.setattr(c,'request',fail)
    with pytest.raises(TimeoutError):c.download_one(tmp_path,SYMBOL,DAY)
    assert not (tmp_path/'raw'/SYMBOL/str(DAY)).exists()
    monkeypatch.setattr(c,'request',fake_request)
    c.download_one(tmp_path,SYMBOL,DAY)
    monkeypatch.setattr(c,'request',lambda _:pytest.fail('Verified raw page must be reused'))
    c.download_one(tmp_path,SYMBOL,DAY)


def test_partial_raw_is_preserved_not_overwritten(tmp_path,tiny,monkeypatch):
    folder=tmp_path/'raw'/SYMBOL/str(DAY);folder.mkdir(parents=True)
    (folder/'archive.zip').write_bytes(b'partial')
    monkeypatch.setattr(c,'request',lambda _:pytest.fail('No silent refresh'))
    with pytest.raises(ValueError,match='Incomplete'):c.download_one(tmp_path,SYMBOL,DAY)
    assert (folder/'archive.zip').read_bytes()==b'partial'


@pytest.mark.parametrize('target',['observations.parquet','source_manifest.json'])
def test_resealed_normalized_tampering_rejected(tmp_path,tiny,monkeypatch,target):
    monkeypatch.setattr(c,'request',fake_request);c.run(tmp_path)
    path=tmp_path/SYMBOL/target
    if target.endswith('parquet'):
        frame=pd.read_parquet(path);frame.loc[0,'sum_open_interest']=99;frame.to_parquet(path,index=False)
    else:
        x=json.loads(path.read_text());x['availability_verified']=True;path.write_bytes(c.encode(x))
    seal=json.loads((tmp_path/'complete.json').read_text());seal['files'][f'{SYMBOL}/{target}']=c.sha(path.read_bytes())
    (tmp_path/'complete.json').write_bytes(c.encode(seal))
    with pytest.raises((ValueError,AssertionError)):c.verify(tmp_path)


def test_namespace_paths_fail_before_read(tmp_path,tiny,monkeypatch):
    monkeypatch.setattr(c,'request',fake_request);c.run(tmp_path)
    seal=json.loads((tmp_path/'complete.json').read_text());seal['files']['/outside']='a'
    (tmp_path/'complete.json').write_bytes(c.encode(seal))
    with pytest.raises(ValueError,match='namespace'):c.verify(tmp_path)


def test_runtime_changed_during_acquisition_no_completion(tmp_path,tiny,monkeypatch):
    original=c.runtime;calls=[0]
    def request(url):
        calls[0]+=1
        if calls[0]==2:monkeypatch.setattr(c,'runtime',lambda:{**original(),'python':'changed'})
        return fake_request(url)
    monkeypatch.setattr(c,'request',request)
    with pytest.raises(ValueError,match='runtime changed'):c.run(tmp_path)
    assert not (tmp_path/'complete.json').exists()


def test_checksum_valid_invalid_source_preserved(tmp_path,tiny,monkeypatch):
    raw=archive(mutate=lambda rows:rows[1].update(sum_open_interest='NaN'))
    def request(url):
        if url.endswith('.CHECKSUM'):
            name=url.rsplit('/',1)[-1][:-9]
            return f'{c.sha(raw)} {name}'.encode(),{},'2026-10-06T00:00:00+00:00'
        return raw,{},'2026-10-06T00:00:00+00:00'
    monkeypatch.setattr(c,'request',request)
    with pytest.raises(ValueError,match='evidence preserved'):c.download_one(tmp_path,SYMBOL,DAY)
    folder=tmp_path/'raw'/SYMBOL/str(DAY)
    assert (folder/'archive.zip').read_bytes()==raw
    assert json.loads((folder/'receipt.json').read_text())['parse_status']=='rejected'
    monkeypatch.setattr(c,'request',lambda _:pytest.fail('Rejected source is immutable, never refreshed silently'))
    with pytest.raises(ValueError):c.download_one(tmp_path,SYMBOL,DAY)
    assert not (tmp_path/'complete.json').exists()
