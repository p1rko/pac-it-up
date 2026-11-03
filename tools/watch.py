"""
Manual match analysis: find the moments that cost points, watch just those
clips, and keep notes next to the stats.

  python tools/watch.py queue   [--agent my_team] [--run latest] [--cause C] [--opp O] [--n 10]
  python tools/watch.py moments [--agent my_team] [--run latest] [--type death|unopposed|ghost|capsule|stall] [--n 20]
  python tools/watch.py events  <game_id>
  python tools/watch.py play    <game_id> [--from 380] [--to 450] [--delay 0.08] [--zoom 1]
  python tools/watch.py note    <game_id> --turn 412 --tag defence "what you saw"
  python tools/watch.py notes   [--tag defence] [--game G]

`queue` lists the worst losses/ties, `moments` ranks individual costly moments
(game id + turn) across a run, `events` prints one game's timeline and
`play` replays a clip in the graphics window, fast-forwarding to --from.
Turns are indices into the game's move list (0-1199, 4 per round).
"""

import argparse
import json
import os
import pickle
import sys
import time
from collections import deque

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TOOLS_DIR)
ENGINE_DIR = os.path.join(REPO_DIR, 'pacman-contest', 'src', 'contest')
sys.path.insert(0, TOOLS_DIR)

import db  # noqa: E402
from analyze import IDLE_WINDOW, UNOPPOSED_DIST  # noqa: E402
from query import table  # noqa: E402

CLUSTER_GAP = 24   # unopposed bites this close in turns count as one raid


def latest_run(con, agent):
    row = con.execute('SELECT g.run_id FROM team_stats ts JOIN games g USING (game_id) JOIN runs r '
                      'USING (run_id) WHERE ts.agent_name = ? ORDER BY r.started DESC LIMIT 1',
                      (agent,)).fetchone()
    if row is None:
        sys.exit(f'no runs with agent {agent}')
    return row[0]


def our_games(con, args):
    run = latest_run(con, args.agent) if args.run == 'latest' else args.run
    sql = ('SELECT ts.*, g.layout, g.replay_path FROM team_stats ts JOIN games g USING (game_id) '
           'WHERE g.run_id = ? AND ts.agent_name = ?')
    params = [run, args.agent]
    if getattr(args, 'opp', None):
        sql += ' AND ts.opp_name = ?'
        params.append(args.opp)
    return run, con.execute(sql, params).fetchall()


def cmd_queue(con, args):
    run, rows = our_games(con, args)
    rows = [r for r in rows if r['points'] < 3 and (not args.cause or r['loss_cause'] == args.cause)]
    rows.sort(key=lambda r: r['margin'])
    print(f'Worst games for {args.agent} in {run}:\n')
    print(table(['game_id', 'margin', 'vs', 'layout', 'side', 'cause', 'deaths/lost', 'unopposed', 'idle'],
                [(r['game_id'], f"{r['margin']:+d}", r['opp_name'], r['layout'], r['side'], r['loss_cause'],
                  f"{r['deaths']}/{r['food_lost']}", r['unopposed_food'], r['idle_attack'])
                 for r in rows[:args.n]]))


def unopposed_raids(events, side):
    """Clusters of enemy bites on our food with no guard near: (start_turn, end_turn, bites)."""
    bites = [t for t, i, s, kind, data in events
             if kind == 'eat' and s != side and data['guard_dist'] > UNOPPOSED_DIST]
    raids = []
    for t in bites:
        if raids and t - raids[-1][1] <= CLUSTER_GAP:
            raids[-1][1], raids[-1][2] = t, raids[-1][2] + 1
        else:
            raids.append([t, t, 1])
    return raids


def load_events(con, game_id):
    return [(r['turn'], r['agent_index'], r['side'], r['type'], json.loads(r['data_json']))
            for r in con.execute('SELECT * FROM events WHERE game_id = ? ORDER BY turn', (game_id,))]


def replay(replay_path):
    os.chdir(ENGINE_DIR)
    from contest.capture import GameState
    with open(os.path.join(REPO_DIR, replay_path), 'rb') as f:
        rep = pickle.load(f)
    state = GameState()
    state.initialize(rep['layout'], 4)
    state.data.timeleft = rep['length']
    return rep, state


def stalls(replay_path, side):
    """Stretches where one of our agents, as Pacman, covered <=2 cells per 10 moves."""
    rep, state = replay(replay_path)
    mine = (0, 2) if side == 'red' else (1, 3)
    recent = {i: deque(maxlen=IDLE_WINDOW) for i in mine}
    open_at, found = {}, []
    for turn, (i, action) in enumerate(rep['actions']):
        state = state.generate_successor(i, action)
        if i not in mine:
            continue
        p = state.get_agent_position(i)
        recent[i].append((int(p[0]), int(p[1])))
        stuck = state.data.agent_states[i].is_pacman and len(recent[i]) == IDLE_WINDOW and len(set(recent[i])) <= 2
        if stuck and i not in open_at:
            open_at[i] = turn
        elif not stuck and i in open_at:
            found.append((open_at.pop(i), turn, i))
    found += [(t, len(rep['actions']), i) for i, t in open_at.items()]
    return found


def cmd_moments(con, args):
    run, rows = our_games(con, args)
    moments = []   # (cost, game_id, turn, description)
    for r in rows:
        events = load_events(con, r['game_id'])
        side = r['side']
        if args.type in ('death', 'all'):
            for t, i, s, kind, d in events:
                if kind == 'death' and s == side and d['carried'] >= args.min_carried:
                    pocket = f", pocket depth {d['pocket_depth']}" if d['pocket_depth'] else ''
                    moments.append((d['carried'], r['game_id'], t,
                                    f"agent {i} died carrying {d['carried']}, {d['home_dist']} from home{pocket}"))
        if args.type in ('unopposed', 'all'):
            for start, end, bites in unopposed_raids(events, side):
                if bites >= 3:
                    moments.append((bites, r['game_id'], start, f'unopposed raid: {bites} bites, turns {start}-{end}'))
        if args.type in ('ghost', 'all'):
            for t, i, s, kind, d in events:
                if kind == 'scared_death' and s != side:
                    moments.append((2, r['game_id'], t, f"we ate scared ghost {i} (killer {d['killer']})"))
        if args.type in ('capsule', 'all'):
            for t, i, s, kind, d in events:
                if kind == 'capsule' and s == side:
                    moments.append((1, r['game_id'], t, f'agent {i} ate a capsule'))
        if args.type == 'stall':
            for start, end, i in stalls(r['replay_path'], side):
                if end - start >= 40:
                    moments.append(((end - start) / 10, r['game_id'], start,
                                    f'agent {i} stalled as Pacman, turns {start}-{end}'))
    moments.sort(key=lambda m: -m[0])
    print(f'Costliest {args.type} moments for {args.agent} in {run} (play with --from about turn-20):\n')
    print(table(['cost', 'game_id', 'turn', 'what'], [(f'{c:g}', g, t, w) for c, g, t, w in moments[:args.n]]))


def cmd_events(con, args):
    g = con.execute('SELECT * FROM games WHERE game_id = ?', (args.game_id,)).fetchone()
    if g is None:
        sys.exit(f'unknown game {args.game_id}')
    print(f"{g['red_name']} (red) vs {g['blue_name']} (blue) on {g['layout']}: {g['winner']} {g['score']:+d} "
          f"({g['end_reason']}, {g['turns']} turns)\n")
    events = load_events(con, args.game_id)
    lines = []
    for t, i, s, kind, d in events:
        if kind == 'death':
            pocket = f" pocket {d['pocket_depth']}" if d['pocket_depth'] else ''
            lines.append((t, f"{s} agent {i} DIED carrying {d['carried']} ({d['home_dist']} from home{pocket}), "
                             f"killer {d['killer']}"))
        elif kind == 'scared_death':
            lines.append((t, f"{s} agent {i} (scared ghost) eaten by {d['killer']}"))
        elif kind == 'bank' and d['amount'] >= 2:
            lines.append((t, f"{s} agent {i} banked {d['amount']}"))
        elif kind == 'capsule':
            lines.append((t, f"{s} agent {i} ate a capsule"))
    for side in ('red', 'blue'):
        for start, end, bites in unopposed_raids(events, side):
            if bites >= 3:
                lines.append((start, f"unopposed raid on {side} food: {bites} bites until turn {end}"))
    lines.sort()
    timeline = json.loads(g['timeline_json'])
    print('score every 40 turns:', ' '.join(f'{s:+d}' for s in timeline), '\n')
    for t, text in lines:
        print(f'{t:5d}  {text}')


def cmd_play(con, args):
    g = con.execute('SELECT * FROM games WHERE game_id = ?', (args.game_id,)).fetchone()
    if g is None:
        sys.exit(f'unknown game {args.game_id}')
    rep, state = replay(g['replay_path'])
    import contest.capture_graphics_display as graphics
    actions = rep['actions']
    start = max(0, min(args.start, len(actions)))
    end = min(args.end or len(actions), len(actions))
    for i, action in actions[:start]:
        state = state.generate_successor(i, action)
    graphics.FRAME_TIME = 0
    display = graphics.PacmanGraphics(g['red_name'], g['red_name'], g['blue_name'], g['blue_name'],
                                      args.zoom, 0, capture=True)
    display.initialize(state.data)
    for turn in range(start, end):
        state = state.generate_successor(*actions[turn])
        display.update(state.data)
        display.info_pane.update_message(f'turn {turn}')
        time.sleep(args.delay)
    try:
        input(f'clip {start}-{end} done, press Enter to close')
    except EOFError:
        pass
    display.finish()


def cmd_note(con, args):
    note_id = db.add_note(con, args.game_id, args.turn, args.tag, args.text)
    print(f'note {note_id} saved')


def cmd_notes(con, args):
    sql, params = 'SELECT * FROM notes WHERE 1 = 1', []
    if args.tag:
        sql += ' AND tag = ?'
        params.append(args.tag)
    if args.game:
        sql += ' AND game_id = ?'
        params.append(args.game)
    rows = con.execute(sql + ' ORDER BY note_id', params).fetchall()
    print(table(['id', 'game_id', 'turn', 'tag', 'note'],
                [(r['note_id'], r['game_id'], r['turn'], r['tag'], r['text']) for r in rows]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('queue')
    p.add_argument('--agent', default='my_team')
    p.add_argument('--run', default='latest')
    p.add_argument('--cause')
    p.add_argument('--opp')
    p.add_argument('--n', type=int, default=10)
    p = sub.add_parser('moments')
    p.add_argument('--agent', default='my_team')
    p.add_argument('--run', default='latest')
    p.add_argument('--opp')
    p.add_argument('--type', choices=['all', 'death', 'unopposed', 'ghost', 'capsule', 'stall'], default='all')
    p.add_argument('--min-carried', type=int, default=3)
    p.add_argument('--n', type=int, default=20)
    sub.add_parser('events').add_argument('game_id')
    p = sub.add_parser('play')
    p.add_argument('game_id')
    p.add_argument('--from', dest='start', type=int, default=0)
    p.add_argument('--to', dest='end', type=int)
    p.add_argument('--delay', type=float, default=0.08)
    p.add_argument('--zoom', type=float, default=1.0)
    p = sub.add_parser('note')
    p.add_argument('game_id')
    p.add_argument('text')
    p.add_argument('--turn', type=int)
    p.add_argument('--tag', default='general')
    p = sub.add_parser('notes')
    p.add_argument('--tag')
    p.add_argument('--game')
    args = parser.parse_args()
    con = db.connect()
    globals()['cmd_' + args.cmd](con, args)


if __name__ == '__main__':
    main()
