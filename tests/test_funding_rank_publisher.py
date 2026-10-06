"""Synthetic certificates/export fixtures only; never reads actual study results."""
import copy
from pathlib import Path
import pandas as pd
import pytest
from examples.funding_rank import publish as p
from examples.funding_rank import run as r


@pytest.fixture
def packet(tmp_path,monkeypatch):
    out=tmp_path/'experiment';out.mkdir();calls=[]
    for name in ('source_lock.json','input_verification.json'):r.dump(out/name,{})
    (out/'features.parquet').write_bytes(b'synthetic immutable features')
    common={key:r.digest(out/name) for key,name in [('source_lock_sha256','source_lock.json'),('features_sha256','features.parquet')]}
    r.dump(out/'feature_receipt.json',common);common['feature_receipt_sha256']=r.digest(out/'feature_receipt.json')
    protocol=out/'executed_source/examples/funding_rank/proposed_protocol.md';protocol.parent.mkdir(parents=True);protocol.write_text('synthetic protocol')
    phases={};scores={}
    for name,begin,stop,stress in r.PHASES:
        folder=out/'trials'/name;folder.mkdir(parents=True)
        for filename in r.OUTPUTS:(folder/filename).write_bytes(b'synthetic sealed output')
        r.dump(folder/'completion.json',{})
        pd.DataFrame({'timestamp':pd.date_range(begin,periods=12,freq='D'),'equity':100000.}).to_parquet(folder/'equity.parquet')
        pd.DataFrame([dict(symbol=s,instrument_id=r.native_id('binance',s),net_pnl=0.,funding_cash=0.,fill_count=0,open_quantity=0.) for s in r.SYMBOLS]).to_csv(folder/'leg_contributions.csv',index=False)
        pd.DataFrame({'amount':pd.Series([],dtype=float)}).to_parquet(folder/'funding.parquet')
        r.dump(folder/'strategy_diagnostics.json',{'events':[]});r.dump(folder/'proposal_ledger.json',[]);r.dump(folder/'rejections.json',[])
        score=dict(total_return=0.,return_after_indicative_exit_reserve=0.,sharpe=None,max_drawdown=0.,funding_pnl=0.,trading_fees=0.,slippage_cost=0.,indicative_exit_reserve_total=0.,completed_basket_count=0,liquidation_event_count=0,terminal_flat_resolved=True)
        r.dump(folder/'metrics.json',score);scores[name]=score
        phases[name]=dict(outputs_sha256=r.output_files(folder),completion_sha256=r.digest(folder/'completion.json'),trajectory_reconstruction_passed=True,recorded_policy_intents={'recorded_policy_reconstruction_passed':True})
    summary=dict(family=r.FAMILY,candidate_count_cumulative=27,research_status='exploratory reused year; no untouched holdout',**common,
        scores=scores,gates={k:False for k in sorted(p.GATES)},passes_hurdles=False,failed_gates=sorted(p.GATES),
        validation_compounded_return=0.,validation_after_exit_reserve=0.,anchored_month_returns=[0.,0.,0.],conditional_interval={'comparison_count':27})
    r.dump(out/'summary.json',summary)
    feature=dict(complete=True,errors=[],source_anchor=p.SOURCE_ANCHOR,input_freeze_anchor=p.INPUT_ANCHOR,
        auditor_sha256=r.digest(p.FEATURE_AUDITOR),reference_helper_sha256=r.digest(p.REFERENCE_HELPER),source_unchanged_during_audit=True,
        auditor_source_unchanged=True,reference_reconstruction_passed=True,**common)
    fp=tmp_path/'feature.json';r.dump(fp,feature)
    financial=dict(complete=True,errors=[],source_anchor=p.SOURCE_ANCHOR,input_anchor=p.INPUT_ANCHOR,
        auditor_sha256=r.digest(p.FINANCIAL_AUDITOR),policy_auditor_sha256=r.digest(p.POLICY_AUDITOR),feature_audit_sha256=r.digest(fp),
        source_unchanged_during_audit=True,auditor_source_unchanged=True,policy_source_unchanged=True,gates_reconstructed=True,
        summary_sha256=r.digest(out/'summary.json'),phases=phases,**common)
    ap=tmp_path/'financial.json';r.dump(ap,financial)
    monkeypatch.setattr(r,'guard',lambda *args:None)
    monkeypatch.setattr(r,'verify_completed',lambda cache,out,phase:calls.append(phase[0]))
    return out,financial,feature,ap,fp,calls


def verify(packet):
    out,a,b,_,fp,_=packet;return p.verify_receipts(None,out,a,b,r.digest(fp))


def test_failed_hurdles_publish_with_complete_positive_audits(packet,tmp_path):
    out,a,b,ap,fp,calls=packet;destination=tmp_path/'report'
    p.publish(None,out,destination,ap,fp)
    manifest=r.read(destination/'publication_manifest.json')
    assert manifest['audited_output_count']==125 and len(calls)==10
    assert not r.read(destination/'summary.json')['passes_hurdles']
    assert len(pd.read_csv(destination/'all_leg_contributions.csv'))==40
    page=(destination/'report.html').read_text()
    assert 'Failed declared historical hurdles' in page and 'omitted unlogged skips' in page
    assert '<script src=' not in page
    for name,sha in manifest['outputs_sha256'].items():assert r.digest(destination/name)==sha
    assert r.digest(destination/'executed_publisher.py')==manifest['publisher_sha256']


@pytest.mark.parametrize('kind',[
 'financial_incomplete','feature_incomplete','financial_errors','feature_errors','source_anchor','input_anchor',
 'feature_source','financial_source','helper_source','policy_source','feature_binding','feature_receipt',
 'source_stable','policy_stable','feature_stable','reference','gates_flag','phase_missing','output_missing',
 'output_changed','completion_changed','trajectory','policy','summary_changed'])
def test_missing_or_stale_positive_audit_rejects_even_failed_results(packet,kind):
    out,a,b,ap,fp,_=packet;first=next(iter(a['phases']));proof=a['phases'][first]
    if kind=='financial_incomplete':a['complete']=False
    elif kind=='feature_incomplete':b['complete']=False
    elif kind=='financial_errors':a['errors']=['cash mismatch']
    elif kind=='feature_errors':b['errors']=['leak']
    elif kind=='source_anchor':a['source_anchor']='wrong'
    elif kind=='input_anchor':b['input_freeze_anchor']='wrong'
    elif kind=='feature_source':b['auditor_sha256']='wrong'
    elif kind=='financial_source':a['auditor_sha256']='wrong'
    elif kind=='helper_source':b['reference_helper_sha256']='wrong'
    elif kind=='policy_source':a['policy_auditor_sha256']='wrong'
    elif kind=='feature_binding':a['feature_audit_sha256']='wrong'
    elif kind=='feature_receipt':a['feature_receipt_sha256']='wrong'
    elif kind=='source_stable':a['source_unchanged_during_audit']=False
    elif kind=='policy_stable':a['policy_source_unchanged']=False
    elif kind=='feature_stable':b['auditor_source_unchanged']=False
    elif kind=='reference':b['reference_reconstruction_passed']=False
    elif kind=='gates_flag':a['gates_reconstructed']=False
    elif kind=='phase_missing':del a['phases'][first]
    elif kind=='output_missing':proof['outputs_sha256'].pop('funding.csv')
    elif kind=='output_changed':(out/'trials'/first/'funding.csv').write_bytes(b'changed')
    elif kind=='completion_changed':(out/'trials'/first/'completion.json').write_bytes(b'changed')
    elif kind=='trajectory':proof['trajectory_reconstruction_passed']=False
    elif kind=='policy':proof['recorded_policy_intents']=None
    elif kind=='summary_changed':a['summary_sha256']='wrong'
    with pytest.raises(RuntimeError):verify(packet)


@pytest.mark.parametrize('mode',['empty','partial','nonboolean','pass_flag','failed_list','candidate','phase_score'])
def test_resealed_summary_cannot_truncate_or_invent_claims(packet,mode):
    out,a,b,ap,fp,_=packet;summary=r.read(out/'summary.json')
    if mode=='empty':summary['gates']={}
    elif mode=='partial':summary['gates'].pop(next(iter(summary['gates'])))
    elif mode=='nonboolean':summary['gates'][next(iter(summary['gates']))]=0
    elif mode=='pass_flag':summary['passes_hurdles']=True
    elif mode=='failed_list':summary['failed_gates']=[]
    elif mode=='candidate':summary['candidate_count_cumulative']=26
    else:summary['scores']['evaluation']['total_return']=1.
    r.dump(out/'summary.json',summary);a['summary_sha256']=r.digest(out/'summary.json')
    with pytest.raises(RuntimeError):verify(packet)


@pytest.mark.parametrize('mode',['existing','experiment_namespace','same_receipt'])
def test_preserves_existing_report_and_experiment(packet,tmp_path,mode):
    out,a,b,ap,fp,_=packet;destination=tmp_path/'report'
    if mode=='existing':destination.mkdir();(destination/'old.txt').write_text('preserve')
    elif mode=='experiment_namespace':destination=out/'executed_source/new-report'
    else:fp=ap
    with pytest.raises(RuntimeError):p.publish(None,out,destination,ap,fp)
    if mode=='existing':assert (destination/'old.txt').read_text()=='preserve'


@pytest.mark.parametrize('mode',['publisher','receipt','ledger'])
def test_mid_generation_mutation_never_promotes(packet,tmp_path,monkeypatch,mode):
    out,a,b,ap,fp,_=packet;destination=tmp_path/'report';original=p.build_report
    if mode=='publisher':
        source=tmp_path/'publisher.py';source.write_bytes(Path(p.__file__).read_bytes());monkeypatch.setattr(p,'__file__',str(source))
    def changed(*args):
        result=original(*args)
        target=source if mode=='publisher' else ap if mode=='receipt' else out/'trials/evaluation/funding.csv'
        target.write_bytes(target.read_bytes()+b'changed');return result
    monkeypatch.setattr(p,'build_report',changed)
    with pytest.raises(RuntimeError):p.publish(None,out,destination,ap,fp)
    assert not destination.exists() and not list(tmp_path.glob('.report-*'))


def test_activity_counts_distinguish_refused_proposals_and_real_abort(packet):
    out,*_=packet;folder=out/'trials/evaluation'
    proposals=[{'type':'WEEKLY_PROPOSAL'},{'type':'PROPOSAL_REJECTED'}]
    r.dump(folder/'proposal_ledger.json',proposals)
    r.dump(folder/'strategy_diagnostics.json',{'events':proposals+[{'type':'ACCOUNT_ABORT'},
        {'type':'BLOCKED_CLEANUP'},{'type':'TARGET_SUBMITTED','transition':'ENTERING'}]})
    r.dump(folder/'rejections.json',[proposals[1]])
    _,_,_,activity=p.build_report(out,r.read(out/'summary.json'))
    row=next(row for row in activity if row['phase']=='evaluation')
    assert row['weekly_proposals']==1 and row['rejected_weekly_proposals']==1
    assert row['abort_events']==1 and row['blocked_cleanup_events']==1 and row['entry_transactions']==1
