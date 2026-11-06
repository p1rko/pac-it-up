"""
How capsules get eaten: for every capsule of ours an invader eats, how far it
and our best responder were from it when the invader first came within 10 steps
during that raid. Eligible responder: unscared, at home or an attacker within 3
of our border (the F14 capsule guard's rule).

  python tools/capsule_race_probe.py <agent> <run_id> [<run_id> ...]
"""
import os, pickle, sys
from collections import Counter
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'tools'))
os.chdir(os.path.join(REPO, 'pacman-contest', 'src', 'contest'))
from contest.capture import GameState
import db
from analyze import RED, BLUE, MapInfo
def pos(s, i):
    p = s.get_agent_position(i); return int(p[0]), int(p[1])
agent, runs = sys.argv[1], sys.argv[2:]
con = db.connect()
rows = con.execute(f"SELECT ts.side, g.replay_path FROM team_stats ts JOIN games g USING (game_id) WHERE g.run_id IN ({','.join('?'*len(runs))}) AND ts.agent_name=?", (*runs, agent)).fetchall()
gap_elig, gap_any, never10, first_d, eaten = Counter(), Counter(), 0, Counter(), 0
for r in rows:
    rep = pickle.load(open(os.path.join(REPO, r['replay_path']), 'rb'))
    info = MapInfo(rep['layout']); s = GameState(); s.initialize(rep['layout'], 4); s.data.timeleft = rep['length']
    red = r['side'] == 'red'; mine = (0, 2) if red else (1, 3); theirs = tuple(k for k in range(4) if k not in mine)
    hd = info.home_dist[RED if red else BLUE]
    rec = {e: [] for e in theirs}   # per enemy, records during the current raid
    for i, a in rep['actions']:
        prev, s = s, s.generate_successor(i, a)
        caps_prev = prev.get_red_capsules() if red else prev.get_blue_capsules()
        if i not in theirs: continue
        st = s.data.agent_states
        if not prev.data.agent_states[i].is_pacman: rec[i] = []
        caps_now = set(s.get_red_capsules() if red else s.get_blue_capsules())
        gone = [c for c in caps_prev if c not in caps_now]
        p = pos(prev, i)
        if prev.data.agent_states[i].is_pacman:
            for c in caps_prev:
                c = (int(c[0]), int(c[1]))
                d_inv = info.d(p, c)
                elig = [info.d(pos(prev, k), c) for k in mine if prev.data.agent_states[k].scared_timer == 0 and
                        (not prev.data.agent_states[k].is_pacman or hd.get(pos(prev, k), 99) <= 3)]
                anyd = min(info.d(pos(prev, k), c) for k in mine)
                rec[i].append((c, d_inv, min(elig) if elig else None, anyd))
        for c in gone:
            c = (int(c[0]), int(c[1])); eaten += 1
            hist = [x for x in rec[i] if x[0] == c]
            w = [x for x in hist if x[1] <= 10]
            if not w: never10 += 1; continue
            _, d_inv, el, an = w[0]
            first_d[min(d_inv, 10)] += 1
            g = 'no eligible' if el is None else 'ahead' if el < d_inv else 'tie' if el == d_inv else '+1-2' if el - d_inv <= 2 else '+3-5' if el - d_inv <= 5 else '+6+'
            gap_elig[g] += 1
            g2 = 'ahead' if an < d_inv else 'tie' if an == d_inv else '+1-2' if an - d_inv <= 2 else '+3-5' if an - d_inv <= 5 else '+6+'
            gap_any[g2] += 1
print(f'{agent}: {eaten} capsules eaten by invaders in {len(rows)} games ({eaten/len(rows):.2f}/game); never seen within 10 in the raid: {never10}')
print(' invader distance at first record within 10:', dict(sorted(first_d.items())))
print(' eligible guard distance minus invader distance at that moment:', dict(gap_elig))
print(' any agent of ours, same:', dict(gap_any))
