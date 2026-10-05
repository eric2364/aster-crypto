"""Independent reserve verifier rejects cash-conserving risk artifacts."""
import pandas as pd
import pytest
from audit.verify_corrected_external import reserve_replay


def ledger():
    t=pd.Timestamp('2026-01-01',tz='UTC');u=t+pd.Timedelta(minutes=1)
    metadata={'instruments':[{'id':'p','market_type':'perpetual','maintenance_rate':.005,'taker_bps':0,'liquidation_bps':0}],
              'engine':{'leverage':1}}
    fills=pd.DataFrame({'timestamp':[t,u],'instrument_id':'p','side':[1,-1],'quantity':[1.,.95],
                        'price':[100.,95.],'realized_pnl':[0.,-4.75],'exit_reason':'strategy'})
    events=pd.DataFrame({'timestamp':[t,u],'type':'FEE','instrument_id':'p'})
    tables={'fills':fills,'funding':pd.DataFrame(),'events':events,
            'equity':pd.DataFrame({'timestamp':[t,u],'margin_used':[100.,5.]}),
            'positions':pd.DataFrame({'instrument_id':['p'],'quantity':[.05],'average_price':[100.],'collateral':[5.]})}
    return metadata,tables


def test_proportional_reserve_replay_at_every_snapshot():
    metadata,tables=ledger();result=reserve_replay(metadata,tables)
    assert result=={'partial_exits':1,'liquidations':0}


def test_inactive_trial_accepts_empty_schema_ledgers_and_checks_zero_margin():
    metadata,tables=ledger()
    for name in ['fills','funding','events','positions']:tables[name]=pd.DataFrame()
    tables['equity']['margin_used']=0.
    assert reserve_replay(metadata,tables)=={'partial_exits':0,'liquidations':0}
    tables['equity'].loc[0,'margin_used']=1.
    with pytest.raises(AssertionError,match='Every-snapshot'):reserve_replay(metadata,tables)


def test_prior_closed_loss_residual_allocation_rejected_even_with_correct_cash():
    metadata,tables=ledger()
    tables['equity'].loc[1,'margin_used']=.25
    tables['positions'].loc[0,'collateral']=.25
    with pytest.raises(AssertionError,match='Every-snapshot'):reserve_replay(metadata,tables)


def test_healthy_residual_forced_close_rejected():
    metadata,tables=ledger();t=tables['fills'].timestamp.iloc[-1]
    forced=pd.DataFrame({'timestamp':[t],'instrument_id':['p'],'side':[-1],'quantity':[.05],
                         'price':[95.],'realized_pnl':[-.25],'exit_reason':['liquidation']})
    tables['fills']=pd.concat([tables['fills'],forced],ignore_index=True)
    tables['events']=pd.concat([tables['events'],pd.DataFrame({'timestamp':[t,t],'type':['FEE','LIQUIDATION'],
                                                              'instrument_id':['p','p'],'mark_price':[95.,95.]})],ignore_index=True)
    with pytest.raises(AssertionError,match='healthy corrected reserve'):reserve_replay(metadata,tables)
