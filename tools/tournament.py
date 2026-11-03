"""
Parallel match runner. Every game is analysed (tools/analyze.py) and stored in
tools/results.db; replays go to tools/replays/, reports to tools/reports/.

Run from the repo root with the venv python:
  python tools/tournament.py rr my_team.py strategies/dario.py baseline_team --maps 6
  python tools/tournament.py gauntlet my_team.py --vs strategies/dario.py baseline_team --maps 10
  python tools/tournament.py ab my_team.py strategies/history/v0.py --vs strategies/dario.py --maps 10

Agents are paths (or `baseline_team`), optionally labelled as `label=path`.
Each (map, pairing) is played with both colour assignments and a seed derived
from the map and the opponent slot, so A/B runs see identical conditions.
"""

import argparse
import io
import itertools
import multiprocessing as mp
import os
import pickle
import random
import subprocess
import sys
import time
import zlib
from contextlib import redirect_stderr, redirect_stdout

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TOOLS_DIR)
ENGINE_DIR = os.path.join(REPO_DIR, 'pacman-contest', 'src', 'contest')
REPLAY_DIR = os.path.join(TOOLS_DIR, 'replays')
sys.path.insert(0, TOOLS_DIR)

import db  # noqa: E402

FIXED_LAYOUTS = ['defaultCapture', 'alleyCapture', 'bloxCapture', 'crowdedCapture', 'distantCapture',
                 'fastCapture', 'jumboCapture', 'mediumCapture', 'officeCapture', 'strategicCapture']
TRAIN_SEEDS = random.Random(1).sample(range(1, 10 ** 6), 30)
HOLDOUT_SEEDS = random.Random(2).sample(range(10 ** 6, 2 * 10 ** 6), 40)


def map_pool(name):
    """Train interleaves fixed layouts with random seeds so any prefix mixes both."""
    if name == 'holdout':
        return [f'RANDOM{s}' for s in HOLDOUT_SEEDS]
    rand = [f'RANDOM{s}' for s in TRAIN_SEEDS]
    pool = []
    for k in range(max(len(FIXED_LAYOUTS), len(rand))):
        if k < len(rand):
            pool.append(rand[k])
        if k < len(FIXED_LAYOUTS):
            pool.append(FIXED_LAYOUTS[k])
    return pool


def parse_agent(spec):
    label, _, path = spec.rpartition('=')
    if path == 'baseline_team':
        path = os.path.join(ENGINE_DIR, 'baseline_team.py')
    path = os.path.abspath(path)
    if not os.path.exists(path):
        sys.exit(f'agent not found: {path}')
    return dict(name=label or os.path.splitext(os.path.basename(path))[0], path=path, hash=db.file_hash(path))


def make_layout(name):
    import contest.capture as capture
    import contest.layout as layout
    if name.startswith('RANDOM'):
        lname, text = capture.random_layout(seed=int(name[6:]))
        return layout.Layout(layout_name=lname, layout_text=text.split('\n'))
    return layout.get_layout(name)


def _timed(fn, times):
    def wrapper(*args):
        t = time.perf_counter()
        result = fn(*args)
        times.append(time.perf_counter() - t)
        return result
    return wrapper


def play(task):
    """Worker: plays one game, analyses it and returns a plain result dict."""
    os.chdir(ENGINE_DIR)
    import contest.capture as capture
    from contest.text_display import NullGraphics
    from analyze import analyze_game

    random.seed(task['seed'])
    err = io.StringIO()
    move_times = [[] for _ in range(4)]
    init_times = [[] for _ in range(4)]
    crashed = []
    start = time.time()
    with open(os.devnull, 'w') as devnull, redirect_stdout(devnull), redirect_stderr(err):
        lay = make_layout(task['layout'])
        red = capture.load_agents(True, task['red']['path'], {})
        blue = capture.load_agents(False, task['blue']['path'], {})
        agents = [red[0], blue[0], red[1], blue[1]]
        for i, a in enumerate(agents):
            if a is not None:
                a.get_action = _timed(a.get_action, move_times[i])
                a.register_initial_state = _timed(a.register_initial_state, init_times[i])
        rules = capture.CaptureRules(quiet=True)
        g = rules.new_game(lay, agents, NullGraphics(), task['length'], True, True)
        orig_crash = g._agent_crash

        def record_crash(index, quiet=False):
            crashed.append(index)
            orig_crash(index, quiet)
        g._agent_crash = record_crash
        g.run()
    wall = time.time() - start

    result = analyze_game(lay, g.move_history, task['length'], crashed[0] if crashed else None)
    score = g.state.data.score
    winner = 'red' if score > 0 else 'blue' if score < 0 else 'tie'
    points = {'red': 3 if winner == 'red' else 1 if winner == 'tie' else 0,
              'blue': 3 if winner == 'blue' else 1 if winner == 'tie' else 0}

    timing = {}
    for side, idx in (('red', (0, 2)), ('blue', (1, 3))):
        ts = sorted(t for i in idx for t in move_times[i])
        timing[side] = dict(max=ts[-1] if ts else 0.0, p99=ts[int(0.99 * (len(ts) - 1))] if ts else 0.0,
                            init=max((t for i in idx for t in init_times[i]), default=0.0),
                            warnings=sum(g.total_agent_time_warnings[i] for i in idx))

    replay_path = os.path.join(REPLAY_DIR, task['game_id'] + '.replay')
    import contest.game as game
    with open(replay_path, 'wb') as f:
        pickle.dump({'layout': lay, 'agents': [game.Agent() for _ in agents], 'actions': g.move_history,
                     'length': task['length'], 'red_team_name': task['red']['name'],
                     'blue_team_name': task['blue']['name']}, f)

    return dict(game_id=task['game_id'], red=task['red'], blue=task['blue'], layout=task['layout'],
                seed=task['seed'], score=score, winner=winner, points=points,
                end_reason=result['end_reason'], turns=len(g.move_history), wall_s=wall,
                timeline=result['timeline'], stats=result['teams'], events=result['events'],
                timing=timing, replay_path=os.path.relpath(replay_path, REPO_DIR),
                stderr_tail=err.getvalue()[-2000:])


def seed_for(*parts):
    return zlib.crc32('|'.join(parts).encode())


def pair_tasks(a, b, layouts, slot_key=None):
    """Both colour assignments of a vs b on each layout."""
    tasks = []
    for lay in layouts:
        for red, blue in ((a, b), (b, a)):
            key = slot_key(red, blue) if slot_key else f'{red["name"]}|{blue["name"]}'
            tasks.append(dict(red=red, blue=blue, layout=lay, seed=seed_for(lay, key)))
    return tasks


def schedule(args):
    pool = map_pool(args.pool)
    if args.mode == 'rr':
        agents = [parse_agent(s) for s in args.agents]
        tasks = []
        for k, (a, b) in enumerate(itertools.combinations(agents, 2)):
            # rotate through the pool so different pairs cover different maps
            layouts = [pool[(k * args.maps + m) % len(pool)] for m in range(args.maps)]
            tasks += pair_tasks(a, b, layouts)
        return agents, tasks
    subjects = [parse_agent(s) for s in args.agents]
    opponents = [parse_agent(s) for s in args.vs]
    layouts = pool[args.offset:args.offset + args.maps]

    def slot(red, blue):
        # key on the opponent and its colour only, so every subject gets the same seeds
        return f'opp={blue["name"]}|opp_side=blue' if red in subjects else f'opp={red["name"]}|opp_side=red'
    tasks = []
    for s in subjects:
        for o in opponents:
            tasks += pair_tasks(s, o, layouts, slot)
    return subjects + opponents, tasks


def git_commit():
    try:
        return subprocess.check_output(['git', '-C', REPO_DIR, 'rev-parse', '--short', 'HEAD'],
                                       text=True).strip()
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=['rr', 'gauntlet', 'ab'])
    parser.add_argument('agents', nargs='+', help='rr: all agents; gauntlet: candidate; ab: new old')
    parser.add_argument('--vs', nargs='*', default=[], help='opponents (gauntlet / ab)')
    parser.add_argument('--maps', type=int, default=6, help='layouts per pairing (x2 colours)')
    parser.add_argument('--offset', type=int, default=0, help='start index into the map pool')
    parser.add_argument('--pool', choices=['train', 'holdout'], default='train')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--length', type=int, default=1200)
    parser.add_argument('--purpose', default='')
    args = parser.parse_args()
    if args.mode == 'ab' and len(args.agents) != 2:
        sys.exit('ab needs exactly two agents: new old')

    agents, tasks = schedule(args)
    run_id = time.strftime('%Y%m%d-%H%M%S') + '-' + args.mode
    for k, t in enumerate(tasks):
        t['game_id'] = f'{run_id}-{k:04d}'
        t['length'] = args.length
    os.makedirs(REPLAY_DIR, exist_ok=True)

    con = db.connect()
    for a in agents:
        db.register_version(con, a['hash'], a['name'], os.path.relpath(a['path'], REPO_DIR))
    db.insert_run(con, run_id, git_commit(), args.mode, args.purpose, args.pool,
                  dict(agents=[f"{a['name']}@{a['hash']}" for a in agents], maps=args.maps,
                       offset=args.offset, games=len(tasks)))

    print(f'run {run_id}: {len(tasks)} games on {args.workers} workers', flush=True)
    start = time.time()
    done = 0
    ctx = mp.get_context('spawn')
    with ctx.Pool(args.workers, maxtasksperchild=1) as workers:
        for r in workers.imap_unordered(play, tasks):
            db.insert_game(con, run_id, r)
            done += 1
            flag = ' CRASH' if r['end_reason'] == 'crash' else ''
            warn = r['timing']['red']['warnings'] + r['timing']['blue']['warnings']
            flag += f' WARN×{warn}' if warn else ''
            print(f'[{done}/{len(tasks)}] {r["red"]["name"]} vs {r["blue"]["name"]} on {r["layout"]}: '
                  f'{r["winner"]} {r["score"]:+d} ({r["end_reason"]}){flag}', flush=True)
    print(f'finished in {(time.time() - start) / 60:.1f} min')

    import query
    report = query.report(con, run_id)
    os.makedirs(os.path.join(TOOLS_DIR, 'reports'), exist_ok=True)
    path = os.path.join(TOOLS_DIR, 'reports', run_id + '.md')
    with open(path, 'w') as f:
        f.write(report)
    print(report)
    print(f'report: {os.path.relpath(path, REPO_DIR)}')


if __name__ == '__main__':
    main()
