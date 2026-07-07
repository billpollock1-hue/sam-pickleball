# First Choice (FC) Analysis — SUSPENDED

**Status: Closed / suspended as of July 2026.** See `../First Choice Analysis.docx`
for the full write-up and conclusion.

**Bottom line:** After testing FC assignment against actual win rates, DEN's
Step ranking, DEN's Percentage rating, and per-player breakdowns, all four
tests landed within a couple percentage points of 50/50. First Choice does
not appear to be assigned based on skill, and does not appear to give a
meaningful competitive advantage. Ongoing monitoring was stopped because the
question is considered answered — see the write-up for the full reasoning,
including a note on why day-specific effects (e.g. wind) wouldn't change
this conclusion in aggregate even if they exist.

Nothing needs to keep running. `fc_tracker.py` was always started manually
(no cron job or background automation), so simply not launching it going
forward is sufficient to stop tracking.

## If you want to resume or re-test later

Everything below still works as-is — no setup should be needed beyond
re-authenticating with DEN (see `den_session.json` note below).

### Scripts, in the order they'd typically be used

| Script | Purpose |
|---|---|
| `fc_tracker.py` | Live polling — auto-detects an open DEN shootout and logs First Choice assignments in real time, every 2 minutes. Run and leave open during a shootout. |
| `fc_backfill.py` | One-time historical backfill — walks the DEN Club Play List and pulls FC data for past shootouts (currently pulled back to Jan 2025). Safe to re-run; skips shootouts already captured. |
| `fc_win_rate.py` | Joins `fc_tracking.csv` against `../../data/master_history_raw.csv` to determine whether the FC team actually won each game. Outputs `fc_win_rate_results.csv`. |
| `step_pct_fc_correlation.py` | Reconstructs DEN's Step and Percentage rating history from `master_history_raw.csv` (the formula is documented in the pickleball rating model's Notes sheet) and checks whether FC correlates with either metric. |
| `resolve_names.py` | Resolves DEN's abbreviated player names ("C Smith") to full names on a per-game basis, correctly separating real people who share initials (e.g. Camie Smith vs. Colin Smith). Run this last, after the above, to produce the `_resolved` CSVs the viewer actually uses. |
| `check_fc_coverage.py` | Diagnostic — compares `master_history_raw.csv` against `fc_tracking.csv` by date to flag any day with games but missing or incomplete FC data. |
| `generate_name_map.py` | Superseded by `resolve_names.py` (kept for reference only — it builds a single global abbreviation-to-name map, which can't correctly separate same-initial collisions the way `resolve_names.py` does). |

### To resume tracking
