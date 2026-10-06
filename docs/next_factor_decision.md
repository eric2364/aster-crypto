# Next factor decision after 26 unsuccessful policies and hypotheses

6 October 2026. The previous goal turn made concrete progress: seven fixed
cross-venue simulations, three scoped independent audits and refreshed
one-year engineering demos were published privately at `aff9591`. They did not
establish any qualified winner. The objective remains four or five successful,
robust strategies on minute crypto data, including DOGE, PEPE and altcoins.

The new independent literature reviews find two testable ideas but no reason
to promise winners:

- [Clock-based return concentration](next_intraday_evidence.md) is distinct from
  another trend threshold. The primary paper's minute-scale effect is small
  relative to our fixed taker costs, and its profitable simulation depends on a
  different venue's volume-based fee reductions. We will not import zero fees
  or claim the published result for our eight assets.
- [Conditional flow reversal](next_flow_evidence.md) differs from unconditional
  flow drift, but temporary pressure and informed continuation can coexist.
  Recent primary evidence finds statistically detectable reversal that fails
  even its cheaper cost benchmark. Reversing our known losing model is not an
  economic justification or an independent successful strategy.

The next concrete input work is **open interest and trader positioning**.
These describe outstanding positions and account/position ratios rather than
past prices or settled funding alone. They may help discriminate risk states,
but do not identify forced liquidations, trader profitability or an eventual
return direction. A fall in reported open-interest value can reflect price,
not a decline in outstanding native quantity. Neither a ratio nor its change
establishes a causal trading rule.

The root downloaded and preserved 48 tiny official daily metrics archives
covering all eight native contracts on the fixed year's first, middle and last
days, plus three days around a reported possible timestamp-definition change.
These are a **sample**, not full-year coverage. Every archive passed its
published checksum; raw row ordering, clock sets and schema were recorded
without constructing predictors or inspecting trading returns. Some physical
CSV row orders are not chronological; future normalization must sort only
after duplicate checks and retain original ordering diagnostics. The original
probe and separate transition receipt remain preserved. An independent source
review is linked below when complete.

The complete collector has now been implemented and independently reviewed,
separately from every frozen experiment. Its intended boundary is 365 daily files per native contract,
5-minute point observations, exact source bodies/checksums/headers and retrieval
receipts, no minute interpolation, and failure on incomplete, malformed or
conflicting evidence. Reported clocks require an explicitly documented UTC
interpretation; a present retrieval is not historical availability. A reported
information-period change must be resolved before causal features can be
claimed. Current archive integrity alone cannot prove an unrevised historical
vintage or real-time receipt.

Before any new strategy outcomes, finish and independently review collection,
validate the complete within-year corpus, write one economically interpretable
hypothesis and freeze its sources, feature availability, engineering choices,
all phase dates, realistic costs and success gates. Record every additional
trial. Preserve both zero-activity and losing results. The previous 26 disclosed outcomes
and their hurdle definitions stay unchanged; this data work does not increment
the economic-family count or qualify a strategy.

A future pass on the same examined year remains exploratory. No bootstrap,
source seal or green test suite can turn that year into fresh evidence or prove
absence of overfitting. The four-or-five-strategy goal remains active and unmet.

Evidence: [sample receipt](positioning_archive_probe.json),
[transition sample receipt](positioning_transition_probe.json),
[probe source](../examples/positioning/probe_archives.py),
[current results](minute_strategy_results.md).

Collector source review: [independent review](positioning_collector_review.md).
The 51 targeted collector tests include 29 independent adversarial cases.
The recorded search count includes correlated policy variants; it is not a count
of 26 independent economic edges. Full real acquisition has not been run by
this preparation.
