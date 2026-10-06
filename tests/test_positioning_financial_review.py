"""Independent resealed-export adversaries; only tiny synthetic Engine inputs."""
import importlib.metadata
import subprocess
import sys
import pandas as pd
import pytest
from audit import verify_positioning_outputs as a
from examples.positioning_research import run as r
from tests.test_positioning_runner_audit import executed

@pytest.fixture
def phase_packet(executed):
    cache,_,out,phase,cert,*_=executed
    lock=a.read(out/'source_lock.json')
    lock['runtime']={'python':sys.version,**{n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','scipy','plotly')}}
    r.dump(out/'source_lock.json',lock)
    folder=out/'trials'/phase[0]
    meta=r.read(folder/'metadata.json');meta['parameters']=r.parameters(out,phase,cert);meta['source_manifest']=r.source_manifest(out)
    r.dump(folder/'metadata.json',meta);r.dump(folder/'source_manifest.json',meta['source_manifest'])
    seal(folder,meta['parameters'])
    anchor=subprocess.run(['git','rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
    return cache,out,phase,lock,anchor,cert

def seal(folder,parameters=None):
    parameters=parameters or r.read(folder/'completion.json')['parameters']
    r.dump(folder/'completion.json',{'parameters':parameters,'outputs_sha256':r.output_files(folder)})

def replay(packet):return a.verify_phase(*packet)

def test_valid_full_export_has_financial_only_scope(phase_packet):
    receipt,score,_=replay(phase_packet)
    assert receipt['trajectory_reconstruction_passed'] is True
    assert receipt['recorded_policy_reconstruction_complete'] is False
    assert len(receipt['outputs_sha256'])==26
    assert score['completed_episode_count']==1 and score['terminal_flat_resolved'] is True

@pytest.mark.parametrize('field,value',[
    ('total_return',.9),('max_drawdown',.9),('completed_episode_count',2),
    ('completed_participants',['DOGEUSDT','PEPEUSDT']),('terminal_flat_resolved',False),
    ('indicative_exit_reserve_total',12.),('liquidation_event_count',1),('unreviewed_winner_metric',123.)])
def test_resealed_score_cannot_invent_returns_activity_or_reserves(phase_packet,field,value):
    _,out,phase,*_=phase_packet;folder=out/'trials'/phase[0]
    metrics=r.read(folder/'metrics.json');metrics[field]=value;r.dump(folder/'metrics.json',metrics);seal(folder)
    with pytest.raises(AssertionError):replay(phase_packet)

@pytest.mark.parametrize('kind',['proposal','rejection','episode_alias','entry_not_closed','native_leg','minute_dd','terminal_dust'])
def test_resealed_activity_native_and_observer_exports_are_recomputed(phase_packet,kind):
    _,out,phase,*_=phase_packet;folder=out/'trials'/phase[0]
    if kind=='proposal':r.dump(folder/'proposal_ledger.json',[])
    elif kind=='rejection':r.dump(folder/'rejections.json',[{'type':'REJECTED','reason':'invented'}])
    elif kind=='episode_alias':r.dump(folder/'completed_baskets.json',[])
    elif kind=='entry_not_closed':
        # Both aliases removed; the independently checked actual closure diagnostic still exists.
        r.dump(folder/'completed_baskets.json',[]);r.dump(folder/'completed_episodes.json',[])
    elif kind=='native_leg':
        df=pd.read_csv(folder/'leg_contributions.csv');df.loc[df.symbol.eq('PEPEUSDT'),'instrument_id']='binance:perpetual:PEPEUSDT';df.to_csv(folder/'leg_contributions.csv',index=False)
    else:
        name='equity' if kind=='minute_dd' else 'exposure';df=pd.read_parquet(folder/(name+'.parquet'))
        if kind=='minute_dd':df.loc[len(df)//2,'equity']*=.7
        else:
            df['quantity_PEPEUSDT']=df['quantity_PEPEUSDT'].astype(float)
            df.loc[len(df)-1,'quantity_PEPEUSDT']=1e-12
        df.to_parquet(folder/(name+'.parquet'),index=False);df.to_csv(folder/(name+'.csv'),index=False)
    seal(folder)
    with pytest.raises(AssertionError):replay(phase_packet)

@pytest.mark.parametrize('key,value',[('strategy','OtherCoordinator'),('terminal_forced_close',True),('open_positions_marked',False),('software','other')])
def test_resealed_execution_identity_is_not_only_a_hash_check(phase_packet,key,value):
    _,out,phase,*_=phase_packet;folder=out/'trials'/phase[0];meta=r.read(folder/'metadata.json')
    meta[key]=value;r.dump(folder/'metadata.json',meta);seal(folder)
    with pytest.raises(AssertionError):replay(phase_packet)

def test_phase_output_mutation_during_reconstruction_is_rejected(phase_packet,monkeypatch):
    _,out,phase,*_=phase_packet;target=out/'trials'/phase[0]/'proposal_ledger.json';original=a.reconstruct
    def changed(*args,**kwargs):
        state=original(*args,**kwargs);target.write_bytes(target.read_bytes()+b' ');return state
    monkeypatch.setattr(a,'reconstruct',changed)
    with pytest.raises(AssertionError,match='Evidence changed'):replay(phase_packet)

@pytest.mark.parametrize('artifact',['auditor','reference_helper','published_lock','feature_receipt','feature'])
def test_first_provenance_call_cannot_relabel_preexisting_source_or_common_bytes(tmp_path,monkeypatch,artifact):
    repo=tmp_path/'repo';out=tmp_path/'out';repo.mkdir();out.mkdir()
    auditor=repo/'audit/verify_positioning_outputs.py';auditor.parent.mkdir();auditor.write_text('# executed original auditor\n')
    monkeypatch.setattr(a,'REPO',repo);monkeypatch.setattr(a,'__file__',str(auditor))
    for name in ('audit/verify_funding_rank_outputs.py',a.FEATURE_AUDITOR,'audit/verify_positioning_dataset.py',a.PREREG+'/preregistration.json'):
        p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# immutable synthetic helper\n')
    cert=out/'feature_audit.json';cert.write_text('{}')
    for name in ('source_lock.json','input_verification.json','feature_receipt.json','published_lock.json','summary.json'):(out/name).write_text('{}')
    for group in a.native_feature_paths(out).values():
        for p in group.values():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'feature-before-guard')
    for phase in a.PHASES:(out/'trials'/phase[0]).mkdir(parents=True)
    targets={'auditor':auditor,'reference_helper':repo/'audit/verify_funding_rank_outputs.py',
             'published_lock':out/'published_lock.json','feature_receipt':out/'feature_receipt.json',
             'feature':next(iter(a.native_feature_paths(out)['baseline'].values()))}
    target=targets[artifact]
    def mutate(*args):target.write_bytes(target.read_bytes()+b' ');return {}
    monkeypatch.setattr(a,'packet_guard',mutate)
    monkeypatch.setattr(a,'evidence_hashes',lambda *args:{str(target.resolve()):a.sha(target)})
    def forbidden(*args):raise RuntimeError('reached numeric/certificate verification after unsealed initial drift')
    monkeypatch.setattr(a,'verify_feature_certificate',forbidden)
    with pytest.raises(AssertionError,match='changed|drift|differ'):
        a.verify(tmp_path/'perp',tmp_path/'metrics',out,'a'*40,'b'*40,cert)

@pytest.mark.parametrize('stress,partial,symbol',[(False,False,'BTCUSDT'),(True,False,'PEPEUSDT'),(False,True,'DOGEUSDT')])
def test_added_pre_callback_detail_does_not_change_reviewed_financial_replay(monkeypatch,stress,partial,symbol):
    from tests.test_positioning_financial_audit import evidence
    from audit import verify_funding_rank_outputs as previous
    args,_,_=evidence(monkeypatch,stress,partial,symbol)
    begin=args[0]['equity'].timestamp.iloc[0];stop=args[0]['equity'].timestamp.iloc[-1]
    current,clocks=a.reconstruct(*args,begin,stop)
    original,old_clocks=previous.reconstruct(*args,begin,stop)
    assert clocks==old_clocks and current.q==original.q and current.cash==original.cash
    assert current.trade_rows==original.trade_rows and current.preopen_account==original.preopen_account
    assert set(current.preopen_detail)==set(clocks)
    for timestamp,detail in current.preopen_detail.items():
        assert set(detail)=={'marks','average_prices','liquidation_before_callback'}
        assert set(detail['marks'])==set(current.ids) and set(detail['average_prices'])==set(current.ids)
        assert type(detail['liquidation_before_callback']) is bool
