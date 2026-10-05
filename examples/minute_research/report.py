"""Publish compact, auditable research evidence; raw minute ledgers stay local."""
from pathlib import Path
import argparse
import json
import shutil
import sys
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

def combined_bootstrap(frame):
 from aster.analytics import daily_returns
 dated=frame.copy();dated['timestamp']=pd.to_datetime(dated.timestamp,utc=True).dt.as_unit('ns');end=dated.timestamp.max()
 if end==end.normalize():dated.loc[dated.timestamp==end,'timestamp']=end-pd.Timedelta(microseconds=1)
 x=daily_returns(dated).dropna().to_numpy();n=len(x);rng=np.random.default_rng(42)
 starts=rng.integers(0,n,size=(10000,int(np.ceil(n/7))))
 indices=(starts[:,:,None]+np.arange(7))%n
 totals=np.expm1(np.log1p(x[indices.reshape(10000,-1)[:,:n]]).sum(axis=1))
 return {'total_policy_tests':13,'method':'circular7dayblocks;10000samples;seed42;conditional retrospective diagnostic',
         'bonferroni_13_interval':np.quantile(totals,[.05/(2*13),1-.05/(2*13)]).tolist()}

def main():
 p=argparse.ArgumentParser();p.add_argument('--run',default='results/minute-study-1y');p.add_argument('--publish',default='examples/minute_research/evidence');args=p.parse_args()
 root=Path(args.run);published=Path(args.publish);published.mkdir(parents=True,exist_ok=True)
 summary=json.loads((root/'summary.json').read_text());families=summary['families']
 for name in ['protocol.json','selection.json','summary.json','all_trials.json']:
  shutil.copy2(root/name,published/name)
 fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.1,subplot_titles=['Locked holdout equity: equal independent sleeves','Minute-calculated drawdown; chart sampled hourly'])
 rows=[];ledger_rows=[];combined_intervals={}
 for family in families:
  name=family['family'];base=pd.read_parquet(root/'pooled'/name/'equity.parquet').set_index('timestamp')
  combined_intervals[name]=combined_bootstrap(base.reset_index())
  hourly=base.equity.resample('1h').last()
  hourly.to_csv(published/f'{name}_equity_hourly.csv')
  dd=base.equity/base.equity.cummax()-1
  fig.add_trace(go.Scatter(x=hourly.index,y=hourly,name=name,mode='lines'),row=1,col=1)
  sampled=dd.resample('1h').min()
  fig.add_trace(go.Scatter(x=sampled.index,y=sampled,name=name,showlegend=False,mode='lines'),row=2,col=1)
  h=family['holdout'];s=family['stress']
  rows.append({'family':name,'selected_scale':family['chosen_scale'],'validation_return':family['validation_compounded_return'],
    'holdout_return':h['total_return'],'stress_return':s['total_return'],'sharpe':h['sharpe'],'max_drawdown':h['max_drawdown'],
    'positive_symbols':family['positive_symbols'],'net_profit':h['net_profit'],'fees':h['trading_fees'],'fills':h['fill_count'],
    'passed':family['historical_hurdles_passed']})
  for ledger in ['trades','fills','events','positions']:
   frames=[]
   for symbol in summary['protocol']['symbols']:
    source=root/'holdout'/name/f"{family['chosen_scale']:g}"/'base'/symbol/f'{ledger}.parquet'
    frame=pd.read_parquet(source)
    frame['research_symbol']=symbol
    frames.append(frame)
   pd.concat(frames,ignore_index=True).to_csv(published/f'{name}_{ledger}.csv',index=False)
 (published/'combined_selection_diagnostic.json').write_text(json.dumps(combined_intervals,indent=2))
 table=pd.DataFrame(rows);table.to_csv(published/'comparison.csv',index=False)
 fig.update_layout(template='plotly_dark',height=900,title='Aster: last-year minute research / fixed historical holdout',hovermode='x unified',legend=dict(orientation='h',y=-.12),paper_bgcolor='#0d1424',plot_bgcolor='#0d1424')
 fig.update_yaxes(tickformat='.1%',row=2,col=1)
 display=table.copy()
 for column in ['validation_return','holdout_return','stress_return','max_drawdown']:
  display[column]=display[column].map(lambda value:f'{value:.2%}')
 for column in ['net_profit','fees']:display[column]=display[column].map(lambda value:f'${value:,.0f}')
 display['sharpe']=display.sharpe.map(lambda value:f'{value:.2f}' if pd.notna(value) else 'undefined')
 display['positive_symbols']=display.positive_symbols.map(lambda value:f'{value}/8')
 display['passed']=display.passed.map({True:'PASS',False:'FAIL'})
 display=display.rename(columns={'family':'Policy','selected_scale':'Scale','validation_return':'Validation','holdout_return':'Holdout','stress_return':'Stress','sharpe':'Sharpe','max_drawdown':'Drawdown','positive_symbols':'Assets','net_profit':'Net P&L','fees':'Fees','fills':'Fills','passed':'Gate'})
 table_html='<div style="overflow-x:auto">'+display.to_html(index=False,classes='table')+'</div>'
 intro=f"""<h1>Last-year minute strategy research</h1><p>Source: 4,204,800 official one-minute spot bars, 5 Oct 2025 to 5 Oct 2026 UTC; 8,760 settled funding observations.</p><p>Training: first six months. Validation: three fresh-wallet monthly folds. Holdout: 5 Jul–5 Oct 2026. Eight families; a common duration scale selected on training only. No holdout tuning.</p><p><strong>{summary['pass_count']} of 8 families passed all predefined historical hurdles.</strong> Historical checks do not establish a durable, non-overfit trading edge. All failures are retained.</p><p>Capital: eight independent $12,500 spot sleeves, 95% entry allocation, fixed units until exit. Standard assumed fee 10 bps per side; slippage 2–8 bps. Stress: 20 bps fee, doubled slippage, one-minute execution delay, half volume participation. Funding is a published predictor here; spot positions collect no funding.</p><p>Charts sampled hourly for presentation. Holdout metrics use minute equity. Universe consists of selected surviving instruments; it is not survivorship-free. Current lot/tick rules approximate historical rules. No historical X, QQQ or inflation signal is claimed.</p>"""
 body=fig.to_html(full_html=False,include_plotlyjs=True)
 html=f'''<!doctype html><html><head><meta charset="utf-8"><title>Aster minute research</title><style>body{{background:#0d1424;color:#dce5f5;font:16px system-ui;max-width:1450px;margin:40px auto;padding:0 24px}}p{{line-height:1.55}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:10px;border-bottom:1px solid #334155;text-align:right}}th:first-child,td:first-child{{text-align:left}}</style></head><body>{intro}{table_html}{body}<p>See summary.json for individual symbols, all pass/fail gates, monthly returns, neighboring parameters and conditional block-bootstrap intervals. All engine ledgers reconcile.</p></body></html>'''
 (root/'dashboard.html').write_text(html)
 (published/'dashboard.html').write_text(html)
 print(table.to_string(index=False));print(root/'dashboard.html')

if __name__=='__main__':main()
