"""Read-only, synthetic integration guard tests; no historical fitting."""
from copy import deepcopy
from dataclasses import asdict
import json
import numpy as np
import pandas as pd
import pytest
from aster.backtest.models import Instrument,SimulationConfig,Order
from aster.backtest.portfolio import Portfolio
from examples.residual_convergence import run as runner


def minimal_estimation(out):
    models={'assets':{'synthetic':{'alpha':.001}}}
    runner.dump(out/'source_lock.json',{'synthetic':'pre-fit freeze'})
    runner.dump(out/'models.json',models)
    runner.dump(out/'estimation_receipt.json',{'source_lock_sha256':runner.digest(out/'source_lock.json'),
                                              'models_sha256':runner.digest(out/'models.json')})
    return models


def cached_phase(out,phase):
    name,begin,stop,stress=phase;directory=out/'trials'/name;directory.mkdir(parents=True)
    for ledger in runner.LEDGERS:
        for extension in ['csv','parquet']:(directory/f'{ledger}.{extension}').write_bytes(b'synthetic sealed ledger')
    for extra in ['source_manifest.json','quality.json','exposure.parquet','exposure.csv','leg_contributions.csv','strategy_diagnostics.json']:
        (directory/extra).write_bytes(b'synthetic sealed output')
    parameters={'family':runner.FAMILY,'phase':name,'begin':str(begin),'stop':str(stop),'stress':stress}
    runner.dump(directory/'metadata.json',{'parameters':parameters})
    runner.dump(directory/'metrics.json',{'total_return':0.,'synthetic':True})
    receipt={'phase':name,'stress':stress,'source_lock_sha256':runner.digest(out/'source_lock.json'),
             'models_sha256':runner.digest(out/'models.json'),'outputs_sha256':runner.output_files(directory)}
    runner.dump(directory/'completion.json',receipt)
    return directory


def test_estimation_guard_runs_before_prices_or_fit(tmp_path,monkeypatch):
    def block(*args):raise RuntimeError('unfrozen sources')
    monkeypatch.setattr(runner,'guard',block)
    monkeypatch.setattr(runner,'available_prices',lambda *args:pytest.fail('prices accessed before guard'))
    monkeypatch.setattr(runner,'fit_models',lambda *args:pytest.fail('fit occurred before guard'))
    with pytest.raises(RuntimeError,match='unfrozen'):runner.estimate(tmp_path,tmp_path)


def test_source_identity_is_relative_and_cannot_escape_executable_archive(tmp_path,monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(runner,'read',lambda path:{'archives':[],'funding_pages':[]})
    monkeypatch.setattr(runner,'digest',lambda path:'synthetic source hash')
    identity=runner.identity(tmp_path/'cache')
    archive=tmp_path/'out'/'executed_source'
    assert 'examples/residual_convergence/run.py' in identity['sources']
    for source in identity['sources']:
        assert not Path(source).is_absolute()
        assert (archive/source).resolve().is_relative_to(archive.resolve())


def test_raw_archive_and_funding_response_hashes_are_in_pre_fit_identity(tmp_path,monkeypatch):
    from pathlib import Path
    archive=tmp_path/'official.zip';page=tmp_path/'funding-response.json'
    archive.write_bytes(b'official archived candles');page.write_bytes(b'original funding response')
    monkeypatch.setattr(runner,'read',lambda path:{'archives':[{'cache_file':'archive'}],'funding_pages':[{'cache_file':'funding'}]})
    monkeypatch.setattr(runner,'cached_path',lambda name:archive if name=='archive' else page)
    real_digest=runner.digest
    monkeypatch.setattr(runner,'digest',lambda path:real_digest(path) if Path(path).exists() else 'synthetic other source hash')
    before=runner.identity(tmp_path/'cache')
    assert before['inputs'][str(archive)]==real_digest(archive)
    assert before['inputs'][str(page)]==real_digest(page)
    archive.write_bytes(b'tampered candle source');page.write_bytes(b'tampered funding response')
    after=runner.identity(tmp_path/'cache')
    assert after['inputs'][str(archive)]!=before['inputs'][str(archive)]
    assert after['inputs'][str(page)]!=before['inputs'][str(page)]


def test_nonnull_partial_transaction_exports_actual_pending_order_without_mutation(tmp_path):
    timestamp=pd.Timestamp('2026-10-05',tz='UTC')
    order=Order('binance:perpetual:1000PEPEUSDT',-1,100.,tif='GTC',reduce_only=True)
    order.id='partial-exit';order.status='partial';order.remaining=3.
    order.submitted_at=timestamp-pd.Timedelta(minutes=2);order.active_at=timestamp-pd.Timedelta(minutes=1)
    transaction={'targets':{order.instrument_id:0.},'stops':{'PEPEUSDT','DOGEUSDT'},
                 'orders':{order.instrument_id:order},'deadline':timestamp+pd.Timedelta(minutes=3)}
    before=deepcopy(transaction);path=tmp_path/'strategy_diagnostics.json'
    runner.dump(path,{'terminal_transaction':transaction})
    saved=runner.read(path)['terminal_transaction']
    assert saved['stops']==['DOGEUSDT','PEPEUSDT']
    exported=saved['orders'][order.instrument_id]
    assert exported['status']=='partial' and exported['remaining']==3. and exported['quantity']==100.
    assert exported['reduce_only'] and exported['id']=='partial-exit'
    assert pd.Timestamp(saved['deadline'])==transaction['deadline']
    assert transaction==before


def test_freeze_archives_before_fit_and_rejects_input_or_archive_mutation(tmp_path,monkeypatch):
    cache=tmp_path/'cache';cache.mkdir();out=tmp_path/'out';input_path=cache/'input.txt';input_path.write_text('known source')
    source='examples/residual_convergence/signals.py'
    def identity(cache):
        return {'sources':{source:runner.digest(source)},'inputs':{str(input_path):runner.digest(input_path)},
                'runtime':{'statsmodels':'0.14.6'}}
    mapping={symbol:'native:'+symbol for symbol in runner.SYMBOLS}
    monkeypatch.setattr(runner,'identity',identity)
    monkeypatch.setattr(runner,'catalog',lambda cache:{iid:object() for iid in mapping.values()})
    monkeypatch.setattr(runner,'mappings',lambda cache:mapping)
    monkeypatch.setattr(runner,'verify',lambda cache,symbol,specs:{'spot_symbol':symbol})
    monkeypatch.setattr(runner,'fit_models',lambda *args:pytest.fail('freeze performed fit'))
    lock=runner.freeze(cache,out)
    assert runner.read(out/'source_lock.json')==lock and not (out/'models.json').exists()
    assert (out/'executed_source'/source).read_bytes()==open(source,'rb').read()
    input_path.write_text('mutated')
    with pytest.raises(RuntimeError,match='differs'):runner.guard(cache,out)
    input_path.write_text('known source')
    (out/'executed_source'/source).write_bytes(b'changed executable archive')
    with pytest.raises(RuntimeError,match='archive'):runner.guard(cache,out)


def test_changed_supplied_model_rejected_before_cached_result(tmp_path,monkeypatch):
    models=minimal_estimation(tmp_path);cached_phase(tmp_path,runner.PHASES[0])
    monkeypatch.setattr(runner,'guard',lambda *args:None)
    assert runner.run_phase(tmp_path,tmp_path,models,runner.PHASES[0])['synthetic']
    changed=deepcopy(models);changed['assets']['synthetic']['alpha']=-100.
    with pytest.raises(RuntimeError):runner.run_phase(tmp_path,tmp_path,changed,runner.PHASES[0])


def test_mutated_saved_model_cannot_resign_cached_case(tmp_path,monkeypatch):
    models=minimal_estimation(tmp_path);directory=cached_phase(tmp_path,runner.PHASES[0])
    monkeypatch.setattr(runner,'guard',lambda *args:None)
    models['assets']['synthetic']['alpha']=2.;runner.dump(tmp_path/'models.json',models)
    receipt=runner.read(directory/'completion.json');receipt['models_sha256']=runner.digest(tmp_path/'models.json');runner.dump(directory/'completion.json',receipt)
    with pytest.raises(RuntimeError):runner.run_phase(tmp_path,tmp_path,models,runner.PHASES[0])


@pytest.mark.parametrize('field,value',[('phase','evaluation'),('stress',True),('begin','2026-01-01'),('stop','2026-12-01'),('family','other')])
def test_resealed_wrong_cached_phase_metadata_rejected(tmp_path,monkeypatch,field,value):
    models=minimal_estimation(tmp_path);directory=cached_phase(tmp_path,runner.PHASES[0])
    monkeypatch.setattr(runner,'guard',lambda *args:None)
    metadata=runner.read(directory/'metadata.json');metadata['parameters'][field]=value;runner.dump(directory/'metadata.json',metadata)
    receipt=runner.read(directory/'completion.json');receipt['outputs_sha256']=runner.output_files(directory);runner.dump(directory/'completion.json',receipt)
    with pytest.raises(RuntimeError):runner.run_phase(tmp_path,tmp_path,models,runner.PHASES[0])


def test_unapproved_phase_tuple_rejected_before_data(tmp_path,monkeypatch):
    models=minimal_estimation(tmp_path)
    monkeypatch.setattr(runner,'guard',lambda *args:None)
    monkeypatch.setattr(runner,'available_prices',lambda *args:pytest.fail('unapproved model accessed data'))
    name,begin,stop,stress=runner.PHASES[0]
    with pytest.raises((ValueError,RuntimeError)):runner.run_phase(tmp_path,tmp_path,models,(name,begin,stop+pd.Timedelta(days=1),stress))


def test_snapshot_observer_returns_original_state_without_mutation():
    specs=[];mapping={}
    for symbol in runner.SYMBOLS:
        native='1000PEPEUSDT' if symbol=='PEPEUSDT' else symbol;iid='binance:perpetual:'+native;mapping[symbol]=iid
        specs.append(Instrument(iid,'binance',native,'perpetual',taker_bps=5,min_quantity=.001,min_notional=0))
    portfolio=Portfolio(specs,SimulationConfig(initial_balances={'binance':100000.},leverage=1,margin_mode='isolated'))
    timestamp=pd.Timestamp('2026-07-05',tz='UTC')
    for symbol,iid in mapping.items():portfolio.marks[iid]=100 if symbol=='BTCUSDT' else 50 if symbol=='ETHUSDT' else 10
    for symbol,side,quantity in [('PEPEUSDT',1,12),('BTCUSDT',-1,.84),('ETHUSDT',-1,.48)]:
        assert portfolio.apply_fill(mapping[symbol],side,quantity,portfolio.marks[mapping[symbol]],timestamp,'taker','market')==(True,'')
    portfolio.settle_funding({'instrument_id':mapping['PEPEUSDT'],'timestamp':timestamp,'funding_rate':.01,'mark_price':10})
    models={'assets':{alt:{'beta_btc':.7,'beta_eth':.2} for alt in runner.ALTS}}
    original=portfolio.snapshot(timestamp)
    state=(dict(portfolio.cash),{iid:asdict(p) for iid,p in portfolio.positions.items()},deepcopy(portfolio.events))
    observer=runner.SnapshotObserver(portfolio,mapping,models);returned=observer(timestamp)
    assert returned==original
    assert state==(portfolio.cash,{iid:asdict(p) for iid,p in portfolio.positions.items()},portfolio.events)
    observed=observer.rows[-1]
    assert observed['frozen_factor_exposure_BTCUSDT']==pytest.approx(0.)
    assert observed['frozen_factor_exposure_ETHUSDT']==pytest.approx(0.)
    assert observed['quantity_PEPEUSDT']==12  # native bundles, never12,000
    assert observed['collateral_PEPEUSDT']==pytest.approx(118.8)
    portfolio.apply_fill(mapping['PEPEUSDT'],-1,2,10,timestamp,'taker','market')
    observer(timestamp)
    assert observer.rows[-1]['frozen_factor_exposure_BTCUSDT']==pytest.approx(-14.)
    assert observer.rows[-1]['frozen_factor_exposure_ETHUSDT']==pytest.approx(-4.)


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_full_resolution_endpoint_and_25_comparison_interval(unit):
    days=pd.date_range(runner.EVAL_START,runner.END,freq='D')
    clock=pd.DatetimeIndex([days[0],days[0]+pd.Timedelta(minutes=1),*days[1:]]).as_unit(unit)
    frame=pd.DataFrame({'timestamp':clock,'equity':100000*1.001**np.arange(len(clock))})
    saved=frame.copy(deep=True);interval=runner.conditional_interval(frame)
    assert interval['available'] and interval['comparison_count']==25
    reference=frame.copy();reference['timestamp']=reference.timestamp.dt.as_unit('ns')
    assert interval==runner.conditional_interval(reference)
    assert len(runner.endpoint_daily(frame))==92
    pd.testing.assert_frame_equal(frame,saved)


def test_available_prices_preserves_native_prices_and_completion_publication_lag(tmp_path,monkeypatch):
    begin=pd.Timestamp('2026-04-05',tz='UTC');stop=begin+pd.Timedelta(minutes=2)
    monkeypatch.setattr(runner,'START',begin);monkeypatch.setattr(runner,'END',stop)
    mapping={s:'binance:perpetual:'+('1000PEPEUSDT' if s=='PEPEUSDT' else s) for s in runner.SYMBOLS}
    monkeypatch.setattr(runner,'mappings',lambda cache:mapping)
    def read_prices(path,**kwargs):
        symbol=path.parent.name
        return pd.DataFrame({'timestamp':pd.date_range(begin,periods=2,freq='min').as_unit('ms'),
                             'duration_seconds':60,'instrument_id':mapping[symbol],
                             'close':.003 if symbol=='PEPEUSDT' else 100.})
    monkeypatch.setattr(runner.pd,'read_parquet',read_prices)
    frame=runner.available_prices(tmp_path)
    assert list(frame.index)==[begin+pd.Timedelta(minutes=2),begin+pd.Timedelta(minutes=3)]
    assert frame.PEPEUSDT.eq(.003).all()  # raw1000PEPE quote; never divide by1000 here
    assert set(frame.columns)==set(runner.SYMBOLS)


@pytest.mark.parametrize('mutation',['missing','duplicate','duration','identity','outside'])
def test_available_price_source_grid_or_identity_error_rejected(tmp_path,monkeypatch,mutation):
    begin=pd.Timestamp('2026-04-05',tz='UTC');stop=begin+pd.Timedelta(minutes=2)
    monkeypatch.setattr(runner,'START',begin);monkeypatch.setattr(runner,'END',stop)
    mapping={s:'binance:perpetual:'+('1000PEPEUSDT' if s=='PEPEUSDT' else s) for s in runner.SYMBOLS}
    monkeypatch.setattr(runner,'mappings',lambda cache:mapping)
    def read_prices(path,**kwargs):
        symbol=path.parent.name
        frame=pd.DataFrame({'timestamp':pd.date_range(begin,periods=2,freq='min'),
                            'duration_seconds':60,'instrument_id':mapping[symbol],'close':100.})
        if mutation=='missing':return frame.iloc[:1]
        if mutation=='duplicate':frame.loc[1,'timestamp']=begin
        if mutation=='duration':frame.loc[1,'duration_seconds']=3600
        if mutation=='identity':frame.loc[1,'instrument_id']='binance:spot:BTCUSDT'
        if mutation=='outside':frame.loc[1,'timestamp']=stop
        return frame
    monkeypatch.setattr(runner.pd,'read_parquet',read_prices)
    with pytest.raises(ValueError):runner.available_prices(tmp_path)


@pytest.mark.parametrize('phase',[runner.PHASES[0],runner.PHASES[-1]])
def test_joint_phase_actual_funding_includes_end_and_uses_minute_risk_clock(tmp_path,monkeypatch,phase):
    from types import SimpleNamespace
    models=minimal_estimation(tmp_path)
    name,begin,stop,stress=phase
    mapping={s:'binance:perpetual:'+('1000PEPEUSDT' if s=='PEPEUSDT' else s) for s in runner.SYMBOLS}
    specs={iid:Instrument(iid,'binance',iid.split(':')[-1],'perpetual') for iid in mapping.values()}
    monkeypatch.setattr(runner,'guard',lambda *args:None)
    monkeypatch.setattr(runner,'mappings',lambda cache:mapping)
    monkeypatch.setattr(runner,'catalog',lambda cache:specs)
    monkeypatch.setattr(runner,'available_prices',lambda cache:pd.DataFrame(index=pd.DatetimeIndex([begin,stop])))
    monkeypatch.setattr(runner,'build_features',lambda prices,models:prices)
    monkeypatch.setattr(runner,'ResidualPortfolio',lambda *args:object())
    def read_source(path,**kwargs):
        iid=mapping[path.parent.name]
        if path.name=='funding.parquet':
            return pd.DataFrame({'timestamp':[begin-pd.Timedelta(minutes=1),begin,stop,stop+pd.Timedelta(minutes=1)],
                                 'instrument_id':iid,'funding_rate':.001,'mark_price':100.})
        return pd.DataFrame({'timestamp':[begin-pd.Timedelta(minutes=1),begin,stop-pd.Timedelta(minutes=1),stop],
                             'instrument_id':iid,'duration_seconds':60})
    monkeypatch.setattr(runner.pd,'read_parquet',read_source)
    class StopBeforeSimulation(Exception):pass
    class Probe:
        def __init__(self,instruments,config):
            self.portfolio=SimpleNamespace(snapshot=lambda timestamp:None)
            assert len(instruments)==8 and {s.id for s in instruments}==set(mapping.values())
            assert config.record_every==1 and config.margin_mode=='isolated' and config.leverage==1
            assert config.slippage_bps==(16 if stress else 8)
            assert config.participation==(.025 if stress else .05)
            assert config.execution_delay_bars==(1 if stress else 0)
            assert all(s.taker_bps==(10 if stress else 5) for s in instruments)
        def run(self,bars,strategy,funding):
            assert len(bars)==16 and set(bars.timestamp)=={begin,stop-pd.Timedelta(minutes=1)}
            assert len(funding)==16 and set(funding.timestamp)=={begin,stop}
            assert set(funding.instrument_id)==set(mapping.values())
            raise StopBeforeSimulation
    monkeypatch.setattr(runner,'Engine',Probe)
    with pytest.raises(StopBeforeSimulation):runner.run_phase(tmp_path,tmp_path,models,phase)
