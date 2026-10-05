"""Final no-admissible certificate must reject invented activity or reserve."""
from copy import deepcopy
import pandas as pd
import pytest
from audit.verify_residual_outputs import assert_inactive,compare
from examples.residual_convergence.run import SYMBOLS


def inactive():
    timestamp=pd.date_range('2026-07-05',periods=2,freq='min',tz='UTC')
    equity=pd.DataFrame({'timestamp':timestamp,'cash':100000.,'equity':100000.,'available_margin':100000.})
    zero=['collateral','margin_used','maintenance_margin','long_exposure','short_exposure','gross_exposure',
          'net_exposure','unrealized_pnl','realized_pnl','funding_pnl','trading_fees','slippage_cost','liquidation_fees','turnover']
    for field in zero:equity[field]=0.
    exposure=pd.DataFrame({'timestamp':timestamp,'cash':100000.,'equity':100000.,'gross_exposure':0.,'net_exposure':0.,
                           'frozen_factor_exposure_BTCUSDT':0.,'frozen_factor_exposure_ETHUSDT':0.})
    for symbol in SYMBOLS:
        for prefix in ['quantity','collateral','unrealized']:exposure[f'{prefix}_{symbol}']=0.
    tables={name:pd.DataFrame() for name in ['fills','funding','trades','positions','events']};tables['equity']=equity
    return tables,exposure


def test_empty_schema_ledgers_and_cash_only_observer_are_valid():
    tables,exposure=inactive();assert_inactive(tables,exposure)


@pytest.mark.parametrize('ledger',['fills','funding','trades','positions','events'])
def test_activity_cannot_hide_inside_cash_only_certificate(ledger):
    tables,exposure=inactive();tables[ledger]=pd.DataFrame({'unexpected_activity':[1]})
    with pytest.raises(AssertionError,match='Unexpected'):assert_inactive(tables,exposure)


def test_zero_equity_pnl_does_not_hide_reserve_or_unhedged_native_inventory():
    tables,exposure=inactive();tables['equity'].loc[1,'margin_used']=5.
    with pytest.raises(AssertionError,match='margin_used'):assert_inactive(tables,exposure)
    tables,exposure=inactive();exposure.loc[1,'quantity_PEPEUSDT']=1000.
    with pytest.raises(AssertionError,match='quantity'):assert_inactive(tables,exposure)


def test_model_admissibility_and_failed_diagnostics_require_exact_identity():
    expected={'eligible':False,'diagnostics':{'half_life_hours':100.,'failed_checks':['intraday_half_life','conditional_adf']}}
    changed=deepcopy(expected);changed['eligible']=True
    with pytest.raises(AssertionError):compare(changed,expected)
    changed=deepcopy(expected);changed['diagnostics']['failed_checks']=['conditional_adf']
    with pytest.raises(AssertionError):compare(changed,expected)


def test_later_documentation_commit_can_replicate_identical_preregistered_source(monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from audit import verify_residual_outputs as auditor
    blob=b'identical preregistered execution source'
    expected=hashlib.sha256(blob).hexdigest();calls=[]
    def git(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=blob,returncode=0)
    monkeypatch.setattr(auditor.subprocess,'run',git)
    auditor.verify_source_anchor({'sources':{'examples/residual_convergence/run.py':expected}})
    later='f'*40;auditor.verify_execution_commit(later)
    assert calls[-1]==['git','merge-base','--is-ancestor',auditor.PREREG,later]
    with pytest.raises(AssertionError,match='differs from preregistration'):
        auditor.verify_source_anchor({'sources':{'examples/residual_convergence/run.py':'0'*64}})


def test_unrelated_or_missing_execution_commit_rejected(monkeypatch):
    from types import SimpleNamespace
    from audit import verify_residual_outputs as auditor
    monkeypatch.setattr(auditor.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=1))
    with pytest.raises(AssertionError,match='descend'):
        auditor.verify_execution_commit('b'*40)
    with pytest.raises(AssertionError,match='full execution commit'):
        auditor.verify_execution_commit('uncommitted')
