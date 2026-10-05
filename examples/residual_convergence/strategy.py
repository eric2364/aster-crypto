"""Central non-atomic native-perpetual execution; no estimation or data loading."""
from collections import Counter
import math
import pandas as pd
from aster.backtest.models import Order
from aster.backtest.execution import adverse_price, floor_step
from aster.strategies.base import BaseStrategy

SYMBOLS = ('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
ALTS = SYMBOLS[2:]
BUDGET = 100000 * .25 / 6
EPS = 1e-9


def entry_plan(symbol, model, prices, direction, instruments, z, budget=BUDGET):
    """Return a rounded unnetted basket and conservative stress-cost admission."""
    if symbol not in ALTS or direction not in (-1,1): raise ValueError('Invalid entry identity/direction')
    if not model.get('eligible',False): return None,'ineligible_model'
    values = [float(model[k]) for k in ['beta_btc','beta_eth','alpha','phi','sigma']]
    b,e,alpha,phi,sigma = values
    if not all(math.isfinite(v) for v in [*values,float(z),float(budget)]) or sigma<=0 or not 0<phi<1 or abs(b)+abs(e)>4:
        return None,'invalid_model'
    if budget<=0: return None,'invalid_budget'
    ideal = budget/(1+abs(b)+abs(e))
    dollars = {symbol:direction*ideal,'BTCUSDT':-b*direction*ideal,'ETHUSDT':-e*direction*ideal}
    quantities = {}; notionals = {}
    for leg, amount in dollars.items():
        spec = instruments[leg]; price=float(prices[leg])
        if not math.isfinite(price) or price<=0: return None,'invalid_price'
        if amount == 0: quantities[spec.id]=0.; notionals[leg]=0.; continue
        quantity = math.copysign(floor_step(abs(amount)/price,spec.lot_size),amount)
        if abs(quantity)<spec.min_quantity-EPS or abs(quantity)*price<spec.min_notional-EPS:
            return None,f'opening_minimum:{leg}'
        quantities[spec.id]=quantity; notionals[leg]=abs(quantity)*price
    alt_notional=notionals[symbol]
    # Fixed joint-stress roundtrip: two sides x (10bps fee +16bps slip).
    cost=.0052*sum(notionals.values())/alt_notional
    recovery=max(0.,(abs(z)*sigma-.5*sigma)*(1-phi**48)-abs(alpha)*48)
    if recovery<2*cost: return None,'stress_cost_filter'
    return {'symbol':symbol,'direction':direction,'quantities':quantities,
            'rounded_notionals':notionals,'expected_recovery':recovery,'stress_roundtrip_cost':cost,
            'entry_z':float(z),'beta_btc':b,'beta_eth':e},''


class ResidualPortfolio(BaseStrategy):
    """One controller, immutable GTC target transactions and actual abort cleanup."""
    version='fixed-residual-convergence-1'

    def __init__(self, models, features, stop):
        self.models=models
        if set(models.get('assets',{}))!=set(ALTS): raise ValueError('Require all six declared asset models')
        self.features=features.copy()
        clock=pd.DatetimeIndex(features.index)
        if clock.tz is None or clock.hasnans or clock.has_duplicates or not clock.is_monotonic_increasing:
            raise ValueError('Features require unique sorted UTC-aware availability times')
        self.features.index=clock.tz_convert('UTC').as_unit('ns')
        required={f'price_{s}' for s in SYMBOLS}|{f'z_{s}' for s in ALTS}
        if not required<=set(features.columns): raise ValueError('Missing synchronized price/z features')
        self.stop=pd.Timestamp(stop)
        if self.stop.tzinfo is None: raise ValueError('Stop must be timezone aware')
        self.stop=self.stop.tz_convert('UTC')
        self.state='IDLE'; self.active={}; self.transaction=None
        self.cleanup_orders={}; self.global_cooldown_until=None; self.local_cooldown_until={}
        self.diagnostics=[]; self.admission_failures=Counter(); self.generation=0
        self._event_cursor=0; self.instruments=None; self.blocked=set(); self._abort_stops=set()

    def _catalog(self, context):
        if self.instruments is not None: return
        by_symbol={s.symbol:s for s in context.instruments.values()}
        self.instruments={label:by_symbol['1000PEPEUSDT' if label=='PEPEUSDT' else label] for label in SYMBOLS}
        if len(context.instruments)!=8 or any(s.market_type!='perpetual' or s.exchange!='binance' for s in self.instruments.values()):
            raise ValueError('Require exactly eight native Binance perpetual instruments')

    def _log(self, context, kind, **values):
        self.diagnostics.append(dict(timestamp=context.now,kind=kind,generation=self.generation,**values))

    def _tolerance(self, iid):
        return max(EPS,self._by_id[iid].lot_size*1e-6)

    @property
    def _by_id(self): return {s.id:s for s in self.instruments.values()}

    def _actual(self, context): return {iid:float(p.quantity) for iid,p in context.positions.items()}

    def _targets(self, baskets):
        result={s.id:0. for s in self.instruments.values()}
        for basket in baskets.values():
            for iid,q in basket['quantities'].items(): result[iid]+=q
        for iid,q in result.items():
            step=self._by_id[iid].lot_size
            rounded=round(q/step)*step
            if abs(q-rounded)>self._tolerance(iid): raise ValueError('Net target left native grid')
            result[iid]=0. if abs(rounded)<EPS else rounded
        return result

    def _feature(self, now):
        return self.features.loc[now] if now in self.features.index else None

    def _exit_reason(self, basket, feature, now):
        if feature is not None:
            z=float(feature[f'z_{basket["symbol"]}'])
            if not math.isfinite(z): return 'invalid_active_feature'
            if abs(z)>=4: return 'stop'
        if now-basket['submitted_at']>=pd.Timedelta(hours=48): return 'maximum_hold'
        if feature is not None and (abs(z)<=.5 or basket['direction']*z>=0): return 'equilibrium'
        return None

    def _preflight(self, context, targets):
        actual=self._actual(context); config=context.portfolio.config
        fees=required=slip=0.; eq=context.portfolio.equity()
        for iid,target in targets.items():
            spec=self._by_id[iid]; old=actual[iid]; delta=target-old
            if abs(delta)<=self._tolerance(iid): continue
            qty=floor_step(abs(delta),spec.lot_size)
            if abs(qty-abs(delta))>self._tolerance(iid) or qty<spec.min_quantity-EPS: return False,'delta_quantity_minimum'
            mark=float(context.portfolio.marks.get(iid,context.positions[iid].average_price))
            if not math.isfinite(mark) or mark<=0: return False,'missing_current_mark'
            side=1 if delta>0 else -1
            price=adverse_price(mark,side,spec,config,qty,None)
            closing=min(abs(old),qty) if old*delta<0 else 0.
            opening=qty-closing
            if opening>EPS and (opening<spec.min_quantity-EPS or opening*price<spec.min_notional-EPS):
                return False,'delta_opening_minimum'
            fees+=qty*price*spec.taker_bps/10000
            required+=opening*price/config.leverage
            slip+=max(0.,side*(price-mark)*qty)
        # Do not spend reserves/pnl that sibling closing orders might release later.
        if required+fees>context.portfolio.available('binance')+EPS: return False,'joint_available_margin'
        future_eq=eq-fees-slip
        gross=sum(abs(q)*context.portfolio.marks.get(iid,0) for iid,q in targets.items())
        if future_eq<=0 or gross>future_eq*config.max_gross_leverage+EPS: return False,'joint_gross_limit'
        if any(abs(q)*context.portfolio.marks.get(iid,0)>future_eq*config.max_position_pct*config.leverage+EPS for iid,q in targets.items()):
            return False,'joint_position_limit'
        return True,''

    def _begin(self, context, baskets, stops):
        targets=self._targets(baskets); actual=self._actual(context)
        if all(abs(targets[i]-actual[i])<=self._tolerance(i) for i in targets):
            self.active=baskets
            for symbol in stops: self.local_cooldown_until[symbol]=context.now+pd.Timedelta(hours=24)
            return
        self.generation+=1
        ok,reason=self._preflight(context,targets)
        if not ok:
            self._log(context,'PREFLIGHT_REJECTED',reason=reason,targets=targets)
            self._abort(context,reason,stops)
            return
        orders={}
        self.transaction=dict(targets=targets,start=actual,baskets=baskets,stops=set(stops),
                              orders=orders,submitted_at=context.now,deadline=None)
        for iid in sorted(targets):
            delta=targets[iid]-actual[iid]
            if abs(delta)<=self._tolerance(iid): continue
            spec=self._by_id[iid]; quantity=floor_step(abs(delta),spec.lot_size)
            reducing=actual[iid]*delta<0 and quantity<=abs(actual[iid])+self._tolerance(iid)
            order=Order(iid,1 if delta>0 else -1,quantity,tif='GTC',reduce_only=reducing)
            context.order(order); orders[iid]=order
        opening=max(o.active_at.ceil('min') for o in orders.values())
        self.transaction['deadline']=opening+pd.Timedelta(minutes=5)
        self.state='TRANSITION'
        self._log(context,'TARGET_SUBMITTED',targets=targets,deadline=self.transaction['deadline'],
                  order_ids=[o.id for o in orders.values()],symbols=list(baskets))
        if any(o.status=='rejected' for o in orders.values()): self._abort(context,'submission_rejected',stops)

    def _abort(self, context, reason, stops=()):
        if self.transaction:
            for order in self.transaction['orders'].values():
                if order.status in ('accepted','partial'): context.cancel(order.id)
        self._abort_stops.update(stops)
        self.transaction=None; self.state='ABORT'
        deadline=context.now+pd.Timedelta(hours=24)
        self.global_cooldown_until=max(deadline,self.global_cooldown_until) if self.global_cooldown_until is not None else deadline
        self._log(context,'ABORT',reason=reason)
        self._cleanup(context)

    def _cleanup(self, context):
        actual=self._actual(context)
        for iid,q in actual.items():
            order=self.cleanup_orders.get(iid)
            if abs(q)<EPS:
                if order and order.status in ('accepted','partial'): context.cancel(order.id)
                self.cleanup_orders.pop(iid,None)
                continue
            spec=self._by_id[iid]; quantity=floor_step(abs(q),spec.lot_size)
            if quantity<spec.min_quantity-EPS or abs(quantity-abs(q))>self._tolerance(iid):
                if order and order.status in ('accepted','partial'): context.cancel(order.id)
                if iid not in self.blocked: self._log(context,'BLOCKED_RESIDUAL',instrument_id=iid,quantity=q)
                self.blocked.add(iid); continue
            if order and order.status in ('accepted','partial'): continue
            order=Order(iid,-1 if q>0 else 1,quantity,tif='GTC',reduce_only=True)
            context.order(order); self.cleanup_orders[iid]=order
        if all(abs(q)<EPS for q in actual.values()) and not any(o.status in ('accepted','partial') for o in self.cleanup_orders.values()):
            self.active={}; self.cleanup_orders={}; self.state='IDLE'
            self.global_cooldown_until=context.now+pd.Timedelta(hours=24)
            for symbol in self._abort_stops: self.local_cooldown_until[symbol]=context.now+pd.Timedelta(hours=24)
            self._abort_stops.clear()
            self._log(context,'ABORT_FLAT',global_cooldown_until=self.global_cooldown_until)

    def _progress(self, context, feature):
        transaction=self.transaction; actual=self._actual(context)
        stops=set()
        for symbol,basket in transaction['baskets'].items():
            reason=self._exit_reason(basket,feature,context.now)
            if reason:
                if reason=='stop': stops.add(symbol)
                self._abort(context,f'exit_during_transition:{reason}',stops)
                return
        for iid,target in transaction['targets'].items():
            q=actual[iid]; start=transaction['start'][iid]; tolerance=self._tolerance(iid)
            if q<min(start,target)-tolerance or q>max(start,target)+tolerance:
                self._abort(context,'quantity_overshoot'); return
            order=transaction['orders'].get(iid)
            reached=abs(q-target)<=tolerance
            if order and reached and order.status in ('accepted','partial'): context.cancel(order.id)
            if order and not reached and order.status in ('rejected','cancelled'):
                self._abort(context,'unmet_cancelled_target'); return
        if all(abs(actual[i]-q)<=self._tolerance(i) for i,q in transaction['targets'].items()):
            self.active=transaction['baskets']
            for symbol in transaction['stops']: self.local_cooldown_until[symbol]=context.now+pd.Timedelta(hours=24)
            self._log(context,'TARGET_COMPLETE',targets=transaction['targets'])
            self.transaction=None; self.state='HOLDING' if self.active else 'IDLE'
        elif context.now>=transaction['deadline']:
            self._abort(context,'five_attempt_timeout',transaction['stops'])

    def on_bars(self, context, bars):
        self._catalog(context)
        if {b['instrument_id'] for b in bars}!=set(self._by_id): raise ValueError('Incomplete simultaneous eight-instrument slice')
        events=context.portfolio.events[self._event_cursor:]
        self._event_cursor=len(context.portfolio.events)
        liquidation=any(e['type']=='LIQUIDATION' for e in events)
        if liquidation:
            self._abort(context,'actual_liquidation'); return
        if self.state=='ABORT': self._cleanup(context); return
        feature=self._feature(context.now)
        if self.transaction is not None: self._progress(context,feature); return
        exits={}; stops=set()
        for symbol,basket in self.active.items():
            reason=self._exit_reason(basket,feature,context.now)
            if reason:
                exits[symbol]=reason
                if reason=='stop': stops.add(symbol)
        if exits:
            desired={s:b for s,b in self.active.items() if s not in exits}
            self._log(context,'EXIT_INTENT',reasons=exits)
            self._begin(context,desired,stops); return
        if feature is None or context.now>=self.stop-pd.Timedelta(hours=48): return
        if self.global_cooldown_until is not None and context.now<self.global_cooldown_until: return
        prices={symbol:float(feature[f'price_{symbol}']) for symbol in SYMBOLS}
        desired=dict(self.active)
        for symbol in ALTS:
            if symbol in desired: continue
            if symbol in self.local_cooldown_until and context.now<self.local_cooldown_until[symbol]: continue
            z=float(feature[f'z_{symbol}'])
            if not math.isfinite(z) or not 2<=abs(z)<4: continue
            plan,reason=entry_plan(symbol,self.models['assets'][symbol],prices,-1 if z>0 else 1,self.instruments,z)
            if plan is None:
                self.admission_failures[f'{symbol}:{reason}']+=1; continue
            plan['submitted_at']=context.now; desired[symbol]=plan
        if set(desired)!=set(self.active): self._begin(context,desired,set())


ResidualConvergence=ResidualPortfolio
