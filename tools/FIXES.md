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

#### F5a: commit to banking: neutral on points, target hit, kept as the base for F5b
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

## Parked (neutral, worth combining later)

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

### F3: Flex home but slow to reach invaders
- **Evidence:** in 219 big-haul bites Flex was already home but about 15 steps away. In 94% of all unopposed bites the invader was unseen, so Flex chases a belief.
- **Ideas:** better intercept target for unseen invaders (the belief mass near our food rather than the single most-likely cell), or patrol closer to the food.

### F4: Same path out of long spawn corridors
- **Evidence:** RANDOM398056 was lost 3 of 4 times (−29, −13, −13). Both agents walk out together, never cross the border, and the opponent raids freely.
- **Idea:** give each agent its own crossing (upper and lower half of the border), and keep Flex home when the trip to the border is long.

## Fixed
(none yet)

## Rejected

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
