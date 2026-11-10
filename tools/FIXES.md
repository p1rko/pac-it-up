# Fix tracker

Every weakness we find gets an entry here. It moves from **To fix** to **In progress**, and then to **Fixed** or **Rejected**.

Each entry names:
- the metric that measures the weakness (from `tools/query.py` reports or `tools/diagnose.py`)
- its value before the change
- its value after the change
- the A/B run that decided it

A fix is accepted only when the A/B gate passes on both the train and holdout pools. The gate:
- mean Δ points/game > 2·SE
- no matchup worse than −1 SE against dario
- 0 warnings or crashes

**Refined rule (2026-11-04).** The real tournament is a round-robin league ranked by total points (W = 3, T = 1, L = 0), with score balance (the sum of margins) as the tie-break. So a change can also be accepted when all of these hold:
- mean Δ ≥ 0
- one opponent better by > 2 SE
- no opponent worse than −2 SE

That way a style-specific gain isn't diluted by our equal-weight gauntlet. Sources: the contest PDF v1.1 §4.2 and `pacman-contest/src/contest/CONTEST.md`.

The targeted metric should also move. If points go up but the targeted metric doesn't move, the gain came from somewhere else, and we note that.

Commands used for evaluation:
```bash
venv/bin/python tools/tournament.py ab my_team.py strategies/history/vN.py --vs <gauntlet> --maps 20             # train
venv/bin/python tools/tournament.py ab my_team.py strategies/history/vN.py --vs <gauntlet> --maps 20 --pool holdout
venv/bin/python tools/diagnose.py unopposed <run_id> --agent my_team   # re-measure the targeted weakness
venv/bin/python tools/query.py progress                                # points/game per version
```
Gauntlet: `strategies/dario.py strategies/tracking.py strategies/search.py strategies/reflex.py strategies/blitz.py strategies/turtle.py`

---

## In progress

### F5: Attack standoffs (branch `f5-stalls`)
- **Evidence:** v0 stalls 71 attacking turns per game (`idle_attack`, train A/B `20261103-232842-ab`), and "stalled" is the cause in 43 of 101 losses and ties.
- **Stall probe** (48 games; now `tools/stall_probe.py`, which tags the code path on every stalled turn; stalled = Pacman with ≤2 cells in its last 10 moves). Almost every stall is two decisions alternating on successive turns:

  | pattern over the 10-move window | share of stalls | cause |
  |---|---|---|
  | eat food ↔ go home | ~28% | the carry limit drops 7 → 5 beyond 15 steps from home; carrying 5–6 at distance 15/16 flips every move |
  | eat food ↔ reposition | ~37% | a guard about 4 away: stepping in makes the food unsafe, stepping back makes it safe again |
  | reposition ↔ reposition with search | ~11% | `reposition()` re-picks its crossing every turn from shifting beliefs |
  | going home while chased | ~12% | really blocked by a ghost (left alone) |

#### F5a: commit to banking: **accepted as v1** (holdout +0.24 ± 0.06)
- **Holdout A/B, `20261104-154525-ab`** (all-random holdout maps, 480 games, 0 crashes, 0 warnings, max move 0.33 s):
  - Δ **+0.24 ± 0.06** pts/game: passes the gate. W-T-L 150-29-61 → 169-30-41.
  - By opponent, every one positive: dario +0.60 ± 0.24, blitz +0.30, tracking +0.28, search +0.15, reflex +0.07, turtle +0.05.
  - Banked 15.55 → 16.86, margin +4.0 → +5.4, food lost in deaths 1.09 → 0.81, conceded unchanged (11.55 → 11.50).
  - Likely reason it shows on holdout but not train: holdout maps are all random mazes, where trips home beyond 15 steps (the carry-limit cliff) are common. The train mix includes small fixed layouts.
- Snapshot `strategies/history/v1.py` (`b41127cc2a`). Earlier train-only notes below.
- **Change:** `self.banking` is set when the carry limit or the "bank first" shortcut sends us home. While it is set, we keep going home. It clears at home, at carrying 0, or when the enemies are scared long enough for the no-limit mode. Steps 1–3 (out of time, scared prey, chased) still come first.
- **Probe after:** the flip at 15–16 from home went from ~690 stalled moves to 2; stalled moves 65.7 → 53.7 per game.
- **`tools/stall_probe.py --maps 4` on F5a** (its own seeds, so the totals differ from above): 37.5 stalled moves per game. **78% are now "food | reposition"** (Raider 46%, Flex 32%), 17% are "food" alone (the target changing each turn), and the go-home flip is under 3%.
- **A/B (train), `20261103-232842-ab`:** 480 games, 0 crashes, 0 warnings, max move 0.34 s.
  - Δ **−0.00 ± 0.05** pts/game: did not pass the gate.
  - By opponent: blitz +0.12, dario +0.12, tracking 0.00, turtle −0.05, reflex −0.10, search −0.12 (all within 1 SE).

  | metric (per game) | v0 | F5a |
  |---|---|---|
  | idle_attack | 71.1 | **51.0** |
  | banked | 14.16 | **14.97** |
  | margin | +5.1 | +5.7 |
  | food lost in deaths | 1.15 | 1.04 |
  | invader food banked against us | 9.03 | 9.27 |
  | stalled losses + ties | 43 | 39 |

- **Why no points:** the extra food mostly widens margins of games that were already decided (W-T-L 139-47-54 → 138-49-53). The stalls that decide close games are the guard standoffs, which is F5b's target.
- **Status:** kept in `my_team.py` on `f5-stalls` (copy in `strategies/experiments/f5a_bank_commit.py`). F5a+F5b will be A/B'd against v0 together.

#### F5b: commit to a crossing: rejected (−0.13 ± 0.11), code kept to revive
- **Change:** when `reposition()` fires it stores its crossing in `self.crossing`, and `follow_crossing()` keeps heading there until we reach it or `COMMIT_TURNS` (12) pass. On the way it only takes safe food within 2 steps that is more than `STANDOFF_RADIUS` (4) from the standoff. Crossings within 4 of the standoff get a −10 appeal penalty, so we really move along the border.
- **Target:** the "food ↔ reposition" and "reposition ↔ reposition" stalls, `idle_attack`, and points against search/tracking/reflex.
- **Probe (`stall_probe.py --maps 4`, F5a+F5b):** stalled moves 37.5 → **14.8** per game; "food ↔ reposition" is gone. What is left is mostly "food" alone (62%): the food target changes every turn, a possible F5c.
- **A/B (train), `20261104-110303-ab`** (F5a+F5b against v0; the earlier run stopped at 220/480 is incomplete, ignore it): 480 games, 0 crashes, 0 warnings, max move 0.32 s.
  - Δ **−0.13 ± 0.11** pts/game: rejected. W-T-L 137-48-55 → 131-35-74.
  - By opponent: dario +0.23, reflex +0.05, tracking +0.03, search −0.15, blitz −0.17, **turtle −0.75 ± 0.27**.
- **Attack got much better:**

  | metric (per game) | v0 | F5a+F5b |
  |---|---|---|
  | idle_attack | 70.1 | **25.9** |
  | banked | 14.12 | **16.37** |
  | banked vs search / tracking / dario | 11.6 / 13.1 / 18.0 | **16.2 / 18.0 / 21.8** |

- **…but defence got worse by more:**

  | metric (per game) | v0 | F5a+F5b |
  |---|---|---|
  | invader food banked against us | 9.02 | **11.85** |
  | unopposed food | 8.22 | 9.82 |
  | "invader-unopposed" losses + ties | 32 | **61** |
  | "both agents home but far" share of unopposed bites | 18% | 26% |

  Conceded food rose against **every** opponent (+2 to +4.5).
- **Why:**
  - **A stalled attacker was a free border guard.** In v0 a stalled agent stood at the border with nothing carried. Flex in that spot reacts to any invader within `DEFEND_RADIUS`, and the Raider's `hunt_nearby_invader` catches anything close. F5b sends them along the border to a far crossing and then deep, often carrying food, which switches Flex's defence off. This is the same lesson as F1/F2 from the other side: our defence mostly comes from agents that happen to be near home.
  - **Turtle (two defenders):** banked 17.2 → 13.9, food lost in deaths 1.95 → 3.05, conceded 2.5 → 7.0, losses 5 → 13. Committing to a crossing for 12 turns walks into the second guard, and turtle's counter-raids get through while we're away.
- **Status:** saved as `strategies/experiments/f5b_crossing_commit.py`; `my_team.py` back to F5a.
- **Ideas to revive it:**
  1. **Raider only.** Keep Flex's stall-at-the-border as it is (it doubles as a guard), or have a stalled Flex switch to `defend()` (the original F5 idea). Give only the Raider the crossing commitment.
  2. **Shorter or weaker commitment:** `COMMIT_TURNS` 4–6, and no −10 far-crossing penalty, so the agent stays near home.
  3. **Don't commit against two guards** (turtle-like: both enemies are ghosts on their side).
  4. Measure defence with `diagnose.py unopposed` alongside `idle_attack`, since the two trade off.

#### F5c: score-aware stalls (revives F5b with ideas 1 + 3 and the user's "press when losing"): neutral, code kept
- **Idea (user's):** a stall is fine when we're ahead, because the stalled agent guards the border, but bad when we're behind. W = 3, T = 1, L = 0, so conceding costs little when already losing, while extra food can flip the result.
- **Change** (on top of F5a):
  - `press()`: we're behind, or level with fewer than `PRESS_TIE_MOVES` (150) own moves left.
  - `two_guards()`: both enemies are ghosts believed within `GUARD_DEPTH` (8) of our border.
  - At a standoff, when pressing and not facing two guards, both agents commit to a crossing (F5b's `follow_crossing`); the commitment drops once we stop pressing.
  - Otherwise the Raider stalls as in v0, and Flex (`STANDOFF_DEFENDS`) calls `defend()` for `COMMIT_TURNS` (12) turns.
- **A/B (train), `20261104-114313-ab`:** 480 games, 0 crashes, 0 warnings, max move 0.32 s.
  - Δ **+0.00 ± 0.11** pts/game: neutral. W-T-L 140-48-52 → 141-45-54.
  - The split by opponent is large and opposite:

    | vs | Δ points/game |
    |---|---|
    | blitz | **+0.68 ± 0.24** |
    | dario | +0.40 ± 0.28 |
    | turtle | +0.15 (F5b's −0.75 fixed) |
    | reflex | −0.17 |
    | tracking | −0.38 ± 0.30 |
    | search | **−0.68 ± 0.26** |

  - idle_attack 69.9 → 36.7; banked 14.22 → 15.07; invader food banked against us 8.94 → 9.86.
- **Where the extra food conceded comes from.** Enemy bites on our food per game, split by the score at the time:

  | vs | agent | ahead | behind | level early | level late |
  |---|---|---|---|---|---|
  | search | v0 | 6.4 | 1.2 | 2.2 | 0 |
  | search | F5c | **10.0** | 2.8 | 3.1 | 0.8 |
  | reflex/turtle | v0 | 5.6 | 2.5 | 2.9 | 0.5 |
  | reflex/turtle | F5c | **9.8** | 1.7 | 2.4 | 0.2 |
  | dario | v0 | 10.7 | 4.3 | 5.0 | 1.0 |
  | dario | F5c | 11.0 | **2.5** | 3.1 | 0.8 |

  - The leak is **while we're ahead**, when F5c doesn't press. Only Flex's guard mode differs from v0 there, so a guarding Flex defends *worse* than a Flex stalled at the border. Possible reasons: `defend()` walks to `patrol_point` away from the invader's crossing, or Flex's 12-turn guard / attack cycle leaves gaps.
  - The press part looks good: bites conceded while behind fell against dario, blitz and reflex/turtle, and points rose against blitz and dario.
- **Status:** saved as `strategies/experiments/f5c_score_aware.py`; `my_team.py` back to F5a.
- **Next:** F5d = F5c without Flex's guard mode (`STANDOFF_DEFENDS = False` on Flex), i.e. press when behind and stall like v0 otherwise. Then watch clips of Flex's guard mode against search to see why it leaks.

#### F5d: press only (F5c without Flex's guard mode): neutral, code kept
- **Change:** F5c with `STANDOFF_DEFENDS` left False on Flex. When behind (or level late) and not facing two guards, both agents commit to a crossing; otherwise both stall like v0.
- **A/B (train), `20261104-120346-ab`:** 480 games, 0 crashes, 0 warnings, max move 0.40 s.
  - Δ **−0.03 ± 0.06** pts/game: neutral. W-T-L 137-49-54 → 136-45-59.
  - By opponent: dario +0.20, blitz −0.03, search −0.07, tracking −0.07, reflex −0.10, turtle −0.10 (all within 1.1 SE).
  - idle_attack 69.7 → 47.4; banked 14.08 → 15.14; invader food banked against us 9.02 → 10.04.
- **Food conceded per game by score state** (enemy bites on our food):

  | run | agent | ahead | behind | level |
  |---|---|---|---|---|
  | F5c | v0 | 5.8 | 2.3 | 3.5 |
  | F5c | F5c | 7.5 | 2.1 | 3.5 |
  | F5d | v0 | 5.9 | 2.3 | 3.5 |
  | F5d | F5d | 6.4 | 2.8 | 3.7 |

- **What this says:**
  - **The press alone doesn't flip results.** Pressing when behind banks more but concedes more too (2.3 → 2.8 while behind). Losses didn't drop (54 → 59).
  - **F5c's blitz gain (+0.68) came from Flex's guard mode, not from the press**, because F5d lost it (−0.03). So guard mode helps against attack-heavy opponents (blitz, dario) and hurts against single-attacker border teams (search, tracking).
- **Status:** saved as `strategies/experiments/f5d_press_only.py`; `my_team.py` back to F5a.

#### F5e: opponent-adaptive guard mode (F5c, guard only against two attackers): neutral, code kept
- **Calibration** (`stall_probe.py`'s new attack-share readout). Share of turns the *less* attacking enemy spends as Pacman at the end of the game:

  | opponent | share |
  |---|---|
  | blitz | 0.36 (range 0.29–0.46) |
  | tracking | 0.09 |
  | search | 0.08 |
  | reflex | 0.07 (max 0.27) |
  | turtle | 0.05 |
  | dario | **0.00**: one attacker, so dario can't be separated from search/tracking by style |

- **Change:** F5c, but Flex's guard mode is on only when `FlexAgent.standoff_defends()` holds: from `STYLE_TURNS` (100) on, both enemies have been Pacman ≥ `ATTACKER_SHARE` (0.25) of turns, i.e. blitz-like opponents.
- **A/B (train), `20261104-150542-ab`:** 480 games, 0 crashes, 0 warnings, max move 0.37 s.
  - Δ **+0.03 ± 0.07** pts/game: neutral. W-T-L 138-47-55 → 141-45-54.
  - By opponent: dario +0.20, blitz +0.07, search +0.07, turtle 0.00, reflex −0.03, tracking −0.15 (all within 1.1 SE).
  - It passes neither the gate nor the refined rule (no opponent > 2 SE).
- **F5c's blitz +0.68 didn't come back** (+0.07 here). Either it was partly noise (we compare 6 opponents per run, so one 2.8 SE result is not that unlikely), or F5c's guard mode helped mainly in the first 100 turns, which F5e skips while it judges the style.
- **Status:** saved as `strategies/experiments/f5e_adaptive_guard.py`; `my_team.py` back to F5a.

#### F5 summary (all on top of or including F5a)
| variant | Δ pts/game | idle_attack | banked | conceded |
|---|---|---|---|---|
| v0 | — | ~70 | ~14.1 | ~9.0 |
| F5a bank commit | −0.00 ± 0.05 | 51 | 15.0 | 9.3 |
| F5b crossing commit | −0.13 ± 0.11 | 26 | 16.4 | 11.9 |
| F5c score-aware + Flex guard | +0.00 ± 0.11 | 37 | 15.1 | 9.9 |
| F5d score-aware, press only | −0.03 ± 0.06 | 47 | 15.1 | 10.0 |
| F5e adaptive guard | +0.03 ± 0.07 | ~47 | 15.5 | ~9.6 |

Pooled over the four runs that contain F5a (1920 games): margin +5.14 → +5.39, banked 14.14 → 15.18, conceded 9.00 → 9.79.

**Lesson:** stall turns are not wasted turns in this field. Every stall turn removed turns into roughly equal food for both sides, because the stalled agent was guarding. Removing stalls alone doesn't win games; a gain has to come from better defence at the same time.

**Revive ideas:**
- **Opponent-adaptive guard mode:** Flex guards after a standoff only against opponents that attack a lot (`TEAM_INFO['invader_turns']`, e.g. blitz/dario), and stalls otherwise.
- Find out why `defend()` leaks against search/tracking compared with a stalled Flex at the border, using `watch.py`.

### F12: F9 home hunt on top of v2: rejected (2026-11-06)
- **Idea:** F9's home hunt made 40% more kills on v1 but conceded the same, because our ghosts couldn't finish a chase. v2 (F11) fixed catching, so the guess was that the two would stack.
- **Change:** v2 + exactly F9's code (`HUNT_CARRY` 2, `HUNT_RADIUS` 10, `SmartAgent.home_hunt()`, called in `RaiderAgent.decide` after `hunt_nearby_invader`). Branch `f12-v2-home-hunt`, saved as `strategies/experiments/f12_v2_home_hunt.py`.
- **A/B against v2** (480 games each, 0 crashes, 0 warnings, max move 0.36 s):

  | batch | run | Δ points/game | margin | banked | conceded | kills |
  |---|---|---|---|---|---|---|
  | train | `20261106-210014-ab` | +0.05 ± 0.07 | +0.28 | −0.45 | −0.72 | +0.10 |
  | holdout | `20261106-212044-ab` | −0.05 ± 0.05 | −0.15 | −0.26 | −0.11 | +0.08 |
  | unseen holdout (offset 20) | `20261106-214120-ab` | **−0.12 ± 0.06** | −0.64 | −0.63 | +0.01 | +0.06 |
  | **pooled** | | **−0.04 ± 0.035 (z −1.1)** | −0.17 | −0.45 | −0.27 | +0.08 |

  Unseen batch by opponent: blitz −0.30 ± 0.14, reflex −0.25, tracking −0.17, search −0.07, dario +0.03, turtle +0.03.
- **Why it failed:** kills and food denied went up again (+0.08 kills, +0.35 to +0.55 food denied per game), but conceded food barely moved once v2 was the base. v2's race evaluation already wins most of the chases a home hunt would start, so the hunt mostly adds attack turns lost: banked fell in all three batches (−0.45 on average). Against blitz (two attackers, so the hunt fires often) it was worst.
- **Lesson:** defence add-ons that pull an attacker home only pay when the existing defence is losing those invaders. After F11 the remaining conceded food comes from invaders nobody is near (`invader-unopposed`), not from chases we lose.
- **Revive ideas:**
  - Hunt only with an agent that is already a ghost at home and not carrying (no turning back), and only for invaders carrying 5+.
  - Gate it on the opponent: only against teams with one dedicated attacker, where one hunter can't be overloaded.

## Parked (neutral, worth combining later)

### F21 / F21b: ambush a loaded invader at the end of the enemy's capsule window: parked without a full A/B (2026-11-09)
- **Evidence** (v6, 720 A/B games + a 72-game live probe): ~10 free bites per game (no ghost of ours within 6); **44% while our ghosts are scared** after the enemy ate our capsule (41% in lost/tied games). The rest is spread thin (no other situation above ~5%). Replaying the enemy's windows in 480 v6 games: 322 windows end with an invader still loaded in our half (1,550 food, 3.2/game); they bank 1,026 of it, we catch 176. At the window end the invader is a median 13.5 steps from its border and our nearest ghost is usually nowhere (within 6 in only 36 of 322).
- **F21:** Flex (carrying ≤ `AMBUSH_MAX_CARRY` 1) runs `defend()` while scared once an invader in our half carries ≥ `AMBUSH_CARRY` (3) and our scared time ≤ its distance + `AMBUSH_LEAD` (6); latched while that invader stays loaded in our half. The trigger works (ambushing at 21 of 27 window ends with a loaded invader, often 2–5 steps away), but `defend()`'s scared ring (distance 2, any side) **herds the invader home**: invaders that used to sit on their haul until the game ended now banked it.
- **F21b:** same trigger, but while scared Flex stands on the invader's shortest path to its nearest crossing, ≥ 2 cells away.
- **Gauntlet, 6 train maps × 6 opponents × 2 colours, 72 games each** (`20261109-205803-gauntlet` … `-211733-gauntlet`):

  | | W-T-L | pts/game | banked after window | recovered by catches |
  |---|---|---|---|---|
  | v6 | 61-4-7 | 2.60 | 115 | 23 |
  | F21 (lead 6 / 4 / 10, carry 5) | 59-6-7 … 60-6-6 | 2.54–2.58 | 143–151 | 18–35 |
  | F21b | 59-6-7 | 2.54 | 130 | 38 |

- **Reading:** a ghost can't reliably catch a Pacman that runs unless it cuts off its only way home; F21b guards only the nearest crossing and invaders take others. The ceiling is ~0.3 food per game, and the herding side effect eats most of it. Parked by the user's choice before a full A/B. Code: branch `f21-window-ambush` (`27c55c5`), `strategies/experiments/f21_window_ambush.py`, `f21b_guard_way_out.py`.
- **To revive:** guard the crossing the invader will really use (belief heading, or the crossing nearest to it and farthest from our agents); or only ambush invaders in a pocket/room whose door we can reach first (like `catchable()` for scared ghosts).

### F20a: trapped haul, Flex gives up a pinned haul: neutral, parked (2026-11-09)
- **Evidence:** v5 loses all 5 games on RANDOM1890298 against tracking/search/reflex by −28. Both our Pacmen enter one small enemy room with two adjacent exits (x 20–25, y 1–3 as red), one guard parks between the exits at (22,3)/(23,3), and both sit for ~700 turns carrying 12 food while the enemy raider eats ours unopposed. Stall probe on that map: 91% of stalled moves are `go_home | go_home>search` (Raider 48%, Flex 43%). `deadlocked()` never fires (score ≠ 0), and Flex only defends with 0 food. Same pattern on RANDOM1390133 and RANDOM66173; 20 v5 non-wins with idle_attack > 200 across 11 maps.
- **Change:** `track_trapped()`: Pacman with food, `go_home` for `TRAP_TURNS` (20) own moves within `TRAP_CELLS` (3) cells → `self.trapped`, shared as `TEAM_INFO['trapped']`. `FlexAgent.give_up_haul()`: a trapped Flex walks into the guard (fight search off) when an enemy is attacking or we are not ahead, latched until it dies or the guard leaves. Branch `f20-trapped-haul` (`0d9b31a`).
- **Stall maps** (3 maps × 6 opponents × 2 colours, 36 games): W-T-L v5 21-2-13 → F20a 21-2-13, margin +2.0 → +5.1. The −28 games became +7/−5/+1/−5/−7; offset by noise flips elsewhere.
- **A/B against v5** (0 crashes or warnings, max move 0.34 s):

  | | train `20261109-163040-ab` | holdout `20261109-165109-ab` |
  |---|---|---|
  | Δ pts/game | +0.03 ± 0.02 | −0.02 ± 0.03 |
  | W-T-L v5 → F20a | 171-25-44 → 173-25-42 | 186-21-33 → 185-20-35 |
  | idle_attack | 48.2 → 47.7 | 42.6 → 35.4 |
  | margin | +6.93 → +7.11 | +7.43 → +7.83 |

- **Reading:** it does what it targets (holdout idle_attack −17%, margins up on both pools), but the trap is rare: it fires in ~9 of 36 games on the worst maps, and turns −28 losses into smaller losses, not wins. Points don't move. Saved as `strategies/experiments/f20a_trapped_haul.py`.
- **F20b draft** (branch `f20b-no-follow`, `4472f19`, on top of F20a): agents also share `pinned` (banking with a dangerous ghost within `DANGER_RADIUS`); an empty-handed Flex defends while its mate is pinned or trapped. Stall maps vs F20a: 22-3-11 vs 23-2-11, margin +4.8 vs +6.3; the trap games got worse (tracking/search as blue −5 → −15). Not A/B'd. Saved as `strategies/experiments/f20b_no_follow.py`.
- **To revive:** combine F20a with something that turns the trapped haul into points (F20c: Raider breakout when trapped regardless of score), or make F20b's `pinned` stricter (no progress home for a few turns).
- **Why F20b failed** (traced RANDOM1890298 vs tracking, us blue): both agents entered the room together at turn ~55, before any guard was near, so `pinned` never stopped Flex. Afterwards the Raider stayed trapped all game, which kept Flex defending all game (score 7 → 21 against us anyway).

### F20d: precomputed trap rooms, Flex doesn't follow the Raider in: neutral, parked (2026-11-09; the user's "don't send both into a trap room" idea)
- **Change** (on top of F20a): `_compute_trap_rooms()` in `register_initial_state`: for every enemy-side cell a guard could stand on, block it and its neighbours and collect the enemy-side cells cut off from our border; areas ≤ `ROOM_MAX` (40) are trap rooms (5–30 ms). In `attack()`, Flex (`AVOID_MATE_ROOM`) drops food in a trap room shared with the Raider's position or target, unless Flex is already in it. Branch `f20d-trap-rooms` (`b30456d`).
- **Detection:** the RANDOM1890298 room is found (37 cells); our two stuck cells (23,2) and (26,6) are in it.
- **Stall maps** (36 games): v5 21-2-13 / 1.81 pts, F20a 23-2-11 / 1.97, **F20d 25-2-9 / 2.14**.
- **A/B against v5** (0 crashes or warnings, max move 0.33 s):

  | | train `20261109-175852-ab` | holdout `20261109-181944-ab` |
  |---|---|---|
  | Δ pts/game | +0.01 ± 0.04 | −0.02 ± 0.04 |
  | W-T-L v5 → F20d | 171-25-44 → 172-25-43 | 186-20-34 → 184-22-34 |
  | dario | −0.15 ± 0.10 | −0.12 ± 0.14 |
  | idle_attack | 48.0 → 47.1 | 42.8 → 37.1 |

- **Where it works:** on RANDOM1890298 (holdout) the five v5 −28 losses became +4, +1, +11, −10, +4: four losses turned into wins.
- **Where it costs:** 6 dario games flip (5 against us). Replaying them reproduces the results, and the room filter acts on 5–71 Flex turns per game there, with no sacrifice. The trap room is 37 cells and rooms nest (most maps have 50–90 rooms of 1–40 cells), so the rule steers Flex in ordinary play, not only near traps. Dario guards don't camp at room exits, so it's pure cost there.
- **To revive (F20e):** fire the filter only when a guard could actually seal the shared room: keep each room's sealing cells and require an enemy ghost (seen or believed) within a few steps of one; or only when the Raider is already banking. Fast check: the 3 stall maps plus the 6 flipped dario games (`20261109-175852-ab-0009`, `-0013`; `20261109-181944-ab-0008`, `-0020`, `-0027`, `-0035`).
- Saved as `strategies/experiments/f20d_trap_rooms.py`.

### F20e: trap-room filter only when a guard could close the room: neutral (pooled +0.01), **accepted as v6** by the user (2026-11-09)
- **Change** (on F20d): each trap room keeps its sealing cells; Flex skips food in the Raider's room only if an enemy ghost (seen or believed, not scared) reaches a sealing cell within `SEAL_SLACK` moves of the Raider's own distance. Branch `f20e-guarded-rooms` (`d73a98f`).
- **Slack sweep** (stall maps pts/game; RANDOM1890298 tracking/search as blue): 2 → 1.89, −5/−5 (never fires on entry: the guard is still far); 6 → 1.81, −5/−5; **10 → 1.89, +1/+11**. The 6 dario games F20d flipped return to v5's results at every slack, although the filter still acts on 10–104 Flex turns there: F20d's dario dip was most likely chaotic divergence, not the rule.
- **A/B against v5** (0 crashes or warnings, max move 0.33 s):

  | | train `20261109-193757-ab` | holdout `-195738-ab` | unseen holdout 20–39 `-201541-ab` |
  |---|---|---|---|
  | Δ pts/game | +0.03 ± 0.03 | +0.00 ± 0.03 | −0.01 ± 0.02 |
  | W-T-L v5 → F20e | 170-26-44 → 173-24-43 | 186-20-34 → 186-21-33 | 175-18-47 → 174-19-47 |
  | idle_attack | 48.2 → 47.9 | 42.8 → 38.2 | 31.0 → 27.0 |

  - **Pooled over 720 pairs: +0.007 ± 0.016 (z 0.4).** Dario 0.00 / −0.07 / +0.07. Banked +0.03 / +0.23 / −0.01; unopposed food −0.13 per game on every pool.
  - RANDOM1890298 (holdout): v5's five −28 losses → +1, +4, +11 (wins), −10, −7.
- **By opponent** (pooled, 120 pairs each): tracking +0.067 ± 0.053, blitz +0.025, search/dario/turtle 0.00, reflex −0.042 ± 0.051. Margin up and conceded down against all six.
- **The 3 reflex games F20e lost** (first different move between the F20e and v5 replays): RANDOM1913344 diverges on a Raider move (same code as v5: search timing); mediumCapture diverges on a fight-search move while Flex defends, and a rerun gives +21 instead of −1 (timing). Only RANDOM123647 (`20261109-193757-ab-0149`, blue) starts at the room filter (Flex move 97, turn 386); 90 turns later both our agents die on consecutive turns (477/478) to the same guard, in pockets 11–12 from home, and the game ends −8 instead of +4. Possible gap: the filter only checks rooms holding the Raider, so Flex can still pick a neighbouring room that the same guard closes.
- **Reading:** fixes the targeted failure and costs nothing measurable, but the trap is ~1–2% of games, so the gain (~+0.01–0.03) is below what 720 pairs can show. Saved as `strategies/experiments/f20e_guarded_rooms.py`.

### F17a: trap rooms as dead ends (the user's "remember dead ends" idea): fewer deaths, less banking; neutral, parked (2026-11-08)
- **User's observation:** our Pacman got caught after walking into a dead end. The agent already knows every simple dead end from turn 1, so nothing has to be remembered during play. The question is why it still dies in them.
- **Analysis** (new `tools/deadend_probe.py`, v3, 480 games): 0.30 deaths per game as Pacman; 65% in dead ends (331 of 469 food lost). 64 in known pockets, **30 in trap rooms**: areas with loops inside and a single door cell, which leaf pruning can't see (42 of 80 map/side combos have one). In 34 of 94 dead-end deaths no enemy ghost was visible when we went in; `safe_food()` only counts visible ghosts.
- **Change:** `_find_trap_rooms()` after the leaf pruning in `_compute_dead_ends()`. For each non-pocket cell taken as a door, cells on that side cut off from the far border become a room (≤ `TRAP_MAX_SIZE` 30 cells, largest room wins). Their `entrance` is the door and their `depth` is the distance to it. Done for both sides, so defenders can trap invaders too. Init cost ≤ 0.05 s. Branch `f17-trap-rooms` (`4496a0a`), saved as `strategies/experiments/f17a_trap_rooms.py`.
- **A/B against v3** (480 games each, 0 crashes or warnings; max move 0.58 s on holdout, p99 0.30):

  | batch | run | Δ points/game | margin | banked | food lost | deaths |
  |---|---|---|---|---|---|---|
  | train | `20261108-100742-ab` | +0.03 ± 0.03 | −0.72 | −0.35 | −0.23 | −0.04 |
  | holdout | `20261108-102736-ab` | −0.05 ± 0.03 | −0.05 | −0.25 | −0.15 | −0.06 |
  | **pooled** | | **−0.01 ± 0.02** | | −0.30 | −0.19 | −0.05 |

  Many opponent rows are exactly ±0.00: maps without trap rooms play out identically.
- **Mechanism (deadend_probe, same games):** deaths 147 → 122; trap-room deaths 29 → 18; pocket deaths 64 → 52; food lost 1.03 → 0.84 per game.
- **Why it doesn't score:** the caution costs as much banking (−0.30) as it saves in food lost (−0.19) plus the respawn walks. Rooms of up to 30 cells make a lot of food "unsafe" whenever a ghost is near the door.
- **Revive ideas:**
  1. Scale caution by what we'd lose: apply the trap-room and dead-end checks only when carrying ≥ 3. 18 of v3's deaths and 28 of F17a's carried nothing, and the food lost is concentrated in deaths carrying 5+.
  2. Smaller `TRAP_MAX_SIZE` (e.g. 12): only the tight rooms like the 2×2 block.
  3. F17b, unseen guards (believed ghost positions in `safe_food` for dead-end food). Expect the same caution trade unless combined with idea 1.

### F17c: trap rooms only when carrying ≥ 3: no effect either way; parked (2026-11-08)
- **Change:** F17a's room maps are kept separate (`room_depth`, `room_entrance`). A Pacman uses them in `safe_food()` and `ghost_cost_fn()` only when carrying ≥ `CAREFUL_CARRY` (3); otherwise it plays exactly like v3. Defenders' `intercept_point()` always uses them. `catchable()` stays on plain pockets, because a scared ghost can circle inside a room. Branch `f17c-careful-carry` (`c9cf2da`), saved as `strategies/experiments/f17c_careful_carry.py`.
- **A/B against v3** (0 crashes or warnings, max move 0.31 s): train `20261108-110332-ab` +0.01 ± 0.01, holdout `20261108-112318-ab` −0.03 ± 0.03; pooled **−0.01 ± 0.02**. Banked −0.06 / −0.14, deaths ±0.00 / −0.02.
- **deadend_probe:** trap-room deaths 30 → 26, food lost 1.04 → 1.02 per game, i.e. almost nothing changed. The banking cost is gone, but so is the benefit.
- **What F17a + F17c show together:** the trap-room deaths are rarely prevented by the visible-ghost checks while carrying. The killers are usually 11+ steps away and often unseen when we go in. F17a only cut deaths through blanket avoidance (any time a ghost was visible), which cost food. The deaths come from **lingering inside** a dead end while a ghost walks up to the door, not from a bad entry decision.
- **Revive idea (F17d, "watch the door"):** while inside a pocket or trap room, carrying food, leave via the door as soon as any enemy ghost (seen, or its believed position) can reach the door no later than we can. Ceiling stays about 0.7 food/game in total for all dead-end deaths.

### F19c: only the Raider pushes: positive on all three pools, **accepted as v5** (2026-11-08)
- **Idea (the user's pick):** F19b pushed with both agents and conceded +0.20 food per game, turning some ties into losses. Keep Flex home instead.
- **Change:** F19b, plus `FlexAgent.decide()` calls `defend()` whenever `deadlocked()` and it carries nothing. Branch `f19c-raider-push`.
- **Deadlock maps** (8 maps × reflex/blitz, both colours): v4 8-22-0, F19b 12-15-3, **F19c 14-13-2**.
- **A/B against v4** (0 crashes or warnings, max move 0.31 s):

  | | train `20261108-215556-ab` | holdout `-221519-ab` | unseen holdout 20–39 `-223302-ab` |
  |---|---|---|---|
  | Δ pts/game | +0.05 ± 0.05 | +0.05 ± 0.04 | +0.03 ± 0.03 |
  | W-T-L v4 → F19c | 165-30-45 → 170-26-44 | 180-29-31 → 187-20-33 | 172-22-46 → 175-19-46 |

  - **Pooled over 720 pairs: +0.040 ± 0.023, z 1.77.** By opponent: reflex +0.16 ± 0.07 (z 2.3), search +0.09, blitz +0.03, turtle 0.00, dario −0.01, tracking −0.03 ± 0.06. Conceded +0.01 (F19b +0.20), banked +0.11.
  - Counting both sides (win 3, tie 1, loss 0): our net +29 points, the opponents' −7.
  - More games differ than with F19b (63 against 27), partly from search timing noise: v4's own W-T-L differs a little between runs.

### F19b: deadlock push with both agents: borderline positive, waiting for the user (2026-11-08)
- **Evidence:** in v4's remaining 0–0 games our agents often never cross. Replay of RANDOM841236 vs reflex: the bold plan blocked the cells around the seen guard (17,10) and around the *believed* second guard at (21,8) (really at (17,11)). Together they sealed every corridor, so the plan found no route and `reposition()` flipped with the safe-food check.
- **Change** (only in `deadlocked()` games): believed guards add cost but no longer block. The Raider (`BAIT = True`) plans with only the guards' own cells blocked and skips the fight search for that move: it carries nothing, so being eaten only costs time, and a guard that chases it leaves its corridor. Flex (`BAIT = False`) keeps the safe bold route. Branch `f19b-deadlock-push` (`f54afe0`).
- **Deadlock maps** (8 maps × reflex/blitz, both colours): v4 8-22-0, F19b 12-15-3.
- **A/B against v4** (0 crashes or warnings, max move 0.33 s):

  | | train `20261108-174930-ab` | holdout `-180922-ab` | unseen holdout 20–39 `-182712-ab` |
  |---|---|---|---|
  | Δ pts/game | −0.01 ± 0.03 | +0.00 ± 0.01 | **+0.10 ± 0.03** |
  | W-T-L v4 → F19b | 165-30-45 → 163-33-44 | 180-29-31 → 182-24-34 | 170-22-48 → 181-13-46 |
  | worst opponent | tracking −0.10 ± 0.07 | search −0.03 | — |

  - **Pooled over 720 pairs: +0.031 ± 0.015, z 2.01.** Ties 81 → 70, losses unchanged at 124.
- **Head-to-head F19b vs v4** (both colours per map): train `20261108-212018-rr` F19b 37-9-34 (net +9 points over 80 games), holdout `20261108-212207-rr` 34-10-36 (net −6). On 74 of 80 maps both agents score the same (the colour decides). F19b is ahead on 4 maps and v4 on 2: even. Both agents had 1–2 timing warnings (max move 1.8 s) in the train run, so a machine hiccup, not F19b.

### F19: deadlock breaker: positive on three pools, **accepted as v4** (2026-11-08)
- **Evidence:** v3 ties 78 of 480 games, 58 of them banking nothing, mostly `stalled`. Replay `20261108-150153-ab-0396` (RANDOM797927 vs reflex): from move 168 to 1200 every agent repeats a 2-move cycle. Our Raider steps to (17,11), the guard at (17,6) comes into sight, no food is safe, it steps back to (16,11), where the guard is out of sight and food looks safe again. Their attacker mirrors it at (16,6) and keeps Flex home.
- **Change** (`deadlocked()`: score tied and ≤ `DEADLOCK_MOVES` (150) own moves left): carry limit 1 (one banked dot turns a tie into a win); unseen non-scared enemy guards count at their `most_likely` cell in `attack()`; when no food is safe and we carry nothing, plan to the cheapest food with ghost-adjacent cells blocked on both sides of the border, instead of `reposition()`; Flex doesn't defend against an invader carrying nothing. Branch `f19-deadlock` (`064781e`).
- **A/B against v3** (0 crashes or warnings, max move 0.32 s):

  | | train `20261108-160527-ab` | holdout `-162536-ab` | unseen holdout 20–39 `-164432-ab` |
  |---|---|---|---|
  | Δ pts/game | +0.10 ± 0.05 | +0.03 ± 0.03 | +0.04 ± 0.03 |
  | ties (v3 → F19) | 49 → 30 | 29 → 29 | 25 → 22 |
  | our banked | +0.81 | +0.22 | +0.31 |
  | invader food banked | +0.71 | +0.10 | +0.13 |
  | worst opponent | reflex −0.05 | blitz −0.07 ± 0.06 | reflex −0.07 ± 0.07 |

  - **Pooled over 720 pairs: +0.053 ± 0.021, z 2.51.**
- **Left over:** some deadlocks are structural. On RANDOM797927 the guard sits on the only corridor into their food, so no route avoids its neighbouring cells. Revive idea: send both agents at once from different crossings to pull the guard.

### F18 / F18b: calm opening: rejected (2026-11-08)
- **Idea (F13 #2):** 84% of big raids start in the first half, often as both of ours cross over. Keep Flex home at the start.
- **Change:** `FlexAgent.opening_hold()`: while it has made ≤ `OPEN_HOLD` moves, Flex calls `defend()` until the first enemy raid is over (an enemy was a Pacman and none is now). Branch `f18-calm-opening` (`d436650`, `34522e0`).
- **A/B against v3** (0 crashes or warnings, max move 0.32 s):

  | | F18 (75) train `20261108-142101-ab` | F18 holdout `-144146-ab` | F18b (35) train `-150153-ab` | F18b holdout `-152219-ab` |
  |---|---|---|---|---|
  | Δ pts/game | −0.15 ± 0.10 | −0.07 ± 0.09 | −0.15 ± 0.09 | −0.08 ± 0.07 |
  | our banked | −2.46 | −1.87 | −1.55 | −1.32 |
  | invader food banked | −0.48 | −1.89 | −0.11 | −0.90 |
  | worst opponent | tracking −0.72 | blitz −0.40 | tracking −0.40 | blitz −0.30 |

- **Why:** the defence gain is real (holdout conceded −1.9) but at best equals the food Flex stops banking, and the extra conceded food on train barely moves. Same lesson as F1/F2/F15: attack throughput wins in this field.
- **Revive ideas:** only against opponents with an early rush (detect a crossing in the first ~15 moves), or hold only while the Raider is also within a few steps of the border.

### F17d: watch the door: deaths −20%, food lost −31%, banking intact, points flat; parked (2026-11-08)
- **Change** (on top of F17c): `door_threatened(cell, d_me)`. (1) Step 2b of `attack()`: inside a pocket or trap room with food, go home as soon as any enemy ghost can reach the door within our distance + `DOOR_MARGIN` (1). An unseen ghost is placed at its `most_likely` cell, with `DOOR_BELIEF_SLACK` (2) extra margin. Ghosts still scared when it matters are ignored. (2) While carrying, skip dead-end food whose door would be threatened by the time we're back out (no re-entry bounce). Branch `f17d-watch-door` (`9cd82bd`), saved as `strategies/experiments/f17d_watch_door.py`.
- **A/B against v3** (0 crashes or warnings, max move 0.31 s):

  | batch | run | Δ points/game | margin | banked | food lost | deaths |
  |---|---|---|---|---|---|---|
  | train | `20261108-120119-ab` | −0.02 ± 0.04 | −0.58 | −0.08 | −0.28 | −0.02 |
  | holdout | `20261108-122051-ab` | +0.01 ± 0.05 | +0.16 | +0.02 | −0.35 | −0.10 |
  | **pooled** | | **−0.00 ± 0.03** | | −0.03 | −0.32 | −0.06 |

- **Mechanism (deadend_probe):** deaths 148 → 118; pocket deaths 63 → 43 (food lost there 218 → 113); deaths carrying 5+ 40 → 23; deaths after an unseen entry 33 → 16. Food lost 1.04 → 0.72 per game. **It does what it was built to do, at no banking cost.**
- **Why points don't move:** the engine (`capture.py`, `dump_food_from_death`) drops a dead Pacman's food back on the map next to where it died. It isn't scored for the enemy, so "food lost" isn't conceded points, only food we have to collect again. A death costs time (the walk from spawn plus re-collecting), and v3 dies only 0.3 times per game. **The dead-end line has a near-zero ceiling in points; closed unless combined with something that converts saved time into banking.**
- **Lesson for the metrics:** `food_lost` overstates the cost of a death. Judge attack changes by `banked` and points.

### F15: proactive capsule cover: defence works, banking pays for it; neutral, parked (2026-11-07)
- **Idea (F14 revive #1, #3, #4):** cover the capsule *before* the invader is close, never recall an attacker, and drop the slack cap.
- **Change:** `SmartAgent.capsule_cover()`, called first in `FlexAgent.decide` and after the Raider's late-lead guard. A ghost of ours at home (unscared, carrying 0) moves towards a defended capsule whenever a threat is within `COVER_RADIUS` (10) of it and we are not at least `COVER_MARGIN` (2) steps closer. The teammate takes it if it is better placed. Threats are invaders, and enemy ghosts that have invaded before (`invader_turns > 0`), or any enemy in the first `COVER_OPENING` (40) turns. This keeps a turtle's border guard from pinning us. `patrol_point` also weights capsules ×`PATROL_CAPSULE_WEIGHT` (5). Branch `f15-capsule-cover` (`234092e`), saved as `strategies/experiments/f15_capsule_cover.py`.
- **A/B against v2** (480 games each, 0 crashes, 0 warnings, max move 0.37 s):

  | batch | run | Δ points/game | margin | banked | conceded |
  |---|---|---|---|---|---|
  | train | `20261107-204214-ab` | +0.05 ± 0.06 | +0.58 | −0.12 | −0.70 |
  | holdout | `20261107-210407-ab` | −0.05 ± 0.06 | −0.02 | −1.07 | −1.05 |
  | **pooled** | | **±0.00 ± 0.04** | +0.28 | −0.60 | −0.88 |

  By opponent: search swung +0.30 (train) / −0.38 (holdout); blitz +0.15 / −0.05 (F14's blitz cost is gone); turtle −0.12 / −0.07.
- **Target metrics (both runs, F15 vs v2):** capsules eaten by invaders 0.79 → 0.73/game; big raids (5+) 1.02 → 0.92/game, food 7.63 → 6.69; big capsule raids 229 → 209; big raids never touched by a ghost 247 → 189. Conceded by raids 9.48 → 8.59/game. "No eligible guard" at the capsule race 94 → 77.
- **Why it doesn't score:** the cost is attack time. `role_probe`: Raider Pacman turns 118.1 → 112.7, banked 8.1 → 7.9; Flex 91.3 → 89.6, 7.5 → 7.2; free ghost turns at home up about 5 per role. Every food we stop costs us about the same food in our own banking.
- **Revive ideas:**
  1. Cover by Flex only: the Raider keeps attacking, so most of the banking cost goes away.
  2. Cover only during the opening (most capsule raids are in the first half), then plain v2.
  3. Cover only from an agent that is idle anyway (stalled at the border), not from one just leaving home.
  4. Stack on the calmer opening (F13 #2).

### F15b: capsule cover by Flex only: neutral, parked (2026-11-07)
- **Change:** F15 with `capsule_cover()` called only from `FlexAgent.decide`, and without the teammate hand-off. The Raider never covers. Branch `f15b-flex-cover` (`5ad3b8b`), saved as `strategies/experiments/f15b_flex_cover.py`.
- **A/B against v2** (480 games each, 0 crashes):

  | batch | run | Δ points/game | margin | banked | conceded |
  |---|---|---|---|---|---|
  | train | `20261107-223045-ab` | **+0.12 ± 0.05** (gate passed) | +0.75 | −0.12 | −0.87 |
  | holdout | `20261107-225307-ab` | −0.11 ± 0.07 | −0.15 | −0.78 | −0.62 |
  | **pooled** | | **±0.00 ± 0.04** | +0.30 | −0.45 | −0.75 |

  By opponent (train / holdout): dario +0.40 / +0.33 (consistently better), search +0.38 / −0.42, tracking −0.07 / −0.33, turtle −0.07 / −0.25, blitz −0.05 / +0.07, reflex +0.12 / −0.05.
- **Reading:** search flipped sign between the map pools in both F15 (+0.30 / −0.38) and F15b. That looks like a map-dependent effect, not noise: the cover helps on train maps and hurts on holdout maps. The banking cost stayed on holdout (−0.78) even with only Flex covering. The Dario gain is the one consistent signal.
- **Timing:** max move 0.43 s, 0 warnings for us. v2 had 10 warnings on holdout because replay probes were running in parallel. Don't run probes during an A/B.
- **Revive ideas:** find which holdout maps lose (`query.py` by layout). If they share a shape (for example, a capsule near the border), gate the cover on it. Or use the cover only against opponents that eat capsules often (Dario: 111 of 141 big raids involve a capsule).

### F14: capsule guard: positive but not significant, parked (2026-11-06)
- **Idea (from F13):** half of v2's big raids involve a capsule. Race an invader to a capsule it's close to.
- **Change:** `SmartAgent.capsule_guard()`, called first by both roles (after the Raider's late-lead guard). It fires when an invader on our side is within `CAP_GUARD_RADIUS` (10) of one of our capsules. The nearest unscared teammate that's at home, or attacking within `CAP_GUARD_RECALL` (3) of our border, walks to the capsule (or stays on it), but only while the race is tight: at most as far as the invader and no more than `CAP_GUARD_SLACK` (2) ahead. Branch `f14-capsule-guard` (`dee79b0`), saved as `strategies/experiments/f14_capsule_guard.py`.
- **A/B against v2** (480 games each, 0 crashes):

  | batch | run | Δ points/game | margin | banked | conceded | unopposed food |
  |---|---|---|---|---|---|---|
  | train | `20261106-222501-ab` | **+0.10 ± 0.05** | −0.04 | −0.12 | −0.08 | −0.45 |
  | holdout | `20261106-225957-ab` | −0.00 ± 0.06 | +0.18 | −0.35 | −0.54 | −0.54 |
  | unseen holdout (offset 20) | `20261106-232246-ab` | +0.05 ± 0.05 | +0.29 | −0.30 | −0.59 | −0.67 |
  | **pooled** | | **+0.05 ± 0.031 (z 1.6)** | +0.14 | −0.26 | −0.40 | −0.55 |

  By opponent (pooled): reflex +0.13, tracking +0.16, search +0.06, dario +0.07, turtle +0.03, **blitz −0.14 ± 0.07 (z −1.9)**. The guard recalls an attacker often against a team with two attackers.
- **Timing:** train had 6 warnings for us and 7 for v2 (machine load, both sides alike). Holdout had a max move of 0.71 s (p99 0.30). Under the 1 s limit, but worth watching.
- **Target metric:** `raid_fate_probe.py` (same games): big raids with a capsule 401 → 382, food conceded by raids 10.02 → 9.62/game. `capsule_race_probe.py`: capsules eaten by invaders 0.90 → 0.85 per game.
- **Why the effect is small:** when an invader first comes within 10 steps of the capsule it will eat, our nearest responder can win the race in only about 10% of cases (v2: 68 of 648 ahead or tied). 54% of the time the responder is 3+ steps behind, and in 28% there's no eligible responder at all (everyone deep in attack or scared). A reactive race can't fix a capsule that's already lost by positioning.
- **Revive ideas:**
  1. **Proactive capsule cover:** when a ghost of ours is home with no invader in, weight `patrol_point` towards the capsule nearest the enemy's likely crossing. Or keep the home ghost within (invader's distance − 1) of our most exposed capsule as soon as an enemy ghost nears the border.
  2. Combine F14 with the calmer opening (F13 #2): most capsule raids are early, while both of ours are away.
  3. Don't recall attackers against teams with two attackers (blitz), where it cost banking.
  4. Drop the slack cap: in 48 capsule losses with F14 our responder was ahead and still lost it.

### F13: where v2 concedes food: big raids, capsules and the opening (analysis, 2026-11-06)
- **Data:** v2's 720 games in the F12 runs (`20261106-210014-ab`, `-212044-ab`, `-214120-ab`). Tools: `diagnose.py unopposed` and the new `tools/raid_fate_probe.py`.
- **Unopposed bites** (no ghost of ours within 6): 8.3 / 10.8 / 12.4 per game. When they happen, both our agents are attacking in 42% / 59% / 60% of cases. In the rest, the nearest home ghost is usually far (≤10 steps in 32%, 11–20 in 47%, 21+ in 21%), and 28% of the time it's scared.
- **A few big raids carry almost everything:** v2 faces 24.6 raids per game, but the **1.1 per game that bank 5+ food bring 8.1 of the 10.1 food conceded (80%)**. 53% of those never come within 6 steps of an unscared ghost of ours.
- **Half the big raids involve a capsule** (400 of 804, 4.3 food/game; one of ours turned scared during the raid). Against dario it's 111 of 141.
- **They happen early:** 84% of big raids start in the first half (quarters 1–4: 361 / 317 / 101 / 25). **Late raids are rare (3%)**, which caps what F10-style "protect the lead late" can win.
- **Where we were when a big raid started:** both attacking 286, Raider attacking and Flex home 205, Raider home and Flex attacking 87, both home 226. When at least one of ours was attacking, the nearest attacker was usually **within 3 steps of the border** (318 of 578): we cross into their side just as they cross into ours. An attacker came home during 75% of those raids, mostly too late.
- **Conclusions / next candidates:**
  1. **Capsule guard (most food):** when an invader is on our side and closer to one of our capsules than our nearest ghost, the home ghost (or an attacker within a few steps of the border) moves to sit between it and the capsule. F11's race evaluation covers capsules only inside fight range (6).
  2. **Opening crossing:** stop both agents crossing at the same time as the enemy in the first quarter. For example, Flex waits at the border until the first invader shows, or turns back if it sees an invader within ~6 steps of the border while it's within 3 of it.
  3. F10 revive is lower value than expected: late big raids are only 3%.
- Re-measure with `python tools/raid_fate_probe.py my_team <run_ids>` (or `v2`).

### F11c: measuring F11's "attack cost": there isn't one (analysis, 2026-11-06)
- **New tool:** `tools/role_probe.py <runs>` gives per-role (Raider/Flex) banked food, Pacman turns, home turns with an invader within 6 (fight), free home turns, stuck turns, and turns near the border.
- **F11 against v1, per agent and game, over F11's three runs:**
  - Pacman turns are unchanged (±5 in both directions).
  - Flex has +3 to +6 fight turns, taken from its free home time, not its attack time.
  - Banked differs by about −0.3 per agent in two runs and is level in train.
- **Paired significance over all 720 F11/v1 pairs** (same map, opponent and colour):

  | metric | F11 Δ/game | z | F11b Δ/game | z |
  |---|---|---|---|---|
  | invader food banked against us | **−1.11 ± 0.22** | **−5.0** | −0.79 ± 0.21 | −3.7 |
  | score margin | **+0.78 ± 0.23** | **+3.4** | +0.54 ± 0.21 | +2.6 |
  | our banked | −0.33 ± 0.21 | −1.6 | −0.24 ± 0.16 | −1.5 |
  | deaths | +0.00 ± 0.02 | 0.1 | −0.02 ± 0.02 | −1.2 |

- **Conclusion:** the banking drop is within noise and has no structural cause, so there's nothing to fix on the attack side. F11's defence gain is strongly significant and shows up as margin (z = 3.4). Points (W/T/L) are coarser and reach only z = 1.86, because most extra margin lands in games that were already won.
- **Options:**
  1. Accept F11 on the margin evidence. This would be a change of acceptance rule, so it's the user's decision. Margin is the league's tie-break.
  2. Stack another defence gain on F11 to turn margin into results. F9's home hunt (+40% kills, near-free) and F10-lite (guard a big late lead) both failed because our ghosts couldn't catch anyone, which F11 addresses.

### F11b: F11 racing only invaders that carry food: neutral, code kept (2026-11-06)
- **Idea:** F11 lost about 0.6 banked per game. The guess was that the cost came from brief border fights with empty-handed invaders, where the race term holds our ghost at an exit instead of letting it chase and go back to attacking.
- **Change:** F11, but the race term is applied only to invaders carrying ≥ `RACE_CARRY` (1) at the search root. Empty-handed ones get v1's `8 · home_escape_gap`. Deciding at the root keeps the evaluation consistent within one search.
- **A/B against v1:** 0 crashes, 0 warnings, max move 0.45 s.

  | | train `20261106-193727-ab` | holdout `20261106-195733-ab` | unseen holdout 20–39 `20261106-201714-ab` |
  |---|---|---|---|
  | Δ pts/game | +0.07 ± 0.06 | +0.04 ± 0.06 | +0.04 ± 0.06 |
  | our banked | +0.23 | −0.49 | −0.47 |
  | invader food banked against us | −0.45 | −1.37 | −0.54 |
  | idle_attack | +4.0 | +5.2 | +0.3 |

  - **Pooled** (360 pairs): **+0.051 ± 0.035, z = 1.47.** That's below F11 (z = 1.86), so it's not accepted.
  - By opponent: tracking +0.19 (2.1 SE), search +0.11, blitz +0.06, turtle +0.04, dario −0.04, reflex −0.05.
- **What this says:** the banking cost didn't come back. idle_attack and banked moved just as in F11. So **F11's attack cost doesn't come from fights with empty invaders**, and the guess was wrong. Restricting the race also gave back some defence (holdout conceded −1.37 against F11's −1.62), so plain F11 remains the better version.
- **Status:** saved as `strategies/experiments/f11b_race_when_carrying.py`; `my_team.py` stays v1.
- **Next:** measure where F11's attack cost actually comes from before tuning further. Candidates:
  - per-agent banked and idle turns (Raider vs Flex) in matched F11/v1 games;
  - whether the defender's fight search now keeps Flex from crossing (its `ESCAPE_PENALTY` dominates while an invader is anywhere within 6);
  - whether `FOOD_FIRST_WEIGHT` pulls ghosts deep into our half.

### F11: Defender fight evaluation races the invader (exits, food, capsules): promising, parked at z = 1.86 (2026-11-06)
- **Evidence:** `tools/chase_probe.py` replays games and classifies how every chase ends. A chase starts when one of our unscared ghosts is within 3 steps of an invader, and ends caught / crossed / outran / capsule / ghost_left.
  - **v1 chases from behind.** In `20261106-155310-ab-0299` Flex trails an invader at exactly 3 steps for 100 turns while it eats 5 → 10 food, and the Raider trails another one at 1 step for 40 turns. An equal-speed Pacman can't be caught from behind. This explains F10: our ghost was near the raider but never caught it.
  - **Cause:** the defender branch of `evaluate_fight` scored −20·distance + 8·(lead to the invader's single nearest exit). It ignored our teammate and our own scared timer. With a search about 4 moves deep, that means following the invader.
- **Ruled out:**
  - **Cycle pockets with one exit cell (a choke):** this looked likely from game 0339, where the invader circled a loop with 11 food for 400 turns. But chases where we reach a choke first are already caught 70–75% of the time, and they are only 1–3% of the big escapes.
  - **Most capsule losses:** in those, the invader was nearer the capsule than us.
- **Change:** `SmartAgent.invader_race()` replaces `home_escape_gap` in the defender evaluation. "Guards" are our searching ghost plus home, unscared teammates (held static), and the penalty counts what the invader reaches strictly before every guard:
  - `ESCAPE_PENALTY` 300 if it reaches some border exit first, plus `EXIT_LEAD_WEIGHT` 25 per step of its best-exit lead (clipped ±6);
  - `FOOD_FIRST_WEIGHT` 8 per defended dot it reaches first;
  - `CAPSULE_FIRST_PENALTY` 200 per capsule it reaches first;
  - `SCARED_PENALTY` 500 when we are scared.

  Results are cached per (our cell, invader cell) within a search.
- **A/B against v1:**

  | | train `20261106-162806-ab` | holdout `20261106-164753-ab` | unseen holdout maps 20–39 `20261106-171206-ab` |
  |---|---|---|---|
  | Δ pts/game | +0.09 ± 0.08 | +0.06 ± 0.06 | +0.07 ± 0.06 |
  | W-T-L v1 → F11 | 139-48-53 → 145-52-43 | 167-30-43 → 171-32-37 | 155-26-59 → 161-24-55 |
  | invader food banked against us | 9.30 → 8.69 | 11.60 → **9.97** | 12.60 → 11.51 |
  | capsule food conceded | 1.21 → 1.14 | 2.08 → 1.68 | 2.08 → 1.78 |
  | our banked | 14.95 → 15.19 | 16.69 → **16.10** | 17.87 → **17.23** |
  | idle_attack | 51 → 57 | 45 → 50 | 39 → 39 |
  | leads lost | 26 → 21 | 13 → 11 | 30 → 28 |

  - **Pooled** (360 pairs, decision rule fixed before the third run: pooled Δ > 2 SE and the fresh batch ≥ 0): **+0.072 ± 0.039, z = 1.86**. It narrowly fails, so it's parked.
  - By opponent, pooled: search +0.15, tracking +0.15, blitz +0.12, turtle +0.05, dario +0.04, reflex −0.08 (all within 1.5 SE).
  - Chase probe (holdout, v1 → F11): escapes with the invader carrying 3+ went 146 → 106 (food 876 → 635); capsule endings 79 → 57.
- **Timing:** 3 holdout games had a move of 0.5–0.68 s (v1 max 0.38). None of them reproduced when replayed with a profiler, so they look like load spikes. The other two runs maxed at 0.31 s. The `TURN_BUDGET` of 0.75 s caps a turn anyway.
- **Why it's not clearly better:** defence improved in all three runs (−0.6 to −1.6 food conceded), but our own banking fell by about 0.6 in two of the three. A ghost near the border now holds an exit or the food race instead of chasing briefly and returning to attack.
- **Status:** saved as `strategies/experiments/f11_race_eval.py`; `my_team.py` stays v1. **The strongest candidate so far.**
- **Revive ideas** (F11b, cheapest first):
  1. **Apply the race only when the invader carries food** (or ≥ 2). Otherwise keep v1's chase-and-return, to win back the attack time.
  2. **Only the agent in defence mode uses the race term;** the Raider's incidental `hunt_nearby_invader` fights keep the v1 evaluation.
  3. Lower `FOOD_FIRST_WEIGHT` (it pulls the ghost deep into our half), or drop it.
  4. Then retry F10 (guard a big late lead) on top: with a ghost that cuts ahead instead of trailing, a home guard might finally pay.

### F6: Spend the scared-guard window on food, not on eating scared ghosts (user's fix)
- **Evidence:** v0 in `20261103-183912-ab`, measured with `diagnose.py capsules`, per window we open.

  | metric (per window) | v0 | dario |
  |---|---|---|
  | food eaten | 6.0 | 6.5 |
  | banked | 3.8 | 2.9 |
  | still carrying when the window closes | 5.5 | 6.2 |
  | scared ghosts eaten | **0.72** | 0.09 |
  | their timer left when eaten | **25.9 moves** | 3.7 |

  Eating a scared ghost respawns it un-scared, so v0 throws away about 26 of the 40 free moves.
- **Cause:**
  - `attack()` step 2 deliberately chases scared ghosts within 2 steps.
  - `plan()` routes through scared ghosts' cells.
  - During the window, food choice keeps the carry limit, the home penalty and the "bank first" shortcut.
- **Change:**
  - Block the cells of scared ghosts with timer > `WAKING` (3).
  - Only eat an adjacent scared ghost whose timer is 2–3 (about to wake up).
  - New step 4a, `harvest_tour()`: a greedy food tour that fits `scared timer − HARVEST_MARGIN` including the way home, with no carry limit. When no dot fits the remaining time, bank.
- **Kept on purpose:** when a scared ghost blocks the only way home, `go_home` falls back to walking through it. Seen in smoke-test game `20261103-192635-gauntlet-0000` at turn 396: we carried 12 and the ghost shadowed us.
- **Smoke test (6 games against dario):** banked per window 7.1, carrying at window end 1.8, 0 crashes.
- **Target metrics:** food eaten and banked per window ↑; scared ghosts eaten per window ↓; carrying at window end ↓.
- **A/B (train), `20261103-192737-ab`:** 480 games, 0 crashes, max move 0.32 s.
  - Δ **−0.02 ± 0.06** pts/game: **neutral, did not pass the gate.**
  - By opponent: blitz +0.07, turtle +0.10, dario −0.03, reflex −0.03, tracking −0.07, search −0.15 (every one within 1.2 SE).
- **Target metrics moved as intended:**

  | metric | v0 | F6 |
  |---|---|---|
  | banked per window | 3.8 | **6.9** |
  | food eaten per window | 6.0 | 6.9 |
  | carrying at window end | 5.5 | 3.4 |
  | scared ghosts eaten per window | 0.72 | **0.11** |

- **Why no points:**
  - **Windows are rare.** We only open 0.53 windows per game.
  - **The extra banking is mostly a timing shift, not new food.** v0 banked its leftover 5.5 later anyway: banked per *game* 14.15 → 14.13. The only truly extra food is about +0.9 per window, roughly +0.5 per game.
  - **Eating a scared ghost had a hidden value we gave up.** It sends that ghost on a long walk back from spawn. Invader food banked against us went up by 0.24 per game and unopposed food by 0.22, which fits the opponent getting that walk back.
- **Status:** saved as `strategies/experiments/f6_harvest.py`; `my_team.py` reverted to v0. Holdout skipped.
- **If revisited:**
  1. Combine it with F7 (take more capsules). The harvest only pays off if there are more windows.
  2. Allow eating a scared ghost when it's cheap and far from its spawn (the long walk back is the real value), and only block it when the ghost is near its spawn.

## To fix

### F7: We take few capsules
- **Evidence:** 0.51 capsules per game for v0, against dario 0.85 and tracking 0.84.
- **Idea:** go for a capsule early when a guard blocks the entry, or when the capsule is on our way in.

### F8: Our scared defenders get eaten (found with `watch.py`)
- **Evidence:** `watch.py events 20261103-180445-rr-0126`, our worst Cycle 0 game (−29 against turtle). After the opponent's capsule, **both** our ghosts were eaten in the same turn, twice: at turns 337 and 520. The opponent then raided unopposed.
- **Idea:** while scared, keep at least distance 2 from visible invaders. `defend()` already shadows at distance 2, but the Raider (attacking) doesn't, and two agents together are an easy double kill. Measure scared deaths per game before choosing.

### F1b: Gated recall (low priority, after F2)
Recall Flex for a big haul only if it reaches the invader's escape crossing first (`intercept_point()` / `home_escape_gap()`). See the F1 post-mortem below for why it's low priority.

### F2: Nobody home when both attack (defence gap, larger share)
- **Evidence:** 48% of unopposed bites happen while both our agents are attacking. Another 634 bites happen while the invader carries 1–3, which is below the `DANGER_HAUL` trigger.
- **Ideas:**
  - Lower `DANGER_HAUL` (sweep 2/3/4).
  - Trigger on vanished food on our side.
  - Let the defence budget refill slowly instead of hitting a hard cap.
- **Target metric:** "raider attacking / flex attacking" share and bites with the invader carrying 1–3.

### F3: Flex home but slow to reach invaders → superseded by F9
- **Evidence:** in 219 big-haul bites Flex was already home but about 15 steps away. In 94% of all unopposed bites the invader was unseen, so Flex chases a belief.
- **Update (F9 analysis):** locating an unseen invader is *not* the problem. `raid_probe.py` shows the most-likely cell is a median 2 steps from the truth (p75 4). The problem is that nobody home responds; see F9.

### F9: Home hunt: neutral, code kept (2026-11-04)
- **Evidence: v1 loss analysis** (480 games, train `20261103-232842-ab` + holdout `20261104-154525-ab`; 307 W, 79 T, 94 L).
  - **54 losses: outplayed from early on.** We bank 5.8, they bank 15.1, 11.9 unopposed.
  - **40 losses: lead lost late** (median turn 1000).
    - One enemy trip, about 64 rounds long, banks 8.7 food on average (max 45, `20261103-232842-ab-0027`).
    - Our ghost was within 3 steps only 10% of that trip.
  - **79 ties:** 56 of them 0–0 deadlocks, concentrated on a few maps. Left as they are for now.
- **`tools/raid_probe.py` on v1** (24 holdout games against dario/tracking/search/reflex). During enemy raids:
  - both agents are deep in enemy territory carrying food about 50–65% of the time;
  - the Raider is home but still attacking ("no trigger") 21% of the time when the invader carries 4+.
- **Change:** `SmartAgent.home_hunt()`. An agent at home, not scared and carrying nothing defends against an invader carrying ≥ `HUNT_CARRY` (2) when it is within `HUNT_RADIUS` (10), when we reach its exit first, or always when its haul would erase our lead. Only the closer of two eligible agents goes. It's hooked into `RaiderAgent.decide`.
- **Probe after:** Raider "home, no trigger" at 4+ went 21% → 7%.
- **A/B against v1:** 0 crashes, max move 0.31 s.

  | | train (`20261104-163637-ab`) | holdout (`20261104-165651-ab`) |
  |---|---|---|
  | Δ pts/game | −0.01 ± 0.06 | +0.00 ± 0.06 |
  | by opponent | tracking +0.20, blitz −0.10, reflex −0.12 | dario +0.20, turtle +0.15, search −0.35 (2.1 SE) |
  | kills | 0.37 → 0.43 | 0.36 → **0.50** |
  | invader food banked against us | 9.34 → 9.04 | 11.46 → 11.03 |
  | our banked | 15.00 → 14.79 | 16.71 → 16.59 |
  | leads lost (`diagnose.py leads`) | 26 → 25 | 13 → 16 |

- **Why no points:** the home hunt catches more invaders (+40% kills on holdout), but the decisive late raids are untouched. During them our ghosts were within 3 steps only 8–12% of the trip. Those raids happen while both our agents are away carrying food. An agent that passes home only briefly can't stop a 60–70-round raid deep in our half.
- **Status:** saved as `strategies/experiments/f9_home_hunt.py`; `my_team.py` stays v1.
- **Revive ideas:**
  - Combine with a lead-protection guard (below), since kills are up.
  - Sweep `HUNT_CARRY` 1 and `HUNT_RADIUS` 15.

### F4: Same path out of long spawn corridors
- **Evidence:** RANDOM398056 was lost 3 of 4 times (−29, −13, −13). Both agents walk out together, never cross the border, and the opponent raids freely.
- **Idea:** give each agent its own crossing (upper and lower half of the border), and keep Flex home when the trip to the border is long.

## Fixed

### F23: Apex, v7 + four follow-ups behind flags: **accepted as v8** (2026-11-10)
- **Parts:**
  - **A `PROFILE`:** classify the opponent from the share of turns its agents are Pacmen in our half (after 200 agent turns).
    - double attack (both at once > 15%): Flex `DEFEND_RADIUS` 12, `FREE_DEFENCE` 80, and Flex skips a push while any invader is home.
    - passive (< 5%): Flex ignores empty-handed invaders, and the deadlock push starts at 250 own moves.
    - Check: blitz double (27–39%); dario/search/hydra standard; turtle reaches 18% "both" late (it raids with both when behind), never passive.
  - **B `PUSH_GUARD`/`PUSH_STUCK`:** Flex skips a capsule push while 2 invaders are home (F22a). A push that got no closer to its capsule in 12 own moves is aborted, and the capsule banned for 60 (F22c).
  - **C `CUTOFF`:** `defend()` against an invader carrying ≥ 1 considers exits up to 3 further than its nearest. If we beat it to all of them, we meet it on the path to the exit where our lead is smallest. Otherwise the old intercept applies.
  - **E `PIN_RESCUE`:** the planned F22b turned out not to be a push problem.
    - v7's extra games ending while carrying food (59 vs v6's 46 in 720 games) are mostly a pinned carrier: e.g. `20261109-223858-ab-0147`, where the Raider is pinned 4 cells inside with 7 food by one guard for 150+ turns, and the game ends 0–0.
    - Banking would have flipped 8 ties and 9 losses (ceiling about +0.04).
    - Fix: Flex attacks while the Raider is trapped with food, the score is ≤ 0, ≤ 300 own moves are left, and no invader carrying 2+ is home.
- **A/B against v7** (seven opponents incl. Hydra, 840 pairs): train +0.04 ± 0.05, holdout +0.10 ± 0.04, unseen +0.03 ± 0.04; pooled **+0.057 ± 0.025 (z 2.2)**.
  - Pooled by opponent: reflex +0.09, dario +0.09, search +0.08, blitz +0.07, hydra +0.06, tracking 0.00, turtle 0.00.
  - Conceded −0.29 / −0.46 / −0.38; banked +0.16 / +0.12 / −0.24.
- **Ablation** (each part off against full Apex; Δ = without − with, so negative means the part helps; train / holdout, 280 pairs each):

  | part off | train | holdout | what it buys |
  |---|---|---|---|
  | C cut-off | −0.09 ± 0.04 | −0.08 ± 0.04 | the biggest: conceded +0.51 in both pools without it; hydra −0.30 / −0.15 |
  | B push guard/abort | −0.05 ± 0.03 | −0.04 ± 0.03 | blitz −0.07 / −0.12 |
  | E pin rescue | −0.06 ± 0.03 | −0.00 ± 0.03 | timeout_carry +0.11 / +0.06 without it |
  | A profiling | +0.00 ± 0.04 | −0.01 ± 0.01 | neutral overall; blitz −0.25 without it on train, search noisy (+0.17 / −0.12) |

  All four are kept: none is negative, and A only acts against double-attack teams (it leaves 'standard' opponents' games identical).
  - Timing: Apex's max move was 0.40 s. One run spiked to 0.75 s for dario and the variant alike: machine load from 10 workers on 10 cores, not code. Use 8 workers.
- **Parameter sweep** (each variant against full Apex, 280 pairs per pool; files in `strategies/experiments/sweep/`): **nothing kept, Apex keeps v7's constants.**

  | variant | train | holdout | unseen |
  |---|---|---|---|
  | `CARRY_LIMIT` 8 | +0.09 ± 0.05 | −0.01 ± 0.04 | |
  | `PUSH_MOVES` 180 | +0.07 ± 0.05 | **−0.14 ± 0.05** | |
  | both together | +0.10 ± 0.07 | −0.06 ± 0.06 | +0.01 ± 0.06 (pooled ≈ +0.02 ± 0.04) |
  | `SCARED_BANK_MARGIN` 2 / 4 | +0.01 / −0.03 | | |
  | `PREY_TRAP_RANGE` 12 | −0.00 | | |
  | `PUSH_LEAD` 2 | −0.01 | | |
  | `CARRY_LIMIT` 6 | −0.07 | | |

  - The same lesson as F15b: train-only gains of +0.07–0.10 didn't survive holdout. The constants look close to a local optimum.
  - `CARRY_LIMIT` 8 still raised banked food (+0.68 on train), so a carry limit that depends on the opponent or the map could be a revive idea.
- **Status:** final Apex = the four parts with v7's constants. **Accepted by the user as v8**; frozen as `strategies/history/v8.py`.

### F22: capsule push to win (the user's idea): **accepted as v7** (2026-11-09)
- **Weakness:** v6 ends 147 of 720 ties/losses with an enemy capsule unused; one scared window (40 moves) would often have covered the deficit.
- **Change:** `capsule_push()` (team state `push`): per enemy capsule, `sweep_value` = dots two agents could eat and bank within `SWEEP_BUDGET` (38) moves (one from the capsule, one from the nearest crossing; greedy, cached). Fire when the sweep alone leaves ≤ 2 dots (food-limit win), or when ≤ `PUSH_MOVES` (120) own moves are left, we're at most `PUSH_LEAD` (0) ahead and score + carried + sweep ≥ 1. Both agents head for the nearest capsule; once eaten, F16's unlimited scared-window attack sweeps and banks; the push ends with the window. Capsules are never held back (the user's constraint): escapes and normal play still eat them.
- **Result vs v6 (720 pairs, three pools):** pooled **+0.115 ± 0.031 (z 3.8)**; unseen +0.23 ± 0.06 passes alone. Ties/losses → wins: 534-64-122 → 566-51-103. Banked +0.78, conceded +0.27 (home is empty during a push). Blitz ±0.01 (two attackers punish the empty home).
- **Follow-ups:** keep Flex home during a push when two invaders are in our half (blitz); abort a push that makes no progress towards a guarded capsule.


### F16: scared-window discipline (the user's observations): **accepted as v3** (2026-11-08)
- **What the user saw:** (1) an attacker next to a scared ghost in a 2×2 block shuffles back and forth until the timer ends; (2) an attacker eats and chases during the window, then the guards recover while it's far from home with food.
- **Measured** (`tools/scared_window_probe.py`, v2, 480 games): in 46% of scared windows an attacker oscillates next to a scared ghost, 7.8 wasted moves per window. Example `20261107-204214-ab-0244`, moves 620–682: carrying 8 food, 6 steps from home. Cause: `attack()` step 2 chased any scared ghost within 2, ahead of banking. Deaths right after a window were rare (0.12 food/game). The bigger loss was time: only 1.6 food per window was banked inside it.
- **Change** (branch `f16-scared-window`, `f9177aa`):
  1. `catchable()`: chase a scared ghost only when it's adjacent, or trapped in a pocket where we're closer to the mouth (≤ `PREY_TRAP_RANGE` 8, within its timer).
  2. Step 4b: while the guards are scared and we carry food, bank once their timer ≤ home distance + `SCARED_BANK_MARGIN` (3). Until then, target only food with dist(us, food) + home distance(food) + 3 < timer.
- **A/B against v2** (480 games each, 0 crashes, 0 warnings, max move 0.34 s):

  | batch | run | Δ points/game | margin | banked | conceded |
  |---|---|---|---|---|---|
  | train | `20261107-234257-ab` | **+0.12 ± 0.05** (gate passed) | +0.73 | +0.15 | −0.58 |
  | holdout | `20261108-000312-ab` | **+0.10 ± 0.05** (gate passed) | +1.34 | +0.94 | −0.40 |
  | **pooled** | | **+0.11 ± 0.035 (z 3.1)** | +1.04 | +0.55 | −0.49 |

  By opponent (train / holdout): blitz +0.23 / +0.05, dario +0.05 / +0.23, reflex +0.42 / +0.03, search +0.20 / −0.05, tracking −0.20 / +0.20, turtle ±0.00 / +0.15.
- **Mechanism (same runs):** oscillating moves near a scared ghost 7.8 → 1.7 per window; food banked inside windows 1.6 → 5.6 per window; scared ghosts eaten 0.66 → 0.52 per window; carrying 9+ steps from home when the window ends 295 → 174.
- Frozen as `strategies/history/v3.py`.

### F5a: banking flip at the carry-limit cliff: v1 (2026-11-04)
Commit to banking once the carry limit sends us home. Holdout +0.24 ± 0.06 pts/game (`20261104-154525-ab`). Details are under F5 in "In progress"; F5's crossing standoff part is still open.

## Rejected

### F10: Protect the lead (Flex guards full-time when ahead late): rejected, code kept (2026-11-06)
- **Idea:** the 40 "lead lost late" losses in v1 come from one long enemy raid while both our agents are away (see F9). So when we're ahead in the second half, Flex stops attacking and guards home full-time with `defend()`. The Raider keeps attacking.
- **Change:** in `FlexAgent.decide`, when score ≥ `GUARD_LEAD` (1) and own moves left < `GUARD_MOVES` (150), call `defend()`, which banks any food carried first. Flex reverts once the lead is gone.
- **A/B against v1:** 0 crashes, 0 warnings, max move 0.31 s.

  | | train (`20261106-153419-ab`) | holdout (`20261106-155310-ab`) |
  |---|---|---|
  | Δ pts/game | **−0.13 ± 0.06** | **−0.09 ± 0.06** |
  | W-T-L v1 → F10 | 139-49-52 → 127-54-59 | 169-28-43 → 161-30-49 |
  | by opponent | dario −0.28, turtle −0.23, reflex −0.15, blitz −0.05, tracking −0.07, search 0.00 | reflex −0.28, search −0.17, blitz −0.12, tracking −0.07, dario +0.05, turtle +0.05 |
  | our banked | 14.97 → 14.12 | 16.81 → 16.12 |
  | invader food banked against us | 9.30 → 9.57 | 11.56 → 11.62 |
  | kills | 0.36 → 0.38 | 0.36 → 0.46 |
  | capsule food conceded | 1.21 → 1.60 | 2.10 → 2.34 |
  | **leads lost** (`diagnose.py leads`) | **26 → 32** | **13 → 20** |
  | our ghost within 3 steps of the decisive raid | 9% → 28% | 14% → 32% |

- **Why it failed:**
  - **Having a guard home didn't stop the raids.** Our ghost was near the decisive raid three times as often (median 2 steps away), yet more leads were lost. `defend()` shadows an invader but rarely catches one that is evading. The raider gets past the guard, or eats a capsule (capsule food conceded went up) and walks through.
  - **Flex's attack was what kept the lead safe.** It banked 0.7–0.85 less per game, so leads stayed narrow, and one ordinary raid was enough to flip them. Conceded food didn't fall at all.
  - This is the same lesson as F1, F2 and F5c: a full-time `defend()` Flex is a weak guard, and attack throughput protects a lead better than guarding does.
- **Status:** saved as `strategies/experiments/f10_protect_lead.py`; `my_team.py` stays v1.
- **Revive ideas:**
  1. **Only guard a big enough lead, late:** e.g. lead ≥ 5 with < 75 moves left, so throughput isn't given up while the lead is still narrow.
  2. **Fix `defend()` first:** find out why a ghost 2 steps away doesn't catch the raider. Watch the raids with `watch.py`. Possible causes are a chase with no cut-off of the exit, and no guard on the capsule. Then retry F10.
  3. **Guard the capsule:** while guarding, stand between the invader and our capsule.
  4. Combine with F9's home hunt (kills went up in both).

### F2+F7: Shallow Flex plus taking safe capsules when guarded (rejected 2026-11-03)
- **Change:**
  - Flex attacks only food within 8 steps of our border (`SHALLOW`); once none are left, it takes the shallowest food left.
  - Flex answers nearby invaders while it's a Pacman within 4 steps of home (`RECALL_DIST`).
  - Any attacker takes a safe capsule within 8 steps when a guard is in sight (`CAPSULE_DETOUR`), and before repositioning when every dot is guarded.
  - Saved as `strategies/experiments/f2_f7_shallow_capsules.py`.
- **A/B (train), `20261103-195324-ab`:** 480 games, 0 crashes.
  - Δ **−0.18 ± 0.07** pts/game: significantly worse.
  - By opponent: search −0.42, tracking −0.35, reflex −0.25, blitz −0.10, dario −0.03, turtle +0.07.
- **What moved:**

  | metric | v0 | F2+F7 |
  |---|---|---|
  | banked per game | 14.09 | 13.20 |
  | invader food banked against us | 8.99 | 9.47 (**up**) |
  | unopposed bites per game | 8.2 | 7.7 |
  | "both attacking" share of unopposed bites | 45% | 46% (unchanged) |
  | capsules per game | 0.51 | 0.56 |

- **Why it failed:**
  - **Border food is the most guarded food.** search, tracking and reflex all patrol the border, so a shallow Flex attacks exactly where their defender stands. Flex banked per game fell 8.62 → 6.61 (against others) and 7.09 → 6.04 (against search/tracking/reflex). The Raider only gained against non-patrolling teams (7.8 → 9.25), because Flex stopped competing with it for deep food.
  - **Being close didn't make defence better.** A shallow Flex counts as "attacking" and is still more than 6 steps from the invaders, and `RECALL_DIST` = 4 rarely fires. Invader food banked against us even rose.
  - **F7 barely changed capsule use** (+0.05 per game). Safe capsules within 8 steps while a guard is visible are rare.
- **Lesson:** three changes in a row that moved an agent toward defence (F1, F2) or traded food for safety all lost points. In this field, **attack throughput is what wins**. Defence has to come at no throughput cost, or it doesn't pay.

### F1: Flex turns back for big hauls even while carrying food (rejected 2026-11-03)
- **Evidence:** Cycle 0 (`20261103-180445-rr`, v0).
  - In 321 of the 690 unopposed bites by an invader carrying 4+ (47%), Flex was carrying food.
  - That's because `FlexAgent.decide` only defends when `num_carrying == 0`.
- **Change tried:** let the `DANGER_HAUL` trigger fire while carrying; `defend()` walks Flex home first.
- **A/B (train), `20261103-183912-ab`:** 480 games, the full gauntlet, 20 maps, both colours.

  Δ points/game (new − old) by opponent:

  | all | blitz | tracking | search | reflex | dario | turtle |
  |---|---|---|---|---|---|---|
  | **−0.11 ± 0.04** | −0.53 ± 0.19 | −0.10 | −0.07 | +0.05 | 0.00 | 0.00 |

  The new version is significantly worse. The holdout run was skipped.
- **Target metric didn't move:**
  - "Big-haul bite while flex carrying": 275 → 273.
  - Unopposed food per game: 8.18 → 8.46.
  - Invader food banked per game: 8.95 → 9.65.
- **Why it failed:** at those moments Flex is on average about 24 steps away, deep in enemy territory. Turning back gets it home too late to stop the bite, and it costs offence. Against blitz (two attackers that always carry hauls) Flex was recalled constantly: banked 14.1 → 12.6, conceded 12.5 → 15.5, points 1.55 → 1.02.
- **Lesson:** defence has to come from an agent that is already **near home**, not from recalling one from deep in enemy territory. That pushes toward F2/F3: keep one agent's attack shallow or close to the border, or react earlier with whoever is closest. "Flex carrying" in `diagnose.py` also counts bites while Flex is walking home, so read that number together with Flex's distance.
