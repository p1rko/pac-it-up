"""
Enemy raids against one of our versions, computed by replaying stored games.

  python tools/raid_fate_probe.py <agent> <run_id> [<run_id> ...]

A raid runs from an enemy becoming a Pacman on our side until it crosses back
(banked = what it carried) or is eaten. Per raid we record where our two agents
were at its start (A = attacking, H = home; Raider first), whether an unscared
ghost of ours ever got within 6 steps, whether one of ours turned scared
(capsule), and whether an attacker of ours came home during it. Big raids
(banking 5+) are broken down further.
"""
import os
import pickle
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'tools'))
os.chdir(os.path.join(REPO, 'pacman-contest', 'src', 'contest'))
from contest.capture import GameState  # noqa: E402
import db  # noqa: E402
from analyze import RED, BLUE, MapInfo  # noqa: E402

NEAR = 6


def pos(s, i):
    p = s.get_agent_position(i)
    return int(p[0]), int(p[1])


def bucket(d):
    return '≤10' if d <= 10 else '11-15' if d <= 15 else '16-20' if d <= 20 else '21+'


def main():
    agent, runs = sys.argv[1], sys.argv[2:]
    con = db.connect()
    marks = ','.join('?' * len(runs))
    rows = con.execute(f'SELECT ts.side, ts.opp_name, g.replay_path FROM team_stats ts JOIN games g USING (game_id) '
                       f'WHERE g.run_id IN ({marks}) AND ts.agent_name = ?', (*runs, agent)).fetchall()
    raids = []
    far_home = Counter()          # nearest home ghost distance bucket at unopposed bites with a ghost home
    far_closing = Counter()
    both_att = Counter()          # what the two attackers were doing at unopposed bites
    both_att_food = Counter()
    for r in rows:
        with open(os.path.join(REPO, r['replay_path']), 'rb') as f:
            rep = pickle.load(f)
        info = MapInfo(rep['layout'])
        s = GameState()
        s.initialize(rep['layout'], 4)
        s.data.timeleft = rep['length']
        mine = (0, 2) if r['side'] == 'red' else (1, 3)
        theirs = tuple(k for k in range(4) if k not in mine)
        my_team = RED if r['side'] == 'red' else BLUE
        hd = info.home_dist[my_team]
        start = {i: tuple(int(c) for c in s.data.agent_states[i].start.pos) for i in range(4)}
        sign = 1 if r['side'] == 'red' else -1
        hist = defaultdict(list)   # agent -> positions after each of its moves
        open_r = {}
        n = len(rep['actions'])
        for t, (i, a) in enumerate(rep['actions']):
            prev, s = s, s.generate_successor(i, a)
            st, pst = s.data.agent_states, prev.data.agent_states
            hist[i].append(pos(s, i))
            if i in theirs:
                if st[i].is_pacman and i not in open_r:
                    ra, fl = (pst[k] for k in mine)
                    open_r[i] = {'opp': r['opp_name'], 'bites': 0, 'unopp': 0, 'touched': False, 'turn': t,
                                 'start': ('A' if ra.is_pacman else 'H') + ('A' if fl.is_pacman else 'H'),
                                 'lead': sign * prev.data.score, 'frac': t / n,
                                 'att_border': min((hd.get(pos(prev, k), 99) for k in mine if pst[k].is_pacman), default=None),
                                 'att_carry': [pst[k].num_carrying for k in mine if pst[k].is_pacman],
                                 'home_d': min((info.d(pos(prev, i), pos(prev, k)) for k in mine if not pst[k].is_pacman), default=None),
                                 'home_scared': any(pst[k].scared_timer > 0 for k in mine if not pst[k].is_pacman),
                                 'came_home': False, 'cap': False}
                c = open_r.get(i)
                if c is not None:
                    p = pos(s, i)
                    ghosts = [k for k in mine if not st[k].is_pacman and st[k].scared_timer == 0]
                    if any(info.d(p, pos(s, k)) <= NEAR for k in ghosts):
                        c['touched'] = True
                    if any(st[k].scared_timer > 0 and pst[k].scared_timer == 0 for k in mine):
                        c['cap'] = True
                    if st[i].num_carrying > pst[i].num_carrying:
                        c['bites'] += 1
                        home = [k for k in mine if not pst[k].is_pacman]
                        dmin = min((info.d(p, pos(prev, k)) for k in home), default=999)
                        if dmin > NEAR:
                            c['unopp'] += 1
                            if home:
                                k = min(home, key=lambda k: info.d(p, pos(prev, k)))
                                far_home[bucket(dmin)] += 1
                                h = hist[k]
                                old = h[-4] if len(h) >= 4 else h[0]
                                far_closing['scared' if pst[k].scared_timer > 0 else
                                            'closing' if info.d(p, pos(prev, k)) < info.d(p, old) else 'not closing'] += 1
                            else:
                                for k, role in zip(mine, ('raider', 'flex')):
                                    ak = pst[k]
                                    both_att[f'{role} carrying' if ak.num_carrying else f'{role} empty'] += 1
                                    both_att_food[role] += ak.num_carrying
                                ds = [hd.get(pos(prev, k), 99) for k in mine]
                                both_att['nearest attacker ≤5 from border'] += min(ds) <= 5
                                both_att['bites'] += 1
                    if not st[i].is_pacman or (pos(s, i) == start[i] and pos(prev, i) != start[i]):
                        died = st[i].is_pacman or pos(s, i) == start[i]
                        c['end'] = 'eaten' if died else 'banked'
                        c['banked'] = 0 if died else pst[i].num_carrying
                        raids.append(c)
                        del open_r[i]
            if i in mine and pst[i].is_pacman and not st[i].is_pacman and pos(s, i) != start[i]:
                for c in open_r.values():
                    c['came_home'] = True
            # an enemy eaten on our side by our move
            for e in list(open_r):
                if pos(s, e) == start[e] and pos(prev, e) != start[e]:
                    c = open_r.pop(e)
                    c['end'], c['banked'] = 'eaten', 0
                    raids.append(c)
        for c in open_r.values():
            c['end'], c['banked'] = 'game_over', 0
            raids.append(c)

    g = max(len(rows), 1)
    print(f'## {agent}: {len(rows)} games, {len(raids)} enemy raids ({len(raids) / g:.1f}/game)\n')
    print('| raid start (raider/flex; A=attacking H=home) | raids | eaten | banked food/game | food per raid | never within 6 of a ghost |')
    print('|---|---|---|---|---|---|')
    grp = defaultdict(list)
    for c in raids:
        grp[c['start']].append(c)
    for k, cs in sorted(grp.items()):
        m = len(cs)
        print(f"| {k} | {m} | {100 * sum(c['end'] == 'eaten' for c in cs) / m:.0f}% | "
              f"{sum(c['banked'] for c in cs) / g:.2f} | {sum(c['banked'] for c in cs) / m:.2f} | "
              f"{100 * sum(not c['touched'] for c in cs) / m:.0f}% |")
    tot = sum(c['banked'] for c in raids)
    untouched = sum(c['banked'] for c in raids if not c['touched'])
    print(f'\nfood banked by raids: {tot / g:.2f}/game; by raids never within 6 of a ghost: {untouched / g:.2f}/game '
          f'({100 * untouched / max(tot, 1):.0f}%)')
    print('\nraid banked by size:', dict(sorted(Counter(min(c["banked"], 10) for c in raids if c['banked']).items())))
    big = [c for c in raids if c['banked'] >= 5]
    print(f'raids banking 5+: {len(big)} ({len(big) / g:.2f}/game), food {sum(c["banked"] for c in big) / g:.2f}/game, '
          f'start {Counter(c["start"] for c in big)}, never touched {sum(not c["touched"] for c in big)}')
    for cap in (True, False):
        cs = [c for c in big if c['cap'] == cap]
        print(f"big raids with capsule={cap}: {len(cs)}, food {sum(c['banked'] for c in cs) / g:.2f}/game, mean {sum(c['banked'] for c in cs) / max(len(cs), 1):.1f}, "
              f"untouched {sum(not c['touched'] for c in cs)}, first half {sum(c['frac'] < .5 for c in cs)}")
    for opp in sorted({c['opp'] for c in big}):
        cs = [c for c in big if c['opp'] == opp]
        gn = sum(1 for r in rows if r['opp_name'] == opp)
        print(f"  {opp}: big {len(cs) / gn:.2f}/game food {sum(c['banked'] for c in cs) / gn:.2f}/game, with capsule {sum(c['cap'] for c in cs)}/{len(cs)}")
    def hist_(title, cs, key):
        print(f'  {title}:', dict(sorted(Counter(key(c) for c in cs).items(), key=lambda kv: str(kv[0]))))
    for st_ in ('AA', 'AH', 'HA', 'HH'):
        cs = [c for c in big if c['start'] == st_]
        print(f'\nbig raids starting {st_}: {len(cs)}, food {sum(c["banked"] for c in cs) / g:.2f}/game')
        hist_('game phase (quarter)', cs, lambda c: int(c['frac'] * 4) + 1)
        hist_('capsule eaten during raid', cs, lambda c: c['cap'])
        hist_('never within 6 of an unscared ghost', cs, lambda c: not c['touched'])
        if st_ != 'HH':
            hist_('nearest attacker distance to border', cs, lambda c: ('≤3' if c['att_border'] <= 3 else '4-6' if c['att_border'] <= 6 else bucket(c['att_border'])) if c['att_border'] is not None else None)
            hist_('an attacker came home during the raid', cs, lambda c: c['came_home'])
            hist_('attackers carrying at start', cs, lambda c: tuple(sorted(c['att_carry'])))
            hist_('came home x attacker ≤6 from border', cs, lambda c: (c['came_home'], c['att_border'] <= 6))
        if st_ != 'AA':
            hist_('home ghost distance to invader at start', cs, lambda c: bucket(c['home_d']) if c['home_d'] is not None else None)
            hist_('home ghost scared at start', cs, lambda c: c['home_scared'])
    print('\nunopposed bites with a ghost home, nearest home ghost distance:', dict(far_home))
    print('  that ghost over its last 3 moves:', dict(far_closing))
    b = both_att['bites']
    print(f'\nunopposed bites with both attacking: {b}; ' + ', '.join(f'{k} {100 * v / max(b, 1):.0f}%' for k, v in both_att.items() if k != 'bites'))
    print('  mean carried at those bites: ' + ', '.join(f'{k} {v / max(b, 1):.1f}' for k, v in both_att_food.items()))
    print('\nby opponent: raids/game, food banked/game, eaten %')
    for opp in sorted({c['opp'] for c in raids}):
        cs = [c for c in raids if c['opp'] == opp]
        gn = sum(1 for r in rows if r['opp_name'] == opp)
        print(f"  {opp}: {len(cs) / gn:.1f}, {sum(c['banked'] for c in cs) / gn:.2f}, {100 * sum(c['end'] == 'eaten' for c in cs) / len(cs):.0f}%")


main()
