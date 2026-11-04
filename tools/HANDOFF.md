# Handoff: where the optimisation stands and what to do next

Last updated 2026-11-04. Read this first when resuming. Details are in `tools/FIXES.md` (one entry per weakness and attempt) and `tools/PROGRESS.md` (one entry per cycle).

## State in one glance
- **Champion: v1** = `my_team@b41127c`, frozen as `strategies/history/v1.py`. It equals `my_team.py` on `optimize-loop`.
  - v1 = v0 + **F5a commit to banking**: once the carry limit sends an agent home, it keeps going home.
  - Holdout A/B against v0: **+0.24 ± 0.06** pts/game, better against every opponent.
- **Branches:**
  - `main`: old; does not have v1 yet. The tournament probably reads `main`, so merge before submitting.
  - `optimize-loop`: pushed, at `302a12f` (v1 accepted). The base for new work.
  - `f9-home-hunt`: local, not pushed, at `3844ea5` + this file. Holds the F9 record, `tools/raid_probe.py` and `diagnose.py leads`. `my_team.py` there is still v1. Merge it into `optimize-loop` with the next accepted version, or now if the tools are wanted there.
  - `f5-stalls`: local; already merged into `optimize-loop`.
  - `f6-harvest`: local; the user's scared-window idea (F6).
- **Not ours to commit:** the user's edits to `CLAUDE.md` and `tools/AGENTS_PROFILE.md`, and the dirty `pacman-contest` submodule pointer.

## Working rules (from the user)
- Edits go through Edit/Write so the user approves them. Propose a plan for bigger changes and wait for confirmation.
- Optimise only `my_team.py`; opponents stay frozen. Don't optimise Dario's agent.
- **Commit** every attempt (on a branch per strategy). **Push only after a version passes testing.**
- **Keep failed attempts:** save the variant to `strategies/experiments/<id>.py`, record why it failed and how to revive it.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## How we test (copy-paste)
```bash
# Train and holdout A/B against the champion: 480 games each, about 15 min each. Always run both.
# Train alone has hidden real gains: v1 was ±0.00 on train and +0.24 on holdout.
PACKITUP_DEBUG=1 venv/bin/python tools/tournament.py ab my_team.py v1=strategies/history/v1.py --vs strategies/dario.py strategies/tracking.py strategies/search.py strategies/reflex.py strategies/blitz.py strategies/turtle.py --maps 20 --purpose "..."
#   ...same with --pool holdout
# zsh: list the opponents literally; a $VAR holding them is passed as one argument.

venv/bin/python tools/query.py report latest
venv/bin/python tools/diagnose.py leads <run> --agent my_team v1        # second-half leads lost, decisive raid
venv/bin/python tools/diagnose.py unopposed <run> --agent my_team v1    # where our agents are during free bites
PACKITUP_DEBUG=1 venv/bin/python tools/raid_probe.py [agent.py] --maps 3   # what our agents do during enemy raids
PACKITUP_DEBUG=1 venv/bin/python tools/stall_probe.py [agent.py] --maps 4  # which code path stalls; enemy attack shares
venv/bin/python tools/watch.py events <game_id>                          # one game's timeline (and play/queue/moments)
```

**Acceptance:**
- the gate: Δ > 2·SE, no crashes or warnings, and Dario no worse than −1 SE;
- **or** the league rule: mean Δ ≥ 0, one opponent better by > 2 SE, and none worse than −2 SE.

The league rule exists because the tournament is a round-robin ranked by total points (W = 3, T = 1, L = 0), with score margin as the tie-break.

**On accept:**
1. Snapshot `strategies/history/vN.py`.
2. Update `AGENT_EXPLAINED.md`, `FIXES.md` and `PROGRESS.md`.
3. Merge into `optimize-loop` and push.

## What we learned so far
1. **Attack throughput wins in this field.** Recalling an attacker to defend (F1), or attacking shallower (F2), lost points.
2. **A stalled attacker at the border also guards it.** Removing stalls (F5b–F5e) traded food evenly; none of those variants was significant.
3. **Locating unseen invaders works.** The belief error is a median 2 cells. The problem is that nobody is home to respond.
4. **Where v1 drops points** (480 games: 307 W, 79 T, 94 L):

   | group | games | points lost (compared with a win) | what happens |
   |---|---|---|---|
   | outplayed from early on | 54 L | 162 | we bank 5.8 and they bank 15.1; we can't get in and they walk in |
   | 0–0 deadlocks | 79 T (56 of them 0–0) | 158 | neither team crosses; concentrated on a few maps (RANDOM519502, RANDOM797927, …). **Deferred by the user.** |
   | lead lost late | 40 L | 120 | one enemy raid of about 64 rounds banks 8.7 food (max 45) while both our agents are away carrying |

## All attempts so far
| id | idea | result | code |
|---|---|---|---|
| F1 | Flex turns back for big hauls even while carrying | −0.11, rejected | not kept (user's choice) |
| F6 | harvest the scared window, don't eat scared ghosts (user's idea) | −0.02, parked | `experiments/f6_harvest.py`, branch `f6-harvest` |
| F2+F7 | shallow Flex + capsules when guarded | −0.18, rejected | `experiments/f2_f7_shallow_capsules.py` |
| **F5a** | **commit to banking** | **train ±0.00, holdout +0.24, accepted as v1** | `history/v1.py` |
| F5b | commit to a new crossing after a standoff | −0.13 (turtle −0.75) | `experiments/f5b_crossing_commit.py` |
| F5c | score-aware: press when behind, Flex guards when ahead | ±0.00 (blitz +0.68, search −0.68) | `experiments/f5c_score_aware.py` |
| F5d | press only | −0.03 | `experiments/f5d_press_only.py` |
| F5e | Flex guard only against two-attacker teams | +0.03 | `experiments/f5e_adaptive_guard.py` |
| F9 | home hunt: an agent at home hunts invaders carrying 2+ | train −0.01, holdout +0.00; kills +40%, leads lost unchanged | `experiments/f9_home_hunt.py` |

## Next possible steps (recommended order)
1. **F10: protect the lead (recommended next; awaiting the user's go-ahead).**
   - **Trigger:** we're ahead in the second half by enough that one big haul could flip it.
   - **Flex** then stops attacking and guards our half full-time, Warden-style (`defend()`), after finishing its current trip home. It is never recalled from deep in enemy territory.
   - **The Raider** keeps attacking.
   - **Revert:** Flex goes back to attacking if the lead shrinks or we fall behind.
   - Optionally keep F9's home hunt on top (kills +40%, almost no cost).
   - **Targets:** `diagnose.py leads` count down (holdout 13–16 per 240 games, train 25); no new losses in games we weren't leading.
   - **Why it differs from F1/F2:** it gives up only Flex's attack, only when we're ahead late, which is when extra food matters least. It's the user's "it's okay to stall/defend when winning" principle.
2. **F9 tuning:** `HUNT_CARRY` 1 and `HUNT_RADIUS` 15, alone or combined with F10.
3. **0–0 deadlocks (deferred by the user):** in a 0–0 game after the halfway point, force one food through (both agents on one crossing, or a capsule). One food turns 1 point into 3. 56 games per 480 are affected.
4. **Outplayed-early losses:** find out why `defend()` concedes more against search than a Flex stalled at the border (seen in F5c). Watch clips with `watch.py`.
5. **Older leads:**
   - F4: both agents leave a long spawn corridor by the same path.
   - F8: both scared ghosts get eaten together.
   - F6 revive: harvest plus more capsules, and still eat scared ghosts far from their spawn.
6. **Before submission:** merge v1 (or later) into `main`, then check timing on a slower machine; lower `SEARCH_TIME` first if needed.
