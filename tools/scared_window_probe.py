"""
What our attackers do with a scared window (after we eat an enemy capsule).

The user's observations (2026-11-07):
 1. a scared ghost cornered near our attacker: both shuffle back and forth
    until the timer runs out (wasted window);
 2. an attacker keeps eating or chasing until the ghosts recover, then gets
    caught carrying food (should have gone home while it still could).

Per window (from a capsule eaten by us until no enemy ghost is scared) and per
agent of ours that is a Pacman in it:
  - oscillating turns: back at the cell of 2 moves ago (A-B-A) while a scared
    ghost is within 3;
  - scared ghosts eaten, food banked during the window;
  - at the moment the last enemy ghost recovers: food carried and home distance;
  - deaths while carrying in the 30 moves after the window, and food lost.

  python tools/scared_window_probe.py <agent> <run_id> [<run_id> ...]
"""
import os, pickle, sys
from collections import Counter
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'tools'))
os.chdir(os.path.join(REPO, 'pacman-contest', 'src', 'contest'))
from contest.capture import GameState
import db
from analyze import RED, BLUE, MapInfo

AFTER = 30   # our agent's moves after the window in which a death counts


def pos(s, i):
    p = s.get_agent_position(i)
    return int(p[0]), int(p[1])


agent, runs = sys.argv[1], sys.argv[2:]
con = db.connect()
rows = con.execute(
    f"SELECT ts.side, g.replay_path FROM team_stats ts JOIN games g USING (game_id) "
    f"WHERE g.run_id IN ({','.join('?' * len(runs))}) AND ts.agent_name=?", (*runs, agent)).fetchall()

windows = 0
osc_turns = osc_windows = 0
eaten_ghosts = banked = 0
carry_at_end = Counter()          # bucket of food carried when the window ends (pacmen only)
end_states = Counter()            # 'home' / 'carrying, home_dist <= 3' / ... at window end
after_deaths = after_lost = 0
after_deaths_late = 0             # died, but was carrying at window end too (never went home)
window_len = []
fates, fate_food = Counter(), Counter()
fate_delay, fate_delay_died = [], []
in_deaths, in_lost = Counter(), 0
examples = []

for r in rows:
    rep = pickle.load(open(os.path.join(REPO, r['replay_path']), 'rb'))
    info = MapInfo(rep['layout'])
    s = GameState(); s.initialize(rep['layout'], 4); s.data.timeleft = rep['length']
    red = r['side'] == 'red'
    mine = (0, 2) if red else (1, 3)
    theirs = tuple(k for k in range(4) if k not in mine)
    hd = info.home_dist[RED if red else BLUE]
    starts = {k: pos(s, k) for k in range(4)}
    in_window = False
    trail = {k: [] for k in mine}
    w_osc = 0
    w_start = 0
    watch = {}    # our agent -> (moves left to watch, carried at window end)
    fate = {}     # our agent carrying at a window end -> (carried, move number)
    move_no = 0
    for i, a in rep['actions']:
        prev, s = s, s.generate_successor(i, a)
        move_no += 1
        st_prev, st = prev.data.agent_states, s.data.agent_states
        scared = [st[e].scared_timer for e in theirs if not st[e].is_pacman]
        any_scared = any(t > 0 for t in scared)
        caps_prev = prev.get_blue_capsules() if red else prev.get_red_capsules()
        caps_now = s.get_blue_capsules() if red else s.get_red_capsules()
        if i in mine and len(caps_now) < len(caps_prev):
            if not in_window:
                windows += 1; w_osc = 0; w_start = move_no
            in_window = True
        # eaten a scared ghost (on either side's move): it is back at its start
        for e in theirs:
            if in_window and st_prev[e].scared_timer > 0 and pos(s, e) == starts[e] and pos(prev, e) != starts[e]:
                eaten_ghosts += 1
        # our deaths happen on either side's move too
        for k in mine:
            p = pos(s, k)
            died = st_prev[k].is_pacman and p == starts[k] and pos(prev, k) != starts[k]
            if died and in_window:
                in_deaths['carrying' if st_prev[k].num_carrying else 'empty'] += 1
                in_lost += st_prev[k].num_carrying
            if k in fate:
                carried_end, t_end = fate[k]
                if st_prev[k].is_pacman and not st[k].is_pacman and not died:
                    fates['banked'] += 1; fate_food['banked'] += st_prev[k].num_carrying
                    fate_delay.append(move_no - t_end); del fate[k]
                elif died:
                    fates['died'] += 1; fate_food['died'] += st_prev[k].num_carrying
                    fate_delay_died.append(move_no - t_end); del fate[k]
            if k in watch and died:
                if st_prev[k].num_carrying > 0:
                    after_deaths += 1; after_lost += st_prev[k].num_carrying
                    if watch[k][1] > 0:
                        after_deaths_late += 1
                del watch[k]
        if i in mine:
            p = pos(s, i)
            # banked
            if st_prev[i].num_carrying > 0 and not st[i].is_pacman and st_prev[i].is_pacman and in_window:
                banked += st_prev[i].num_carrying
            if in_window and st[i].is_pacman:
                trail[i].append(p)
                near_scared = any(st[e].scared_timer > 0 and not st[e].is_pacman and
                                  info.d(p, pos(s, e)) <= 3 for e in theirs)
                if len(trail[i]) >= 3 and trail[i][-1] == trail[i][-3] != trail[i][-2] and near_scared:
                    osc_turns += 1; w_osc += 1
                    ghost_info = [(pos(s, e), st[e].scared_timer, info.pocket_depth.get(pos(s, e), 0))
                                  for e in theirs if not st[e].is_pacman]
                    examples.append((r['replay_path'], move_no, i, p, trail[i][-2], st[i].num_carrying,
                                     hd.get(p, 99), ghost_info))
            if i in watch:
                left, carried_end = watch[i]
                watch[i] = (left - 1, carried_end)
                if left <= 1:
                    del watch[i]
        if in_window and not any_scared:
            in_window = False
            window_len.append(move_no - w_start)
            if w_osc:
                osc_windows += 1
            for k in mine:
                trail[k] = []
                c = st[k].num_carrying
                if st[k].is_pacman:
                    b = '0' if c == 0 else '1-2' if c <= 2 else '3-5' if c <= 5 else '6+'
                    carry_at_end[b] += 1
                    hdist = hd.get(pos(s, k), 99)
                    end_states['pacman, carrying, home <= 3' if c and hdist <= 3 else
                               'pacman, carrying, home 4-8' if c and hdist <= 8 else
                               'pacman, carrying, home 9+' if c else 'pacman, empty'] += 1
                else:
                    end_states['ghost (home)'] += 1
                watch[k] = (AFTER, c)
                if st[k].is_pacman and c > 0:
                    fate[k] = (c, move_no)
    for k in fate:
        fates['game ended'] += 1; fate_food['game ended'] += st[k].num_carrying

n = len(rows)
print(f'{agent}: {n} games, {windows} scared windows ({windows / max(n, 1):.2f}/game), '
      f'mean length {sum(window_len) / max(len(window_len), 1):.0f} moves')
print(f' oscillating turns near a scared ghost: {osc_turns} ({osc_turns / max(windows, 1):.1f}/window), '
      f'windows with any: {osc_windows} ({100 * osc_windows / max(windows, 1):.0f}%)')
print(f' scared ghosts eaten in windows: {eaten_ghosts} ({eaten_ghosts / max(windows, 1):.2f}/window); '
      f'food banked in windows: {banked} ({banked / max(windows, 1):.1f}/window)')
print(' our agents when the last ghost recovers:', dict(end_states))
print(' food carried then (pacmen):', dict(carry_at_end))
print(f' deaths carrying within {AFTER} moves after a window: {after_deaths} '
      f'({after_deaths / max(n, 1):.2f}/game), food lost {after_lost} ({after_lost / max(n, 1):.2f}/game); '
      f'{after_deaths_late} of them were carrying when the window ended')
print(f' deaths during windows: {dict(in_deaths)}, food lost {in_lost} ({in_lost / max(n, 1):.2f}/game)')
if '--examples' in sys.argv[3:] or os.environ.get('EXAMPLES'):
    print(' oscillation examples (replay, move, agent, at, other cell, carrying, home dist, '
          'enemy ghosts (pos, scared, pocket depth)):')
    seen = set()
    for ex in examples:
        key = (ex[0], ex[2], ex[1] // 40)
        if key in seen:
            continue
        seen.add(key)
        print('  ', ex)
        if len(seen) >= int(os.environ.get('EXAMPLES', 12)):
            break
med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None
print(f' fate of food carried at the window end: {dict(fates)}, food {dict(fate_food)}; '
      f'median moves until banked {med(fate_delay)}, until died {med(fate_delay_died)}')
