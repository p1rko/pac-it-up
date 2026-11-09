# Team "Pack It Up": how the agent works and why

The submitted agent is `my_team.py` (a single self-contained file, as the contest requires).
`create_team` builds a **RaiderAgent** and a **FlexAgent**. Both are subclasses of a shared
`SmartAgent`, which holds all the machinery.

---

## 1. The idea in one paragraph

I measured the early versions in hundreds of games and found that in Capture the Flag
between decent agents, **catching an invader is rare** (about 0.3 catches per game). Games are
decided by **how fast each team banks food**. A full-time defender spends most of the game
standing on the border, which wastes half the team. So both of our agents attack by default.
Pure double-offence, however, loses to simple greedy attackers like `baseline_team`, which then
walk in and eat everything. The fix is a **flex** second agent. It attacks, but it turns around to
defend when an invader comes near it or is carrying a dangerous amount of food. It also stops
chasing if chasing has not been catching anyone.

---

## 2. Shared machinery (`SmartAgent`)

### 2.1 Map analysis (done once, in `register_initial_state`)
* **Maze distances** are precomputed by the framework (`get_maze_distance`).
* **Border cells:** our side of the middle line, used as "home" targets and for patrol points.
* **Dead ends (`_compute_dead_ends`):** the map is repeatedly pruned of cells with one
  open neighbour. Every pruned cell is inside a *pocket* with a single exit. For each pocket cell
  we store its **depth** and its **entrance**. This is the most important safety feature: a
  Pacman deep in a pocket with a ghost near the entrance is dead, so we avoid that food when a
  ghost is around.
* **Trap rooms (`_compute_trap_rooms`, v6):** for every enemy-side cell a guard could stand on,
  block it and its neighbours and collect the enemy-side cells that can no longer reach our
  border. Areas of at most `ROOM_MAX` (40) cells are rooms one guard can seal; each keeps its
  sealing cells. Rooms nest (a map has 50–90 of them, 1–40 cells). Takes 5–30 ms.

### 2.2 Belief tracking: where are the enemies we can't see?
Enemies are only visible within 5 squares. Otherwise we only get a noisy distance. The team keeps
an **exact probability distribution over cells for each enemy** (`update_beliefs`), shared by both
agents through `TEAM_INFO`:
1. **Predict:** the enemy that just moved spreads its probability to neighbouring cells.
2. **Observe:** each cell is weighted by how likely the noisy sonar reading is from there.
3. **Constrain:** cells are removed if they contradict what we know. An invader must be on our
   side and a ghost on theirs, and an enemy cannot be within our sight radius if we don't see it.
4. **Food clue:** if a dot disappears from our side, an unseen invader is standing exactly there.
5. **Respawn recovery:** if the distribution collapses to nothing (usually the enemy was eaten),
   it restarts from the enemy's spawn point.

The most likely cell is used for patrol points, choosing food far from the guards, and hunting
invisible invaders.

### 2.3 Path planning
`plan()` is a Dijkstra search with:
* an extra **cost** for cells near dangerous ghosts, and for pocket cells when a ghost is near;
* **blocked** cells: ghosts and the squares next to them are never entered.

### 2.4 Close-range fights: alpha-beta search
When a visible enemy is within 6 steps (a ghost that can eat our Pacman, or an invader near
our ghost), the planned move is checked by **iterative-deepening alpha-beta** over the real
game rules. It includes us **and every nearby enemy**, so two ghosts trapping us are both
modelled. The evaluation rewards surviving, keeping the food we carry, getting home and eating
capsules. It punishes standing in pockets near ghosts. For a defender (since v2) it scores a
**race**: what the invader can reach before any of our home ghosts (the searcher, plus a teammate
held where it stands). It is penalised for an exit over the border it reaches first, its lead to
its best exit, our food and capsules it reaches first, and our being scared. This makes our
ghosts get in front of an invader instead of trailing it, since an equal-speed Pacman can't be
caught from behind. Search is **time-boxed** to 0.3 s per move.

### 2.5 Safety against forfeits
The rules forfeit a game after 3 slow moves or any exception. So:
* `choose_action` wraps everything in `try/except`. If anything goes wrong, a random legal move
  is played instead of crashing.
* A per-turn budget (0.75 s) caps search time. Measured worst case in testing: **0.30 s/move**.
* Setting the environment variable `PACKITUP_DEBUG=1` turns the safety net off so bugs show
  up during development.

---

## 3. Attacking (`attack`)

Priority list, top to bottom:
1. **Bank it** if time is nearly out (moves left ≤ distance home + 3), or if the food we carry
   wins the game.
2. **Eat a scared ghost we can surely catch** (v3): it's right next to us (stepping onto it eats
   it), or it's trapped in a pocket and we are closer to the pocket's mouth (at most 8 steps,
   within its timer). It costs the enemy a long walk back. Before v3 we chased any scared ghost
   within 2 steps. A ghost circling a 2×2 block can't be caught that way, and our attacker
   shuffled next to it, often carrying food, until the timer ran out (7.8 wasted moves per
   scared window).
3. **Being chased:** run for a capsule if we get there before the ghost. Otherwise run home if
   carrying food.
4. **Carry limit:** go home after 7 dots (5 if home is far). The limit is raised while the
   guards are scared, and is unlimited if they stay scared long enough for us to get home.
   **Once we decide to bank, we stick to it** (`self.banking`) until we are home or carry
   nothing. Before v1 the limit changed as we moved (7 → 5 beyond 15 steps from home), so an
   attacker carrying 5–6 flipped between eating and going home on every move. Only steps 1–3
   can interrupt the walk home. The commitment is dropped when the guards are scared long enough
   for the unlimited mode.
   **Bank before the guards recover** (v3, the user's idea): while the guards are scared and we
   carry food, we go home once their timer is ≤ our distance home + 3 (`SCARED_BANK_MARGIN`).
   Until then we only target food we can reach *and* bring home before the timer ends. Food
   banked inside a scared window went from 1.6 to 5.6 per window.
5. **Pick a target dot** from the *safe* food: no ghost is closer to it than we are, and no ghost
   can cut us off at the pocket exit. Prefer dots that are close to us, far from where the guards
   probably are, and (when carrying) not far from home. Avoid the teammate's target so the two
   attackers spread out and overload a single defender.
6. **Blocked by a guard:** slide along our border to the crossing furthest from every ghost
   (seen or believed) and try again there.
7. **Tied late: break the deadlock** (v4). With the score tied and at most 150 own moves left
   (`DEADLOCK_MOVES`), a single banked dot turns a tie (1 point) into a win (3), and dying only
   costs time (the dead Pacman's food is dropped back on the map, not given to the enemy). So:
   bank after one dot; count unseen guards at their believed cells (otherwise stepping across the
   border and seeing the guard flips the plan every move); and when no food is safe, take the
   cheapest route to food (never next to a ghost) instead of sliding along the border.
   Since v5, believed guards only add cost (a wrong belief used to seal every corridor); only
   seen guards block. The Raider walks right up to the guards (only their own cells blocked) and
   skips the fight search while doing so, to bait them; Flex stays home (see Roles).
8. **Capsule push** (v7, the user's idea; checked first in each agent's turn). For every enemy
   capsule we estimate how many dots two agents could eat *and bank* inside its scared window
   (`SWEEP_BUDGET` 38 of the 40 moves; one agent from the capsule, one from the nearest
   crossing). If that sweep alone would leave ≤ 2 dots (the food-limit win), or late in the game
   (≤ `PUSH_MOVES` 120 own moves left) while we aren't ahead (`PUSH_LEAD` 0) and the sweep would
   put us in front, both agents go for the nearest capsule; once it is eaten the scared-window
   attack (step 4) sweeps and banks. Capsules are never saved: escapes still eat them.

---

## 4. Defending (`defend`)

* **Visible or believed invader:** go to an **intercept point**. If the invader is in a pocket
  and we can reach the pocket's mouth first, close the mouth (trap). If we can reach its escape
  crossing first, wait on its path. Otherwise chase directly. The last few steps are handled by
  alpha-beta.
* **Scared** (they ate a capsule): shadow the invader at distance 2 so we can pounce the moment
  the timer ends, without being eaten.
* **No invaders:** stand on the border cell that best balances "close to the food we defend"
  and "close to where the next attacker probably is".
* Defenders **never cross the border** while defending.

---

## 5. Roles

### RaiderAgent (agent 1)
* Attacks by default, and eats any invader within 4 steps while passing through home.
* If **two** invaders are in our half and one is near, it helps defend (one defender can't stop two).
* **Late game with a lead:** stops attacking and defends the lead.

### FlexAgent (agent 2)
Same as the Raider, plus it defends when:
* an invader is within 8 steps of it on our side **and defending has been paying off**, or
* any invader carries **4+ dots** (always worth stopping).

In a tied late game (v4) it ignores an invader that carries nothing: it can't score, and
guarding it was what kept both teams frozen at 0–0. Since v5, in a tied late game it doesn't
attack at all while carrying nothing: it guards home so the Raider's push can't hand the
opponent the winning dot.

Since v6 it also avoids the "one guard holds both of us" trap (found on RANDOM1890298, where
v5 lost 5 games by −28: both Pacmen sat in one room for ~700 turns while the enemy raider ate
freely):
* **Don't follow the Raider in:** Flex skips food in a trap room it shares with the Raider's
  position or target, but only while an enemy guard could reach that room's door within
  `SEAL_SLACK` (10) moves of the Raider. Always-on avoidance (F20d) steered Flex too often.
* **Give up a pinned haul:** an agent is *trapped* after `TRAP_TURNS` (20) moves trying to go
  home with food while covering at most `TRAP_CELLS` (3) cells. A trapped Flex walks into the
  guard (when an enemy is attacking or we aren't ahead): its food goes back on the map, which it
  was never going to bank anyway, and it respawns home where it can defend again.

"Paying off" is measured live. It gets 40 free defend turns, then 40 more per invader it
actually catches. Against greedy attackers (like the baseline) it catches several per game and
keeps defending. Against evasive attackers it stops wasting time and goes back to scoring.

(`WardenAgent`, a classic full-time defender that raids, is still in the file for comparison but
is not used. It tested worse.)

---

## 6. How I tested it

Scripts (not part of the submission) ran full games headless and in parallel on random maps
(`-l RANDOM<seed>`), with each team playing **both colours** on every map. They counted wins,
average score, and per-agent deaths, food lost and food returned.

Sparring opponents:
* `baseline_team`: the staff example (greedy attacker + reflex defender).
* `strategies/reflex.py`, `tracking.py`, `search.py`: earlier drafts (attacker + defender).
* **turtle**: two defenders. **blitz**: two attackers (both built from `search.py`).

### Results that shaped the design (12 games each, from our side)

| Version | vs baseline | vs tracking | vs blitz (2 attackers) |
|---|---|---|---|
| search.py (attacker + defender) | 10-0 (+19.8) | 8-9 | 3-16 |
| v4: Raider + full-time Warden | win all | 3-9 | 5-10 |
| v5: two Raiders (no defence) | **4-8** | 10-2 | 7-4 |
| v5: Raider + Flex (fixed) | **12-0 (+23.1)** | 9-2 | 5-6 |
| **final: Raider + adaptive Flex** | **12-0 (+23.1)** | 8-4 (+2.8) | 6-2-4 (-1.3) |

Lessons:
1. A dedicated defender loses throughput races (v4 vs tracking).
2. No defender loses to greedy attackers (v5 double vs baseline).
3. Flex defence gets most of both. The adaptive rule turned the blitz matchup from 5-6 into 6-2-4. With 12 games per row, differences of 1-2 wins are within noise.

Timing: worst observed move 0.30 s (limit 1 s), and no crashes in debug mode.

### Optimisation cycles (`tools/`, 480-game paired A/B runs against the previous version)
Since then, versions are compared with `tools/tournament.py ab` against the gauntlet of dario,
tracking, search, reflex, blitz and turtle: 20 maps, both colours, paired seeds. A version must
pass on train maps and on unseen holdout maps. Full logs are in `tools/PROGRESS.md` and
`tools/FIXES.md`.

| Version | Change | Train Δ pts/game | Holdout Δ pts/game |
|---|---|---|---|
| v0 | baseline of this log (2.14 pts/game, 1st of 8 in the Cycle 0 round-robin) | — | — |
| **v1** | commit to banking (no eat ↔ go-home flip at the carry-limit cliff) | −0.00 ± 0.05 | **+0.24 ± 0.06** (W-T-L 150-29-61 → 169-30-41, better against every opponent) |
| **v2** | F11: defender fight evaluation races the invader to exits, food and capsules | +0.09 ± 0.08 | +0.06 ± 0.06, unseen holdout +0.07 ± 0.06; pooled points z 1.86, **margin +0.78 (z 3.4), food conceded −1.11 (z −5.0)**; accepted by the user on margin |
| **v3** | F16: scared-window discipline (sure-catch prey only; bank before the guards recover) | **+0.12 ± 0.05** | **+0.10 ± 0.05** (both pass the gate; pooled +0.11 ± 0.035, z 3.1; holdout margin +1.34, banked +0.94) |
| **v4** | F19: deadlock breaker (tied with ≤ 150 moves left: bank after one dot, count unseen guards, bold route, Flex ignores empty-handed invaders) | +0.10 ± 0.05 | +0.03 ± 0.03, unseen holdout +0.04 ± 0.03; **pooled +0.053 ± 0.021 (z 2.51)** over 720 pairs; ties 49 → 30 on train; accepted by the user |
| **v5** | F19c: Raider-only deadlock push (believed guards cost but don't block, Raider baits the guards, Flex guards home) | +0.05 ± 0.05 | +0.05 ± 0.04, unseen holdout +0.03 ± 0.03; **pooled +0.040 ± 0.023 (z 1.77)**, positive on all three pools; reflex +0.16 (z 2.3); W-T-L 517-81-122 → 532-65-123; conceded unchanged; accepted by the user |
| **v6** | F20e: trap rooms (Flex doesn't follow the Raider into a room a guard could close; a trapped Flex gives up its haul) | +0.03 ± 0.03 | +0.00 ± 0.03, unseen holdout −0.01 ± 0.02; pooled +0.007 ± 0.016 (below what 720 pairs can show); fixes the targeted trap (RANDOM1890298: three −28 losses → wins); margin up and conceded down against all six opponents, tracking +0.07; accepted by the user |
| **v7** | F22: capsule push (go for an enemy capsule when one scared window's sweep would win the game) | +0.03 ± 0.04 | +0.08 ± 0.05, unseen holdout +0.23 ± 0.06; **pooled +0.115 ± 0.031 (z 3.8)**; W-T-L 534-64-122 → 566-51-103; banked +0.78, conceded +0.27; better against five opponents, blitz neutral; accepted by the user |

v1 also stalls less (71 → 51 idle attacking turns per game) and banks more (+1.3 food per game
on holdout). The holdout maps are all random mazes, where long trips home past the 15-step
cliff are common, which is likely why the gain shows there and not on the train mix of fixed
layouts.

Lessons from the rejected attempts (code kept in `strategies/experiments/`):
- Recalling an attacker to defend, or attacking shallower, costs more food than it saves.
- A stalled attacker at the border also guards it. Removing stalls without keeping someone near
  home trades food evenly.

---

## 7. Running it

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team             # watch a game
python capture.py -r ../../../my_team.py -b baseline_team -Q -l RANDOM42   # fast, random map
```

## 8. Tunable knobs (top of `SmartAgent` / `FlexAgent`)
`CARRY_LIMIT`, `DANGER_RADIUS`, `SAFETY_MARGIN`, `SEARCH_TIME`, `FIGHT_RANGE`,
`DEFEND_RADIUS`, `DANGER_HAUL`, `FREE_DEFENCE`, `TURNS_PER_CATCH`, `SCARED_BANK_MARGIN`,
`PREY_TRAP_RANGE`, `DEADLOCK_MOVES`, `TRAP_TURNS`, `TRAP_CELLS`, `ROOM_MAX`, `SEAL_SLACK`, `PUSH_MOVES`, `PUSH_LEAD`,
`SWEEP_BUDGET`.
If the tournament machine turns out slower, lower `SEARCH_TIME` first.
