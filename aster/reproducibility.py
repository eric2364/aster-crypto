from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import subprocess
import pandas as pd
from aster.analytics import metrics, json_safe
from aster import __version__

def data_hash(frame):
    # Serialized normalized values include instrument identity and event timestamps.
    return hashlib.sha256(frame.to_csv(index=False,float_format='%.17g').encode()).hexdigest()

def export_result(result, destination, bars=None, funding_source=None, parameters=None, benchmark=None, data_source=None, source_manifest=None):
    root=Path(destination);root.mkdir(parents=True,exist_ok=True)
    for name in ('equity','fills','trades','funding','events','positions'):
        frame=getattr(result,name)
        frame.to_csv(root/f'{name}.csv',index=False)
        frame.to_parquet(root/f'{name}.parquet',index=False)
    if benchmark is not None:benchmark.to_csv(root/'benchmark.csv',index=False)
    try:git=subprocess.check_output(['git','rev-parse','HEAD'],stderr=subprocess.DEVNULL,text=True).strip()
    except (OSError,subprocess.CalledProcessError):git=None
    source_root=Path(__file__).resolve().parent
    source_hashes={str(p.relative_to(source_root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_root.rglob('*.py'))}
    summary=metrics(result.equity,result.trades,result.fills)
    metadata={'software':'aster','version':__version__,'run_timestamp':datetime.now(timezone.utc).isoformat(),
        'strategy':result.strategy,'strategy_version':result.strategy_version,'parameters':parameters or {},'git_commit':git,
        'source_sha256':source_hashes,'engine':asdict(result.config),'instruments':[asdict(i) for i in result.instruments],
        'source_manifest':source_manifest,
        'data_source':data_source or 'user supplied; provenance unverified',
        'data_sha256':data_hash(bars) if bars is not None else None,
        'funding_sha256':data_hash(funding_source) if funding_source is not None else None,
        'start':str(result.equity.timestamp.iloc[0]),'end':str(result.equity.timestamp.iloc[-1]),
        'timeframes_seconds':sorted(bars.duration_seconds.unique().tolist()) if bars is not None else [],
        'data_quality':result.quality,'timestamp_semantics':'UTC interval start; complete bar available at end',
        'python':__import__('sys').version,'dependencies':{p:importlib.metadata.version(p) for p in ['numpy','pandas','pyarrow','plotly']},
        'open_positions_marked':True,'terminal_forced_close':False,
        'slippage_accounting':'embedded in fill-price P&L; diagnostic, never subtracted twice'}
    for name,obj in [('metrics',summary),('metadata',metadata)]:
        (root/f'{name}.json').write_text(json.dumps(json_safe(obj),indent=2,allow_nan=False))
    if source_manifest is not None:
        (root/'source_manifest.json').write_text(json.dumps(json_safe(source_manifest),indent=2))
    (root/'quality.json').write_text(json.dumps(json_safe(result.quality),indent=2))
    verify_ledgers(result)
    return root,summary

def verify_ledgers(result):
    """Conservation identities cover open inventory, closed trades and all cash costs."""
    last=result.equity.iloc[-1];initial=sum(result.config.initial_balances.values())
    expected=initial+last.realized_pnl+last.unrealized_pnl+last.funding_pnl-last.trading_fees-last.liquidation_fees
    if abs(expected-last.equity)>max(1e-7,abs(expected)*1e-10):raise AssertionError('Equity ledger does not reconcile')
    if not result.fills.empty:
        if abs(result.fills.fee.sum()-last.trading_fees)>1e-7:raise AssertionError('Fill fees do not reconcile')
        if (result.fills.quantity<=0).any() or (result.fills.price<=0).any():raise AssertionError('Invalid fills')
    if not result.funding.empty and abs(result.funding.funding_payment.sum()-last.funding_pnl)>1e-7:
        raise AssertionError('Funding ledger does not reconcile')
    closed_net=result.trades.net_pnl.sum() if not result.trades.empty else 0
    open_net=(result.positions.unrealized_pnl+result.positions.funding_pnl-result.positions.entry_fees).sum() if not result.positions.empty else 0
    if abs(closed_net+open_net-(last.equity-initial))>max(1e-7,abs(initial)*1e-10):
        raise AssertionError('Closed trades plus open positions do not reconcile')
    return True
