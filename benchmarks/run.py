"""Reproducible measured workloads; each CLI invocation has isolated peak RSS.

python benchmarks/run.py --bars 100000 --symbols 1 --mode noop
python benchmarks/run.py --bars 10000 --mode ma --profile benchmarks/ma.prof
"""
import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import platform
import resource
import sys
from time import perf_counter

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from aster.strategies.base import BaseStrategy
from aster.strategies.examples import MovingAverage
from aster.strategies.vectorized import moving_average_signals


class PeriodicMA(MovingAverage):
    """Hourly observation/rebalance on minute inputs, keeping bounded indicator state."""
    def on_bar(self, context, bar):
        if int(context.now.timestamp()) % 3600 == 0:
            super().on_bar(context, bar)


def generate(rows, symbols, duration, include_bars=True):
    if rows < symbols or rows % symbols:
        raise ValueError('Total bars must be a positive multiple of symbols')
    steps = rows // symbols
    stamps = pd.date_range('2020-01-01', periods=steps, freq=f'{duration}s', tz='UTC')
    rng = np.random.default_rng(42)
    catalog = [Instrument(f'binance:perpetual:COIN{i}USDT', 'binance', f'COIN{i}USDT',
                          'perpetual', min_notional=0) for i in range(symbols)]
    frames = []
    close_matrix = {}
    for i, spec in enumerate(catalog):
        close = (100+i) * np.exp(np.cumsum(rng.normal(0, 0.0003, steps)))
        opening = np.r_[close[0], close[:-1]]
        if include_bars:
            frames.append(pd.DataFrame(dict(timestamp=stamps, instrument_id=spec.id,
                 open=opening, high=np.maximum(opening,close)*1.0002,
                 low=np.minimum(opening,close)*0.9998, close=close,
                 mark_open=opening, mark_price=close, volume=np.full(steps,10000.0),
                 duration_seconds=np.full(steps,duration))))
        close_matrix[spec.id] = close
    return (pd.concat(frames,ignore_index=True) if include_bars else None), catalog, pd.DataFrame(close_matrix,index=stamps)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bars',type=int,default=10000,help='Total rows across all symbols')
    parser.add_argument('--symbols',type=int,default=1)
    parser.add_argument('--duration',type=int,default=60)
    parser.add_argument('--mode',choices=['noop','ma','periodic_ma','vector'],default='noop')
    parser.add_argument('--record-every',type=int,default=100)
    parser.add_argument('--profile',type=Path)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    build_start = perf_counter()
    bars, catalog, matrix = generate(args.bars,args.symbols,args.duration,args.mode!='vector')
    build_seconds = perf_counter()-build_start
    profile = cProfile.Profile() if args.profile else None
    if profile: profile.enable()
    start = perf_counter()
    if args.mode == 'vector':
        signals = moving_average_signals(matrix,8,24)
        counts = dict(fills=0,trades=0,ledger_events=0,snapshots=0,
                      signal_cells=int(signals.size))
    else:
        strategy = (BaseStrategy() if args.mode=='noop' else
                    MovingAverage(allocation=0.1/args.symbols) if args.mode=='ma' else
                    PeriodicMA(allocation=0.1/args.symbols))
        config = SimulationConfig(initial_balances={'binance':100000.0},
                 record_every=args.record_every, margin_mode='cross')
        result = Engine(catalog,config).run(bars,strategy)
        counts = dict(fills=len(result.fills),trades=len(result.trades),
                      ledger_events=len(result.events),snapshots=len(result.equity))
    elapsed = perf_counter()-start
    if profile:
        profile.disable()
        args.profile.parent.mkdir(parents=True,exist_ok=True)
        profile.dump_stats(str(args.profile))
    # RSS includes interpreter, input generation, normalization, event schedule and output frames.
    # Linux ru_maxrss can retain the command launcher's pre-exec high-water mark.
    # VmHWM is this executable's observed peak, verified against /proc/self/status.
    status = Path('/proc/self/status')
    peak = (float(next(line.split()[1] for line in status.read_text().splitlines()
                      if line.startswith('VmHWM:'))) / 1024 if status.exists() else
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    boundary_count = args.bars // args.symbols + 1
    row = dict(mode=args.mode,bars=args.bars,symbols=args.symbols,duration_seconds=args.duration,
        record_every=args.record_every,seconds=elapsed,build_seconds=build_seconds,
        peak_rss_mib=peak,peak_rss_source='proc_vm_hwm' if status.exists() else 'rusage',
        bars_per_second=args.bars/elapsed,
        market_observations_per_second=(2*args.bars/elapsed if args.mode!='vector' else None),
        clock_timestamps=boundary_count if args.mode!='vector' else None,
        clock_timestamps_per_second=boundary_count/elapsed if args.mode!='vector' else None,
        python=platform.python_version(),platform=platform.platform(),
        pandas=pd.__version__,numpy=np.__version__,seed=42,**counts)
    root = Path(__file__).resolve().parents[1]
    row['source_sha256'] = {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [root/'aster/backtest/engine.py',root/'aster/backtest/portfolio.py']}
    text = json.dumps(row,indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text+'\n')


if __name__ == '__main__':
    main()
