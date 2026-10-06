"""Independent candidate28 native long/cash financial reconstruction.

No imports from the engine, portfolio, strategy, signals or frozen runner.
Arithmetic adapted from the independently audited cross-venue verifier;
no strategy/runner/core imports and no historical evaluation on import.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import numpy as np
import pandas as pd

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
VENUES=('binance',)
FAMILY='confirmed_native_position_unwind_rebound'
SOURCE_ANCHOR='290c9b755290a382d696ac86f83a1fbec7ee1fe5'
PREREG='docs/positioning_preregistration'
FEATURE_AUDITOR='audit/verify_positioning_features.py'
DELAYS={'baseline':6,'delayed':11}
START=pd.Timestamp('2025-10-05',tz='UTC');VALID=pd.Timestamp('2026-04-05',tz='UTC');EVAL=pd.Timestamp('2026-07-05',tz='UTC');END=pd.Timestamp('2026-10-05',tz='UTC')
PHASES=[(f'validation{k+1}',VALID+pd.DateOffset(months=k),VALID+pd.DateOffset(months=k+1),False) for k in range(3)]+[('evaluation',EVAL,END,False),('evaluation_stress',EVAL,END,True)]
LEDGERS=('equity','fills','trades','funding','events','positions')
OUTPUTS=tuple([f'{n}.{e}' for n in LEDGERS for e in ('csv','parquet')]+['metadata.json','metrics.json','source_manifest.json','quality.json','exposure.csv','exposure.parquet','leg_contributions.csv','strategy_diagnostics.json','completed_baskets.json','proposal_ledger.json','rejections.json','terminal_orders.json','daily_returns.csv','completed_episodes.json'])
EPS=1e-10

from audit import verify_funding_rank_outputs as arithmetic
check=arithmetic.check;sha=arithmetic.sha;read=arithmetic.read;iid=arithmetic.iid
close=arithmetic.close;compare=arithmetic.compare;csv_hash=arithmetic.csv_hash
Replay=arithmetic.Replay;adverse=arithmetic.adverse
reference_metrics=arithmetic.reference_metrics;verify_csv=arithmetic.verify_csv
configuration=arithmetic.configuration;endpoint_returns=arithmetic.endpoint_returns


# Independent reference event replay with additional pre-callback provenance.
def reconstruct(tables,exposure,bars,source_funding,specs,config,begin,stop):
    state=Replay(specs,config);ids=state.ids;equity=tables['equity']
    expected_clock=pd.date_range(begin,stop,freq='min').as_unit('ns').union(pd.DatetimeIndex(source_funding.timestamp).as_unit('ns').unique()).sort_values()
    check(pd.DatetimeIndex(equity.timestamp).as_unit('ns').equals(expected_clock),'Every source minute and settlement clock required')
    check(pd.DatetimeIndex(exposure.timestamp).as_unit('ns').equals(expected_clock) and len(exposure.columns)==len(state.exposure())+1,'Observer clock/63-field schema differs')
    fills=tables['fills'].to_dict('records') if len(tables['fills']) else []
    funded=tables['funding'].to_dict('records') if len(tables['funding']) else []
    check([r['fill_id'] for r in fills]==list(range(1,len(fills)+1)),'Fill identities/order differ')
    fg=defaultdict(list);sg=defaultdict(list);pg={}
    for r in fills:fg[pd.Timestamp(r['timestamp'])].append(r)
    for r in funded:
        key=(pd.Timestamp(r['timestamp']),r['instrument_id']);check(key not in pg,'Duplicate funding cash flow');pg[key]=r
    for r in source_funding.to_dict('records'):sg[pd.Timestamp(r['timestamp'])].append(r)
    check(set(fg)<=set(expected_clock) and {k[0] for k in pg}<=set(expected_clock),'Fill/payment outside source clocks')
    arrays={i:{k:bars[i][k].to_numpy() for k in ('open','volume','mark_open','mark_price')} for i in ids}
    for i in ids:check(pd.DatetimeIndex(bars[i].timestamp).as_unit('ns').equals(pd.date_range(begin,stop,freq='min',inclusive='left').as_unit('ns')),'Phase grid differs')
    event_rows=tables['events'].to_dict('records') if len(tables['events']) else []
    orders={};cancelled={};accepted={};filled_events=defaultdict(list);liq_events=defaultdict(list)
    for sequence,event in enumerate(event_rows):
        event['_sequence']=sequence
        typ=event['type'];clock=pd.Timestamp(event['timestamp'])
        check(begin<=clock<=stop,'Event outside phase')
        if typ=='ORDER_SUBMITTED':
            oid=event['order_id'];check(oid not in orders,'Order identity reused');orders[oid]=event
            check(event['order_type']=='market' and event['tif']=='GTC' and not event['post_only'],'Nonpacket order type')
            close(event['quantity'],round(event['quantity']/state.specs[event['instrument_id']]['lot_size'])*state.specs[event['instrument_id']]['lot_size'],'Submitted native lot')
            active=pd.Timestamp(event['active_at']);check(active==clock+pd.Timedelta(minutes=config['execution_delay_bars']),'Order activation clock differs')
        elif typ=='ORDER_ACCEPTED':
            check(event['order_id'] in orders,'Acceptance before submission');accepted[event['order_id']]=sequence
        elif typ=='ORDER_CANCELLED':cancelled[event['order_id']]=sequence
        elif typ in ('ORDER_FILLED','ORDER_PARTIALLY_FILLED'):filled_events[event['order_id']].append(event)
        elif typ=='LIQUIDATION':liq_events[(clock,event['instrument_id'])].append(event)
    fee_events=[r for r in event_rows if r['type']=='FEE']
    check(len(fee_events)==len(fills),'Fee event count differs')
    for event,fill in zip(fee_events,fills):
        check(pd.Timestamp(event['timestamp'])==pd.Timestamp(fill['timestamp']) and event['instrument_id']==fill['instrument_id'],'Fee event identity differs')
        close(event['amount'],-fill['fee'],'Fee event cash amount')
    funding_events=[r for r in event_rows if r['type']=='FUNDING_PAYMENT']
    check(len(funding_events)==len(funded),'Funding event count differs')
    for event,payment in zip(funding_events,funded):
        check(pd.Timestamp(event['timestamp'])==pd.Timestamp(payment['timestamp']) and event['instrument_id']==payment['instrument_id'],'Funding cash event identity differs')
        close(event['amount'],payment['funding_payment'],'Funding event cash amount')
        check(event['rate']==payment['funding_rate'],'Funding event rate differs')
    order_filled=defaultdict(float);consumed_payments=set();preopen={};reconstructed_equity=[];reconstructed_exposure=[]
    def liquidation(clock,remaining):
        candidates=state.liquidation_ids()
        for i in candidates:
            check(remaining and remaining[0]['instrument_id']==i and remaining[0]['exit_reason']=='liquidation','Missing/incorrect venue-local forced liquidation')
            r=remaining.pop(0);quantity=abs(state.q[i]);side=-1 if state.q[i]>0 else 1
            close(r['quantity'],quantity,'Forced full native close');check(r['side']==side,'Wrong liquidation side')
            check(r['reference_price']==state.mark[i],'Liquidation reference differs from source stage mark')
            close(r['price'],adverse(state.mark[i],side,state.specs[i],config),'Forced adverse tick price')
            state.fill(r)
            events=liq_events[(clock,i)];check(events,'Missing liquidation event');event=events.pop(0)
            close(event['mark_price'],r['reference_price'],'Liquidation event mark');close(event['execution_price'],r['price'],'Liquidation event price');close(event['cash_after'],state.cash[state.specs[i]['exchange']],'Liquidation local cash')
    live_events=defaultdict(list)
    for event in event_rows:
        if event['type'] in ('ORDER_ACCEPTED','ORDER_FILLED','ORDER_REJECTED','ORDER_CANCELLED') and not (event['type']=='ORDER_CANCELLED' and event.get('reason')=='end_of_data'):
            live_events[pd.Timestamp(event['timestamp'])].append(event)
    live=set()
    for number,clock in enumerate(expected_clock):
        for event in live_events.get(clock,[]):
            if event['type']=='ORDER_ACCEPTED':live.add(event['order_id'])
            else:live.discard(event['order_id'])
        state.live_order_count=len(live)
        remaining=list(fg.get(clock,[]));elapsed=(clock-begin).total_seconds()/60;aligned=elapsed==int(elapsed)
        if aligned and elapsed>0:
            index=int(elapsed)-1
            for i in ids:state.mark[i]=float(arrays[i]['mark_price'][index])
        liquidation(clock,remaining)
        for event in sg.get(clock,[]):state.mark[event['instrument_id']]=float(event['mark_price'])
        liquidation(clock,remaining)
        for event in sg.get(clock,[]):
            key=(clock,event['instrument_id']);payment=pg.get(key)
            state.funding_event(event,payment)
            if payment is not None:consumed_payments.add(key)
        liquidation(clock,remaining)
        preopen[clock]=dict(state.q)
        if not hasattr(state,'preopen_account'):state.preopen_account={}
        state.preopen_account[clock]=state.aggregates()
        if not hasattr(state,'preopen_detail'):state.preopen_detail={}
        unconsumed={r['fill_id'] for r in remaining}
        state.preopen_detail[clock]={
            'marks':dict(state.mark),'average_prices':dict(state.avg),
            'liquidation_before_callback':any(r['exit_reason']=='liquidation' and r['fill_id'] not in unconsumed
                for r in fg.get(clock,[]))}
        if aligned and clock<stop:
            index=int(elapsed)
            for i in ids:state.mark[i]=float(arrays[i]['mark_open'][index])
            liquidation(clock,remaining)
            capacity_used=defaultdict(float)
            for r in list(remaining):
                check(r['exit_reason']=='strategy','Unhealthy or misplaced forced fill')
                i=r['instrument_id'];spec=state.specs[i];oid=r['order_id'];check(oid in orders and oid in accepted,'Fill lacks immutable accepted order')
                order=orders[oid];check(order['instrument_id']==i and int(order['side'])==r['side'],'Fill/order target differs')
                check(pd.Timestamp(order['active_at'])<=clock and pd.Timestamp(order['timestamp'])<=clock,'Fill precedes submission/activation')
                check(filled_events[oid],'Missing ordered fill event')
                event_sequence=filled_events[oid][0]['_sequence']
                check(accepted[oid]<event_sequence and orders[oid]['_sequence']<event_sequence and (oid not in cancelled or cancelled[oid]>event_sequence),'Fill follows cancellation or precedes ordered acceptance')
                reference=float(arrays[i]['open'][index]);check(r['reference_price']==reference,'Execution reference is not actual minute open')
                check(np.isclose(r['price'],adverse(reference,r['side'],spec,config),rtol=1e-12,atol=1e-12),'Execution adverse tick price differs')
                cap=(float(arrays[i]['volume'][index-1]) if index>0 else 0.)*config['participation']
                available_capacity=max(0.,cap-capacity_used[i])
                remaining_order=order['quantity']-order_filled[oid]
                expected_quantity=math.floor((min(remaining_order,available_capacity)+spec['lot_size']*1e-9)/spec['lot_size'])*spec['lot_size']
                if order['reduce_only']:expected_quantity=min(expected_quantity,abs(state.q[i]))
                close(r['quantity'],expected_quantity,'Exact remaining-order/prior-volume native fill quantity')
                capacity_used[i]+=r['quantity']
                check(capacity_used[i]<=cap+max(1e-8,cap*1e-12),'Fill exceeds prior completed volume capacity')
                check(abs(r['quantity']/spec['lot_size']-round(r['quantity']/spec['lot_size']))<1e-6 and r['quantity']>=spec['min_quantity']-EPS,'Fill violates native lot/minimum')
                order_filled[oid]+=r['quantity'];check(order_filled[oid]<=order['quantity']+max(1e-8,order['quantity']*1e-12),'Immutable order quantity exceeded')
                if order['reduce_only']:
                    check(state.q[i]*r['side']<0 and r['quantity']<=abs(state.q[i])+EPS,'Reduce-only fill opened or flipped inventory')
                else:check(r['quantity']*r['price']>=spec['min_notional']-EPS,'Opening fill below native minimum notional')
                events=filled_events[oid];check(events,'Missing order fill event');event=events.pop(0)
                check(pd.Timestamp(event['timestamp'])==clock,'Order fill event clock');close(event['quantity'],r['quantity'],'Order fill event quantity');close(event['price'],r['price'],'Order fill event price')
                # Close-only fills are admissible without new risk; opening risk is local to the wallet.
                old=state.q[i];new=old+r['side']*r['quantity']
                if not (old*r['side']<0 and abs(new)<=abs(old)+EPS):
                    a=state.aggregates();venue=spec['exchange'];eq=a[venue+'_equity']-r['side']*r['quantity']*(r['price']-state.mark[i])-r['fee'];gross=a[venue+'_gross_exposure']-abs(old)*state.mark[i]+abs(new)*state.mark[i]
                    check(eq>0 and gross<=eq*.5+EPS and abs(new)*state.mark[i]<=eq*.25+EPS,'Opening fill violates separate wallet margin/risk limits')
                state.fill(r);remaining.pop(0)
            liquidation(clock,remaining)
        check(not remaining,'Nonexecuted/misplaced fills left at source clock')
        a=state.aggregates();x=state.exposure()
        if number==0:
            check(not any(state.q.values()) and not state.fees,'Initial baseline unexpectedly traded')
            baseline=Replay(specs,config);a=baseline.aggregates();x=baseline.exposure()
        reconstructed_equity.append(a);reconstructed_exposure.append(x)
    check(consumed_payments==set(pg),'Extra actual funding payments')
    check(all(not v for v in filled_events.values()) and all(not v for v in liq_events.values()),'Unmatched fill/liquidation events')
    # Compare columns in bulk, avoiding a row-wise 127-column pandas loop.
    expected_eq=pd.DataFrame(reconstructed_equity)
    equity_columns=(set(expected_eq)|{'timestamp'})-{v+'_'+k for v in VENUES for k in ('gross_exposure','margin_used','available_margin')}
    check(set(equity)==equity_columns,'Equity schema differs')
    for k in expected_eq:
        if k in equity:close(equity[k].to_numpy(),expected_eq[k].to_numpy(),'Equity '+k)
    expected_x=pd.DataFrame(reconstructed_exposure)
    check(set(exposure)==set(expected_x)|{'timestamp'},'Exposure field identities differ')
    for k in expected_x:
        if k.startswith('mark_'):check(np.array_equal(exposure[k].to_numpy(),expected_x[k].to_numpy()),'Source mark observer differs: '+k)
        else:close(exposure[k].to_numpy(),expected_x[k].to_numpy(),'Exposure '+k)
    trades=tables['trades'];check(len(trades)==len(state.trade_rows),'Trade count differs from replay')
    for row,expected in zip(trades.to_dict('records'),state.trade_rows):
        for k,v in expected.items():
            if isinstance(v,(float,np.floating)):close(row[k],v,'Trade '+k)
            else:check(row[k]==v,'Trade identity '+k)
    positions=tables['positions'];expected_ids={i for i in ids if abs(state.q[i])>EPS}
    check(len(positions)==len(expected_ids) and (set(positions.instrument_id) if len(positions) else set())==expected_ids,'Final native open position set differs')
    for row in positions.to_dict('records'):
        i=row['instrument_id'];spec=state.specs[i]
        for k,v in dict(quantity=state.q[i],average_price=state.avg[i],mark_price=state.mark[i],unrealized_pnl=state.q[i]*(state.mark[i]-state.avg[i]),funding_pnl=state.fund[i],entry_fees=state.entryfee[i],collateral=state.alloc[i],maintenance_margin=abs(state.q[i])*state.mark[i]*spec['maintenance_rate']).items():close(row[k],v,'Open position '+k)
        check(row['exchange']==spec['exchange'] and row['symbol']==spec['symbol'] and pd.isna(row['liquidation_price']),'Cross open position identity/liquidation threshold')
    return state,preopen


def committed_file(commit,path):
    check(isinstance(commit,str) and re.fullmatch('[a-f0-9]{40}',commit),'Full Git anchor required')
    return subprocess.run(['git','show',commit+':'+path],cwd=REPO,capture_output=True,check=True).stdout


def expected_sources(source_anchor):
    core=subprocess.run(['git','ls-tree','-r','--name-only',source_anchor,'--','aster'],cwd=REPO,capture_output=True,check=True,text=True).stdout.splitlines()
    explicit={f'examples/{folder}/{name}' for folder in ('funding_rank','positioning_research')
              for name in ('run.py','signals.py','strategy.py','proposed_protocol.md')}
    explicit|={'examples/cross_venue/signals.py','examples/minute_research/download.py',
               'examples/minute_research/downloadcarry.py','examples/positioning/collect_archives.py',
               'audit/verify_positioning_dataset.py','docs/positioning_economic_research.md'}
    return {p for p in core if p.endswith('.py')}|explicit


def native_feature_paths(out):
    return {variant:{iid('binance',symbol):Path(out)/'features'/variant/(iid('binance',symbol).split(':')[-1]+'.parquet')
                     for symbol in SYMBOLS} for variant in DELAYS}


def packet_guard(perp_cache,metrics_cache,out,source_anchor,input_anchor):
    perp_cache,metrics_cache,out=map(Path,(perp_cache,metrics_cache,out))
    check(source_anchor==SOURCE_ANCHOR,'Exact candidate28 reviewed source anchor required')
    receipts={}
    for name in ('source_lock.json','input_verification.json'):
        original=committed_file(input_anchor,PREREG+'/'+name)
        check((out/name).read_bytes()==original,'Committed pre-feature receipt changed: '+name)
        receipts[name]=json.loads(original)
    lock=receipts['source_lock.json'];verification=receipts['input_verification.json']
    original=committed_file(input_anchor,PREREG+'/preregistration.json')
    check((REPO/PREREG/'preregistration.json').read_bytes()==original,'Immutable preregistration receipt differs')
    prereg=json.loads(original)
    check(prereg.get('source_commit')==source_anchor and prereg.get('proposed_candidate_number')==28
          and prereg.get('historical_features_exist') is False and prereg.get('trial_directory_exists') is False,'Pre-outcome candidate/source anchor differs')
    for name in receipts:check(prereg.get(name.removesuffix('.json')+'_sha256')==sha(out/name),'Pre-outcome receipt SHA differs')
    check(prereg.get('source_files')==len(lock['sources'])
          and prereg.get('perpetual_input_files')==len(lock['perpetual_inputs'])
          and prereg.get('metrics_input_files')==len(lock['metrics_inputs']),'Exact pre-outcome namespace counts differ')
    published=read(out/'published_lock.json')
    check(published.get('remote_commit')==input_anchor and published.get('commit_path')==PREREG
          and published.get('historical_features_exist') is False and published.get('trials_exist') is False,
          'Exact prior publication anchor/status required')
    for name in receipts:check(published.get(name.removesuffix('.json')+'_sha256')==sha(out/name),'Published receipt SHA differs')
    check(subprocess.run(['git','merge-base','--is-ancestor',source_anchor,input_anchor],cwd=REPO,capture_output=True).returncode==0,'Input lock predates reviewed source')
    check(subprocess.run(['git','merge-base','--is-ancestor',input_anchor,'origin/main'],cwd=REPO,capture_output=True).returncode==0,'Input anchor not published in origin/main history')
    check(lock.get('family')==FAMILY and lock.get('candidate_count_cumulative')==28,'Locked family/count differs')
    check(lock.get('phases')==[[n,str(b),str(e),stress] for n,b,e,stress in PHASES],'Exact five frozen phase dates required')
    check(lock.get('input_verification')==verification,'Locked input verification differs')
    check(set(lock.get('sources',{}))==expected_sources(source_anchor),'Complete frozen transitive source graph differs')
    for name,digest in lock['sources'].items():
        check(hashlib.sha256(committed_file(source_anchor,name)).hexdigest()==digest,'Reviewed source anchor differs: '+name)
        check(sha(REPO/name)==digest and sha(out/'executed_source'/name)==digest,'Current/archived execution source differs: '+name)
    expected={(perp_cache/name).resolve() for name in ('instruments.json','cross_mapping.json','instrument_source_manifest.json','exchange_info_current.json')}
    for symbol in SYMBOLS:
        expected|={(perp_cache/symbol/name).resolve() for name in ('bars.parquet','funding.parquet','source_manifest.json')}
        manifest=read(perp_cache/symbol/'source_manifest.json')
        for item in manifest['archives']+manifest['funding_pages']:
            path=Path(item['cache_file'])
            if not path.exists():path=REPO/path
            expected.add(path.resolve())
    check(set(lock.get('perpetual_inputs',{}))=={str(p) for p in expected},'Complete perpetual raw/normalized namespace differs')
    check(all(not p.is_symlink() for p in metrics_cache.rglob('*')),'Metrics symlink unsupported')
    metric_files={str(p.resolve()) for p in metrics_cache.rglob('*') if p.is_file()}
    check(set(lock.get('metrics_inputs',{}))==metric_files,'Complete positioning raw/normalized namespace differs')
    for namespace in ('perpetual_inputs','metrics_inputs'):
        for path,digest in lock[namespace].items():check(sha(path)==digest,'Raw/normalized input drift: '+path)
    certificate=REPO/'audit/positioning_dataset_evidence.json'
    check(lock.get('dataset_certificate_path')==str(certificate.resolve()) and lock.get('dataset_certificate_sha256')==sha(certificate),'Dataset certificate binding differs')
    check(certificate.read_bytes()==committed_file(source_anchor,'audit/positioning_dataset_evidence.json'),'Dataset certificate differs from immutable reviewed packet')
    cert=read(certificate)
    check(cert.get('complete') is True and cert.get('errors')==[] and cert.get('source_anchor')=='241a6502a939a4bfe27dea938bdb5ef151808f46','Independent acquisition certificate incomplete')
    for key in ('source_unchanged_during_audit','auditor_source_unchanged','exact_normalization_reconstruction_passed','source_and_runtime_reconstruction_passed','evidence_unchanged_during_audit'):
        check(cert.get(key) is True,'Dataset audit stability claim failed: '+key)
    check(cert.get('complete_seal_sha256')==sha(metrics_cache/'complete.json')
          and cert.get('collector_sha256')==sha(REPO/'examples/positioning/collect_archives.py')
          and cert.get('auditor_sha256')==sha(REPO/'audit/verify_positioning_dataset.py'),'Dataset audit source/seal differs')
    check(cert.get('raw_source_files_checked')==8760 and cert.get('raw_archive_count')==2920
          and cert.get('normalized_source_file_count')==18,'Dataset audit scope differs')
    check(verification.get('positioning_dataset_certificate')==cert
          and verification.get('positioning_complete_seal_sha256')==sha(metrics_cache/'complete.json'),'Frozen positioning verification differs')
    checks=verification.get('perpetual',[])
    check(len(checks)==8 and {c['spot_symbol'] for c in checks}==set(SYMBOLS),'Eight native perpetual input certifications required')
    versions={'python':sys.version,**{n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','scipy','plotly')}}
    check(lock.get('runtime')==versions,'Executed runtime drift')
    return lock


def verify_feature_certificate(out,feature_audit,source_anchor,input_anchor):
    out=Path(out);receipt=read(out/'feature_receipt.json');cert=read(feature_audit);paths=native_feature_paths(out)
    check((out/'features').is_dir() and not (out/'features').is_symlink(),'Regular native feature namespace required')
    check({p.name for p in (out/'features').iterdir()}==set(DELAYS),'Exact two native feature namespaces required')
    for variant,group in paths.items():
        check(not (out/'features'/variant).is_symlink() and {p.name for p in (out/'features'/variant).iterdir()}=={p.name for p in group.values()},'Exact eight native feature packets required')
        check(all(p.is_file() and not p.is_symlink() for p in group.values()),'Regular native feature files required')
    hashes={v:{i:sha(p) for i,p in group.items()} for v,group in paths.items()}
    check(receipt.get('source_lock_sha256')==sha(out/'source_lock.json') and receipt.get('features_sha256')==hashes,'Feature receipt/input seal drift')
    check(cert.get('complete') is True and cert.get('errors')==[] and cert.get('features_sha256')==hashes
          and cert.get('source_lock_sha256')==sha(out/'source_lock.json')
          and cert.get('feature_receipt_sha256')==sha(out/'feature_receipt.json'),'Exact independent feature certification required')
    check(cert.get('source_anchor')==source_anchor and cert.get('input_anchor')==input_anchor,'Independent feature audit Git anchors differ')
    for key in ('source_unchanged_during_audit','input_unchanged_during_audit','features_unchanged_during_audit','auditor_source_unchanged'):
        check(cert.get(key) is True,'Independent feature stability failed: '+key)
    check(cert.get('scope')==dict(native_stream_count=8,delays_minutes=[6,11],begin=START.isoformat(),end=END.isoformat(),full_reconstruction=True),'Independent feature scope differs')
    check(cert.get('auditor_path')==FEATURE_AUDITOR and cert.get('auditor_sha256')==sha(REPO/FEATURE_AUDITOR)
          and cert.get('raw_dataset_helper_sha256')==sha(REPO/'audit/verify_positioning_dataset.py'),'Independent causal auditor/helper source differs')
    check(cert.get('published_lock_sha256')==sha(out/'published_lock.json')
          and cert.get('input_verification_sha256')==sha(out/'input_verification.json'),'Independent feature common-receipt binding differs')
    stamp=pd.Timestamp(cert.get('completed_at_utc'))
    check(not pd.isna(stamp) and stamp.tzinfo is not None and stamp>=pd.Timestamp((out/'feature_receipt.json').stat().st_mtime,unit='s',tz='UTC'),'Feature certificate is stale')
    return cert


def evidence_hashes(out,lock,feature_audit):
    """Pin all raw inputs, helpers and phase packets before any numeric reads."""
    out=Path(out);paths={Path(__file__),REPO/'audit/verify_funding_rank_outputs.py',REPO/FEATURE_AUDITOR,
                      Path(feature_audit),Path(lock['dataset_certificate_path']),REPO/PREREG/'preregistration.json'}
    paths|={out/n for n in ('source_lock.json','input_verification.json','feature_receipt.json','published_lock.json','summary.json')}
    paths|={Path(name) for namespace in ('perpetual_inputs','metrics_inputs') for name in lock[namespace]}
    paths|={REPO/name for name in lock['sources']}|{out/'executed_source'/name for name in lock['sources']}
    paths|={p for group in native_feature_paths(out).values() for p in group.values()}
    paths|={out/'trials'/phase[0]/name for phase in PHASES for name in (*OUTPUTS,'completion.json')}
    hashes={str(path.resolve()):sha(path) for path in sorted(paths)}
    hashes['__runtime__']=json.dumps({'python':sys.version,**{n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','scipy','plotly')}},sort_keys=True)
    return hashes


def verify_long_inventory(tables,exposure):
    running={iid('binance',s):0. for s in SYMBOLS}
    orders={row['order_id']:row for row in tables['events'].to_dict('records') if row['type']=='ORDER_SUBMITTED'}
    for row in tables['fills'].to_dict('records'):
        i=row['instrument_id'];check(i in running,'Unknown native fill')
        if row['side']<0 and row['exit_reason']=='strategy':check(orders[row['order_id']]['reduce_only'] is True,'Long close must be actual reduce-only order')
        running[i]+=row['side']*row['quantity']
        if abs(running[i])<EPS:running[i]=0.
        check(all(q>=0 for q in running.values()) and sum(q>0 for q in running.values())<=1,'Observed fills create short or simultaneous native inventory')
    values=exposure[[f'quantity_{s}' for s in SYMBOLS]].to_numpy(dtype=float)
    check(np.isfinite(values).all() and (values>=0).all() and (np.count_nonzero(values,axis=1)<=1).all(),'Observed account not single-active long/cash')


def verify_terminal_orders(terminal,tables,exposure,stop):
    rows=tables['events'].to_dict('records');submitted={};live=set();filled=defaultdict(float)
    for row in rows:
        typ=row['type'];oid=row.get('order_id')
        if typ=='ORDER_SUBMITTED':submitted[oid]=row
        elif typ=='ORDER_ACCEPTED':live.add(oid)
        elif typ in ('ORDER_FILLED','ORDER_PARTIALLY_FILLED'):
            filled[oid]+=row['quantity']
            if typ=='ORDER_FILLED':live.discard(oid)
        elif typ in ('ORDER_REJECTED','ORDER_CANCELLED'):
            if typ=='ORDER_CANCELLED' and row.get('reason')=='end_of_data':continue
            live.discard(oid)
    before=terminal['before_end_of_data_cancellation']
    check(terminal['after_run_live_orders']==[] and len(before)==exposure.live_order_count.iloc[-1], 'Terminal observer/order count differs')
    check(len({o['id'] for o in before})==len(before) and {o['id'] for o in before}==live,'Exact pre-auto-cancellation live identities differ')
    fields={'instrument_id','side','quantity','order_type','limit_price','stop_price','post_only','reduce_only','tif',
            'id','submitted_at','active_at','remaining','status','first_seen','triggered'}
    for order in before:
        check(set(order)==fields,'Terminal immutable-order fields differ')
        source=submitted[order['id']]
        for key in ('instrument_id','side','quantity','order_type','post_only','reduce_only','tif'):
            compare(order[key],source[key],'Terminal immutable order '+key)
        for key in ('limit_price','stop_price'):
            expected=source[key] if not pd.isna(source[key]) else None
            compare(order[key],expected,'Terminal optional order '+key)
        check(pd.Timestamp(order['submitted_at'])==pd.Timestamp(source['timestamp'])
              and pd.Timestamp(order['active_at'])==pd.Timestamp(source['active_at']),'Terminal immutable order clocks differ')
        close(order['remaining'],source['quantity']-filled[order['id']],'Terminal actual remaining quantity')
        check(order['status']==('partial' if filled[order['id']]>0 else 'accepted') and order['triggered'] is False,'Terminal market-order state differs')
        first=pd.Timestamp(source['active_at']).ceil('min')
        check((order['first_seen'] is None if first>=stop else pd.Timestamp(order['first_seen'])==first),
              'Terminal market-order first eligible bar differs')
        cancels=[r for r in rows if r['type']=='ORDER_CANCELLED' and r.get('order_id')==order['id']]
        check(len(cancels)==1 and cancels[0]['reason']=='end_of_data' and pd.Timestamp(cancels[0]['timestamp'])==stop,
              'Live endpoint order lacks actual automatic cancellation')
    return before


def verify_completed_episodes(completed,diagnostics,preopen,tables,begin,stop):
    """Actual full entry and flat closure evidence; not an eligibility-policy proof."""
    fields={'generation','symbol','instrument_id','submitted_at','entry_completed_at','exit_reason',
            'average_entry_price','closed_at','observed_closed_at','failed'}
    transactions={};entries={};closures={}
    for row in diagnostics['events']:
        gen=row.get('generation')
        if row['type']=='TARGET_SUBMITTED' and row['transition']=='ENTERING':
            check(gen not in transactions,'Duplicate actual entry transaction');transactions[gen]=row
        elif row['type']=='ENTRY_COMPLETE':
            check(gen not in entries,'Duplicate actual completed entry');entries[gen]=row
        elif row['type']=='EPISODE_CLOSED' and row.get('failed') is False and row.get('entry_completed_at') is not None:
            check(gen not in closures,'Duplicate successful closure diagnostic');closures[gen]=row
    participants=set();generations=set();fills=tables['fills']
    for row in completed:
        check(set(row)==fields,'Completed episode fields differ')
        gen=row['generation'];symbol=row['symbol'];i=iid('binance',symbol)
        check(type(gen) is int and gen>0 and gen not in generations and gen in transactions and gen in entries and gen in closures,'Missing/repeated actual episode generation')
        check(symbol in SYMBOLS and row['instrument_id']==i and row['failed'] is False,'Invalid completed native episode identity')
        compare(row,{key:closures[gen][key] for key in fields},'Actual completed closure diagnostic')
        tx=transactions[gen];entry=entries[gen];targets=tx['targets']
        check(set(targets)=={iid('binance',s) for s in SYMBOLS} and targets[i]>0 and all(q==0 for j,q in targets.items() if j!=i),'Only one positive native target required')
        submitted,entered,closed,observed=map(pd.Timestamp,(row['submitted_at'],row['entry_completed_at'],row['closed_at'],row['observed_closed_at']))
        entry_observed=pd.Timestamp(entry['observed_completed_at'])
        check(all(t.tzinfo is not None for t in (submitted,entered,closed,observed,entry_observed)) and begin<=submitted<=entered<=entry_observed<=closed<=observed<stop,'Completed episode actual clocks differ')
        check(submitted==pd.Timestamp(tx['timestamp']) and entered<=pd.Timestamp(tx['deadline']),'Entry timing/deadline differs')
        check(submitted in preopen and entry_observed in preopen and observed in preopen,'Completion observation unavailable')
        check(all(q==0 for q in preopen[submitted].values()),'Entry was not actually flat')
        bought=fills.loc[fills.order_id.isin(tx['order_ids'])]
        check(len(bought)>0 and bought.instrument_id.eq(i).all() and bought.side.eq(1).all() and entered==bought.timestamp.max(),'Entry completion differs from last actual native buy')
        close(bought.quantity.sum(),targets[i],'Full actual entered target')
        close(row['average_entry_price'],float((bought.quantity*bought.price).sum()/bought.quantity.sum()),'Actual episode entry VWAP')
        close(entry['average_entry_price'],row['average_entry_price'],'Entry/episode VWAP differs')
        for j,q in targets.items():close(preopen[entry_observed][j],q,'Observed full native target')
        sold=fills.loc[fills.instrument_id.eq(i)&fills.side.eq(-1)&fills.timestamp.ge(entered)&fills.timestamp.le(closed)]
        check(len(sold)>0 and sold.exit_reason.eq('strategy').all() and sold.timestamp.max()==closed,'Actual successful close differs')
        close(sold.quantity.sum(),targets[i],'Actual fully closed episode quantity')
        check(all(q==0 for q in preopen[observed].values()),'Completed episode remains actual nonflat')
        participants.add(symbol);generations.add(gen)
    check(generations==set(closures),'Completed export omitted/invented successful closures')
    return sorted(participants),len(generations)


def verify_phase(cache,out,phase,lock,input_anchor,feature_audit):
    name,begin,stop,stress=phase;path=out/'trials'/name
    sealed={n:sha(path/n) for n in OUTPUTS}
    completion_sha=sha(path/'completion.json')
    parameters=dict(family=FAMILY,phase=name,begin=str(begin),stop=str(stop),stress=stress,
        source_lock_sha256=sha(out/'source_lock.json'),features_sha256=read(out/'feature_receipt.json')['features_sha256'],
        feature_receipt_sha256=sha(out/'feature_receipt.json'),feature_audit_sha256=sha(feature_audit),
        published_lock_sha256=sha(out/'published_lock.json'),research_status='exploratory reused year; candidate28')
    check(read(path/'completion.json')==dict(parameters=parameters,outputs_sha256=sealed),'Completed phase seal differs')
    specs=read(cache/'instruments.json');by_id={s['id']:dict(s,maker_bps=10 if stress else 5,taker_bps=10 if stress else 5) for s in specs}
    check(set(by_id)=={iid('binance',s) for s in SYMBOLS},'Native source catalog differs')
    specs=[by_id[iid('binance',s)] for s in SYMBOLS];cfg=configuration(stress)
    meta=read(path/'metadata.json')
    check(meta['parameters']==parameters and meta['engine']==cfg and meta['instruments']==specs,'Executed metadata/config/native catalog differs')
    check(meta['strategy']=='PositioningPortfolio' and meta['strategy_version']=='prospective-native-oi-stabilization-rebound-1','Strategy class/version differs')
    check(meta['source_sha256']=={p.removeprefix('aster/'):h for p,h in lock['sources'].items() if p.startswith('aster/')},'Core source metadata differs')
    check(subprocess.run(['git','merge-base','--is-ancestor',input_anchor,meta['git_commit']],cwd=REPO,capture_output=True).returncode==0,'Execution precedes preregistration Git anchor')
    check(meta['start']==str(begin) and meta['end']==str(stop) and meta['timeframes_seconds']==[60],'Execution bounds/timeframe differ')
    check(meta['python']==lock['runtime']['python'] and meta['dependencies']=={n:lock['runtime'][n] for n in ('numpy','pandas','pyarrow','plotly')},'Executed runtime metadata differs')
    check(meta['software']=='aster' and meta['open_positions_marked'] is True and meta['terminal_forced_close'] is False,'Actual software/terminal accounting policy differs')
    manifest=dict(source_lock=lock,funding_boundary='actual sourced begin<=timestamp<=stop; predictor excludes END; original mark and native units',terminal_order_semantics='captured at final equity clock BEFORE automatic end_of_data cancellations')
    check(meta['source_manifest']==manifest and read(path/'source_manifest.json')==manifest,'Actual source manifest differs')
    tables={n:pd.read_parquet(path/(n+'.parquet')) for n in LEDGERS}
    quality=read(path/'quality.json')
    check(not quality['errors'] and meta['data_quality']==quality,'Executed source quality differs')
    for n,frame in tables.items():verify_csv(path/(n+'.csv'),frame)
    exposure=pd.read_parquet(path/'exposure.parquet');verify_csv(path/'exposure.csv',exposure)
    bars={};funds=[]
    for symbol in SYMBOLS:
        source=pd.read_parquet(cache/symbol/'bars.parquet');fund=pd.read_parquet(cache/symbol/'funding.parquet')
        i=iid('binance',symbol)
        check(source.instrument_id.eq(i).all() and source.duration_seconds.eq(60).all() and fund.instrument_id.eq(i).all(),'Wrong native minute/funding input')
        bars[i]=source.loc[source.timestamp.ge(begin)&source.timestamp.lt(stop)].reset_index(drop=True)
        funds.append(fund.loc[fund.timestamp.ge(begin)&fund.timestamp.le(stop)])
    funding=pd.concat(funds,ignore_index=True)
    check(meta['data_sha256']==csv_hash(list(bars.values())) and meta['funding_sha256']==csv_hash([funding]),'Serialized actual input hashes differ')
    state,preopen=reconstruct(tables,exposure,bars,funding,specs,cfg,begin,stop)
    diagnostics=read(path/'strategy_diagnostics.json');completed=read(path/'completed_episodes.json')
    check(read(path/'completed_baskets.json')==completed,'Compatibility export differs from actual closed episodes')
    verify_long_inventory(tables,exposure)
    participants,count=verify_completed_episodes(completed,diagnostics,preopen,tables,begin,stop)
    legs=[]
    for symbol in SYMBOLS:
        i=iid('binance',symbol)
        legs.append(dict(symbol=symbol,instrument_id=i,net_pnl=state.leg_net[i]+state.q[i]*(state.mark[i]-state.avg[i]),
            fill_count=state.leg_fills[i],open_quantity=state.q[i],funding_cash=state.leg_fund[i]))
    compare(pd.read_csv(path/'leg_contributions.csv').to_dict('records'),legs,'All eight leg contributions')
    check(read(path/'proposal_ledger.json')==[r for r in diagnostics['events'] if r['type']=='EVENT_PROPOSAL'],'Proposal export differs')
    check(read(path/'rejections.json')==[r for r in diagnostics['events'] if 'REJECTED' in r['type'] or r['type']=='ACCOUNT_RISK_BLOCKED'],'Refusal export differs')
    terminal=read(path/'terminal_orders.json');before=verify_terminal_orders(terminal,tables,exposure,stop)
    actual_terminal_quantities=[float(exposure[f'quantity_{s}'].iloc[-1]) for s in SYMBOLS]
    check(np.isfinite(actual_terminal_quantities).all(),'Nonfinite final observed native inventory')
    check([q!=0 for q in actual_terminal_quantities]==[state.q[iid('binance',s)]!=0 for s in SYMBOLS],'Exact final nonzero/dust classification differs from native replay')
    terminal_nonzero=sum(q!=0 for q in actual_terminal_quantities)
    terminal_flat=terminal_nonzero==0 and not before
    score=read(path/'metrics.json');base=reference_metrics(tables['equity'],tables['trades'],tables['fills'])
    daily=endpoint_returns(tables['equity']).dropna();std=float(daily.std(ddof=1))
    daily_export=pd.read_csv(path/'daily_returns.csv')
    check(list(daily_export)==['timestamp','return'] and len(daily_export)==len(daily),'Exported daily return grid/schema differs')
    check(pd.DatetimeIndex(pd.to_datetime(daily_export.timestamp,utc=True)).as_unit('ns').equals(daily.index.as_unit('ns')),'Exported daily return clocks differ')
    close(daily_export['return'].to_numpy(),daily.to_numpy(),'Exported daily return values')
    base.update(sharpe=float(daily.mean()/std*np.sqrt(365)) if np.isfinite(std) and std>0 else None,daily_return_count=len(daily))
    for k,v in base.items():compare(score[k],v,'Base metric '+k)
    fee=sum(abs(state.q[i])*state.mark[i]*state.specs[i]['taker_bps']/10000 for i in state.ids)
    slip=sum(abs(state.q[i])*state.mark[i]*cfg['slippage_bps']/10000 for i in state.ids)
    liq=int(tables['events'].type.eq('LIQUIDATION').sum()) if len(tables['events']) else 0
    extra=dict(indicative_exit_fee_reserve=fee,indicative_exit_slippage_reserve=slip,indicative_exit_reserve_total=fee+slip,
        return_after_indicative_exit_reserve=(float(tables['equity'].equity.iloc[-1])-fee-slip)/100000-1,
        liquidation_event_count=liq,open_position_count=len(tables['positions']),terminal_live_order_count=len(before),
        terminal_observed_nonzero_position_count=terminal_nonzero,
        terminal_flat_resolved=terminal_flat,completed_participants=participants,completed_basket_count=count,completed_episode_count=count,joint_account=True)
    for k,v in extra.items():compare(score[k],v,'Additional metric '+k)
    check(set(score)==set(base)|set(extra)|{'runtime_seconds','peak_rss_mib_process'},'Unverified metric fields')
    check({n:sha(path/n) for n in OUTPUTS}==sealed and sha(path/'completion.json')==completion_sha,'Evidence changed during replay')
    return dict(outputs_sha256=sealed,completion_sha256=completion_sha,equity_snapshots=len(exposure),fills=len(tables['fills']),
        funding_cash_events=len(tables['funding']),closed_trades=len(tables['trades']),completed_episodes=count,
        participants=participants,liquidation_events=liq,terminal_flat_resolved=terminal_flat,
        trajectory_reconstruction_passed=True,recorded_policy_reconstruction_complete=False),score,tables['equity']


def summary_gates(records):
    scores={n:r[1] for n,r in records.items()};base=scores['evaluation'];stress=scores['evaluation_stress']
    validation=float(np.prod([1+scores[f'validation{k}']['total_return'] for k in (1,2,3)])-1)
    reserve=float(np.prod([1+scores[f'validation{k}']['return_after_indicative_exit_reserve'] for k in (1,2,3)])-1)
    series=records['evaluation'][2].set_index('timestamp').equity
    points=[float(series.asof(EVAL+pd.DateOffset(months=k))) for k in range(4)]
    check(np.isfinite(points).all() and min(points)>0,'Anchored monthly equity missing/nonpositive')
    months=[points[k+1]/points[k]-1 for k in range(3)];participants=set(base['completed_participants'])
    gates=dict(positive_compounded_validation=validation>0,positive_validation_after_exit_reserve=reserve>0,
        positive_evaluation=base['total_return']>0,positive_evaluation_after_exit_reserve=base['return_after_indicative_exit_reserve']>0,
        positive_stress=stress['total_return']>0,positive_stress_after_exit_reserve=stress['return_after_indicative_exit_reserve']>0,
        two_positive_anchored_months=sum(x>0 for x in months)>=2,daily_sharpe_at_least_half=base['sharpe'] is not None and base['sharpe']>=.5,
        minute_drawdown_at_most_twenty_percent=base['max_drawdown']<=.2,no_liquidation_all_five_runs=sum(s['liquidation_event_count'] for s in scores.values())==0,
        four_completed_assets=len(participants)>=4,completed_doge_participation='DOGEUSDT' in participants,
        completed_pepe_participation='PEPEUSDT' in participants,two_completed_entry_generations=base['completed_basket_count']>=2,
        actual_terminal_flat_all_five_runs=all(s['terminal_flat_resolved'] for s in scores.values()))
    return gates,validation,reserve,months


def verify(perp_cache,metrics_cache,out,source_anchor,input_anchor,feature_audit):
    cache,out=Path(perp_cache),Path(out)
    initial_lock=read(out/'source_lock.json')
    before=evidence_hashes(out,initial_lock,feature_audit)  # BEFORE first provenance/receipt reads
    lock=packet_guard(cache,metrics_cache,out,source_anchor,input_anchor)
    check(lock==initial_lock and evidence_hashes(out,lock,feature_audit)==before,'Evidence changed during initial provenance validation')
    check({p.name for p in (out/'trials').iterdir()}=={p[0] for p in PHASES},'Require all five exact phases')
    feature_certificate=verify_feature_certificate(out,feature_audit,source_anchor,input_anchor)
    records={}
    for phase in PHASES:
        records[phase[0]]=verify_phase(cache,out,phase,lock,input_anchor,feature_audit)
        check(evidence_hashes(out,lock,feature_audit)==before,'Source/common/feature/earlier-phase evidence changed during reconstruction')
    gates,validation,reserve,months=summary_gates(records);summary=read(out/'summary.json')
    expected_fields={'family','candidate_count_cumulative','research_status','passes_hurdles','gates','failed_gates',
        'validation_compounded_return','validation_after_exit_reserve','scores','anchored_month_returns',
        'completed_participants','completed_basket_count','completed_episode_count','all_evaluation_leg_contributions',
        'conditional_interval','full_resolution_evaluation_equity_sha256','source_lock_sha256','features_sha256',
        'feature_receipt_sha256','feature_audit_sha256','publication_status'}
    check(set(summary)==expected_fields,'Unexpected/unverified summary fields')
    check(summary['publication_status']=='UNPUBLISHED: independent policy, trajectory and summary reconstruction required','Summary publication claim differs')
    check(summary['gates']==gates and summary['passes_hurdles']==all(gates.values()) and summary['failed_gates']==[k for k,v in gates.items() if not v],'Fifteen summary gates differ')
    close(summary['validation_compounded_return'],validation,'Validation compound');close(summary['validation_after_exit_reserve'],reserve,'Validation after reserve')
    compare(summary['anchored_month_returns'],months,'Anchored evaluation months')
    compare(summary['scores'],{n:record[1] for n,record in records.items()},'All five scorecards')
    check(summary['family']==FAMILY and summary['candidate_count_cumulative']==28 and summary['research_status']=='exploratory reused year; no untouched holdout','Summary family/search/holdout differs')
    score=records['evaluation'][1]
    for key in ('completed_participants','completed_basket_count','completed_episode_count'):compare(summary[key],score[key],'Summary '+key)
    compare(summary['all_evaluation_leg_contributions'],pd.read_csv(out/'trials/evaluation/leg_contributions.csv').to_dict('records'),'Summary all eight legs')
    for key,path in [('source_lock_sha256',out/'source_lock.json'),('feature_receipt_sha256',out/'feature_receipt.json'),('feature_audit_sha256',Path(feature_audit)),('full_resolution_evaluation_equity_sha256',out/'trials/evaluation/equity.parquet')]:
        check(summary[key]==sha(path),'Summary evidence identity differs: '+key)
    check(summary['features_sha256']==feature_certificate['features_sha256'],'Summary feature packet differs')
    compare(summary['conditional_interval'],conditional_interval(records['evaluation'][2]),'Exact candidate28 conditional block bootstrap')
    packet_guard(cache,metrics_cache,out,source_anchor,input_anchor)
    check(evidence_hashes(out,lock,feature_audit)==before,'Source/runtime/common/raw/features/all-phase evidence changed during audit')
    return dict(complete=True,errors=[],financial_reconstruction_complete=True,complete_financial_scope=True,policy_reconstruction_complete=False,recorded_policy_reconstruction_complete=False,
        publication_ready=False,source_anchor=source_anchor,input_anchor=input_anchor,
        auditor_sha256=before[str(Path(__file__).resolve())],reference_helper_sha256=before[str((REPO/'audit/verify_funding_rank_outputs.py').resolve())],
        feature_audit_sha256=before[str(Path(feature_audit).resolve())],feature_auditor_sha256=before[str((REPO/FEATURE_AUDITOR).resolve())],
        source_unchanged_during_audit=True,input_unchanged_during_audit=True,features_unchanged_during_audit=True,
        auditor_source_unchanged=True,reference_source_unchanged=True,all_phase_evidence_unchanged=True,
        source_lock_sha256=before[str((out/'source_lock.json').resolve())],input_verification_sha256=before[str((out/'input_verification.json').resolve())],
        feature_receipt_sha256=before[str((out/'feature_receipt.json').resolve())],published_lock_sha256=before[str((out/'published_lock.json').resolve())],
        features_sha256=feature_certificate['features_sha256'],summary_sha256=before[str((out/'summary.json').resolve())],
        raw_and_normalized_input_files_checked={n:len(lock[n]) for n in ('perpetual_inputs','metrics_inputs')},
        common_artifacts_sha256={n:before[str((out/n).resolve())] for n in ('source_lock.json','input_verification.json','feature_receipt.json','published_lock.json','summary.json')},
        phases={n:record[0] for n,record in records.items()},gates_reconstructed=True,candidate_count_cumulative=28,
        completed_at_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        scope='Independent actual native long/cash fills, settled funding, wallet cash/equity, current-mark cross-margin, 63 observer fields, all ledgers, actual completed episodes, terminal orders, costs, fifteen gates and conditional block bootstrap.',
        limitations=['Not a comprehensive recorded-policy or omitted-decision reconstruction; a separately reviewed positioning policy auditor/certificate is required before publication readiness.',
                    'Original historical OI units, delivery and vintage are not verified; causal features retain declared availability assumptions.',
                    'This already examined year remains exploratory; conditional bootstrap cannot remove adaptive research bias.'])


def conditional_interval(frame):
    values=endpoint_returns(frame).dropna().to_numpy()
    if len(values)<7 or not np.isfinite(values).all() or (values<=-1).any():
        return {'available':False,'reason':'insufficient/invalid daily observations'}
    n=len(values);rng=np.random.default_rng(42);starts=rng.integers(0,n,(10000,(n+6)//7))
    index=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    draws=np.expm1(np.log1p(values[index]).sum(axis=1))
    return {'available':True,'comparison_count':28,'method':'conditional circular seven-day blocks;10000 draws;seed42',
            'tails':[.05/56,1-.05/56],'return_interval95':np.quantile(draws,[.025,.975]).tolist(),
            'return_interval_bonferroni28':np.quantile(draws,[.05/56,1-.05/56]).tolist(),
            'limitations':'conditional reused year; diagnostic only; cannot undo adaptive research'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--perp-cache',required=True);parser.add_argument('--metrics-cache',required=True)
    parser.add_argument('--out',required=True);parser.add_argument('--source-anchor',required=True);parser.add_argument('--input-anchor',required=True)
    parser.add_argument('--feature-audit',required=True);parser.add_argument('--receipt',required=True)
    args=parser.parse_args();check(not Path(args.receipt).exists(),'Preserve existing independent financial certificate')
    cert=verify(args.perp_cache,args.metrics_cache,args.out,args.source_anchor,args.input_anchor,args.feature_audit)
    Path(args.receipt).parent.mkdir(parents=True,exist_ok=True)
    with Path(args.receipt).open('x') as stream:stream.write(json.dumps(cert,indent=2,allow_nan=False)+'\n')
    print('Independent financial reconstruction passed; separate recorded-policy certification remains required.')


if __name__=='__main__':main()
