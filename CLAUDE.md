# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Pacman Capture-the-Flag contest entry (team "Pack It Up"). The submission is the single file `my_team.py`; it must stay self-contained (only stdlib + `contest.*` imports). The game engine lives in the `pacman-contest/` git submodule (upstream `aig-upf/pacman-contest`) — treat it as third-party and don't edit it for agent work. `AGENT_EXPLAINED.md` is the full design write-up and test-results log; keep it in sync when behaviour or tunables change.

## Setup and running

```bash
git submodule update --init --remote        # pull the contest engine
python3 -m venv venv && source venv/bin/activate
cd pacman-contest && pip install -r requirements.txt && pip install -e . && cd ..
```

Games are run from inside the engine directory, with team files given as paths relative to it:

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team                    # watch a game
python capture.py -r ../../../my_team.py -b baseline_team -Q -l RANDOM42     # headless, random map
python capture.py -r ../../../my_team.py -b ../../../strategies/blitz.py -Q -n 5
python capture.py -r ../../../my_team.py --redOpts first=WardenAgent,second=FlexAgent -b baseline_team
```

Useful `capture.py` flags: `-Q` super-quiet (no graphics), `-q` quiet, `-l RANDOM<seed>` random maze, `-n N` games, `-f`/`--setRandomSeed` reproducibility, `-c` catch exceptions, `--record` save replays.

Set `PACKITUP_DEBUG=1` to disable the agent's `try/except` safety net in `choose_action` so exceptions surface instead of being replaced by a random legal move. There is no test suite or linter; evaluation is done by playing many headless games on random maps with both colours (`-r`/`-b` swapped) and comparing wins/scores.

`scripts/play.sh` is stale (references `myTeam.py` and `runner.py`); prefer the `capture.py` commands above.

## Architecture of `my_team.py`

- `create_team` defaults to `RaiderAgent` + `FlexAgent` (the tournament calls it with no extra args, so the defaults _are_ the submission). Classes are resolved by `eval(name)`, so any class in the file can be swapped in via `--redOpts`/`--blueOpts`.
- `SmartAgent(CaptureAgent)` holds all shared machinery; the role subclasses only decide _when_ to call `attack()` vs `defend()`:
  - `RaiderAgent` — attacks by default, helps defend against two invaders or to protect a late lead.
  - `FlexAgent(RaiderAgent)` — also defends when an invader is near or carrying a lot, gated by an adaptive "is defending paying off" budget (`FREE_DEFENCE`, `TURNS_PER_CATCH`).
  - `WardenAgent` — full-time defender kept for comparison only; not used in the submission.
- `TEAM_INFO` is a module-level dict keyed by team colour (`self.red`) that both agents share (same process). It holds per-enemy probability distributions (exact belief tracking from noisy distances, visibility, side-of-map constraints and vanished food) plus coordination state like teammate targets.
- Per-turn pipeline: `update_beliefs` → role decision → `attack`/`defend` pick a goal → `plan()` (Dijkstra with ghost-proximity and dead-end-pocket costs, ghost-adjacent cells blocked) → if a visible enemy is within `FIGHT_RANGE`, the move is overridden by time-boxed iterative-deepening alpha-beta over real game rules.
- Dead-end pockets (depth + entrance per cell) are precomputed once in `register_initial_state` and drive both attacker safety and defender trapping.
- Tunables are class constants at the top of `SmartAgent` / `FlexAgent` (`CARRY_LIMIT`, `DANGER_RADIUS`, `SAFETY_MARGIN`, `SEARCH_TIME`, `FIGHT_RANGE`, `DEFEND_RADIUS`, `DANGER_HAUL`, `FREE_DEFENCE`, `TURNS_PER_CATCH`).

## Contest constraints that shape the code

- A game is forfeited after 3 moves over the time limit (1 s) or any uncaught exception. Keep `choose_action` wrapped in its safety net and keep search time-boxed (`SEARCH_TIME` 0.3 s, overall per-turn budget ~0.75 s). If adding computation, measure worst-case move time; lower `SEARCH_TIME` first if the tournament machine is slower.
- Heavy precomputation belongs in `register_initial_state` (it has a larger time allowance).

## `strategies/`

Earlier/alternative team files used only as sparring opponents, not submitted: `reflex.py`, `tracking.py`, `search.py` (attacker + defender drafts), `blitz.py` (two attackers) and `turtle.py` (two defenders), both derived from `search.py`. They are standalone copies — changes to `my_team.py` do not propagate to them.

## Workflow

-Work is based on analyzing the already existing agents and trying to optimize them based on the results they produce
-For bigger changes, propose a plan first
