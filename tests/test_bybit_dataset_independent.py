"""Adversarial tests of the independent auditor, not the collector's verifier."""
import base64
import json
import pandas as pd
import pytest
from audit import verify_bybit_dataset as a
from test_bybit_collector_audit import sealed, reseal, sha


@pytest.fixture
def toy(sealed, monkeypatch):
    monkeypatch.setattr(a,'END',a.START+pd.Timedelta(minutes=3))
    return sealed


def test_independent_exact_native_proxy_and_read_only(toy):
    before={str(p):sha(p.read_bytes()) for p in toy.rglob('*') if p.is_file()}
    receipt=a.verify_dataset(toy)
    assert receipt['complete'] and receipt['errors']==[] and receipt['raw_pages']==40
    pepe=receipt['symbols'][3]
    assert pepe['native_symbol']=='1000PEPEUSDT' and pepe['funding_rows']==3
    assert pepe['proxy_counts']=={'settlement_minute_mark_open_proxy':2,'END_last_completed_mark_close_proxy':1}
    assert pepe['source_interval_minutes_histogram']=={'1.0':1,'2.0':1}
    assert before=={str(p):sha(p.read_bytes()) for p in toy.rglob('*') if p.is_file()}


@pytest.mark.parametrize('column,value', [('mark_high',999),('turnover',22),('volume',200000),('duration_seconds',30),('instrument_id','bybit:perpetual:PEPEUSDT'),('end',pd.Timestamp('2025-10-05',tz='UTC'))])
def test_resealed_bar_corruption(toy,column,value):
    name='PEPEUSDT/bars.parquet'
    frame=pd.read_parquet(toy/name);frame.loc[0,column]=value;frame.to_parquet(toy/name,index=False);reseal(toy,name)
    with pytest.raises(ValueError):a.verify_dataset(toy)


@pytest.mark.parametrize('column,value',[('funding_rate',.8),('mark_price',110),('mark_price_source','actual'),('boundary',True),('timestamp',pd.Timestamp('2025-10-05T00:00:00.001Z'))])
def test_resealed_funding_corruption(toy,column,value):
    name='BTCUSDT/funding.parquet'
    frame=pd.read_parquet(toy/name);frame.loc[0,column]=value;frame.to_parquet(toy/name,index=False);reseal(toy,name)
    with pytest.raises(ValueError):a.verify_dataset(toy)


def forge_raw(toy, page_index, mutation):
    name='BTCUSDT/source_manifest.json';manifest=json.loads((toy/name).read_text())
    receipt=manifest['raw_pages'][page_index];path=toy/receipt['cache_file'];envelope=json.loads(path.read_text())
    body=json.loads(base64.b64decode(envelope['raw_base64']));mutation(body)
    raw=json.dumps(body).encode();envelope['raw_base64']=base64.b64encode(raw).decode();envelope['raw_sha256']=sha(raw)
    path.write_text(json.dumps(envelope));receipt.update(raw_sha256=sha(raw),raw_bytes=len(raw),envelope_sha256=sha(path.read_bytes()))
    (toy/name).write_text(json.dumps(manifest));reseal(toy,name)


@pytest.mark.parametrize('mutation',[
    lambda b:b['result'].update(symbol='ETHUSDT'),
    lambda b:b['result'].update(category='inverse'),
    lambda b:b.update(retCode=False),
    lambda b:b['result']['list'][0].__setitem__(0,str(a.START.value//10**6+180000)),
    lambda b:b['result']['list'][0].append('extra'),
    lambda b:b['result']['list'].append(b['result']['list'][0]),
    lambda b:b['result']['list'][0].__setitem__(1,'NaN'),
])
def test_resealed_raw_identity_schema_grid(toy,mutation):
    forge_raw(toy,1,mutation)
    with pytest.raises(ValueError):a.verify_dataset(toy)


def test_resealed_fund_row_identity(toy):
    forge_raw(toy,3,lambda b:b['result']['list'][0].update(symbol='ETHUSDT'))
    with pytest.raises(ValueError):a.verify_dataset(toy)


@pytest.mark.parametrize('field,value',[('cache_file','../outside.json'),('url','https://evil.test/kline'),('raw_bytes',0),('retrieved_utc','2026-10-06T00:00:00')])
def test_receipt_identity_traversal(toy,field,value):
    name='BTCUSDT/source_manifest.json';m=json.loads((toy/name).read_text());m['raw_pages'][1][field]=value
    (toy/name).write_text(json.dumps(m));reseal(toy,name)
    with pytest.raises(ValueError):a.verify_dataset(toy)


def test_seal_extra_path_and_provenance(toy):
    path=toy/'dataset_seal.json';original=json.loads(path.read_text());bad=dict(original);bad['files']=dict(original['files'],**{'../escape':'x'})
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):a.verify_dataset(toy)
    bad=json.loads(json.dumps(original));bad['source_provenance']['collector_sha256']='0'*64;path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):a.verify_dataset(toy)


def test_resealed_catalog_historical_rule_or_native_unit(toy):
    path=toy/'instruments.json';spec=json.loads(path.read_text());spec[3]['lot_size']=1;path.write_text(json.dumps(spec));reseal(toy,'instruments.json')
    with pytest.raises(ValueError):a.verify_dataset(toy)


def test_missing_or_extra_receipt(toy):
    name='BTCUSDT/source_manifest.json';original=json.loads((toy/name).read_text())
    for change in ('missing','extra'):
        m=json.loads(json.dumps(original))
        if change=='missing':m['raw_pages'].pop()
        else:m['raw_pages'].append(m['raw_pages'][-1])
        (toy/name).write_text(json.dumps(m));reseal(toy,name)
        with pytest.raises(ValueError):a.verify_dataset(toy)


def test_full_funding_page_requires_backwards_continuation(toy):
    def full(body):
        begin=a.START.value//10**6
        body['result']['list']=[{'symbol':'BTCUSDT','fundingRateTimestamp':str(begin+60000+i),'fundingRate':'.001'} for i in range(200)]
    forge_raw(toy,3,full)
    # A full page requires another bounded backwards page, not the END receipt.
    with pytest.raises(ValueError,match='Noncanonical URL/page identity'):a.verify_dataset(toy)


def test_incomplete_seal_fails_before_any_source_reconstruction(tmp_path):
    with pytest.raises(ValueError,match='Missing/escaped'):a.verify_dataset(tmp_path)


def test_official_catalog_result_need_not_repeat_symbol(toy):
    forge_raw(toy,0,lambda b:b['result'].pop('symbol'))
    assert a.verify_dataset(toy)['complete']
