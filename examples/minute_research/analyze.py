"""Rebuild summaries from verified completed ledgers; never rerun or retune signals."""
from pathlib import Path
import hashlib
import json
import runpy
import sys
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
m=runpy.run_path(str(Path(__file__).with_name('run.py')))
root=Path(sys.argv[1] if len(sys.argv)>1 else 'results/minute-study-1y')
protocol=json.loads((root/'protocol.json').read_text())
selection=json.loads((root/'selection.json').read_text());chosen=selection['chosen']
executed=root/'reproducibility'/'executed_runner.py'
old_hash=hashlib.sha256(executed.read_bytes()).hexdigest()
package={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('aster').rglob('*.py')}
source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('data_cache/minute-1y').glob('*/bars.parquet')}
catalog_hash=hashlib.sha256(Path('data_cache/minute-1y/instruments.json').read_bytes()).hexdigest()
funding_hashes={p.stem:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('data_cache/minute-1y/funding').glob('*.parquet')}
allrows=[]
for path in root.rglob('metrics.json'):
 metadata=json.loads((path.parent/'metadata.json').read_text());p=metadata['parameters'];fp=p['fingerprints']
 if fp['runner']!=old_hash or fp['package']!=package:raise RuntimeError('Executed strategy/engine version mismatch')
 symbol=metadata['instruments'][0]['symbol'];source=f'data_cache/minute-1y/{symbol}/bars.parquet'
 if fp['data']!=source_hashes[source] or fp['instruments']!=catalog_hash:raise RuntimeError('Market/instrument source changed')
 if 'leader' in fp and fp['leader']!=source_hashes['data_cache/minute-1y/BTCUSDT/bars.parquet']:raise RuntimeError('Leader source changed')
 if 'funding' in fp and fp['funding']!=funding_hashes[symbol]:raise RuntimeError('Funding source changed')
 allrows.append({'family':p['family'],'symbol':symbol,'scale':p['scale'],'phase':p['phase'],'stress':'stress' in path.parts,
                 'path':str(path.parent),'metrics':json.loads(path.read_text())})
expected=set()
for family,scale in chosen.items():
 for symbol in protocol['symbols']:
  for candidate in protocol['scales']:
   expected.add((family,symbol,candidate,'training',False))
   expected.add((family,symbol,candidate,'holdout',False))
  for k in (1,2,3):expected.add((family,symbol,scale,f'validation{k}',False))
  expected.add((family,symbol,scale,'holdout',True))
actual=[(r['family'],r['symbol'],r['scale'],r['phase'],r['stress']) for r in allrows]
if len(actual)!=640 or len(set(actual))!=640 or set(actual)!=expected:raise RuntimeError('Expected640 distinct locked-protocol trials')
for family,selected in chosen.items():
 scores=[]
 for scale in protocol['scales']:
  rows=[r for r in allrows if r['family']==family and r['scale']==scale and r['phase']=='training']
  _,score=m['aggregate'](rows)
  scores.append((score['sharpe'] if score['sharpe'] is not None else -np.inf,-abs(scale-1),scale))
 if max(scores)[2]!=selected:raise RuntimeError('Retained training-only choice differs from deterministic training selection')
summaries=[];pooled=[]
for family,scale in chosen.items():
 def rows_for(phase,s=scale,stress=False):return [r for r in allrows if r['family']==family and r['scale']==s and r['phase']==phase and r['stress']==stress]
 validation=[m['aggregate'](rows_for(f'validation{k}'))[1] for k in (1,2,3)]
 rows=rows_for('holdout');equity,score=m['aggregate'](rows)
 stressed,stress=m['aggregate'](rows_for('holdout',stress=True))
 months=m['anchored_months'](equity,m['HOLDOUT_START'])
 neighbors={str(s):m['aggregate'](rows_for('holdout',s))[1]['total_return'] for s in m['SCALES']}
 positive_symbols=sum(r['metrics']['total_return']>0 for r in rows)
 validation_return=np.prod([1+v['total_return'] for v in validation])-1
 checks={'validation_positive':bool(validation_return>0),'holdout_positive':score['total_return']>0,
  'two_positive_months':sum(x>0 for x in months)>=2,'sharpe_at_least_half':(score.get('sharpe') or -np.inf)>=.5,
  'sampled_drawdown_within20pct':score['max_drawdown']<=.2,'jointstress_positive':stress['total_return']>0,
  'all_neighbor_returns_positive':all(v>0 for v in neighbors.values()),'broad_symbol_success':positive_symbols>=5}
 summaries.append({'family':family,'chosen_scale':scale,'validation_fold_metrics':validation,'validation_compounded_return':validation_return,
  'holdout':score,'stress':stress,'anchored_month_returns':months,'neighbor_holdout_returns':neighbors,
  'positive_symbols':positive_symbols,'symbols':{r['symbol']:r['metrics'] for r in rows},
  'bootstrap':m['bootstrap'](equity),'checks':checks,'historical_hurdles_passed':all(checks.values())})
 destination=root/'pooled'/family;destination.mkdir(parents=True,exist_ok=True)
 equity.to_parquet(destination/'equity.parquet',index=False);stressed.to_parquet(destination/'stress_equity.parquet',index=False)
 for frame,scenario in [(equity,'base'),(stressed,'stress')]:
  pooled.extend({'family':family,'scenario':scenario,'timestamp':str(r.timestamp),'equity':r.equity} for r in frame.itertuples())
m['dump'](root/'summary.json',{'protocol':protocol,'families':summaries,'pass_count':sum(s['historical_hurdles_passed'] for s in summaries)})
pd.DataFrame(pooled).to_csv(root/'pooled_equity.csv',index=False)
m['dump'](root/'all_trials.json',allrows)
m['dump'](root/'analysis_repair.json',{'reason':'postprocessing timestamp dtype was millisecond; cast to ns before retaining final midnight mark',
 'executed_runner_sha256':old_hash,'repaired_runner_sha256':hashlib.sha256(Path(__file__).with_name('run.py').read_bytes()).hexdigest(),
 'analysis_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 'simulation_trials_unchanged':640,'signal_parameters_and_execution_unchanged':True})
print('Completed verified postprocessing; pass count:',sum(x['historical_hurdles_passed'] for x in summaries))
