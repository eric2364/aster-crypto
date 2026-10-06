"""Candidate28 audit-gated presentation; no features, orders or historical audits generated."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from examples.positioning_research import run as r
from examples.funding_rank.publish import table, pct, num, esc, display_indices
from audit import verify_positioning_outputs as financial_reference
import plotly.graph_objects as go
from plotly.subplots import make_subplots

SOURCE_ANCHOR=financial_reference.SOURCE_ANCHOR
INPUT_ANCHOR='7aa7830878821ed4819f2b2feac51cbd9fe1e82c'
FINANCIAL_AUDITOR=r.REPO/'audit/verify_positioning_outputs.py'
POLICY_AUDITOR=r.REPO/'audit/verify_positioning_policy.py'
REPORT_HELPER=r.REPO/'examples/funding_rank/publish.py'
GATES=financial_reference.GATES if hasattr(financial_reference,'GATES') else {
'positive_compounded_validation','positive_validation_after_exit_reserve','positive_evaluation','positive_evaluation_after_exit_reserve','positive_stress','positive_stress_after_exit_reserve','two_positive_anchored_months','daily_sharpe_at_least_half','minute_drawdown_at_most_twenty_percent','no_liquidation_all_five_runs','four_completed_assets','completed_doge_participation','completed_pepe_participation','two_completed_entry_generations','actual_terminal_flat_all_five_runs'}
STABILITY=('source_unchanged_during_audit','input_unchanged_during_audit','features_unchanged_during_audit','auditor_source_unchanged','all_phase_evidence_unchanged')
COMMON=('source_lock.json','input_verification.json','feature_receipt.json','published_lock.json','summary.json')


def check(ok,message):
    if not ok:raise RuntimeError(message)


def snapshot(out,feature_path,financial_path,policy_path):
    """Capture identities before the first provenance guard, including transitive helpers."""
    paths={Path(__file__),REPORT_HELPER,POLICY_AUDITOR,FINANCIAL_AUDITOR,
           Path(financial_path),Path(policy_path),Path(feature_path),
           r.REPO/'audit/verify_funding_rank_outputs.py',r.REPO/'audit/verify_positioning_features.py',
           r.REPO/'audit/verify_positioning_dataset.py'}
    paths|={Path(out)/n for n in COMMON}
    first={str(p.resolve()):r.digest(p) for p in paths}
    sealed=financial_reference.evidence_hashes(out,r.read(Path(out)/'source_lock.json'),feature_path)
    check({str(p.resolve()):r.digest(p) for p in paths}==first,'Publisher/helper/certificate changed during evidence enumeration')
    sealed.update(first)
    return sealed


def verify_stage(stage,manifest):
    """Compare to pre-write seals; never reseal changed presentation bytes."""
    expected=set(manifest['outputs_sha256'])|{'publication_manifest.json'}
    check({p.name for p in stage.iterdir()}==expected,'Staged publication namespace differs')
    check(all((stage/name).is_file() and not (stage/name).is_symlink() for name in expected),'Staged publication regular files required')
    check({name:r.digest(stage/name) for name in manifest['outputs_sha256']}==manifest['outputs_sha256'],'Staged publication bytes differ from manifest')
    check(r.read(stage/'publication_manifest.json')==manifest,'Staged publication manifest claims differ')


def verify_receipts(perp_cache,metrics_cache,out,financial_path,feature_path,policy_path):
    out=Path(out)
    financial_reference.packet_guard(perp_cache,metrics_cache,out,SOURCE_ANCHOR,INPUT_ANCHOR)
    feature=financial_reference.verify_feature_certificate(out,feature_path,SOURCE_ANCHOR,INPUT_ANCHOR)
    financial,policy=r.read(financial_path),r.read(policy_path)
    common={n:r.digest(out/n) for n in COMMON}
    for cert,label,auditor in ((financial,'financial',FINANCIAL_AUDITOR),(policy,'recorded-policy',POLICY_AUDITOR)):
        check(cert.get('complete') is True and cert.get('errors')==[],label+' certificate incomplete')
        check(cert.get('source_anchor')==SOURCE_ANCHOR and cert.get('input_anchor')==INPUT_ANCHOR,label+' anchors differ')
        check(cert.get('auditor_sha256')==r.digest(auditor),label+' auditor changed')
        check(all(cert.get(k) is True for k in STABILITY),label+' stability absent')
        check(all(cert.get(n.removesuffix('.json')+'_sha256')==digest for n,digest in common.items()),label+' common receipts differ')
        if 'common_artifacts_sha256' in cert:check(cert['common_artifacts_sha256']==common,label+' common map differs')
        check(cert.get('features_sha256')==feature['features_sha256'] and cert.get('feature_audit_sha256')==r.digest(feature_path),label+' feature binding differs')
        check(cert.get('summary_sha256')==common['summary.json'],label+' summary differs')
        check(isinstance(cert.get('scope'),str) and cert['scope'] and isinstance(cert.get('limitations'),list) and cert['limitations'],label+' scope/limits absent')
    check(financial.get('financial_reconstruction_complete') is True and financial.get('complete_financial_scope') is True and financial.get('gates_reconstructed') is True,'Complete independent financial reconstruction required')
    check(financial.get('policy_reconstruction_complete') is False and financial.get('recorded_policy_reconstruction_complete') is False and financial.get('publication_ready') is False,'Financial-only certificate scope was forged')
    check(financial.get('reference_source_unchanged') is True and financial.get('reference_helper_sha256')==r.digest(r.REPO/'audit/verify_funding_rank_outputs.py'),'Financial arithmetic helper differs')
    check(financial.get('feature_auditor_sha256')==r.digest(r.REPO/'audit/verify_positioning_features.py'),'Financial feature helper differs')
    check(policy.get('recorded_policy_reconstruction_complete') is True and policy.get('financial_audit_sha256')==r.digest(financial_path),'Separate recorded-policy/financial binding required')
    check(policy.get('policy_reconstruction_complete') is False and policy.get('publication_ready') is False and policy.get('full_cleanup_state_reconstruction_passed') is False and policy.get('all_unlogged_abort_transitions_proved') is False,'Separate policy certificate scope was forged')
    check(policy.get('financial_source_unchanged') is True,'Policy financial source stability absent')
    check(policy.get('financial_auditor_sha256')==r.digest(FINANCIAL_AUDITOR) and policy.get('reference_helper_sha256')==r.digest(r.REPO/'audit/verify_funding_rank_outputs.py'),'Policy financial helper differs')
    expected={p[0] for p in r.PHASES}
    check({p.name for p in (out/'trials').iterdir()}==expected,'Exact five phase namespaces required')
    check(set(financial.get('phases',{}))==expected and set(policy.get('phases',{}))==expected,'Exact five independent phases required')
    for phase in r.PHASES:
        folder=out/'trials'/phase[0]
        for cert,label in ((financial,'financial'),(policy,'policy')):
            proof=cert['phases'][phase[0]]
            check(proof.get('outputs_sha256')==r.output_files(folder) and set(proof['outputs_sha256'])==set(r.OUTPUTS),label+' exact26 exports differ')
            check(proof.get('completion_sha256')==r.digest(folder/'completion.json'),label+' completion differs')
        check(financial['phases'][phase[0]].get('trajectory_reconstruction_passed') is True,'Financial trajectory absent')
        proof=policy['phases'][phase[0]]
        check(proof.get('recorded_policy_reconstruction_passed') is True and proof.get('all_callback_clocks_examined') is True,'All-clock recorded policy absent')
        check(proof.get('full_cleanup_state_reconstruction_passed') is False and proof.get('all_unlogged_abort_transitions_proved') is False,'Policy omission limits erased')
        r.verify_completed(perp_cache,out,phase,feature_audit=feature_path)
    summary=r.read(out/'summary.json')
    check(summary.get('family')==r.FAMILY and summary.get('candidate_count_cumulative')==28 and summary.get('research_status')=='exploratory reused year; no untouched holdout','Candidate identity differs')
    check(summary.get('source_lock_sha256')==common['source_lock.json'] and summary.get('feature_receipt_sha256')==common['feature_receipt.json'] and summary.get('feature_audit_sha256')==r.digest(feature_path) and summary.get('features_sha256')==feature['features_sha256'],'Summary packet differs')
    check(set(summary.get('scores',{}))==expected,'All five scores required')
    check(set(summary.get('gates',{}))==set(GATES) and all(type(v) is bool for v in summary['gates'].values()),'Exact fifteen Boolean gates required')
    check(type(summary.get('passes_hurdles')) is bool and summary['passes_hurdles']==all(summary['gates'].values()) and summary.get('failed_gates')==[k for k,v in summary['gates'].items() if not v],'Hurdle claim inconsistent')
    for name in expected:check(summary['scores'][name]==r.read(out/'trials'/name/'metrics.json'),'Phase score differs')
    return summary,financial,policy


def build_report(out,summary,financial,policy):
    scores=[];legs=[];activity=[];charts=[]
    for index,(name,_,_,_) in enumerate(r.PHASES):
        folder=Path(out)/'trials'/name;score={'phase':name,**summary['scores'][name]};scores.append(score)
        native=pd.read_csv(folder/'leg_contributions.csv')
        check(len(native)==8 and set(native.symbol)==set(r.SYMBOLS) and set(native.instrument_id)=={r.native_id('binance',s) for s in r.SYMBOLS},'All eight native legs required')
        legs.extend({'phase':name,**row} for row in native.to_dict('records'))
        completed=r.read(folder/'completed_episodes.json')
        participants,_=r.episode_participation(completed)
        activity.append(dict(phase=name,completed_closed_episodes=len(completed),completed_assets=', '.join(sorted(participants)),completed_DOGE='DOGEUSDT' in participants,completed_PEPE='PEPEUSDT' in participants,actual_funding_payments=len(pd.read_parquet(folder/'funding.parquet')),terminal_flat_resolved=score['terminal_flat_resolved']))
        equity=pd.read_parquet(folder/'equity.parquet');idx=display_indices(equity);shown=equity.iloc[idx]
        chart=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[.7,.3])
        chart.add_trace(go.Scatter(x=shown.timestamp,y=shown.equity,name='Actual marked wallet equity'),row=1,col=1)
        chart.add_trace(go.Scatter(x=shown.timestamp,y=(equity.equity/equity.equity.cummax()-1).iloc[idx]*100,name='Drawdown %',fill='tozeroy'),row=2,col=1)
        chart.update_layout(template='plotly_dark',height=400,margin=dict(l=50,r=20,t=30,b=40),hovermode='x unified')
        charts.append('<details'+(' open' if name=='evaluation' else '')+'><summary>'+esc(name)+'</summary>'+chart.to_html(full_html=False,include_plotlyjs='inline' if index==0 else False,config={'responsive':True,'displaylogo':False})+'</details>')
    status='Passed all declared historical gates' if summary['passes_hurdles'] else 'Failed declared historical gates — no qualified strategy'
    columns=[('phase','Account',str),('total_return','Net return',pct),('return_after_indicative_exit_reserve','After reserve',pct),('sharpe','Daily Sharpe',num),('max_drawdown','Minute drawdown',pct),('trading_fees','Actual fees',num),('funding_pnl','Settled funding',num),('slippage_cost','Embedded slippage diagnostic',num),('indicative_exit_reserve_total','Indicative exit reserve',num),('terminal_flat_resolved','Terminal resolved',str)]
    page='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Positioning rebound · candidate 28</title><style>body{background:#09111e;color:#dbeafe;font:15px/1.6 system-ui;margin:0}main{max-width:1240px;margin:auto;padding:30px}section{background:#111c2d;padding:22px;border-radius:12px;margin:20px 0}h1{font-size:36px}table{border-collapse:collapse;white-space:nowrap;width:100%;font-size:13px}td,th{padding:9px;border-bottom:1px solid #334155;text-align:right}.scroll{overflow-x:auto}a{color:#7dd3fc}pre{white-space:pre-wrap}summary{cursor:pointer;padding:12px}.fail{color:#fda4af}.pass{color:#6ee7b7}</style><main><h1>Confirmed native positioning unwind / rebound</h1><p>Exploratory candidate 28 · one actual 100,000 USDT wallet · fixed long/cash rules · 5 October 2025–5 October 2026 UTC.</p>'
    page+='<section><h2>'+status+'</h2><p>Qualified historical families across the cumulative search: '+str(int(summary['passes_hurdles']))+' / 28. The previous 27 failed. This does not fulfill a request for 4–5 robust examples. Repeatedly examined historical data are not an untouched holdout or proof of a future edge.</p></section>'
    page+='<section><h2>All five independent accounts and all fifteen gates</h2>'+table(scores,columns)+'<p>Validation compounded return '+pct(summary['validation_compounded_return'])+'; after reserve '+pct(summary['validation_after_exit_reserve'])+'. Anchored months: '+', '.join(pct(x) for x in summary['anchored_month_returns'])+'.</p><ul>'+''.join('<li class="'+('pass' if v else 'fail')+'">'+('PASS ' if v else 'FAIL ')+esc(k)+'</li>' for k,v in summary['gates'].items())+'</ul></section>'
    page+='<section><h2>Actual closed participation</h2><p>DOGE and native 1000PEPE participation requires entered and actually closed completed episodes. Opening intentions and partial fills do not count.</p>'+table(activity,[(k,k.replace('_',' '),str) for k in activity[0]])+'</section>'
    page+='<section><h2>Every native leg, including losses</h2>'+table(legs,[('phase','Account',str),('symbol','Asset',str),('instrument_id','Native ID',str),('net_pnl','Net P&L',num),('funding_cash','Funding cash',num),('fill_count','Fills',str),('open_quantity','Terminal quantity',str)])+'</section>'
    page+='<section><h2>Full wallet equity and drawdown</h2><p>Plots sample daily endpoints and global extrema; metrics and audits use every minute/settlement clock.</p>'+''.join(charts)+'</section>'
    page+='<section><h2>Economic, timing and execution limits</h2><p>Native open-interest quantity contraction, a nonnegative five-minute OI pause and a completed-price rebound define a hypothesis; these are not verified forced-liquidation events. Original historical OI units, publication/delivery timing and dataset vintage are unverified. Label plus six minutes is assumed baseline availability; plus eleven is the delay stress. Current metadata/rule assumptions approximate historical execution.</p><p>Baseline costs are 5 bps taker fees and 8 bps adverse slippage per side; stress uses 10/16 bps, delayed activation and half volume participation. Slippage is already embedded in executed prices and is not deducted twice. Settled funding is separate actual wallet cash. Exit reserves are sensitivities, not fictitious cash debits.</p><p>Seven-day circular blocks, 10,000 draws, seed 42 and cumulative 28-comparison tails are descriptive conditional uncertainty; they cannot undo adaptive selection.</p><pre>'+esc(json.dumps(summary['conditional_interval'],indent=2))+'</pre></section>'
    page+='<section><h2>Separate audited scopes</h2><p>130 exports and five completion seals are required. Financial-only publication_ready remains false in its unchanged certificate; this presentation composes separate financial and recorded-policy evidence. It does not certify exhaustive cleanup/BLOCKED transitions or omissions outside resolved audited idle windows.</p>'
    for label,cert in [('Financial',financial),('Recorded policy',policy)]:page+='<p>'+label+': '+esc(cert['scope'])+'</p><ul>'+''.join('<li>'+esc(x)+'</li>' for x in cert['limitations'])+'</ul>'
    page+='<p>'+ ' · '.join('<a href="'+n+'">'+esc(n)+'</a>' for n in ('summary.json','comparison.csv','all_leg_contributions.csv','activity.csv','feature_audit.json','financial_audit.json','recorded_policy_audit.json','publication_manifest.json'))+'</p></section></main><script>document.querySelectorAll("details").forEach(n=>n.addEventListener("toggle",()=>{if(n.open)requestAnimationFrame(()=>n.querySelectorAll(".plotly-graph-div").forEach(c=>Plotly.Plots.resize(c)));}));</script></html>'
    return page,scores,legs,activity


def publish(perp_cache,metrics_cache,out,destination,financial_path,feature_path,policy_path):
    out,destination=Path(out),Path(destination)
    receipts=[Path(x) for x in (financial_path,feature_path,policy_path)]
    check(len({p.resolve() for p in receipts})==3,'Separate certificates required')
    check(not destination.exists(),'Existing publication is preserved')
    forbidden=[out,Path(perp_cache),Path(metrics_cache),*(r.REPO/n for n in ('aster','examples','audit'))]
    check(not any(destination.resolve().is_relative_to(p.resolve()) for p in forbidden),'Publication cannot mutate source/input/experiment namespace')
    before=snapshot(out,feature_path,financial_path,policy_path)
    summary,financial,policy=verify_receipts(perp_cache,metrics_cache,out,*receipts[:2],receipts[2])
    check(snapshot(out,feature_path,financial_path,policy_path)==before,'Evidence changed during initial provenance verification')
    page,scores,legs,activity=build_report(out,summary,financial,policy)
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.'+destination.name+'-',dir=destination.parent))
    try:
        (stage/'report.html').write_text(page)
        for name,rows in [('comparison.csv',scores),('all_leg_contributions.csv',legs),('activity.csv',activity)]:pd.DataFrame(rows).to_csv(stage/name,index=False)
        copies={n:out/n for n in COMMON}
        copies.update(feature_audit=Path(feature_path),financial_audit=Path(financial_path),recorded_policy_audit=Path(policy_path))
        copies={n if n.endswith('.json') else n+'.json':p for n,p in copies.items()}
        copies['executed_publisher.py']=Path(__file__)
        copies['executed_report_helper.py']=REPORT_HELPER
        for name,path in copies.items():(stage/name).write_bytes(path.read_bytes())
        check(snapshot(out,feature_path,financial_path,policy_path)==before,'Evidence changed during rendering/copy')
        check(verify_receipts(perp_cache,metrics_cache,out,*receipts[:2],receipts[2])[0]==summary,'Reverified summary differs')
        check(snapshot(out,feature_path,financial_path,policy_path)==before,'Evidence changed during final verification')
        check(all(r.digest(stage/name)==before[str(path.resolve())] for name,path in copies.items()),'Staged evidence differs')
        manifest=dict(composed_publication_ready=True,financial_certificate_publication_ready=False,recorded_policy_scope_only=True,source_anchor=SOURCE_ANCHOR,input_anchor=INPUT_ANCHOR,candidate_count_cumulative=28,qualified_historical_count=int(summary['passes_hurdles']),audited_output_count=130,audited_completion_count=5,financial_audit_sha256=before[str(Path(financial_path).resolve())],feature_audit_sha256=before[str(Path(feature_path).resolve())],policy_audit_sha256=before[str(Path(policy_path).resolve())],publisher_sha256=before[str(Path(__file__).resolve())],report_helper_sha256=before[str(REPORT_HELPER.resolve())],audited_outputs_sha256={n:p['outputs_sha256'] for n,p in financial['phases'].items()},outputs_sha256={p.name:r.digest(p) for p in sorted(stage.iterdir())})
        r.dump(stage/'publication_manifest.json',manifest)
        verify_stage(stage,manifest)
        check(snapshot(out,feature_path,financial_path,policy_path)==before,'Evidence changed before promotion')
        check(not destination.exists(),'Destination appeared during staging')
        verify_stage(stage,manifest)
        os.rename(stage,destination)
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True);raise
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--perp-cache',required=True);parser.add_argument('--metrics-cache',required=True);parser.add_argument('--out',required=True);parser.add_argument('--destination',required=True)
    for name in ('financial-audit','feature-audit','policy-audit'):parser.add_argument('--'+name,required=True)
    a=parser.parse_args();print(publish(a.perp_cache,a.metrics_cache,a.out,a.destination,a.financial_audit,a.feature_audit,a.policy_audit))

if __name__=='__main__':main()
