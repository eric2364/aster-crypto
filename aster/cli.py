import argparse
from dataclasses import asdict
from pathlib import Path
import json
import yaml
from aster.backtest.models import Instrument, SimulationConfig
from aster.backtest.engine import Engine
from aster.data.loader import load
from aster.data.synthetic import generate
from aster.exchanges.adapters import ADAPTERS
from aster.strategies.examples import STRATEGIES
from aster.analytics.benchmarks import benchmarks
from aster.reproducibility import export_result

def execute(document,out=None,report=True):
    instruments=[Instrument(**spec) for spec in document['instruments']]
    cfg=SimulationConfig(**document.get('engine',{}))
    params=document.get('strategy',{}).get('parameters',{})
    name=document.get('strategy',{}).get('name','ma')
    if name not in STRATEGIES:raise ValueError('Unknown example strategy')
    source=document.get('data',{})
    if source.get('bars'):
        bars=load(source['bars']);funding=load(source['funding']) if source.get('funding') else None
    elif source.get('synthetic',False):
        bars,funding=generate(instruments,source.get('periods',2160),source.get('frequency','1h'),cfg.seed)
    else:raise ValueError('Supply data.bars or explicitly enable data.synthetic')
    manifest_path=Path(source.get('manifest',str(Path(source['bars']).parent/'source_manifest.json'))) if source.get('bars') else None
    manifest=json.loads(manifest_path.read_text()) if manifest_path is not None and manifest_path.exists() else None
    result=Engine(instruments,cfg).run(bars,STRATEGIES[name](**params),funding)
    benchmark=benchmarks(bars,sum(cfg.initial_balances.values()))
    root,summary=export_result(result,out or document.get('output','results/latest'),bars,funding,params,benchmark,
        data_source="SYNTHETIC demonstration" if source.get("synthetic") else (manifest.get("source") if manifest else str(source.get("bars"))), source_manifest=manifest)
    (root/'config.yaml').write_text(yaml.safe_dump(document,sort_keys=False))
    if report:
        from aster.reports.dashboard import write_html
        result.benchmark=benchmark
        result.metadata=json.loads((root/'metadata.json').read_text())
        write_html(result,root/'dashboard.html',summary)
    print(json.dumps({'output':str(root.resolve()),'strategy':name,'data':'SYNTHETIC' if source.get('synthetic') else 'user supplied',
        'return':summary['total_return'],'fills':len(result.fills),'closed_trades':len(result.trades),
        'funding_events':len(result.funding),'final_equity':summary['final_equity'],'quality_warnings':result.quality['warnings']},indent=2))
    return result

def main():
    parser=argparse.ArgumentParser(description='Aster crypto research — explicit execution assumptions')
    sub=parser.add_subparsers(dest='command',required=True)
    back=sub.add_parser('backtest');back.add_argument('--config',required=True);back.add_argument('--out');back.add_argument('--no-report',action='store_true')
    demo=sub.add_parser('demo');demo.add_argument('--market',choices=['spot','perpetual'],default='perpetual')
    demo.add_argument('--strategy',choices=list(STRATEGIES),default='ma');demo.add_argument('--periods',type=int,default=2160)
    demo.add_argument('--out',default='results/demo');demo.add_argument('--no-report',action='store_true')
    args=parser.parse_args()
    if args.command=='backtest':document=yaml.safe_load(Path(args.config).read_text())
    else:
        specs=[ADAPTERS['binance'].instrument('BTCUSDT',args.market,base='BTC'),
               ADAPTERS['bybit'].instrument('ETHUSDT',args.market,base='ETH')]
        document={'instruments':[asdict(s) for s in specs],
            'engine':{'initial_balances':{'binance':50000,'bybit':50000},'leverage':3,'margin_mode':'isolated'},
            'strategy':{'name':args.strategy,'parameters':{'allocation':.2}},
            'data':{'synthetic':True,'periods':args.periods,'frequency':'1h'}}
    execute(document,args.out,not args.no_report)

if __name__=='__main__':main()
