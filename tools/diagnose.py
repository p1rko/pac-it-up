"""
Deeper per-situation breakdowns, computed by replaying stored games.

  python tools/diagnose.py unopposed <run_id> [--agent my_team v0]
  python tools/diagnose.py capsules <run_id> [--agent my_team v0]
  python tools/diagnose.py leads <run_id> [--agent my_team v1]

unopposed: every bite an invader takes from our food with none of our ghosts
within 6 steps, split by what our two agents (first = Raider, second = Flex)
were doing, how much the invader already carried, and why Flex didn't react
to big hauls.
"""

import argparse
import json
import os
import pickle
import sys
from collections import Counter, defaultdict

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TOOLS_DIR)
sys.path.insert(0, TOOLS_DIR)
os.chdir(os.path.join(REPO_DIR, 'pacman-contest', 'src', 'contest'))

from contest.capture import GameState  # noqa: E402

import db  # noqa: E402
from analyze import UNOPPOSED_DIST, MapInfo  # noqa: E402

BIG_HAUL = 4


def _pos(state, i):
    p = state.get_agent_position(i)
    return int(p[0]), int(p[1])


def unopposed(con, run_id, agent):
    rows = con.execute('SELECT ts.side, ts.agent_hash, ts.opp_name, g.replay_path FROM team_stats ts '
                       'JOIN games g USING (game_id) WHERE g.run_id = ? AND ts.agent_name = ?',
                       (run_id, agent)).fetchall()
    situation, carried, by_opp = Counter(), Counter(), Counter()
    flex_why, flex_dist = Counter(), defaultdict(list)
    total = 0
    for r in rows:
        with open(os.path.join(REPO_DIR, r['replay_path']), 'rb') as f:
            rep = pickle.load(f)
        info = MapInfo(rep['layout'])
        state = GameState()
        state.initialize(rep['layout'], 4)
        state.data.timeleft = rep['length']
        mine = (0, 2) if r['side'] == 'red' else (1, 3)
        for i, action in rep['actions']:
            prev, state = state, state.generate_successor(i, action)
            if i in mine or state.data.agent_states[i].num_carrying <= prev.data.agent_states[i].num_carrying:
                continue
            pos = _pos(state, i)
            guards = [k for k in mine if not prev.data.agent_states[k].is_pacman]
            if min((info.d(pos, _pos(prev, k)) for k in guards), default=999) <= UNOPPOSED_DIST:
                continue
            total += 1
            by_opp[r['opp_name']] += 1
            raider, flex = (prev.data.agent_states[k] for k in mine)
            situation[('raider attacking' if raider.is_pacman else 'raider home, far') + ' / ' +
                      ('flex attacking' if flex.is_pacman else 'flex home, far')] += 1
            c = prev.data.agent_states[i].num_carrying
            carried['0' if c == 0 else '1-3' if c < BIG_HAUL else f'{BIG_HAUL}+'] += 1
            if c >= BIG_HAUL:
                why = ('flex carrying food' if flex.num_carrying > 0 else 'flex scared' if flex.scared_timer > 0
                       else 'flex home but far' if not flex.is_pacman else 'flex attacking, empty-handed')
                flex_why[why] += 1
                flex_dist[why].append(info.d(pos, _pos(prev, mine[1])))

    print(f'## Unopposed bites on {agent} in {run_id}: {total} over {len(rows)} games '
          f'({total / max(len(rows), 1):.1f} per game)\n')
    print('| our agents | bites | share |\n|---|---|---|')
    for k, v in situation.most_common():
        print(f'| {k} | {v} | {100 * v / total:.0f}% |')
    print('\n| invader already carrying | bites |\n|---|---|')
    for k in ('0', '1-3', f'{BIG_HAUL}+'):
        print(f'| {k} | {carried[k]} |')
    print(f'\n| big-haul bite ({BIG_HAUL}+), flex was | bites | avg flex distance |\n|---|---|---|')
    for k, v in flex_why.most_common():
        print(f'| {k} | {v} | {sum(flex_dist[k]) / v:.1f} |')
    print('\n| opponent | bites |\n|---|---|')
    for k, v in by_opp.most_common():
        print(f'| {k} | {v} |')


def capsules(con, run_id, agents):
    """Per capsule window opened by the agent's Pacman: food eaten/banked, food still
    carried when the window closes, scared ghosts eaten and the timer they had left."""
    marks = ','.join('?' * len(agents))
    rows = con.execute(f'SELECT ts.side, ts.agent_name, g.replay_path FROM team_stats ts JOIN games g '
                       f'USING (game_id) WHERE g.run_id = ? AND ts.agent_name IN ({marks})',
                       (run_id, *agents)).fetchall()
    agg = defaultdict(Counter)
    for r in rows:
        with open(os.path.join(REPO_DIR, r['replay_path']), 'rb') as f:
            rep = pickle.load(f)
        state = GameState()
        state.initialize(rep['layout'], 4)
        state.data.timeleft = rep['length']
        mine = (0, 2) if r['side'] == 'red' else (1, 3)
        opp = tuple(k for k in range(4) if k not in mine)
        starts = {k: tuple(map(int, state.data.agent_states[k].start.pos)) for k in opp}
        a = agg[r['agent_name']]
        a['games'] += 1
        window = None
        for i, action in rep['actions']:
            prev, state = state, state.generate_successor(i, action)
            if i in mine and len(state.get_capsules()) < len(prev.get_capsules()):
                a['windows'] += 1
                window = Counter(banked0=sum(state.data.agent_states[k].num_returned for k in mine))
            if window is None:
                continue
            if i in mine and state.data.agent_states[i].num_carrying > prev.data.agent_states[i].num_carrying:
                window['eaten'] += 1
            for k in opp:
                was = prev.data.agent_states[k]
                # a scared *ghost* eaten by our Pacman (an invader still carrying a
                # scared timer and caught at our home is ordinary defence)
                if (was.scared_timer > 0 and not was.is_pacman
                        and _pos(state, k) == starts[k] and _pos(prev, k) != starts[k]):
                    a['ghosts_eaten'] += 1
                    a['timer_left_at_kill'] += was.scared_timer
            if max(state.data.agent_states[k].scared_timer for k in opp) == 0:
                a['eaten'] += window['eaten']
                a['banked'] += sum(state.data.agent_states[k].num_returned for k in mine) - window['banked0']
                a['carry_at_end'] += sum(state.data.agent_states[k].num_carrying for k in mine)
                window = None

    print(f'## Capsule windows in {run_id}\n')
    print('| agent | games | capsules/game | food eaten/window | banked/window | carrying at end | '
          'scared ghosts eaten/window | their timer left when eaten |\n|---|---|---|---|---|---|---|---|')
    for name, a in agg.items():
        w = max(a['windows'], 1)
        print(f"| {name} | {a['games']} | {a['windows'] / a['games']:.2f} | {a['eaten'] / w:.1f} | "
              f"{a['banked'] / w:.1f} | {a['carry_at_end'] / w:.1f} | {a['ghosts_eaten'] / w:.2f} | "
              f"{a['timer_left_at_kill'] / max(a['ghosts_eaten'], 1):.1f} |")


def leads(con, run_id, agents):
    """Losses after leading in the second half, and the enemy trip that decided
    each one: the biggest bank after we last stood level or ahead."""
    marks = ','.join('?' * len(agents))
    rows = con.execute(f'SELECT ts.side, ts.agent_name, ts.points, g.timeline_json, g.replay_path FROM team_stats ts '
                       f'JOIN games g USING (game_id) WHERE g.run_id = ? AND ts.agent_name IN ({marks})',
                       (run_id, *agents)).fetchall()
    agg = defaultdict(lambda: defaultdict(list))
    for r in rows:
        a = agg[r['agent_name']]
        a['games'].append(1)
        if r['points'] != 0:
            continue
        sign = 1 if r['side'] == 'red' else -1
        timeline = [sign * s for s in json.loads(r['timeline_json'])]
        if not any(s > 0 for s in timeline[len(timeline) // 2:]):
            continue
        a['blown'].append(1)
        last_level = max(k for k, s in enumerate(timeline) if s >= 0) * 40
        with open(os.path.join(REPO_DIR, r['replay_path']), 'rb') as f:
            rep = pickle.load(f)
        info = MapInfo(rep['layout'])
        state = GameState()
        state.initialize(rep['layout'], 4)
        state.data.timeleft = rep['length']
        mine = (0, 2) if r['side'] == 'red' else (1, 3)
        history = []
        for i, action in rep['actions']:
            state = state.generate_successor(i, action)
            history.append(state)
        best = None   # (turn, enemy, amount) of the biggest bank after last_level
        for turn in range(max(last_level, 1), len(history)):
            for e in (k for k in range(4) if k not in mine):
                before = history[turn - 1].data.agent_states[e]
                after = history[turn].data.agent_states[e]
                banked = before.num_carrying > 0 and after.num_carrying == 0 and not after.is_pacman \
                    and after.configuration.pos != after.start.pos
                if banked and (best is None or before.num_carrying > best[2]):
                    best = (turn, e, before.num_carrying)
        if best is None:
            continue
        turn, e, amount = best
        start = turn
        while start > 0 and history[start - 1].data.agent_states[e].num_carrying > 0:
            start -= 1
        near, closest = 0, 999
        for s in history[start:turn]:
            ghosts = [info.d(_pos(s, e), _pos(s, k)) for k in mine if not s.data.agent_states[k].is_pacman]
            closest = min([closest] + ghosts)
            near += bool(ghosts) and min(ghosts) <= 3
        a['haul'].append(amount)
        a['rounds'].append((turn - start) / 4)
        a['near'].append(near / max(turn - start, 1))
        a['closest'].append(closest)

    print(f'## Second-half leads lost in {run_id}\n')
    print('| agent | games | leads lost | decisive haul | trip (rounds) | our ghost within 3 | '
          'closest ghost (median) |\n|---|---|---|---|---|---|---|')
    for name, a in agg.items():
        n = max(len(a['haul']), 1)
        closest = sorted(a['closest'])[len(a['closest']) // 2] if a['closest'] else '-'
        print(f"| {name} | {len(a['games'])} | {len(a['blown'])} | {sum(a['haul']) / n:.1f} | "
              f"{sum(a['rounds']) / n:.0f} | {100 * sum(a['near']) / n:.0f}% | {closest} |")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('kind', choices=['unopposed', 'capsules', 'leads'])
    parser.add_argument('run_id')
    parser.add_argument('--agent', nargs='+', default=['my_team'])
    args = parser.parse_args()
    if args.kind == 'unopposed':
        for agent in args.agent:
            unopposed(db.connect(), args.run_id, agent)
    elif args.kind == 'leads':
        leads(db.connect(), args.run_id, args.agent)
    else:
        capsules(db.connect(), args.run_id, args.agent)


if __name__ == '__main__':
    main()
