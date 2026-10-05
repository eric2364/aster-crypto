"""Five exploratory external-factor hypotheses on a previously examined year.

Freeze and independently audit before execution. All 400 trials remain disclosed.
python examples/external_factors/run.py --freeze-only
python examples/external_factors/run.py --workers 4
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aster.analytics import daily_returns, json_safe
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from aster.reproducibility import export_result, verify_ledgers
from examples.external_factors.signals import FAMILIES, build_signals, parameters
# Reuse precisely these audited primitives. The whole importing kernel and its
# own signals dependency are fingerprinted and archived before dispatch.
from examples.minute_directional.run import (
    FixedDirectional, aggregate, anchored_months, exit_reserve,
)

START = pd.Timestamp('2025-10-05', tz='UTC')
TRAIN_END = pd.Timestamp('2026-04-05', tz='UTC')
EVALUATION_START = pd.Timestamp('2026-07-05', tz='UTC')
END = pd.Timestamp('2026-10-05', tz='UTC')
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'DOGEUSDT', 'PEPEUSDT', 'SOLUSDT', 'XRPUSDT', 'LINKUSDT', 'ADAUSDT']
SCALES = [.8, 1., 1.2]
REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / 'examples/minute_directional/run.py'
PROPOSAL = Path(__file__).with_name('proposed_protocol.md')
OUTPUT_FILES = [f'{ledger}.{suffix}' for ledger in
                ['equity', 'fills', 'trades', 'funding', 'events', 'positions']
                for suffix in ['csv', 'parquet']] + [
                    'metrics.json', 'metadata.json', 'quality.json', 'source_manifest.json']


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(value), indent=2, allow_nan=False) + '\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seal_outputs(destination):
    """Seal completed execution files after final metrics are written."""
    destination = Path(destination)
    if any(not (destination / name).is_file() for name in OUTPUT_FILES):
        raise RuntimeError('Cannot seal incomplete execution outputs')
    dump(destination / 'execution_outputs.json', {
        'version': 1, 'sha256': {name: digest(destination / name) for name in OUTPUT_FILES}})


def verify_outputs(destination):
    destination = Path(destination)
    path = destination / 'execution_outputs.json'
    if not path.is_file():
        raise RuntimeError('Cached execution output hash manifest missing')
    manifest = json.loads(path.read_text())
    if manifest.get('version') != 1 or set(manifest.get('sha256', {})) != set(OUTPUT_FILES):
        raise RuntimeError('Cached execution output hash manifest incomplete')
    for name, expected in manifest['sha256'].items():
        if not (destination / name).is_file() or digest(destination / name) != expected:
            raise RuntimeError(f'Cached execution output hash mismatch: {name}')


def source_identity():
    source_paths = [Path(__file__), Path(__file__).with_name('signals.py'), PROPOSAL,
                    SHARED, SHARED.with_name('signals.py')]
    source_paths += [Path(__file__).with_name(name) for name in
                     ['download_qqq.py', 'download_cpi.py', 'extract_flow.py']]
    source_paths += sorted((REPO / 'aster').rglob('*.py'))
    return {'modules': {str(path.relative_to(REPO)): digest(path) for path in source_paths},
            'runtime': {'python': sys.version, 'pandas': pd.__version__, 'numpy': np.__version__},
            'shared_primitives': ['FixedDirectional', 'aggregate', 'anchored_months', 'exit_reserve']}


def used_paths(family, symbol, cache, spot_cache, factors):
    cache, spot_cache, factors = map(Path, [cache, spot_cache, factors])
    paths = [cache / 'instruments.json', cache / 'cross_mapping.json', cache / 'instrument_source_manifest.json',
             cache / symbol / 'bars.parquet', cache / symbol / 'funding.parquet', cache / symbol / 'source_manifest.json']
    if family == 'qqq_risk_transmission':
        paths += [factors / 'qqq/observations.parquet', factors / 'qqq/source_manifest.json']
    elif family == 'cpi_acceleration_event':
        paths += [factors / 'cpi/releases.parquet', factors / 'cpi/source_manifest.json', factors / 'cpi/coverage.json']
    elif family == 'taker_flow_drift':
        paths += [factors / 'flow' / symbol / 'observations.parquet', factors / 'flow' / symbol / 'source_manifest.json']
    elif family == 'perpetual_premium_fade':
        paths += [spot_cache / symbol / 'bars.parquet', spot_cache / symbol / 'source_manifest.json']
    return paths


def dataset_identity(cache, spot_cache, factors):
    paths = set()
    for family in FAMILIES:
        for symbol in SYMBOLS:
            paths.update(used_paths(family, symbol, cache, spot_cache, factors))
    # Original external observations are small and are part of the freeze, even
    # though workers consume their normalized tables. Full Binance raw archives
    # are represented by their publisher-verified hashes in the frozen manifests.
    for directory in ['qqq', 'cpi']:
        paths.update(path for path in (Path(factors) / directory).rglob('*') if path.is_file())
    return {str(path.resolve()): digest(path) for path in sorted(paths)}


def input_coverage(cache, spot_cache, factors):
    cache, spot_cache, factors = map(Path, [cache, spot_cache, factors])
    qqq = pd.read_parquet(factors / 'qqq/observations.parquet')
    cpi = pd.read_parquet(factors / 'cpi/releases.parquet')
    qmeta = json.loads((factors / 'qqq/source_manifest.json').read_text())
    cmeta = json.loads((factors / 'cpi/coverage.json').read_text())
    if len(qqq) != 250 or digest(factors / 'qqq/observations.parquet') != qmeta['normalized_sha256']:
        raise ValueError('Expected verified 250 actual QQQ sessions')
    if len(cpi) != 11 or digest(factors / 'cpi/releases.parquet') != cmeta['releases_parquet_sha256']:
        raise ValueError('Expected verified 11 original-release CPI events')
    if not qqq.source_timestamp.between(START, END, inclusive='left').all():
        raise ValueError('QQQ source history outside fixed year')
    if not cpi.release_time.between(START, END, inclusive='left').all():
        raise ValueError('CPI source history outside fixed year')
    if not cpi.available_at.eq(cpi.release_time + pd.Timedelta(minutes=1)).all():
        raise ValueError('CPI availability mismatch')
    if cpi.reference_month.eq('2025-10').any():
        raise ValueError('Unpublished October CPI cannot be synthesized')
    expected = pd.date_range(START, END, freq='1min', inclusive='left').as_unit('ns')
    coverage = {}
    mappings = json.loads((cache / 'cross_mapping.json').read_text())['mapping']
    for symbol in SYMBOLS:
        mapping = next(item for item in mappings if item['spot_symbol'] == symbol)
        for market, root in [('perpetual', cache), ('spot', spot_cache)]:
            frame = pd.read_parquet(root / symbol / 'bars.parquet', columns=['timestamp', 'instrument_id'])
            expected_id = mapping[f'{market}_instrument_id']
            if not pd.DatetimeIndex(frame.timestamp).as_unit('ns').equals(expected) or not frame.instrument_id.eq(expected_id).all():
                raise ValueError(f'Complete exact-year {market} grid/identity required: {symbol}')
        flow_path = factors / 'flow' / symbol / 'observations.parquet'
        flow = pd.read_parquet(flow_path, columns=['timestamp', 'available_at', 'instrument_id'])
        flow_meta = json.loads((flow_path.parent / 'source_manifest.json').read_text())
        if digest(flow_path) != flow_meta['normalized_sha256']:
            raise ValueError(f'Flow normalized hash mismatch: {symbol}')
        if flow_meta['sources']['target_bars_sha256'] != digest(cache / symbol / 'bars.parquet'):
            raise ValueError(f'Flow original target mismatch: {symbol}')
        if not pd.DatetimeIndex(flow.timestamp).as_unit('ns').equals(expected) or not flow.instrument_id.eq(mapping['perpetual_instrument_id']).all():
            raise ValueError(f'Flow source grid/identity mismatch: {symbol}')
        if not flow.available_at.eq(flow.timestamp + pd.Timedelta(minutes=2)).all():
            raise ValueError(f'Flow publication lag mismatch: {symbol}')
        coverage[symbol] = {'perpetual_minutes': len(expected), 'spot_minutes': len(expected), 'flow_minutes': len(flow),
                            'native_id': mapping['perpetual_instrument_id'],
                            'spot_units_per_native_quantity': mapping['spot_base_units_per_perpetual_quantity_unit']}
    return {'qqq_actual_sessions': len(qqq), 'cpi_unique_actual_releases': len(cpi),
            'cpi_missing_reference_months': cmeta['missing_reference_months'], 'symbols': coverage,
            'macro_independence': 'Identical macro events across eight sleeves are not eight independent announcements'}


def freeze(out, cache='data_cache/minute-perpetual-1y', spot_cache='data_cache/minute-1y', factors='data_cache/external-factors-1y'):
    root = Path(out)
    protocol = {'research_status': 'EXPLORATORY: this historical year was already examined in nineteen prior policies/hypotheses; no untouched-test or non-overfit proof',
                'families': FAMILIES, 'scales': SCALES,
                'model_parameters': {family: {str(scale): parameters(family, scale) for scale in SCALES} for family in FAMILIES},
                'economic_proposal_sha256': digest(PROPOSAL),
                'start': str(START), 'training_end': str(TRAIN_END), 'evaluation_start': str(EVALUATION_START), 'end_exclusive': str(END),
                'selection': 'training pooled daily Sharpe; one common scale per family; ties prefer1 then larger scale; all undefined picks1 and reports undefined evidence',
                'validation': 'fresh-wallet April5-May5, May5-June5, June5-July5; no validation-based selection',
                'trials': {'training': 120, 'validation': 120, 'evaluation_all_scales': 120, 'selected_joint_stress': 40, 'total': 400},
                'symbols': SYMBOLS, 'pooled_initial_capital': 100000, 'sleeve_initial_capital': 12500,
                'entry_notional_fraction': .25, 'quantity_policy': 'fixed native quantity at direction transitions, lot-rounded; no minute rebalance',
                'native_pepe': '1000PEPEUSDT trade/funding quantity remains native; divide price by1000 only for synchronized spot premium',
                'leverage': 1, 'margin_mode': 'isolated', 'max_gross_leverage': 1, 'max_position_pct': .5,
                'base_taker_bps': 5, 'slippage_bps': {'BTCUSDT': 2, 'ETHUSDT': 2, 'DOGEUSDT': 8, 'PEPEUSDT': 8, 'other': 5},
                'participation': .05, 'stress': 'double fees/slippage; add1minute order delay; halve participation',
                'funding': 'actual native settlement cash flows, including actual endpoint settlements if supplied; predictor available one minute after actual receipt when supplied, otherwise settlement plus one minute',
                'phase_cutoffs': 'bar start<stop; QQQ/CPI/flow available_at<=stop; all source histories begin within the fixed year; no older initialization',
                'equity_sampling': 'minute/funding-clock evaluation; approximately hourly training/validation; pooled union with prior-only carry-forward',
                'terminal': 'actual final open inventory marked; no fabricated terminal close orders',
                'indicative_exit_reserve': 'diagnostic final marked notional times assumed exit fee/adverse slippage; no executable-volume guarantee or ledger change',
                'criteria': {'validation_positive': True, 'evaluation_positive': True, 'jointstress_positive': True,
                             'positive_after_reserve': 'validation/evaluation/stress/all3neighbors', 'positive_months_minimum': 2,
                             'evaluation_sharpe_minimum': .5, 'evaluation_minute_drawdown_maximum': .2,
                             'all3neighbor_returns_positive': True, 'profitable_evaluation_sleeves_minimum': 5,
                             'liquidations_across_validation_all_neighbors_stress': 0},
                'source_independence': 'QQQ and CPI common directions are correlated sleeve exposures; 11 CPI announcements total, not88',
                'multiple_testing': '24 cumulative economic candidates if this cohort executes; conditional7dayblockbootstrap tails .05/48 and1-.05/48; scales retained as trials',
                'unchanged_prior_research': 'all nineteen prior candidate source/results remain separate',
                'limitations': ['reused-data research adaptation', 'sparse CPI events', 'surviving eight-symbol universe',
                                'current rules approximate history', 'QQQ vendor correction/vintage unknown', 'CPI rendered-source transport disclosed',
                                'minute OHLCV/mark observations omit tick execution and intraminute liquidation paths',
                                'flow is aggregate taker volume, not book OFI', 'funding and premium fades overlap carry mechanisms']}
    path = root / 'protocol.json'
    if path.exists() and json.loads(path.read_text()) != json_safe(protocol):
        raise RuntimeError('Frozen external-factor protocol changed; a separately disclosed batch is required')
    datasets = dataset_identity(cache, spot_cache, factors)
    coverage = input_coverage(cache, spot_cache, factors)
    if not path.exists():
        dump(path, protocol)
    lock = {**source_identity(), 'protocol': digest(path), 'data': datasets, 'input_coverage': coverage}
    lock_path = root / 'source_lock.json'
    if lock_path.exists() and json.loads(lock_path.read_text()) != json_safe(lock):
        raise RuntimeError('Frozen source/model/dataset changed; preserve prior batch instead of silently overwriting')
    if not lock_path.exists():
        dump(lock_path, lock)
    for source, name in [(Path(__file__), 'executed_run.py'), (Path(__file__).with_name('signals.py'), 'executed_signals.py'),
                         (SHARED, 'executed_shared_kernel.py'), (SHARED.with_name('signals.py'), 'executed_shared_signals.py'),
                         (PROPOSAL, 'executed_proposed_protocol.md')]:
        destination = root / name
        if not destination.exists():
            destination.write_bytes(source.read_bytes())
        if digest(destination) != digest(source):
            raise RuntimeError('Executed model/kernel snapshot mismatch')
    return protocol


def phase_inputs(family, symbol, all_bars, history_funding, stop, spot_cache, factors, mapping):
    """Cut off every source before signal construction, retaining causal warmup."""
    factors = Path(factors)
    kwargs = {}
    if family == 'qqq_risk_transmission':
        data = pd.read_parquet(factors / 'qqq/observations.parquet')
        kwargs['qqq'] = data[(data.source_timestamp >= START) & (data.source_timestamp < END) & (data.available_at <= stop)].copy()
    elif family == 'cpi_acceleration_event':
        data = pd.read_parquet(factors / 'cpi/releases.parquet')
        kwargs['cpi'] = data[(data.release_time >= START) & (data.release_time < END) & (data.available_at <= stop)].copy()
    elif family == 'funding_crowding_fade':
        receipt = history_funding.available_at if 'available_at' in history_funding else history_funding.timestamp
        if (receipt < history_funding.timestamp).any():
            raise ValueError('Actual funding receipt cannot precede settlement')
        available = receipt + pd.Timedelta(minutes=1)
        kwargs['funding'] = history_funding[(history_funding.timestamp >= START) & (available <= stop)].copy()
    elif family == 'taker_flow_drift':
        data = pd.read_parquet(factors / 'flow' / symbol / 'observations.parquet')
        kwargs['flow'] = data[(data.timestamp >= START) & (data.timestamp < END) & (data.available_at <= stop)].copy()
    else:
        data = pd.read_parquet(Path(spot_cache) / symbol / 'bars.parquet')
        kwargs['spot_bars'] = data[(data.timestamp >= START) & (data.timestamp < stop)].copy()
        kwargs['spot_units_per_perpetual_unit'] = mapping['spot_base_units_per_perpetual_quantity_unit']
    return kwargs


def activity(signals, result, family, kwargs, begin, stop):
    changed = signals.ne(signals.shift())
    desired = pd.DataFrame({'long_minutes': signals.gt(0).astype(int), 'short_minutes': signals.lt(0).astype(int)})
    # Reconstruct inventory from actual signed fills, including forced fills.
    # Hourly training/validation equity snapshots cannot measure minute exposure.
    if result.fills.empty:
        quantity = pd.Series(0., index=signals.index)
    else:
        fills = result.fills.copy()
        fills['signed_quantity'] = fills.quantity * fills.side
        inventory = fills.groupby('timestamp').signed_quantity.sum().sort_index().cumsum()
        quantity = inventory.reindex(inventory.index.union(signals.index).sort_values()).ffill().reindex(signals.index).fillna(0.)
        lot = result.instruments[0].lot_size
        quantity = (quantity / lot).round() * lot
    monthly = desired.groupby(desired.index.strftime('%Y-%m')).sum().to_dict('index')
    actual = pd.DataFrame({'long_minutes': quantity.gt(0).astype(int), 'short_minutes': quantity.lt(0).astype(int)})
    stats = {'active_signal_minutes': int(signals.ne(0).sum()), 'entry_intent_count': int((changed & signals.ne(0)).sum()),
             'signal_minutes_by_calendar_month': monthly,
             'actual_position_minutes_by_calendar_month': actual.groupby(actual.index.strftime('%Y-%m')).sum().to_dict('index'),
             'activity_sampling': 'actual signed-fill inventory at each completed target minute; fresh-wallet zero before first fill; funding-clock marks retained separately in risk equity'}
    if family == 'cpi_acceleration_event':
        history = kwargs['cpi'].sort_values('available_at').copy()
        months = pd.PeriodIndex(history.reference_month, freq='M').asi8
        history['consecutive_reference'] = np.r_[False, np.diff(months) == 1][:len(history)]
        dh, dc = history.headline_yoy.diff(), history.core_yoy.diff()
        history['directional_source_event'] = history.consecutive_reference & (
            ((dh >= .1 - 1e-12) & (dc >= .1 - 1e-12)) |
            ((dh <= -.1 + 1e-12) & (dc <= -.1 + 1e-12)))
        events = history if history.empty else history[(history.available_at >= begin) & (history.available_at <= stop)]
        stats['phase_cpi_release_times'] = [str(value) for value in events.release_time]
        stats['phase_cpi_release_count'] = len(events)
        stats['phase_cpi_consecutive_reference_count'] = int(events.consecutive_reference.sum())
        stats['phase_cpi_nonconsecutive_release_times'] = [str(value) for value in events.loc[~events.consecutive_reference, 'release_time']]
        stats['phase_cpi_directional_source_event_count'] = int(events.directional_source_event.sum())
        stats['phase_cpi_directional_source_event_times'] = [str(value) for value in events.loc[events.directional_source_event, 'release_time']]
        stats['phase_cpi_available_times'] = [str(value) for value in events.available_at]
        stats['phase_directional_cpi_release_times'] = [str(row.release_time) for row in events.itertuples()
                                                      if row.available_at in signals.index and signals.loc[row.available_at] != 0]
        stats['cpi_independence'] = 'Count these release timestamps once across all8sleeves, never sum event counts across assets'
    elif family == 'qqq_risk_transmission':
        stats['phase_qqq_actual_sessions_available'] = 0 if kwargs['qqq'].empty else int(kwargs['qqq'].available_at.between(begin, stop).sum())
    return stats


def job(args):
    family, symbol, scale, phase, begin, stop, stress, cache, spot_cache, factors, out = args
    root = Path(cache)
    begin, stop = pd.Timestamp(begin), pd.Timestamp(stop)
    destination = Path(out) / phase / family / f'{scale:g}' / ('stress' if stress else 'base') / symbol
    sources = used_paths(family, symbol, cache, spot_cache, factors)
    fingerprints = {**source_identity(), 'data': {str(path.resolve()): digest(path) for path in sources}}
    locked = json.loads((Path(out) / 'source_lock.json').read_text())
    if any(locked['modules'].get(path) != value for path, value in fingerprints['modules'].items()):
        raise RuntimeError('Worker code differs from blind frozen source')
    if any(locked['data'].get(path) != value for path, value in fingerprints['data'].items()):
        raise RuntimeError('Worker data differs from blind frozen source')
    if (destination / 'metrics.json').exists():
        prior = json.loads((destination / 'metadata.json').read_text())['parameters']
        requested = {'family': family, 'symbol': symbol, 'scale': scale,
                     'phase': phase, 'stress': stress,
                     'requested_start': str(begin), 'requested_end_exclusive': str(stop)}
        if any(prior.get(key) != value for key, value in requested.items()):
            raise RuntimeError('Cached external-factor trial identity mismatch')
        if prior['fingerprints'] != fingerprints:
            raise RuntimeError('Cached external-factor result fingerprint mismatch')
        verify_outputs(destination)
        return dict(family=family, symbol=symbol, scale=scale, phase=phase, stress=stress,
                    path=str(destination), metrics=json.loads((destination / 'metrics.json').read_text()))
    mapping = next(item for item in json.loads((root / 'cross_mapping.json').read_text())['mapping'] if item['spot_symbol'] == symbol)
    spec = Instrument(**next(item for item in json.loads((root / 'instruments.json').read_text()) if item['id'] == mapping['perpetual_instrument_id']))
    spec = replace(spec, maker_bps=10 if stress else 5, taker_bps=10 if stress else 5)
    all_bars = pd.read_parquet(root / symbol / 'bars.parquet')
    all_bars = all_bars[(all_bars.timestamp >= START) & (all_bars.timestamp < stop)].copy()
    if not all_bars.instrument_id.eq(spec.id).all():
        raise ValueError('Native perpetual target identity mismatch')
    history_funding = pd.read_parquet(root / symbol / 'funding.parquet')
    history_funding = history_funding[(history_funding.timestamp >= START) & (history_funding.timestamp <= stop)].copy()
    if not history_funding.instrument_id.eq(spec.id).all():
        raise ValueError('Native funding settlement identity mismatch')
    kwargs = phase_inputs(family, symbol, all_bars, history_funding, stop, spot_cache, factors, mapping)
    signals = build_signals(all_bars, family, scale, **kwargs)
    bars = all_bars[all_bars.timestamp >= begin].copy()
    clock = pd.DatetimeIndex(bars.timestamp + pd.to_timedelta(bars.duration_seconds, unit='s'))
    if not clock.isin(signals.index).all():
        raise ValueError('Signal builder must cover every completed target minute')
    signals = signals.reindex(clock)
    if signals.isna().any():
        raise ValueError('Missing factor directions cannot silently become market decisions')
    signals = signals.astype(np.int8)
    cash_funding = history_funding[history_funding.timestamp >= begin].copy()
    slip = 2 if symbol in ['BTCUSDT', 'ETHUSDT'] else 8 if symbol in ['DOGEUSDT', 'PEPEUSDT'] else 5
    config = SimulationConfig(initial_balances={'binance': 12500}, leverage=1, margin_mode='isolated', max_gross_leverage=1,
                              max_position_pct=.5, slippage_bps=slip * (2 if stress else 1), participation=.025 if stress else .05,
                              execution_delay_bars=1 if stress else 0, record_every=1 if phase == 'holdout' else 60)
    result = Engine([spec], config).run(bars, FixedDirectional(signals, stop), funding=cash_funding)
    verify_ledgers(result)
    reserve = exit_reserve(result)
    active = activity(signals, result, family, kwargs, begin, stop)
    source_manifests = {str(path): json.loads(path.read_text()) for path in sources
                        if path.name in ['source_manifest.json', 'instrument_source_manifest.json', 'coverage.json']}
    _, score = export_result(result, destination, parameters={
        'family': family, 'symbol': symbol, 'scale': scale, 'family_parameters': parameters(family, scale), 'phase': phase, 'stress': stress,
        'fingerprints': fingerprints, 'research_status': 'exploratory reused historical evaluation after19 prior candidates',
        'entry_notional_fraction': .25, 'quantity_policy': 'fixed native entry quantity between direction transitions',
        'native_perpetual_base': spec.base, 'source_base_units_per_quantity': mapping['spot_base_units_per_perpetual_quantity_unit'],
        'warmup': 'only earlier available observations within the same fixed year; all phase source cutoffs enforced before feature building',
        'requested_start': str(begin), 'requested_end_exclusive': str(stop), 'terminal_open_position_count': len(result.positions),
        'terminal_convention': 'actual open inventory marked; no terminal close orders', 'indicative_exit_reserve': reserve,
        'factor_activity': active, 'funding_settlement_cutoff': 'actual timestamp inclusive<=end when supplied',
        'equity_sampling_minutes': 1 if phase == 'holdout' else 60},
        data_source='Actual native Binance perpetual trade/mark/funding plus separately available QQQ, CPI, paired spot or authentic native taker-flow features',
        source_manifest={'sources': source_manifests, 'mapping': mapping})
    score.update(reserve)
    score['liquidation_event_count'] = int(result.events.type.eq('LIQUIDATION').sum()) if 'type' in result.events else 0
    score['factor_activity'] = active
    dump(destination / 'metrics.json', score)
    seal_outputs(destination)
    return dict(family=family, symbol=symbol, scale=scale, phase=phase, stress=stress, path=str(destination), metrics=score)


def choose_training(rows):
    chosen, trials, undefined = {}, [], {}
    for family in FAMILIES:
        ranks = []
        for scale in SCALES:
            group = [row for row in rows if row['family'] == family and row['scale'] == scale and row['phase'] == 'training' and not row['stress']]
            if len(group) != len(SYMBOLS) or {row['symbol'] for row in group} != set(SYMBOLS):
                raise ValueError('Training selection requires all8unique sleeves for every declared scale')
            _, score = aggregate(group)
            sharpe = score.get('sharpe')
            finite = sharpe is not None and np.isfinite(sharpe)
            activity_count = sum(row['metrics']['factor_activity']['active_signal_minutes'] for row in group)
            trials.append({'family': family, 'scale': scale, **score, 'active_sleeve_signal_minutes': activity_count,
                           'undefined_sharpe': not finite})
            ranks.append((float(sharpe) if finite else -np.inf, -abs(scale - 1), scale))
        chosen[family] = max(ranks)[2]
        undefined[family] = all(rank[0] == -np.inf for rank in ranks)
    return {'chosen': chosen, 'training_trials': trials, 'all_training_sharpes_undefined': undefined,
            'selection_basis': 'training rows only; one common scale per family across8sleeves; default1 if all undefined is not positive evidence'}


def bootstrap(frame):
    adjusted = frame.copy()
    adjusted['timestamp'] = pd.to_datetime(adjusted.timestamp, utc=True).dt.as_unit('ns')
    end = adjusted.timestamp.max()
    if end == end.normalize():
        adjusted.loc[adjusted.timestamp == end, 'timestamp'] = end - pd.Timedelta(microseconds=1)
    values = daily_returns(adjusted).dropna().to_numpy()
    if len(values) < 7:
        return {}
    rng = np.random.default_rng(42)
    starts = rng.integers(0, len(values), (10000, int(np.ceil(len(values) / 7))))
    indices = ((starts[:, :, None] + np.arange(7)) % len(values)).reshape(10000, -1)[:, :len(values)]
    totals = np.expm1(np.log1p(values[indices]).sum(axis=1))
    return {'method': 'conditional circular7dayblockbootstrap;10000draws;seed42;reused/adaptive research',
            'cumulative_economic_candidate_count': 24, 'return_interval95': np.quantile(totals, [.025, .975]).tolist(),
            'return_interval_bonferroni24policies': np.quantile(totals, [.05 / 48, 1 - .05 / 48]).tolist(),
            'limitation': 'Conditional resampling cannot remove adaptive reuse, small CPI sample, correlated assets or survivorship bias'}


def summarize(rows, selection, out, protocol):
    root = Path(out)
    summaries = []
    for family, scale in selection['chosen'].items():
        def group(phase, neighbor=scale, stress=False):
            found = [row for row in rows if row['family'] == family and row['scale'] == neighbor and row['phase'] == phase and row['stress'] == stress]
            if len(found) != 8 or {row['symbol'] for row in found} != set(SYMBOLS):
                raise ValueError('Every reported scenario requires all8unique sleeves')
            return found
        validation_rows = [group(f'validation{k}') for k in [1, 2, 3]]
        validations = [aggregate(group_rows)[1] for group_rows in validation_rows]
        validation_return = float(np.prod([1 + score['total_return'] for score in validations]) - 1)
        validation_reserved = float(np.prod([1 + score['return_after_indicative_exit_reserve'] for score in validations]) - 1)
        evaluation_rows = group('holdout')
        frame, score = aggregate(evaluation_rows)
        stressed, stress = aggregate(group('holdout', stress=True))
        months = anchored_months(frame)
        neighbor_scores = {str(neighbor): aggregate(group('holdout', neighbor))[1] for neighbor in SCALES}
        neighbors = {key: value['total_return'] for key, value in neighbor_scores.items()}
        reserved_neighbors = {key: value['return_after_indicative_exit_reserve'] for key, value in neighbor_scores.items()}
        risk_rows = sum((group('holdout', neighbor) for neighbor in SCALES), []) + group('holdout', stress=True) + sum(validation_rows, [])
        liquidations = sum(row['metrics']['liquidation_event_count'] for row in risk_rows)
        positive = sum(row['metrics']['total_return'] > 0 for row in evaluation_rows)
        traded = sum((row['metrics'].get('fill_count') or 0) > 0 for row in evaluation_rows)
        checks = {'validation_positive': validation_return > 0, 'evaluation_positive': score['total_return'] > 0,
                  'jointstress_positive': stress['total_return'] > 0, 'two_positive_months': sum(value > 0 for value in months) >= 2,
                  'sharpe_at_least_half': score.get('sharpe') is not None and score['sharpe'] >= .5,
                  'minute_drawdown_within20pct': score['max_drawdown'] <= .2,
                  'all_neighbors_positive': all(value > 0 for value in neighbors.values()), 'no_liquidations': liquidations == 0,
                  'broad_symbol_success': positive >= 5,
                  'validation_positive_after_indicative_reserve': validation_reserved > 0,
                  'evaluation_positive_after_indicative_reserve': score['return_after_indicative_exit_reserve'] > 0,
                  'jointstress_positive_after_indicative_reserve': stress['return_after_indicative_exit_reserve'] > 0,
                  'all_neighbors_positive_after_indicative_reserve': all(value > 0 for value in reserved_neighbors.values())}
        releases = sorted({timestamp for row in evaluation_rows for timestamp in row['metrics']['factor_activity'].get('phase_cpi_release_times', [])})
        directional_releases = sorted({timestamp for row in evaluation_rows for timestamp in row['metrics']['factor_activity'].get('phase_directional_cpi_release_times', [])})
        phase_liquidations = {
            'training_all_three_scales': sum(row['metrics']['liquidation_event_count'] for row in rows if row['family'] == family and row['phase'] == 'training'),
            **{f'validation{k}_selected_scale': sum(row['metrics']['liquidation_event_count'] for row in group(f'validation{k}')) for k in [1, 2, 3]},
            'evaluation_all_three_scales': sum(row['metrics']['liquidation_event_count'] for neighbor in SCALES for row in group('holdout', neighbor)),
            'evaluation_selected_base_subset': sum(row['metrics']['liquidation_event_count'] for row in evaluation_rows),
            'evaluation_selected_joint_stress': sum(row['metrics']['liquidation_event_count'] for row in group('holdout', stress=True)),
        }
        summaries.append({'family': family, 'chosen_scale': scale, 'parameters': parameters(family, scale),
                          'validation_fold_metrics': validations, 'validation_compounded_return': validation_return,
                          'validation_return_after_indicative_reserve': validation_reserved, 'holdout': score, 'stress': stress,
                          'anchored_month_returns': months, 'neighbor_evaluation_metrics': neighbor_scores,
                          'neighbor_evaluation_returns': neighbors, 'neighbor_returns_after_indicative_reserve': reserved_neighbors,
                          'later_trial_liquidation_events': liquidations, 'positive_symbols': positive, 'traded_symbols': traded,
                          'liquidation_event_counts_by_phase': phase_liquidations,
                          'liquidation_count_note': 'selected evaluation base is a subset of all-three-scale evaluation; do not sum both',
                          'symbols': {row['symbol']: row['metrics'] for row in evaluation_rows},
                          'evaluation_unique_cpi_release_count': len(releases), 'evaluation_unique_cpi_release_times': releases,
                          'evaluation_unique_directional_cpi_release_count': len(directional_releases),
                          'macro_independence_warning': 'Eight exposures to the same release remain one macro announcement',
                          'bootstrap': bootstrap(frame), 'checks': checks, 'historical_hurdles_passed': all(checks.values()),
                          'research_status': 'exploratory reused evaluation after nineteen already examined candidates'})
        destination = root / 'pooled' / family
        destination.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(destination / 'equity.parquet', index=False)
        stressed.to_parquet(destination / 'stress_equity.parquet', index=False)
    result = {'protocol': protocol, 'input_coverage': json.loads((root / 'source_lock.json').read_text())['input_coverage'],
              'families': summaries, 'pass_count': sum(row['historical_hurdles_passed'] for row in summaries),
              'total_trial_count': len(rows), 'research_status': 'exploratory reused historical year; prior nineteen candidates unchanged'}
    dump(root / 'summary.json', result)
    dump(root / 'all_trials.json', rows)
    return result


def report(out, publish='docs/external_factor_results'):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    root, destination = Path(out), Path(publish)
    destination.mkdir(parents=True, exist_ok=True)
    summary = json.loads((root / 'summary.json').read_text())
    for name in ['protocol.json', 'source_lock.json', 'selection.json', 'summary.json', 'all_trials.json']:
        dump(destination / name, json.loads((root / name).read_text()))
    for name in ['executed_run.py', 'executed_signals.py', 'executed_shared_kernel.py', 'executed_shared_signals.py', 'executed_proposed_protocol.md']:
        (destination / name).write_bytes((root / name).read_bytes())
    comparison, equities, provenance, activity_rows = [], [], [], []
    ledgers = {name: [] for name in ['trades', 'funding', 'fills', 'positions']}
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.09,
                        subplot_titles=['Reused evaluation · pooled $100,000 marked equity', 'Drawdown · full minute/funding-event metrics'])
    for item in summary['families']:
        family, scale = item['family'], item['chosen_scale']
        frame = pd.read_parquet(root / 'pooled' / family / 'equity.parquet').set_index('timestamp')
        hourly = frame[['equity', 'funding_pnl', 'trading_fees', 'realized_pnl', 'unrealized_pnl', 'gross_exposure']].resample('1h').last()
        fig.add_trace(go.Scatter(x=hourly.index, y=hourly.equity, name=family), row=1, col=1)
        drawdown = frame.equity / frame.equity.cummax() - 1
        fig.add_trace(go.Scatter(x=hourly.index, y=drawdown.resample('1h').min() * 100, name=family, showlegend=False), row=2, col=1)
        hourly = hourly.reset_index()
        hourly['family'] = family
        equities.append(hourly)
        score = item['holdout']
        comparison.append({'family': family, 'chosen_scale': scale, 'validation': item['validation_compounded_return'],
                           'evaluation': score['total_return'], 'stress': item['stress']['total_return'], 'sharpe': score['sharpe'],
                           'drawdown': score['max_drawdown'], 'profitable_assets': item['positive_symbols'], 'traded_assets': item['traded_symbols'],
                           'funding': score['funding_pnl'], 'fees': score['trading_fees'], 'exit_reserve': score['indicative_exit_reserve_total'],
                           'reserve_return': score['return_after_indicative_exit_reserve'], 'later_trial_liquidations': item['later_trial_liquidation_events'],
                           'unique_evaluation_cpi_releases': item['evaluation_unique_cpi_release_count'],
                           'directional_evaluation_cpi_releases': item['evaluation_unique_directional_cpi_release_count'],
                           'passed': item['historical_hurdles_passed']})
        for scenario in ['base', 'stress']:
            for symbol in SYMBOLS:
                source = root / 'holdout' / family / f'{scale:g}' / scenario / symbol
                metadata = json.loads((source / 'metadata.json').read_text())
                provenance.append({'family': family, 'scale': scale, 'symbol': symbol, 'scenario': scenario,
                                   'fingerprints': metadata['parameters']['fingerprints'], 'source_manifest': metadata['source_manifest'],
                                   'terminal_open_positions': metadata['parameters']['terminal_open_position_count'],
                                   'indicative_exit_reserve': metadata['parameters']['indicative_exit_reserve']})
                active = metadata['parameters']['factor_activity']
                for month, counts in active['actual_position_minutes_by_calendar_month'].items():
                    activity_rows.append({'family': family, 'symbol': symbol, 'scenario': scenario, 'month': month,
                                          'actual_long_minutes': counts['long_minutes'], 'actual_short_minutes': counts['short_minutes'],
                                          'signal_long_minutes': active['signal_minutes_by_calendar_month'][month]['long_minutes'],
                                          'signal_short_minutes': active['signal_minutes_by_calendar_month'][month]['short_minutes'],
                                          'phase_entry_intents': active['entry_intent_count'],
                                          'phase_unique_cpi_releases': active.get('phase_cpi_release_count', 0)})
                for ledger, collection in ledgers.items():
                    table = pd.read_parquet(source / f'{ledger}.parquet')
                    if table.empty:
                        continue
                    table['family'], table['chosen_scale'], table['underlying_symbol'], table['scenario'] = family, scale, symbol, scenario
                    collection.append(table)
    comparison = pd.DataFrame(comparison)
    comparison.to_csv(destination / 'comparison.csv', index=False)
    pd.concat(equities, ignore_index=True).to_csv(destination / 'equity_hourly.csv', index=False)
    pd.DataFrame(activity_rows).to_csv(destination / 'activity_monthly.csv', index=False)
    for ledger, collection in ledgers.items():
        if collection:
            pd.concat(collection, ignore_index=True).to_csv(destination / f'{ledger}_ledger.csv', index=False)
    dump(destination / 'source_provenance.json', provenance)
    fig.add_hline(y=100000, line_dash='dot', row=1, col=1)
    fig.update_layout(template='plotly_dark', height=700, legend=dict(orientation='h', y=-.15))
    display = comparison.copy()
    for key in ['validation', 'evaluation', 'stress', 'drawdown', 'reserve_return']:
        display[key] = display[key].map(lambda value: f'{value:.3%}')
    display['sharpe'] = display.sharpe.map(lambda value: 'undefined' if pd.isna(value) else f'{value:.2f}')
    for key in ['funding', 'fees', 'exit_reserve']:
        display[key] = display[key].map(lambda value: f'${value:,.2f}')
    display['passed'] = display.passed.map({True: 'PASS', False: 'FAIL'})
    chart = fig.to_html(full_html=False, include_plotlyjs=True)
    page = f'''<!doctype html><html><head><meta charset="utf-8"><title>Exploratory external factors</title>
<style>body{{background:#0b1220;color:#dbe7f7;font:15px system-ui;max-width:1450px;margin:35px auto;padding:24px}}p{{line-height:1.6}}table{{border-collapse:collapse;font-size:12px}}td,th{{padding:9px;border-bottom:1px solid #29415b;text-align:right}}a{{color:#6ee7cf}}.panel{{padding:20px;background:#102033;border-radius:12px;margin:20px 0;overflow:auto}}</style></head><body>
<h1>External-factor hypotheses on a reused historical year</h1>
<p><strong>{summary['pass_count']} / 5 candidates pass the unchanged exploratory historical hurdles.</strong> All 400 simulations, all three scales and failures are retained. Nineteen prior candidates already examined this historical year; this cohort cannot demonstrate an untouched test or non-overfit proof. Twenty-four cumulative economic candidates are disclosed. Conditional bootstrap adjustment does not remove adaptive reuse or dependent hypotheses.</p>
<p>Inputs: 250 actual unadjusted vendor QQQ sessions with next-UTC-day availability; 11 archived original-release CPI announcements with one-minute availability; actual native settled funding; synchronized trade/spot premium; and authentic archived aggregate taker-buy/total volumes. QQQ is not an official exchange tape. CPI rendered-response transport and missing October2025 reference data are disclosed. There are 11 macro announcements, not 88 independent observations; the evaluation's unique release/activity counts and monthly exposure minutes are retained. No consensus surprise or social-media input is invented.</p>
<div class="panel">{display.to_html(index=False, border=0)}</div>{chart}
<p>First six months select one common scale by pooled training Sharpe. Three monthly validation folds have fresh wallets. July5–October5 evaluation reuses the already examined year. Each family requires five profitable sleeves, positive validation/evaluation/stress and all neighboring returns with indicative exit reserves, at least two positive anchored months, Sharpe≥0.5, minute drawdown≤20% and no actual liquidation across later cases. Sparse CPI activity does not relax any hurdle.</p>
<p>Eight segregated $12,500 sleeves use native perpetual quantities at25% entry notional, isolated leverage1 and fixed quantity between direction transitions. Actual funding is a separate cash flow; final open inventory remains marked. Indicative exit reserves are diagnostic assumed fees/slippage, not fabricated closing trades or guaranteed volume. The pooled union clock carries sleeve equity only from earlier snapshots. Joint stress doubles fees/slippage, adds one-minute delay and halves participation. Native1000PEPE quantities are unchanged; normalization applies only to the paired spot premium feature. Flow is aggregate aggressive volume, not L2 book OFI.</p>
<p>Current trading rules, surviving-universe selection, vendor corrections, minute-volume execution approximations and missing intraminute liquidation paths limit inference. Charts display hourly points; evaluation risk metrics retain minute and funding clocks. Genuine market shocks can dominate P&L and require separate concentration review.</p>
<p><a href="summary.json">All hurdles and asset outcomes</a> · <a href="all_trials.json">All400trials</a> · <a href="activity_monthly.csv">Monthly activity</a> · <a href="fills_ledger.csv">Fills</a> · <a href="funding_ledger.csv">Funding</a> · <a href="positions_ledger.csv">Open positions</a> · <a href="source_provenance.json">Source identities</a> · <a href="protocol.json">Frozen protocol</a></p></body></html>'''
    (destination / 'report.html').write_text(page)
    return destination / 'report.html'


def execute_jobs(pool, jobs, rows, root):
    for row in pool.map(job, jobs):
        rows.append(row)
        print(row['phase'], row['family'], row['scale'], row['symbol'], 'stress' if row['stress'] else 'base', flush=True)
    dump(Path(root) / 'all_trials_progress.json', rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='data_cache/minute-perpetual-1y')
    parser.add_argument('--spot-cache', default='data_cache/minute-1y')
    parser.add_argument('--factors', default='data_cache/external-factors-1y')
    parser.add_argument('--out', default='results/external-factor-1y')
    parser.add_argument('--publish', default='docs/external_factor_results')
    parser.add_argument('--workers', type=int, default=4, choices=[1, 2, 3, 4])
    parser.add_argument('--freeze-only', action='store_true')
    parser.add_argument('--training-only', action='store_true')
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    protocol = freeze(args.out, args.cache, args.spot_cache, args.factors)
    root = Path(args.out)
    if args.freeze_only:
        print('Protocol, all model defaults, shared kernel, original external sources and all datasets frozen; no Engine simulation dispatched.')
        return
    if args.report_only:
        print(report(args.out, args.publish))
        return
    rows = []
    def task(family, symbol, scale, phase, begin, stop, stress=False):
        return (family, symbol, scale, phase, str(begin), str(stop), stress, args.cache, args.spot_cache, args.factors, args.out)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [task(family, symbol, scale, 'training', START, TRAIN_END) for family in FAMILIES for scale in SCALES for symbol in SYMBOLS]
        execute_jobs(pool, jobs, rows, root)
        selection = choose_training(rows)
        selected = root / 'selection.json'
        if selected.exists() and json.loads(selected.read_text()) != json_safe(selection):
            raise RuntimeError('Frozen training selection changed')
        dump(selected, selection)
        if args.training_only:
            print('Training-only common-scale selection saved; no later phases dispatched.')
            return
        jobs = []
        for family, scale in selection['chosen'].items():
            for k in range(3):
                begin, stop = TRAIN_END + pd.DateOffset(months=k), TRAIN_END + pd.DateOffset(months=k + 1)
                jobs.extend(task(family, symbol, scale, f'validation{k + 1}', begin, stop) for symbol in SYMBOLS)
            for neighbor in SCALES:
                jobs.extend(task(family, symbol, neighbor, 'holdout', EVALUATION_START, END) for symbol in SYMBOLS)
            jobs.extend(task(family, symbol, scale, 'holdout', EVALUATION_START, END, True) for symbol in SYMBOLS)
        execute_jobs(pool, jobs, rows, root)
    if len(rows) != 400:
        raise RuntimeError('All400declared trials required before final report')
    summarize(rows, selection, args.out, protocol)
    print(report(args.out, args.publish))


if __name__ == '__main__':
    main()
