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
              'trajectory_reconstruction_passed':True,'summary_reconstruction_passed':True}
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


def publish(cache,out,destination,audit_path):
    out=Path(out); destination=Path(destination); receipt=read(audit_path)
    verify_receipt(cache,out,receipt)
    if destination.exists(): raise RuntimeError('Preserve previous publication; choose a fresh destination')
    summary=read(out/'summary.json'); models=verified_models(out)
    rows=[{'phase':name,**summary['scores'][name]} for name,*_ in PHASES]
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
    page+='<h1>BTC/ETH-factor residual convergence</h1><p class="warning">One exploratory economic family, the 25th disclosed candidate. This year has already been examined. Conditional diagnostics and intervals cannot establish a fresh holdout or remove research adaptation.</p>'
    page+='<p>Unchanged prospective hurdles: '+('passed' if summary['passes_hurdles'] else 'failed')+'. All five joint-account simulations and every target are disclosed. Native 1000PEPE units are retained. Marked terminal inventory and indicative exit reserves are separately reported.</p>'
    page+='<table><thead><tr><th>Run</th><th>Net return</th><th>After indicative reserve</th><th>Liquidations</th><th>Open legs</th></tr></thead><tbody>'+table+'</tbody></table>'
    page+='<p>Compounded validation return: '+percentage(summary['validation_compounded_return'])+'. After indicative reserve: '+percentage(summary['validation_after_exit_reserve'])+'. The reserve is an approximation, not an executed exit or assurance of fillable volume.</p><ul>'+gates+'</ul>'
    page+='<h2>All eight evaluation legs</h2><table><tr><th>Underlying label</th><th>Net P&amp;L, USDT</th><th>Fills</th><th>Open native quantity</th></tr>'+legs+'</table>'
    page+='<h2>Frozen training diagnostics</h2>'+diagnostics
    page+='<h2>Joint account paths</h2><p>Plots sample about 4,000 observations for display. Risk, cash and reconciliation use every minute and settlement-clock observation. Factor exposures use frozen return betas and actual current mark notionals; they are approximate sensitivity diagnostics.</p>'+''.join(charts)
    page+='<h2>Conditional interval and provenance</h2><pre>'+html.escape(json.dumps(summary['conditional_interval'],indent=2))+'</pre>'
    page+='<p>All raw ledgers remain in the sealed experiment directory. Published summary pins source, model and full-resolution equity hashes. Independent audit receipt SHA256: '+digest(audit_path)+'.</p></body></html>'
    verify_receipt(cache,out,receipt)
    destination.mkdir(parents=True)
    (destination/'report.html').write_text(page)
    pd.DataFrame(rows).to_csv(destination/'comparison.csv',index=False)
    dump(destination/'summary.json',{**summary,'publication_status':'independently audited',
                                    'independent_audit_receipt_sha256':digest(audit_path)})
    dump(destination/'publication_verification.json',receipt)
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
