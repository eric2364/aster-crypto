"""Audit-gated candidate27 presentation; never builds features or executes orders."""
from __future__ import annotations
import argparse
import hashlib
import html
import os
from pathlib import Path
import shutil
import sys
import tempfile
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from examples.funding_rank import run as r

SOURCE_ANCHOR='ffa52d6b44bfed3f589389dd374719129b671771'
INPUT_ANCHOR='22b21f12054dbde0895c94d1299a81025156ba92'
FINANCIAL_AUDITOR=r.REPO/'audit/verify_funding_rank_outputs.py'
POLICY_AUDITOR=r.REPO/'audit/verify_funding_rank_policy.py'
FEATURE_AUDITOR=r.REPO/'audit/verify_funding_rank_features.py'
REFERENCE_HELPER=r.REPO/'audit/verify_cross_venue_features.py'
GATES={'positive_compounded_validation','positive_validation_after_exit_reserve',
 'positive_evaluation','positive_evaluation_after_exit_reserve','positive_stress','positive_stress_after_exit_reserve',
 'two_positive_anchored_months','daily_sharpe_at_least_half','minute_drawdown_at_most_twenty_percent',
 'no_liquidation_all_five_runs','four_completed_assets','completed_doge_participation','completed_pepe_participation',
 'two_completed_entry_generations','actual_terminal_flat_all_five_runs'}


def check(ok,message):
    if not ok:raise RuntimeError(message)


def verify_receipts(cache,out,financial,feature,feature_sha):
    out=Path(out);r.guard(cache,out)
    common={name:r.digest(out/path) for name,path in [('source_lock_sha256','source_lock.json'),
        ('features_sha256','features.parquet'),('feature_receipt_sha256','feature_receipt.json')]}
    receipt=r.read(out/'feature_receipt.json')
    check(all(receipt.get(k)==common[k] for k in ('source_lock_sha256','features_sha256')),'Immutable feature receipt differs')
    for cert,label,auditor in [(financial,'financial',FINANCIAL_AUDITOR),(feature,'feature',FEATURE_AUDITOR)]:
        check(cert.get('complete') is True and cert.get('errors')==[],'Incomplete independent '+label+' audit')
        check(all(cert.get(k)==v for k,v in common.items()),'Stale independent '+label+' packet')
        check(cert.get('source_anchor')==SOURCE_ANCHOR and cert.get('auditor_sha256')==r.digest(auditor),'Independent '+label+' source differs')
        check(cert.get('source_unchanged_during_audit') is True,'Independent '+label+' source stability absent')
    check(financial.get('input_anchor')==INPUT_ANCHOR and feature.get('input_freeze_anchor')==INPUT_ANCHOR,'Input anchors differ')
    check(feature.get('auditor_source_unchanged') is True and feature.get('reference_reconstruction_passed') is True,'Independent feature reconstruction absent')
    check(feature.get('reference_helper_sha256')==r.digest(REFERENCE_HELPER),'Feature reference helper changed')
    check(financial.get('policy_auditor_sha256')==r.digest(POLICY_AUDITOR) and financial.get('feature_audit_sha256')==feature_sha,'Recorded-policy/feature certificate binding differs')
    check(financial.get('auditor_source_unchanged') is True and financial.get('policy_source_unchanged') is True,'Financial/policy source stability absent')
    check(financial.get('gates_reconstructed') is True,'Independent fifteen-gate reconstruction absent')
    check(financial.get('summary_sha256')==r.digest(out/'summary.json'),'Audited summary changed')
    expected={phase[0] for phase in r.PHASES}
    check({p.name for p in (out/'trials').iterdir()}==expected and set(financial.get('phases',{}))==expected,'Exact five phase audits required')
    for phase in r.PHASES:
        proof=financial['phases'][phase[0]]
        check(proof.get('trajectory_reconstruction_passed') is True,'Financial trajectory reconstruction absent')
        check(isinstance(proof.get('recorded_policy_intents'),dict) and proof['recorded_policy_intents'].get('recorded_policy_reconstruction_passed') is True,'Recorded policy reconstruction absent')
        check(proof.get('completion_sha256')==r.digest(out/'trials'/phase[0]/'completion.json'),'Independent completion seal differs')
        hashes=proof.get('outputs_sha256',{})
        check(set(hashes)==set(r.OUTPUTS) and hashes==r.output_files(out/'trials'/phase[0]),'Audited125 output bytes differ')
        r.verify_completed(cache,out,phase)
    summary=r.read(out/'summary.json')
    check(summary.get('family')==r.FAMILY and summary.get('candidate_count_cumulative')==27
          and summary.get('research_status')=='exploratory reused year; no untouched holdout','Candidate identity differs')
    check(all(summary.get(k)==v for k,v in common.items()),'Summary packet differs')
    check(set(summary.get('scores',{}))==expected,'Five scores required')
    check(isinstance(summary.get('gates'),dict) and set(summary['gates'])==GATES and all(type(v) is bool for v in summary['gates'].values()),'Exact15 Boolean gates required')
    check(type(summary.get('passes_hurdles')) is bool and summary['passes_hurdles']==all(summary['gates'].values())
          and summary.get('failed_gates')==[k for k,v in summary['gates'].items() if not v],'Inconsistent hurdle claims')
    for phase in r.PHASES:check(summary['scores'][phase[0]]==r.read(out/'trials'/phase[0]/'metrics.json'),'Hidden/mislabelled phase score')
    return summary


def esc(value):return html.escape(str(value))
def pct(value):return 'undefined' if value is None else f'{value:.3%}'
def num(value):return 'undefined' if value is None else f'{value:,.2f}'
def table(rows,columns):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(label)+'</th>' for _,label,_ in columns)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(fmt(row.get(k)))+'</td>' for k,_,fmt in columns)+'</tr>' for row in rows)+'</tbody></table></div>'


def display_indices(equity):
    times=pd.DatetimeIndex(equity.timestamp);daily=np.flatnonzero(~times.normalize().duplicated(keep='last'))
    values=equity.equity.to_numpy(float);dd=values/np.maximum.accumulate(values)-1
    return np.unique(np.r_[0,daily,len(values)-1,np.argmin(dd),np.argmin(values),np.argmax(values)])


def build_report(out,summary):
    scores=[];legs=[];charts=[];activity=[];inline=True
    for name,_,_,_ in r.PHASES:
        folder=Path(out)/'trials'/name;score={'phase':name,**summary['scores'][name]};scores.append(score)
        native=pd.read_csv(folder/'leg_contributions.csv')
        check(len(native)==8 and set(native.symbol)==set(r.SYMBOLS),'All eight native legs required')
        legs.extend({'phase':name,**row} for row in native.to_dict('records'))
        diagnostic=r.read(folder/'strategy_diagnostics.json');events=diagnostic['events']
        activity.append({'phase':name,'weekly_proposals':sum(row['type']=='WEEKLY_PROPOSAL' for row in r.read(folder/'proposal_ledger.json')),
          'rejected_weekly_proposals':sum(row['type']=='PROPOSAL_REJECTED' for row in r.read(folder/'proposal_ledger.json')),
          'refusals':len(r.read(folder/'rejections.json')),'completed_generations':score['completed_basket_count'],
          'entry_transactions':sum(row['type']=='TARGET_SUBMITTED' and row.get('transition')=='ENTERING' for row in events),
          'abort_events':sum(row['type']=='ACCOUNT_ABORT' for row in events),
          'blocked_cleanup_events':sum(row['type'] in ('BLOCKED_DUST','BLOCKED_CLEANUP','CLEANUP_DEADLINE_EXCEEDED') for row in events),
          'actual_funding_payments':len(pd.read_parquet(folder/'funding.parquet')),
          'terminal_flat_resolved':score['terminal_flat_resolved']})
        equity=pd.read_parquet(folder/'equity.parquet');idx=display_indices(equity);shown=equity.iloc[idx]
        dd=equity.equity/equity.equity.cummax()-1
        chart=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[.7,.3],vertical_spacing=.12)
        chart.add_trace(go.Scatter(x=shown.timestamp,y=shown.equity,name='Actual marked equity',line={'color':'#7dd3fc','width':2}),row=1,col=1)
        chart.add_trace(go.Scatter(x=shown.timestamp,y=dd.iloc[idx]*100,name='Actual drawdown %',fill='tozeroy',line={'color':'#fb7185'}),row=2,col=1)
        chart.update_layout(template='plotly_dark',paper_bgcolor='#111c2d',plot_bgcolor='#111c2d',height=420,margin={'l':45,'r':20,'t':35,'b':35},legend={'orientation':'h'},hovermode='x unified')
        chart.update_yaxes(title_text='USDT',row=1,col=1);chart.update_yaxes(title_text='Drawdown %',row=2,col=1)
        charts.append('<details'+(' open' if name=='evaluation' else '')+'><summary>'+esc(name)+' · '+pct(score['total_return'])+'</summary>'+chart.to_html(full_html=False,include_plotlyjs='inline' if inline else False,config={'responsive':True,'displaylogo':False})+'</details>');inline=False
    comparison=table(scores,[('phase','Run',str),('total_return','Net return',pct),('return_after_indicative_exit_reserve','After exit reserve',pct),('sharpe','Daily Sharpe',num),('max_drawdown','Minute drawdown',pct),('funding_pnl','Funding cash',num),('trading_fees','Actual fees',num),('slippage_cost','Slippage diagnostic',num),('indicative_exit_reserve_total','Exit reserve',num),('completed_basket_count','Completed generations',str),('liquidation_event_count','Liquidations',str),('terminal_flat_resolved','Terminal resolved',str)])
    gate_html='<ul class="gates">'+''.join('<li class="'+('pass' if v else 'fail')+'"><b>'+('PASS' if v else 'FAIL')+'</b> '+esc(k.replace('_',' '))+'</li>' for k,v in summary['gates'].items())+'</ul>'
    leg_columns=[('phase','Run',str),('symbol','Asset',str),('instrument_id','Native instrument',str),('net_pnl','Net P&L',num),('funding_cash','Funding cash',num),('fill_count','Actual fills',str),('open_quantity','Terminal native qty',lambda v:f'{v:.8g}')]
    page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Funding rank · candidate 27</title><style>
*{box-sizing:border-box}body{margin:0;background:#09111e;color:#dbeafe;font:15px/1.65 system-ui,sans-serif}.wrap{max-width:1220px;margin:auto;padding:28px 22px}header{background:linear-gradient(120deg,#10223a,#15324c);padding:30px 0}h1{font-size:clamp(30px,4vw,48px);line-height:1.15}h2{font-size:23px;margin-top:0}.eyebrow{color:#7dd3fc;text-transform:uppercase;letter-spacing:.13em;font-size:12px}.card{padding:24px;background:#111c2d;border:1px solid #273850;border-radius:15px;margin:22px 0}.notice{border-left:4px solid #fbbf24}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:13px}th,td{padding:10px;border-bottom:1px solid #273850;text-align:right}th:first-child,td:first-child{text-align:left}th{color:#93c5fd}.gates{display:grid;grid-template-columns:1fr 1fr;gap:9px;list-style:none;padding:0}.gates li{background:#16243a;padding:9px;border-radius:8px}.gates b{font-size:11px;display:inline-block;width:40px}.fail b{color:#fda4af}.pass b{color:#6ee7b7}details{border-top:1px solid #273850;padding:12px 0}summary{cursor:pointer;font-weight:650}a{color:#7dd3fc}p{max-width:1020px}footer{color:#94a3b8;font-size:12px}.meme{color:#fde68a}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}@media(max-width:700px){.wrap{padding:18px 12px}.card{padding:17px}.gates{grid-template-columns:1fr}}
</style></head><body><header><div class="wrap"><div class="eyebrow">Exploratory candidate 27 · fixed rules · independent audits</div><h1>Weekly cross-sectional funding rank</h1><p>Four selected native perpetual legs in one actual 100,000 USDT cross-margin wallet. Weekly long-low / short-high past funding ranks expose real directional price risk.</p></div></header><main class="wrap">'''
    status='Passed declared historical hurdles' if summary['passes_hurdles'] else 'Failed declared historical hurdles'
    page+='<section class="card notice"><h2>'+status+'</h2><p>One new family after 26 prior unsuccessful candidates on the same examined year. This is exploratory reused-year evidence, not an untouched holdout, an established future edge, or a claim that the search avoided overfitting. The 15 gates remain unchanged.</p></section>'
    page+='<section class="card"><h2>Every execution, including losses</h2>'+comparison+'<p>Compounded validation '+pct(summary['validation_compounded_return'])+'; after indicative reserve '+pct(summary['validation_after_exit_reserve'])+'. Anchored evaluation months: '+', '.join(pct(v) for v in summary['anchored_month_returns'])+'.</p>'+gate_html+'</section>'
    page+='<section class="card"><h2>Actual participation and failures</h2><p>A completed generation requires all four actual native targets. Orders, partial fills and proposals alone do not qualify. <span class="meme">DOGE and PEPE</span> are disclosed alongside all assets and must both complete participation; their colors do not select winners.</p>'+table(activity,[(k,k.replace('_',' ').title(),str) for k in activity[0]])+'</section>'
    page+='<section class="card"><h2>All eight legs, all five runs</h2><p>Hedge losses remain visible. PEPE quantities and prices retain native 1000PEPEUSDT bundle units. Contributions reconcile marked inventory, realized trade cash, actual funding and executed fees.</p>'+table(legs,leg_columns)+'</section>'
    page+='<section class="card"><h2>Account performance</h2><p>Plots show daily endpoint samples plus actual global equity and drawdown extrema. The drawdown metric and all audit/accounting computations use the complete minute and settlement clocks; sampling changes presentation only.</p>'+''.join(charts)+'</section>'
    page+='<section class="card"><h2>Audit scope and evidence</h2><p>The independent feature certificate reconstructs causal inputs under declared availability assumptions. The financial certificate reconstructs actual native fills, cash, funding, cross-margin, completed baskets, all five scorecards and all 15 gates. Its separate policy helper verifies recorded proposals, ranks, fresh sizing, submitted targets and exit intents. It does not reconstruct omitted unlogged skips or prove every abort-state transition complete. Publication rechecks 125 financial export files, receipt hashes and frozen source/data/runtime guards.</p><p>'+ ' · '.join('<a href="'+name+'">'+label+'</a>' for name,label in [('summary.json','Exact summary'),('comparison.csv','Five scorecards'),('all_leg_contributions.csv','All 40 legs'),('feature_audit.json','Feature certificate'),('financial_recorded_policy_audit.json','Financial and recorded-policy certificate'),('source_lock.json','Source lock'),('input_verification.json','Input verification'),('feature_receipt.json','Feature receipt'),('proposed_protocol.md','Prospective protocol'),('publication_manifest.json','Publication seal')])+'</p></section>'
    page+='<section class="card"><h2>Causal and execution limits</h2><p>Past actual settlement rates are not forecasts. Absent original historical receipts, settlement plus one minute is assumed availability; price inputs use prior completed minute plus processing delay. Funding observations do not prove a complete historical contractual schedule. No older warmup enters this fixed year.</p><p>This is a slow scheduled basket in minute data, not high-frequency arbitrage, a neutral hedge, or evidence of simultaneous execution. Four independent GTC legs can fail or fill partially; fresh sizing follows actual old-basket flatness. Native quantity grids, current rule metadata, constant fees and maintenance assumptions approximate the past.</p><p>Baseline taker fees are 5 bps and adverse slippage 8 bps; joint stress uses 10 /16 bps, one-minute delay and half participation. Slippage is embedded in fills; its diagnostic is not deducted again. Indicative exit reserves are sensitivity costs, not synthetic exits or another cash debit. Terminal dust or unresolved pending orders fail the terminal gate. Real funding cash and genuine marked inventory remain in the account.</p><p>Seven-day circular blocks, 10,000 draws, seed 42 and 27-comparison tails are conditional uncertainty on this reused path, not a correction that erases adaptation.</p><pre>'+esc(str(summary['conditional_interval']))+'</pre></section></main><footer class="wrap">Fixed year: 5 October 2025 to 5 October 2026 UTC. Original sealed experiment and prior reports are preserved.</footer><script>document.querySelectorAll("details").forEach(n=>n.addEventListener("toggle",()=>{if(n.open)requestAnimationFrame(()=>n.querySelectorAll(".plotly-graph-div").forEach(c=>Plotly.Plots.resize(c)));}));</script></body></html>'
    return page,scores,legs,activity


def publish(cache,out,destination,financial_path,feature_path):
    source=Path(__file__).read_bytes();source_sha=hashlib.sha256(source).hexdigest()
    out,destination=Path(out),Path(destination)
    check(not destination.resolve().is_relative_to(out.resolve()),'Publication cannot mutate experiment namespace')
    check(cache is None or not destination.resolve().is_relative_to(Path(cache).resolve()),'Publication cannot mutate immutable cache namespace')
    check(not any(destination.resolve().is_relative_to((r.REPO/name).resolve()) for name in ('aster','examples','audit')),'Publication cannot mutate executed source namespace')
    check(not destination.exists(),'Preserve previous publication; choose fresh destination')
    financial_path,feature_path=Path(financial_path),Path(feature_path)
    check(financial_path.resolve()!=feature_path.resolve(),'Separate audit receipts required')
    hashes={path:r.digest(path) for path in (financial_path,feature_path)}
    financial,feature=r.read(financial_path),r.read(feature_path)
    summary=verify_receipts(cache,out,financial,feature,hashes[feature_path])
    page,scores,legs,activity=build_report(out,summary)
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.'+destination.name+'-',dir=destination.parent))
    try:
        (stage/'report.html').write_text(page)
        pd.DataFrame(scores).to_csv(stage/'comparison.csv',index=False)
        pd.DataFrame(legs).to_csv(stage/'all_leg_contributions.csv',index=False)
        pd.DataFrame(activity).to_csv(stage/'activity.csv',index=False)
        for name in ('summary.json','source_lock.json','input_verification.json','feature_receipt.json'):(stage/name).write_bytes((out/name).read_bytes())
        (stage/'feature_audit.json').write_bytes(feature_path.read_bytes())
        (stage/'financial_recorded_policy_audit.json').write_bytes(financial_path.read_bytes())
        (stage/'executed_publisher.py').write_bytes(source)
        (stage/'proposed_protocol.md').write_bytes((out/'executed_source/examples/funding_rank/proposed_protocol.md').read_bytes())
        (stage/'README.md').write_text('# Weekly funding rank: exploratory candidate 27\n\n[Interactive report](report.html) · [Exact summary](summary.json) · [Financial and recorded-policy audit](financial_recorded_policy_audit.json) · [Feature audit](feature_audit.json)\n\nFive fixed executions and all forty native leg rows are disclosed. The year has already been examined; this is not a fresh holdout. Recorded-policy verification does not prove omitted unlogged decisions absent.\n')
        check(all(r.digest(path)==sha for path,sha in hashes.items()),'Audit receipt changed during publication')
        check(verify_receipts(cache,out,r.read(financial_path),r.read(feature_path),hashes[feature_path])==summary,'Audited summary changed during publication')
        check(r.digest(__file__)==source_sha,'Publisher source changed during generation')
        copies={'summary.json':financial['summary_sha256'],'source_lock.json':financial['source_lock_sha256'],
            'feature_receipt.json':financial['feature_receipt_sha256'],'feature_audit.json':hashes[feature_path],
            'financial_recorded_policy_audit.json':hashes[financial_path],'executed_publisher.py':source_sha,
            'input_verification.json':r.digest(out/'input_verification.json'),
            'proposed_protocol.md':r.digest(out/'executed_source/examples/funding_rank/proposed_protocol.md')}
        check(all(r.digest(stage/name)==sha for name,sha in copies.items()),'Staged evidence differs')
        r.dump(stage/'publication_manifest.json',dict(publisher_sha256=source_sha,source_anchor=SOURCE_ANCHOR,input_anchor=INPUT_ANCHOR,
            financial_audit_sha256=hashes[financial_path],feature_audit_sha256=hashes[feature_path],
            audited_output_count=125,audited_outputs_sha256={name:proof['outputs_sha256'] for name,proof in financial['phases'].items()},
            outputs_sha256={p.name:r.digest(p) for p in sorted(stage.iterdir())}))
        check(not destination.exists(),'Destination appeared during staging')
        os.rename(stage,destination)
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True);raise
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',default='data_cache/minute-perpetual-1y');parser.add_argument('--out',default='results/funding-rank-1y-v1')
    parser.add_argument('--destination',default='docs/funding_rank_results');parser.add_argument('--financial-audit',required=True);parser.add_argument('--feature-audit',required=True)
    args=parser.parse_args();print(publish(args.cache,args.out,args.destination,args.financial_audit,args.feature_audit))


if __name__=='__main__':main()
