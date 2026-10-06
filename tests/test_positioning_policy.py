"""Synthetic policy evidence; no production implementation is invoked."""
from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from audit import verify_positioning_policy as p

B=pd.Timestamp('2026-04-05',tz='UTC');E=B+pd.Timedelta(hours=6)


def fixture(eligible=False):
    clocks=pd.date_range(B+pd.Timedelta(minutes=1),E,freq='min',inclusive='left');ids=[p.iid(s) for s in p.SYMBOLS]
    features={i:pd.DataFrame(dict(price=100.,price_return_1h=-.02 if eligible else 0.,price_return_15m=.01 if eligible else 0.,quantity_change_1h=-.03 if eligible else 0.,quantity_change_5m=0.,valid=True,metric_available_at=clocks-pd.Timedelta(minutes=1),price_available_at=clocks,metric_age_seconds=60.,instrument_id=i),index=clocks) for i in ids}
    q={t:dict.fromkeys(ids,0.) for t in clocks};account={t:dict(binance_equity=100000.,binance_available_margin=100000.,binance_margin_used=0.,binance_gross_exposure=0.,maintenance_margin=0.) for t in clocks}
    detail={t:dict(marks=dict.fromkeys(ids,100.),average_prices=dict.fromkeys(ids,0.),liquidation_before_callback=False) for t in clocks}
    specs=[dict(id=i,lot_size=1.,tick_size=.01,min_quantity=1.,min_notional=5.,taker_bps=5.,liquidation_bps=10.,maintenance_rate=.005) for i in ids]
    config=dict(slippage_bps=8.,max_gross_leverage=.5,max_position_pct=.25,execution_delay_bars=0,latency_ms=0)
    return [features,{'events':[dict(timestamp=E-pd.Timedelta(minutes=10),type='TERMINAL_EXIT_REQUEST',generation=0),dict(timestamp=E-pd.Timedelta(minutes=10),type='TERMINAL_FLAT',generation=0)]},q,account,detail,specs,[],[],B,E,config,[]]


def entry_fixture():
    x=fixture();features,diagnostics,q,account,detail,specs,events,fills,b,e,config,completed=x
    t=B+pd.Timedelta(minutes=5);i=p.iid('BTCUSDT');targets={j:0. for j in features};targets[i]=100.
    for field,val in [('price_return_1h',-.02),('price_return_15m',.01),('quantity_change_1h',-.03)]:features[i].loc[t,field]=val
    tx=dict(timestamp=t,type='TARGET_SUBMITTED',generation=1,transition='ENTERING',targets=targets,deadline=t+pd.Timedelta(minutes=5),order_ids=['O1'])
    terminal_events=diagnostics['events']
    diagnostics['events']=[dict(timestamp=t,type='EVENT_PROPOSAL',generation=0,symbol='BTCUSDT',eligible_symbols=['BTCUSDT']),tx]
    events.extend([dict(timestamp=t,type='ORDER_SUBMITTED',order_id='O1',instrument_id=i,quantity=100.,side=1,active_at=t,tif='GTC',order_type='market',reduce_only=False),dict(timestamp=t,type='ORDER_ACCEPTED',order_id='O1')])
    f=t+pd.Timedelta(minutes=1);observed=f+pd.Timedelta(minutes=1)
    events.append(dict(timestamp=f,type='ORDER_FILLED',order_id='O1'));fills.append(dict(timestamp=f,order_id='O1',instrument_id=i,quantity=100.,price=100.))
    for clock in q:
        if clock>=observed:q[clock][i]=100.;detail[clock]['average_prices'][i]=100.;account[clock]['binance_available_margin']=90000.;account[clock]['binance_margin_used']=account[clock]['binance_gross_exposure']=10000.;account[clock]['maintenance_margin']=50.
    diagnostics['events'].append(dict(timestamp=observed,type='ENTRY_COMPLETE',generation=1,completed_at=f,observed_completed_at=observed,instrument_id=i,targets=targets,average_entry_price=100.))
    diagnostics['events'].extend(terminal_events)
    diagnostics['events'].sort(key=lambda r:r['timestamp'])
    return x,t,observed


def test_all_idle_clocks_and_truthful_scope():
    result=p.verify_policy(*fixture())
    assert result['all_callback_clocks_examined'] and result['callback_clocks']==359
    assert result['resolved_idle_review_clocks_checked']>0 and result['recorded_proposals']==0
    assert result['full_cleanup_state_reconstruction_passed'] is False and result['all_unlogged_abort_transitions_proved'] is False


def test_omitted_eligible_review_detected():
    with pytest.raises(AssertionError,match='Omitted/duplicate'):p.verify_policy(*fixture(True))


@pytest.mark.parametrize('delay',[6,11])
def test_strict_metric_boundary_and_price_age(delay):
    x=fixture();f=x[0][p.iid('BTCUSDT')];t=f.index[50]
    f.loc[t,'metric_available_at']=t
    assert p.feature_at(f,t) is None
    f.loc[t,'metric_available_at']=t-pd.Timedelta(minutes=5);assert p.feature_at(f,t) is not None
    f.loc[t,'metric_available_at']=t-pd.Timedelta(minutes=5,seconds=1);assert p.feature_at(f,t) is None
    f.loc[t,'metric_available_at']=t-pd.Timedelta(minutes=1);f.loc[t,'price_available_at']=t-pd.Timedelta(minutes=3);assert p.feature_at(f,t) is None


@pytest.mark.parametrize('budget,price,step,expected',[(10000,100,1,100),(100,3,.1,33.3),(10,11,1,0),(10000,.003,1,3333333)])
def test_exact_native_lot_floor(budget,price,step,expected):
    assert p.quantity(budget,price,step)==expected
    assert p.quantity(budget,price,step)*price<=budget


@pytest.mark.parametrize('mutation',['priority','target','deadline','side','reduce','clock'])
def test_logged_entry_adversaries(mutation):
    x,t,obs=entry_fixture();logs=x[1]['events']
    if mutation=='priority':logs[0]['symbol']='ETHUSDT'
    if mutation=='target':logs[1]['targets'][p.iid('BTCUSDT')]=101.
    if mutation=='deadline':logs[1]['deadline']+=pd.Timedelta(minutes=1)
    if mutation=='side':x[6][0]['side']=-1
    if mutation=='reduce':x[6][0]['reduce_only']=True
    if mutation=='clock':x[6][0]['active_at']+=pd.Timedelta(minutes=1)
    with pytest.raises(AssertionError):p.verify_policy(*x)


def test_entry_deadline_timeout_is_not_silent():
    x,t,obs=entry_fixture();x[1]['events']=x[1]['events'][:2];x[6]=x[6][:2];x[7]=[]
    for q in x[2].values():q[p.iid('BTCUSDT')]=0.
    with pytest.raises(AssertionError,match='timeout'):p.verify_policy(*x)


def test_counterfeit_entry_completion_precedes_fill():
    x,t,obs=entry_fixture();x[1]['events'][2]['timestamp']=t+pd.Timedelta(minutes=1)
    with pytest.raises(AssertionError,match='actually filled'):p.verify_policy(*x)


def test_mandatory_held_exit_log_without_order_is_rejected():
    x,t,obs=entry_fixture();when=obs+pd.Timedelta(minutes=1);x[0][p.iid('BTCUSDT')].loc[when,'price']=97.
    x[1]['events'].append(dict(timestamp=when,type='EPISODE_EXIT',generation=1,reason='closed_price_adverse_two_percent'))
    x[1]['events'].sort(key=lambda r:r['timestamp'])
    with pytest.raises(AssertionError,match='omitted actual'):p.verify_policy(*x)


def test_missing_held_exit_and_holding_drift_are_rejected():
    x,t,obs=entry_fixture();when=obs+pd.Timedelta(minutes=1);x[0][p.iid('BTCUSDT')].loc[when,'price']=97.
    with pytest.raises(AssertionError,match='Omitted mandatory'):p.verify_policy(*x)
    x,t,obs=entry_fixture();x[2][obs+pd.Timedelta(minutes=1)][p.iid('BTCUSDT')]=101.
    with pytest.raises(AssertionError,match='unexpected holding'):p.verify_policy(*x)


def test_native_identity_and_counterfeit_closed_export():
    x=fixture();x[0][p.iid('PEPEUSDT').replace('1000PEPE','PEPE')]=x[0].pop(p.iid('PEPEUSDT'))
    with pytest.raises(AssertionError,match='eight native'):p.verify_policy(*x)
    x=fixture();x[-1]=[dict(generation=1)]
    with pytest.raises(AssertionError,match='invented'):p.verify_policy(*x)


def closed_fixture():
    x,t,obs=entry_fixture();features,diagnostics,q,account,detail,specs,events,fills,b,e,config,completed=x
    i=p.iid('BTCUSDT');final=obs-pd.Timedelta(minutes=1);when=final+pd.Timedelta(hours=4);done=when+pd.Timedelta(minutes=2)
    targets=dict.fromkeys(features,0.)
    rows=[dict(timestamp=when,type='EPISODE_EXIT',generation=1,reason='four_hour_hold'),dict(timestamp=when,type='TARGET_SUBMITTED',generation=1,transition='EXITING',targets=targets,deadline=when+pd.Timedelta(minutes=5),order_ids=['O2'])]
    events.extend([dict(timestamp=when,type='ORDER_SUBMITTED',order_id='O2',instrument_id=i,quantity=100.,side=-1,active_at=when,tif='GTC',order_type='market',reduce_only=True),dict(timestamp=when,type='ORDER_ACCEPTED',order_id='O2'),dict(timestamp=when+pd.Timedelta(minutes=1),type='ORDER_FILLED',order_id='O2')])
    fills.append(dict(timestamp=when+pd.Timedelta(minutes=1),order_id='O2',instrument_id=i,quantity=100.,price=100.))
    closure=dict(generation=1,symbol='BTCUSDT',instrument_id=i,submitted_at=t,entry_completed_at=final,exit_reason='four_hour_hold',average_entry_price=100.,closed_at=when+pd.Timedelta(minutes=1),observed_closed_at=done,failed=False)
    rows.extend([dict(timestamp=done,type='EPISODE_CLOSED',**closure),dict(timestamp=done,type='NORMAL_FLAT',generation=1,cooldown_until=done+pd.Timedelta(hours=1))]);completed.append(closure)
    for clock in q:
        if clock>=done:
            q[clock][i]=0.;detail[clock]['average_prices'][i]=0.;account[clock].update(binance_available_margin=100000.,binance_margin_used=0.,binance_gross_exposure=0.,maintenance_margin=0.)
    diagnostics['events'].extend(rows);diagnostics['events'].sort(key=lambda r:r['timestamp'])
    return x


def test_successful_lifecycle_uses_actual_final_fill_hold_and_close():
    result=p.verify_policy(*closed_fixture())
    assert result['actual_completed_entries']==result['actual_completed_closed_episodes']==1
    assert result['recorded_proposals']==result['eligible_idle_proposals_checked']==1


def test_terminal_request_cannot_be_omitted_even_when_idle():
    x=fixture();x[1]['events']=[]
    with pytest.raises(AssertionError,match='terminal request'):p.verify_policy(*x)


def test_four_hour_exit_cannot_be_early_or_missing_completed_episode():
    x=closed_fixture();exitrow=next(r for r in x[1]['events'] if r['type']=='EPISODE_EXIT');exitrow['reason']='invalid_or_stale_feature'
    with pytest.raises(AssertionError,match='exit reason'):p.verify_policy(*x)
    x=closed_fixture();x[1]['events']=[r for r in x[1]['events'] if r['type']!='EPISODE_CLOSED'];x[-1]=[]
    with pytest.raises(AssertionError,match='omitted completed episode'):p.verify_policy(*x)


def test_unowned_already_filled_event_or_dormant_inventory_requires_abort():
    x=fixture();i=p.iid('BTCUSDT');t=B+pd.Timedelta(minutes=2)
    x[6]=[dict(timestamp=t,type='ORDER_SUBMITTED',order_id='foreign',instrument_id=i),dict(timestamp=t,type='ORDER_ACCEPTED',order_id='foreign'),dict(timestamp=t,type='ORDER_FILLED',order_id='foreign')]
    with pytest.raises(AssertionError,match='unowned'):p.verify_policy(*x)
    x=fixture();x[2][t][p.iid('DOGEUSDT')]=1.
    with pytest.raises(AssertionError,match='unexpected native'):p.verify_policy(*x)


def test_standalone_cli_bootstraps_repo_and_never_writes_on_missing_inputs(tmp_path):
    import subprocess,sys
    from pathlib import Path
    cert=tmp_path/'not-written.json'
    command=[sys.executable,str(Path(p.__file__).resolve())]
    for name in ('perp-cache','metrics-cache','out','feature-audit','financial-audit'):command.extend(['--'+name,str(tmp_path/('missing-'+name))])
    command.extend(['--source-anchor','290c9b755290a382d696ac86f83a1fbec7ee1fe5','--input-anchor','7aa7830878821ed4819f2b2feac51cbd9fe1e82c','--certificate',str(cert)])
    result=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode!=0 and 'FileNotFoundError' in result.stderr
    assert 'ModuleNotFoundError' not in result.stderr and not cert.exists()


def test_fake_flat_cooldowns_cannot_mask_idle_eligibility():
    for kind in ('NORMAL_FLAT','ABORT_FLAT'):
        x=fixture();t=B+pd.Timedelta(minutes=2)
        x[1]['events'].insert(0,dict(timestamp=t,type=kind,generation=0,cooldown_until=t+pd.Timedelta(hours=1)))
        with pytest.raises(AssertionError,match='cooldown lacks'):p.verify_policy(*x)
