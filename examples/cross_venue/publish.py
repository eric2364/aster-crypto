"""Three independent audits gate presentation; never runs features, strategy or Engine."""
from __future__ import annotations
import argparse
import html
import hashlib
import json
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
from examples.cross_venue import run as r

SOURCE_ANCHOR='98fe45a55866ccfd1fa5a4e68deb52a127ff7ff2'
INPUT_FREEZE_ANCHOR='1820b8278bfae8a3775fce3b0ee15be8ac2a5448'
FINANCIAL_AUDITOR=r.REPO/'audit/verify_cross_venue_outputs.py'
FEATURE_AUDITOR=r.REPO/'audit/verify_cross_venue_features.py'
NO_ADMISSION_AUDITOR=r.REPO/'audit/verify_cross_venue_no_admission.py'
GATES={'positive_compounded_validation','positive_validation_after_exit_reserve','two_positive_anchored_months',
       'daily_sharpe_at_least_half','minute_drawdown_at_most_twenty_percent','no_liquidation_all_seven_runs',
       'four_matched_pairs_including_both_doge_and_pepe'} | {'positive_'+name+suffix
       for name in ('evaluation','evaluation_stress','evaluation_alternative','evaluation_alternative_stress')
       for suffix in ('','_after_exit_reserve')}


def check(ok,message):
    if not ok:raise RuntimeError(message)


def verify_receipts(binance,bybit,out,financial,feature,no_admission=None):
    """Recheck source packet, all three scopes and all 175 sealed financial output files."""
    check(isinstance(no_admission,dict),'Separate cohort-specific no-admission audit required')
    out=Path(out)
    r.guard(binance,bybit,out)
    frame=r.verified_features(out);del frame
    common={'source_lock_sha256':r.digest(out/'source_lock.json'),
            'features_sha256':r.digest(out/'features.parquet'),
            'feature_receipt_sha256':r.digest(out/'feature_receipt.json')}
    for receipt,label in [(financial,'financial'),(feature,'feature')]:
        check(receipt.get('complete') is True and receipt.get('errors') == []
              and all(receipt.get(k)==v for k,v in common.items()),f'Missing/stale independent {label} audit')
    for receipt,implementation in ((financial,FINANCIAL_AUDITOR),(feature,FEATURE_AUDITOR)):
        check(receipt.get('source_anchor')==SOURCE_ANCHOR,'Independent audit source anchor differs')
        check(receipt.get('source_unchanged_during_audit') is True,'Independent auditor source stability absent')
        check(receipt.get('auditor_sha256')==r.digest(implementation),'Independent auditor implementation SHA differs')
    check(financial.get('auditor_source_unchanged') is True,'Independent financial auditor source stability absent')
    check(financial.get('input_anchor')==INPUT_FREEZE_ANCHOR,'Financial input freeze anchor differs')
    check(feature.get('auditor_source_unchanged') is True,'Independent feature auditor source stability absent')
    check(feature.get('input_freeze_anchor')==INPUT_FREEZE_ANCHOR,'Feature input freeze anchor differs')
    check(feature.get('reference_reconstruction_passed') is True,'Independent causal feature reconstruction absent')
    check(financial.get('trajectory_reconstruction_passed') is True and financial.get('summary_reconstruction_passed') is True,
          'Independent financial/summary reconstruction absent')
    check(financial.get('execution_fill_reconstruction_passed') is True
          and financial.get('separate_wallet_reconstruction_passed') is True,'Independent fill/separate-wallet reconstruction absent')
    check(financial.get('summary_sha256')==r.digest(out/'summary.json'),'Audited summary SHA differs')
    check(no_admission.get('complete') is True and no_admission.get('errors')==[]
          and all(no_admission.get(k)==v for k,v in common.items()),'Missing/stale cohort-specific no-admission audit')
    check(no_admission.get('source_anchor')==SOURCE_ANCHOR and no_admission.get('input_anchor')==INPUT_FREEZE_ANCHOR,'No-admission frozen anchor differs')
    check(no_admission.get('auditor_sha256')==r.digest(NO_ADMISSION_AUDITOR)
          and no_admission.get('guard_helper_sha256')==r.digest(FINANCIAL_AUDITOR)
          and no_admission.get('source_unchanged_during_audit') is True,'No-admission auditor provenance differs')
    check(no_admission.get('summary_sha256')==financial['summary_sha256']
          and no_admission.get('no_economic_admission_reconstruction_passed') is True
          and no_admission.get('unit_cost_upper_bound_reconstruction_passed') is True
          and no_admission.get('zero_activity_cohort_verified') is True
          and no_admission.get('economic_admission_count')==0,'Cohort no-admission proof absent')
    expected={phase[0] for phase in r.PHASES}
    trials=out/'trials'
    check(trials.exists() and {p.name for p in trials.iterdir()}==expected,'Exact seven actual phases required')
    check(set(financial.get('trials',{}))==expected and set(no_admission.get('trials',{}))==expected,'Audits must cover seven exact phases')
    for phase in r.PHASES:
        hashes=financial['trials'][phase[0]].get('outputs_sha256',{})
        check(set(hashes)==set(r.OUTPUTS) and hashes==r.output_files(trials/phase[0]),'Audited175 output bytes differ')
        cohort=no_admission['trials'][phase[0]]
        check(cohort.get('outputs_sha256')==hashes and cohort.get('zero_activity_verified') is True
              and cohort.get('economic_admission_count')==0
              and cohort.get('unit_cost_upper_bound_reconstruction_passed') is True,'No-admission phase seal/scope differs')
        expected_clocks=len(pd.date_range(phase[1]+pd.Timedelta(minutes=5),phase[2]-pd.Timedelta(hours=168),freq='h',inclusive='left'))
        check(cohort.get('hourly_clocks_checked')==expected_clocks and cohort.get('pair_decisions_checked')==8*expected_clocks,'No-admission eligible clock coverage differs')
        r.verify_completed(binance,bybit,out,phase)
    summary=r.read(out/'summary.json')
    check(summary.get('family')==r.FAMILY and summary.get('candidate_count_cumulative')==26,'Wrong candidate summary identity')
    check(set(summary.get('scores',{}))==expected,'Summary must disclose seven phases')
    check(summary.get('source_lock_sha256')==common['source_lock_sha256'] and summary.get('features_sha256')==common['features_sha256'],'Summary frozen packet differs')
    check(isinstance(summary.get('gates'),dict) and set(summary['gates'])==GATES
          and all(type(v) is bool for v in summary['gates'].values()),'Exact15 Boolean gates required')
    check(type(summary.get('passes_hurdles')) is bool and summary['passes_hurdles']==all(summary['gates'].values()),'Summary hurdle flag inconsistent')
    for phase in r.PHASES:
        check(summary['scores'][phase[0]]==r.read(trials/phase[0]/'metrics.json'),'Summary hides/mislabels phase metrics')
    return summary


def text(value):return html.escape(str(value))

def pct(value):return 'undefined' if value is None else f'{value:.3%}'


def num(value):return 'undefined' if value is None else f'{value:,.2f}'


def table(rows,columns):
    header=''.join('<th>'+text(label)+'</th>' for _,label,_ in columns)
    body=''.join('<tr>'+''.join('<td>'+text(formatter(row.get(key)))+'</td>' for key,_,formatter in columns)+'</tr>' for row in rows)
    return '<div class="table-scroll"><table><thead><tr>'+header+'</tr></thead><tbody>'+body+'</tbody></table></div>'


def sample_indices(equity,limit=2000):
    """Display sample keeps endpoints and global equity/drawdown extrema."""
    values=equity.equity.to_numpy(dtype=float)
    dd=values/np.maximum.accumulate(values)-1
    return np.unique(np.r_[np.arange(0,len(values),max(1,int(np.ceil(len(values)/limit)))),
                            len(values)-1,np.argmin(values),np.argmax(values),np.argmin(dd)])


def exposure_diagnostics(frame):
    times=pd.DatetimeIndex(frame.timestamp).as_unit('ns')
    check(not times.has_duplicates and times.is_monotonic_increasing,'Invalid financial exposure clock')
    seconds=np.r_[np.diff(times.asi8)/1e9,0.]
    rows=[]
    for symbol in r.SYMBOLS:
        native=frame[f'unmatched_native_{symbol}'].to_numpy(dtype=float)
        dollars=frame[f'unmatched_dollars_{symbol}'].to_numpy(dtype=float)
        matched=frame[f'matched_native_{symbol}'].to_numpy(dtype=float)
        rows.append({'pair':symbol,'unmatched_peak_native':float(native.max()),
            'unmatched_peak_dollars':float(dollars.max()),'unmatched_duration_hours':float(seconds[native>1e-9].sum()/3600),
            'matched_peak_native':float(matched.max()),'terminal_unmatched_native':float(native[-1]),
            'terminal_unmatched_dollars':float(dollars[-1]),
            'terminal_binance_native':float(frame[f'quantity_binance_{symbol}'].iloc[-1]),
            'terminal_bybit_native':float(frame[f'quantity_bybit_{symbol}'].iloc[-1])})
    return rows


def build_report(out,summary,financial,feature,financial_sha,feature_sha,no_admission=None,no_admission_sha=None):
    """Read only audited exports; sampling affects visual display only."""
    out=Path(out);scores=[];all_legs=[];all_pairs=[];all_unmatched=[];charts=[]
    included_js=False
    for phase in r.PHASES:
        name,_,_,_,valuation=phase;path=out/'trials'/name
        score={'phase':name,**summary['scores'][name]};scores.append(score)
        equity=pd.read_parquet(path/'equity.parquet');exposure=pd.read_parquet(path/'exposure.parquet')
        legs=pd.read_csv(path/'leg_contributions.csv');pairs=pd.read_csv(path/'pair_contributions.csv')
        check(len(legs)==16 and len(pairs)==8,'Must disclose all 16 venue legs and eight pairs')
        for frame,collection in [(legs,all_legs),(pairs,all_pairs)]:
            for row in frame.to_dict('records'):collection.append({'phase':name,**row})
        all_unmatched.extend({'phase':name,**row} for row in exposure_diagnostics(exposure))
        idx=sample_indices(equity);shown=equity.iloc[idx]
        full_dd=equity.equity/equity.equity.cummax()-1
        chart=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.12,row_heights=[.7,.3])
        for field,label,color in [('equity','Combined marked equity','#1b6d75'),('binance_equity','Binance wallet equity','#2c58aa'),('bybit_equity','Bybit wallet equity','#c78328')]:
            chart.add_trace(go.Scatter(x=shown.timestamp,y=shown[field],name=label,line={'color':color,'width':2}),row=1,col=1)
        chart.add_trace(go.Scatter(x=shown.timestamp,y=100*full_dd.iloc[idx],name='Combined drawdown (%)',fill='tozeroy',line={'color':'#c35353'}),row=2,col=1)
        chart.update_layout(height=430,template='plotly_white',margin={'l':45,'r':20,'t':30,'b':35},legend={'orientation':'h','y':1.12},font={'family':'system-ui'},hovermode='x unified')
        chart.update_yaxes(title_text='USDT',row=1,col=1);chart.update_yaxes(title_text='Drawdown %',row=2,col=1)
        markup=chart.to_html(full_html=False,include_plotlyjs='inline' if not included_js else False,config={'responsive':True,'displaylogo':False})
        included_js=True
        observed=exposure.iloc[idx];risk=go.Figure()
        for v,color in [('binance','#2c58aa'),('bybit','#c78328')]:
            risk.add_trace(go.Scatter(x=observed.timestamp,y=observed[f'{v}_available_margin'],name=v.title()+' available margin',line={'color':color}))
            risk.add_trace(go.Scatter(x=observed.timestamp,y=observed[f'{v}_gross_exposure'],name=v.title()+' gross exposure',line={'color':color,'dash':'dot'}))
        risk.update_layout(height=290,template='plotly_white',margin={'l':45,'r':20,'t':30,'b':35},legend={'orientation':'h'},hovermode='x unified')
        risk_html=risk.to_html(full_html=False,include_plotlyjs=False,config={'responsive':True,'displaylogo':False})
        charts.append('<details class="phase"'+(' open' if name=='evaluation' else '')+'><summary>'+text(name.replace('_',' ').title())+' · '+pct(score['total_return'])+' net · '+text(valuation)+' valuation</summary>'+markup+ '<h3>Separate wallet capacity</h3>'+risk_html+'</details>')
    status='Passed the declared historical hurdles' if summary['passes_hurdles'] else 'Failed the declared historical hurdles'
    base=summary['scores']['evaluation'];participants=summary['actual_matched_pairs']
    gates=''.join('<li class="'+('ok' if value else 'fail')+'"><span>'+('PASS' if value else 'FAIL')+'</span>'+text(key.replace('_',' '))+'</li>' for key,value in summary['gates'].items())
    comparison=table(scores,[('phase','Run',str),('total_return','Net return',pct),('return_after_indicative_exit_reserve','After exit reserve',pct),('sharpe','Daily Sharpe',num),('max_drawdown','Full-clock drawdown',pct),('funding_pnl','Funding cash',num),('trading_fees','Executed fees',num),('slippage_cost','Slippage diagnostic',num),('indicative_exit_reserve_total','Indicative reserve',num),('matched_entry_count','Matched entries',str),('liquidation_event_count','Liquidations',str),('open_position_count','Open legs',str)])
    evaluation_pairs=[x for x in all_pairs if x['phase']=='evaluation']
    evaluation_legs=[x for x in all_legs if x['phase']=='evaluation']
    pair_table=table(evaluation_pairs,[('pair','Pair',str),('net_pnl','Net P&L, USDT',num),('funding_cash','Funding cash, USDT',num),('fill_count','Actual fills',str)])
    leg_table=table(evaluation_legs,[('pair','Pair',str),('venue','Venue',str),('instrument_id','Native instrument',str),('net_pnl','Net P&L, USDT',num),('funding_cash','Funding cash, USDT',num),('fill_count','Fills',str),('open_quantity','Terminal native quantity',lambda x:f'{x:.8g}')])
    unmatched_table=table([x for x in all_unmatched if x['phase']=='evaluation'],[('pair','Pair',str),('unmatched_peak_native','Peak unmatched native',lambda x:f'{x:.8g}'),('unmatched_peak_dollars','Peak unmatched, USDT',num),('unmatched_duration_hours','Unmatched hours',num),('terminal_unmatched_native','Terminal unmatched native',lambda x:f'{x:.8g}'),('terminal_unmatched_dollars','Terminal unmatched, USDT',num)])
    page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cross-venue funding differential · candidate 26</title><style>
:root{--ink:#182b3b;--muted:#586a78;--paper:#f2f5f7;--teal:#1b6d75;--border:#d9e2e8}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 system-ui,sans-serif}.wrap{max-width:1240px;margin:auto;padding:34px 24px}header{background:#102f40;color:#fff;padding:42px 0}header .wrap{padding-top:0;padding-bottom:0}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.17em;color:#a7d4d9}h1{font-size:clamp(28px,4vw,46px);line-height:1.15;max-width:900px;margin:12px 0}h2{font-size:23px;margin-top:0}h3{font-size:16px}p{max-width:950px}.lede{color:#c4d8e2;max-width:850px}.card{background:#fff;border:1px solid var(--border);border-radius:14px;padding:25px;margin:22px 0;box-shadow:0 4px 16px #102f4005}.notice{border-left:5px solid #c78328;background:#fff9ed}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.metric{padding:20px;background:white;border:1px solid var(--border);border-radius:12px}.metric strong{display:block;font-size:27px;line-height:1.2;margin:9px 0}.metric small,.muted{color:var(--muted)}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th,td{padding:11px;border-bottom:1px solid var(--border);text-align:right}th:first-child,td:first-child{text-align:left}th{background:#f3f7f9}.gates{list-style:none;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:8px}.gates li{background:#f6f8fa;border-radius:8px;padding:10px}.gates span{font-size:10px;font-weight:700;display:inline-block;width:40px}.fail span{color:#a03434}.ok span{color:#157359}.phase{border-top:1px solid var(--border);padding:15px 0}.phase>summary{cursor:pointer;font-weight:650;padding:8px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f9;border-radius:9px;padding:18px;font-size:12px}a{color:#145d87}.links{display:flex;flex-wrap:wrap;gap:16px}footer{color:var(--muted);font-size:12px;margin:28px 0}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}.gates{grid-template-columns:1fr}.wrap{padding:22px 12px}.card{padding:18px}.metric strong{font-size:23px}}@media(max-width:430px){.grid{grid-template-columns:1fr}}
</style></head><body><header><div class="wrap"><div class="eyebrow">One economic family · exploratory candidate 26 · three independent audit scopes</div><h1>Cross-venue realized-funding differential</h1><p class="lede">Eight native perpetual pairs, two separate 50,000 USDT wallets, and seven fixed simulations. The mechanism uses past settled funding under explicit availability assumptions; it does not claim a contemporaneous executable spread edge.</p></div></header><main class="wrap">'''
    page+='<section class="card notice"><h2>'+status+'</h2><p>This year was already examined through 25 earlier candidates. This is one additional exploratory family, not a fresh holdout or evidence that research adaptation has been eliminated. '+('A historical pass does not establish a durable future edge.' if summary['passes_hurdles'] else 'The hypothesis remains a failure under its unchanged rules; no hurdle was relaxed.')+'</p></section>'
    page+='<div class="grid">'+''.join('<div class="metric"><small>'+label+'</small><strong>'+value+'</strong><small>'+note+'</small></div>' for label,value,note in [
        ('Primary evaluation',pct(base['total_return']),'Executed cash plus genuinely marked inventory'),
        ('After indicative exit reserve',pct(base['return_after_indicative_exit_reserve']),'Analysis reserve; no synthetic terminal fill'),
        ('Actual matched pairs',str(len(participants))+' / 8','Requires ≥4, including both DOGE and PEPE'),
        ('All-phase liquidations',str(sum(x['liquidation_event_count'] for x in summary['scores'].values())),'Any of the seven runs fails the hurdle')])+'</div>'
    page+='<section class="card"><h2>All seven executions</h2><p>Three fresh-wallet validation folds, primary evaluation and joint stress, then evaluation and stress under the alternative Bybit settlement-mark approximation. There is no training-P&L selection or neighboring grid.</p>'+comparison+'<p>Compounded validation: '+pct(summary['validation_compounded_return'])+'; after reserve: '+pct(summary['validation_after_exit_reserve'])+'. Anchored evaluation months: '+', '.join(pct(x) for x in summary['anchored_month_returns'])+'.</p><ul class="gates">'+gates+'</ul></section>'
    cohort_table=table([{'phase':name,**record} for name,record in no_admission['trials'].items()],
        [('phase','Phase',str),('hourly_clocks_checked','Eligible hourly clocks',str),('pair_decisions_checked','Pair checks',str),
         ('valid_pair_decisions_checked','Valid feature pairs',str),('economic_admission_count','Economic admissions',str),
         ('max_forecast_to_cost_ratio','Maximum unit carry/cost',lambda v:'not recorded' if v is None else f'{v:.6f}')])
    page+='<section class="card"><h2>Why this cohort stayed in cash</h2><p>A separate audit checked every eligible hourly economic admission, independently of the recorded orders. The conservative unit-notional carry/cost test ignores minimum size and margin rejection because quantity cancels. No potential admission passed the fixed 1.5× stress-roundtrip-cost rule. This closes the omitted-admission question for this zero-activity cohort only; it does not certify the complete policy state machine for a trading cohort.</p>'+cohort_table+'<p><a href="no_admission_audit.json">Complete cohort-specific certificate</a> · Required carry/cost ratio: 1.5. All original rejection reasons and clock counts remain in the receipt.</p></section>'
    page+='<section class="card"><h2>Every evaluation pair and both venue legs</h2><p>Pair P&L sums all 16 venue contributions back to the 100,000 USDT account. A hedge leg may lose; it is not hidden or required to win independently. Native PEPE remains 1000PEPEUSDT at both venues, with equal bundle quantities.</p>'+pair_table+'<details><summary>Show all 16 native venue legs</summary>'+leg_table+'</details><p class="links"><a href="all_pair_contributions.csv">All 56 phase-pair rows</a><a href="all_leg_contributions.csv">All 112 phase-leg rows</a></p></section>'
    page+='<section class="card"><h2>Unmatched execution and terminal inventory</h2><p>Independent venue orders can partially fill or fail. These figures use actual post-fill account snapshots; strategy callback diagnostics occur before current open fills. Unmatched duration sums the observed state interval until the next snapshot. Same-direction legs count as entirely unmatched. Native units are not universally spot coins.</p>'+unmatched_table+'<p class="links"><a href="all_unmatched_exposure.csv">All phases and terminal exposures</a><a href="comparison.csv">Full phase comparison</a></p></section>'
    page+='<section class="card"><h2>Full-clock performance and separate-wallet risk</h2><p>Charts retain approximately 2,000 points, endpoints and global equity/drawdown extrema for display. All risk metrics, bootstrap inputs and financial reconstructions use complete minute and funding clocks. Separate wallets cannot rescue one another with automatic transfers or shared collateral.</p>'+''.join(charts)+'</section>'
    page+='<section class="card"><h2>Independent audit and source coverage</h2><p>The financial audit reconstructed every wallet, quantity, funding and equity trajectory, all gates across seven runs and the bootstrap. The feature audit independently reconstructed available prices, publication-aware yields and validity. A separate cohort-specific audit checked every eligible hourly economic admission and verified zero eligible entries. The financial audit covers recorded executable fills and cash paths; it does not certify generic strategy intent or omitted-order reproduction for a trading cohort. Publication rechecked every one of 175 exported file hashes plus three receipt hashes and the frozen source/data/runtime packet.</p><p class="links"><a href="financial_audit.json">Financial audit</a><a href="feature_audit.json">Feature audit</a><a href="no_admission_audit.json">Zero-admission audit</a><a href="source_lock.json">Frozen source/input/runtime lock</a><a href="feature_receipt.json">Feature receipt</a><a href="proposed_protocol.md">Prospective protocol</a><a href="summary.json">Exact audited summary</a></p><pre>'+text(json.dumps({'financial_audit_sha256':financial_sha,'feature_audit_sha256':feature_sha,'no_admission_audit_sha256':no_admission_sha,'source_lock_sha256':summary['source_lock_sha256'],'features_sha256':summary['features_sha256']},indent=2))+'</pre></section>'
    page+='<section class="card"><h2>What the data and model cannot establish</h2><p>Historical funding rates are actual settlements, not historical forecasts of the next payment. Where no original receipt exists, settlement plus one minute is an assumed availability clock. Mixed, unrecognized or stale observed funding intervals suppress decisions; raw pagination and coverage checks cannot recover an undocumented contractual schedule.</p><p>Bybit does not source an exact settlement mark in funding history. Primary valuation uses the same minute mark-open and the END last completed close; sensitivity uses the latest completed mark-close. Marks are not executable prices. Historical BBO, queue position and simultaneous cross-venue execution are unverified, so these are adverse minute-bar market fills with prior-volume capacity, not high-frequency arbitrage or maker-fill evidence.</p><p>Current contract rules and fixed fees, maintenance/risk tiers and liquidation assumptions approximate the historical environment. Baseline fees are Binance 5 / Bybit 6 bps and adverse slippage 8 bps; stress uses10 / 12 bps,16 bps slippage, one-minute delay and half participation. Slippage is embedded in executed P&L and its diagnostic is not deducted again. Indicative exit reserve is not a funded exit, a volume guarantee or another cash debit. Forced liquidation retains the disclosed mark-derived emergency-fill approximation.</p><p>No pre-year warmup, future payment, fabricated hedge or terminal closure is used. DOGE and PEPE must both actually achieve a completed matched entry for breadth. Cash-only or sparse participation does not establish a trading edge.</p><h3>Conditional uncertainty</h3><p>Seven-day circular blocks, 10,000 draws, seed 42 and 26-comparison tails describe this recorded path conditional on the reused year. They do not undo adaptive research or certify future performance. A constant account can have a zero-width interval without a profitable edge.</p><pre>'+text(json.dumps(summary['conditional_interval'],indent=2))+'</pre></section>'
    page+='</main><footer class="wrap">Fixed year: 5 October 2025–5 October 2026 UTC. Original sealed experiments and175 full-resolution outputs remain in the local experiment directory. Compact publication contains no changes to economic code, data or prior reports.</footer><script>document.querySelectorAll("details.phase").forEach(function(node){node.addEventListener("toggle",function(){if(node.open){requestAnimationFrame(function(){node.querySelectorAll(".plotly-graph-div").forEach(function(chart){Plotly.Plots.resize(chart);});});}});});</script></body></html>'
    return page,scores,all_pairs,all_legs,all_unmatched


def publish(binance,bybit,out,destination,financial_path,feature_path,no_admission_path=None):
    publisher_bytes=Path(__file__).read_bytes();publisher_sha=hashlib.sha256(publisher_bytes).hexdigest()
    out=Path(out);destination=Path(destination)
    check(not destination.resolve().is_relative_to(out.resolve()),'Publication cannot mutate sealed experiment namespace')
    check(no_admission_path is not None,'Separate cohort-specific no-admission receipt required')
    check(not destination.exists(),'Preserve previous publication; choose a fresh destination')
    financial_path,feature_path,no_admission_path=Path(financial_path),Path(feature_path),Path(no_admission_path)
    check(len({path.resolve() for path in (financial_path,feature_path,no_admission_path)})==3,'Require three separate independent audit receipts')
    hashes={path:r.digest(path) for path in (financial_path,feature_path,no_admission_path)}
    financial,feature,no_admission=r.read(financial_path),r.read(feature_path),r.read(no_admission_path)
    check(no_admission.get('feature_audit_sha256')==hashes[feature_path],'No-admission feature audit seal differs')
    summary=verify_receipts(binance,bybit,out,financial,feature,no_admission)
    page,scores,pairs,legs,unmatched=build_report(out,summary,financial,feature,hashes[financial_path],hashes[feature_path],no_admission,hashes[no_admission_path])
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.'+destination.name+'-staged-',dir=destination.parent))
    try:
        (stage/'report.html').write_text(page)
        pd.DataFrame(scores).to_csv(stage/'comparison.csv',index=False)
        pd.DataFrame(pairs).to_csv(stage/'all_pair_contributions.csv',index=False)
        pd.DataFrame(legs).to_csv(stage/'all_leg_contributions.csv',index=False)
        pd.DataFrame(unmatched).to_csv(stage/'all_unmatched_exposure.csv',index=False)
        for name in ('summary.json','source_lock.json','feature_receipt.json','input_verification.json'):
            (stage/name).write_bytes((out/name).read_bytes())
        (stage/'financial_audit.json').write_bytes(financial_path.read_bytes())
        (stage/'feature_audit.json').write_bytes(feature_path.read_bytes())
        (stage/'no_admission_audit.json').write_bytes(no_admission_path.read_bytes())
        (stage/'executed_publisher.py').write_bytes(publisher_bytes)
        (stage/'proposed_protocol.md').write_bytes((out/'executed_source/examples/cross_venue/proposed_protocol.md').read_bytes())
        (stage/'README.md').write_text('# Cross-venue funding differential: exploratory candidate 26\n\n'
            'One economic family on an already examined year. This is not a fresh holdout or proof that adaptation has been eliminated.\n\n'
            +('Declared historical hurdles passed.' if summary['passes_hurdles'] else 'Declared historical hurdles failed; no parameters or gates were relaxed.')+' All seven runs, all eight pairs and all 16 native venue legs remain disclosed.\n\n'
            '[Interactive report](report.html) · [Exact audited summary](summary.json) · [Financial audit](financial_audit.json) · [Feature audit](feature_audit.json) · [Zero-admission audit](no_admission_audit.json) · [Frozen packet](source_lock.json) · [Prospective protocol](proposed_protocol.md)\n\n'
            'Display sampling does not change full-resolution metrics. Actual settlement rates are distinct from predictive availability; Bybit funding-mark cash valuation and bar fills remain explicit approximations. Terminal inventory is marked, not synthetically sold; exit reserves are indicative.\n')
        # Stage consistency and immutable audit inputs checked again just before promotion.
        check(all(r.digest(path)==sha for path,sha in hashes.items()),'Independent audit receipt changed during publication')
        current=verify_receipts(binance,bybit,out,r.read(financial_path),r.read(feature_path),r.read(no_admission_path))
        check(current==summary and r.digest(stage/'summary.json')==financial['summary_sha256'],'Audited summary changed during staging')
        check(r.digest(stage/'financial_audit.json')==hashes[financial_path] and r.digest(stage/'feature_audit.json')==hashes[feature_path],'Staged receipt copy differs')
        check(r.digest(stage/'no_admission_audit.json')==hashes[no_admission_path],'Staged no-admission receipt differs')
        check(r.digest(__file__)==publisher_sha and r.digest(stage/'executed_publisher.py')==publisher_sha,'Publisher source changed during report generation')
        check(r.digest(stage/'source_lock.json')==financial['source_lock_sha256'] and r.digest(stage/'feature_receipt.json')==financial['feature_receipt_sha256'],'Staged frozen packet differs')
        r.dump(stage/'publication_manifest.json',{'publisher_sha256':publisher_sha,
            'financial_audit_sha256':hashes[financial_path],'feature_audit_sha256':hashes[feature_path],
            'no_admission_audit_sha256':hashes[no_admission_path],
            'source_lock_sha256':financial['source_lock_sha256'],'features_sha256':financial['features_sha256'],
            'summary_sha256':financial['summary_sha256'],'source_anchor':SOURCE_ANCHOR,
            'auditor_sha256':{'financial':financial['auditor_sha256'],'feature':feature['auditor_sha256'],'no_admission':no_admission['auditor_sha256']},'financial_output_count':sum(len(t['outputs_sha256']) for t in financial['trials'].values()),
            'outputs_sha256':{p.name:r.digest(p) for p in sorted(stage.iterdir())}})
        check(not destination.exists(),'Publication destination appeared; preserve it')
        os.rename(stage,destination)
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True)
        raise
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binance',default='data_cache/minute-perpetual-1y')
    parser.add_argument('--bybit',default='data_cache/minute-bybit-1y')
    parser.add_argument('--out',default='results/cross-venue-funding-1y-v1')
    parser.add_argument('--destination',default='docs/cross_venue_results')
    parser.add_argument('--financial-audit',required=True)
    parser.add_argument('--feature-audit',required=True)
    parser.add_argument('--no-admission-audit',required=True)
    args=parser.parse_args()
    print(publish(args.binance,args.bybit,args.out,args.destination,args.financial_audit,args.feature_audit,args.no_admission_audit))


if __name__=='__main__':main()
