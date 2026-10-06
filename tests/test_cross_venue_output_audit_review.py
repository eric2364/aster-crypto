"""Independent reviewer adversaries and cohort-specific admission contract."""
from dataclasses import asdict
from fractions import Fraction
import copy
import pandas as pd
import pytest
from audit import verify_cross_venue_outputs as financial
from audit import verify_cross_venue_no_admission as a
from test_cross_venue_execution import specs,features,START
from test_cross_venue_output_audit import fixture,run


def pair(symbol='DOGEUSDT'):
    rows={s.id:asdict(s) for s in specs()}
    return rows[a.iid('binance',symbol)],rows[a.iid('bybit',symbol)]


def test_recorded_financial_replay_scope_does_not_prove_absent_eligible_fills():
    # Coherent exports made with zero Bybit capacity, against a high-capacity source.
    # There are NO recorded Bybit fills to test; observed-fill cash replay alone
    # cannot prove that a pending executable leg was not omitted.
    omitted=fixture(partial=True);eligible=fixture(partial=False)
    native=a.iid('bybit','PEPEUSDT')
    omitted[2][native]['volume']=eligible[2][native].volume.to_numpy()
    state,_=run(omitted)
    assert state.q[native]==0 and omitted[0]['fills'].exchange.eq('binance').all()


def test_rational_common_grid_is_intersection_not_maximum():
    b,y=pair();b['lot_size']=.03;y['lot_size']=.02
    assert a.common_grid(b,y)==Fraction(3,50)
    row=features(gap=.001).loc[START+pd.Timedelta(minutes=5)]
    result=a.admission(row,b,y,'DOGEUSDT')
    assert result['eligible'] and result['native_quantity']==12.48
    assert result['direction']==1
    assert result['stress_roundtrip_cost']==pytest.approx(2*12.48*100*(.0026+.0028))


def test_native_pepe_bundle_quantity_and_both_venue_costs():
    b,y=pair('PEPEUSDT');row=features(active='PEPEUSDT',gap=.001).loc[START+pd.Timedelta(minutes=5)]
    result=a.admission(row,b,y,'PEPEUSDT')
    assert result['native_quantity']==125000 and result['common_grid']=='100'
    assert result['stress_roundtrip_cost']==pytest.approx(13.5)
    assert result['forecast_carry']==pytest.approx(210.)
    assert result['direction']==1 and result['eligible']
    bad=copy.deepcopy(y);bad['base']='PEPE'
    with pytest.raises(AssertionError):a.admission(row,b,bad,'PEPEUSDT')


@pytest.mark.parametrize('gap,allowed',[(.00009,False),(.0001,True),(-.0001,True),(0.,False)])
def test_fixed_cost_admission_not_relaxed_or_net_of_hedge_fees(gap,allowed):
    row=features(gap=gap).loc[START+pd.Timedelta(minutes=5)]
    b,y=pair();result=a.admission(row,b,y,'DOGEUSDT')
    assert result['eligible'] is allowed
    if gap:assert result['direction']==(1 if gap>0 else -1)


def test_zero_cohort_certificate_rejects_true_hourly_admission(monkeypatch):
    begin=START-pd.Timedelta(minutes=5);stop=begin+pd.Timedelta(days=8)
    index=pd.date_range(begin+pd.Timedelta(minutes=5),stop-pd.Timedelta(days=7),freq='h',inclusive='left')
    frame=pd.DataFrame(index=index)
    for s in a.SYMBOLS:
        for v in a.VENUES:
            frame[f'valid_{v}_{s}']=True;frame[f'price_{v}_{s}']=.01 if s=='PEPEUSDT' else 100.
            frame[f'yield_{v}_{s}']=.001 if s=='DOGEUSDT' and v=='bybit' else 0.
    instruments={s.id:asdict(s) for s in specs()}
    with pytest.raises(AssertionError,match='Eligible economic admission'):
        a.phase_checks(frame,instruments,('synthetic',begin,stop,False,'primary'))
    frame['yield_bybit_DOGEUSDT']=.00001
    result=a.phase_checks(frame,instruments,('synthetic',begin,stop,False,'primary'))
    assert result['hourly_clocks_checked']==24 and result['pair_decisions_checked']==192
    assert result['economic_admission_count']==0
    assert result['rejection_counts']=={'stress_cost_filter':24,'zero_gap':168}


def test_no_admission_opening_minima_and_undeclared_units_fail():
    row=features(gap=.001).loc[START+pd.Timedelta(minutes=5)]
    b,y=pair();b['min_notional']=1251
    assert a.admission(row,b,y,'DOGEUSDT')['reason']=='opening_notional_minimum'
    b,y=pair();y['min_quantity']=13
    assert a.admission(row,b,y,'DOGEUSDT')['reason']=='common_quantity_minimum'
    b,y=pair();y['multiplier']=1000
    with pytest.raises(AssertionError):a.admission(row,b,y,'DOGEUSDT')


def test_cohort_scope_refuses_inventory_even_if_equity_pools_flat(tmp_path):
    for name in ('fills','trades','funding','matched_entries','unmatched','events'):
        pd.DataFrame().to_parquet(tmp_path/(name+'.parquet'))
    pd.DataFrame({'quantity':[1.]}).to_parquet(tmp_path/'positions.parquet')
    with pytest.raises(AssertionError,match='positions'):a.zero_activity(tmp_path)


def test_conservative_union_includes_float_ideal_rounding_to_native_minimum():
    b,y=pair();row=features(gap=.001).loc[START+pd.Timedelta(minutes=5)].copy()
    for v in a.VENUES:row[f'price_{v}_DOGEUSDT']=3.
    # Exact1250/3 is below this grid/minimum; floatideal rounds onto it.
    for spec in (b,y):spec['lot_size']=spec['min_quantity']=416.6666666666667
    result=a.admission(row,b,y,'DOGEUSDT')
    assert result['exact_native_quantity']==0
    assert result['float_ideal_native_quantity']==416.6666666666667
    assert result['eligible'] is True


def test_opening_min_notional_keeps_coordinator_epsilon():
    b,y=pair();row=features(gap=.001).loc[START+pd.Timedelta(minutes=5)]
    for spec in (b,y):spec['min_notional']=1250.0000000005
    assert a.admission(row,b,y,'DOGEUSDT')['eligible'] is True


def test_unit_upper_bound_refuses_high_cost_pass_even_when_native_minimum_blocks():
    b,y=pair();row=features(gap=.001).loc[START+pd.Timedelta(minutes=5)]
    y['min_quantity']=1000
    assert a.admission(row,b,y,'DOGEUSDT')['eligible'] is False
    assert a.unit_cost_upper_bound(row,'DOGEUSDT')['eligible'] is True
