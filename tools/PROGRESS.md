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
- **Attempt 7: F15, proactive capsule cover** (2026-11-07). Neutral, parked.
  - Against v2: train +0.05 ± 0.06, holdout −0.05 ± 0.06; pooled **±0.00 ± 0.04**. No crashes or warnings.
  - The defence works: conceded −0.88/game, capsules eaten 0.79 → 0.73, big raids 1.02 → 0.92/game. But banked fell 0.60 (Raider Pacman turns −5): the food we save, we fail to bank.
  - Saved as `strategies/experiments/f15_capsule_cover.py`; champion stays v2. Next: F15b, cover by Flex only, or cover only in the opening.
- **Attempt 8: F15b, capsule cover by Flex only** (2026-11-07). Neutral, parked.
  - Against v2: train **+0.12 ± 0.05** (gate passed), holdout −0.11 ± 0.07; pooled **±0.00 ± 0.04**.
  - Dario +0.40 / +0.33 both times; search flips between map pools as in F15. Banked still −0.78 on holdout.
  - Saved as `strategies/experiments/f15b_flex_cover.py`; champion stays v2.
- **Analysis: the scared window (user's observations, 2026-11-07).** New `tools/scared_window_probe.py`.
  - v2, 480 games: 0.77 windows per game. In 45% of them an attacker shuffles A-B-A next to a scared ghost, about 17 moves each time. Example: game `20261107-204214-ab-0244`, moves 620–682, a 2×2 loop around a ghost, carrying 8 food 6 steps from home.
  - Cause: the `attack()` step-2 prey chase fires whenever a scared ghost is within 2 steps, with no check that it can be caught, and before banking.
  - Deaths right after a window are rare: 14 in 480 games, 0.12 food/game; 98% of the food carried at a window's end is banked later (median 65 moves later).
  - Next: F16, scared-window discipline.
- **Attempt 9: F16, scared-window discipline** (2026-11-08). **Accepted as v3.**
  - Against v2: train **+0.12 ± 0.05**, holdout **+0.10 ± 0.05**, both pass the gate; pooled +0.11 ± 0.035 (z 3.1). Holdout margin +1.34, banked +0.94. No crashes or warnings.
  - Oscillating moves near scared ghosts 7.8 → 1.7 per window; food banked inside a window 1.6 → 5.6.
  - Frozen as `strategies/history/v3.py`; new changes are A/B'd against v3.
- **Attempt 10: F17a, trap rooms as dead ends (the user's idea)** (2026-11-08). Neutral, parked.
  - Against v3: train +0.03 ± 0.03, holdout −0.05 ± 0.03; pooled **−0.01 ± 0.02**.
  - Deaths 147 → 122 and trap-room deaths 29 → 18 (`tools/deadend_probe.py`); food lost −0.19/game, but banked −0.30.
  - Saved as `strategies/experiments/f17a_trap_rooms.py`; champion stays v3. Next idea: scale dead-end caution by the food carried.
- **Attempt 11: F17c, trap rooms only when carrying ≥ 3** (2026-11-08). Neutral, parked.
  - Against v3: train +0.01 ± 0.01, holdout −0.03 ± 0.03; pooled **−0.01 ± 0.02**. The banking cost is gone, but trap-room deaths only fell 30 → 26.
  - Reading: dead-end deaths come from lingering inside while a far or unseen ghost reaches the door, not from the entry check. Next idea: F17d, "watch the door".
  - Saved as `strategies/experiments/f17c_careful_carry.py`; champion stays v3.
- **Attempt 12: F17d, watch the door** (2026-11-08). Works as designed, but points are flat; parked.
  - Against v3: train −0.02 ± 0.04, holdout +0.01 ± 0.05; pooled **−0.00 ± 0.03**. Banked unchanged.
  - Deaths 148 → 118, food lost 1.04 → 0.72 per game, pocket food lost halved.
  - Why no points: a dead Pacman's food is dropped back on the map (`dump_food_from_death`), not given to the enemy. A death only costs time, and v3 dies 0.3 times per game. The dead-end line (F17a–d) is closed.
  - Saved as `strategies/experiments/f17d_watch_door.py`; champion stays v3.
- **Attempt 13: F18 / F18b, calm opening** (2026-11-08). Rejected.
  - Change: Flex guards home (`defend()`) from the start until the first enemy raid is over (an invader appeared and is gone), capped at `OPEN_HOLD` own moves.
  - F18 (cap 75) against v3: train −0.15 ± 0.10, holdout −0.07 ± 0.09. Conceded −0.48 / −1.89, but banked −2.46 / −1.87.
  - F18b (cap 35): train −0.15 ± 0.09, holdout −0.08 ± 0.07. Banked −1.55 / −1.32, conceded only −0.11 / −0.90.
  - Reading: same lesson as F1/F2/F15: Flex's attack throughput is worth more than the opening raids it prevents. Opening line closed.
  - Saved as `strategies/experiments/f18_calm_opening.py` and `f18b_short_hold.py`; champion stays v3.
- **Attempt 14: F19, deadlock breaker** (2026-11-08). Positive on all three pools; **accepted as v4** by the user. Frozen as `strategies/history/v4.py`; new changes are A/B'd against v4.
  - Diagnosis: in a 0–0 game (`20261108-150153-ab-0396`) both teams repeat a 2-move cycle from move 168 to the end. Our Raider steps across, the guard comes into sight, nothing is safe, it steps back; at home the guard is out of sight again. Their attacker does the same, which pins Flex.
  - Change (only when the score is tied and ≤ `DEADLOCK_MOVES` (150) own moves are left): carry limit 1; unseen enemy guards count at their `most_likely` cell; when no food is safe, plan to the cheapest food (ghost-adjacent cells blocked on both sides of the border) instead of `reposition()`; Flex doesn't defend against an invader carrying nothing.
  - Against v3: train +0.10 ± 0.05 (z 1.93), holdout +0.03 ± 0.03, unseen holdout 20–39 +0.04 ± 0.03; pooled **+0.053 ± 0.021 (z 2.51)**. Ties 49 → 30 (train), 29 → 29, 25 → 22. No crashes or warnings, max move 0.32 s.
- **Attempt 15: F19b, deadlock push with both agents** (2026-11-08). Borderline positive; waiting for the user.
  - Diagnosis: in v4's remaining 0–0 games (e.g. RANDOM841236 vs reflex) our agents never cross. The bold plan blocked the cells around a *believed* guard at (21,8) (really at (17,11)); with the seen guard that sealed every corridor.
  - Change (deadlock only): believed guards add cost but don't block; the Raider (`BAIT = True`) plans with only the guards' own cells blocked and skips the fight search while doing so; Flex keeps the safe bold route.
  - Deadlock maps (8 maps × reflex/blitz, 30 games): v4 8-22-0 → F19b 12-15-3.
  - Against v4: train −0.01 ± 0.03, holdout +0.00 ± 0.01, unseen holdout 20–39 **+0.10 ± 0.03** (z 3.0); pooled +0.031 ± 0.015 (z 2.01). W-T-L 515-81-124 → 526-70-124. No crashes or warnings, max move 0.33 s.
  - **Head-to-head F19b vs v4** (both colours per map): train `20261108-212018-rr` F19b 37-9-34 (net +9 points over 80 games), holdout `20261108-212207-rr` 34-10-36 (net −6). On 74 of 80 maps both agents score the same (the colour decides). F19b is ahead on 4 maps and v4 on 2: even. Both agents had 1–2 timing warnings (max move 1.8 s) in the train run, so a machine hiccup, not F19b.
- **Attempt 16: F19c, only the Raider pushes** (2026-11-08, the user's pick). Positive on all three pools; **accepted as v5** by the user. Frozen as `strategies/history/v5.py`; new changes are A/B'd against v5.
  - Change: F19b, plus Flex guards home (`defend()`) whenever the game is deadlocked and it carries nothing.
  - Deadlock maps (8 maps × reflex/blitz): v4 8-22-0, F19b 12-15-3, F19c 14-13-2.
  - Against v4: train +0.05 ± 0.05, holdout +0.05 ± 0.04, unseen +0.03 ± 0.03; pooled **+0.040 ± 0.023 (z 1.77)**. W-T-L 517-81-122 → 532-65-123. Reflex +0.16 ± 0.07, search +0.09, tracking −0.03 ± 0.06. Conceded +0.01 (F19b: +0.20). No crashes or warnings, max move 0.31 s.
  - Counting both sides: our net +29 points, the opponents' net −7, so the gap to them grows by 36 over 720 games.
- **Attempt 17: F20a, trapped haul** (2026-11-09). Neutral; parked. Champion stays v5.
  - Diagnosis: on RANDOM1890298 v5 loses 5 games by −28: both Pacmen trapped in one enemy room by a single guard, ~700 turns in `go_home` vetoed by the fight search, nobody defending.
  - Change: a Flex trapped in `go_home` for 20 moves (≤3 cells) walks into the guard to respawn home, when an enemy attacks or we're not ahead.
  - Against v5: train +0.03 ± 0.02, holdout −0.02 ± 0.03. Holdout idle_attack 42.6 → 35.4; margins up; points flat.
  - F20b draft (Flex defends while the Raider is pinned or trapped) was worse than F20a on the stall maps; not A/B'd.
  - Saved as `strategies/experiments/f20a_trapped_haul.py` and `f20b_no_follow.py`.
- **Attempt 18: F20d, trap rooms (the user's idea: don't send both agents into a trap room)** (2026-11-09). Neutral; parked. Champion stays v5.
  - Change (on F20a): precompute enemy-side areas one guard can seal (≤40 cells); Flex skips food in a trap room shared with the Raider.
  - Stall maps: 1.81 (v5) → 1.97 (F20a) → 2.14 pts/game. On RANDOM1890298 four of five −28 losses became wins in the A/B too.
  - Against v5: train +0.01 ± 0.04, holdout −0.02 ± 0.04; dario −0.15 / −0.12. The filter acts on 5–71 Flex turns per dario game (rooms nest), so it steers Flex far from any trap.
  - Next (F20e): only filter when a guard is near the room's sealing cells.
  - Saved as `strategies/experiments/f20d_trap_rooms.py`.
- **Attempt 19: F20e, guarded trap rooms** (2026-11-09). Neutral, but fixes the targeted trap and costs nothing measurable; **accepted as v6** by the user. Frozen as `strategies/history/v6.py`; new changes are A/B'd against v6.
  - Change (on F20d): Flex only avoids the Raider's trap room when an enemy guard could reach its door within `SEAL_SLACK` (10) moves of the Raider.
  - Against v5: train +0.03 ± 0.03, holdout +0.00 ± 0.03, unseen −0.01 ± 0.02; pooled **+0.007 ± 0.016**. No crashes or warnings, max move 0.33 s.
  - RANDOM1890298: three of five −28 losses became wins. idle_attack −0.3 / −4.6 / −4.0 per game.
  - F20d's dario dip didn't reproduce: same games, same filter activity, v5's results. Treat single-game flips as noise.
  - Saved as `strategies/experiments/f20e_guarded_rooms.py`.
- **Attempt 20: F21 / F21b, ambush at the end of the enemy's capsule window** (2026-11-09). Parked by the user before a full A/B. Champion stays v6.
  - Diagnosis: 44% of free bites happen while our ghosts are scared; at the window end invaders still carry 3.2 food/game in our half and bank 2.1 of it, with no ghost of ours near.
  - F21 (Flex runs `defend()` near the window end) herded invaders home: banked after the window 115 → 147 on 72 gauntlet games. F21b (stand on the invader's way out) recovered more (23 → 38) but still conceded more after the window (130). Points 2.60 → 2.54 (2 wins → ties, noise-level).
  - Saved as `strategies/experiments/f21_window_ambush.py` and `f21b_guard_way_out.py`; branch `f21-window-ambush`.
- **Attempt 21: F22, capsule push (the user's capsule idea)** (2026-11-09). **Accepted as v7** by the user. Frozen as `strategies/history/v7.py`; new changes are A/B'd against v7.
  - Step 0 (720 v6 games): 147 ties/losses still had an enemy capsule unused at turn 1000; a 38-move sweep from it would cover the deficit in 136. The food-limit finisher (all but 2 in one window) was possible in only 12.
  - Change: each turn, for each enemy capsule, estimate the two-agent greedy sweep inside the scared window (`SWEEP_BUDGET` 38). Push (both agents go for the nearest capsule, then F16's scared-window attack) when the sweep wins on the food limit, or late (≤ `PUSH_MOVES` 120 own moves left), not ahead (`PUSH_LEAD` 0) and score + carried + sweep ≥ 1. Capsules are never saved; escapes still eat them.
  - Against v6: train +0.03 ± 0.04, holdout +0.08 ± 0.05, unseen +0.23 ± 0.06 (passes alone); pooled **+0.115 ± 0.031 (z 3.8)** over 720 pairs. W-T-L 534-64-122 → 566-51-103; banked +0.78, margin +0.51, conceded +0.27, deaths unchanged. No crashes or warnings, max move 0.32 s.
  - Per opponent: dario +0.13, tracking +0.13, search +0.16, reflex +0.19, blitz +0.01, turtle +0.08. Blitz is neutral (two invaders punish the empty home during a push).
  - Saved as `strategies/experiments/f22_capsule_push.py`; branch `f22-capsule-push`.
