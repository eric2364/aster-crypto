"""Independent recorded-policy adversaries on manufactured multi-hour inputs."""
from dataclasses import asdict
import copy
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from audit import verify_positioning_outputs as financial
from audit import verify_positioning_policy as policy
from examples.positioning_research.strategy import PositioningPortfolio
from examples.funding_rank.run import SnapshotObserver,forensic_normalize
from tests.test_funding_rank_execution import START,catalog,candles,config
from tests.test_positioning_strategy import features

@pytest.fixture
def recorded():
    begin=START;stop=begin+pd.Timedelta(minutes=300);specs=list(catalog().values());cfg=config()
    feature=features(minutes=300,eligible=('BTCUSDT','ETHUSDT'))
    bars=candles(minutes=300);fund=pd.DataFrame({'timestamp':pd.Series([],dtype='datetime64[ns, UTC]'),
        'instrument_id':pd.Series([],dtype=str),'funding_rate':pd.Series([],dtype=float),'mark_price':pd.Series([],dtype=float)})
    engine=Engine(specs,cfg);observer=SnapshotObserver(engine);engine.portfolio.snapshot=observer
    strategy=PositioningPortfolio(feature,stop);result=engine.run(bars,strategy,fund)
    tables={name:getattr(result,name) for name in financial.LEDGERS}
    sources={s.id:bars.loc[bars.instrument_id.eq(s.id)].reset_index(drop=True) for s in specs}
    state,preopen=financial.reconstruct(tables,pd.DataFrame(observer.rows),sources,fund,[asdict(s) for s in specs],asdict(cfg),begin,stop)
    args=[feature,{'events':forensic_normalize(strategy.diagnostics)},preopen,state.preopen_account,
          state.preopen_detail,[asdict(s) for s in specs],tables['events'],tables['fills'],begin,stop,asdict(cfg),forensic_normalize(strategy.completed_episodes)]
    return args

def test_valid_fixed_lifecycle_and_resolved_idle_scope(recorded):
    result=policy.verify_policy(*recorded)
    assert result['actual_completed_entries']==1 and result['actual_completed_closed_episodes']==1
    assert result['full_cleanup_state_reconstruction_passed'] is False
    assert result['all_unlogged_abort_transitions_proved'] is False


def test_logged_mandatory_held_exit_cannot_replace_actual_close_submission(recorded):
    args=copy.deepcopy(recorded)
    # Financial reconstruction supplies real account evidence; policy independently
    # must reject a missing linkage rather than accepting EPISODE_EXIT alone.
    args[1]['events']=[r for r in args[1]['events'] if not (r['type']=='TARGET_SUBMITTED' and r['transition']=='EXITING')]
    with pytest.raises(AssertionError):policy.verify_policy(*args)

@pytest.mark.parametrize('mutation',['priority','eligibility','native_quantity','source_clock','hold_reason','completion_clock','closed_episode'])
def test_recorded_actions_are_checked_against_actual_inputs(recorded,mutation):
    args=copy.deepcopy(recorded);events=args[1]['events']
    proposal=next(r for r in events if r['type']=='EVENT_PROPOSAL')
    entry=next(r for r in events if r['type']=='TARGET_SUBMITTED' and r['transition']=='ENTERING')
    complete=next(r for r in events if r['type']=='ENTRY_COMPLETE')
    if mutation=='priority':proposal['symbol']='ETHUSDT';proposal['eligible_symbols']=['ETHUSDT','BTCUSDT']
    elif mutation=='eligibility':args[0][policy.iid('BTCUSDT')].loc[pd.Timestamp(proposal['timestamp']),'quantity_change_5m']=-.01
    elif mutation=='native_quantity':entry['targets'][policy.iid('BTCUSDT')]+=1
    elif mutation=='source_clock':args[0][policy.iid('BTCUSDT')].loc[pd.Timestamp(proposal['timestamp']),'metric_available_at']=pd.Timestamp(proposal['timestamp'])
    elif mutation=='hold_reason':next(r for r in events if r['type']=='EPISODE_EXIT')['reason']='profitable_target'
    elif mutation=='completion_clock':complete['completed_at']=(pd.Timestamp(complete['completed_at'])+pd.Timedelta(minutes=1)).isoformat()
    else:args[-1]=[]
    with pytest.raises(AssertionError):policy.verify_policy(*args)

def test_successful_admission_cannot_also_claim_rejection(recorded):
    args=copy.deepcopy(recorded);rows=args[1]['events'];entry=next(r for r in rows if r['type']=='TARGET_SUBMITTED' and r['transition']=='ENTERING')
    index=rows.index(entry)+1
    rows.insert(index,{'timestamp':entry['timestamp'],'type':'ADMISSION_REJECTED','generation':entry['generation'],
        'symbol':'BTCUSDT','reason':'opening_minimum','cooldown_until':(pd.Timestamp(entry['timestamp'])+pd.Timedelta(hours=1)).isoformat()})
    with pytest.raises(AssertionError):policy.verify_policy(*args)


def test_eligible_resolved_idle_decision_cannot_be_removed(recorded):
    args=copy.deepcopy(recorded);rows=args[1]['events'];first=next(r['timestamp'] for r in rows if r['type']=='EVENT_PROPOSAL')
    args[1]['events']=[r for r in rows if r['timestamp']!=first]
    with pytest.raises(AssertionError,match='eligible flat review'):policy.verify_policy(*args)

def test_recorded_early_hold_exit_is_not_certified_as_four_hours():
    from tests.test_positioning_policy import entry_fixture
    args,submitted,observed=entry_fixture();now=observed+pd.Timedelta(minutes=1);sold=now+pd.Timedelta(minutes=1);flat=sold+pd.Timedelta(minutes=1)
    selected=policy.iid('BTCUSDT');targets={i:0. for i in args[0]}
    args[1]['events'] += [
        {'timestamp':now,'type':'EPISODE_EXIT','generation':1,'reason':'four_hour_hold'},
        {'timestamp':now,'type':'TARGET_SUBMITTED','generation':1,'transition':'EXITING','targets':targets,'deadline':now+pd.Timedelta(minutes=5),'order_ids':['O2']},
        {'timestamp':flat,'type':'NORMAL_FLAT','generation':1,'cooldown_until':flat+pd.Timedelta(hours=1)}]
    args[1]['events'].sort(key=lambda r:pd.Timestamp(r['timestamp']))
    args[6] += [{'timestamp':now,'type':'ORDER_SUBMITTED','order_id':'O2','instrument_id':selected,'quantity':100.,'side':-1,'active_at':now,'tif':'GTC','order_type':'market','reduce_only':True},
                {'timestamp':now,'type':'ORDER_ACCEPTED','order_id':'O2'},{'timestamp':sold,'type':'ORDER_FILLED','order_id':'O2'}]
    args[7].append({'timestamp':sold,'order_id':'O2','instrument_id':selected,'quantity':100.,'price':100.})
    for t in args[2]:
        if t>=flat:
            args[2][t][selected]=0.;args[4][t]['average_prices'][selected]=0.
            args[3][t].update(binance_available_margin=100000.,binance_margin_used=0.,binance_gross_exposure=0.,maintenance_margin=0.)
    with pytest.raises(AssertionError):policy.verify_policy(*args)

def test_successful_full_entry_and_normal_flat_require_closed_episode(recorded):
    args=copy.deepcopy(recorded)
    args[1]['events']=[r for r in args[1]['events'] if r['type']!='EPISODE_CLOSED'];args[-1]=[]
    with pytest.raises(AssertionError):policy.verify_policy(*args)

@pytest.fixture
def cohort_packet(phase_packet,monkeypatch):
    from pathlib import Path
    from examples.positioning_research import run as runner
    cache,out,phase,lock,anchor,featurecert=phase_packet
    monkeypatch.setattr(financial,'PHASES',[phase])
    packet=features(minutes=120)
    for group in financial.native_feature_paths(out).values():
        for native,path in group.items():path.parent.mkdir(parents=True,exist_ok=True);packet[native].to_parquet(path)
    runner.dump(out/'summary.json',{})
    hashes=runner.read(out/'feature_receipt.json')['features_sha256']
    proof,_,_=financial.verify_phase(cache,out,phase,lock,anchor,featurecert)
    cert={'complete':True,'errors':[],'financial_reconstruction_complete':True,'complete_financial_scope':True,'gates_reconstructed':True,'candidate_count_cumulative':28,
          'policy_reconstruction_complete':False,'recorded_policy_reconstruction_complete':False,'publication_ready':False,
          'source_anchor':'source','input_anchor':anchor,'auditor_sha256':financial.sha(financial.__file__),
          'reference_helper_sha256':financial.sha(financial.REPO/'audit/verify_funding_rank_outputs.py'),
          'feature_audit_sha256':financial.sha(featurecert),'feature_auditor_sha256':financial.sha(financial.REPO/financial.FEATURE_AUDITOR),
          'features_sha256':hashes,'phases':{phase[0]:proof}}
    for flag in ('source_unchanged_during_audit','input_unchanged_during_audit','features_unchanged_during_audit','auditor_source_unchanged','reference_source_unchanged','all_phase_evidence_unchanged'):cert[flag]=True
    for field,name in [('source_lock_sha256','source_lock.json'),('input_verification_sha256','input_verification.json'),('feature_receipt_sha256','feature_receipt.json'),('published_lock_sha256','published_lock.json'),('summary_sha256','summary.json')]:cert[field]=financial.sha(out/name)
    path=out/'financial_cert.json';runner.dump(path,cert)
    calls=[]
    monkeypatch.setattr(financial,'packet_guard',lambda *args:calls.append('guard'))
    monkeypatch.setattr(financial,'verify_feature_certificate',lambda *args:{'features_sha256':hashes})
    def evidence(*args):
        files=[out/n for n in ('source_lock.json','input_verification.json','feature_receipt.json','published_lock.json','summary.json')]
        files += [p for group in financial.native_feature_paths(out).values() for p in group.values()]
        files += [out/'trials'/phase[0]/n for n in (*financial.OUTPUTS,'completion.json')]
        return {str(p.resolve()):financial.sha(p) for p in files}
    monkeypatch.setattr(financial,'evidence_hashes',evidence)
    monkeypatch.setattr(policy,'verify_policy',lambda *args:{'recorded_policy_reconstruction_passed':True}) # binding-only tests
    return (cache,cache,out,'source',anchor,featurecert,path),cert,calls

from tests.test_positioning_financial_review import phase_packet
from tests.test_positioning_runner_audit import executed

def test_wrapper_valid_positive_binding_retains_bounded_scope(cohort_packet):
    args,_,_=cohort_packet;result=policy.verify_cohort(*args)
    assert result['recorded_policy_reconstruction_complete'] is True
    for flag in ('policy_reconstruction_complete','full_cleanup_state_reconstruction_passed','all_unlogged_abort_transitions_proved','publication_ready'):assert result[flag] is False

@pytest.mark.parametrize('flag',['complete_financial_scope','gates_reconstructed','candidate_count_cumulative'])
def test_wrapper_missing_positive_financial_certificate_claim_rejected(cohort_packet,flag):
    from examples.positioning_research import run as runner
    args,cert,_=cohort_packet;cert.pop(flag);runner.dump(args[-1],cert)
    with pytest.raises(AssertionError):policy.verify_cohort(*args)


def test_wrapper_final_provenance_mutation_cannot_escape_last_stability_check(cohort_packet,monkeypatch):
    args,_,_=cohort_packet;calls=[];target=args[2]/'published_lock.json'
    def changed(*unused):
        calls.append(1)
        if len(calls)==2:target.write_bytes(target.read_bytes()+b' ')
    monkeypatch.setattr(financial,'packet_guard',changed)
    with pytest.raises(AssertionError,match='changed|differ|drift'):policy.verify_cohort(*args)

@pytest.mark.parametrize('kind',['source_anchor','summary','financial_scope','output_bytes','completion','native_features'])
def test_wrapper_cannot_relabel_certified_study_or_sealed_evidence(cohort_packet,kind):
    from examples.positioning_research import run as runner
    args,cert,_=cohort_packet
    if kind=='source_anchor':cert['source_anchor']='different'
    elif kind=='summary':cert['summary_sha256']='0'*64
    elif kind=='financial_scope':cert['policy_reconstruction_complete']=True
    elif kind=='output_bytes':next(iter(cert['phases'].values()))['outputs_sha256']['fills.parquet']='0'*64
    elif kind=='completion':next(iter(cert['phases'].values()))['completion_sha256']='0'*64
    else:cert['features_sha256']={'baseline':'different','delayed':'different'}
    runner.dump(args[-1],cert)
    with pytest.raises(AssertionError):policy.verify_cohort(*args)


def test_wrapper_policy_source_change_during_replay_is_detected(cohort_packet,monkeypatch,tmp_path):
    args,_,_=cohort_packet;source=tmp_path/'executed_policy.py';source.write_text('# original policy auditor\n')
    monkeypatch.setattr(policy,'__file__',str(source))
    def changed(*unused):
        source.write_text('# replaced auditor\n');return {'recorded_policy_reconstruction_passed':True}
    monkeypatch.setattr(policy,'verify_policy',changed)
    with pytest.raises(AssertionError,match='changed'):policy.verify_cohort(*args)
