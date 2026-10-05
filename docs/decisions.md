# Decision log

| Decision | Alternatives | Evidence / advantages | Disadvantages | Rationale |
|---|---|---|---|---|
| Hybrid research + Python event engine | Pure vectorization; existing framework wrapper | Nautilus event lifecycle; VectorBT arrays | Python loop slower; new engine needs adversarial tests | Keep causal, inspectable accounting while screening efficiently |
| Linear quote-margined contracts first | Inverse, options, dated futures | Derivatives specialist formulas | Narrow initial scope | Reject unsupported types explicitly rather than fake accounting |
| Separate exchange wallets | Global cash pool | Exchange collateral cannot instantly transfer | More capital bookkeeping | Cross-exchange research must honor venue solvency |
| UTC interval-start input | Ambiguous timestamp convention | Candle close unavailable until interval ends | Requires normalization | Prevent same-candle look-ahead |
| Conservative trade-through limits | Touch; stochastic queue; L2 | OHLC does not reveal queue | Underfills relative to some markets | Label assumptions and offer explicit touch alternative |
| Pandas / NumPy / Arrow | Polars, DuckDB, Numba | Stable ecosystem, array signals, Parquet | Memory and Python-loop cost | Profile correctness baseline before optional acceleration |
| Flat configurable maintenance margin | Venue risk tiers | Auditable manual math | Not exact venue emulation | Adapter policy extension and prominent limitation |
| Plotly HTML + Streamlit | Custom frontend | Interactive export and familiar Python dashboard | Streamlit server dependency | Deliver both portable report and exploratory UI |
| Fill P&L already includes slippage | Subtract slippage from realized P&L | Accounting conservation | Diagnostic/pre-cost attribution must be explained | Prevent double counting execution costs |
