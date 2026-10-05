"""Combine completed studies without treating correlated carry policies as independent edges."""
from pathlib import Path
import json
import argparse


def main():
 p=argparse.ArgumentParser();p.add_argument('--price',default='examples/minute_research/evidence');p.add_argument('--carry',default='docs/minute_carry_results');a=p.parse_args()
 price=json.loads((Path(a.price)/'summary.json').read_text());carry=json.loads((Path(a.carry)/'summary.json').read_text())
 intervals=json.loads((Path(a.price)/'combined_selection_diagnostic.json').read_text())
 cases=[]
 for x in price['families']:
  cases.append((x['family'],'price / directional factor',x['validation_compounded_return'],x['holdout'],x['stress'],x['positive_symbols'],x['historical_hurdles_passed'],intervals[x['family']]['bonferroni_13_interval']))
 for x in carry['policies']:
  cases.append((x['policy'],'funding carry',x['validation']['total_return'],x['holdout'],x['stress'],sum(s['total_return']>0 for s in x['symbols'].values()),x['historical_hurdles_passed'],x['bootstrap']['return_interval_bonferroni13policies']))
 lines=['# Last-year minute strategy results','',
  'Actual source period: **5 October 2025–5 October 2026 UTC**, end exclusive. The final three months, **5 July–5 October 2026**, are the historical holdout. All trading, warmup and selection data is confined to this year.', '',
  'Eight underlyings: BTC, ETH, DOGE, PEPE, SOL, XRP, LINK and ADA. Exact coverage: 4,204,800 spot minute candles, 4,204,800 perpetual trade candles and matching mark candles, plus 8,760 settled funding observations. Official archives were checksum-verified; no candles or funding values were interpolated.', '',
  'Thirteen policies were evaluated: eight price/directional-factor hypotheses and five variants of **one funding-carry economic family**. Carry variants are correlated, so their number is not a count of independent edges. All candidates and losers are retained.', '',
  '| Policy | Validation net | Holdout net | Joint stress net | Daily Sharpe | Minute drawdown | Positive assets | Hurdles |',
  '|---|---:|---:|---:|---:|---:|---:|---|']
 for name,family,val,h,s,n,passed,ci in cases:
  sharpe=f"{h['sharpe']:.2f}" if h['sharpe'] is not None else 'undefined'
  lines.append(f"| {name} | {val:.2%} | {h['total_return']:.2%} | {s['total_return']:.2%} | {sharpe} | {h['max_drawdown']:.2%} | {n}/8 | {'PASS' if passed else 'FAIL'} |")
 passes=[x for x in cases if x[6]];positive_ci=[x for x in passes if x[7][0]>0]
 lines.extend(['',f"**{len(passes)} of 13 policies passed every predefined historical hurdle.** {len(positive_ci)} of those also have a positive lower endpoint in the conditional seven-day block-bootstrap interval corrected conservatively for all thirteen policy tests.", '',
  'A historical hurdle pass is not certification that a strategy is non-overfit or will work in another regime. Bootstrap intervals depend on the observed short holdout; they do not remove survivorship bias, literature selection, transaction-cost model error or repeated research choices. Some reviewed papers were published during the sample, so this is retrospective research rather than prospective preregistration.', '',
  '## Evaluation mechanics','',
  'Price/factor models select a single shared duration scale on the first six months only, then use three separate fresh-wallet monthly validation folds and a continuous fresh-wallet final-quarter holdout. Carry policies have fixed defaults with no optimization and use a continuous three-month validation run. Their validation conventions differ and are labelled; no training return is merged into holdout equity.', '',
  'Capital is $100,000 per candidate portfolio, split across eight $12,500 sleeves without transfers. Directional spot entries allocate 95% of current sleeve equity, hold fixed units and pay assumed 10 bps per side. Carry fixes $3,750 notional per leg at entry, long spot and short equivalent perpetual base units with isolated leverage 2; PEPE spot units are explicitly converted to 1000PEPE contract units. Perpetual taker fees assume 5 bps. Actual trading P&L, fees, funding and liquidation costs reconcile in the ledgers.', '',
  'Baseline adverse slippage is 2 bps for BTC/ETH, 5 for other alts and 8 for DOGE/PEPE, with adverse tick rounding. Joint stress doubles fees and slippage, delays execution one minute, and halves prior-volume participation. Carry exits are submitted before the known horizon and use the same constrained engine; unresolved terminal inventory fails the carry gate. Legs fill separately, so carry is not atomic or risk-free.', '',
  'All models consume actual minute candles and execute on minute observations. Price-model entry clocks are 15–60 minutes; carry decisions are daily. Holding periods are longer than one minute. These examples therefore assess strategies on minute data, not demonstrated one-minute scalping.', '',
  'BTC features and published funding observations receive an additional one-minute lag. Funding is only a predictor in the directional spot study; actual funding cashflows are paid or received by the carry perpetual leg. Verified historical QQQ, inflation-surprise and X sentiment inputs were not imported. Their primary sources and publication-time requirements are documented in the research notes.', '',
  '## Files and reproduction','',
  '- [Directional study and compact evidence](../examples/minute_research/README.md)',
  '- [Funding-carry report](minute_carry_results/report.html)',
  '- [Directional report](../examples/minute_research/evidence/dashboard.html)',
  '- [Primary academic research](leading_factor_research.md)',
  '- [Factor data sources](leading_factor_sources.md)',
  '- [Independent validation protocol and audit](minute_validation_protocol.md)',
  '- [User manual](user_manual.md)', '',
  'Full minute equity, trade/fill/event ledgers, open positions and source manifests remain under the ignored local results folders. Compact metrics, trial results, hourly presentation curves and trading/funding ledgers are versioned. The collector and runner commands regenerate full evidence without an account API key. Current exchange instrument rules approximate dated historical rules; the selected survivor universe is not a historically complete exchange universe.', ''])
 Path('docs/minute_strategy_results.md').write_text('\n'.join(lines))
 print('Policies passing all hurdles:',len(passes),'positive adjusted interval:',len(positive_ci))

if __name__=='__main__':main()
