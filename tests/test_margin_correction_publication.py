"""Independent report guards; no expensive models or market outcomes."""
import json
from pathlib import Path
import pandas as pd
import pytest
from examples.research_review import publish_margin_correction as report


def test_seal_rejects_post_audit_mutation(tmp_path):
    for name in report.SEALED_FILES:(tmp_path/name).write_bytes(b'audited')
    seals={name:report.sha(tmp_path/name) for name in report.SEALED_FILES}
    report.sealed_trial(tmp_path,seals)
    (tmp_path/'positions.parquet').write_bytes(b'changed residual collateral')
    with pytest.raises(ValueError,match='Execution changed'):
        report.sealed_trial(tmp_path,seals)


def test_seal_rejects_missing_terminal_inventory_file(tmp_path):
    with pytest.raises(ValueError,match='sixteen-file'):
        report.sealed_trial(tmp_path,{name:'x' for name in report.SEALED_FILES if name!='positions.parquet'})


def cases():
    p={'families':['family'],'symbols':['symbol'],'scales':[.8,1.,1.2]}
    s={'chosen':{'family':1.}}
    rows=[]
    for scale in p['scales']:
        for phase in ['training','holdout']:rows.append(dict(family='family',symbol='symbol',scale=scale,phase=phase,stress=False))
    for phase in ['validation1','validation2','validation3']:rows.append(dict(family='family',symbol='symbol',scale=1.,phase=phase,stress=False))
    rows.append(dict(family='family',symbol='symbol',scale=1.,phase='holdout',stress=True))
    return rows,p,s


def test_exact_scope_rejects_duplicate_missing_and_wrong_selected_stress():
    rows,p,s=cases();assert len(report.exact_identities(rows,p,s))==10
    for broken in [rows[:-1],rows+[rows[0]],rows[:-1]+[{**rows[-1],'scale':.8}]]:
        with pytest.raises(ValueError,match='identities'):report.exact_identities(broken,p,s)


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_interval_endpoint_resolution_and_input_immutability(unit):
    days=pd.date_range('2026-07-05',periods=93,freq='D',tz='UTC')
    times=pd.DatetimeIndex([days[0],days[0]+pd.Timedelta(minutes=1),*days[1:]]).as_unit(unit)
    frame=pd.DataFrame({'timestamp':times,'equity':[100000*(1.001**k) for k in range(len(times))]})
    saved=frame.copy(deep=True)
    result=report.conditional_interval(frame)
    assert result['declared_comparisons']==24 and result['daily_observations']==92
    assert len(result['conditional_bonferroni24_interval'])==2
    pd.testing.assert_frame_equal(frame,saved)


def test_incomplete_execution_cannot_pass_publication_guard(tmp_path,monkeypatch):
    monkeypatch.setattr(report,'CONTROL',tmp_path)
    (tmp_path/'rerun_lock.json').write_text(json.dumps({'planned_trials':1000,'candidate_count_unchanged':24}))
    (tmp_path/'execution_complete.json').write_text(json.dumps({'all_batches_finished':False,'planned_trials':1000}))
    with pytest.raises(ValueError,match='finish first'):
        report.guard('missing600receipt','missing400receipt')


@pytest.mark.parametrize('mutation',['summary','equity','identity'])
def test_retained_spot_anchor_rejects_changed_evidence(tmp_path,monkeypatch,mutation):
    monkeypatch.setattr(report,'ROOT',tmp_path)
    names=['btc_lead_momentum','btc_lead_reversal','donchian','funding_contrarian','mean_reversion','trend','trend_pullback','volatility_breakout']
    root=tmp_path/'results/minute-study-1y';root.mkdir(parents=True)
    published=tmp_path/'examples/minute_research/evidence/summary.json';published.parent.mkdir(parents=True)
    summary={'families':[{'family':n} for n in names]}
    for p in [root/'summary.json',published]:p.write_text(json.dumps(summary))
    (root/'protocol.json').write_text(json.dumps({'families':names}))
    prior={}
    for name in names:
        path=root/'pooled'/name/'equity.parquet';path.parent.mkdir(parents=True);path.write_bytes(b'original published equity')
        prior[name]={'source':str(path.relative_to(tmp_path)),'sha256':report.sha(path)}
    anchor=tmp_path/'docs/minute_directional_results/combined_selection_diagnostic19.json';anchor.parent.mkdir(parents=True);anchor.write_text(json.dumps(prior))
    report.retained_spot_guard()
    if mutation=='summary':(root/'summary.json').write_text(json.dumps({'families':[]}))
    elif mutation=='equity':(root/'pooled'/names[0]/'equity.parquet').write_bytes(b'rewritten return curve')
    else:(root/'protocol.json').write_text(json.dumps({'families':names[:-1]}))
    with pytest.raises(ValueError,match='Retained spot'):report.retained_spot_guard()
