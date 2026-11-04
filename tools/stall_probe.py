"""
Stall probe: which code path is an agent in while it is stalled as Pacman?

  python tools/stall_probe.py [AGENT] [--maps 4]

Plays AGENT (default my_team.py) against the gauntlet on the first --maps train
maps, both colours, and tags every move with the SmartAgent methods it went
through (attack, reposition, go_home, defend, ...) and whether the fight search
overrode it. A move is stalled when the agent is Pacman and visited <= 2 cells
in its last IDLE_WINDOW moves (the same rule as analyze.py's idle_attack).
Stalls are grouped by the set of paths used over that window, so a flip such
as "food | go_home" shows up as one pattern. Nothing is stored in results.db.
"""

import argparse
import io
import multiprocessing as mp
import os
import random
import sys
from collections import Counter, deque
from contextlib import redirect_stderr, redirect_stdout

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TOOLS_DIR)
sys.path.insert(0, TOOLS_DIR)

from analyze import IDLE_WINDOW  # noqa: E402
from tournament import ENGINE_DIR, make_layout, map_pool, seed_for  # noqa: E402

GAUNTLET = ['strategies/dario.py', 'strategies/tracking.py', 'strategies/search.py',
            'strategies/reflex.py', 'strategies/blitz.py', 'strategies/turtle.py']
TRACED = ['defend', 'go_home', 'reposition', 'follow_crossing', 'flee']   # attack/hunt are implied by "food"
STYLE_CHECKPOINTS = (60, 150, 299)   # own turns at which the enemies' share of turns as Pacman is read


def instrument(agent):
    """Wrap the agent's methods so every move logs the paths it took."""
    for name in TRACED:
        orig = getattr(agent, name, None)
        if orig is None:   # older versions lack some methods
            continue

        def traced(*args, _orig=orig, _name=name, **kwargs):
            agent.probe_tags.append(_name)
            return _orig(*args, **kwargs)
        setattr(agent, name, traced)
    orig_finish, orig_choose = agent.finish, agent.choose_action

    def finish(game_state, action):
        new = orig_finish(game_state, action)
        if new != action:
            agent.probe_tags.append('search')
        return new

    def choose_action(game_state):
        agent.probe_tags = []
        action = orig_choose(game_state)
        st = game_state.get_agent_state(agent.index)
        pos = st.get_position()
        recent.append(pos)
        stuck = st.is_pacman and len(recent) == IDLE_WINDOW and len(set(recent)) <= 2
        agent.probe_log.append(dict(stuck=stuck, path='>'.join(agent.probe_tags) or 'food',
                                    carry=st.num_carrying, home_dist=agent.home_distance(pos)))
        turns = len(agent.observation_history)
        if turns in STYLE_CHECKPOINTS:
            invaded = agent.team()['invader_turns'].values()
            agent.probe_shares[turns] = sorted(n / (2.0 * turns) for n in invaded)
        return action

    recent = deque(maxlen=IDLE_WINDOW)
    agent.probe_log = []
    agent.probe_shares = {}
    agent.finish, agent.choose_action = finish, choose_action


def play(task):
    os.chdir(ENGINE_DIR)
    import contest.capture as capture
    from contest.text_display import NullGraphics
    random.seed(task['seed'])
    with open(os.devnull, 'w') as devnull, redirect_stdout(devnull), redirect_stderr(io.StringIO()):
        lay = make_layout(task['layout'])
        ours = capture.load_agents(task['red'], task['agent'], {})
        theirs = capture.load_agents(not task['red'], task['opp'], {})
        red, blue = (ours, theirs) if task['red'] else (theirs, ours)
        for a in ours:
            instrument(a)
        g = capture.CaptureRules(quiet=True).new_game(lay, [red[0], blue[0], red[1], blue[1]],
                                                      NullGraphics(), 1200, True, True)
        g.run()
    return dict(opp=os.path.basename(task['opp']), shares=ours[0].probe_shares,
                logs=[(type(a).__name__, a.probe_log) for a in ours])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('agent', nargs='?', default='my_team.py')
    parser.add_argument('--maps', type=int, default=4)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    agent = os.path.abspath(args.agent)
    tasks = [dict(agent=agent, opp=os.path.join(REPO_DIR, o), layout=m, red=red, seed=seed_for(m, o, str(red)))
             for m in map_pool('train')[:args.maps] for o in GAUNTLET for red in (True, False)]
    with mp.get_context('spawn').Pool(args.workers, maxtasksperchild=1) as pool:
        games = pool.map(play, tasks)

    patterns, flip_home_dist = Counter(), Counter()
    for game in games:
        for role, log in game['logs']:
            for k, move in enumerate(log):
                if not move['stuck']:
                    continue
                paths = sorted({m['path'] for m in log[k - IDLE_WINDOW + 1:k + 1]})
                patterns[f"{role}: {' | '.join(paths)}"] += 1
                if 'food' in paths and 'go_home' in paths:
                    flip_home_dist[move['home_dist']] += 1
    stalled = sum(patterns.values())
    print(f'{len(games)} games, {stalled} stalled moves ({stalled / len(games):.1f} per game)\n')
    print('paths used over the stalled window:')
    for pattern, n in patterns.most_common(15):
        print(f'  {n:5d} {n / stalled:6.1%}  {pattern}')
    print('\nfood <-> go_home flips by distance from home:', sorted(flip_home_dist.items()))

    # Opponent style: share of turns each enemy spent as Pacman, the less
    # attacking enemy first. "range" is over games, to see how clean a split is.
    print('\nenemy share of turns as Pacman (less attacking / more attacking enemy):')
    for opp in sorted({g['opp'] for g in games}):
        cells = []
        for t in STYLE_CHECKPOINTS:
            vals = [g['shares'][t] for g in games if g['opp'] == opp and t in g['shares']]
            if vals:
                low = [v[0] for v in vals]
                high = sum(v[1] for v in vals) / len(vals)
                cells.append(f'turn {t}: {sum(low) / len(low):.2f} (range {min(low):.2f}-{max(low):.2f}) / {high:.2f}')
        print(f'  {opp:12s} ' + ' | '.join(cells))


if __name__ == '__main__':
    main()
