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
- **Branch `f6-harvest`** holds this idea for further work.

## Cycle 1, attempt 3: F2+F7, shallow Flex plus capsules when guarded (2026-11-03): rejected
- **A/B (train), `20261103-195324-ab`:** Δ **−0.18 ± 0.07** pts/game. Worst against border-patrolling teams: search −0.42, tracking −0.35, reflex −0.25.
- **What moved:**
  - Flex banks about 1–2 fewer food per game (border food is the most guarded).
  - Defence didn't improve: invader food banked against us went up, 8.99 → 9.47.
  - F7 added only 0.05 capsules per game.
- **Status:** saved as `strategies/experiments/f2_f7_shallow_capsules.py`. Champion is still v0.
- **Lesson across F1, F2 and F6:** throughput wins. The next attempts should add food without costing attack time, for example F5 (stalls: about 70 idle attacking turns per game, roughly 12% of our team's moves).

## Cycle 1, attempt 4: F5a, commit to banking (2026-11-03): neutral on points, kept as base
- **Branch:** `f5-stalls`. F5 is split into F5a (banking flip) and F5b (crossing standoff); see `FIXES.md`.
- **Diagnosis:** a stall probe showed nearly all stalls are two decisions alternating every turn. About 28% are the food ↔ go-home flip at the carry-limit cliff (15 steps from home), and about 37% are food ↔ reposition standoffs.
- **A/B (train), `20261103-232842-ab`:** Δ **−0.00 ± 0.05** pts/game, 0 crashes.
  - Target hit: idle_attack 71.1 → 51.0 per game; banked 14.16 → 14.97.
  - Wins, ties and losses barely changed: the extra food widens margins of games already decided.
- **Status:** kept in `my_team.py` on `f5-stalls` as the base for F5b. Champion is still v0 until F5a+F5b passes.

## Cycle 1, attempt 5: F5b, commit to the reposition crossing (2026-11-04): rejected, code kept
- **Change:** see `FIXES.md`. Stall probe: stalled moves 37.5 → 14.8 per game.
- **A/B (train), `20261104-110303-ab`** (F5a+F5b against v0): Δ **−0.13 ± 0.11** pts/game; turtle −0.75.
  - Attack up: idle_attack 70 → 26, banked 14.1 → 16.4.
  - Defence down by more: invader food banked against us 9.0 → 11.9, "invader-unopposed" losses + ties 32 → 61.
- **Lesson:** a stalled attacker standing at the border was doing unpaid guard duty. Stall fixes have to keep someone near home, or move the stalled agent into real defence.
- **Status:** saved as `strategies/experiments/f5b_crossing_commit.py`. `my_team.py` is back to F5a; champion is still v0. Revive ideas are in `FIXES.md` (Raider-only commitment, stalled Flex defends, shorter commitment, skip it against two guards).

## Cycle 1, attempt 6: F5c, score-aware stalls (user's idea + F5b ideas 1 and 3) (2026-11-04): neutral, code kept
- **Change:** press at standoffs only when behind (or level late) and not facing two guards; otherwise the Raider stalls as in v0 and Flex guards home for 12 turns.
- **A/B (train), `20261104-114313-ab`:** Δ **+0.00 ± 0.11** pts/game.
  - Gains: blitz +0.68, dario +0.40, turtle +0.15.
  - Losses: search −0.68, tracking −0.38.
- **Diagnosis:** the extra food conceded comes while we're **ahead**, so it's Flex's guard mode, not the press. Bites conceded while behind actually fell against dario, blitz and reflex/turtle.
- **Status:** saved as `strategies/experiments/f5c_score_aware.py`; `my_team.py` back to F5a.
- **Next:** F5d, which is F5c with the press only (Flex keeps v0's stall).

## Cycle 1, attempt 7: F5d, press only (2026-11-04): neutral, code kept
- **A/B (train), `20261104-120346-ab`:** Δ **−0.03 ± 0.06** pts/game. Stalls 70 → 47, banked +1.1, conceded +1.0. Losses 54 → 59.
- **Finding:** F5c's blitz gain came from Flex's guard mode, not from pressing. Pressing when behind banks more but also concedes more, so results don't flip.
- **Status:** saved as `strategies/experiments/f5d_press_only.py`; `my_team.py` back to F5a.
- **F5 overall (as of F5d):** four variants, none above noise. Stall turns double as guard turns, so cutting them trades food evenly. The summary table and revive ideas are in `FIXES.md` (opponent-adaptive guard mode is the most promising).

## Cycle 1, attempt 8: F5e, opponent-adaptive guard mode (2026-11-04): neutral, code kept
- **Tournament format checked** (contest PDF §4.2, `CONTEST.md`): a round-robin league ranked by total points, with score balance as the tie-break, and more runs in the final. This led to the refined acceptance rule in `FIXES.md`.
- **Calibration:** only blitz attacks with both agents (the less-attacking enemy is Pacman 0.36 of turns); dario has one attacker.
- **A/B (train), `20261104-150542-ab`:** Δ **+0.03 ± 0.07** pts/game; blitz only +0.07, so F5c's +0.68 didn't come back.
- **Status:** saved as `strategies/experiments/f5e_adaptive_guard.py`; `my_team.py` back to F5a.
- **F5 overall:** five variants, none significant on points. Pooled over the four runs containing F5a: margin +0.25, banked +1.0, conceded +0.8.

## Cycle 1 result: v1 = F5a accepted (2026-11-04)
- **Holdout A/B, `20261104-154525-ab`:** F5a against v0 gives Δ **+0.24 ± 0.06** pts/game.
  - W-T-L 150-29-61 → 169-30-41, positive against every opponent (dario +0.60, blitz +0.30, tracking +0.28).
  - Banked +1.3, margin +1.4, conceded unchanged. 0 crashes, max move 0.33 s.
- Train was −0.00 ± 0.05. The holdout pool is all random mazes, where long trips home past the 15-step carry-limit cliff are common.
- **Champion: v1 = `my_team@b41127c`**, frozen as `strategies/history/v1.py`. From now on, A/B new changes against v1.

## Cycle 2: defence (2026-11-04)
- **Loss analysis of v1** (480 games): 54 losses outplayed from early on, 40 losses from a lead lost late, and 79 ties (56 of them 0–0 deadlocks).
  - In the late lead losses, one long enemy raid (about 64 rounds, 8.7 food) decides the game.
  - New tools: `tools/raid_probe.py` and `tools/diagnose.py leads`.
- **Attempt 1: F9, home hunt.** Neutral, code kept.
  - Train −0.01 ± 0.06 (`20261104-163637-ab`), holdout +0.00 ± 0.06 (`20261104-165651-ab`).
  - Kills up (holdout 0.36 → 0.50) and slightly less food conceded, but leads lost are unchanged: the decisive raids happen while both our agents are away.
  - Saved as `strategies/experiments/f9_home_hunt.py`; champion is still v1.
- **Attempt 2: F10, protect the lead** (2026-11-06). Rejected, code kept.
  - When ahead with fewer than 150 moves left, Flex guards home full-time with `defend()`.
  - Train −0.13 ± 0.06 (`20261106-153419-ab`), holdout −0.09 ± 0.06 (`20261106-155310-ab`).
  - Leads lost went **up** (train 26 → 32, holdout 13 → 20), although our ghost was near the decisive raid 3× as often. `defend()` doesn't catch evading raiders, and the lost banking (−0.7 to −0.85 per game) leaves narrower leads.
  - Saved as `strategies/experiments/f10_protect_lead.py`; champion is still v1.
- **Attempt 3: F11, defender races the invader** (2026-11-06). Promising, parked.
  - New tool `tools/chase_probe.py` showed that v1's ghosts chase from behind, so they never catch anyone. The fix replaces the defender fight evaluation with a "who reaches exits, food and capsules first" race, counting both our home ghosts.
  - Train +0.09 ± 0.08, holdout +0.06 ± 0.06, unseen holdout maps 20–39 +0.07 ± 0.06. Pooled **+0.072 ± 0.039 (z = 1.86)**, just under the rule fixed beforehand (z > 2).
  - Food conceded fell in every run (holdout 11.6 → 10.0), but our banking fell by about 0.6 in two runs.
  - Saved as `strategies/experiments/f11_race_eval.py`; champion is still v1. Next: F11b, which applies the race only when the invader carries food, to win back attack time.
- **Attempt 4: F11b, race only invaders carrying food** (2026-11-06). Neutral, code kept.
  - Train +0.07, holdout +0.04, unseen +0.04; pooled **+0.051 ± 0.035 (z = 1.47)**, weaker than F11.
  - Our banked food still fell about 0.5, so F11's attack cost doesn't come from fights with empty invaders.
  - Saved as `strategies/experiments/f11b_race_when_carrying.py`; champion is still v1. Next: measure where F11's attack cost comes from (F11c).
- **Analysis F11c: F11's attack cost** (2026-11-06). There isn't one.
  - New tool `tools/role_probe.py`: per-role Pacman turns are unchanged, and banked −0.33 ± 0.21 is noise.
  - F11's defence gain is strong: conceded **−1.11 ± 0.22 (z −5.0)**, margin **+0.78 ± 0.23 (z +3.4)**; points only reach z 1.86.
  - Next: the user decides on F11, or we test F11 + F9 home hunt.
- **v2 = F11** (2026-11-06): the user accepted F11 on its margin and defence evidence (margin z 3.4, conceded z −5.0; points z 1.86). Frozen as `strategies/history/v2.py` on branch `v2-f11`. New changes are A/B'd against v2.
- **Attempt 5: F12, v2 + F9 home hunt** (2026-11-06). Rejected.
  - Against v2: train +0.05, holdout −0.05, unseen −0.12 ± 0.06; pooled **−0.04 ± 0.035 (z −1.1)**.
  - Kills up again, but conceded barely moved and banked fell 0.45 per game: v2 already wins the chases the hunt would start.
  - Saved as `strategies/experiments/f12_v2_home_hunt.py`; champion stays v2.
- **v2 pushed** (2026-11-06): `optimize-loop` fast-forwarded to v2 and pushed (`d3a7089`, with the F12 record).
- **Analysis F13: where v2 concedes food** (2026-11-06).
  - Big raids (banking 5+) are 1.1 per game but 80% of the food conceded; half of them involve a capsule, 84% start in the first half, and only 3% are late.
  - Often we cross into their side just as they cross into ours (nearest attacker ≤3 from the border).
  - Next: capsule guard, then a calmer opening; F10 revive has a low ceiling.
- **Attempt 6: F14, capsule guard** (2026-11-06). Positive, not significant; parked.
  - Against v2: train +0.10 ± 0.05, holdout −0.00, unseen +0.05; pooled **+0.05 ± 0.031 (z 1.6)**; blitz −0.14 (z −1.9).
  - Conceded −0.40/game, banked −0.26. Capsules eaten only 0.90 → 0.85/game: most capsule races are lost 3+ steps before a reactive guard could act.
  - Saved as `strategies/experiments/f14_capsule_guard.py`; champion stays v2. Next: proactive capsule cover, or the calmer opening.
