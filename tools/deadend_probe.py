"""
Where our attackers die (F17, the user's "remember dead ends" idea).

Each death as a Pacman is classed by where it happened:
  - pocket:    a classic dead end (leaf pruning, `MapInfo.pocket_depth`);
  - trap room: an area with loops inside but a single door cell towards our
               home border (removing one cell cuts it off), not a pocket;
  - open:      anywhere else.
For dead-end deaths: was an enemy ghost visible (within 5 of either of our
agents) when we went in, and how far was the nearest enemy ghost then.

  python tools/deadend_probe.py <agent> <run_id> [<run_id> ...]
"""
import os, pickle, sys
from collections import Counter, deque
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'tools'))
os.chdir(os.path.join(REPO, 'pacman-contest', 'src', 'contest'))
from contest.capture import GameState
import db
from analyze import RED, BLUE, MapInfo


def pos(s, i):
    p = s.get_agent_position(i)
    return int(p[0]), int(p[1])


def trap_rooms(info, red):
    """Enemy-side, non-pocket cells cut off from our home border by removing one cell."""
    home = info.border[RED if red else BLUE]
    mid = info.width // 2
    enemy = [c for c in info.cells if (c[0] >= mid if red else c[0] < mid)]
    behind = set()
    for door in enemy:
        seen = set(h for h in home if h != door)
        q = deque(seen)
        while q:
            c = q.popleft()
            for n in info.nbrs[c]:
                if n != door and n not in seen:
                    seen.add(n); q.append(n)
        behind.update(c for c in enemy if c not in seen and c != door and info.pocket_depth.get(c, 0) == 0)
    return behind


agent, runs = sys.argv[1], sys.argv[2:]
con = db.connect()
rows = con.execute(
    f"SELECT ts.side, g.replay_path FROM team_stats ts JOIN games g USING (game_id) "
    f"WHERE g.run_id IN ({','.join('?' * len(runs))}) AND ts.agent_name=?", (*runs, agent)).fetchall()
kind, lost, carried, seen_at_entry, nearest = Counter(), Counter(), Counter(), Counter(), Counter()
deaths, rooms = 0, {}
for r in rows:
    rep = pickle.load(open(os.path.join(REPO, r['replay_path']), 'rb'))
    red = r['side'] == 'red'
    info = MapInfo(rep['layout'])
    key = (str(rep['layout']), red)
    if key not in rooms:
        rooms[key] = trap_rooms(info, red)
    behind = rooms[key]
    s = GameState(); s.initialize(rep['layout'], 4); s.data.timeleft = rep['length']
    mine = (0, 2) if red else (1, 3)
    theirs = tuple(k for k in range(4) if k not in mine)
    starts = {k: pos(s, k) for k in range(4)}
    entry = {}   # our agent -> (enemy ghost positions, our positions) when it went in

    def trapped(c):
        return info.pocket_depth.get(c, 0) > 0 or c in behind

    for i, a in rep['actions']:
        prev, s = s, s.generate_successor(i, a)
        for k in mine:   # deaths happen on either side's move
            p, pp = pos(s, k), pos(prev, k)
            st_prev = prev.data.agent_states[k]
            if st_prev.is_pacman and p == starts[k] and pp != starts[k]:
                deaths += 1
                where = 'pocket' if info.pocket_depth.get(pp, 0) else 'trap room' if pp in behind else 'open'
                kind[where] += 1; lost[where] += st_prev.num_carrying
                c = st_prev.num_carrying
                carried['0' if not c else '1-4' if c < 5 else '5+'] += 1
                if where != 'open' and k in entry:
                    enemies, ours = entry[k]
                    vis = any(min(abs(e[0] - o[0]) + abs(e[1] - o[1]) for o in ours) <= 5 for e in enemies)
                    seen_at_entry['visible' if vis else 'not visible'] += 1
                    d = min((info.d(e, pp) for e in enemies), default=99)
                    nearest['<=5' if d <= 5 else '6-10' if d <= 10 else '11+'] += 1
                entry.pop(k, None)
                continue
            if trapped(p) and not trapped(pp):
                entry[k] = ([pos(s, e) for e in theirs if not s.data.agent_states[e].is_pacman],
                            [pos(s, m) for m in mine])
            elif not trapped(p):
                entry.pop(k, None)

n = max(len(rows), 1)
print(f'{agent}: {len(rows)} games, {deaths} deaths as Pacman ({deaths / n:.2f}/game)')
print(' where (deaths):', dict(kind))
print(' where (food lost):', dict(lost), f'= {sum(lost.values()) / n:.2f}/game')
print(' carrying at death:', dict(carried))
print(' dead-end deaths, an enemy ghost visible when we went in:', dict(seen_at_entry))
print(' nearest enemy ghost to the death cell when we went in:', dict(nearest))
