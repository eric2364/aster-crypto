class BaseStrategy:
    version = '1'
    def on_bar(self, context, bar): pass
    def on_bars(self, context, bars): pass
    def on_funding(self, context, event): pass
