"""Independent positioning recorded-policy audit and bounded omission checks.

No production imports. Requires already independently verified pre-callback
accounts/quantities/marks, not post-open equity. Full cleanup-state equivalence
is intentionally not claimed. No historical files are read on import.
"""
from collections import defaultdict
from fractions import Fraction
import math
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:sys.path.insert(0,str(REPO))
import numpy as np
import pandas as pd

SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
HOUR=pd.Timedelta(hours=1);HOLD=4*HOUR;MIN=pd.Timedelta(minutes=1);EPS=1e-9


def check(ok,message):
    if not ok:raise AssertionError(message)


def iid(s):return 'binance:perpetual:'+('1000PEPEUSDT' if s=='PEPEUSDT' else s)


def same(a,b,message):
    check(np.allclose(a,b,rtol=2e-10,atol=1e-8,equal_nan=True),message)


def stamp(x):
    t=pd.Timestamp(x);check(not pd.isna(t) and t.tzinfo is not None,'Aware recorded policy clock required');return t.tz_convert('UTC')


def feature_at(frame,clock):
    j=frame.index.searchsorted(clock,side='right')-1
    if j<0 or clock-frame.index[j]>2*MIN:return None
    row=frame.iloc[j]
    if pd.isna(row.valid) or not bool(row.valid):return None
    for field in ('price','price_return_1h','price_return_15m','quantity_change_1h','quantity_change_5m'):
        try:v=float(row[field])
        except (TypeError,ValueError):return None
        if not math.isfinite(v) or field=='price' and v<=0:return None
    for field,strict,age in [('metric_available_at',True,5*MIN),('price_available_at',False,2*MIN)]:
        t=pd.Timestamp(row[field])
        if pd.isna(t) or t.tzinfo is None or (t>=clock if strict else t>clock) or clock-t>age:return None
    if 'metric_age_seconds' in row and (not math.isfinite(float(row.metric_age_seconds)) or not 0<=float(row.metric_age_seconds)<=300):return None
    return row


def eligible(row):
    return row is not None and row.quantity_change_1h<=-.02 and row.quantity_change_5m>=0 and row.price_return_1h<=-.015 and row.price_return_15m>=.003


def quantity(budget,price,lot):
    b,p,s=map(lambda x:Fraction(str(x)),(budget,price,lot));check(min(b,p,s)>0,'Invalid sizing inputs')
    count=(b/p)//s;q=float(count*s)
    if Fraction(str(q))*p>b or q*float(price)>float(budget):q=float(max(0,count-1)*s)
    return q


def admission(row,account,mark,spec,config):
    eq=account['binance_equity'];budget=.1*eq
    if not math.isfinite(budget) or budget<=0:return None,'invalid_equity'
    q=quantity(budget,float(row.price),spec['lot_size'])
    if q<=0 or q<spec['min_quantity']-EPS or q*row.price<spec['min_notional']-EPS:return None,'opening_minimum'
    if not math.isfinite(mark) or mark<=0:return None,'invalid_current_mark'
    ticks=mark*(1+config['slippage_bps']/10000)/spec['tick_size']
    execution=math.ceil(ticks-1e-10)*spec['tick_size'];fee=q*execution*spec['taker_bps']/10000
    margin=q*mark;slip=max(0,q*(execution-mark));future=eq-fee-slip;available=account['binance_available_margin']
    if future-margin < -EPS:return None,'core_margin'
    if future<=0 or margin>future*config['max_gross_leverage']+EPS:return None,'core_gross_leverage'
    if margin>future*config['max_position_pct']+EPS:return None,'core_position_limit'
    if margin+fee+slip>=available:return None,'available_margin'
    if future<=0 or margin>min(.5,config['max_gross_leverage'])*future+EPS:return None,'gross_limit'
    if margin>min(.25,config['max_position_pct'])*future+EPS:return None,'position_limit'
    reserve=margin*(spec['maintenance_rate']+(spec['taker_bps']+spec['liquidation_bps'])/10000)
    if margin>=.8*future or reserve>=.8*future:return None,'margin_reserve'
    return q,''


def risk_reason(account,quantities,detail,specs,liquidated=False):
    eq=account['binance_equity'];marks=detail['marks']
    if liquidated or detail.get('liquidation_before_callback',False):return 'actual_liquidation'
    if not math.isfinite(eq) or eq<=80000:return 'equity_floor'
    if account['binance_available_margin']<=0:return 'nonpositive_available'
    if account['binance_margin_used']>=.8*eq:return 'margin_utilization'
    if account['binance_gross_exposure']>.5*eq+EPS:return 'gross_limit'
    if any(abs(q)*marks[i]>.25*eq+EPS for i,q in quantities.items()):return 'position_limit'
    reserve=account['maintenance_margin']+sum(abs(q)*marks[i]*(specs[i]['taker_bps']+specs[i]['liquidation_bps'])/10000 for i,q in quantities.items())
    if reserve>=.8*eq:return 'maintenance_close_reserve'
    if any(abs(q)>=EPS and (not math.isfinite(marks[i]) or marks[i]<=0) for i,q in quantities.items()):return 'invalid_current_mark'
    return None


def verify_policy(features,diagnostics,preopen,accounts,detail,specs,events,fills,begin,stop,config,completed=()):
    """Audit all callbacks; bounded idle omissions, not complete cleanup replay.

    detail[clock] contains independent marks, average_prices, and a boolean
    liquidation_before_callback. preopen/accounts come from financial replay.
    """
    begin,stop=stamp(begin),stamp(stop);ids={iid(s) for s in SYMBOLS};byid={s['id']:s for s in specs}
    check(set(features)==set(byid)==ids,'Exact eight native policy streams/catalog required')
    records=diagnostics['events'] if isinstance(diagnostics,dict) else diagnostics
    groups=defaultdict(list);last=begin
    for r in records:
        t=stamp(r['timestamp']);check(begin<=t<stop and t>=last,'Recorded diagnostic order/phase differs');last=t;groups[t].append(r)
    eventrows=events.to_dict('records') if isinstance(events,pd.DataFrame) else list(events)
    fillrows=fills.to_dict('records') if isinstance(fills,pd.DataFrame) else list(fills)
    submissions={};accepted={};terminal={};fillby=defaultdict(list);liquidation_clocks=[]
    for e in eventrows:
        oid=e.get('order_id');t=stamp(e['timestamp']);typ=e['type']
        if typ=='LIQUIDATION':liquidation_clocks.append(t)
        if typ=='ORDER_SUBMITTED':check(oid not in submissions,'Duplicate actual order identity');submissions[oid]=e
        elif typ=='ORDER_ACCEPTED':accepted[oid]=t
        elif typ in ('ORDER_FILLED','ORDER_CANCELLED','ORDER_REJECTED'):terminal[oid]=(t,typ)
    for f in fillrows:fillby[f['order_id']].append(f)
    public_changes=sorted([(stamp(e['timestamp']),n,e['type'],e['order_id']) for n,e in enumerate(eventrows) if e['type'] in ('ORDER_ACCEPTED','ORDER_FILLED','ORDER_CANCELLED','ORDER_REJECTED')],key=lambda x:(x[0],x[1]))
    current_live=set();change_cursor=0
    def live_at(clock):return set(current_live)
    def filled_at(oid,clock):return oid in terminal and terminal[oid][0]<clock and terminal[oid][1]=='ORDER_FILLED'
    def fill_visible(oid,clock):return [f for f in fillby[oid] if stamp(f['timestamp'])<clock]
    known=set();previous_clock=begin;state='IDLE';cold=None;tx=None;held=None;entries={};closures={};observed_proposals=0;idle_reviews=0;omissions=0;callbacks=0
    delta=pd.Timedelta(milliseconds=config.get('latency_ms',0))+config['execution_delay_bars']*MIN
    clock=pd.date_range(begin+MIN,stop,freq='min',inclusive='left').as_unit('ns')
    check(set(groups)<=set(clock),'Diagnostic outside a real minute callback')
    for now in clock:
        recent_accepted=set()
        while change_cursor<len(public_changes) and public_changes[change_cursor][0]<now:
            _,_,typ,oid=public_changes[change_cursor]
            if typ=='ORDER_ACCEPTED':current_live.add(oid);recent_accepted.add(oid)
            else:current_live.discard(oid)
            change_cursor+=1
        callbacks+=1;check(now in preopen and now in accounts and now in detail,'Missing independently reconstructed callback state')
        q=preopen[now];a=accounts[now];d=detail[now];actual=groups.get(now,[]);kinds=[r['type'] for r in actual]
        flat=all(q[i]==0 for i in ids) and not live_at(now)
        liquidated=any(previous_clock<=t<now for t in liquidation_clocks)
        risk=risk_reason(a,q,d,byid,liquidated)
        if risk and state not in ('ABORTING','BLOCKED'):
            check(('ACCOUNT_ABORT' if tx or held or not flat or risk=='actual_liquidation' else 'ACCOUNT_RISK_BLOCKED') in kinds,'Omitted actual account risk response')
        if state=='HOLDING' and held and any(abs(q[i]-v)>max(EPS,byid[i]['lot_size']*1e-6) for i,v in held['targets'].items()):
            check('ACCOUNT_ABORT' in kinds,'Omitted unexpected holding native quantity abort')
        if now==stop-10*MIN:check(kinds.count('TERMINAL_EXIT_REQUEST')==1,'Omitted/duplicate ten-minute terminal request')
        if cold is not None and now>=cold and state=='COOLDOWN':state='IDLE'
        unknown_before=(recent_accepted-known)|(live_at(now)-known)
        if unknown_before and state not in ('ABORTING','BLOCKED'):check('ACCOUNT_ABORT' in kinds,'Omitted unowned accepted/live order abort')
        selected=(held or (tx if tx and tx['transition']=='ENTERING' else {}) or {}).get('instrument_id')
        if state not in ('EXITING','ABORTING','BLOCKED') and any(v!=0 and (i!=selected or v<0) for i,v in q.items()):
            check(any(r['type']=='ACCOUNT_ABORT' and r['reason']=='unexpected_native_inventory' for r in actual),'Omitted unexpected native inventory abort')
        # Mandatory feature/price/holding checks while a recorded target remains active.
        required=None
        plan=held or (tx if tx and tx['transition']=='ENTERING' else None)
        if plan and state in ('HOLDING','ENTERING'):
            row=feature_at(features[plan['instrument_id']],now);avg=d['average_prices'][plan['instrument_id']]
            required='invalid_or_stale_feature' if row is None else ('closed_price_adverse_two_percent' if q[plan['instrument_id']]>0 and avg>0 and row.price<=avg*.98 else ('four_hour_hold' if held and now>=held['completed_at']+HOLD else None))
            if required and not risk and now<stop-10*MIN:
                wanted='ACCOUNT_ABORT' if state=='ENTERING' else 'EPISODE_EXIT'
                check(wanted in kinds,'Omitted mandatory minute exit/partial-entry abort')
                r=next(r for r in actual if r['type']==wanted)
                check(r['reason']==('partial_entry_'+required if state=='ENTERING' else required),'Mandatory minute exit reason differs')
        if tx and now<stop-10*MIN and not any(k in kinds for k in ('ACCOUNT_ABORT','EPISODE_EXIT')):
            resolved=all(abs(q[i]-v)<=max(EPS,byid[i]['lot_size']*1e-6) for i,v in tx['targets'].items())
            if tx['transition']=='ENTERING':resolved=resolved and all(filled_at(o,now) for o in tx['order_ids'])
            if resolved:
                check(('ENTRY_COMPLETE' if tx['transition']=='ENTERING' else 'NORMAL_FLAT') in kinds,'Omitted actual target completion')
            elif now>=stamp(tx['deadline']):check('ACCOUNT_ABORT' in kinds,'Omitted immutable five-minute timeout abort')
        # Eligibility omission checks are exhaustive only for resolved, audited idle windows.
        review=now.minute%5==0 and now.second==now.microsecond==now.nanosecond==0
        if state=='IDLE' and flat and now<stop-HOLD-10*MIN and review:
            idle_reviews+=1;chosen=[s for s in SYMBOLS if eligible(feature_at(features[iid(s)],now))]
            if chosen and not risk:
                check(kinds.count('EVENT_PROPOSAL')==1,'Omitted/duplicate eligible flat review proposal');omissions+=1
            elif not chosen:check('EVENT_PROPOSAL' not in kinds,'Proposal without current eligibility')
        for r in actual:
            typ=r['type']
            if typ=='EVENT_PROPOSAL':
                check(review and now<stop-HOLD-10*MIN and state=='IDLE' and flat,'Entry review busy, cooldown, nonflat, offclock or final window')
                chosen=[s for s in SYMBOLS if eligible(feature_at(features[iid(s)],now))]
                check(chosen and r['symbol']==chosen[0] and r['eligible_symbols']==chosen,'Current eligibility/stable priority differs');observed_proposals+=1
                row=feature_at(features[iid(chosen[0])],now);target,why=admission(row,a,d['marks'][iid(chosen[0])],byid[iid(chosen[0])],config)
                following=actual[actual.index(r)+1:]
                refused=[x for x in following if x['type']=='ADMISSION_REJECTED'];opened=[x for x in following if x['type']=='TARGET_SUBMITTED' and x['transition']=='ENTERING']
                if why:check(len(refused)==1 and refused[0]['reason']==why and refused[0]['symbol']==chosen[0] and not opened,'Missing/extraneous genuine admission rejection')
                else:
                    check(len(opened)==1 and not refused,'Eligible admitted proposal omitted entry target or falsely refused')
                    entry=opened[0]
                    expected={i:0. for i in ids};expected[iid(chosen[0])]=target
                    check(set(entry['targets'])==ids,'Native target namespace differs')
                    for i in ids:same(entry['targets'][i],expected[i],'Fresh native ten-percent target differs')
            elif typ=='ADMISSION_REJECTED':
                check(kinds.count('EVENT_PROPOSAL')==1 and not any(x['type']=='TARGET_SUBMITTED' and x['transition']=='ENTERING' for x in actual),'Rejection lacks unique current failed proposal');cold=now+HOUR;check(stamp(r['cooldown_until'])==cold,'Failed admission cooldown differs');state='COOLDOWN'
            elif typ=='TARGET_SUBMITTED':
                check(r['transition'] in ('ENTERING','EXITING') and stamp(r['deadline'])==now+delta+5*MIN,'Immutable five-minute target deadline differs')
                targets=r['targets'];check(set(targets)==ids,'Exact target namespace required');orders=r['order_ids'];check(len(orders)==len(set(orders)),'Duplicate target order IDs')
                expected_orders={i for i in ids if targets[i]!=q[i] and (r['transition']=='EXITING' or abs(targets[i]-q[i])>max(EPS,byid[i]['lot_size']*1e-6))}
                check({submissions[o]['instrument_id'] for o in orders}==expected_orders and len(orders)==len(expected_orders),'Actual immutable order set differs')
                for oid in orders:
                    o=submissions[oid];i=o['instrument_id'];change=targets[i]-q[i]
                    check(stamp(o['timestamp'])==now and stamp(o['active_at'])==now+delta and o['tif']=='GTC' and o['order_type']=='market' and bool(o['reduce_only'])==(r['transition']=='EXITING'),'Actual order clock/type/reduce-only differs')
                    check(o['side']==(1 if change>0 else -1),'Actual order side differs');same(o['quantity'],abs(change),'Actual immutable target quantity differs')
                known.update(orders);state=r['transition'];tx=dict(r,submitted_at=now)
                if state=='ENTERING':
                    check(flat and 'EVENT_PROPOSAL' in kinds and len(orders)==1,'Entry not one actual flat native instrument');tx['instrument_id']=submissions[orders[0]]['instrument_id']
                else:
                    check(all(v==0 for v in targets.values()),'Exit target is not actual flat')
                    check(any(x['type']=='EPISODE_EXIT' for x in actual[:actual.index(r)]),'Actual close target lacks recorded applicable exit intent')
            elif typ=='ENTRY_COMPLETE':
                check(tx and tx['transition']=='ENTERING' and all(filled_at(o,now) for o in tx['order_ids']),'Entry completion without actually filled order')
                visible=[f for o in tx['order_ids'] for f in fill_visible(o,now)];check(visible,'Entry completion without actual fill')
                final=max(stamp(f['timestamp']) for f in visible);check(final<=stamp(tx['deadline']) and stamp(r['completed_at'])==final and stamp(r['observed_completed_at'])==now,'Actual entry completion timing differs')
                check(r['generation']==tx['generation'] and r['instrument_id']==tx['instrument_id'] and r['targets']==tx['targets'],'Completion changed immutable selected identity/target/generation')
                for i in ids:same(q[i],tx['targets'][i],'Completion actual native vector differs')
                same(r['average_entry_price'],d['average_prices'][tx['instrument_id']],'Actual entry VWAP differs')
                check(r['generation'] not in entries,'Duplicate completed generation');entries[r['generation']]=dict(r);held=dict(r,completed_at=final);tx=None;state='HOLDING'
            elif typ=='EPISODE_EXIT':
                check(any(x['type']=='TARGET_SUBMITTED' and x['transition']=='EXITING' for x in actual[actual.index(r)+1:]),'Exit diagnostic omitted actual immutable close target')
                check(held is not None or now>=stop-10*MIN,'Exit without held episode')
                if r['reason']=='terminal_ten_minutes':check(now==stop-10*MIN,'Terminal close timing differs')
                else:check(r['reason']==required and required is not None and not risk,'Recorded held exit precedes actual hold/adverse/stale condition or changes precedence')
            elif typ in ('NORMAL_FLAT','ABORT_FLAT'):
                check(flat,'Cooldown starts before actual flat/resolved orders')
                if typ=='NORMAL_FLAT':check(tx is not None and tx['transition']=='EXITING','Normal-flat cooldown lacks actual exit transaction')
                else:check(state in ('ABORTING','BLOCKED'),'Abort-flat cooldown lacks recorded abort state')
                if typ=='NORMAL_FLAT' and held:check(held['generation'] in closures and any(x['type']=='EPISODE_CLOSED' and x.get('failed') is False and x['generation']==held['generation'] for x in actual),'Actual normal fully entered close omitted completed episode')
                cold=now+HOUR;check(stamp(r['cooldown_until'])==cold,'Actual flat one-hour cooldown differs');state='COOLDOWN';tx=None;held=None
            elif typ=='ACCOUNT_ABORT':
                check(stamp(r['cleanup_deadline'])==now+delta+5*MIN,'Abort cleanup deadline differs')
                if r['reason'].startswith('partial_entry_'):check(required is not None and r['reason']=='partial_entry_'+required,'Recorded partial-entry exit reason is not then applicable')
                if risk:check(r['reason']==risk or r['reason'] in ('unowned_live_order','unowned_order_event','unexpected_native_inventory'),'Abort account-risk reason differs')
                if tx:
                    for oid in tx['order_ids']:
                        if oid in live_at(now):check(oid in terminal and terminal[oid][0]==now and terminal[oid][1]=='ORDER_CANCELLED','Abort did not actually cancel pending immutable transaction')
                state='ABORTING';tx=None
            elif typ=='EPISODE_CLOSED':
                if r.get('failed') is False and r.get('entry_completed_at') is not None:
                    check(flat and r['generation'] in entries and r['generation'] not in closures,'Counterfeit/duplicate completed closed episode')
                    check(stamp(r['entry_completed_at'])==stamp(entries[r['generation']]['completed_at']),'Closed episode changed completed entry');closures[r['generation']]=dict(r)
            elif typ=='TERMINAL_EXIT_REQUEST':check(now==stop-10*MIN,'Terminal request missing exact ten-minute clock')
            elif typ=='TERMINAL_FLAT':check(flat and now>=stop-10*MIN,'Terminal flat is fabricated');state='IDLE';held=None;tx=None
        # Every entering/holding quantity mismatch and accepted foreign event needs a real abort.
        unknown=(recent_accepted-known)|(live_at(now)-known)
        if unknown and state not in ('ABORTING','BLOCKED'):
            check('ACCOUNT_ABORT' in kinds,'Unowned accepted order omitted abort')
        if state in ('ABORTING','BLOCKED'):
            for oid,o in submissions.items():
                if stamp(o['timestamp'])!=now or oid in known:continue
                i=o['instrument_id'];check(bool(o['reduce_only']) and o['side']==(-1 if q[i]>0 else 1) and q[i]!=0,'Cleanup order opens or selects unexplained inventory')
                same(o['quantity'],abs(q[i]),'Cleanup immutable actual residual quantity differs');known.add(oid)
        previous_clock=now
    claimed={r['generation']:r for r in completed};check(len(claimed)==len(completed) and set(claimed)==set(closures),'Completed episode export omitted or invented successful closure')
    for gen,row in claimed.items():
        for key,value in row.items():
            expected=closures[gen][key]
            if key.endswith('_at'):check(stamp(value)==stamp(expected),'Closed episode export clock differs')
            elif isinstance(value,(float,int)) and not isinstance(value,bool):same(value,expected,'Closed episode export differs')
            else:check(value==expected,'Closed episode export differs')
    return dict(recorded_policy_reconstruction_passed=True,all_callback_clocks_examined=True,callback_clocks=callbacks,
        resolved_idle_review_clocks_checked=idle_reviews,eligible_idle_proposals_checked=omissions,recorded_proposals=observed_proposals,
        actual_completed_entries=len(entries),actual_completed_closed_episodes=len(closures),
        full_cleanup_state_reconstruction_passed=False,all_unlogged_abort_transitions_proved=False,
        scope='Recorded eligibility, stable priority, admission, immutable actual orders, actual completions/closures and mandatory held/partial feature exits; eligible omissions checked in resolved audited idle windows.',
        limitations=['Cleanup/BLOCKED state transitions are not independently simulated exhaustively. Omission completeness outside resolved audited idle windows is not proved.',
                     'Certified inputs retain assumed source availability and reused-year vintage limits.'])


def verify_cohort(perp_cache,metrics_cache,out,source_anchor,input_anchor,feature_audit,financial_audit):
    """Offline composition with an existing independent financial certificate.

    Replays ledger arithmetic only; no Engine or strategy execution. Invoke only
    after separately authorized actual output audit and synthetic source review.
    """
    import hashlib
    import json
    from pathlib import Path
    from audit import verify_positioning_outputs as financial
    perp_cache,metrics_cache,out=map(Path,(perp_cache,metrics_cache,out))
    digest=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
    load=lambda path:json.loads(Path(path).read_bytes())
    own=Path(__file__).resolve();financial_path=Path(financial.__file__).resolve()
    # Pin receipts before validation, including fields not used semantically.
    financial_hash=digest(financial_audit);feature_hash=digest(feature_audit)
    own_hash=digest(own);financial_source=digest(financial_path)
    lock=load(out/'source_lock.json')
    before=financial.evidence_hashes(out,lock,feature_audit)
    before.update({str(own):own_hash,str(Path(financial_audit).resolve()):financial_hash})
    cert=load(financial_audit)
    check(cert.get('complete') is True and cert.get('errors')==[] and cert.get('financial_reconstruction_complete') is True and cert.get('complete_financial_scope') is True and cert.get('gates_reconstructed') is True and cert.get('candidate_count_cumulative')==28,'Passing complete separate financial certificate required')
    check(cert.get('policy_reconstruction_complete') is False and cert.get('recorded_policy_reconstruction_complete') is False and cert.get('publication_ready') is False,'Financial evidence must retain honest policy scope')
    check(cert.get('source_anchor')==source_anchor and cert.get('input_anchor')==input_anchor and cert.get('auditor_sha256')==financial_source,'Financial source/anchor binding differs')
    for flag in ('source_unchanged_during_audit','input_unchanged_during_audit','features_unchanged_during_audit','auditor_source_unchanged','reference_source_unchanged','all_phase_evidence_unchanged'):
        check(cert.get(flag) is True,'Financial proof stability missing: '+flag)
    check(cert.get('reference_helper_sha256')==digest(financial.REPO/'audit/verify_funding_rank_outputs.py'),'Financial arithmetic helper changed')
    financial.packet_guard(perp_cache,metrics_cache,out,source_anchor,input_anchor)
    featurecert=financial.verify_feature_certificate(out,feature_audit,source_anchor,input_anchor)
    for field,name in [('source_lock_sha256','source_lock.json'),('input_verification_sha256','input_verification.json'),('feature_receipt_sha256','feature_receipt.json'),('published_lock_sha256','published_lock.json'),('summary_sha256','summary.json')]:
        check(cert.get(field)==digest(out/name),'Financial common packet differs: '+field)
    check(cert.get('feature_audit_sha256')==feature_hash and cert.get('feature_auditor_sha256')==digest(financial.REPO/financial.FEATURE_AUDITOR) and cert.get('features_sha256')==featurecert['features_sha256'],'Financial causal feature proof differs')
    check(set(cert.get('phases',{}))=={p[0] for p in financial.PHASES},'Exact five financial phases required')
    allfeatures={v:{i:pd.read_parquet(path) for i,path in group.items()} for v,group in financial.native_feature_paths(out).items()}
    phases={}
    for name,begin,stop,stress in financial.PHASES:
        folder=out/'trials'/name;proof=cert['phases'][name]
        hashes={n:digest(folder/n) for n in financial.OUTPUTS};completion=digest(folder/'completion.json')
        check(proof.get('outputs_sha256')==hashes and proof.get('completion_sha256')==completion and proof.get('trajectory_reconstruction_passed') is True,'Financial phase seal/reconstruction differs')
        metadata=load(folder/'metadata.json');specs=metadata['instruments'];config=metadata['engine']
        tables={n:pd.read_parquet(folder/(n+'.parquet')) for n in financial.LEDGERS};exposure=pd.read_parquet(folder/'exposure.parquet')
        bars={};funding=[]
        for symbol in SYMBOLS:
            b=pd.read_parquet(perp_cache/symbol/'bars.parquet');f=pd.read_parquet(perp_cache/symbol/'funding.parquet')
            bars[iid(symbol)]=b[b.timestamp.ge(begin)&b.timestamp.lt(stop)].reset_index(drop=True)
            funding.append(f[f.timestamp.ge(begin)&f.timestamp.le(stop)])
        state,preopen=financial.reconstruct(tables,exposure,bars,pd.concat(funding,ignore_index=True),specs,config,begin,stop)
        diagnostics=load(folder/'strategy_diagnostics.json');closed=load(folder/'completed_episodes.json')
        financial.verify_completed_episodes(closed,diagnostics,preopen,tables,begin,stop)
        record=verify_policy(allfeatures['delayed' if stress else 'baseline'],diagnostics,preopen,state.preopen_account,state.preopen_detail,specs,tables['events'],tables['fills'],begin,stop,config,closed)
        phases[name]=dict(outputs_sha256=hashes,completion_sha256=completion,**record)
        del state,preopen,bars,tables,exposure
    after=financial.evidence_hashes(out,lock,feature_audit)
    after.update({str(own):digest(own),str(Path(financial_audit).resolve()):digest(financial_audit)})
    check(before==after and digest(financial_path)==financial_source and digest(feature_audit)==feature_hash,'Policy/financial/helper/source/input/features/output evidence changed during policy audit')
    financial.packet_guard(perp_cache,metrics_cache,out,source_anchor,input_anchor)
    final=financial.evidence_hashes(out,lock,feature_audit)
    final.update({str(own):digest(own),str(Path(financial_audit).resolve()):digest(financial_audit)})
    check(final==before and digest(financial_path)==financial_source,'Evidence changed during final provenance guard')
    return dict(complete=True,errors=[],recorded_policy_reconstruction_complete=True,policy_reconstruction_complete=False,
        full_cleanup_state_reconstruction_passed=False,all_unlogged_abort_transitions_proved=False,publication_ready=False,
        source_anchor=source_anchor,input_anchor=input_anchor,auditor_path='audit/verify_positioning_policy.py',auditor_sha256=own_hash,
        financial_audit_sha256=financial_hash,financial_auditor_sha256=financial_source,reference_helper_sha256=cert['reference_helper_sha256'],feature_audit_sha256=feature_hash,
        source_lock_sha256=cert['source_lock_sha256'],input_verification_sha256=cert['input_verification_sha256'],published_lock_sha256=cert['published_lock_sha256'],
        feature_receipt_sha256=cert['feature_receipt_sha256'],features_sha256=featurecert['features_sha256'],summary_sha256=cert['summary_sha256'],
        source_unchanged_during_audit=True,input_unchanged_during_audit=True,features_unchanged_during_audit=True,auditor_source_unchanged=True,
        financial_source_unchanged=True,all_phase_evidence_unchanged=True,phases=phases,completed_at_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        scope='All minute callback clocks examined; recorded eligibility/priority/admission/orders/actual completions and closures/mandatory feature exits; omitted eligible proposals checked in resolved audited idle windows.',
        limitations=['Full ABORTING/BLOCKED cleanup transition simulation and omission completeness outside resolved audited idle windows are not proved.',
                    'Passing scoped policy plus financial reconstruction does not establish historical delivery/units/vintage, untouched validation or profitability.'])


def main():
    import argparse,json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('perp-cache','metrics-cache','out','source-anchor','input-anchor','feature-audit','financial-audit','certificate'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();destination=Path(args.certificate);check(not destination.exists(),'Fresh policy certificate path required')
    result=verify_cohort(args.perp_cache,args.metrics_cache,args.out,args.source_anchor,args.input_anchor,args.feature_audit,args.financial_audit)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print('Scoped independent recorded policy reconstruction passed; full cleanup-state proof remains false.')


if __name__=='__main__':main()
