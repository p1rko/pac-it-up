"""
Mini tournament you can watch: every game opens the graphics window, and the
standings table (3 points per win, 1 per tie) is printed after each game.

  python tools/mini_tournament.py                       # our team vs each sparring team, 1 random map each
  python tools/mini_tournament.py --mode round-robin    # every team plays every other team (21 games)
  python tools/mini_tournament.py --maps 2 --delay 0.01 # 2 maps per pairing (colours swapped), faster
  python tools/mini_tournament.py --quiet               # no graphics, just the table
  python tools/mini_tournament.py --teams dario blitz   # only these opponents

Matches run with -c (time limits enforced, like the real contest). Close the
graphics window or press Ctrl-C to stop early; the table so far is kept.
"""

import argparse
import itertools
import os
import random
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(REPO, 'pacman-contest', 'src', 'contest')
PY = os.path.join(REPO, 'venv', 'bin', 'python')
if not os.path.exists(PY):
    PY = sys.executable

TEAMS = {
    'packitup': 'my_team.py',
    'dario': 'strategies/dario.py',
    'tracking': 'strategies/tracking.py',
    'search': 'strategies/search.py',
    'reflex': 'strategies/reflex.py',
    'blitz': 'strategies/blitz.py',
    'turtle': 'strategies/turtle.py',
}


def play(red, blue, layout, args):
    cmd = [PY, 'capture.py', '-r', os.path.join(REPO, TEAMS[red]), '-b', os.path.join(REPO, TEAMS[blue]),
           '-l', layout, '-c', '--red-name', red, '--blue-name', blue,
           '--delay-step', str(args.delay), '-z', str(args.zoom)]
    if args.quiet:
        cmd.append('-Q')
    out = subprocess.run(cmd, cwd=ENGINE, capture_output=True, text=True).stdout
    # returns (sign, margin): sign +1 red won, -1 blue won, 0 tie; margin None for food-limit wins
    m = re.search(r'The (Red|Blue) team has returned at least', out)
    if m:
        return (1 if m.group(1) == 'Red' else -1), None
    if 'Tie game!' in out:
        return 0, 0
    m = re.search(r'The (Red|Blue) team wins by (\d+) points', out)
    if m:
        return (1 if m.group(1) == 'Red' else -1), int(m.group(2))
    return None, None


def table(stats):
    rows = sorted(stats.items(), key=lambda kv: (-kv[1]['pts'], -kv[1]['diff']))
    print("\n(score± counts time-up margins only; food-limit wins add 3 pts but no margin)")
    print(f"{'#':>2}  {'team':10} {'P':>3} {'W':>3} {'T':>3} {'L':>3} {'score±':>7} {'pts':>4}")
    for i, (t, s) in enumerate(rows, 1):
        print(f"{i:>2}  {t:10} {s['p']:>3} {s['w']:>3} {s['t']:>3} {s['l']:>3} {s['diff']:>+7} {s['pts']:>4}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['gauntlet', 'round-robin'], default='gauntlet')
    ap.add_argument('--teams', nargs='*', help='opponents to include (default: all)')
    ap.add_argument('--maps', type=int, default=1, help='maps per pairing; colours alternate')
    ap.add_argument('--seed', type=int, help='seed for picking the random maps')
    ap.add_argument('--delay', type=float, default=0.02, help='seconds per move in the window')
    ap.add_argument('--zoom', type=float, default=1.0)
    ap.add_argument('--quiet', action='store_true', help='no graphics')
    args = ap.parse_args()

    names = ['packitup'] + [t for t in TEAMS if t != 'packitup' and (not args.teams or t in args.teams)]
    if args.mode == 'gauntlet':
        pairs = [('packitup', o) for o in names[1:]]
    else:
        pairs = list(itertools.combinations(names, 2))
    rng = random.Random(args.seed)
    games = []
    for a, b in pairs:
        for k in range(args.maps):
            red, blue = (a, b) if k % 2 == 0 else (b, a)
            games.append((red, blue, f'RANDOM{rng.randint(1, 10**6)}'))

    stats = {t: dict(p=0, w=0, t=0, l=0, diff=0, pts=0) for t in names}
    print(f'{len(games)} games: ' + ', '.join(f'{r} v {b}' for r, b, _ in games))
    try:
        for i, (red, blue, layout) in enumerate(games, 1):
            print(f'\n[{i}/{len(games)}] {red} (red) vs {blue} (blue) on {layout} ...', flush=True)
            sign, margin = play(red, blue, layout, args)
            if sign is None:
                print('  game did not finish (window closed or crash); skipped')
                continue
            for team, s in ((red, sign), (blue, -sign)):
                st = stats[team]
                st['p'] += 1
                st['diff'] += s * (margin or 0)
                if s > 0:
                    st['w'] += 1; st['pts'] += 3
                elif s == 0:
                    st['t'] += 1; st['pts'] += 1
                else:
                    st['l'] += 1
            winner = red if sign > 0 else blue if sign < 0 else None
            how = 'by bringing home all but 2 dots' if margin is None else f'by {margin} at time-up'
            print(f'  -> {winner} wins {how}' if winner else '  -> tie')
            table(stats)
    except KeyboardInterrupt:
        print('\nstopped early')
        table(stats)


if __name__ == '__main__':
    main()
