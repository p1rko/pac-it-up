"""
How our ghosts' chases end, computed by replaying stored games.

  python tools/chase_probe.py <run_id> [--agent my_team v1] [--late] [--examples 5]

A chase starts when one of our ghosts (not scared) is within START_DIST steps
of an enemy Pacman, and lasts while that enemy is still a Pacman within
KEEP_DIST of the same ghost. It ends as one of:

  caught     the invader was eaten (by anyone of ours)
  capsule    the invader (or its mate) ate a capsule, so our ghost became scared
  crossed    the invader made it back to its own side (banked or empty-handed)
  outran     the invader got more than KEEP_DIST away, still on our side
  ghost_left our ghost became a Pacman itself (went attacking)
  game_over  the game ended mid-chase

For each chase we also record whether, at the start, our ghost was nearer than
the invader to the invader's closest crossing ("ahead of exit"), whether the
invader sat in a dead-end pocket, and whether our second ghost joined in.
--late keeps only chases that start in the second half of the game.
"""

import argparse
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
from analyze import RED, BLUE, MapInfo, team_of  # noqa: E402

START_DIST = 3
KEEP_DIST = 6


def _pos(state, i):
    p = state.get_agent_position(i)
    return int(p[0]), int(p[1])


def chokes(info, cell, targets, cache):
    """Cells every route from `cell` to `targets` must pass through, nearest first."""
    if cell in cache:
        return cache[cell]
    parent, q, end = {cell: None}, [cell], None
    for c in q:
        if c in targets:
            end = c
            break
        for n in info.nbrs[c]:
            if n not in parent:
                parent[n] = c
                q.append(n)
    path = []
    while end is not None and end != cell:
        path.append(end)
        end = parent[end]
    path.reverse()
    result = []
    for x in path:
        seen, q, ok = {cell, x}, [cell], False
        for c in q:
            if c in targets:
                ok = True
                break
            for n in info.nbrs[c]:
                if n not in seen:
                    seen.add(n)
                    q.append(n)
        if not ok:
            result.append(x)
    cache[cell] = result
    return result


def chases_in_game(rep, side, late_only):
    info = MapInfo(rep['layout'])
    state = GameState()
    state.initialize(rep['layout'], 4)
    state.data.timeleft = rep['length']
    mine = (0, 2) if side == 'red' else (1, 3)
    theirs = tuple(k for k in range(4) if k not in mine)
    starts = {i: tuple(int(c) for c in state.data.agent_states[i].start.pos) for i in range(4)}
    enemy_border = info.border[BLUE if side == 'red' else RED]   # cells the invader exits onto
    our_border = set(info.border[RED if side == 'red' else BLUE])  # cells it must pass to get out
    choke_cache = {}
    n_moves = len(rep['actions'])

    active = {}     # (ghost, enemy) -> chase record
    done = []
    for turn, (i, action) in enumerate(rep['actions']):
        prev, state = state, state.generate_successor(i, action)
        st = state.data.agent_states
        # update / close open chases
        for (g, e), c in list(active.items()):
            ep, gp = _pos(state, e), _pos(state, g)
            c['steps'] += 1
            if i == g:
                c['ghost_moves'] += 1
                d_before = info.d(_pos(prev, g), _pos(prev, e))
                c['ghost_closer'] += info.d(gp, _pos(prev, e)) < d_before
            if any(st[k].scared_timer > 0 for k in mine) and not c['scared_at_start']:
                c['end'] = 'capsule'
            elif ep == starts[e] and _pos(prev, e) != starts[e]:
                c['end'] = 'caught'
            elif not st[e].is_pacman:
                c['end'] = 'crossed'
                c['banked'] = prev.data.agent_states[e].num_carrying
            elif st[g].is_pacman:
                c['end'] = 'ghost_left'
            elif info.d(gp, ep) > KEEP_DIST:
                c['end'] = 'outran'
            else:
                other = [k for k in mine if k != g][0]
                if not st[other].is_pacman and info.d(_pos(state, other), ep) <= KEEP_DIST:
                    c['two_ghosts'] = True
                c['min_d'] = min(c['min_d'], info.d(gp, ep))
                continue
            c['end_turn'] = turn
            c['carry_end'] = st[e].num_carrying if c['end'] != 'crossed' else c['banked']
            done.append(c)
            del active[(g, e)]
        # open new chases
        if late_only and turn < n_moves // 2:
            continue
        for g in mine:
            if st[g].is_pacman or st[g].scared_timer > 0:
                continue
            for e in theirs:
                if (g, e) in active or not st[e].is_pacman:
                    continue
                if any((k, e) in active for k in mine):
                    continue   # one chase per invader
                gp, ep = _pos(state, g), _pos(state, e)
                if info.d(gp, ep) > START_DIST:
                    continue
                exit_cell = min(enemy_border, key=lambda b: info.d(ep, b))
                caps = [c for c in (state.get_red_capsules() if side == 'red' else state.get_blue_capsules())]
                cap_e = min((info.d(ep, c) for c in caps), default=None)
                cap_g = min((info.d(gp, c) for c in caps), default=None)
                trap = [x for x in chokes(info, ep, our_border, choke_cache) if info.d(gp, x) < info.d(ep, x)]
                active[(g, e)] = {
                    'turn': turn, 'role': 'raider' if g == mine[0] else 'flex',
                    'start_d': info.d(gp, ep), 'min_d': info.d(gp, ep),
                    'carry_start': st[e].num_carrying,
                    'ahead_of_exit': info.d(gp, exit_cell) < info.d(ep, exit_cell),
                    'exit_gap': info.d(ep, exit_cell) - info.d(gp, exit_cell),
                    'pocket': info.pocket_depth.get(ep, 0) > 0,
                    'cap_e': cap_e, 'cap_closer': cap_e is not None and cap_g < cap_e,
                    'trappable': bool(trap), 'choke_d': info.d(ep, trap[0]) if trap else None,
                    'scared_at_start': any(st[k].scared_timer > 0 for k in mine),
                    'two_ghosts': False, 'steps': 0, 'ghost_moves': 0, 'ghost_closer': 0,
                    'banked': 0,
                }
    for c in active.values():
        c['end'] = 'game_over'
        c['carry_end'] = 0
        done.append(c)
    return done


def report(run_id, agent, late_only, examples):
    con = db.connect()
    rows = con.execute('SELECT ts.side, ts.opp_name, g.game_id, g.replay_path FROM team_stats ts '
                       'JOIN games g USING (game_id) WHERE g.run_id = ? AND ts.agent_name = ?',
                       (run_id, agent)).fetchall()
    all_c = []
    for r in rows:
        with open(os.path.join(REPO_DIR, r['replay_path']), 'rb') as f:
            rep = pickle.load(f)
        for c in chases_in_game(rep, r['side'], late_only):
            c['opp'], c['game'] = r['opp_name'], r['game_id']
            all_c.append(c)
    n = max(len(all_c), 1)
    print(f'\n## {agent}: {len(all_c)} chases in {len(rows)} games{" (second half)" if late_only else ""}\n')
    ends = Counter(c['end'] for c in all_c)
    print('| end | chases | share | invader carry at end (mean) |\n|---|---|---|---|')
    for end, k in ends.most_common():
        carry = [c['carry_end'] for c in all_c if c['end'] == end]
        print(f'| {end} | {k} | {100 * k / n:.0f}% | {sum(carry) / max(len(carry), 1):.1f} |')

    def split(title, key):
        print(f'\n| {title} | chases | caught | crossed | outran | capsule | ghost_left |\n|---|---|---|---|---|---|---|')
        groups = defaultdict(list)
        for c in all_c:
            groups[key(c)].append(c)
        for g, cs in sorted(groups.items(), key=lambda kv: str(kv[0])):
            m = len(cs)
            cnt = Counter(c['end'] for c in cs)
            print(f'| {g} | {m} | ' + ' | '.join(f"{100 * cnt[e] / m:.0f}%" for e in
                                                ('caught', 'crossed', 'outran', 'capsule', 'ghost_left')) + ' |')
    split('ahead of exit at start', lambda c: c['ahead_of_exit'])
    split('invader in pocket at start', lambda c: c['pocket'])
    split('trappable (we reach a choke first)', lambda c: c['trappable'])
    big = [c for c in all_c if c['end'] in ('crossed', 'capsule', 'outran', 'game_over', 'ghost_left') and c['carry_end'] >= 3]
    capc = [c for c in all_c if c['end'] == 'capsule']
    print(f"\ncapsule endings: {len(capc)}; invader within 5 of a capsule at start: {sum(c['cap_e'] is not None and c['cap_e'] <= 5 for c in capc)}; "
          f"our ghost nearer the capsule than the invader at start: {sum(c['cap_closer'] for c in capc)}")
    allcap = [c for c in all_c if c['cap_e'] is not None and c['cap_e'] <= 5]
    print(f"all chases starting with the invader within 5 of a capsule: {len(allcap)}, end in capsule: {sum(c['end'] == 'capsule' for c in allcap)}, "
          f"of those we were nearer the capsule: {sum(c['end'] == 'capsule' and c['cap_closer'] for c in allcap)}")
    for end in ('outran', 'ghost_left', 'capsule', 'crossed'):
        sub = [c for c in all_c if c['end'] == end]
        mv = sum(c['ghost_moves'] for c in sub); cl = sum(c['ghost_closer'] for c in sub)
        print(f"  {end}: ghost moves closing distance {100 * cl / max(mv, 1):.0f}%, by role {Counter(c['role'] for c in sub)}, mean carry start {sum(c['carry_start'] for c in sub) / max(len(sub), 1):.1f}")
    tr = [c for c in big if c['trappable']]
    print(f"\nchases ending with the invader free and carrying 3+: {len(big)}, food {sum(c['carry_end'] for c in big)}; "
          f"trappable at start: {len(tr)} ({100 * len(tr) / max(len(big), 1):.0f}%), food {sum(c['carry_end'] for c in tr)}")
    for end in ('crossed', 'capsule', 'outran', 'game_over', 'ghost_left'):
        sub = [c for c in big if c['end'] == end]
        print(f"  {end}: {len(sub)}, trappable {sum(c['trappable'] for c in sub)}")
    split('second ghost joined', lambda c: c['two_ghosts'])
    split('our chaser', lambda c: c['role'])
    split('opponent', lambda c: c['opp'])
    moves = sum(c['ghost_moves'] for c in all_c)
    closer = sum(c['ghost_closer'] for c in all_c)
    print(f'\nghost moves that closed distance: {100 * closer / max(moves, 1):.0f}% of {moves}')
    if examples:
        bad = sorted((c for c in all_c if c['end'] in ('crossed', 'outran') and c['trappable']),
                     key=lambda c: -c['carry_end'])[:examples]
        print('\nescapes although we could reach a choke first (biggest carry first):')
        for c in bad:
            print(f"  {c['game']} turns {c['turn']}-{c['end_turn']} vs {c['opp']}: {c['role']} "
                  f"start_d={c['start_d']} choke_d={c['choke_d']} pocket={c['pocket']} -> {c['end']} "
                  f"carry {c['carry_start']}->{c['carry_end']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run_id')
    parser.add_argument('--agent', nargs='+', default=['my_team'])
    parser.add_argument('--late', action='store_true')
    parser.add_argument('--examples', type=int, default=0)
    args = parser.parse_args()
    for agent in args.agent:
        report(args.run_id, agent, args.late, args.examples)


if __name__ == '__main__':
    main()
