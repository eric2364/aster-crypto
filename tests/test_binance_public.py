"""Official-source ingestion audit using only in-memory archives and mocked fetches."""
from io import BytesIO
import hashlib
import json
import urllib.error
import urllib.parse
import zipfile

import pandas as pd
import pytest

from aster.data import binance_public as bp
from aster.data.validation import normalize_funding
from aster.backtest.models import Instrument

T = pd.Timestamp('2025-01-01', tz='UTC')


def archive(rows, header=False):
    buf = BytesIO()
    text = 'open_time,open,high,low,close,volume,close_time,quote_volume,count\n' if header else ''
    text += '\n'.join(','.join(map(str,row)) for row in rows) + '\n'
    with zipfile.ZipFile(buf,'w') as z: z.writestr('BTCUSDT-1h.csv',text)
    return buf.getvalue()


def row(stamp, unit='ms'):
    divisor = 1000000 if unit == 'ms' else 1000
    return [stamp.value//divisor,100,101,99,100,5,0,500,3]


@pytest.mark.parametrize('header', [False,True])
def test_futures_milliseconds_and_spot_microseconds_preserve_first_row(header):
    parsed = bp.parse_archive(archive([row(T),row(T+pd.Timedelta(hours=1),'us')],header))
    assert parsed.timestamp.tolist() == [T,T+pd.Timedelta(hours=1)]
    assert parsed.volume.tolist() == [5,5]
    assert parsed.quote_volume.tolist() == [500,500]


def test_checksum_mismatch_rejects_before_cache_or_parse(monkeypatch,tmp_path):
    payload=archive([row(T)])
    monkeypatch.setattr(bp,'fetch',lambda url: b'0'*64+b' file.zip' if url.endswith('CHECKSUM') else payload)
    with pytest.raises(ValueError,match='Checksum mismatch'):
        bp.get_archive('https://example.test/file.zip',tmp_path)
    assert not list(tmp_path.iterdir())


def test_checksum_verified_cache_is_revalidated(monkeypatch,tmp_path):
    payload=archive([row(T)])
    digest=hashlib.sha256(payload).hexdigest(); calls=[]
    def fetch(url):
        calls.append(url)
        return (digest+' file.zip').encode() if url.endswith('CHECKSUM') else payload
    monkeypatch.setattr(bp,'fetch',fetch)
    parsed,entry=bp.get_archive('https://example.test/file.zip',tmp_path)
    assert entry['checksum_verified'] and entry['sha256']==digest
    assert parsed.timestamp.iloc[0]==T
    calls.clear(); bp.get_archive('https://example.test/file.zip',tmp_path)
    assert len(calls)==1 and calls[0].endswith('CHECKSUM')
    (tmp_path/('file.zip.'+digest)).write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='Checksum mismatch'):
        bp.get_archive('https://example.test/file.zip',tmp_path)


def test_daily_fallback_includes_partial_final_calendar_day(monkeypatch,tmp_path):
    calls=[]
    def get(url,cache):
        calls.append(url)
        if '/monthly/' in url:
            raise urllib.error.HTTPError(url,404,'missing',None,None)
        day=pd.Timestamp(url.rsplit('-',3)[-3]+'-'+url.rsplit('-',3)[-2]+'-'+url.rsplit('-',3)[-1].removesuffix('.zip'),tz='UTC')
        times=pd.date_range(day,periods=24,freq='h')
        return pd.DataFrame({'timestamp':times,'open':100,'high':100,'low':100,'close':100,'volume':1}),{'url':url}
    monkeypatch.setattr(bp,'get_archive',get)
    start=T+pd.Timedelta(hours=12); end=T+pd.Timedelta(days=1,hours=12)
    frame,_=bp.archive_series('BTCUSDT','1h','spot','klines',start,end,tmp_path)
    assert len(frame)==24
    assert frame.timestamp.min()==start
    assert frame.timestamp.max()==end-pd.Timedelta(hours=1)
    assert len([url for url in calls if '/daily/' in url])==2


@pytest.mark.parametrize('fault,reason',[('missing','Incomplete interval coverage'),('duplicate','Duplicate archived')])
def test_full_coverage_missing_or_duplicate_candles_rejected(monkeypatch,tmp_path,fault,reason):
    times=pd.date_range(T,periods=24,freq='h')
    if fault=='missing': times=times.delete(3)
    else: times=times.append(times[[3]])
    monkeypatch.setattr(bp,'get_archive',lambda url,cache:(pd.DataFrame({'timestamp':times}),{}))
    with pytest.raises(ValueError,match=reason):
        bp.archive_series('BTCUSDT','1h','spot','klines',T,T+pd.Timedelta(days=1),tmp_path)


@pytest.mark.parametrize('repair_fault', [None,'still_missing','duplicate_missing'])
def test_official_daily_repair_selects_only_missing_observations(monkeypatch,tmp_path,repair_fault):
    times=pd.date_range(T,periods=24,freq='h')
    original=pd.DataFrame({'timestamp':times.delete(3),'close':100})
    repaired=pd.DataFrame({'timestamp':times,'close':999})
    if repair_fault=='still_missing': repaired=repaired.drop(index=3)
    elif repair_fault=='duplicate_missing': repaired=pd.concat([repaired,repaired.iloc[[3]]])
    calls=[]
    def get(url,cache):
        calls.append(url)
        return (original.copy() if '/monthly/' in url else repaired.copy()),{'url':url}
    monkeypatch.setattr(bp,'get_archive',get)
    if repair_fault:
        with pytest.raises(ValueError,match='Incomplete interval coverage|Duplicate'):
            bp.archive_series('BTCUSDT','1h','perpetual','markPriceKlines',T,T+pd.Timedelta(days=1),tmp_path)
    else:
        frame,sources=bp.archive_series('BTCUSDT','1h','perpetual','markPriceKlines',T,T+pd.Timedelta(days=1),tmp_path)
        assert len(frame)==24 and not frame.timestamp.duplicated().any()
        assert frame.close.iloc[3]==999
        assert frame.close.drop(index=3).eq(100).all()
        assert len(sources)==2 and 'repair' in sources[-1]['purpose']
    assert len(calls)==2


def funding_row(milliseconds,rate='0.001',mark='100'):
    return {'fundingTime':milliseconds,'fundingRate':rate,'markPrice':mark}


def test_funding_pagination_cursor_advances_one_millisecond(monkeypatch,tmp_path):
    epoch=T.value//1000000; calls=[]
    first=[funding_row(epoch+i) for i in range(1000)]
    def fetch(url):
        query=urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        cursor=int(query['startTime'][0]); calls.append(cursor)
        return json.dumps(first if cursor==epoch else [funding_row(epoch+1000,rate='-0.002')]).encode()
    monkeypatch.setattr(bp,'fetch',fetch)
    frame,sources=bp.funding_history('BTCUSDT',T,T+pd.Timedelta(days=1),tmp_path)
    assert calls==[epoch,epoch+1000]
    assert len(frame)==1001 and len(sources)==2
    assert not frame.timestamp.duplicated().any()
    assert frame.funding_rate.iloc[:1000].eq(.001).all()
    assert frame.funding_rate.iloc[-1]==-.002  # signs and per-settlement rate retained


def test_repeated_funding_page_is_rejected_without_infinite_loop(monkeypatch,tmp_path):
    epoch=T.value//1000000
    first=[funding_row(epoch+i) for i in range(1000)]
    monkeypatch.setattr(bp,'fetch',lambda url:json.dumps(first).encode())
    with pytest.raises(ValueError,match='cursor did not advance'):
        bp.funding_history('BTCUSDT',T,T+pd.Timedelta(days=1),tmp_path)


def test_duplicate_funding_is_not_silently_deduplicated(monkeypatch,tmp_path):
    epoch=T.value//1000000
    monkeypatch.setattr(bp,'fetch',lambda url:json.dumps([funding_row(epoch),funding_row(epoch)]).encode())
    frame,_=bp.funding_history('BTCUSDT',T,T+pd.Timedelta(days=1),tmp_path)
    spec=Instrument('binance:perpetual:BTCUSDT','binance','BTCUSDT','perpetual')
    with pytest.raises(ValueError,match='Duplicate funding'):
        normalize_funding(frame,{spec.id:spec})


@pytest.mark.parametrize('mark',[None,'0','nan','inf'])
def test_missing_or_invalid_funding_mark_rejected(monkeypatch,tmp_path,mark):
    record=funding_row(T.value//1000000)
    if mark is None: record.pop('markPrice')
    else: record['markPrice']=mark
    monkeypatch.setattr(bp,'fetch',lambda url:json.dumps([record]).encode())
    spec=Instrument('binance:perpetual:BTCUSDT','binance','BTCUSDT','perpetual')
    with pytest.raises((ValueError,KeyError),match='mark|markPrice|Invalid|Missing'):
        frame,_=bp.funding_history('BTCUSDT',T,T+pd.Timedelta(days=1),tmp_path)
        normalize_funding(frame,{spec.id:spec})
