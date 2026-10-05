"""Independent-audit-gated presentation; never estimates or runs Engine."""
import argparse
import html
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import plotly.graph_objects as go
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from examples.residual_convergence.run import (
    PHASES, guard, verified_models, digest, dump, read, output_files, verify_phase_metadata)


def verify_receipt(cache,out,receipt):
    out=Path(out); guard(cache,out); verified_models(out)
    required={'complete':True,'errors':[],
              'source_lock_sha256':digest(out/'source_lock.json'),
              'models_sha256':digest(out/'models.json'),
              'summary_sha256':digest(out/'summary.json'),
              'trajectory_reconstruction_passed':True,'summary_reconstruction_passed':True,
              'training_model_reconstruction_passed':True}
    if any(receipt.get(k)!=v for k,v in required.items()):
        raise RuntimeError('Independent final source/trajectory/summary audit missing or mismatched')
    if set(receipt.get('trials',{}))!={p[0] for p in PHASES}:
        raise RuntimeError('Audit must cover exactly five joint trials')
    for phase in PHASES:
        path=out/'trials'/phase[0]
        if receipt['trials'][phase[0]].get('outputs_sha256')!=output_files(path):
            raise RuntimeError('Independent trial output seal differs')
        verify_phase_metadata(path,phase)


def percentage(value): return f'{value:.3%}' if value is not None else 'undefined'

def number(value,digits): return f'{value:.{digits}f}' if value is not None else 'undefined'


def publish(cache,out,destination,audit_path):
    out=Path(out); destination=Path(destination); receipt=read(audit_path)
    verify_receipt(cache,out,receipt)
    if destination.exists(): raise RuntimeError('Preserve previous publication; choose a fresh destination')
    summary=read(out/'summary.json'); models=verified_models(out)
    rows=[{'phase':name,**summary['scores'][name]} for name,*_ in PHASES]
    eligible=[alt for alt,model in models['assets'].items() if model['eligible']]
    training=[]
    for alt,model in models['assets'].items():
        diagnostic=model['diagnostics']
        training.append({'asset':alt,'eligible':model['eligible'],'beta_btc':model['beta_btc'],
                         'beta_eth':model['beta_eth'],'hourly_alpha':model['alpha'],
                         'half_life_hours':diagnostic['ou'].get('half_life_hours'),
                         'conditional_adf_pvalue':diagnostic['adf'].get('pvalue'),
                         'failed_checks':'; '.join(diagnostic['failed_checks'])})
    charts=[]
    for name,*_ in PHASES:
        equity=pd.read_parquet(out/'trials'/name/'equity.parquet')
        exposure=pd.read_parquet(out/'trials'/name/'exposure.parquet')
        indices=np.unique(np.r_[np.arange(0,len(equity),max(1,int(np.ceil(len(equity)/4000)))),len(equity)-1])
        shown=equity.iloc[indices]; observed=exposure.iloc[indices]
        figure=go.Figure(go.Scatter(x=shown.timestamp,y=shown.equity,name='Actual marked equity'))
        figure.update_layout(title=name.replace('_',' ').title(),height=310,template='plotly_white')
        charts.append(figure.to_html(full_html=False,include_plotlyjs='inline' if not charts else False))
        factors=go.Figure()
        for key in ['gross_exposure','net_exposure','frozen_factor_exposure_BTCUSDT','frozen_factor_exposure_ETHUSDT']:
            factors.add_trace(go.Scatter(x=observed.timestamp,y=observed[key],name=key.replace('_',' ')))
        factors.update_layout(title='Actual mark-dollar and approximate frozen-factor exposures',height=320,
                              template='plotly_white',legend=dict(orientation='h'))
        charts.append(factors.to_html(full_html=False,include_plotlyjs=False))
    table=''.join('<tr><td>'+html.escape(row['phase'])+'</td><td>'+percentage(row['total_return'])+
                  '</td><td>'+percentage(row['return_after_indicative_exit_reserve'])+'</td><td>'+
                  str(row['liquidation_event_count'])+'</td><td>'+str(row['open_position_count'])+'</td></tr>' for row in rows)
    gates=''.join('<li>'+html.escape(key.replace('_',' '))+': '+('pass' if value else 'fail')+'</li>'
                  for key,value in summary['gates'].items())
    diagnostics=''.join('<details><summary>'+html.escape(alt)+' — '+
                        ('eligible' if model['eligible'] else 'inadmissible')+'</summary><pre>'+
                        html.escape(json.dumps(model,indent=2))+'</pre></details>' for alt,model in models['assets'].items())
    legs=''.join('<tr><td>'+html.escape(row['symbol'])+'</td><td>'+f"{row['net_pnl']:.2f}"+
                 '</td><td>'+str(row['fill_count'])+'</td><td>'+f"{row['open_quantity']:.8g}"+'</td></tr>'
                 for row in summary['all_evaluation_leg_contributions'])
    page='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Residual convergence: exploratory candidate 25</title><style>body{font:16px/1.55 system-ui;margin:32px auto;max-width:1100px;padding:0 20px;color:#17212e}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{padding:9px;border-bottom:1px solid #ccd3df;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:16px}details{margin:12px 0}h1{line-height:1.2}.warning{background:#fff2d7;padding:18px}</style></head><body>'''
    page+='<h1>'+('No admissible assets: residual convergence stayed in cash' if not eligible else 'BTC/ETH-factor residual convergence')+'</h1><p class="warning">One exploratory economic family, the 25th disclosed candidate. This year has already been examined. Conditional diagnostics and intervals cannot establish a fresh holdout or remove research adaptation.</p>'
    page+='<p>'+str(len(eligible))+' of six target assets met the frozen training requirements. '+('The five actual joint simulations therefore produced no trades; this is a rejected hypothesis, not a successful strategy.' if not eligible else 'Every admissibility failure is retained below.')+'</p>'
    page+='<p>Unchanged prospective hurdles: '+('passed' if summary['passes_hurdles'] else 'failed')+'. All five joint-account simulations and every target are disclosed. Native 1000PEPE units are retained. Marked terminal inventory and indicative exit reserves are separately reported.</p>'
    page+='<table><thead><tr><th>Run</th><th>Net return</th><th>After indicative reserve</th><th>Liquidations</th><th>Open legs</th></tr></thead><tbody>'+table+'</tbody></table>'
    page+='<p>Compounded validation return: '+percentage(summary['validation_compounded_return'])+'. After indicative reserve: '+percentage(summary['validation_after_exit_reserve'])+'. The reserve is an approximation, not an executed exit or assurance of fillable volume.</p><ul>'+gates+'</ul>'
    page+='<h2>All eight evaluation legs</h2><table><tr><th>Underlying label</th><th>Net P&amp;L, USDT</th><th>Fills</th><th>Open native quantity</th></tr>'+legs+'</table>'
    training_table=''.join('<tr><td>'+html.escape(row['asset'])+'</td><td>'+number(row['half_life_hours'],1)+'</td><td>'+number(row['conditional_adf_pvalue'],4)+'</td><td>'+html.escape(row['failed_checks'].replace('_',' '))+'</td></tr>' for row in training)
    page+='<h2>All six frozen training diagnostics</h2><p>Prospective requirements were a 1–24-hour half-life and conditional ADF p ≤ 0.01, alongside identification and stability checks. Thresholds were retained after observing the failures. Conditional ADF is not a joint stationarity proof.</p><table><tr><th>Asset</th><th>Half-life, hours</th><th>ADF p</th><th>Failed checks</th></tr>'+training_table+'</table>'+diagnostics
    page+='<h2>Joint account paths</h2><p>Plots sample about 4,000 observations for display. Risk, cash and reconciliation use every minute and settlement-clock observation. Factor exposures use frozen return betas and actual current mark notionals; they are approximate sensitivity diagnostics.</p>'+''.join(charts)
    page+='<p><a href="comparison.csv">Comparison CSV</a> · <a href="training_diagnostics.csv">Training diagnostics CSV</a> · <a href="models.json">Full frozen models</a> · <a href="summary.json">Audited summary</a> · <a href="source_lock.json">Pre-fit source lock</a> · <a href="proposed_protocol.md">Prospective protocol</a></p>'
    page+='<h2>Conditional interval and provenance</h2><p>A zero-width interval on a constant no-trade account measures its cash path; it does not establish a profitable trading edge.</p><pre>'+html.escape(json.dumps(summary['conditional_interval'],indent=2))+'</pre>'
    page+='<p>All raw ledgers remain in the sealed experiment directory. Published summary pins source, model and full-resolution equity hashes. Independent audit receipt SHA256: '+digest(audit_path)+'.</p></body></html>'
    verify_receipt(cache,out,receipt)
    destination.mkdir(parents=True)
    (destination/'report.html').write_text(page)
    compact_columns=['phase','total_return','return_after_indicative_exit_reserve','sharpe','max_drawdown',
                     'trade_count','fill_count','liquidation_event_count','open_position_count',
                     'trading_fees','funding_pnl','indicative_exit_reserve_total','runtime_seconds']
    pd.DataFrame(rows)[compact_columns].to_csv(destination/'comparison.csv',index=False)
    pd.DataFrame(training).to_csv(destination/'training_diagnostics.csv',index=False)
    (destination/'models.json').write_bytes((out/'models.json').read_bytes())
    (destination/'source_lock.json').write_bytes((out/'source_lock.json').read_bytes())
    (destination/'proposed_protocol.md').write_bytes(Path(__file__).with_name('proposed_protocol.md').read_bytes())
    pd.DataFrame(summary['all_evaluation_leg_contributions']).to_csv(destination/'leg_contributions.csv',index=False)
    dump(destination/'summary.json',{**summary,'publication_status':'independently audited',
                                    'independent_audit_receipt_sha256':digest(audit_path)})
    dump(destination/'publication_verification.json',receipt)
    heading='No eligible targets: residual convergence stayed in cash' if not eligible else 'Residual convergence: exploratory candidate 25'
    notes=['# '+heading,'',
           'One exploratory economic family on an already examined year; the 25th disclosed candidate. '
           'This is not a fresh holdout or evidence of a durable trading edge.','',
           str(len(eligible))+' of six targets passed the frozen training requirements. '
           +('All five actual joint-account runs consequently had zero trades and zero return. '
             'The account remained at 100,000 USDT; no eligibility threshold was relaxed.' if not eligible else
             'All targets and failed diagnostics remain disclosed.'),'',
           '| Target | Half-life (hours) | Conditional ADF p | Failed checks |',
           '|---|---:|---:|---|']
    for row in training:
        notes.append('| '+row['asset']+' | '+number(row['half_life_hours'],2)+' | '+
                     number(row['conditional_adf_pvalue'],5)+' | '+row['failed_checks'].replace('_',' ')+' |')
    notes.extend(['',
       'The prospective requirements included a 1–24-hour half-life and conditional ADF p ≤ 0.01. '
       'Models used disjoint October–January beta estimation and January–April residual calibration. '
       'The ADF diagnostic is conditional, not a joint stationarity certificate.','',
       'The independent audit reconstructed all six training diagnostics, all five joint account trajectories '
       'and the unchanged summary gates. It verified 34 executed source files, 307 input files and '
       '20 output files for each simulation. Frozen models, execution code and earlier studies were retained.','',
       '[Interactive report](report.html) · [Comparison CSV](comparison.csv) · '
       '[Training diagnostics](training_diagnostics.csv) · [Full frozen models](models.json) · '
       '[Audited summary](summary.json) · [Pre-fit source lock](source_lock.json) · '
       '[Prospective protocol](proposed_protocol.md)','',
       'The conditional 25-comparison bootstrap interval describes the recorded account path. '
       'A zero-width interval on a cash-only account provides no evidence of a profitable strategy. '
       'Display charts sample observations; metrics and audit use the complete minute and settlement clocks.','',
       'Independent receipt SHA256: '+digest(audit_path)+'.'])
    (destination/'README.md').write_text('\n'.join(notes)+'\n')
    dump(destination/'publication_manifest.json',{'publisher_sha256':digest(__file__),
         'independent_audit_receipt_sha256':digest(audit_path),
         'outputs_sha256':{path.name:digest(path) for path in sorted(destination.iterdir())}})
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',default='data_cache/minute-perpetual-1y')
    parser.add_argument('--out',default='results/residual-convergence-1y-v1')
    parser.add_argument('--destination',default='docs/residual_convergence_results')
    parser.add_argument('--audit-receipt',required=True)
    args=parser.parse_args()
    print(publish(args.cache,args.out,args.destination,args.audit_receipt))


if __name__=='__main__': main()
