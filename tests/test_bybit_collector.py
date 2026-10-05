import base64
import json
import pytest
import pandas as pd
from examples.cross_venue import download_bybit as d


def payload(rows,symbol='1000PEPEUSDT'):
    return {'retCode':0,'result':{'category':'linear','symbol':symbol,'list':rows}}


def candles(endpoint='kline'):
    return [[str(d.START_MS+i*60000),'2','4','1','3',*(['100','250'] if endpoint=='kline' else [])] for i in range(3)]


def test_native_proxy_mapping_and_terminal():
    native='1000PEPEUSDT'
    trade=d.parse_candles(payload(candles()),native,'kline',d.START_MS,d.START_MS+179999)
    marks=d.parse_candles(payload(candles('mark-price-kline')),native,'mark-price-kline',d.START_MS,d.START_MS+179999)
    stop=d.START+pd.Timedelta(minutes=3)
    bars,fund,_=d.normalize(native,trade,marks,[(d.START_MS,.001),(stop.value//1000000,.002)],end=stop)
    assert bars.volume.tolist()==[100,100,100]
    assert bars.instrument_id.iloc[0]=='bybit:perpetual:1000PEPEUSDT'
    assert fund.mark_price.tolist()==[2,3]
    assert fund.boundary.tolist()==[False,True]
    assert fund.mark_price_source.iloc[1]=='END_last_completed_mark_close_proxy'


@pytest.mark.parametrize('mutator',[
    lambda p:p.update(retCode=10006),
    lambda p:p['result'].update(symbol='PEPEUSDT'),
    lambda p:p['result']['list'][0].__setitem__(1,'nan'),
    lambda p:p['result']['list'][0].__setitem__(2,'1'),
    lambda p:p['result']['list'][0].__setitem__(5,'-1'),
    lambda p:p['result']['list'][0].__setitem__(0,str(d.START_MS-60000)),
])
def test_reject_corrupt_pages(mutator):
    p=payload(candles());mutator(p)
    with pytest.raises(ValueError):
        d.parse_candles(p,'1000PEPEUSDT','kline',d.START_MS,d.START_MS+179999)


def test_duplicate_missing_and_misaligned_funding():
    t=d.parse_candles(payload(candles()),'1000PEPEUSDT','kline',d.START_MS,d.START_MS+179999)
    m=d.parse_candles(payload(candles('mark-price-kline')),'1000PEPEUSDT','mark-price-kline',d.START_MS,d.START_MS+179999)
    for bad in [t[:-1],t+[t[0]]]:
        with pytest.raises(ValueError):d.normalize('1000PEPEUSDT',bad,m,[],end=d.START+pd.Timedelta(minutes=3))
    with pytest.raises(ValueError):d.normalize('1000PEPEUSDT',t,m,[(d.START_MS+1,.01)],end=d.START+pd.Timedelta(minutes=3))


def test_bounds():
    for a,b in [(d.START_MS-1,d.START_MS),(d.END_MS,d.END_MS+1),(d.START_MS,d.END_MS)]:
        with pytest.raises(ValueError):d.page_url('kline','BTCUSDT',a,b)
    assert 'startTime' in d.page_url('funding/history','BTCUSDT',d.END_MS,d.END_MS)


def test_offline_sealed_page_and_corruption(tmp_path):
    url=d.page_url('kline','1000PEPEUSDT',d.START_MS,d.START_MS+179999)
    raw=json.dumps(payload(candles())).encode()
    envelope={'url':url,'retrieved_utc':'2026-10-06T00:00:00+00:00','raw_sha256':d.digest(raw),'raw_base64':base64.b64encode(raw).decode()}
    target=tmp_path/'raw'/(d.digest(url.encode())+'.json')
    d.atomic(target,d.encoded(envelope))
    pages=d.Pages(tmp_path,offline=True)
    assert pages.get('kline','1000PEPEUSDT',d.START_MS,d.START_MS+179999)[0]['retCode']==0
    envelope['url']+='BAD';d.atomic(target,d.encoded(envelope))
    with pytest.raises(ValueError):pages.get('kline','1000PEPEUSDT',d.START_MS,d.START_MS+179999)
    with pytest.raises(ValueError):pages.get('kline','BTCUSDT',d.START_MS,d.START_MS+179999)


def test_interrupt_atomic_preserves_committed_page(tmp_path,monkeypatch):
    target=tmp_path/'page.json';target.write_bytes(b'old')
    def fail(*args):raise OSError('simulated interruption')
    monkeypatch.setattr(d.os,'replace',fail)
    with pytest.raises(OSError):d.atomic(target,b'new')
    assert target.read_bytes()==b'old'


def test_global_rate_gate(monkeypatch):
    clock=[0.0];sleeps=[]
    monkeypatch.setattr(d.time,'monotonic',lambda:clock[0])
    def sleep(delay):sleeps.append(delay);clock[0]+=delay
    monkeypatch.setattr(d.time,'sleep',sleep)
    gate=d.RateLimiter()
    for _ in range(10):gate.acquire()
    assert clock[0]>=.99-1e-12
    assert len(sleeps)==9


def test_public_engine_data_contract_and_full_mark_ohlc():
    from aster.data.validation import normalize_bars, normalize_funding
    from aster.backtest.models import Instrument
    native='1000PEPEUSDT'
    t=d.parse_candles(payload(candles()),native,'kline',d.START_MS,d.START_MS+179999)
    m=d.parse_candles(payload(candles('mark-price-kline')),native,'mark-price-kline',d.START_MS,d.START_MS+179999)
    bars,fund,_=d.normalize(native,t,m,[(d.START_MS,.01)],end=d.START+pd.Timedelta(minutes=3))
    spec=Instrument(id='bybit:perpetual:'+native,exchange='bybit',symbol=native,market_type='perpetual',base='1000PEPE',quote='USDT')
    canonical,quality=normalize_bars(bars,{spec.id:spec})
    assert not quality.errors and not quality.gaps
    assert canonical.duration_seconds.tolist()==[60]*3
    assert (canonical.end==canonical.timestamp+pd.Timedelta(minutes=1)).all()
    assert len(normalize_funding(fund,{spec.id:spec}))==1
    for malformed in [ [(m[0][0],2,1,1,3),*m[1:]],[(m[0][0],2,4,float('nan'),3),*m[1:]] ]:
        with pytest.raises(ValueError):d.normalize(native,t,malformed,[(d.START_MS,.01)],end=d.START+pd.Timedelta(minutes=3))


@pytest.mark.parametrize('bad',[True,float(d.START_MS)+.5,'1759622400000.0','nan'])
def test_timestamp_cannot_be_truncated_or_coerced(bad):
    page=payload(candles());page['result']['list'][0][0]=bad
    with pytest.raises(ValueError):
        d.parse_candles(page,'1000PEPEUSDT','kline',d.START_MS,d.START_MS+179999)
