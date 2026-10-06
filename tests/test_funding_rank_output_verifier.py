"""Independent audit adversaries on tiny synthetic Engine exports only.

HOLD is shortened only in synthetic fixtures to exercise trading in twenty
minutes. This verifier's monetary scope is not a certificate of policy intents.
"""
from dataclasses import asdict
import copy
from pathlib import Path
import subprocess
import sys
import importlib.metadata
import pandas as pd
import pytest
from audit import verify_funding_rank_outputs as a
from examples.funding_rank import run as r
from examples.funding_rank import strategy as control
from tests.test_funding_rank_execution import START,catalog,candles,feature_frame


@pytest.fixture
def phase_export(tmp_path,monkeypatch):
    cache=tmp_path/'cache';out=tmp_path/'experiment';cache.mkdir();out.mkdir()
    phase=('evaluation',START,START+pd.Timedelta(minutes=20),False)
    monkeypatch.setattr(r,'PHASES',[phase]);monkeypatch.setattr(a,'PHASES',[phase])
    monkeypatch.setattr(r,'START',START);monkeypatch.setattr(r,'END',phase[2])
    monkeypatch.setattr(control,'HOLD',pd.Timedelta(minutes=1))
    specs=catalog();r.dump(cache/'instruments.json',[asdict(s) for s in specs.values()])
    bars=candles(minutes=20)
    for symbol,spec in specs.items():
        folder=cache/symbol;folder.mkdir()
        bars.loc[bars.instrument_id.eq(spec.id)].reset_index(drop=True).to_parquet(folder/'bars.parquet',index=False)
        fund=pd.DataFrame({'timestamp':pd.Series([],dtype='datetime64[ns, UTC]'),
                           'instrument_id':pd.Series([],dtype=str),'funding_rate':pd.Series([],dtype=float),
                           'mark_price':pd.Series([],dtype=float)})
        if symbol=='BTCUSDT':
            fund=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=5),instrument_id=spec.id,funding_rate=.001,mark_price=100.),
                               dict(timestamp=START+pd.Timedelta(minutes=5,milliseconds=500),instrument_id=spec.id,funding_rate=.001,mark_price=100.)])
        fund.to_parquet(folder/'funding.parquet',index=False)
    lock={'sources':{str(p.relative_to(r.REPO)):r.digest(p) for p in (r.REPO/'aster').rglob('*.py')},
          'runtime':{'python':sys.version,**{n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','scipy','plotly')}}}
    r.dump(out/'source_lock.json',lock)
    features=feature_frame();features.to_parquet(out/'features.parquet')
    r.dump(out/'feature_receipt.json',{'source_lock_sha256':r.digest(out/'source_lock.json'),'features_sha256':r.digest(out/'features.parquet')})
    monkeypatch.setattr(r,'guard',lambda *args:lock)
    monkeypatch.setattr(r,'verified_features',lambda *args:features.copy())
    r.run_phase(cache,out,phase)
    anchor=subprocess.run(['git','rev-parse','HEAD'],cwd=r.REPO,capture_output=True,text=True,check=True).stdout.strip()
    return cache,out,phase,lock,anchor


def verify(fixture):return a.verify_phase(*fixture)


def reseal(fixture):
    _,out,phase,_,_=fixture;folder=out/'trials'/phase[0]
    value=r.read(folder/'completion.json');value['outputs_sha256']=r.output_files(folder)
    r.dump(folder/'completion.json',value)


def change_json(fixture,name,mutate):
    path=fixture[1]/'trials'/fixture[2][0]/name;value=r.read(path);mutate(value);r.dump(path,value);reseal(fixture)


def test_actual_export_all_25_files_and_cash_reconstruction(phase_export):
    receipt,score,equity=verify(phase_export)
    assert len(receipt['outputs_sha256'])==25
    assert receipt['trajectory_reconstruction_passed'] and receipt['completed_baskets']==1
    assert receipt['fills']==8 and receipt['closed_trades']==4 and receipt['funding_cash_events']==1
    assert receipt['terminal_flat_resolved'] and score['total_return']<0
    assert set(receipt['participants'])=={'BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT'}
    assert len(equity)==22 # 21 minute observations and one fractional settlement


@pytest.mark.parametrize('field,value',[('total_return',1.),('funding_pnl',999.),('trading_fees',0.),
                                       ('max_drawdown',0.),('turnover',0.)])
def test_resealed_wrong_base_metric_fails_actual_reconstruction(phase_export,field,value):
    change_json(phase_export,'metrics.json',lambda score:score.update({field:value}))
    with pytest.raises(AssertionError,match='metric'):verify(phase_export)


def test_resealed_native_leg_attribution_cannot_hide_loser(phase_export):
    path=phase_export[1]/'trials'/phase_export[2][0]/'leg_contributions.csv'
    table=pd.read_csv(path);table.loc[table.symbol.eq('PEPEUSDT'),'net_pnl']=12345;table.to_csv(path,index=False)
    reseal(phase_export)
    with pytest.raises(AssertionError,match='leg contributions'):verify(phase_export)


@pytest.mark.parametrize('mode',['targets','actual_clock','deadline','duplicate','membership'])
def test_false_completed_basket_resealed_is_not_activity_evidence(phase_export,mode):
    folder=phase_export[1]/'trials'/phase_export[2][0]
    completed=r.read(folder/'completed_baskets.json');diag=r.read(folder/'strategy_diagnostics.json')
    if mode=='targets':
        completed[0]['targets'][a.iid('binance','PEPEUSDT')]+=1
    elif mode=='actual_clock':
        completed[0]['completed_at']=str(START+pd.Timedelta(minutes=6));completed[0]['timestamp']=completed[0]['completed_at']
    elif mode=='deadline':
        tx=next(x for x in diag['events'] if x['type']=='TARGET_SUBMITTED' and x['transition']=='ENTERING')
        tx['deadline']=str(START+pd.Timedelta(minutes=4));r.dump(folder/'strategy_diagnostics.json',diag)
    elif mode=='duplicate':completed.append(copy.deepcopy(completed[0]))
    else:completed[0]['proposal']['longs']=['DOGEUSDT','DOGEUSDT']
    r.dump(folder/'completed_baskets.json',completed);reseal(phase_export)
    with pytest.raises(AssertionError):verify(phase_export)


def test_resealed_wrong_preopen_completed_quantity_fails(phase_export):
    folder=phase_export[1]/'trials'/phase_export[2][0]
    exposure=pd.read_parquet(folder/'exposure.parquet')
    exposure.loc[exposure.timestamp.eq(START+pd.Timedelta(minutes=6)),'quantity_PEPEUSDT']=1
    exposure.to_parquet(folder/'exposure.parquet',index=False);exposure.to_csv(folder/'exposure.csv',index=False);reseal(phase_export)
    with pytest.raises(AssertionError,match='Exposure'):verify(phase_export)


def test_resealed_terminal_sub_epsilon_dust_not_ignored(phase_export):
    folder=phase_export[1]/'trials'/phase_export[2][0]
    exposure=pd.read_parquet(folder/'exposure.parquet')
    exposure['quantity_PEPEUSDT']=exposure['quantity_PEPEUSDT'].astype(float)
    exposure.loc[exposure.index[-1],'quantity_PEPEUSDT']=1e-12
    exposure.to_parquet(folder/'exposure.parquet',index=False);exposure.to_csv(folder/'exposure.csv',index=False)
    score=r.read(folder/'metrics.json');score.update(terminal_observed_nonzero_position_count=1,terminal_flat_resolved=False)
    r.dump(folder/'metrics.json',score);reseal(phase_export)
    receipt,verified,_=verify(phase_export)
    assert not receipt['terminal_flat_resolved'] and not verified['terminal_flat_resolved']


@pytest.mark.parametrize('name',['proposal_ledger.json','rejections.json'])
def test_resealed_missing_proposal_or_invented_rejection_export_fails(phase_export,name):
    if name=='proposal_ledger.json':change_json(phase_export,name,lambda rows:rows.clear())
    else:change_json(phase_export,name,lambda rows:rows.append({'type':'PROPOSAL_REJECTED','reason':'invented'}))
    with pytest.raises(AssertionError,match='export differs'):verify(phase_export)


def records():
    # Default full five-phase schedule; no financial replay mocked here.
    names=['validation1','validation2','validation3','evaluation','evaluation_stress']
    scores={name:dict(total_return=.01,return_after_indicative_exit_reserve=.009,sharpe=.7,
                      max_drawdown=.1,liquidation_event_count=0,terminal_flat_resolved=True,
                      completed_participants=['BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT'],completed_basket_count=2) for name in names}
    stamps=[a.EVAL+pd.DateOffset(months=k) for k in range(4)]
    equity=pd.DataFrame({'timestamp':stamps,'equity':[100000,101000,102000,103000]})
    return {name:({},score,equity.copy()) for name,score in scores.items()}


def test_all_fifteen_gates_are_independently_reconstructed():
    gates,*_=a.summary_gates(records());assert len(gates)==15 and all(gates.values())


@pytest.mark.parametrize('target,field,value,failed',[
 ('validation2','liquidation_event_count',1,'no_liquidation_all_five_runs'),
 ('validation3','terminal_flat_resolved',False,'actual_terminal_flat_all_five_runs'),
 ('evaluation','completed_participants',['BTCUSDT','ETHUSDT','DOGEUSDT','ADAUSDT'],'completed_pepe_participation'),
 ('evaluation','completed_basket_count',1,'two_completed_entry_generations'),
 ('evaluation','sharpe',None,'daily_sharpe_at_least_half'),
 ('evaluation_stress','return_after_indicative_exit_reserve',-.01,'positive_stress_after_exit_reserve')])
def test_bad_member_phase_or_undefined_metric_cannot_pass_gate(target,field,value,failed):
    data=records();data[target][1][field]=value;gates,*_=a.summary_gates(data)
    assert not gates[failed]


@pytest.mark.parametrize('field,value',[
 ('strategy','AnotherPortfolio'),('python','different-runtime'),
 ('source_sha256',{}),('terminal_forced_close',True)])
def test_resealed_execution_provenance_cannot_be_relabelled(phase_export,field,value):
    change_json(phase_export,'metadata.json',lambda metadata:metadata.update({field:value}))
    with pytest.raises(AssertionError):verify(phase_export)


def test_resealed_fabricated_daily_return_in_short_phase_fails(phase_export):
    folder=phase_export[1]/'trials'/phase_export[2][0]
    # The exported endpoint return includes the final partial UTC day. Its
    # value must agree with actual equity even when correctly resealed.
    pd.DataFrame({'timestamp':[str(START)],'return':[.5]}).to_csv(folder/'daily_returns.csv',index=False)
    reseal(phase_export)
    with pytest.raises(AssertionError,match='daily return'):verify(phase_export)


@pytest.mark.parametrize('column,value',[('quantity',1.),('price',110.),('fee',0.)])
def test_resealed_executable_fill_or_fee_discrepancy_fails(phase_export,column,value):
    folder=phase_export[1]/'trials'/phase_export[2][0]
    fills=pd.read_parquet(folder/'fills.parquet')
    fills.loc[fills.index[0],column]=value
    fills.to_parquet(folder/'fills.parquet',index=False);fills.to_csv(folder/'fills.csv',index=False)
    reseal(phase_export)
    with pytest.raises(AssertionError):verify(phase_export)
