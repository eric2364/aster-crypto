"""Engineering demonstrations. All sizing uses observed closes, fills use future opens."""
from collections import defaultdict, deque
import numpy as np
from aster.strategies.base import BaseStrategy
from aster.backtest.execution import floor_step

class ResearchStrategy(BaseStrategy):
    def __init__(self, allocation=.2, lookback=24, fast=8, slow=24, threshold=.02):
        self.allocation=allocation; self.lookback=lookback; self.fast=fast; self.slow=slow; self.threshold=threshold
        self.prices=defaultdict(lambda:deque(maxlen=max(lookback+1,slow+1,fast+1)))
        self.seen=set()
    def size(self,ctx,iid,price,direction=1):
        spec=ctx.instruments[iid]
        leverage=1 if spec.market_type=='spot' else ctx.portfolio.config.leverage
        return floor_step(max(0,ctx.portfolio.venue_equity(spec.exchange))*self.allocation*leverage/price,spec.lot_size)*direction
    def target(self,ctx,bar,direction):
        if direction<0 and ctx.instruments[bar['instrument_id']].market_type=='spot': direction=0
        ctx.target(bar['instrument_id'],self.size(ctx,bar['instrument_id'],bar['close'],direction))
    def observe(self,bar):
        self.prices[bar['instrument_id']].append(bar['close'])
        return np.asarray(self.prices[bar['instrument_id']])

class BuyHold(ResearchStrategy):
    def on_bar(self,ctx,bar):
        iid=bar['instrument_id']
        if iid not in self.seen:
            self.target(ctx,bar,1); self.seen.add(iid)

class MovingAverage(ResearchStrategy):
    def on_bar(self,ctx,bar):
        a=self.observe(bar)
        if len(a)>=self.slow: self.target(ctx,bar,1 if a[-self.fast:].mean()>a[-self.slow:].mean() else -1)

class RSIMeanReversion(ResearchStrategy):
    def on_bar(self,ctx,bar):
        a=self.observe(bar)
        if len(a)<self.lookback+1:return
        diff=np.diff(a[-self.lookback-1:]); up=np.maximum(diff,0).mean(); down=np.maximum(-diff,0).mean()
        rsi=100 if down==0 and up>0 else 50 if down==up==0 else 100-100/(1+up/down)
        if rsi<30:self.target(ctx,bar,1)
        elif rsi>70:self.target(ctx,bar,-1)
        elif 45<rsi<55:self.target(ctx,bar,0)

class Momentum(ResearchStrategy):
    def on_bar(self,ctx,bar):
        a=self.observe(bar)
        if len(a)>self.lookback:
            change=a[-1]/a[-self.lookback-1]-1
            self.target(ctx,bar,1 if change>self.threshold else -1 if change<-self.threshold else 0)

class Breakout(ResearchStrategy):
    def on_bar(self,ctx,bar):
        a=self.observe(bar)
        if len(a)>self.lookback:
            direction=1 if a[-1]>max(a[:-1]) else -1 if a[-1]<min(a[:-1]) else None
            if direction is not None:self.target(ctx,bar,direction)

class FundingCarry(ResearchStrategy):
    def on_funding(self,ctx,event):
        # This published settlement can influence subsequent holdings, never past payments.
        iid=event['instrument_id']
        if ctx.instruments[iid].market_type!='perpetual':return
        direction=-1 if event['funding_rate']>0 else 1 if event['funding_rate']<0 else 0
        ctx.target(iid,self.size(ctx,iid,event['mark_price'],direction))

class CrossSectionalMomentum(ResearchStrategy):
    def on_bars(self,ctx,bars):
        scores={}
        current={b['instrument_id']:b for b in bars}
        for bar in bars:
            a=self.observe(bar)
            if len(a)>self.lookback:scores[bar['instrument_id']]=a[-1]/a[-self.lookback-1]-1
        if len(scores)<2:return
        ranked=sorted(scores,key=scores.get); count=max(1,len(ranked)//3)
        for iid in ranked:
            d=1 if iid in ranked[-count:] else -1 if iid in ranked[:count] else 0
            self.target(ctx,current[iid],d)

class MarketNeutral(CrossSectionalMomentum):
    """Equal observed quote notional long/short ranked baskets; price drift remains."""

class RelativeValue(ResearchStrategy):
    def __init__(self,**kwargs):super().__init__(**kwargs);self.ratios=deque(maxlen=self.lookback)
    def on_bars(self,ctx,bars):
        if len(bars)!=2:return
        a,b=sorted(bars,key=lambda x:x['instrument_id']);ratio=a['close']/b['close'];self.ratios.append(ratio)
        if len(self.ratios)<self.lookback:return
        avg=np.mean(self.ratios);std=np.std(self.ratios)
        z=(ratio-avg)/std if std>0 else 0
        d=-1 if z>1 else 1 if z<-1 else 0
        self.target(ctx,a,d);self.target(ctx,b,-d)

STRATEGIES={'buy_hold':BuyHold,'ma':MovingAverage,'rsi':RSIMeanReversion,'momentum':Momentum,
            'breakout':Breakout,'funding':FundingCarry,'cross_momentum':CrossSectionalMomentum,
            'neutral':MarketNeutral,'relative_value':RelativeValue}
