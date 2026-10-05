# Last-year minute research examples

This study uses **5 October 2025 00:00 UTC through 5 October 2026 00:00 UTC, end exclusive**. This is the latest complete UTC-day year selected for this run, not a multi-year sample. Eight assets: BTC, ETH, DOGE, PEPE, SOL, XRP, LINK and ADA, against USDT. Each has exactly 525,600 real minute bars. Funding observations are predictors for spot trades; these spot positions do not receive funding.

## Reproduce

From the repository root after installation:

```bash
.venv/bin/python examples/minute_research/download.py
.venv/bin/python examples/minute_research/download.py --verify-only
.venv/bin/python examples/minute_research/run.py --workers 2 --out results/minute-study-reproduction
.venv/bin/python examples/minute_research/report.py --run results/minute-study-reproduction --publish results/minute-study-reproduction/compact
.venv/bin/python -m http.server 8765 --bind 127.0.0.1
```

Open `http://127.0.0.1:8765/results/minute-study-reproduction/dashboard.html` after the study completes, or inspect the already saved `evidence/dashboard.html`. Downloads and full ledgers are ignored by Git; compact evidence, trading ledgers and the self-contained report are versioned under `evidence/`. Downloading uses official archive checksums and preserves genuine zero-volume minutes. No exchange account or API key is needed.

The runner is resumable only when code, instrument specifications and data fingerprints match. If any changes, choose a fresh output directory with `--out results/my-new-study`. Do not erase mismatching metadata to reuse old results. `--training-only` stops before forward validation and holdout.

## Candidate families

Five price hypotheses: slow trend hysteresis, Donchian breakout, downside mean reversion, volatility compression breakout and trend pullback. Three factor hypotheses: lagged BTC momentum/catch-up, lagged BTC selloff/reversal and published negative funding with a rebound filter. BTC-leading models retain a BTC cash sleeve rather than claim BTC leads itself. All parameters and trial failures are disclosed.

First six months select one shared duration scale per family from 0.8/1.0/1.2, using pooled training daily Sharpe. The following three months are independent one-month forward validation folds. The final three months form a continuous fresh-wallet historical holdout. Warmup uses earlier observations within this same year. No parameters or assets are chosen using holdout profits. Monthly validation returns are compounded as a diagnostic of separately restarted accounts, not presented as a continuous traded portfolio.

Each asset begins with a separate $12,500 sleeve. A long entry allocates 95% of its equity; entry quantity remains fixed until the cash signal. Sleeve equity sums exactly to the family portfolio. Market orders fill only at eligible next observations, using prior completed volume capacity. Current exchange tick/lot rules approximate historical rules. Baseline fees are 10 bps per side; slippage is 2 bps for majors, 5 for other alts, 8 for DOGE/PEPE. Joint stress doubles fees and slippage, delays one minute, and halves participation. These are stated assumptions, not measured account commissions or spread history.

The result declares a historical hurdle pass only if validation and holdout are net positive, at least two of three anchored holdout months are positive, daily Sharpe is at least 0.5, minute drawdown is at most 20%, joint stress stays positive, all neighboring duration settings stay positive, and at least five of eight symbols are positive. This does not prove lack of overfitting. Conditional seven-day circular block-bootstrap intervals are also reported, including correction for eight family-level holdout tests. One year contains limited independent regimes, and the chosen surviving universe has survivorship bias.

## Read the results

`comparison.csv` gives a compact family summary. `summary.json` contains every gate, each asset, monthly results, neighboring parameter results and confidence intervals. `selection.json` preserves all training choices. `all_trials.json` includes every family/symbol/scale/scenario result, including losers. Versioned trading ledgers include partial closures and final open positions. Full minute equity, all cash flows and provenance remain in the local run directory; rerunning regenerates them. Reports sample charts hourly for readability, while holdout metrics and drawdowns use minute equity.

`docs/leading_factor_research.md` reviews primary academic sources. `docs/leading_factor_sources.md` describes QQQ, inflation and X data feasibility. Their historical inputs were not verified/imported into these models. Cross-market correlation and a paper's published return are not evidence of an executable current strategy edge. Papers published during the historical year make this a retrospective experiment rather than a prospective preregistration. Newly arriving data is needed for a genuinely prospective test.

The original 640 simulations completed before a timestamp-unit error interrupted summary generation. `evidence/executed_runner.py` preserves their exact runner source. Only postprocessing was repaired by casting timestamps to nanosecond precision before assigning the final valuation to its trading day. `analysis_repair.json` records both source hashes. `analyze.py` recovered the existing ledgers after checking every source fingerprint, all 640 distinct trial identities and the original training-only selection; it does not run or retune strategies. The current `run.py` includes this fix for fresh reproductions. Existing old-version caches remain tied to their executed fingerprint.
