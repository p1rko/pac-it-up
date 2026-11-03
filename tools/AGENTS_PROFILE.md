# Agent profiles (Cycle 0)

Source: round-robin `20261103-180445-rr`. 8 agents, 28 pairs, 10 maps per pair with both colours (560 games). The map pool is train (fixed layouts plus RANDOM seeds). Full report: `tools/reports/20261103-180445-rr.md`.

Points: W=3, T=1, L=0. "Unopposed" means invader food eaten with none of the defending team's ghosts within 6 steps. "Idle" means turns spent as Pacman covering ≤2 distinct cells over the last 10 moves (a standoff or a stuck attacker).

| agent | pts/game | W-T-L | banked | deaths | food lost | invader food banked vs it | unopposed | idle (attack) |
|---|---|---|---|---|---|---|---|---|
| **my_team** (Raider + Flex) | **2.14** | 95-15-30 | **17.8** | 0.4 | 1.7 | 9.3 | 11.4 | 52 |
| tracking | 1.76 | 79-10-51 | 14.3 | 0.3 | 0.7 | 10.1 | 5.8 | 69 |
| search | 1.71 | 75-14-51 | 11.9 | 0.3 | 1.2 | 9.0 | 6.3 | 53 |
| dario | 1.66 | 75-8-57 | 14.2 | 1.0 | 2.7 | 11.7 | 9.8 | 13 |
| reflex | 1.64 | 67-28-45 | 12.0 | 0.1 | 0.5 | 9.0 | 5.6 | 52 |
| blitz | 1.55 | 65-22-53 | 13.6 | 0.4 | 1.7 | 11.0 | 11.7 | 84 |
| turtle | 0.95 | 39-16-85 | 6.2 | 0.2 | 0.3 | 10.3 | 7.3 | 10 |
| baseline_team | 0.18 | 8-1-131 | 1.5 | 4.3 | 17.4 | 21.1 | 16.7 | 0 |

No agent had a move-time warning or a crash. Our worst move was 0.31 s (search 0.41 s, blitz 0.55 s).

## my_team (Raider + adaptive Flex): the agent we optimise
- **Strengths:**
  - Best throughput by far (17.8 banked per game).
  - Most food taken back from invaders (5.3 per game).
  - Rarely dies.
  - Positive result against every opponent (≥1.55 pts/game).
  - Beats Dario 2.20 to 0.70.
- **Weaknesses:**
  - **Defence gaps.** "invader-unopposed" is the main cause in 26 of our 45 losses and ties. 11.4 of our food per game is eaten with nobody near it, the worst of any agent above baseline. The other good agents concede about 6.
  - **Standoffs.** 52 idle attacking turns per game, and "stalled" is the cause in 13 losses and ties.
  - **Weakest matchups:** blitz (1.55) and reflex (1.60). Against blitz (two attackers) we bank only 9.3 and idle 85 turns per game.
  - **Map pathology:** we lost RANDOM398056 in 3 of 4 games (−29, −13, −13). Both spawns sit at the end of a 30-move snake corridor. Both our agents walk out together on the same path and never cross the border, while the opponent's raider banks freely. Traced with `PACKITUP_DEBUG=1`: no exception, it's a decision problem.

## Dario (`strategies/dario.py`, 2024 contest winner, frozen)
- **Attacker:**
  - Monte-Carlo rollouts: 24 random forward walks of 20 steps for each move, scored by a linear evaluation.
  - On respawn it picks a random entry point.
  - It plans a greedy food path after eating a capsule.
  - It doesn't model ghost movement in the rollouts.
- **Defender:** never leaves home. It patrols points near the border weighted by nearby food and capsules, and chases only *visible* invaders. It has no belief tracking.
- **Strengths:**
  - Never stalls (13 idle turns per game, the lowest of the serious agents).
  - Steady throughput (14.2 banked).
  - Beats blitz (2.20).
- **Weaknesses:**
  - Dies the most of the serious agents (1.0 per game, 2.7 food lost, half of those deaths in dead-end pockets).
  - Concedes the most banked food (11.7).
  - Its main loss cause is invader-unopposed (48 of 65): the patrol can't find invaders it can't see.

## tracking (Strategy B)
- **Strengths:** belief tracking for both defence and food choice; very safe (0.3 deaths, 0.7 food lost); best defence of the field (5.8 unopposed).
- **Weaknesses:** stalls a lot (69 idle; 22 stalled losses and ties); concedes capsule food (4.5 per game).

## search (Strategy C = B + alpha-beta in fights)
- **Strengths:** good defence (6.3 unopposed); beats reflex.
- **Weaknesses:** lower throughput (11.9); carries food into the time limit most often (1.1 per game); concedes capsule food (4.4).

## reflex (Strategy A)
- **Strengths:**
  - Safest agent (0.1 deaths per game).
  - Good defence (5.6 unopposed).
  - Holds us to 1.30 pts/game, our second-hardest opponent.
- **Weaknesses:**
  - Very passive: the most ties (28) and 52 idle turns.
  - Low throughput (12.0).

## blitz (two Strategy C attackers)
- **Strengths:**
  - Our hardest opponent: it takes 1.10 pts/game from us.
  - Overloads single-defender teams.
- **Weaknesses:**
  - No defence: 11.7 unopposed.
  - The worst stalling of the field (84 idle).
  - Loses to Dario (0.70).

## turtle (two Strategy C defenders that raid)
- **Strengths:** hard to score against; still beats us on some maps by raiding (RANDOM398056).
- **Weaknesses:** banks almost nothing (6.2 per game).

## baseline_team (staff example)
Only a sanity floor: it dies 4.3 times per game. We beat it in 20 of 20 games.

## Gauntlet chosen for the cycles
dario, tracking, search, reflex, blitz, turtle, plus every accepted past version from `strategies/history/` (starting with v0 = the current `my_team.py`). `baseline_team` is dropped from the gauntlet (3.00 pts/game against it) and kept only as a quick sanity check in the acceptance gate.
