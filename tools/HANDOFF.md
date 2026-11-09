# Handoff: where the optimisation stands and what to do next

Last updated 2026-11-07. Read this first when resuming. Details are in `tools/FIXES.md` (one entry per weakness and attempt) and `tools/PROGRESS.md` (one entry per cycle).

## State in one glance
- **Resume here (2026-11-09, latest):** champion is **v6** = v5 + F20e, guarded trap rooms (`strategies/history/v6.py`, on `optimize-loop`, `main` and the team repo). Pooled +0.007 ± 0.016 against v5 over three pools (below detection: the trap is ~1–2% of games), but it fixes the targeted failure (RANDOM1890298: v5 lost 5 games by −28 with both Pacmen held in one room by one guard; three became wins), and margin is up / conceded down against all six opponents; accepted by the user. F20a/F20b/F20d are parked steps towards it (`strategies/experiments/f20*.py`). A/B new work against `v6=strategies/history/v6.py`. **Lesson:** single-game flips between versions are mostly chaotic divergence (time-boxed search); check the first differing move in the replays before blaming a rule.
- **Previous (2026-11-08):** champion was **v5** = v4 + F19c, the Raider-only deadlock push (`strategies/history/v5.py`, on `optimize-loop`, `main` and the team repo). Pooled +0.040 ± 0.023 (z 1.77) against v4, positive on all three pools; accepted by the user. Before: champion was **v4** = v3 + F19, the deadlock breaker (`strategies/history/v4.py`, on `optimize-loop` and `main`). Pooled +0.053 ± 0.021 (z 2.51) over three pools against v3; accepted by the user. F17a–d (dead ends) and F18/F18b (calm opening) are closed. Earlier: champion was **v3** = F16, scared-window discipline (`strategies/history/v3.py`, on `optimize-loop`). It passed the gate on both train (+0.12) and holdout (+0.10) against v2. F15 and F15b (capsule cover) were parked at ±0.00. F17a (the user's dead-end idea: trap rooms) was parked at −0.01: deaths −17%, but banked −0.30. Its record is on the local branch `f17-trap-rooms`. Every experiment's code is in `strategies/experiments/`; per-attempt branches are local only.
- **Champion: v6** = v5 + F20e, `strategies/history/v6.py`, on `optimize-loop`. Before that: **v5** = v4 + F19c, `strategies/history/v5.py`. Before that: **v4** = v3 + F19, `strategies/history/v4.py`. Before that: **v3** = v2 + F16, `strategies/history/v3.py`. Before that: **v2** = F11, `strategies/history/v2.py`. Before that: **v1** = `my_team@b41127c`, frozen as `strategies/history/v1.py`. It equals `my_team.py` on `optimize-loop`.
  - v1 = v0 + **F5a commit to banking**: once the carry limit sends an agent home, it keeps going home.
  - Holdout A/B against v0: **+0.24 ± 0.06** pts/game, better against every opponent.
- **Branches:**
  - `main`: **v6** (2026-11-09); previously v5, v4, v3, fast-forwarded to `optimize-loop` and pushed. The tournament probably reads `main`; fast-forward it again after each accepted version.
  - `optimize-loop`: at v6 (2026-11-09). **The base for new work; A/B against `strategies/history/v6.py`** (use `v6=strategies/history/v6.py` as the old agent in the commands below; older commands may still say v4/v5).
  - `f20-trapped-haul` (F20a), `f20b-no-follow` (F20b), `f20d-trap-rooms` (F20d), `f20e-guarded-rooms` (F20e = v6, merged): local only.
  - `f16-scared-window`: F16 = v3, merged into `optimize-loop`.
  - `f15-capsule-cover`, `f15b-flex-cover`: local, F15/F15b records (parked); records also merged into `optimize-loop`.
  - `f9-home-hunt`: local, not pushed, at `3844ea5` + this file. Holds the F9 record, `tools/raid_probe.py` and `diagnose.py leads`. `my_team.py` there is still v1. Merge it into `optimize-loop` with the next accepted version, or now if the tools are wanted there.
  - `f10-protect-lead`: local, not pushed, branched from `f9-home-hunt`. Holds the F10 record (rejected).
  - `f11-defend-catch`: local, not pushed, branched from `f10-protect-lead`. Holds the F11 record (parked at z = 1.86) and `tools/chase_probe.py`.
  - `f11b-race-when-carrying`: local, not pushed, branched from `f11-defend-catch`. Holds the F11b record (z = 1.47).
  - `v2-f11`: local, not pushed. `my_team.py` = **v2 = F11**, frozen as `strategies/history/v2.py` (the user accepted it on margin, 2026-11-06). Same code as `optimize-loop`.
  - `f14-capsule-guard`: local, branched from `optimize-loop`. Holds F14 (parked).
  - `f12-v2-home-hunt`: local, branched from `v2-f11`. Holds the F12 record (rejected). Newest branch for records.
  - `f5-stalls`: local; already merged into `optimize-loop`.
  - `f6-harvest`: local; the user's scared-window idea (F6).
- **Not ours to commit:** the user's edits to `CLAUDE.md` and `tools/AGENTS_PROFILE.md`, `tools/manual_analysis.md`, and the dirty `pacman-contest` submodule pointer.

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
venv/bin/python tools/chase_probe.py <run> --agent my_team v1 [--late] [--examples 5]  # how chases end (caught/crossed/outran/capsule)
venv/bin/python tools/role_probe.py <run> [<run> ...]               # per-role banked / pacman / fight / idle turns
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
| F10 | protect the lead: Flex guards full-time when ahead with < 150 moves left | train −0.13, holdout −0.09; leads lost **up** (26→32, 13→20) | `experiments/f10_protect_lead.py` |
| F11 | defender fight eval races the invader to exits/food/capsules (both home ghosts) | train +0.09, holdout +0.06, unseen +0.07; pooled **+0.072 ± 0.039 (z 1.86)**, parked; conceded −0.6 to −1.6, banked −0.6 | `experiments/f11_race_eval.py` |
| F11b | F11, race only invaders carrying ≥ 1 | train +0.07, holdout +0.04, unseen +0.04; pooled +0.051 ± 0.035 (z 1.47); banking cost unchanged | `experiments/f11b_race_when_carrying.py` |
| **v2** | **= F11, accepted by the user on margin** | | `history/v2.py` |
| **F16 = v3** | **scared-window discipline: sure-catch prey only; bank before the guards recover (user's idea)** | **train +0.12, holdout +0.10, both pass; pooled +0.11 ± 0.035 (z 3.1); oscillation 7.8 → 1.7/window, banked in window 1.6 → 5.6** | `history/v3.py` |
| F17a | trap rooms (one-door areas with loops) count as dead ends (user's idea) | train +0.03, holdout −0.05; pooled −0.01 ± 0.02, parked; deaths −17%, food lost −0.19, banked −0.30 | `experiments/f17a_trap_rooms.py`, branch `f17-trap-rooms` |
| F17c | F17a for a Pacman only when carrying ≥ 3 (defenders always) | train +0.01, holdout −0.03; pooled −0.01 ± 0.02, parked; trap-room deaths only 30 → 26 | `experiments/f17c_careful_carry.py`, branch `f17c-careful-carry` |
| F17d | watch the door: leave a dead end when a seen or believed guard can reach its door first | train −0.02, holdout +0.01; pooled −0.00 ± 0.03, parked; deaths −20%, food lost −31%, banked unchanged. A dead Pacman's food is dropped back on the map, so deaths only cost time; dead-end line closed | `experiments/f17d_watch_door.py`, branch `f17d-watch-door` |
| **F20e = v6** | trap rooms precomputed; Flex skips food in the Raider's room while a guard could reach its door within 10 moves of the Raider; a Flex trapped 20 moves going home walks into the guard (F20a) | vs v5: train +0.03 ± 0.03, holdout +0.00 ± 0.03, unseen −0.01 ± 0.02; pooled +0.007 ± 0.016; tracking +0.07, reflex −0.04 (2 of 3 losses traced to search timing); margin up and conceded down vs all six. **Accepted as v6** | `history/v6.py`, branch `f20e-guarded-rooms` |
| F20d | F20a + Flex always skips food in a trap room shared with the Raider | vs v5: train +0.01, holdout −0.02; parked; dario −0.14 later shown to be divergence noise; steers Flex on 5–71 turns/game | `experiments/f20d_trap_rooms.py`, branch `f20d-trap-rooms` |
| F20b | F20a + empty-handed Flex defends while the Raider is pinned/trapped | stall maps only, worse than F20a (pinned fires after both are inside; locks Flex on defence); not A/B'd | `experiments/f20b_no_follow.py`, branch `f20b-no-follow` |
| F20a | trapped Flex (20 moves going home within 3 cells) walks into the guard to respawn and defend | vs v5: train +0.03, holdout −0.02; parked; idle_attack −17% on holdout | `experiments/f20a_trapped_haul.py`, branch `f20-trapped-haul` |
| F19c | F19b, but only the Raider pushes; Flex guards home in a deadlock | vs v4: train +0.05 ± 0.05, holdout +0.05 ± 0.04, unseen +0.03 ± 0.03; pooled **+0.040 ± 0.023 (z 1.77)**, positive on all three; reflex +0.16 (z 2.3); conceded unchanged (+0.01); tracking −0.03. W-T-L 517-81-122 → 532-65-123. **Accepted as v5** by the user | `experiments/f19c_raider_push.py`, branch `f19c-raider-push` |
| F19b | deadlock push with both agents: believed guards only cost (don't block); Raider baits up to the guards with no fight search; Flex is the runner | vs v4: train −0.01 ± 0.03, holdout +0.00 ± 0.01, unseen +0.10 ± 0.03 (z 3.0); pooled +0.031 ± 0.015 (z 2.01); W-T-L 515-81-124 → 526-70-124 (ties → wins, no extra losses). **Waiting for the user's decision** | `experiments/f19b_deadlock_push.py`, branch `f19b-deadlock-push` |
| **F19 = v4** | deadlock breaker: tied with ≤ 150 own moves left → bank after 1 dot, count unseen guards at their believed cells, bold route when no food is safe, Flex ignores empty-handed invaders | train +0.10 ± 0.05, holdout +0.03 ± 0.03, unseen +0.04 ± 0.03; pooled **+0.053 ± 0.021 (z 2.51)** over 720 pairs; ties 49→30 on train; no opponent below −1 SE. **Accepted as v4** | `experiments/f19_deadlock_breaker.py`, branch `f19-deadlock` |
| F18 | calm opening: Flex guards home until the first raid is over (≤ 75 own moves) | train −0.15, holdout −0.07; rejected; conceded −0.5/−1.9 but banked −2.5/−1.9 | `experiments/f18_calm_opening.py`, branch `f18-calm-opening` |
| F18b | F18 with a 35-move cap | train −0.15, holdout −0.08; rejected; banked −1.6/−1.3, conceded only −0.1/−0.9. Opening line closed: Flex's attack is worth more than the raids it blocks | `experiments/f18b_short_hold.py`, branch `f18-calm-opening` |
| F14 | capsule guard (race to a capsule an invader is near) | train +0.10, holdout −0.00, unseen +0.05; pooled +0.05 ± 0.031 (z 1.6), parked; blitz −0.14 | `experiments/f14_capsule_guard.py` |
| F13 | analysis: where v2 concedes | big raids 1.1/game = 80% of conceded; half capsule; 84% first half | `tools/raid_fate_probe.py` |
| F15 | proactive capsule cover by home ghosts (never recalls attackers) | train +0.05, holdout −0.05; pooled ±0.00, parked; conceded −0.88, capsules eaten −8%, big raids −10%, but banked −0.60 | `experiments/f15_capsule_cover.py`, branch `f15-capsule-cover` |
| F15b | F15, cover by Flex only | train +0.12 (gate passed), holdout −0.11; pooled ±0.00, parked; dario +0.40/+0.33, search flips by map pool | `experiments/f15b_flex_cover.py`, branch `f15b-flex-cover` |
| F12 | v2 + F9 home hunt (vs v2) | train +0.05, holdout −0.05, unseen −0.12; pooled −0.04 ± 0.035 (z −1.1), rejected; kills up, banked −0.45, conceded ≈ | `experiments/f12_v2_home_hunt.py` |

## Next possible steps (recommended order)
0. **F20 follow-ups** (v6): F20f, Flex also avoids rooms the same guard can close (seen in `20261109-193757-ab-0149`: both agents killed by one guard on consecutive turns); F20c, Raider breakout when trapped regardless of score. Biggest remaining loss cause overall is still invader-unopposed, not stalls.
1. **Deadlock follow-ups** (F19c accepted as v5). Background: remaining deadlocks are mostly structural: a guard parked on the only corridor (e.g. RANDOM797927). A revive idea: both agents attack from different crossings to pull the guard.
(Dead ends, F17a–d: closed. Deaths only cost time, because the food is dropped back on the map. Calmer opening, F18/F18b: closed, holding Flex home costs more banked food than it saves.)
2. F16 tuning: `SCARED_BANK_MARGIN` 2 or 4; scared ghosts eaten fell 0.66 → 0.52 per window, so test `PREY_TRAP_RANGE` larger or a sure-catch check at distance 2 without a pocket (e.g. a ghost in a corridor with no escape).
3. F15/F15b revive: gate the capsule cover by map shape or by opponent (consistent Dario gain).
2. **Calmer opening** (F13): 84% of big raids start in the first half, often as we cross at the same moment. Hold Flex at the border until the first invader shows, or turn back for an invader seen near the border. Can be stacked on F14.
3. **F10 revive on top of v2:** big lead (≥ 5), very late (< 75 moves). Low ceiling: late big raids are only 3% (F13).
4. **F12 revive (cheap):** home hunt only by an agent already a ghost at home, only for invaders carrying 5+.
5. **0–0 deadlocks (deferred by the user):** in a 0–0 game after the halfway point, force one food through (both agents on one crossing, or a capsule). One food turns 1 point into 3. 56 games per 480 are affected.
6. **Outplayed-early losses:** find out why `defend()` concedes more against search than a Flex stalled at the border (seen in F5c). Watch clips with `watch.py`.
7. **Older leads:**
   - F4: both agents leave a long spawn corridor by the same path.
   - F8: both scared ghosts get eaten together.
   - F6 revive: harvest plus more capsules, and still eat scared ghosts far from their spawn.
8. **Before submission:** `main` has v4. Check timing on a slower machine; lower `SEARCH_TIME` first if needed.
