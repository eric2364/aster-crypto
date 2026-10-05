"""Postpublication guards; fabricated summaries never touch earlier artifacts."""
import json
import pandas as pd
import pytest
from examples.external_factors import update_results as u
from examples.external_factors import run as r


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_combined24_bootstrap_units_tail_and_endpoint(unit):
    frame=pd.DataFrame({'timestamp':pd.date_range(r.EVALUATION_START,periods=91,freq='D'),
                        'equity':[100.]*90+[150.]})
    frame.timestamp=frame.timestamp.astype(f'datetime64[{unit}, UTC]')
    original=frame.copy();result=u.interval(frame)
    assert result['comparison_count']==24
    assert result['return_interval_bonferroni24policies'][1]>0
    pd.testing.assert_frame_equal(frame,original)


def test_incomplete_audit_rejects_before_reading_or_publishing(tmp_path,monkeypatch):
    monkeypatch.setattr(u,'audit',lambda root:{'all400_complete':False})
    with pytest.raises(ValueError,match='400 expected'):u.validate_completed(tmp_path)


@pytest.fixture
def complete(tmp_path,monkeypatch):
    rows=[]
    for family in r.FAMILIES:
        for phase in ['training','validation1','validation2','validation3','holdout']:
            variants=[(.8,False),(1.,False),(1.2,False)] if phase=='training' else [(1.,False)]
            if phase=='holdout':variants=[(.8,False),(1.,False),(1.2,False),(1.,True)]
            for scale,stress in variants:
                for symbol in r.SYMBOLS:
                    path=tmp_path/phase/family/f'{scale:g}'/('stress' if stress else 'base')/symbol
                    path.mkdir(parents=True)
                    metric={'total_return':-.01};(path/'metrics.json').write_text(json.dumps(metric))
                    rows.append({'family':family,'symbol':symbol,'scale':scale,'phase':phase,'stress':stress,'path':str(path),'metrics':metric})
    selection={'chosen':{f:1. for f in r.FAMILIES}}
    summary={'families':[{'family':f,'checks':{'evaluation_positive':False},'historical_hurdles_passed':False} for f in r.FAMILIES],
             'pass_count':0,'protocol':{'families':r.FAMILIES}}
    for name,value in [('all_trials',rows),('summary',summary),('protocol',{'families':r.FAMILIES}),('selection',selection),('source_lock',{})]:
        (tmp_path/f'{name}.json').write_text(json.dumps(value))
    evidence={'all400_complete':True,'trials':json.loads(json.dumps(rows))}
    monkeypatch.setattr(u,'audit',lambda root:evidence)
    monkeypatch.setattr(u.frozen_runner,'choose_training',lambda rows:selection)
    monkeypatch.setattr(u.frozen_runner,'summarize',lambda *args:summary)
    monkeypatch.setattr(u.pd,'read_parquet',lambda *args:pd.DataFrame({'equity':[100.,99.]}))
    return tmp_path,rows,selection,summary


def test_valid_full_reconciliation_is_read_only(complete):
    root,rows,selection,summary=complete
    prior={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    actual,table,evidence=u.validate_completed(root)
    assert actual==summary and len(table)==400
    assert all(p.read_bytes()==data for p,data in prior.items())


@pytest.mark.parametrize('defect',['arbitrary_tuple','duplicate','metric_tamper','path_tamper','selection_tamper','summary_pass_tamper'])
def test_full_count_does_not_override_provenance_and_recomputed_outcomes(complete,defect):
    root,rows,selection,summary=complete
    if defect=='arbitrary_tuple':rows[0]['family']='invented_family'
    elif defect=='duplicate':rows[0]=rows[1].copy()
    elif defect=='metric_tamper':rows[0]['metrics']={'total_return':999.}
    elif defect=='path_tamper':rows[0]['path']=rows[1]['path']
    elif defect=='selection_tamper':
        changed={'chosen':{**selection['chosen'],next(iter(r.FAMILIES)):.8}}
        (root/'selection.json').write_text(json.dumps(changed))
    else:
        changed={**summary,'pass_count':5};(root/'summary.json').write_text(json.dumps(changed))
    if defect in ['arbitrary_tuple','duplicate','metric_tamper','path_tamper']:(root/'all_trials.json').write_text(json.dumps(rows))
    with pytest.raises((ValueError,KeyError)):u.validate_completed(root)


@pytest.fixture
def pooled24(tmp_path,monkeypatch):
    import hashlib
    monkeypatch.chdir(tmp_path)
    paths=['results/minute-study-1y','results/minute-carry-1y-v2','results/minute-directional-1y-v2','results/external-factor-1y']
    counts=[8,5,6,5];prior={}
    for cohort,(directory,n) in enumerate(zip(paths,counts)):
        root=tmp_path/directory;root.mkdir(parents=True)
        names=[f'candidate_{cohort}_{i}' for i in range(n)]
        (root/'protocol.json').write_text(json.dumps({'candidate_policies' if cohort==1 else 'families':dict.fromkeys(names,'synthetic')}))
        for name in names:
            equity=root/'pooled'/name/'equity.parquet';equity.parent.mkdir(parents=True)
            pd.DataFrame({'timestamp':pd.date_range(r.EVALUATION_START,periods=91,freq='D'),
                          'equity':[100.]*90+[110.]}).to_parquet(equity,index=False)
            if cohort<3:prior[name]={'source':str(equity.relative_to(tmp_path)),'sha256':hashlib.sha256(equity.read_bytes()).hexdigest()}
    anchor=tmp_path/'docs/minute_directional_results/combined_selection_diagnostic19.json'
    anchor.parent.mkdir(parents=True);anchor.write_text(json.dumps(prior))
    return paths[-1],prior


def test_combined24_requires_exact_identities_and_preserves_prior19_hashes(pooled24):
    root,prior=pooled24
    output=u.combined_diagnostics(root)
    assert len(output)==24
    assert all(output[key]['source_sha256']==record['sha256'] for key,record in prior.items())
    assert all(value['comparison_count']==24 for value in output.values())


@pytest.mark.parametrize('defect',['old_source_tamper','same_count_wrong_identity'])
def test_combined24_fails_before_republishing_changed_prior_outputs(pooled24,defect):
    root,prior=pooled24
    source=next(iter(prior.values()))['source']
    from pathlib import Path
    if defect=='old_source_tamper':Path(source).write_bytes(Path(source).read_bytes()+b'tampered')
    else:Path(source).parent.rename(Path(source).parent.with_name('invented_same_count_policy'))
    with pytest.raises(ValueError):u.combined_diagnostics(root)


def test_publication_preserves_prior_artifacts_and_replaces_only_its_extension(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    from pathlib import Path
    root=Path('results/external-factor-1y');root.mkdir(parents=True)
    for name in ['summary.json','all_trials.json','source_lock.json']:(root/name).write_text('{}')
    docs=Path('docs');docs.mkdir()
    previous=b'# Original nineteen outcomes\n\nZero passes, with all failures preserved.\n'
    (docs/'minute_strategy_results.md').write_bytes(previous)
    sentinel=docs/'minute_directional_results/combined_selection_diagnostic19.json';sentinel.parent.mkdir()
    sentinel.write_bytes(b'prior-19-anchor-bytes')
    rows=[{'family':f,'symbol':a,'scale':v,'phase':p,'stress':q} for f in r.FAMILIES
          for a in r.SYMBOLS for v,p,q in [(v,'training',False) for v in r.SCALES]+[(1.,'validation1',False),(1.,'validation2',False),(1.,'validation3',False)]+[(v,'holdout',False) for v in r.SCALES]+[(1.,'holdout',True)]]
    families=[{'family':f,'holdout':{'sharpe':None,'total_return':-.01,'max_drawdown':.1},
               'validation_compounded_return':-.02,'stress':{'total_return':-.03},'positive_symbols':0,
               'historical_hurdles_passed':False,'checks':{'evaluation_positive':False}} for f in r.FAMILIES]
    monkeypatch.setattr(u,'validate_completed',lambda root:({'families':families},rows,{'all400_complete':True}))
    monkeypatch.setattr(u,'combined_diagnostics',lambda root:{f'policy{i}':{'comparison_count':24} for i in range(24)})
    u.main();first=(docs/'minute_strategy_results.md').read_bytes()
    u.main();second=(docs/'minute_strategy_results.md').read_bytes()
    assert first==second and first.startswith(previous)
    assert sentinel.read_bytes()==b'prior-19-anchor-bytes'
    assert first.count(b'## External-factor extension:')==1
