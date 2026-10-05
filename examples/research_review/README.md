# Partial-exit margin correction

These tools preserve the original twenty-four candidate results and repeat the
same 1,000 derivative simulations after a margin-allocation correction. The
fixed real-data window is `[2025-10-05, 2026-10-05)` UTC. Eight spot policies are
retained unchanged. The correction adds no economic hypotheses and changes no
fees, thresholds, assets, selection rules or success gates.

A partial derivative exit now releases proportional isolated reserve. Its
realized P&L and fees settle in wallet cash; they do not also alter the remaining
position's allocation. Funding in that allocation is released proportionally.
This is an explicit simulator policy, not a claim to reproduce every historical
exchange margin rule.

From the repository root, install the environment and prepare the verified
minute and external-factor inputs described in the [manual](../../docs/user_manual.md)
and [external-factor guide](../external_factors/README.md). Then run:

```bash
.venv/bin/python examples/research_review/rerun_margin_correction.py
.venv/bin/python examples/research_review/audit_corrected_ledgers.py --seal
.venv/bin/python audit/verify_corrected_external.py --final
.venv/bin/python examples/research_review/publish_margin_correction.py --verify-only
.venv/bin/python examples/research_review/publish_margin_correction.py --out docs/margin_correction_reproduction
```

The driver uses fresh carry120, signed480 and external400 output folders and
checks each economic protocol against its preserved original. All source and
input fingerprints must agree before cached results can resume. Publication
requires complete runs, independent ledger replay, sixteen-file seals per
trial, rebuilt summaries and training-only selection, retained spot anchors,
and unchanged original evidence. Use a fresh publication destination.

The downloaded market data and complete result trajectories are excluded from
Git; compact comparisons and provenance are saved in the repository. This
workspace's frozen original results are required by the correction driver.
For a new clone, recreate those original runs using Git commit `8cd5f36` in a
separate checkout, copy their result folders into the corrected checkout, and
retain the identical verified data caches. The original carry runner's saved
executed source includes the documented timestamp-analysis repair history.
Later vendor revisions may make byte-identical reconstruction unavailable;
retain original archives, manifests and result hashes when reproducing.

Original liquidation scope can be reviewed without rewriting old results:

```bash
.venv/bin/python audit/analyze_original_liquidations.py --all
```

That replay holds original fills fixed. Its healthy-residual count is distinct
from the liquidation counts in the corrected, fully simulated trajectories.
Additional hypotheses on this already examined year remain exploratory.
