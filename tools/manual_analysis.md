# Manual match analysis

The statistics tell you *what* is going wrong (how many points are lost and to which cause). Watching games tells you *why*. To keep it fast, don't watch whole 1200-move games. Find the moments that cost points and watch 20–60-move clips around them, then write down what you saw so it ends up next to the numbers.

Run all commands from the repo root (`pacman-agent/`):

```bash
alias W='venv/bin/python tools/watch.py'
```

## The 15-minute routine (after every A/B or tournament run)

1. **Pick what to look at.** Start from the report's loss causes: `tools/reports/<run_id>.md`.
2. **Get a short list.** Use `W queue` for the worst games, or `W moments` for the costliest moments.
3. **Read the timeline** of one game with `W events <game_id>`. It fits on one screen.
4. **Watch the clip** with `W play <game_id> --from <turn−20> --to <turn+20>`.
5. **Write a note** right away with `W note <game_id> --turn <t> --tag <tag> "..."`.
6. After 5–10 clips, run `W notes --tag <tag>`. If the same thing shows up three or more times, add it to `tools/FIXES.md` as a new entry and cite the note ids as evidence.

## Commands

### `queue`: worst losses and ties
```bash
W queue                                   # latest run that contains my_team, 10 worst games
W queue --run 20261103-180445-rr --n 20   # a specific run
W queue --cause invader-unopposed         # only games lost to this cause
W queue --opp blitz                       # only against one opponent
W queue --agent v0                        # an older version (it's named v0 in A/B runs)
```
Columns:
- **margin:** points (negative means a loss).
- **cause:** the analyzer's main reason.
- **deaths/lost:** our deaths and the food we lost in them.
- **unopposed:** our food eaten with no defender within 6 steps.
- **idle:** turns stuck as Pacman.

### `moments`: individual costly moments across a run
```bash
W moments                                  # all kinds, ranked by cost
W moments --type death --min-carried 5     # we died carrying 5+ food
W moments --type unopposed                 # invader raids with nobody defending (3+ bites)
W moments --type ghost                     # we ate a scared ghost (did that waste our free run?)
W moments --type capsule                   # capsules we ate: was the window used well?
W moments --type stall                     # an attacker stuck for 40+ turns (slower: replays every game)
W moments --opp dario --type death         # combine with an opponent filter
```
Each row gives a `game_id` and a `turn`, ready to paste into `play`.

### `events`: one game on one screen
```bash
W events 20261103-180445-rr-0126
```
It shows the score every 40 turns, plus deaths (with food carried, distance home and pocket depth), scared ghosts eaten, banks of 2+, capsules and unopposed raids. Use the score line to find where the game swung, then pick the event that explains it.

### `play`: watch a clip
```bash
W play 20261103-180445-rr-0126 --from 320 --to 360               # default speed
W play 20261103-180445-rr-0126 --from 320 --to 360 --delay 0.25  # slower
W play <game_id> --from 500 --zoom 1.5                           # bigger window, play to the end
```
- It skips straight to `--from` without drawing the earlier turns, so starting at turn 900 is instant.
- The current turn number shows in the window's info bar.
- Press Enter in the terminal to close the window at the end.
- **Turn numbering:** each turn is one agent's move (0–1199). One "round" is 4 turns: every agent moves once. Agent indices: red = 0 and 2, blue = 1 and 3. In our team the **first** agent is the **Raider** and the second is **Flex**.

### `note` / `notes`: keep what you saw
```bash
W note 20261103-180445-rr-0126 --turn 337 --tag scared-defence "both our ghosts scared next to each other near our food; invader ate both"
W notes                       # everything
W notes --tag scared-defence  # one topic
W notes --game 20261103-180445-rr-0126
```
Notes live in `tools/results.db` (table `notes`) with the game and turn, so you can always replay the exact clip again.

## Suggested tags
Reusing the same tags keeps `W notes --tag` useful:

| tag | use it when |
|---|---|
| `defence` | an invader ate freely, a defender was in the wrong place, or the chase failed |
| `scared-defence` | our scared ghosts were eaten or ran the wrong way |
| `attack-death` | we died carrying food (pocket, two guards, wrong escape) |
| `stall` | an attacker was stuck against a guard |
| `capsule` | a capsule was used badly or missed |
| `coordination` | both agents did the same thing, or nobody was home |
| `endgame` | the last ~100 moves: banking, defending the lead |
| `opponent-trick` | a pattern an opponent uses that we could copy or counter |
| `engine` | something weird in the rules or the tooling |

## What to look for, by loss cause

| cause | watch | questions |
|---|---|---|
| `invader-unopposed` | `W moments --type unopposed`, from the raid start −20 | Where were both our agents? Did anyone see the invader? (Unseen invaders are tracked by a guess.) Did Flex react, and how far away was it? |
| `died-carrying` | `W moments --type death --min-carried 4`, from −30 | Was it a dead-end pocket? Did we see the ghost coming? Was there a safer route home or a capsule? Was the carry limit too high? |
| `stalled` | `W moments --type stall`, from the stall start | Does the attacker go back and forth between two crossings? Is the guard mirroring it? Would going for a capsule or switching sides have worked? |
| `capsule-swing` | `W events`, then the turns after the opponent's capsule | Did our scared ghosts get eaten? Did the invader raid freely while we were scared? |
| `outscored-throughput` | `W events` score line, then a middle stretch | Are we taking long trips for little food? Banking too early or too late? |
| `timeout-carrying` | the last 60 turns | Did we start for home too late? |

## Comparing two versions on the same situation
A/B runs play both versions on the same maps and colours with the same seeds. To see what a change did, find the same opponent, layout and side for both:
```bash
venv/bin/python tools/query.py sql "SELECT game_id, agent_name, side, margin FROM team_stats ts JOIN games g USING(game_id) WHERE run_id='<ab_run>' AND layout='<layout>' AND opp_name='<opp>' ORDER BY side, agent_name"
```
Then `W play` both game ids from the same turn.

## Useful numbers next to the clips
```bash
venv/bin/python tools/query.py report <run_id>                    # standings, causes, timing, worst games
venv/bin/python tools/diagnose.py unopposed <run_id> --agent my_team v0   # defence breakdown
venv/bin/python tools/diagnose.py capsules <run_id> --agent my_team v0    # capsule-window use
venv/bin/python tools/query.py progress                           # points/game per version over time
```

## Tips
- **Start from the money.** The `moments` cost column is in food points. A 30-bite raid is worth more attention than one death carrying 3.
- **Watch one agent at a time.** On the first pass follow only the Raider, then replay and follow Flex.
- **Slow down** for fights (`--delay 0.3`); use the default speed for walking.
- **Write the note before watching the next clip.** Details are forgotten quickly.
- **One-offs aren't fixes.** Only patterns seen three or more times (or backed by a `diagnose.py` count) go into `FIXES.md`.
