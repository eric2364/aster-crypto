"""Independent offline source reconstruction; no exchange/network calls."""
import base64
import copy
import hashlib
import json
from urllib.parse import urlencode

import pandas as pd
import pytest
from examples.cross_venue import download_bybit as d


def sha(value):
    return hashlib.sha256(value).hexdigest()


def payload(native, rows):
    return {'retCode': 0, 'result': {'category': 'linear', 'symbol': native, 'list': rows}}


def catalog(native):
    return payload(native, [{'symbol': native, 'contractType': 'LinearPerpetual',
        'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'baseCoin': native[:-4], 'status': 'Trading',
        'lotSizeFilter': {'qtyStep': '100' if native == '1000PEPEUSDT' else '.001',
                          'minOrderQty': '100' if native == '1000PEPEUSDT' else '.001',
                          'minNotionalValue': '5'}, 'priceFilter': {'tickSize': '.000001'}}])


def candle_rows(start, mark=False):
    # Different mark opens and closes expose any future-close valuation substitution.
    return [[str(start+i*60000), str(100+i), str(120+i), str(90+i), str(110+i),
             *([] if mark else ['200', '21000'])] for i in reversed(range(3))]


def envelope(root, endpoint, native, body, begin=None, end=None):
    params = {'category': 'linear', 'symbol': native}
    if endpoint == 'funding/history':
        params.update(startTime=begin, endTime=end, limit=200)
    elif endpoint != 'instruments-info':
        params.update(interval='1', start=begin, end=end, limit=1000)
    url = 'https://api.bybit.com/v5/market/'+endpoint+'?'+urlencode(params)
    raw = json.dumps(body).encode()
    value = {'url': url, 'retrieved_utc': '2026-10-06T00:00:00+00:00',
             'raw_sha256': sha(raw), 'raw_base64': base64.b64encode(raw).decode()}
    path = root/'raw'/(sha(url.encode())+'.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    begin = d.START
    end = begin+pd.Timedelta(minutes=3)
    start_ms, end_ms = begin.value//10**6, end.value//10**6
    monkeypatch.setattr(d, 'END', end)
    monkeypatch.setattr(d, 'END_MS', end_ms)
    original = d.normalize
    # Restrict only the test's dataset size, retaining the production reparser and collector.
    monkeypatch.setattr(d, 'normalize', lambda n,t,m,f: original(n,t,m,f,start=begin,end=end))
    def forbidden(*a, **k):
        raise AssertionError('Network is forbidden in the audit suite')
    monkeypatch.setattr(d.urllib.request, 'urlopen', forbidden)
    for native in d.NATIVE.values():
        envelope(tmp_path, 'instruments-info', native, catalog(native))
        for ep in ('kline', 'mark-price-kline'):
            envelope(tmp_path, ep, native, payload(native,candle_rows(start_ms, ep != 'kline')), start_ms,end_ms-1)
        funding = [{'symbol':native,'fundingRateTimestamp':str(start_ms),'fundingRate':'.001'},
                   {'symbol':native,'fundingRateTimestamp':str(start_ms+60000),'fundingRate':'-.002'}]
        envelope(tmp_path,'funding/history',native,payload(native,funding),start_ms,end_ms-1)
        envelope(tmp_path,'funding/history',native,payload(native,[{'symbol':native,
            'fundingRateTimestamp':str(end_ms),'fundingRate':'.003'}]),end_ms,end_ms)
    d.run(tmp_path,workers=1)
    return tmp_path


def reseal(root, name):
    path = root/'dataset_seal.json'
    seal = json.loads(path.read_text())
    seal['files'][name] = sha((root/name).read_bytes())
    path.write_text(json.dumps(seal))


def test_exact_offline_roundtrip_native_units_and_proxy(sealed):
    before = {str(p.relative_to(sealed)):sha(p.read_bytes()) for p in sealed.rglob('*') if p.is_file()}
    d.run(sealed, workers=2, verify_only=True)
    after = {str(p.relative_to(sealed)):sha(p.read_bytes()) for p in sealed.rglob('*') if p.is_file()}
    assert before == after
    bars=pd.read_parquet(sealed/'PEPEUSDT/bars.parquet')
    fund=pd.read_parquet(sealed/'PEPEUSDT/funding.parquet')
    assert bars.instrument_id.unique().tolist()==['bybit:perpetual:1000PEPEUSDT']
    assert bars.volume.tolist()==[200,200,200]  # native 1000-PEPE units, never 200000
    assert fund.mark_price.tolist()==[100,101,112]  # open at settlement; END completed close
    assert fund.funding_rate.tolist()==[.001,-.002,.003]
    assert 'available_at' not in fund
    spec=next(x for x in json.loads((sealed/'instruments.json').read_text()) if x['symbol']=='1000PEPEUSDT')
    assert spec['lot_size']==100 and spec['multiplier']==1 and spec['base']=='1000PEPE'
    manifest=json.loads((sealed/'PEPEUSDT/source_manifest.json').read_text())
    assert manifest['metadata_historical_rules'] is False
    assert len(json.loads((sealed/'dataset_seal.json').read_text())['files'])==25


@pytest.mark.parametrize('what',['bars','funding','catalog','manifest','provenance'])
def test_forged_normalization_even_resealed_rejected(sealed,what):
    if what in ('bars','funding'):
        name='PEPEUSDT/'+what+'.parquet'; frame=pd.read_parquet(sealed/name)
        frame.loc[0,'close' if what=='bars' else 'mark_price']+=1
        frame.to_parquet(sealed/name,index=False); reseal(sealed,name)
    elif what=='catalog':
        name='instruments.json'; value=json.loads((sealed/name).read_text()); value[3]['lot_size']=1
        (sealed/name).write_text(json.dumps(value)); reseal(sealed,name)
    elif what=='manifest':
        name='PEPEUSDT/source_manifest.json'; value=json.loads((sealed/name).read_text())
        value['metadata_historical_rules']=True
        (sealed/name).write_text(json.dumps(value)); reseal(sealed,name)
    else:
        path=sealed/'dataset_seal.json'; value=json.loads(path.read_text())
        value['source_provenance']['collector_sha256']='0'*64;path.write_text(json.dumps(value))
    with pytest.raises((ValueError,AssertionError)):
        d.run(sealed,verify_only=True)


@pytest.mark.parametrize('what',['url','raw_hash','retcode','receipt_offset','missing'])
def test_corrupt_raw_source_rejected_offline(sealed,what):
    manifest=json.loads((sealed/'BTCUSDT/source_manifest.json').read_text())
    path=sealed/manifest['raw_pages'][1]['cache_file']
    value=json.loads(path.read_text())
    if what=='missing':path.unlink()
    else:
        if what=='url':value['url']=value['url'].replace('api.bybit.com','example.invalid')
        elif what=='raw_hash':value['raw_sha256']='0'*64
        elif what=='receipt_offset':value['retrieved_utc']='2026-10-06T08:00:00+08:00'
        else:
            raw=json.loads(base64.b64decode(value['raw_base64']));raw['retCode']=10006
            raw=json.dumps(raw).encode();value['raw_base64']=base64.b64encode(raw).decode();value['raw_sha256']=sha(raw)
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):d.run(sealed,verify_only=True)


@pytest.mark.parametrize('kind',['duplicate_trade','duplicate_mark','conflicting_funding','missing_trade','extra_mark','unaligned_funding'])
def test_exact_three_minute_coverage_and_duplicates(kind):
    start=d.START_MS; stop=d.START+pd.Timedelta(minutes=3)
    trade=d.parse_candles(payload('BTCUSDT',candle_rows(start)),'BTCUSDT','kline',start,start+179999)
    mark=d.parse_candles(payload('BTCUSDT',candle_rows(start,True)),'BTCUSDT','mark-price-kline',start,start+179999)
    fund=[(start,.001)]
    if kind=='duplicate_trade':trade.append(trade[0])
    elif kind=='duplicate_mark':mark.append(mark[0])
    elif kind=='conflicting_funding':fund.append((start,-.001))
    elif kind=='missing_trade':trade.pop()
    elif kind=='extra_mark':mark.append((start-60000,100,120,90,110))
    else:fund=[(start+1,.001)]
    with pytest.raises(ValueError):d.normalize('BTCUSDT',trade,mark,fund,end=stop)


@pytest.mark.parametrize('what',['native','category','time','ohlc','infinite','negative_volume'])
def test_adversarial_page_semantics(what):
    value=payload('1000PEPEUSDT',candle_rows(d.START_MS))
    if what=='native':value['result']['symbol']='PEPEUSDT'
    elif what=='category':value['result']['category']='inverse'
    elif what=='time':value['result']['list'][0][0]=str(d.START_MS-60000)
    elif what=='ohlc':value['result']['list'][0][2]='50'
    elif what=='infinite':value['result']['list'][0][4]='inf'
    else:value['result']['list'][0][5]='-1'
    with pytest.raises(ValueError):d.parse_candles(value,'1000PEPEUSDT','kline',d.START_MS,d.START_MS+179999)


def test_end_candle_forbidden_but_real_end_settlement_allowed():
    with pytest.raises(ValueError):d.page_url('kline','BTCUSDT',d.END_MS,d.END_MS)
    url=d.page_url('funding/history','BTCUSDT',d.END_MS,d.END_MS)
    assert 'startTime='+str(d.END_MS) in url
    p=payload('BTCUSDT',[{'symbol':'BTCUSDT','fundingRateTimestamp':str(d.END_MS),'fundingRate':'-.0001'}])
    assert d.parse_funding(p,'BTCUSDT',d.END_MS,d.END_MS)==[(d.END_MS,-.0001)]
    with pytest.raises(ValueError):d.page_url('funding/history','BTCUSDT',d.START_MS-1,d.START_MS)


def test_engine_normalization_contract(sealed):
    from aster.data.validation import normalize_bars, normalize_funding
    from aster.backtest.models import Instrument
    specs={x['id']:Instrument(**x) for x in json.loads((sealed/'instruments.json').read_text())}
    bars=pd.read_parquet(sealed/'PEPEUSDT/bars.parquet')
    fund=pd.read_parquet(sealed/'PEPEUSDT/funding.parquet')
    checked, quality=normalize_bars(bars,specs)
    payments=normalize_funding(fund,specs)
    assert (checked.duration_seconds==60).all()
    assert (checked.end-checked.timestamp==pd.Timedelta(minutes=1)).all()
    assert checked.iloc[-1].end==d.END
    assert payments.iloc[-1].timestamp==d.END
    assert checked.volume.sum()==600 and payments.mark_price.tolist()==[100,101,112]


def test_funding_full_page_cursor_keeps_all_actual_events(monkeypatch):
    begin=d.START;start=d.START_MS;stop=begin+pd.Timedelta(minutes=501);end=stop.value//10**6
    monkeypatch.setattr(d,'END',stop);monkeypatch.setattr(d,'END_MS',end)
    original=d.normalize
    monkeypatch.setattr(d,'normalize',lambda n,t,m,f:original(n,t,m,f,start=begin,end=stop))
    calls=[]
    class FakePages:
        offline=True
        def get(self,ep,n,lo=None,hi=None):
            calls.append((ep,lo,hi))
            if ep=='instruments-info':return catalog(n),{'url':ep}
            if ep in ('kline','mark-price-kline'):
                rows=[[str(start+i*60000),'100','120','90','110',*(['200','21000'] if ep=='kline' else [])]
                      for i in reversed(range(501))]
                return payload(n,rows),{'url':ep}
            timestamps=[start+2*i*60000 for i in range(201)] + [end]
            stamps=sorted((t for t in timestamps if lo<=t<=hi),reverse=True)[:200]
            return payload(n,[{'symbol':n,'fundingRateTimestamp':str(t),'fundingRate':'.001'} for t in stamps]),{'url':ep}
    _,bars,funding,_=d.collect_symbol(FakePages(),'PEPEUSDT')
    assert len(bars)==501 and len(funding)==202
    funding_calls=[c for c in calls if c[0]=='funding/history']
    assert funding_calls==[('funding/history',start,end-1),('funding/history',start,start+120000-1),('funding/history',end,end)]
    assert funding.timestamp.is_unique
    assert funding.timestamp.iloc[0]==begin and funding.timestamp.iloc[-1]==stop


@pytest.mark.parametrize('mutation',['base','contract','quote','zero_step'])
def test_native_catalog_cannot_silently_rescale_pepe(mutation):
    value=catalog('1000PEPEUSDT');row=value['result']['list'][0]
    if mutation=='base':row['baseCoin']='PEPE'
    elif mutation=='contract':row['contractType']='InversePerpetual'
    elif mutation=='quote':row['settleCoin']='USDC'
    else:row['lotSizeFilter']['qtyStep']='0'
    with pytest.raises(ValueError):d.catalog_record(value,'1000PEPEUSDT')


@pytest.mark.parametrize('field',['missing','absolute','traversal','extra'])
def test_seal_paths_rejected_before_arbitrary_file_reads(sealed,field,monkeypatch):
    target=sealed/'dataset_seal.json';value=json.loads(target.read_text())
    if field=='missing':value['files'].pop('instruments.json')
    else:
        value['files'][{'absolute':'/tmp/do-not-read', 'traversal':'../do-not-read', 'extra':'unexpected.json'}[field]]='0'*64
    target.write_text(json.dumps(value))
    original=d.Path.read_bytes
    def read(path):
        assert str(path) not in ('/tmp/do-not-read',str(sealed/'../do-not-read'),str(sealed/'unexpected.json')),'Read untrusted seal path before validating allowed set'
        return original(path)
    monkeypatch.setattr(d.Path,'read_bytes',read)
    with pytest.raises(ValueError):d.run(sealed,verify_only=True)
