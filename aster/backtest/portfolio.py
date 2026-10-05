"""Quote-currency accounting. Margin reserves are not cash expenses."""
from collections import defaultdict
import math
from aster.backtest.models import Position

EPS = 1e-9

class Portfolio:
    def __init__(self, instruments, config):
        self.instruments = {x.id:x for x in instruments}
        self.config = config
        if len({x.quote for x in instruments}) != 1:
            raise ValueError('One settlement/reporting currency per run required')
        if any(x.exchange not in config.initial_balances for x in instruments):
            raise ValueError('Every venue needs a funded wallet')
        if any(config.leverage > x.max_leverage for x in instruments if x.market_type == 'perpetual'):
            raise ValueError('Configured leverage exceeds instrument maximum')
        self.cash = dict(config.initial_balances)
        self.positions = {x.id:Position() for x in instruments}
        self.marks = {}
        self.realized = 0.0
        self.fees = 0.0
        self.funding_pnl = 0.0
        self.slippage = 0.0
        self.liquidation_fees = 0.0
        self.turnover = 0.0
        self.fills = []
        self.trades = []
        self.funding = []
        self.events = []

    def event(self, kind, timestamp, iid='', **details):
        spec=self.instruments.get(iid)
        self.events.append({'timestamp':timestamp,'type':kind,'instrument_id':iid,
            'exchange':spec.exchange if spec else '', 'symbol':spec.symbol if spec else '',**details})

    def unrealized(self, iid, mark=None):
        p = self.positions[iid]
        mark = self.marks.get(iid,p.average_price) if mark is None else mark
        return p.quantity * (mark-p.average_price)

    def venue_equity(self, venue):
        value = self.cash[venue]
        for iid,p in self.positions.items():
            s = self.instruments[iid]
            if s.exchange != venue: continue
            if s.market_type == 'spot': value += p.quantity * self.marks.get(iid,p.average_price)
            else: value += self.unrealized(iid)
        return value

    def equity(self): return sum(self.venue_equity(v) for v in self.cash)

    def margin_used(self, venue=None):
        total = 0.0
        for iid,p in self.positions.items():
            s = self.instruments[iid]
            if s.market_type != 'perpetual' or (venue and s.exchange != venue): continue
            total += p.collateral if self.config.margin_mode == 'isolated' else abs(p.quantity)*self.marks.get(iid,p.average_price)/self.config.leverage
        return total

    def available(self, venue):
        if self.config.margin_mode == 'isolated': return self.cash[venue] - self.margin_used(venue)
        # Spot holdings cannot collateralize derivatives in this cash-only model.
        derivative_upl = sum(self.unrealized(iid) for iid in self.positions
                             if self.instruments[iid].exchange == venue and self.instruments[iid].market_type == 'perpetual')
        return self.cash[venue] + derivative_upl - self.margin_used(venue)

    def exposure(self, venue=None):
        long = short = 0.0
        for iid,p in self.positions.items():
            if venue and self.instruments[iid].exchange != venue: continue
            n = p.quantity * self.marks.get(iid,p.average_price)
            if n >= 0: long += n
            else: short -= n
        return long,short

    def admissible(self, iid, side, qty, price, fee):
        s,p = self.instruments[iid],self.positions[iid]
        new = p.quantity + side*qty
        if s.market_type == 'spot':
            if new < -EPS: return False,'spot_short'
            if side > 0 and qty*price+fee > self.available(s.exchange)+EPS: return False,'cash'
        reducing = p.quantity*side < 0 and qty <= abs(p.quantity)+EPS
        if reducing: return True,''
        opening = max(0,qty-abs(p.quantity)) if p.quantity*side < 0 else qty
        released = p.collateral if p.quantity*side < 0 else 0
        realized_close = self.unrealized(iid,price) if p.quantity*side < 0 else 0
        if s.market_type == 'perpetual':
            if self.config.margin_mode == 'cross':
                mark = self.marks.get(iid,price)
                closing = min(qty,abs(p.quantity)) if p.quantity*side < 0 else 0
                pnl = closing*(1 if p.quantity>0 else -1)*(price-p.average_price)
                if p.quantity*side>=0 and abs(new)>EPS:
                    avg = (abs(p.quantity)*p.average_price+qty*price)/abs(new)
                elif opening>0: avg = price
                else: avg = p.average_price
                future_upl = new*(mark-avg)
                other_upl = sum(self.unrealized(i) for i in self.positions if i!=iid
                    and self.instruments[i].exchange==s.exchange and self.instruments[i].market_type=='perpetual')
                old_margin = abs(p.quantity)*mark/self.config.leverage
                new_margin = abs(new)*mark/self.config.leverage
                future_free = self.cash[s.exchange]+pnl-fee+other_upl+future_upl-(self.margin_used(s.exchange)-old_margin+new_margin)
                if future_free < -EPS: return False,'margin'
            else:
                required = opening*price/self.config.leverage+fee
                if required > self.available(s.exchange)+released+realized_close+EPS: return False,'margin'
        mark = self.marks.get(iid,price)
        eq = self.venue_equity(s.exchange)-side*qty*(price-mark)-fee
        long,short = self.exposure(s.exchange)
        current = abs(p.quantity)*self.marks.get(iid,p.average_price)
        gross = long+short-current+abs(new)*mark
        if eq <= 0 or gross > eq*self.config.max_gross_leverage+EPS: return False,'gross_leverage'
        if abs(new)*mark > eq*self.config.max_position_pct*(1 if s.market_type=='spot' else self.config.leverage)+EPS: return False,'position_limit'
        return True,''

    def apply_fill(self, iid, side, quantity, price, timestamp, liquidity, order_type,
                   reference_price=None, exit_reason='strategy', order_id='', forced=False):
        if side not in (-1,1) or not all(math.isfinite(v) and v>0 for v in (quantity,price)):
            raise ValueError('Invalid fill quantity, side or price')
        s,p = self.instruments[iid],self.positions[iid]
        fee = quantity*price*(s.maker_bps if liquidity == 'maker' else s.taker_bps)/10000
        ok,reason = self.admissible(iid,side,quantity,price,fee)
        if not ok and not forced: return False,reason
        old = p.quantity
        signed = side*quantity
        slip = 0 if reference_price is None else side*(price-reference_price)*quantity
        closing = min(abs(old),quantity) if old*signed < 0 else 0.0
        opening = quantity-closing
        close_fraction = closing/abs(old) if closing else 0.0
        close_fee = fee*closing/quantity
        close_slip = slip*closing/quantity
        pnl = closing*(1 if old > 0 else -1)*(price-p.average_price)
        self.cash[s.exchange] += pnl if s.market_type == 'perpetual' else -signed*price
        self.cash[s.exchange] -= fee
        self.realized += pnl
        self.fees += fee
        self.slippage += slip
        self.turnover += quantity*price
        if closing:
            entry_maker = p.maker_fees*close_fraction
            entry_taker = p.taker_fees*close_fraction
            funding = p.funding*close_fraction
            entry_slip = p.slippage*close_fraction
            liquidation_fee = closing*price*s.liquidation_bps/10000 if exit_reason == 'liquidation' else 0
            self.cash[s.exchange] -= liquidation_fee
            self.liquidation_fees += liquidation_fee
            maker_fees = entry_maker + (close_fee if liquidity == 'maker' else 0)
            taker_fees = entry_taker + (close_fee if liquidity == 'taker' else 0)
            self.trades.append({'trade_id':len(self.trades)+1,'exchange':s.exchange,'symbol':s.symbol,
                'instrument_id':iid,'market_type':s.market_type,'direction':'long' if old>0 else 'short',
                'order_type':p.entry_order_type,'liquidity_type':liquidity,'entry_time':p.entry_time,
                'entry_price':p.average_price,'exit_time':timestamp,'exit_price':price,'quantity':closing,
                'leverage':1 if s.market_type=='spot' else self.config.leverage,'gross_pnl':pnl,
                'maker_fees':maker_fees,'taker_fees':taker_fees,'funding_pnl':funding,
                'slippage':entry_slip+close_slip,'liquidation_fee':liquidation_fee,
                'net_pnl':pnl-maker_fees-taker_fees+funding-liquidation_fee,
                'return_pct':(pnl-maker_fees-taker_fees+funding-liquidation_fee)/(closing*p.average_price),
                'holding_seconds':(timestamp-p.entry_time).total_seconds(),'exit_reason':exit_reason})
            p.maker_fees -= entry_maker
            p.taker_fees -= entry_taker
            p.funding -= funding
            p.slippage -= entry_slip
            # Release the closed quantity's share of the isolated reserve.
            # Closed-leg P&L and execution fees have already changed cash above;
            # assigning them again to the remaining reserve transfers the closed
            # leg's result into a different, still-open risk allocation.
            p.collateral *= 1-close_fraction
        if opening:
            if closing: p = Position(); self.positions[iid] = p
            if abs(p.quantity) < EPS or closing:
                p.average_price = price
                p.entry_time = timestamp
                p.entry_order_type = order_type
            else:
                p.average_price = (abs(old)*p.average_price+opening*price)/(abs(old)+opening)
            p.entry_quantity += opening
            open_fee = fee-close_fee
            if liquidity == 'maker': p.maker_fees += open_fee
            else: p.taker_fees += open_fee
            p.slippage += slip-close_slip
            if s.market_type == 'perpetual': p.collateral += opening*price/self.config.leverage
        p.quantity = old+signed
        if abs(p.quantity) < EPS:
            self.positions[iid] = Position()
            self.event('POSITION_CLOSED',timestamp,iid,reason=exit_reason)
        elif abs(old)<EPS or (closing and opening): self.event('POSITION_OPENED',timestamp,iid,quantity=p.quantity)
        self.fills.append({'fill_id':len(self.fills)+1,'order_id':order_id,'timestamp':timestamp,
            'instrument_id':iid,'exchange':s.exchange,'symbol':s.symbol,'market_type':s.market_type,
            'side':side,'quantity':quantity,'price':price,'reference_price':reference_price,
            'liquidity_type':liquidity,'fee':fee,'slippage':slip,'realized_pnl':pnl,'exit_reason':exit_reason})
        self.event('FEE',timestamp,iid,amount=-fee,liquidity_type=liquidity)
        return True,''

    def settle_funding(self, event):
        iid = event['instrument_id']
        p,s = self.positions[iid],self.instruments[iid]
        self.marks[iid] = float(event['mark_price'])
        if abs(p.quantity) < EPS: return
        payment = -p.quantity*float(event['mark_price'])*float(event['funding_rate'])
        self.cash[s.exchange] += payment
        p.funding += payment
        if self.config.margin_mode == 'isolated': p.collateral += payment
        self.funding_pnl += payment
        row = {**event,'exchange':s.exchange,'symbol':s.symbol,'position_size':p.quantity,'funding_payment':payment}
        self.funding.append(row)
        self.event('FUNDING_PAYMENT',event['timestamp'],iid,amount=payment,rate=event['funding_rate'])

    def liquidation_price(self, iid):
        p,s = self.positions[iid],self.instruments[iid]
        if s.market_type!='perpetual' or abs(p.quantity)<EPS or self.config.margin_mode!='isolated': return None
        rate=s.maintenance_rate+(s.taker_bps+s.liquidation_bps)/10000
        q=abs(p.quantity)
        if p.quantity>0:
            if rate>=1:return None
            price=(q*p.average_price-p.collateral)/(q*(1-rate))
        else: price=(q*p.average_price+p.collateral)/(q*(1+rate))
        return max(0,price)

    def maintenance_margin(self, venue=None):
        return sum(abs(p.quantity)*self.marks.get(iid,p.average_price)*self.instruments[iid].maintenance_rate
            for iid,p in self.positions.items() if self.instruments[iid].market_type=='perpetual'
            and (venue is None or self.instruments[iid].exchange==venue))

    def liquidation_candidates(self):
        result = []
        for venue in self.cash:
            ids = [iid for iid,p in self.positions.items() if self.instruments[iid].exchange==venue
                   and self.instruments[iid].market_type=='perpetual' and abs(p.quantity)>EPS]
            if self.config.margin_mode == 'cross':
                equity = self.cash[venue] + sum(self.unrealized(i) for i in ids)
                maintenance = sum(abs(self.positions[i].quantity)*self.marks.get(i,self.positions[i].average_price)*
                    (self.instruments[i].maintenance_rate+(self.instruments[i].taker_bps+self.instruments[i].liquidation_bps)/10000) for i in ids)
                if ids and equity <= maintenance: result.extend(ids)
            else:
                for iid in ids:
                    p,s = self.positions[iid],self.instruments[iid]
                    mark = self.marks.get(iid,p.average_price)
                    maintenance = abs(p.quantity)*mark*(s.maintenance_rate+(s.taker_bps+s.liquidation_bps)/10000)
                    if p.collateral+self.unrealized(iid) <= maintenance: result.append(iid)
        return result

    def snapshot(self, timestamp):
        long,short = self.exposure()
        equity = self.equity()
        unrealized = sum(self.unrealized(i) for i in self.positions)
        used = self.margin_used()
        row = {'timestamp':timestamp,'cash':sum(self.cash.values()),'collateral':used,'margin_used':used,
            'available_margin':sum(self.available(v) for v in self.cash),'maintenance_margin':self.maintenance_margin(),
            'long_exposure':long,'short_exposure':short,
            'gross_exposure':long+short,'net_exposure':long-short,'unrealized_pnl':unrealized,
            'realized_pnl':self.realized,'funding_pnl':self.funding_pnl,'trading_fees':self.fees,
            'slippage_cost':self.slippage,'liquidation_fees':self.liquidation_fees,'equity':equity,
            'gross_leverage':(long+short)/equity if equity>0 else float('nan'),
            'net_leverage':(long-short)/equity if equity>0 else float('nan'),
            'margin_utilization':used/equity if equity>0 else float('nan'),'turnover':self.turnover}
        for venue in self.cash:
            row[f'{venue}_cash'] = self.cash[venue]
            row[f'{venue}_equity'] = self.venue_equity(venue)
        return row
