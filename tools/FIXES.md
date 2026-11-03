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
(none)

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

### F5: Attack standoffs
- **Evidence:** 52 idle attacking turns per game, and "stalled" is the cause in 13 losses and ties.
- **Cause (suspected):** `reposition()` re-picks its crossing every turn, so the attacker goes back and forth against a guard that mirrors it.
- **Idea:** commit to a crossing for several turns; after K stuck turns, try a capsule, switch sides, or have Flex defend instead.
- **Target metric:** `idle_attack` per game and stalled losses and ties.

## Fixed
(none yet)

## Rejected

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
