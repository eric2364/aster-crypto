"""Only synthetic study/certificate fixtures; actual candidate28 outputs are never read."""
from pathlib import Path
import copy
import pandas as pd
import pytest
from examples.positioning_research import publish as p
r=p.r

@pytest.fixture
def packet(tmp_path,monkeypatch):
    out=tmp_path/'experiment';out.mkdir()
    for n in p.COMMON:r.dump(out/n,{})
    feature=dict(complete=True,errors=[],features_sha256={'baseline':{},'delayed':{}})
    fp=tmp_path/'feature.json';r.dump(fp,feature)
    phases={};policies={};scores={}
    for name,begin,stop,stress in r.PHASES:
        folder=out/'trials'/name;folder.mkdir(parents=True)
        for n in (*r.OUTPUTS,'completion.json'):(folder/n).write_bytes(b'synthetic')
        pd.DataFrame({'timestamp':pd.date_range(begin,periods=12,freq='D'),'equity':100000.}).to_parquet(folder/'equity.parquet')
        pd.DataFrame([dict(symbol=s,instrument_id=r.native_id('binance',s),net_pnl=0.,funding_cash=0.,fill_count=0,open_quantity=0.) for s in r.SYMBOLS]).to_csv(folder/'leg_contributions.csv',index=False)
        pd.DataFrame({'amount':pd.Series([],dtype=float)}).to_parquet(folder/'funding.parquet')
        r.dump(folder/'completed_episodes.json',[])
        score=dict(total_return=0.,return_after_indicative_exit_reserve=0.,sharpe=None,max_drawdown=0.,funding_pnl=0.,trading_fees=0.,slippage_cost=0.,indicative_exit_reserve_total=0.,terminal_flat_resolved=True)
        r.dump(folder/'metrics.json',score);scores[name]=score
        phases[name]=dict(outputs_sha256=r.output_files(folder),completion_sha256=r.digest(folder/'completion.json'),trajectory_reconstruction_passed=True)
        policies[name]=dict(outputs_sha256=r.output_files(folder),completion_sha256=r.digest(folder/'completion.json'),recorded_policy_reconstruction_passed=True,all_callback_clocks_examined=True,full_cleanup_state_reconstruction_passed=False,all_unlogged_abort_transitions_proved=False)
    summary=dict(family=r.FAMILY,candidate_count_cumulative=28,research_status='exploratory reused year; no untouched holdout',scores=scores,gates={k:False for k in sorted(p.GATES)},passes_hurdles=False,failed_gates=sorted(p.GATES),validation_compounded_return=0.,validation_after_exit_reserve=0.,anchored_month_returns=[0.,0.,0.],conditional_interval={'comparison_count':28},source_lock_sha256=r.digest(out/'source_lock.json'),feature_receipt_sha256=r.digest(out/'feature_receipt.json'),feature_audit_sha256=r.digest(fp),features_sha256=feature['features_sha256'])
    r.dump(out/'summary.json',summary)
    common={n:r.digest(out/n) for n in p.COMMON}
    shared=dict(complete=True,errors=[],source_anchor=p.SOURCE_ANCHOR,input_anchor=p.INPUT_ANCHOR,features_sha256=feature['features_sha256'],feature_audit_sha256=r.digest(fp),scope='synthetic scoped reconstruction',limitations=['No exhaustive cleanup/omission proof.'],**{k:True for k in p.STABILITY},**{n.removesuffix('.json')+'_sha256':v for n,v in common.items()})
    financial=dict(**shared,auditor_sha256=r.digest(p.FINANCIAL_AUDITOR),common_artifacts_sha256=common,financial_reconstruction_complete=True,complete_financial_scope=True,gates_reconstructed=True,policy_reconstruction_complete=False,recorded_policy_reconstruction_complete=False,publication_ready=False,reference_source_unchanged=True,reference_helper_sha256=r.digest(r.REPO/'audit/verify_funding_rank_outputs.py'),feature_auditor_sha256=r.digest(r.REPO/'audit/verify_positioning_features.py'),phases=phases)
    ap=tmp_path/'financial.json';r.dump(ap,financial)
    policy=dict(**shared,auditor_sha256=r.digest(p.POLICY_AUDITOR),recorded_policy_reconstruction_complete=True,policy_reconstruction_complete=False,publication_ready=False,full_cleanup_state_reconstruction_passed=False,all_unlogged_abort_transitions_proved=False,financial_source_unchanged=True,financial_audit_sha256=r.digest(ap),financial_auditor_sha256=r.digest(p.FINANCIAL_AUDITOR),reference_helper_sha256=financial['reference_helper_sha256'],phases=policies)
    pp=tmp_path/'policy.json';r.dump(pp,policy)
    monkeypatch.setattr(p.financial_reference,'packet_guard',lambda *a:None)
    monkeypatch.setattr(p.financial_reference,'verify_feature_certificate',lambda *a:r.read(fp))
    monkeypatch.setattr(r,'verify_completed',lambda *a,**k:None)
    def evidence(out,lock,feature):
        paths={out/n for n in p.COMMON}|{fp}|{out/'trials'/phase[0]/n for phase in r.PHASES for n in (*r.OUTPUTS,'completion.json')}
        return {str(x.resolve()):r.digest(x) for x in paths}
    monkeypatch.setattr(p.financial_reference,'evidence_hashes',evidence)
    return out,ap,fp,pp


def verify(packet):
    out,ap,fp,pp=packet;return p.verify_receipts('synthetic-perp','synthetic-metrics',out,ap,fp,pp)


def test_failed_gates_publish_all_evidence_and_honest_scopes(packet,tmp_path):
    out,ap,fp,pp=packet;dest=tmp_path/'published'
    p.publish('synthetic-perp','synthetic-metrics',out,dest,ap,fp,pp)
    manifest=r.read(dest/'publication_manifest.json')
    assert manifest['audited_output_count']==130 and manifest['qualified_historical_count']==0
    assert manifest['composed_publication_ready'] and not r.read(dest/'financial_audit.json')['publication_ready']
    assert not r.read(dest/'recorded_policy_audit.json')['publication_ready']
    assert len(pd.read_csv(dest/'all_leg_contributions.csv'))==40
    page=(dest/'report.html').read_text()
    assert 'no qualified strategy' in page and 'not verified forced-liquidation' in page
    assert '<script src=' not in page and 'outside resolved audited idle windows' in page
    assert not pd.read_csv(dest/'activity.csv').completed_DOGE.any()
    for name,digest in manifest['outputs_sha256'].items():assert r.digest(dest/name)==digest


@pytest.mark.parametrize('cert,key,value',[(c,k,v) for c in ('financial','policy') for k,v in [('complete',False),('errors',['mismatch']),('source_anchor','wrong'),('input_anchor','wrong'),('auditor_sha256','wrong'),('features_sha256',{}),('summary_sha256','wrong'),('feature_audit_sha256','wrong'),('scope',''),('limitations',[])]]+[(c,k,False) for c in ('financial','policy') for k in p.STABILITY]+[('financial','publication_ready',True),('financial','recorded_policy_reconstruction_complete',True),('financial','gates_reconstructed',False),('financial','reference_helper_sha256','wrong'),('policy','recorded_policy_reconstruction_complete',False),('policy','publication_ready',True),('policy','full_cleanup_state_reconstruction_passed',True),('policy','financial_source_unchanged',False),('policy','financial_audit_sha256','wrong'),('policy','financial_auditor_sha256','wrong')])
def test_incomplete_stale_or_overclaimed_certificate_fails(packet,cert,key,value):
    out,ap,fp,pp=packet;path=ap if cert=='financial' else pp
    data=r.read(path);data[key]=value;r.dump(path,data)
    with pytest.raises(RuntimeError):verify(packet)


@pytest.mark.parametrize('kind',['missing_phase','missing_export','changed_export','changed_completion','policy_clock','policy_cleanup','summary_gate','summary_claim','summary_candidate','summary_score'])
def test_exact_cohort_and_summary_required(packet,kind):
    out,ap,fp,pp=packet;fin=r.read(ap);pol=r.read(pp);name='evaluation'
    if kind=='missing_phase':del pol['phases'][name]
    elif kind=='missing_export':pol['phases'][name]['outputs_sha256'].pop('funding.csv')
    elif kind=='changed_export':(out/'trials'/name/'funding.csv').write_bytes(b'changed')
    elif kind=='changed_completion':(out/'trials'/name/'completion.json').write_bytes(b'changed')
    elif kind=='policy_clock':pol['phases'][name]['all_callback_clocks_examined']=False
    elif kind=='policy_cleanup':pol['phases'][name]['full_cleanup_state_reconstruction_passed']=True
    else:
        s=r.read(out/'summary.json')
        if kind=='summary_gate':s['gates']={}
        elif kind=='summary_claim':s['passes_hurdles']=True
        elif kind=='summary_candidate':s['candidate_count_cumulative']=27
        else:s['scores'][name]['total_return']=1.
        r.dump(out/'summary.json',s);digest=r.digest(out/'summary.json')
        fin['summary_sha256']=pol['summary_sha256']=digest;fin['common_artifacts_sha256']['summary.json']=digest
    r.dump(ap,fin);pol['financial_audit_sha256']=r.digest(ap);r.dump(pp,pol)
    with pytest.raises(RuntimeError):verify(packet)


@pytest.mark.parametrize('mode',['initial_guard','render_receipt','render_earlier_phase','render_source','final_guard'])
def test_mutation_at_each_boundary_cannot_promote(packet,tmp_path,monkeypatch,mode):
    out,ap,fp,pp=packet;dest=tmp_path/'report';source=tmp_path/'publisher.py';source.write_bytes(Path(p.__file__).read_bytes());monkeypatch.setattr(p,'__file__',str(source))
    target=out/'published_lock.json' if mode=='initial_guard' else pp if mode=='render_receipt' else source if mode=='render_source' else out/'trials/validation1/funding.csv'
    def mutate():target.write_bytes(target.read_bytes()+b' ')
    if mode=='initial_guard':monkeypatch.setattr(p.financial_reference,'packet_guard',lambda *a:mutate())
    elif mode=='final_guard':
        old=p.verify_receipts;calls=[]
        def guard(*a):
            value=old(*a);calls.append(1)
            if len(calls)==2:mutate()
            return value
        monkeypatch.setattr(p,'verify_receipts',guard)
    else:
        old=p.build_report
        def render(*a):
            value=old(*a);mutate();return value
        monkeypatch.setattr(p,'build_report',render)
    with pytest.raises(RuntimeError):p.publish('synthetic-perp','synthetic-metrics',out,dest,ap,fp,pp)
    assert not dest.exists() and not list(tmp_path.glob('.report-*'))


def test_existing_destination_and_same_certificate_preserved(packet,tmp_path):
    out,ap,fp,pp=packet;dest=tmp_path/'existing';dest.mkdir();(dest/'old').write_text('keep')
    with pytest.raises(RuntimeError):p.publish('synthetic-perp','synthetic-metrics',out,dest,ap,fp,pp)
    assert (dest/'old').read_text()=='keep'
    with pytest.raises(RuntimeError):p.publish('synthetic-perp','synthetic-metrics',out,tmp_path/'new',ap,fp,fp)


def test_certificate_schema_with_individual_hashes_and_no_common_map(packet):
    out,ap,fp,pp=packet;fin=r.read(ap);fin.pop('common_artifacts_sha256');r.dump(ap,fin)
    pol=r.read(pp);pol['financial_audit_sha256']=r.digest(ap);r.dump(pp,pol)
    assert verify(packet)[0]['candidate_count_cumulative']==28


def test_closed_native_activity_never_uses_opening_intents(packet):
    out,ap,fp,pp=packet;folder=out/'trials/evaluation'
    times=dict(submitted_at='2026-07-05T00:10:00+00:00',entry_completed_at='2026-07-05T00:11:00+00:00',closed_at='2026-07-05T01:00:00+00:00',observed_closed_at='2026-07-05T01:01:00+00:00')
    completed=[dict(symbol=s,instrument_id=r.native_id('binance',s),generation=i+1,failed=False,average_entry_price=1.,**times) for i,s in enumerate(('DOGEUSDT','PEPEUSDT'))]
    r.dump(folder/'completed_episodes.json',completed)
    summary=r.read(out/'summary.json');_,_,_,activity=p.build_report(out,summary,r.read(ap),r.read(pp))
    row=next(x for x in activity if x['phase']=='evaluation')
    assert row['completed_DOGE'] and row['completed_PEPE'] and row['completed_closed_episodes']==2
    completed[0]['closed_at']=None;r.dump(folder/'completed_episodes.json',completed)
    with pytest.raises(RuntimeError):p.build_report(out,summary,r.read(ap),r.read(pp))


@pytest.mark.parametrize('namespace',['experiment','perp','metrics','source'])
def test_forbidden_destination_namespaces(packet,tmp_path,namespace):
    out,ap,fp,pp=packet;perp=tmp_path/'perp';metrics=tmp_path/'metrics'
    roots={'experiment':out,'perp':perp,'metrics':metrics,'source':r.REPO/'examples'}
    with pytest.raises(RuntimeError):p.publish(perp,metrics,out,roots[namespace]/'newpublication',ap,fp,pp)
