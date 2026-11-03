"""
SQLite store for every game we play (tools/results.db). Agents are keyed by
the sha1 of their file, so any edit becomes a new version automatically.
"""

import hashlib
import json
import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results.db')

STAT_COLUMNS = ['banked', 'deaths', 'food_lost', 'death_pocket', 'kills', 'food_denied',
                'scared_kills', 'scared_deaths', 'invader_food_eaten', 'invader_food_banked',
                'unopposed_food', 'capsule_food_conceded', 'capsules', 'idle_attack', 'idle_home',
                'pacman_turns', 'timeout_carry', 'crashed']

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS versions (
    agent_hash TEXT PRIMARY KEY, name TEXT, path TEXT, first_seen REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started REAL, git_commit TEXT, kind TEXT, purpose TEXT,
    map_pool TEXT, params_json TEXT);
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY, run_id TEXT, red_hash TEXT, blue_hash TEXT, red_name TEXT,
    blue_name TEXT, layout TEXT, seed INTEGER, score INTEGER, winner TEXT,
    points_red INTEGER, points_blue INTEGER, end_reason TEXT, turns INTEGER, wall_s REAL,
    timeline_json TEXT, replay_path TEXT, stderr_tail TEXT);
CREATE TABLE IF NOT EXISTS team_stats (
    game_id TEXT, side TEXT, agent_hash TEXT, agent_name TEXT, opp_hash TEXT, opp_name TEXT,
    points INTEGER, margin INTEGER,
    {', '.join(c + ' INTEGER' for c in STAT_COLUMNS)},
    max_move_s REAL, p99_move_s REAL, init_s REAL, warnings INTEGER, loss_cause TEXT,
    PRIMARY KEY (game_id, side));
CREATE TABLE IF NOT EXISTS events (
    game_id TEXT, turn INTEGER, agent_index INTEGER, side TEXT, type TEXT, data_json TEXT);
CREATE INDEX IF NOT EXISTS idx_games_run ON games(run_id);
CREATE INDEX IF NOT EXISTS idx_stats_agent ON team_stats(agent_hash);
CREATE INDEX IF NOT EXISTS idx_events_game ON events(game_id);
"""


def connect(path=DB_PATH):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript(SCHEMA)
    return con


def file_hash(path):
    with open(path, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()[:10]


def register_version(con, agent_hash, name, path):
    con.execute('INSERT OR IGNORE INTO versions VALUES (?, ?, ?, ?, ?)',
                (agent_hash, name, path, time.time(), None))


def insert_run(con, run_id, git_commit, kind, purpose, map_pool, params):
    con.execute('INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)',
                (run_id, time.time(), git_commit, kind, purpose, map_pool, json.dumps(params)))
    con.commit()


def insert_game(con, run_id, r):
    """`r` is the result dict returned by tournament.play()."""
    con.execute('INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (r['game_id'], run_id, r['red']['hash'], r['blue']['hash'], r['red']['name'],
                 r['blue']['name'], r['layout'], r['seed'], r['score'], r['winner'],
                 r['points']['red'], r['points']['blue'], r['end_reason'], r['turns'], r['wall_s'],
                 json.dumps(r['timeline']), r['replay_path'], r['stderr_tail']))
    for side, other in (('red', 'blue'), ('blue', 'red')):
        s = r['stats'][side]
        margin = r['score'] if side == 'red' else -r['score']
        con.execute(f'INSERT INTO team_stats VALUES ({", ".join("?" * (len(STAT_COLUMNS) + 13))})',
                    (r['game_id'], side, r[side]['hash'], r[side]['name'], r[other]['hash'],
                     r[other]['name'], r['points'][side], margin, *[s[c] for c in STAT_COLUMNS],
                     r['timing'][side]['max'], r['timing'][side]['p99'], r['timing'][side]['init'],
                     r['timing'][side]['warnings'], s['loss_cause']))
    con.executemany('INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)',
                    [(r['game_id'], t, i, 'red' if i % 2 == 0 else 'blue', kind, json.dumps(data))
                     for t, i, kind, data in r['events']])
    con.commit()
