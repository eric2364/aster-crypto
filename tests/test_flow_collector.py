"""Mocked official ZIP extraction; no network or full-year fixtures."""
import hashlib
import json
import zipfile

import pandas as pd
import pytest
from examples.external_factors import extract_flow as f


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    start=pd.Timestamp('2026-01-01',tz='UTC');end=start+pd.Timedelta(minutes=3)
    monkeypatch.setattr(f,'START',start);monkeypatch.setattr(f,'END',end)
    source=tmp_path/'source';target=source/'PEPEUSDT';target.mkdir(parents=True)
    output=tmp_path/'output'
    times=pd.date_range(start,periods=3,freq='min')
    frame=pd.DataFrame({'open_time':[int(t.timestamp()*1000) for t in times],
                        'volume':[100.,200.,0.],'taker_buy_volume':[80.,20.,0.],'count':[5.,7.,0.]})
    frame['close_time']=frame.open_time+59999
    archive=tmp_path/'1000PEPEUSDT-1m-2026-01.zip'
    def save_raw():
        with zipfile.ZipFile(archive,'w') as z:z.writestr('1000PEPEUSDT-1m-2026-01.csv',frame.to_csv(index=False))
        item={'url':'https://data.binance.vision/data/futures/um/monthly/klines/1000PEPEUSDT/1m/1000PEPEUSDT-1m-2026-01.zip',
              'checksum_url':'official.CHECKSUM','checksum_verified':True,
              'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'cache_file':str(archive)}
        (target/'source_manifest.json').write_text(json.dumps({'symbol':'1000PEPEUSDT','market':'perpetual','interval':'1m','archives':[item,{'url':'https://data.binance.vision/data/futures/um/monthly/markPriceKlines/1000PEPEUSDT/1m/mark.zip'}]}))
    save_raw()
    bars=pd.DataFrame({'timestamp':times,'volume':frame.volume,'instrument_id':'binance:perpetual:1000PEPEUSDT'})
    bars.to_parquet(target/'bars.parquet',index=False)
    return source,output,target,frame,bars,save_raw


def test_native_units_publication_roundtrip_and_marks_ignored(fixture):
    source,output,target,frame,bars,save_raw=fixture
    f.extract(source,output,'PEPEUSDT')
    result=pd.read_parquet(output/'PEPEUSDT'/'observations.parquet')
    assert result.instrument_id.eq('binance:perpetual:1000PEPEUSDT').all()
    assert result.total_volume.tolist()==[100.,200.,0.]
    assert result.available_at.eq(result.timestamp+pd.Timedelta(minutes=2)).all()
    f.extract(source,output,'PEPEUSDT',True)


@pytest.mark.parametrize('defect',['buy_exceeds','gap','fractional_count','duration','wrong_identity','raw_tamper'])
def test_archive_grid_volume_identity_fail_closed(fixture,defect):
    source,output,target,frame,bars,save_raw=fixture
    if defect=='buy_exceeds':frame.loc[0,'taker_buy_volume']=101.
    elif defect=='gap':frame.drop(index=1,inplace=True)
    elif defect=='fractional_count':frame.loc[0,'count']=1.5
    elif defect=='duration':frame.loc[0,'close_time']-=1
    elif defect=='wrong_identity':
        bars['instrument_id']='binance:perpetual:BTCUSDT';bars.to_parquet(target/'bars.parquet',index=False)
    if defect not in ['wrong_identity','raw_tamper']:save_raw()
    if defect=='raw_tamper':
        manifest=json.loads((target/'source_manifest.json').read_text())
        p=manifest['archives'][0]['cache_file']
        with open(p,'ab') as handle:handle.write(b'tampered')
    with pytest.raises(ValueError):f.extract(source,output,'PEPEUSDT')


@pytest.mark.parametrize('defect',['wrong_symbol','wrong_market','wrong_interval','wrong_url_asset','wrong_host','wrong_url_interval'])
def test_manifest_archive_identity_rejected(fixture,defect):
    source,output,target,frame,bars,save_raw=fixture
    path=target/'source_manifest.json';manifest=json.loads(path.read_text())
    if defect=='wrong_symbol':manifest['symbol']='BTCUSDT'
    elif defect=='wrong_market':manifest['market']='spot'
    elif defect=='wrong_interval':manifest['interval']='1h'
    elif defect=='wrong_url_asset':manifest['archives'][0]['url']=manifest['archives'][0]['url'].replace('1000PEPEUSDT','BTCUSDT')
    elif defect=='wrong_host':manifest['archives'][0]['url']=manifest['archives'][0]['url'].replace('data.binance.vision','example.com')
    elif defect=='wrong_url_interval':manifest['archives'][0]['url']=manifest['archives'][0]['url'].replace('/1m/','/1h/')
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):f.extract(source,output,'PEPEUSDT')
