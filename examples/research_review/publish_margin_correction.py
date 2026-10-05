"""Publish only complete, independently audited accounting-correction evidence.

No Engine execution, new hypothesis, parameter search or original report writes.
"""
from pathlib import Path
import argparse
import hashlib
import html
import json
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from aster.analytics import daily_returns, json_safe
from examples.research_review.rerun_margin_correction import COHORTS

CONTROL = ROOT/'results/margin-correction-rerun'
SEALED_FILES = {f'{name}.{suffix}' for name in ['equity','fills','trades','funding','events','positions']
                for suffix in ['csv','parquet']} | {'metadata.json','metrics.json','quality.json','source_manifest.json'}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(json_safe(value), indent=2, allow_nan=False)+'\n')


def sealed_trial(path, fingerprints):
    if set(fingerprints) != SEALED_FILES:
        raise ValueError('Incomplete sixteen-file audit seal')
    for name, expected in fingerprints.items():
        if sha(Path(path)/name) != expected:
            raise ValueError(f'Execution changed after independent audit: {path}/{name}')


def exact_identities(rows, protocol, selection):
    actual = [(r['family'],r['symbol'],float(r['scale']),r['phase'],bool(r['stress'])) for r in rows]
    expected = set()
    for family in protocol['families']:
        chosen = float(selection['chosen'][family])
        for symbol in protocol['symbols']:
            for scale in protocol['scales']:
                expected.add((family,symbol,float(scale),'training',False))
                expected.add((family,symbol,float(scale),'holdout',False))
            for k in [1,2,3]:
                expected.add((family,symbol,chosen,f'validation{k}',False))
            expected.add((family,symbol,chosen,'holdout',True))
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('Missing, duplicated or unexpected economic trial identities')
    return actual


def retained_spot_guard():
    root = ROOT/'results/minute-study-1y'
    published = ROOT/'examples/minute_research/evidence/summary.json'
    summary = read(root/'summary.json')
    if summary != read(published):
        raise ValueError('Retained spot summary differs from original published evidence')
    expected = {'btc_lead_momentum','btc_lead_reversal','donchian','funding_contrarian',
                'mean_reversion','trend','trend_pullback','volatility_breakout'}
    protocol = read(root/'protocol.json')
    rows = summary['families']
    if set(protocol['families'])!=expected or len(rows)!=8 or {r['family'] for r in rows}!=expected:
        raise ValueError('Retained spot candidate identities changed')
    prior_path = ROOT/'docs/minute_directional_results/combined_selection_diagnostic19.json'
    prior = read(prior_path)
    actual = {path.parent.name for path in (root/'pooled').glob('*/equity.parquet')}
    if actual != expected:
        raise ValueError('Retained spot pooled identities changed')
    for name in expected:
        path = root/'pooled'/name/'equity.parquet'
        if name not in prior or (ROOT/prior[name]['source']).resolve()!=path.resolve() or sha(path)!=prior[name]['sha256']:
            raise ValueError('Retained spot equity changed from previously published source hash')
    return {'summary_published_anchor':str(published.relative_to(ROOT)),
            'summary_published_sha256':sha(published),'prior19_diagnostic_sha256':sha(prior_path),
            'exact_spot_candidates':sorted(expected)}


def guard(micro_receipt, external_receipt):
    lock = read(CONTROL/'rerun_lock.json')
    complete = read(CONTROL/'execution_complete.json')
    if complete.get('all_batches_finished') is not True or complete.get('planned_trials') != 1000 or complete.get('rerun_lock_sha256') != sha(CONTROL/'rerun_lock.json'):
        raise ValueError('All 1000 frozen correction executions must finish first')
    if lock['planned_trials'] != 1000 or lock['candidate_count_unchanged'] != 24:
        raise ValueError('Changed correction scope')
    for section in ['package','models']:
        for path, expected in lock[section].items():
            if sha(ROOT/path) != expected:
                raise ValueError(f'Current frozen {section} source changed: {path}')
    for old, anchor in lock['originals'].items():
        for name in ['protocol','summary']:
            if sha(ROOT/old/f'{name}.json') != anchor[f'{name}_sha256']:
                raise ValueError('Original evidence anchor changed')
    retained_spot_guard()
    signed_before = read(ROOT/COHORTS[1][2]/'source_lock.json')
    if signed_before['runner']!=lock['models']['examples/minute_directional/run.py'] or signed_before['signals']!=lock['models']['examples/minute_directional/signals.py']:
        raise ValueError('Signed model changed from original executed source')
    changed_core = {p for p,h in lock['package'].items() if signed_before['package'].get(p)!=h}
    if changed_core!={'aster/backtest/portfolio.py'}:
        raise ValueError('Correction must change only portfolio accounting core')
    external_before = read(ROOT/COHORTS[2][2]/'source_lock.json')['modules']
    changed_modules = {p for p,h in external_before.items() if sha(ROOT/p)!=h}
    if changed_modules!={'aster/backtest/portfolio.py'}:
        raise ValueError('External models, collectors or other core changed from original')
    m, e = read(micro_receipt), read(external_receipt)
    if not m.get('complete') or not m.get('sealed') or m.get('errors') or len(m.get('trials',[])) != 600:
        raise ValueError('Require final sealed independent 600-case replay')
    if not e.get('complete') or e.get('errors') or e.get('expected_trials') != 400 or e.get('reserve_replay_trials') != 400:
        raise ValueError('Require final independent external 400-case replay')
    for key in ['summary_reconstruction_passed','training_selection_reconstruction_passed','pooled_equity_reconstruction_passed']:
        if e.get(key) is not True:
            raise ValueError('External summary/selection/equity reconstruction incomplete')
    if e.get('rerun_lock_sha256') != sha(CONTROL/'rerun_lock.json'):
        raise ValueError('External audit has stale freeze identity')
    paths = set()
    for trial in m['trials']:
        path = (ROOT/trial['path']).resolve()
        if path in paths:
            raise ValueError('Duplicate independent audit trajectory')
        paths.add(path)
        sealed_trial(path, trial['output_sha256'])
    external_root = ROOT/COHORTS[2][3]
    for filename, key in [('source_lock.json','source_lock_sha256'),('summary.json','summary_sha256'),
                          ('selection.json','selection_sha256'),('all_trials.json','all_trials_sha256')]:
        if e.get(key) != sha(external_root/filename):
            raise ValueError(f'External audit stale: {filename}')
    manifest_path = Path(e['output_manifest_path'])
    if sha(manifest_path) != e['output_manifest_sha256']:
        raise ValueError('External independent seal manifest changed')
    manifest = read(manifest_path)
    if manifest.get('version') != 1 or manifest.get('cohort') != 'external' or len(manifest.get('trials',[])) != 400:
        raise ValueError('Incomplete independently pinned external seal manifest')
    manifest_trials = {Path(t['path']).resolve():t for t in manifest['trials']}
    if len(manifest_trials)!=400:
        raise ValueError('Duplicated external independent seals')
    external_rows = read(external_root/'all_trials.json')
    external_ids = exact_identities(external_rows,read(external_root/'protocol.json'),read(external_root/'selection.json'))
    identity_digest = hashlib.sha256(json.dumps(sorted(external_ids),separators=(',',':')).encode()).hexdigest()
    if identity_digest != e['metadata_identity_digest']:
        raise ValueError('External audited identity digest changed')
    for row in external_rows:
        path = Path(row['path']).resolve()
        if not path.is_relative_to(external_root.resolve()) or path in paths:
            raise ValueError('External trajectory outside corrected root or duplicated')
        if path not in manifest_trials:
            raise ValueError('External trajectory missing independent manifest')
        audited = manifest_trials[path]
        row_identity=[row['family'],row['symbol'],row['scale'],row['phase'],row['stress']]
        if audited['identity']!=row_identity:
            raise ValueError('External manifest economic identity differs from trial table')
        if sha(path/'execution_outputs.json') != audited['seal_sha256']:
            raise ValueError('External execution seal changed after audit')
        sealed_trial(path,audited['output_sha256'])
        seal = read(path/'execution_outputs.json')
        if seal.get('version') != 1:
            raise ValueError('Unknown external execution seal')
        sealed_trial(path, seal['sha256'])
        paths.add(path)
    if len(paths) != 1000:
        raise ValueError('Expected exactly 1000 independently sealed trial folders')
    for _, _, old, new, _, count in COHORTS:
        current, previous = ROOT/new, ROOT/old
        if read(current/'protocol.json') != read(previous/'protocol.json'):
            raise ValueError('Economic protocol differs from original')
        folders = {p.parent.resolve() for p in current.rglob('metadata.json')}
        audited = {p for p in paths if p.is_relative_to(current.resolve())}
        if len(folders) != count or folders != audited:
            raise ValueError('Audit does not cover exact corrected cohort folders')
    current_hashes = {}
    for path in paths:
        metadata = read(path/'metadata.json')
        fingerprints = metadata['parameters']['fingerprints']
        if 'package' in fingerprints and fingerprints['package'] != lock['package']:
            raise ValueError('Worker runtime differs from correction freeze')
        data_fingerprints = fingerprints.get('data')
        if data_fingerprints is None:
            data_fingerprints = {k:v for k,v in fingerprints.items() if k not in ['runner','package']}
        for source, expected in data_fingerprints.items():
            if source not in current_hashes:current_hashes[source]=sha(source)
            if current_hashes[source]!=expected:
                raise ValueError('Current market source differs from audited worker identity')
    # Every external model/data anchor is part of the external source lock.
    external_lock = read(external_root/'source_lock.json')
    for section in ['modules','data']:
        for path, expected in external_lock[section].items():
            if sha(ROOT/path if section=='modules' else path) != expected:
                raise ValueError('External frozen module/data changed')
    return lock, paths


def reconstruct_600():
    from examples.minute_carry import run as carry
    from examples.minute_directional import run as signed
    evidence = {}
    with tempfile.TemporaryDirectory(prefix='corrected-summary-replay-') as folder:
        temp = Path(folder)
        cr = ROOT/COHORTS[0][3]
        ct = temp/'carry'; ct.mkdir()
        for phase in ['validation','holdout']:
            (ct/phase).symlink_to(cr/phase,target_is_directory=True)
        rebuilt = json_safe(carry.summarize(ct))
        if rebuilt != read(cr/'summary.json'):
            raise ValueError('Carry summary/gates do not reconstruct from audited ledgers')
        policies = read(cr/'protocol.json')['candidate_policies']
        expected = {cr/phase/policy/scenario/symbol for phase,scenario in [('validation','base'),('holdout','base'),('holdout','stress')]
                    for policy in policies for symbol in carry.SYMBOLS}
        actual = {p.parent for p in cr.rglob('metadata.json')}
        if expected != actual or len(actual)!=120:
            raise ValueError('Carry exact identities incomplete')
        for policy in policies:
            pd.testing.assert_frame_equal(pd.read_parquet(cr/'pooled'/policy/'equity.parquet'),pd.read_parquet(ct/'pooled'/policy/'equity.parquet'))
        evidence['carry'] = {'summary_reconstructed':True,'pooled_equity_reconstructed':True,'exact_trials':120,'selection':'five fixed policies, no optimization'}
        sr = ROOT/COHORTS[1][3]; rows = read(sr/'all_trials.json'); protocol = read(sr/'protocol.json'); selection = read(sr/'selection.json')
        exact_identities(rows,protocol,selection)
        for row in rows:
            path = sr/row['phase']/row['family']/f"{row['scale']:g}"/('stress' if row['stress'] else 'base')/row['symbol']
            if Path(row['path']).resolve()!=path.resolve() or row['metrics']!=read(path/'metrics.json'):
                raise ValueError('Signed trial table differs from sealed execution')
        if json_safe(signed.choose_training(rows)) != selection:
            raise ValueError('Corrected signed training-only selection does not reconstruct')
        st = temp/'signed'; st.mkdir()
        rebuilt = json_safe(signed.summarize(rows,selection,st,protocol))
        if rebuilt != read(sr/'summary.json'):
            raise ValueError('Corrected signed summary/gates do not reconstruct')
        for family in protocol['families']:
            for name in ['equity.parquet','stress_equity.parquet']:
                pd.testing.assert_frame_equal(pd.read_parquet(sr/'pooled'/family/name),pd.read_parquet(st/'pooled'/family/name))
        evidence['signed'] = {'summary_reconstructed':True,'training_selection_reconstructed':True,'pooled_equity_reconstructed':True,'exact_trials':480}
    return evidence


def conditional_interval(frame):
    x = frame.copy()
    x['timestamp'] = pd.to_datetime(x.timestamp,utc=True).dt.as_unit('ns')
    endpoint = x.timestamp.max()
    if endpoint==endpoint.normalize():
        x.loc[x.timestamp==endpoint,'timestamp'] = endpoint-pd.Timedelta(microseconds=1)
    values = daily_returns(x).dropna().to_numpy()
    if len(values)<7:
        return {'daily_observations':len(values),'interval_unavailable':True}
    if not np.isfinite(values).all() or (values<=-1).any():
        raise ValueError('Undefined compounded bootstrap return')
    rng = np.random.default_rng(42)
    starts = rng.integers(0,len(values),(10000,int(np.ceil(len(values)/7))))
    indices = ((starts[:,:,None]+np.arange(7))%len(values)).reshape(10000,-1)[:,:len(values)]
    totals = np.expm1(np.log1p(values[indices]).sum(axis=1))
    return {'daily_observations':len(values),'draws':10000,'block_days':7,'seed':42,'declared_comparisons':24,
            'interval95':np.quantile(totals,[.025,.975]).tolist(),
            'conditional_bonferroni24_interval':np.quantile(totals,[.05/48,1-.05/48]).tolist(),
            'limitations':'Conditional resampling does not remove reused-year adaptation, dependence, survivors, or execution-model uncertainty.'}


def candidate_rows():
    cohorts = [('spot','results/minute-study-1y','results/minute-study-1y')]+[(name,old,new) for name,_,old,new,_,_ in COHORTS]
    rows=[]
    for cohort,old,new in cohorts:
        original,corrected=read(ROOT/old/'summary.json'),read(ROOT/new/'summary.json')
        a=original.get('families',original.get('policies')); b=corrected.get('families',corrected.get('policies'))
        lookup={r.get('family',r.get('policy')):r for r in a}
        if len(a)!=len(b):raise ValueError('Candidate count changed')
        for item in b:
            key=item.get('family',item.get('policy'));previous=lookup[key]
            if item['historical_hurdles_passed']!=all(item['checks'].values()):raise ValueError('Summary gate boolean mismatch')
            row={'candidate':key,'cohort':cohort,'old':previous,'corrected':item,'old_root':old,'corrected_root':new,
                 'original_summary_sha256':sha(ROOT/old/'summary.json'),'corrected_summary_sha256':sha(ROOT/new/'summary.json'),
                 'original_equity':str(Path(old)/'pooled'/key/'equity.parquet'),'corrected_equity':str(Path(new)/'pooled'/key/'equity.parquet')}
            rows.append(row)
    if len(rows)!=24 or len({r['candidate'] for r in rows})!=24:raise ValueError('Expected exactly24 economic candidates')
    return rows


def validation(row):
    return row.get('validation_compounded_return',row.get('validation',{}).get('total_return'))


def liquidations(row):
    return row['holdout'].get('liquidation_event_count',row['holdout'].get('liquidation_count',0))


def pct(value):
    return 'undefined' if value is None else f'{value:.3%}'


def render(rows, diagnostics):
    import plotly.graph_objects as go
    panels=[]; table=[]
    for row in rows:
        old,new=row['old'],row['corrected']; key=row['candidate']; esc=html.escape
        def pair(a,b):return f'<span class="before">{esc(str(a))}</span><br><span class="after">{esc(str(b))}</span>'
        table.append('<tr>'+''.join('<td>'+v+'</td>' for v in [esc(key),pair(pct(validation(old)),pct(validation(new))),
          pair(pct(old['holdout']['total_return']),pct(new['holdout']['total_return'])),pair(pct(old['stress']['total_return']),pct(new['stress']['total_return'])),
          pair(liquidations(old),liquidations(new)),pair('PASS' if old['historical_hurdles_passed'] else 'FAIL','PASS' if new['historical_hurdles_passed'] else 'FAIL'),
          pair(old.get('chosen_scale','fixed'),new.get('chosen_scale','fixed'))])+'</tr>')
        fig=go.Figure()
        for label,path,color,dash in [('original',row['original_equity'],'#8893ac','dash'),('corrected',row['corrected_equity'],'#49dfbd','solid')]:
            frame=pd.read_parquet(ROOT/path);frame.timestamp=pd.to_datetime(frame.timestamp,utc=True)
            sampled=frame.set_index('timestamp').equity.resample('1h').last().dropna()
            fig.add_trace(go.Scatter(x=sampled.index,y=sampled/frame.equity.iloc[0]-1,name=label,line={'color':color,'dash':dash}))
        fig.update_layout(template='plotly_dark',height=270,margin=dict(l=45,r=10,t=25,b=30),yaxis_tickformat='.1%',paper_bgcolor='#121d31',plot_bgcolor='#121d31',legend=dict(orientation='h'))
        chart=fig.to_html(full_html=False,include_plotlyjs=True if not panels else False,config={'responsive':True,'displaylogo':False})
        details={'original_failed_gates':[k for k,v in old['checks'].items() if not v], 'corrected_failed_gates':[k for k,v in new['checks'].items() if not v],
                 'original_later_trial_liquidations':old.get('later_trial_liquidation_events'), 'corrected_later_trial_liquidations':new.get('later_trial_liquidation_events'),
                 'corrected_neighbors':new.get('neighbor_evaluation_returns',new.get('neighbor_holdout_returns')),
                 'corrected_reserve_evaluation':new['holdout'].get('return_after_indicative_exit_reserve'),
                 'corrected_reserve_stress':new['stress'].get('return_after_indicative_exit_reserve'),
                 'corrected_all_asset_metrics':new.get('symbols'), 'conditional_interval':diagnostics[key]}
        panels.append(f'<section><h2>{esc(key)}</h2><p>{esc(row["cohort"])} · hourly display; full-resolution source used for risk and intervals</p>{chart}<details><summary>Every failed gate, neighbor, reserve, liquidation scope and asset metric</summary><pre>{esc(json.dumps(json_safe(details),indent=2))}</pre></details></section>')
    passes=sum(r['corrected']['historical_hurdles_passed'] for r in rows)
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Accounting correction — all 24 comparisons</title><style>
body{{background:#091120;color:#e0e8f7;font:15px system-ui;margin:0}}main{{max-width:1180px;margin:auto;padding:24px}}h1{{font-size:30px}}h2{{font-size:19px}}p{{line-height:1.6;color:#b7c8de}}section{{background:#121d31;padding:18px;border-radius:12px;margin:18px 0}}table{{width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed}}td,th{{padding:10px 5px;text-align:left;border-bottom:1px solid #29364c;overflow-wrap:anywhere}}td:first-child,th:first-child{{width:22%}}.before{{color:#9da8bd}}.after{{color:#49dfbd}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}a{{color:#49dfbd}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}@media(max-width:800px){{.grid{{display:block}}main{{padding:12px}}table{{font-size:10px}}td,th{{padding:6px 3px}}}}
</style></head><body><main><h1>Isolated-margin accounting correction</h1><p>All 1,000 derivative simulations were rerun after correcting proportional reserve release on partial exits. Closed-leg PnL and fees affect wallet cash and do not get reassigned to the remaining isolated allocation. Economic protocols and model sources are unchanged; training-selected scales can change because corrected training accounting changes scores. The original eight spot candidates are retained unchanged. This is still 24 disclosed comparisons, not24 new independent edges.</p><p><b>{passes}/24 meet their unchanged historical hurdles.</b> Green values are corrected, gray values original. Original evidence remains preserved. Later cohorts reuse the previously examined year; conditional intervals cannot prove absence of overfitting or durable future profitability. Five carry policies represent one correlated economic family.</p><section><h2>Original → corrected comparison</h2><table><thead><tr><th>Candidate</th><th>Validation</th><th>Evaluation</th><th>Joint stress</th><th>Evaluation liquidation events</th><th>Hurdles</th><th>Train scale</th></tr></thead><tbody>{''.join(table)}</tbody></table><p>Liquidation table counts are selected evaluation only; detailed risk counts include validation, neighbors and joint stress where required. Carry retains its strict actual terminal-flat gate; directional portfolios retain genuine marked inventory and separate indicative exit reserves. No artificial trades or rewritten old results.</p></section><p><a href="summary.json">Complete old/new summaries</a> · <a href="comparison.csv">Comparison CSV</a> · <a href="conditional_diagnostic24.json">All 24 full-resolution intervals and source hashes</a> · <a href="publication_verification.json">Independent audit and source provenance</a></p><div class="grid">{''.join(panels)}</div></main></body></html>'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',default='docs/margin_correction_results')
    parser.add_argument('--micro-audit',default='results/margin-correction-rerun/independent_ledger_audit.json')
    parser.add_argument('--external-audit',default='audit/corrected_external_evidence.json')
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args();os.chdir(ROOT)
    lock,paths=guard(args.micro_audit,args.external_audit)
    reconstructed=reconstruct_600()
    # Recheck independent seals after the read-only reconstruction, before publication.
    guard(args.micro_audit,args.external_audit)
    if args.verify_only:
        print('All 1,000 independent seals,600 rebuilt summaries/selection and400 independent reconstruction guards pass.');return
    rows=candidate_rows();diagnostics={}
    for row in rows:
        path=ROOT/row['corrected_equity'];frame=pd.read_parquet(path)
        diagnostics[row['candidate']]={**conditional_interval(frame),'source':row['corrected_equity'],'sha256':sha(path),'cohort':row['cohort']}
    comparison=[]
    for row in rows:
        old,new=row['old'],row['corrected']
        record={'candidate':row['candidate'],'cohort':row['cohort']}
        for label,item in [('original',old),('corrected',new)]:
            record.update({f'{label}_validation':validation(item),f'{label}_evaluation':item['holdout']['total_return'],f'{label}_stress':item['stress']['total_return'],
              f'{label}_scale':item.get('chosen_scale'),f'{label}_hurdles_passed':item['historical_hurdles_passed'],
              f'{label}_evaluation_liquidation_events':liquidations(item),f'{label}_failed_gates':';'.join(k for k,v in item['checks'].items() if not v)})
        comparison.append(record)
    evidence={'complete':True,'independently_sealed_trial_count':len(paths),'economic_candidate_count':24,'postprocessor_sha256':sha(__file__),
              'rerun_lock_sha256':sha(CONTROL/'rerun_lock.json'),'rerun_lock':lock,'independent_receipt_sha256':{args.micro_audit:sha(args.micro_audit),args.external_audit:sha(args.external_audit)},
              'retained_spot8_source_anchor_verification':retained_spot_guard(),
              'summary_reconstruction_600':reconstructed,'external_summary_reconstruction_receipt':read(args.external_audit),
              'original_and_corrected_anchors':[{k:v for k,v in row.items() if k not in ['old','corrected']} for row in rows]}
    page=render(rows,diagnostics)
    out=ROOT/args.out;out.parent.mkdir(parents=True,exist_ok=True)
    # Stage a complete report; never leave a partially rendered final directory.
    with tempfile.TemporaryDirectory(prefix='margin-publication-',dir=out.parent) as tmp:
        stage=Path(tmp)
        save(stage/'summary.json',{'candidate_count':24,'corrected_hurdle_pass_count':sum(r['corrected']['historical_hurdles_passed'] for r in rows),'candidates':rows})
        save(stage/'conditional_diagnostic24.json',diagnostics);save(stage/'publication_verification.json',evidence)
        pd.DataFrame(comparison).to_csv(stage/'comparison.csv',index=False);(stage/'report.html').write_text(page)
        guard(args.micro_audit,args.external_audit)
        if out.exists():raise ValueError('Preserve existing correction report; choose a fresh destination')
        stage.rename(out)
    print(f'Published all 24 comparisons to {out}; corrected passes {sum(r["corrected"]["historical_hurdles_passed"] for r in rows)}/24.')


if __name__=='__main__':main()
