"""Publisher evidence fixtures are entirely synthetic; no cached historical reads."""
import copy
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from examples.cross_venue import publish as p
from examples.cross_venue import run as r


@pytest.fixture
def packet(tmp_path,monkeypatch):
    out=tmp_path/'experiment';out.mkdir()
    r.dump(out/'source_lock.json',{'synthetic':True})
    r.dump(out/'feature_receipt.json',{'synthetic':True})
    r.dump(out/'input_verification.json',{'synthetic':True})
    pd.DataFrame({'synthetic':[1]}).to_parquet(out/'features.parquet')
    protocol=out/'executed_source/examples/cross_venue/proposed_protocol.md';protocol.parent.mkdir(parents=True);protocol.write_text('Synthetic prospective packet')
    scores={};hashes={};calls=[]
    for phase in r.PHASES:
        name,begin,stop,stress,valuation=phase;folder=out/'trials'/name;folder.mkdir(parents=True)
        for filename in r.OUTPUTS:(folder/filename).write_bytes(b'synthetic sealed export')
        times=pd.date_range(begin,periods=12,freq='D')
        equity=pd.DataFrame({'timestamp':times,'equity':100000.,'binance_equity':50000.,'bybit_equity':50000.})
        exposure=equity.copy()
        for venue in r.VENUES:
            exposure[f'{venue}_available_margin']=50000.;exposure[f'{venue}_gross_exposure']=0.
        for symbol in r.SYMBOLS:
            for field in ('unmatched_native','unmatched_dollars','matched_native'):
                exposure[f'{field}_{symbol}']=0.
            for venue in r.VENUES:exposure[f'quantity_{venue}_{symbol}']=0.
        equity.to_parquet(folder/'equity.parquet');exposure.to_parquet(folder/'exposure.parquet')
        legs=pd.DataFrame([{'symbol':v+'_'+s,'venue':v,'pair':s,'instrument_id':r.native_id(v,s),
            'net_pnl':0.,'funding_cash':0.,'fill_count':0,'open_quantity':0.} for s in r.SYMBOLS for v in r.VENUES])
        pairs=pd.DataFrame([{'pair':s,'net_pnl':0.,'funding_cash':0.,'fill_count':0} for s in r.SYMBOLS])
        legs.to_csv(folder/'leg_contributions.csv',index=False);pairs.to_csv(folder/'pair_contributions.csv',index=False)
        score={'total_return':0.,'return_after_indicative_exit_reserve':0.,'sharpe':None,'max_drawdown':0.,
               'funding_pnl':0.,'trading_fees':0.,'slippage_cost':0.,'indicative_exit_reserve_total':0.,
               'matched_entry_count':0,'liquidation_event_count':0,'open_position_count':0}
        r.dump(folder/'metrics.json',score);scores[name]=score
        hashes[name]={'outputs_sha256':r.output_files(folder)}
    summary={'family':r.FAMILY,'candidate_count_cumulative':26,'scores':scores,'gates':{key:False for key in p.GATES},
             'passes_hurdles':False,'source_lock_sha256':r.digest(out/'source_lock.json'),'features_sha256':r.digest(out/'features.parquet'),
             'actual_matched_pairs':[],'validation_compounded_return':0.,'validation_after_exit_reserve':0.,
             'anchored_month_returns':[0.,0.,0.],'conditional_interval':{'available':True,'comparison_count':26,'return_interval_bonferroni26':[0.,0.]}}
    r.dump(out/'summary.json',summary)
    common={'complete':True,'errors':[],'source_anchor':p.SOURCE_ANCHOR,'source_unchanged_during_audit':True,'source_lock_sha256':r.digest(out/'source_lock.json'),
            'features_sha256':r.digest(out/'features.parquet'),'feature_receipt_sha256':r.digest(out/'feature_receipt.json')}
    financial={**common,'summary_sha256':r.digest(out/'summary.json'),'trials':hashes,
               'trajectory_reconstruction_passed':True,'summary_reconstruction_passed':True,
               'execution_fill_reconstruction_passed':True,'separate_wallet_reconstruction_passed':True,
               'auditor_sha256':r.digest(p.FINANCIAL_AUDITOR),'auditor_source_unchanged':True,
               'input_anchor':p.INPUT_FREEZE_ANCHOR}
    feature={**common,'reference_reconstruction_passed':True,'auditor_sha256':r.digest(p.FEATURE_AUDITOR),
             'auditor_source_unchanged':True,'input_freeze_anchor':p.INPUT_FREEZE_ANCHOR}
    financial_path=tmp_path/'financial.json';feature_path=tmp_path/'feature.json'
    r.dump(financial_path,financial);r.dump(feature_path,feature)
    cohort={**common,'input_anchor':p.INPUT_FREEZE_ANCHOR,'summary_sha256':r.digest(out/'summary.json'),
        'feature_audit_sha256':r.digest(feature_path),'auditor_sha256':r.digest(p.NO_ADMISSION_AUDITOR),
        'guard_helper_sha256':r.digest(p.FINANCIAL_AUDITOR),'no_economic_admission_reconstruction_passed':True,
        'zero_activity_cohort_verified':True,'unit_cost_upper_bound_reconstruction_passed':True,'economic_admission_count':0,'trials':{}}
    for phase in r.PHASES:
        clocks=len(pd.date_range(phase[1]+pd.Timedelta(minutes=5),phase[2]-pd.Timedelta(hours=168),freq='h',inclusive='left'))
        cohort['trials'][phase[0]]={**hashes[phase[0]],'zero_activity_verified':True,'economic_admission_count':0,
            'hourly_clocks_checked':clocks,'pair_decisions_checked':8*clocks,'unit_cost_upper_bound_reconstruction_passed':True}
    r.dump(out/'no_admission_audit.json',cohort)
    monkeypatch.setattr(r,'guard',lambda *args:None)
    monkeypatch.setattr(r,'verified_features',lambda *args:pd.DataFrame())
    monkeypatch.setattr(r,'verify_completed',lambda b,y,o,phase:calls.append(phase[0]))
    return out,financial,feature,financial_path,feature_path,calls


@pytest.mark.parametrize('kind',['incomplete_financial','financial_errors','incomplete_feature','feature_errors',
    'feature_reference','feature_hash','receipt_hash','summary_hash','lock_hash','trajectory','summary_reconstruction',
    'missing_phase','missing_file','foreign_file'])
def test_missing_stale_or_incomplete_audit_fails(packet,kind):
    out,financial,feature,fp,xp,calls=packet
    a,b=copy.deepcopy(financial),copy.deepcopy(feature)
    if kind=='incomplete_financial':a['complete']=False
    elif kind=='financial_errors':a['errors']=['unreconciled']
    elif kind=='incomplete_feature':b['complete']=False
    elif kind=='feature_errors':b['errors']=['publication leakage']
    elif kind=='feature_reference':b['reference_reconstruction_passed']=False
    elif kind=='feature_hash':b['features_sha256']='wrong'
    elif kind=='receipt_hash':a['feature_receipt_sha256']='wrong'
    elif kind=='summary_hash':a['summary_sha256']='wrong'
    elif kind=='lock_hash':b['source_lock_sha256']='wrong'
    elif kind=='trajectory':a['trajectory_reconstruction_passed']=False
    elif kind=='summary_reconstruction':a['summary_reconstruction_passed']=False
    elif kind=='missing_phase':a['trials'].pop(r.PHASES[0][0])
    elif kind=='missing_file':a['trials'][r.PHASES[0][0]]['outputs_sha256'].pop(r.OUTPUTS[0])
    else:a['trials'][r.PHASES[0][0]]['outputs_sha256']['../arbitrary']='evil'
    with pytest.raises(RuntimeError):p.verify_receipts('binance','bybit',out,a,b,r.read(out/'no_admission_audit.json'))


@pytest.mark.parametrize('what',['equity','metrics','extra_phase','summary_scores'])
def test_all175_outputs_and_summary_crosschecks(packet,what):
    out,financial,feature,fp,xp,calls=packet
    folder=out/'trials'/r.PHASES[0][0]
    if what=='equity':(folder/'equity.parquet').write_bytes(b'tampered ledger')
    elif what=='metrics':(folder/'metrics.json').write_text('{}')
    elif what=='extra_phase':(out/'trials/hidden_variant').mkdir()
    else:
        summary=r.read(out/'summary.json');summary['scores'][r.PHASES[0][0]]['total_return']=.1;r.dump(out/'summary.json',summary)
        financial['summary_sha256']=r.digest(out/'summary.json')
    with pytest.raises(RuntimeError):p.verify_receipts('binance','bybit',out,financial,feature,r.read(out/'no_admission_audit.json'))


def test_complete_packet_promotes_portable_report_and_preserves_prior(packet,tmp_path):
    out,financial,feature,fp,xp,calls=packet;destination=tmp_path/'publication'
    p.publish('binance','bybit',out,destination,fp,xp,out/'no_admission_audit.json')
    assert len(calls)==14
    page=(destination/'report.html').read_text()
    assert 'candidate 26' in page and 'Failed the declared historical hurdles' in page
    assert 'fresh holdout' in page and 'Plotly' in page and 'viewport' in page
    assert 'all 16' in page.lower() and 'Bybit settlement-mark approximation' in page
    assert len(pd.read_csv(destination/'all_leg_contributions.csv'))==112
    assert len(pd.read_csv(destination/'all_pair_contributions.csv'))==56
    assert len(pd.read_csv(destination/'all_unmatched_exposure.csv'))==56
    manifest=r.read(destination/'publication_manifest.json');assert manifest['financial_output_count']==175
    assert r.digest(destination/'summary.json')==financial['summary_sha256']
    assert r.digest(destination/'financial_audit.json')==r.digest(fp)
    before=(destination/'report.html').read_bytes()
    with pytest.raises(RuntimeError):p.publish('binance','bybit',out,destination,fp,xp,out/'no_admission_audit.json')
    assert (destination/'report.html').read_bytes()==before


@pytest.mark.parametrize('target',['ledger','feature_receipt','financial_receipt'])
def test_mutation_during_report_staging_aborts_atomic_publication(packet,tmp_path,monkeypatch,target):
    out,financial,feature,fp,xp,calls=packet;destination=tmp_path/'publication';original=p.build_report
    def mutate(*args):
        result=original(*args)
        if target=='ledger':(out/'trials'/r.PHASES[0][0]/'events.parquet').write_bytes(b'late mutation')
        elif target=='feature_receipt':r.dump(xp,{**feature,'errors':['late audit failure']})
        else:r.dump(fp,{**financial,'complete':False})
        return result
    monkeypatch.setattr(p,'build_report',mutate)
    with pytest.raises(RuntimeError):p.publish('binance','bybit',out,destination,fp,xp,out/'no_admission_audit.json')
    assert not destination.exists() and not list(tmp_path.glob('.publication-staged-*'))


def test_exposure_duration_and_same_direction_native_units():
    times=pd.date_range(r.EVAL_START,periods=3,freq='min');frame=pd.DataFrame({'timestamp':times})
    for s in r.SYMBOLS:
        frame[f'unmatched_native_{s}']=[5.,1.,0.];frame[f'unmatched_dollars_{s}']=[50.,11.,0.]
        frame[f'matched_native_{s}']=[0.,2.,0.]
        frame[f'quantity_binance_{s}']=[3.,3.,0.];frame[f'quantity_bybit_{s}']=[2.,-2.,0.]
    row=p.exposure_diagnostics(frame)[3]
    assert row['unmatched_peak_native']==5 and row['unmatched_peak_dollars']==50
    assert row['unmatched_duration_hours']==pytest.approx(2/60)
    assert row['terminal_unmatched_native']==0 and row['matched_peak_native']==2


def test_two_separate_independent_receipts_required(packet,tmp_path):
    out,financial,feature,fp,xp,calls=packet
    with pytest.raises(RuntimeError):p.publish('binance','bybit',out,tmp_path/'publication',fp,fp,out/'no_admission_audit.json')


@pytest.mark.parametrize('scope',['financial','feature'])
@pytest.mark.parametrize('field',['source_anchor','auditor_sha256','source_unchanged_during_audit'])
@pytest.mark.parametrize('failure',['missing','wrong'])
def test_independent_auditor_source_contract_exact(packet,scope,field,failure):
    out,financial,feature,fp,xp,calls=packet
    a,b=copy.deepcopy(financial),copy.deepcopy(feature)
    changed=a if scope=='financial' else b
    if failure=='missing':changed.pop(field)
    else:changed[field]=False if field=='source_unchanged_during_audit' else 'wrong'
    with pytest.raises(RuntimeError):p.verify_receipts('binance','bybit',out,a,b,r.read(out/'no_admission_audit.json'))


@pytest.mark.parametrize('field',['execution_fill_reconstruction_passed','separate_wallet_reconstruction_passed'])
@pytest.mark.parametrize('failure',['missing','wrong'])
def test_fill_and_independent_wallet_certification_required(packet,field,failure):
    out,financial,feature,fp,xp,calls=packet
    financial=copy.deepcopy(financial)
    if failure=='missing':financial.pop(field)
    else:financial[field]=False
    with pytest.raises(RuntimeError):p.verify_receipts('binance','bybit',out,financial,feature,r.read(out/'no_admission_audit.json'))


@pytest.mark.parametrize('scope',['financial','feature'])
def test_current_auditor_implementation_change_invalidates_certificate(packet,tmp_path,monkeypatch,scope):
    out,financial,feature,fp,xp,calls=packet
    other=tmp_path/'changed_auditor.py';other.write_text('changed implementation')
    monkeypatch.setattr(p,'FINANCIAL_AUDITOR' if scope=='financial' else 'FEATURE_AUDITOR',other)
    with pytest.raises(RuntimeError):p.verify_receipts('binance','bybit',out,financial,feature,r.read(out/'no_admission_audit.json'))


@pytest.mark.parametrize('field',['auditor_source_unchanged','input_freeze_anchor'])
@pytest.mark.parametrize('failure',['missing','wrong'])
def test_final_feature_auditor_and_input_anchor_contract(packet,field,failure):
    out,financial,feature,fp,xp,calls=packet
    feature=copy.deepcopy(feature)
    if failure=='missing':feature.pop(field)
    else:feature[field]=False if field=='auditor_source_unchanged' else 'wrong'
    with pytest.raises(RuntimeError):p.verify_receipts('binance','bybit',out,financial,feature,r.read(out/'no_admission_audit.json'))


@pytest.mark.parametrize('field',['auditor_source_unchanged','input_anchor'])
@pytest.mark.parametrize('failure',['missing','wrong'])
def test_final_financial_auditor_and_input_anchor_contract(packet,field,failure):
    out,financial,feature,fp,xp,calls=packet
    financial=copy.deepcopy(financial)
    if failure=='missing':financial.pop(field)
    else:financial[field]=False if field=='auditor_source_unchanged' else 'wrong'
    with pytest.raises(RuntimeError):p.verify_receipts('binance','bybit',out,financial,feature,r.read(out/'no_admission_audit.json'))


@pytest.mark.parametrize('what',['missing','eligible','scope','hash','clock','output','feature_receipt'])
def test_third_no_admission_audit_required_and_current(packet,what,tmp_path):
    out,financial,feature,fp,xp,calls=packet
    cohort=r.read(out/'no_admission_audit.json')
    if what=='missing':cohort=None
    elif what=='eligible':cohort['economic_admission_count']=1
    elif what=='scope':cohort['zero_activity_cohort_verified']=False
    elif what=='hash':cohort['summary_sha256']='wrong'
    elif what=='clock':cohort['trials'][r.PHASES[0][0]]['hourly_clocks_checked']-=1
    elif what=='output':cohort['trials'][r.PHASES[0][0]]['outputs_sha256']={}
    else:cohort['feature_receipt_sha256']='wrong'
    with pytest.raises(RuntimeError):p.verify_receipts('binance','bybit',out,financial,feature,cohort)
