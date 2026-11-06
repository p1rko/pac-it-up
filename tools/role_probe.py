"""
Where each of our agents spends its turns, split by role (first index =
Raider, second = Flex), computed by replaying stored games.

  python tools/role_probe.py <run_id> [<run_id> ...] [--agent my_team v1]

Per agent and game (own moves only):
  banked        food brought home
  pacman        turns spent on the enemy side
  ghost_fight   turns at home with an enemy Pacman within FIGHT steps
  ghost_free    turns at home with no enemy Pacman that close
  stuck         turns at home not further than 1 step from where it stood
                IDLE moves earlier, with no invader within FIGHT steps
  near_border   ghost_free turns within 2 steps of the border
"""

import argparse
import os
import pickle
import sys
from collections import defaultdict

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TOOLS_DIR)
sys.path.insert(0, TOOLS_DIR)
os.chdir(os.path.join(REPO_DIR, 'pacman-contest', 'src', 'contest'))

from contest.capture import GameState  # noqa: E402

import db  # noqa: E402
from analyze import RED, BLUE, MapInfo  # noqa: E402

FIGHT = 6
IDLE = 5
KEYS = ('banked', 'pacman', 'ghost_fight', 'ghost_free', 'stuck', 'near_border')


def _pos(state, i):
    p = state.get_agent_position(i)
    return int(p[0]), int(p[1])


def game_stats(rep, side):
    info = MapInfo(rep['layout'])
    state = GameState()
    state.initialize(rep['layout'], 4)
    state.data.timeleft = rep['length']
    mine = (0, 2) if side == 'red' else (1, 3)
    theirs = tuple(k for k in range(4) if k not in mine)
    home_dist = info.home_dist[RED if side == 'red' else BLUE]
    out = {k: defaultdict(int) for k in mine}
    trail = {k: [] for k in mine}
    for i, action in rep['actions']:
        prev, state = state, state.generate_successor(i, action)
        if i not in mine:
            continue
        st, before = state.data.agent_states[i], prev.data.agent_states[i]
        if before.num_carrying > 0 and st.num_carrying == 0 and not st.is_pacman \
                and st.configuration.pos != st.start.pos:
            out[i]['banked'] += before.num_carrying
        p = _pos(state, i)
        trail[i].append(p)
        if st.is_pacman:
            out[i]['pacman'] += 1
            continue
        invaders = [_pos(state, e) for e in theirs if state.data.agent_states[e].is_pacman]
        if any(info.d(p, q) <= FIGHT for q in invaders):
            out[i]['ghost_fight'] += 1
            continue
        out[i]['ghost_free'] += 1
        if home_dist.get(p, 99) <= 2:
            out[i]['near_border'] += 1
        if len(trail[i]) > IDLE and info.d(p, trail[i][-1 - IDLE]) <= 1:
            out[i]['stuck'] += 1
    return {('raider' if k == mine[0] else 'flex'): v for k, v in out.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run_ids', nargs='+')
    parser.add_argument('--agent', nargs='+', default=['my_team', 'v1'])
    args = parser.parse_args()
    con = db.connect()
    marks = ','.join('?' * len(args.run_ids))
    print('| agent | role | games | ' + ' | '.join(KEYS) + ' |\n|---|---|---|' + '---|' * len(KEYS))
    for agent in args.agent:
        rows = con.execute(f'SELECT ts.side, g.replay_path FROM team_stats ts JOIN games g USING (game_id) '
                           f'WHERE g.run_id IN ({marks}) AND ts.agent_name = ?', (*args.run_ids, agent)).fetchall()
        tot = {'raider': defaultdict(int), 'flex': defaultdict(int)}
        for r in rows:
            with open(os.path.join(REPO_DIR, r['replay_path']), 'rb') as f:
                rep = pickle.load(f)
            for role, v in game_stats(rep, r['side']).items():
                for k in KEYS:
                    tot[role][k] += v[k]
        n = max(len(rows), 1)
        for role in ('raider', 'flex'):
            print(f'| {agent} | {role} | {len(rows)} | ' + ' | '.join(f'{tot[role][k] / n:.1f}' for k in KEYS) + ' |')


if __name__ == '__main__':
    main()
