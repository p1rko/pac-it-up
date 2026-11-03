"""
Mistake tracker: rebuilds every state of a finished game from its layout and
move history (the rules are deterministic; only observations are noisy) and
extracts per-team statistics, an event stream and a primary loss cause.

Used by tournament.py inside each worker right after the game is played.
"""

from collections import deque

from contest.capture import GameState

RED, BLUE = 'red', 'blue'
UNOPPOSED_DIST = 6      # invader food counts as "unopposed" if no defender is this close
IDLE_WINDOW = 10        # own moves looked at when deciding if an agent is stuck
TIMELINE_STEP = 40      # score sampled every this many moves


def team_of(index):
    return RED if index % 2 == 0 else BLUE


class MapInfo:
    """All-pairs maze distances, home borders and dead-end pocket depths."""

    def __init__(self, layout):
        walls = layout.walls
        self.width, self.height = walls.width, walls.height
        self.cells = [(x, y) for x in range(self.width) for y in range(self.height) if not walls[x][y]]
        cell_set = set(self.cells)
        self.nbrs = {c: [n for n in ((c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1))
                         if n in cell_set] for c in self.cells}
        self.dist = {c: self._bfs([c]) for c in self.cells}
        mid = self.width // 2
        self.border = {RED: [c for c in self.cells if c[0] == mid - 1],
                       BLUE: [c for c in self.cells if c[0] == mid]}
        self.home_dist = {t: self._bfs(self.border[t]) for t in (RED, BLUE)}
        self.pocket_depth = self._pockets()

    def _bfs(self, sources):
        d = {s: 0 for s in sources}
        q = deque(sources)
        while q:
            c = q.popleft()
            for n in self.nbrs[c]:
                if n not in d:
                    d[n] = d[c] + 1
                    q.append(n)
        return d

    def _pockets(self):
        degree = {c: len(self.nbrs[c]) for c in self.cells}
        pocket = set()
        q = deque(c for c in self.cells if degree[c] <= 1)
        while q:
            c = q.popleft()
            if c in pocket:
                continue
            pocket.add(c)
            for n in self.nbrs[c]:
                if n not in pocket:
                    degree[n] -= 1
                    if degree[n] == 1:
                        q.append(n)
        exits = [c for c in self.cells if c not in pocket]
        d = self._bfs(exits) if exits else {}
        return {c: d.get(c, 0) for c in pocket}

    def d(self, a, b):
        return self.dist[a].get(b, 999)


def _pos(state, i):
    p = state.get_agent_position(i)
    return (int(p[0]), int(p[1]))


def analyze_game(layout, actions, length, crashed=None):
    """
    Returns {'teams': {red: stats, blue: stats}, 'events': [...],
             'timeline': [...], 'end_reason': str}.
    `crashed` is the index of the agent that crashed/timed out, if any.
    """
    info = MapInfo(layout)
    state = GameState()
    state.initialize(layout, 4)
    state.data.timeleft = length
    starts = [state.data.agent_states[i].start.pos for i in range(4)]
    starts = [(int(p[0]), int(p[1])) for p in starts]

    stats = {t: dict(banked=0, deaths=0, food_lost=0, death_pocket=0, kills=0, food_denied=0,
                     scared_kills=0, scared_deaths=0, invader_food_eaten=0, invader_food_banked=0,
                     unopposed_food=0, capsule_food_conceded=0, capsules=0, idle_attack=0,
                     idle_home=0, pacman_turns=0, timeout_carry=0, crashed=0)
             for t in (RED, BLUE)}
    events, timeline = [], []
    recent = {i: deque(maxlen=IDLE_WINDOW) for i in range(4)}

    def emit(turn, i, kind, **data):
        events.append((turn, i, kind, data))

    for turn, (i, action) in enumerate(actions):
        prev = state
        state = prev.generate_successor(i, action)
        me = team_of(i)

        # Deaths: a non-mover that changed cell was eaten; the mover died if it
        # jumped back to its start.
        for j in range(4):
            pp, np_ = _pos(prev, j), _pos(state, j)
            if pp == np_:
                continue
            if j != i or (np_ == starts[j] and abs(pp[0] - np_[0]) + abs(pp[1] - np_[1]) > 1):
                ps = prev.data.agent_states[j]
                victim, killer_team = team_of(j), (BLUE if team_of(j) == RED else RED)
                enemies = [k for k in range(4) if team_of(k) == killer_team]
                killer = i if team_of(i) == killer_team else min(enemies, key=lambda k: info.d(pp, _pos(prev, k)))
                if ps.is_pacman:
                    depth = info.pocket_depth.get(pp, 0)
                    stats[victim]['deaths'] += 1
                    stats[victim]['food_lost'] += ps.num_carrying
                    stats[killer_team]['kills'] += 1
                    stats[killer_team]['food_denied'] += ps.num_carrying
                    if depth > 0:
                        stats[victim]['death_pocket'] += 1
                    emit(turn, j, 'death', carried=ps.num_carrying, pos=pp, killer=killer,
                         home_dist=info.home_dist[victim].get(pp), pocket_depth=depth)
                else:
                    stats[victim]['scared_deaths'] += 1
                    stats[killer_team]['scared_kills'] += 1
                    emit(turn, j, 'scared_death', pos=pp, killer=killer)

        ps, ns = prev.data.agent_states[i], state.data.agent_states[i]
        mpos = _pos(state, i)
        if ns.num_returned > ps.num_returned:
            amount = ns.num_returned - ps.num_returned
            stats[me]['banked'] += amount
            stats[BLUE if me == RED else RED]['invader_food_banked'] += amount
            emit(turn, i, 'bank', amount=amount)
        if ns.num_carrying > ps.num_carrying:
            owner = BLUE if me == RED else RED
            guards = [k for k in range(4) if team_of(k) == owner and not prev.data.agent_states[k].is_pacman]
            gd = min((info.d(mpos, _pos(prev, k)) for k in guards), default=999)
            all_scared = bool(guards) and all(prev.data.agent_states[k].scared_timer > 0 for k in guards)
            stats[owner]['invader_food_eaten'] += 1
            if gd > UNOPPOSED_DIST:
                stats[owner]['unopposed_food'] += 1
            if all_scared:
                stats[owner]['capsule_food_conceded'] += 1
            emit(turn, i, 'eat', pos=mpos, guard_dist=gd, guards_scared=all_scared)
        if len(state.get_capsules()) < len(prev.get_capsules()):
            stats[me]['capsules'] += 1
            emit(turn, i, 'capsule', pos=mpos)

        if ns.is_pacman:
            stats[me]['pacman_turns'] += 1
        recent[i].append(mpos)
        if len(recent[i]) == IDLE_WINDOW and len(set(recent[i])) <= 2:
            stats[me]['idle_attack' if ns.is_pacman else 'idle_home'] += 1

        if turn % TIMELINE_STEP == 0:
            timeline.append(state.data.score)

    timeline.append(state.data.score)
    food_to_win = layout.total_food / 2 - 2
    if crashed is not None:
        end_reason = 'crash'
        stats[team_of(crashed)]['crashed'] = 1
    elif max(stats[RED]['banked'], stats[BLUE]['banked']) >= food_to_win:
        end_reason = 'food'
    else:
        end_reason = 'time'
        for j in range(4):
            stats[team_of(j)]['timeout_carry'] += state.data.agent_states[j].num_carrying

    score = state.data.score if crashed is None else None
    for t in (RED, BLUE):
        stats[t]['loss_cause'] = loss_cause(stats[t], stats[BLUE if t == RED else RED])
    return dict(teams=stats, events=events, timeline=timeline, end_reason=end_reason, replay_score=score)


def loss_cause(mine, theirs):
    """Biggest avoidable swing for a team, measured in food points."""
    if mine['crashed']:
        return 'forfeit'
    swings = {
        'died-carrying': mine['food_lost'],
        'timeout-carrying': mine['timeout_carry'],
        'invader-unopposed': mine['unopposed_food'],
        'capsule-swing': mine['capsule_food_conceded'],
        'stalled': mine['idle_attack'] / 10.0,
    }
    cause, value = max(swings.items(), key=lambda kv: kv[1])
    return cause if value >= 3 else 'outscored-throughput'
