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
