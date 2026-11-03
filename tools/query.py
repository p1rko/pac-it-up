"""
Reports over tools/results.db.

  python tools/query.py report <run_id|latest>      # markdown report for one run
  python tools/query.py progress [--agent my_team]  # points/game per version over time
  python tools/query.py sql "SELECT ..."            # ad-hoc query
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

PROFILE_COLUMNS = ['banked', 'deaths', 'food_lost', 'death_pocket', 'kills', 'food_denied',
                   'invader_food_banked', 'unopposed_food', 'capsule_food_conceded', 'scared_kills',
                   'idle_attack', 'timeout_carry']


def label(name, agent_hash):
    return f'{name}@{agent_hash[:7]}'


def table(headers, rows):
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)]
    out += ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows]
    return '\n'.join(out) + '\n'


def stats_rows(con, run_id):
    return con.execute('SELECT ts.*, g.layout, g.end_reason, g.replay_path FROM team_stats ts '
                       'JOIN games g USING (game_id) WHERE g.run_id = ?', (run_id,)).fetchall()


def standings(rows):
    agg = defaultdict(lambda: dict(n=0, w=0, t=0, l=0, pts=0, bal=0))
    for r in rows:
        a = agg[label(r['agent_name'], r['agent_hash'])]
        a['n'] += 1
        a['pts'] += r['points']
        a['bal'] += r['margin']
        a['w' if r['points'] == 3 else 't' if r['points'] == 1 else 'l'] += 1
    order = sorted(agg.items(), key=lambda kv: -kv[1]['pts'] / kv[1]['n'])
    return table(['agent', 'games', 'W-T-L', 'points/game', 'avg margin'],
                 [(k, a['n'], f"{a['w']}-{a['t']}-{a['l']}", f"{a['pts'] / a['n']:.2f}",
                   f"{a['bal'] / a['n']:+.1f}") for k, a in order]), [k for k, _ in order]


def matrix(rows, order):
    cell = defaultdict(list)
    for r in rows:
        cell[(label(r['agent_name'], r['agent_hash']), label(r['opp_name'], r['opp_hash']))].append(r['points'])
    short = [o.split('@')[0] for o in order]
    body = []
    for a, sa in zip(order, short):
        line = [sa]
        for b in order:
            v = cell.get((a, b))
            line.append(f'{sum(v) / len(v):.2f}' if v else '—')
        body.append(line)
    return table(['points/game (row vs col)'] + short, body)


def profile(rows, order):
    agg = defaultdict(lambda: defaultdict(float))
    n = defaultdict(int)
    for r in rows:
        k = label(r['agent_name'], r['agent_hash'])
        n[k] += 1
        for c in PROFILE_COLUMNS:
            agg[k][c] += r[c] or 0
    return table(['agent'] + PROFILE_COLUMNS,
                 [[k.split('@')[0]] + [f'{agg[k][c] / n[k]:.1f}' for c in PROFILE_COLUMNS] for k in order])


def causes(rows, order):
    agg = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r['points'] < 3:
            agg[label(r['agent_name'], r['agent_hash'])][r['loss_cause']] += 1
    kinds = sorted({c for v in agg.values() for c in v})
    return table(['agent (losses+ties)'] + kinds,
                 [[k.split('@')[0]] + [agg[k].get(c, 0) for c in kinds] for k in order if k in agg])


def timing(rows, order):
    agg = defaultdict(lambda: dict(max=0.0, p99=0.0, init=0.0, warn=0, crash=0))
    for r in rows:
        a = agg[label(r['agent_name'], r['agent_hash'])]
        a['max'] = max(a['max'], r['max_move_s'])
        a['p99'] = max(a['p99'], r['p99_move_s'])
        a['init'] = max(a['init'], r['init_s'])
        a['warn'] += r['warnings']
        a['crash'] += r['crashed']
    return table(['agent', 'max move s', 'worst p99 s', 'max init s', 'warnings', 'crashes'],
                 [(k.split('@')[0], f"{agg[k]['max']:.2f}", f"{agg[k]['p99']:.2f}", f"{agg[k]['init']:.1f}",
                   agg[k]['warn'], agg[k]['crash']) for k in order])


def worst(rows, agent_label, n=10):
    mine = [r for r in rows if label(r['agent_name'], r['agent_hash']) == agent_label and r['points'] < 3]
    mine.sort(key=lambda r: r['margin'])
    return table(['margin', 'vs', 'layout', 'side', 'cause', 'deaths/lost', 'inv banked', 'replay'],
                 [(f"{r['margin']:+d}", r['opp_name'], r['layout'], r['side'], r['loss_cause'],
                   f"{r['deaths']}/{r['food_lost']}", r['invader_food_banked'], r['replay_path'])
                  for r in mine[:n]])


def paired(con, run_id):
    """A/B: points(new) - points(old) on identical (opponent, layout, colour) slots."""
    params = json.loads(con.execute('SELECT params_json FROM runs WHERE run_id = ?', (run_id,)).fetchone()[0])
    new, old = [a.split('@')[1] for a in params['agents'][:2]]
    pts = defaultdict(dict)
    for r in stats_rows(con, run_id):
        if r['agent_hash'] in (new, old):
            pts[(r['opp_name'], r['layout'], r['side'])][r['agent_hash']] = r['points']
    by_opp = defaultdict(list)
    for (opp, _, _), v in pts.items():
        if new in v and old in v:
            by_opp[opp].append(v[new] - v[old])

    def summary(d):
        m = sum(d) / len(d)
        sd = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1)) if len(d) > 1 else 0.0
        return m, sd / math.sqrt(len(d))
    rows = []
    for opp, d in sorted(by_opp.items()):
        m, se = summary(d)
        rows.append((opp, len(d), f'{m:+.2f}', f'{se:.2f}'))
    alld = [x for d in by_opp.values() for x in d]
    m, se = summary(alld) if alld else (0.0, 0.0)
    rows.append(('**all**', len(alld), f'**{m:+.2f}**', f'{se:.2f}'))
    return table(['vs', 'pairs', 'Δ points/game (new−old)', 'SE'], rows), m, se


def report(con, run_id):
    if run_id == 'latest':
        run_id = con.execute('SELECT run_id FROM runs ORDER BY started DESC LIMIT 1').fetchone()[0]
    run = con.execute('SELECT * FROM runs WHERE run_id = ?', (run_id,)).fetchone()
    rows = stats_rows(con, run_id)
    out = [f'# Run {run_id} ({run["kind"]}, pool {run["map_pool"]}, commit {run["git_commit"]})\n',
           f'{run["purpose"]}\n' if run['purpose'] else '']
    st, order = standings(rows)
    out += ['## Standings\n', st]
    if run['kind'] == 'ab':
        t, m, se = paired(con, run_id)
        verdict = 'ACCEPT' if m > 2 * se else 'REJECT'
        out += ['## A/B\n', t, f'\nGate (Δ > 2·SE): **{verdict}**\n']
    out += ['## Head-to-head\n', matrix(rows, order), '## Per-game averages\n', profile(rows, order),
            '## Loss/tie causes\n', causes(rows, order), '## Timing\n', timing(rows, order)]
    focus = next((k for k in order if k.startswith('my_team@')), order[0])
    out += [f'## Worst games for {focus}\n', worst(rows, focus)]
    return '\n'.join(out)


def progress(con, agent):
    rows = con.execute(
        'SELECT v.agent_hash, MIN(r.started) AS first, COUNT(*) AS n, AVG(ts.points) AS ppg, '
        'AVG(ts.margin) AS margin FROM team_stats ts JOIN games g USING (game_id) '
        'JOIN runs r USING (run_id) JOIN versions v ON v.agent_hash = ts.agent_hash '
        'WHERE ts.agent_name = ? GROUP BY v.agent_hash ORDER BY first', (agent,)).fetchall()
    return table(['version', 'games', 'points/game', 'avg margin'],
                 [(r['agent_hash'][:7], r['n'], f"{r['ppg']:.2f}", f"{r['margin']:+.1f}") for r in rows])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('report').add_argument('run_id')
    p = sub.add_parser('progress')
    p.add_argument('--agent', default='my_team')
    sub.add_parser('sql').add_argument('query')
    args = parser.parse_args()
    con = db.connect()
    if args.cmd == 'report':
        print(report(con, args.run_id))
    elif args.cmd == 'progress':
        print(progress(con, args.agent))
    else:
        rows = con.execute(args.query).fetchall()
        if rows:
            print(table(rows[0].keys(), [tuple(r) for r in rows]))


if __name__ == '__main__':
    main()
