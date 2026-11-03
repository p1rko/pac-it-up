# Optimisation progress

Each cycle records:
- the champion version (the sha1 prefix of `my_team.py`)
- gauntlet results
- top loss causes
- the change tried
- the A/B verdict

Raw data is in `tools/results.db`; query it with `python tools/query.py report <run_id>` or `progress`.

## Cycle 0: baseline profile (2026-11-03)
- **Champion:** v0 = `my_team@f818255` (frozen as `strategies/history/v0.py`)
- **Run:** `20261103-180445-rr`, a round-robin of 8 agents: 560 games, 10 maps per pair, both colours.
- **Result:** my_team was first with **2.14 pts/game** (95-15-30). Next were tracking 1.76, search 1.71, dario 1.66, reflex 1.64, blitz 1.55, turtle 0.95 and baseline 0.18.
- **Our points by opponent:**

  | blitz | reflex | search | dario | turtle | tracking | baseline |
  |---|---|---|---|---|---|---|
  | 1.55 | 1.60 | 2.00 | 2.20 | 2.30 | 2.35 | 3.00 |

- **Loss and tie causes (45 games):**
  - invader-unopposed: 26
  - stalled: 13
  - outscored-throughput: 4
  - capsule-swing: 2
- **Timing:** max move 0.31 s, 0 warnings, 0 crashes.
- **Leads for Cycle 1:**
  1. Unopposed invader food (11.4 per game, against about 6 for the best defenders).
  2. Attack standoffs (52 idle turns per game).
  3. Long spawn-corridor maps (RANDOM398056 lost 3 of 4), where both agents leave on the same path and never cross the border.
- **Gauntlet from now on:** dario, tracking, search, reflex, blitz, turtle, plus past versions.

## Cycle 1: defence fix F1 (2026-11-03): rejected
- **Champion:** still v0 (`f818255`).
- **v0 on this gauntlet:** 1.91 pts/game (137-48-55). This is lower than the round-robin figure because baseline isn't in the gauntlet.
- **Change:** F1, where Flex turns back for big hauls even while carrying (see `FIXES.md`).
- **A/B (train), `20261103-183912-ab`:** Δ **−0.11 ± 0.04** pts/game, so rejected. Almost all of the loss is against blitz (−0.53). The targeted bites didn't drop (275 → 273): Flex is about 24 steps away when it matters.
- **Lesson:** defence must come from an agent that is already near home. The next candidates are F2/F3.

## Cycle 1, attempt 2: F6, harvest the scared-guard window (user's fix) (2026-11-03): neutral, not accepted
- **A/B (train), `20261103-192737-ab`:** Δ **−0.02 ± 0.06** pts/game, 0 crashes.
- **Target metrics hit:**
  - banked per window 3.8 → 6.9
  - scared ghosts eaten per window 0.72 → 0.11
  - carrying at window end 5.5 → 3.4
- **But points didn't move.** We only open 0.53 windows per game, most of the extra banking is a timing shift (banked per game is unchanged), and we gave up the value of sending a ghost back to spawn.
- **Status:** kept as `strategies/experiments/f6_harvest.py`. Champion is still v0.
- **New tooling:**
  - `tools/watch.py`: queue, moments, events, play and notes.
  - `tools/manual_analysis.md`: how to use it.
  - `diagnose.py capsules`: per-window capsule metrics.
- **New leads:** F7 (we take few capsules) and F8 (our scared defenders get double-killed).
