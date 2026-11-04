"""
Raid probe: what are our agents doing while an enemy invader carries food?

  python tools/raid_probe.py [AGENT] [--maps 3] [--pool holdout]

Plays AGENT (default my_team.py) against the one-attacker gauntlet teams
(dario, tracking, search, reflex) on the first --maps maps, both colours. On
every move of ours while a real enemy invader carries food, it logs where our
agent is (home / over there), what it does (defend, hunt, home_hunt, attack)
and, when attacking, why it didn't defend (carrying, scared, Flex budget used
up, no trigger). It also measures how far our belief about an unseen invader is
from its true cell, and our true distance to it. Nothing is stored in results.db.
"""

import argparse
import io
import multiprocessing as mp
import os
import random
import sys
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TOOLS_DIR)
sys.path.insert(0, TOOLS_DIR)

from tournament import ENGINE_DIR, make_layout, map_pool, seed_for  # noqa: E402

OPPONENTS = ['strategies/dario.py', 'strategies/tracking.py', 'strategies/search.py', 'strategies/reflex.py']
TRACED = ['defend', 'hunt_nearby_invader', 'home_hunt']   # anything else is "attack"


def instrument(agent, game):
    """Wrap the agent so every move during an enemy raid is logged."""
    for name in TRACED:
        orig = getattr(agent, name, None)
        if orig is None:   # older versions lack home_hunt
            continue

        def traced(*args, _orig=orig, _name=name, **kwargs):
            result = _orig(*args, **kwargs)
            if result is not None:
                agent.probe_tags.append(_name)
            return result
        setattr(agent, name, traced)
    orig_choose = agent.choose_action

    def choose_action(game_state):
        agent.probe_tags = []
        action = orig_choose(game_state)
        real = game['g'].state.data.agent_states
        raids = [e for e in agent.get_opponents(game_state) if real[e].is_pacman and real[e].num_carrying > 0]
        if not raids:
            return action
        e = max(raids, key=lambda i: real[i].num_carrying)
        true_pos = tuple(int(v) for v in real[e].configuration.pos)
        me = real[agent.index]
        mode = next((t for t in ('home_hunt', 'defend', 'hunt_nearby_invader') if t in agent.probe_tags), 'attack')
        if mode == 'attack':
            if me.num_carrying > 0:
                mode = 'attack (carrying)'
            elif me.scared_timer > 0:
                mode = 'attack (scared)'
            elif hasattr(agent, 'defend_turns') and \
                    agent.defend_turns >= agent.FREE_DEFENCE + agent.TURNS_PER_CATCH * agent.catches:
                mode = 'attack (budget used up)'
            else:
                mode = 'attack (no trigger)'
        my_pos = game_state.get_agent_position(agent.index)
        unseen_err = None if game_state.get_agent_position(e) is not None else \
            agent.dist(agent.most_likely(e), true_pos)
        agent.probe_log.append(dict(band='1-3' if real[e].num_carrying < 4 else '4+',
                                    where='over there' if me.is_pacman else 'home', mode=mode,
                                    belief_err=unseen_err, dist=agent.dist(my_pos, true_pos)))
        return action

    agent.probe_log = []
    agent.choose_action = choose_action


def play(task):
    os.chdir(ENGINE_DIR)
    import contest.capture as capture
    from contest.text_display import NullGraphics
    random.seed(task['seed'])
    game = {}
    with open(os.devnull, 'w') as devnull, redirect_stdout(devnull), redirect_stderr(io.StringIO()):
        lay = make_layout(task['layout'])
        ours = capture.load_agents(task['red'], task['agent'], {})
        theirs = capture.load_agents(not task['red'], task['opp'], {})
        red, blue = (ours, theirs) if task['red'] else (theirs, ours)
        for a in ours:
            instrument(a, game)
        game['g'] = capture.CaptureRules(quiet=True).new_game(lay, [red[0], blue[0], red[1], blue[1]],
                                                              NullGraphics(), 1200, True, True)
        game['g'].run()
    return [(type(a).__name__, a.probe_log) for a in ours]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('agent', nargs='?', default='my_team.py')
    parser.add_argument('--maps', type=int, default=3)
    parser.add_argument('--pool', choices=['train', 'holdout'], default='holdout')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    agent = os.path.abspath(args.agent)
    tasks = [dict(agent=agent, opp=os.path.join(REPO_DIR, o), layout=m, red=red, seed=seed_for(m, o, str(red)))
             for m in map_pool(args.pool)[:args.maps] for o in OPPONENTS for red in (True, False)]
    with mp.get_context('spawn').Pool(args.workers, maxtasksperchild=1) as pool:
        games = pool.map(play, tasks)

    modes, errors, dists = defaultdict(Counter), defaultdict(list), defaultdict(list)
    for game in games:
        for role, log in game:
            for m in log:
                modes[(role, m['band'])][f"{m['where']}: {m['mode']}"] += 1
                if m['belief_err'] is not None:
                    errors[m['band']].append(m['belief_err'])
                dists[(role, m['mode'].split(' ')[0])].append(m['dist'])
    median = lambda v: sorted(v)[len(v) // 2] if v else '-'
    print(f'{len(games)} games\n')
    for key in sorted(modes):
        total = sum(modes[key].values())
        print(f'{key[0]}, invader carrying {key[1]}: {total} moves')
        for mode, n in modes[key].most_common():
            print(f'  {n / total:5.0%}  {mode}')
    print()
    for band in sorted(errors):
        v = sorted(errors[band])
        print(f'belief error for an unseen invader carrying {band}: median {median(v)}, p75 {v[3 * len(v) // 4]}')
    for key in sorted(dists):
        print(f'true distance to the invader, {key[0]} {key[1]}: median {median(dists[key])}')


if __name__ == '__main__':
    main()
