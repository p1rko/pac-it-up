# my_team.py
# ---------------
# Licensing Information: Please do not distribute or publish solutions to this
# project. You are free to use and extend these projects for educational
# purposes. The Pacman AI projects were developed at UC Berkeley, primarily by
# John DeNero (denero@cs.berkeley.edu) and Dan Klein (klein@cs.berkeley.edu).
# For more info, see http://inst.eecs.berkeley.edu/~cs188/sp09/pacman.html
#
# Team "Pack It Up" -- see AGENT_EXPLAINED.md for the full design write-up.
#
# Two hybrid agents that share one brain (TEAM_INFO):
#   * a probability map of where every unseen enemy is (exact inference from
#     the noisy sonar, vision, the side of the map and vanished food);
#   * Dijkstra path planning that avoids ghosts and dead-end traps;
#   * a time-boxed alpha-beta search whenever a fight is close;
#   * roles that adapt every turn: the "Raider" mostly attacks, the "Warden"
#     mostly defends, but both switch to whatever the position needs.

import heapq
import os
import random
import time
from collections import deque

from contest.capture_agents import CaptureAgent
from contest.game import Directions, Actions

#################
# Team creation #
#################

# Information shared by the two agents of a team (same process, no threads).
TEAM_INFO = {}


def create_team(first_index, second_index, is_red,
                first='RaiderAgent', second='FlexAgent', num_training=0):
    """
    Returns the two agents that form the team. The tournament calls this
    without extra arguments, so the defaults are the submitted team.
    """
    return [eval(first)(first_index), eval(second)(second_index)]


##########
# Agents #
##########

INF = float('inf')
DEBUG = bool(os.environ.get('PACKITUP_DEBUG'))


class SearchTimeout(Exception):
    pass


class SmartAgent(CaptureAgent):
    """
    Shared machinery: map analysis, beliefs, path planning, fights and the
    two behaviours (attack / defend) that the concrete agents pick between.
    """

    # Tunable parameters
    CARRY_LIMIT = 7         # return home after carrying this many dots
    DANGER_RADIUS = 5       # ghosts closer than this make us cautious
    SAFETY_MARGIN = 3       # extra moves kept to reach home before time runs out
    RAID_DIST = 5           # warden raids when both enemies are believed this far from our border
    RAID_CARRY = 3          # ... and comes back after eating this many dots
    SIGHT = 5               # Manhattan distance within which enemies are visible
    SEARCH_TIME = 0.30      # seconds of alpha-beta per move (limit is 1 s on a slower machine)
    TURN_BUDGET = 0.75      # hard stop for everything we do in one turn
    FIGHT_RANGE = 6         # search when an opponent is this close
    # Defender fight evaluation ("who gets there first" against an invader):
    ESCAPE_PENALTY = 300        # the invader reaches some border exit before all our ghosts
    EXIT_LEAD_WEIGHT = 25       # per step of its lead (or deficit) to its best exit ...
    EXIT_LEAD_CAP = 6           # ... clipped to this many steps either way
    FOOD_FIRST_WEIGHT = 8       # per defended dot it reaches first
    CAPSULE_FIRST_PENALTY = 200 # per defended capsule it reaches first
    SCARED_PENALTY = 500        # we are scared (it ate a capsule)

    # Scared window (F16): use it, don't get stuck in it.
    SCARED_BANK_MARGIN = 3      # bank when the guards recover within home distance + this
    PREY_TRAP_RANGE = 8         # chase a scared ghost trapped in a pocket at most this far
    DEADLOCK_MOVES = 150        # tied with at most this many own moves left: break the standoff (F19)
    BAIT = False                # in a deadlock, walk right up to the guards to pull them away (F19b)
    # Trapped haul (F20): going home as Pacman with food, but pinned by a guard.
    TRAP_TURNS = 20             # own moves in go_home ...
    TRAP_CELLS = 3              # ... covering at most this many cells = trapped
    ROOM_MAX = 40               # biggest area one guard can seal that counts as a trap room (F20d)
    AVOID_MATE_ROOM = False     # skip food in the teammate's trap room (F20d, Flex only)

    def __init__(self, index, time_for_computing=.1):
        super().__init__(index, time_for_computing)
        self.start = None
        self.recent = deque(maxlen=12)
        self.turn_start = time.time()

    # ------------------------------------------------------------------ #
    # Initialisation                                                       #
    # ------------------------------------------------------------------ #

    def register_initial_state(self, game_state):
        CaptureAgent.register_initial_state(self, game_state)  # computes maze distances
        self.start = game_state.get_agent_position(self.index)
        self.walls = game_state.get_walls()
        self.width, self.height = self.walls.width, self.walls.height
        self.cells = [(x, y) for x in range(self.width) for y in range(self.height)
                      if not self.walls[x][y]]
        self.neighbors = {c: self._adjacent(c) for c in self.cells}
        self.home_cells = [c for c in self.cells if self.is_home(c)]
        self.enemy_side = frozenset(c for c in self.cells if not self.is_home(c))

        mid = self.width // 2
        home_x = mid - 1 if self.red else mid
        enemy_x = mid if self.red else mid - 1
        self.home_border = [(home_x, y) for y in range(self.height)
                            if not self.walls[home_x][y] and not self.walls[enemy_x][y]]
        if not self.home_border:
            self.home_border = [(home_x, y) for y in range(self.height) if not self.walls[home_x][y]]
        self.enemy_border = [(enemy_x, y) for (_, y) in self.home_border]

        self._compute_dead_ends()
        self._compute_trap_rooms()
        self.home_dist_cache = {}
        self.banking = False    # decided to bank: keep going home instead of re-deciding
        self.went_home = False  # go_home ran this turn (F20)
        self.home_trace = deque(maxlen=self.TRAP_TURNS)
        self.trapped = False
        self.sacrificing = False

        # Fresh shared state every game (agents are reused across games with -n).
        TEAM_INFO[self.red] = {
            'targets': {},
            'trapped': {},
            'beliefs': {e: {game_state.get_initial_agent_position(e): 1.0}
                        for e in self.get_opponents(game_state)},
            'invader_turns': {e: 0 for e in self.get_opponents(game_state)},
        }

    def _adjacent(self, cell):
        x, y = cell
        result = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.width and 0 <= ny < self.height and not self.walls[nx][ny]:
                result.append((nx, ny))
        return result

    def _compute_dead_ends(self):
        """
        Iteratively prunes cells with a single open neighbour. Pruned cells
        are pockets with one way in and out: deadly when a ghost is near.
        For each pocket cell we store its depth and its entrance (the first
        non-pocket cell on the way out).
        """
        degree = {c: len(self.neighbors[c]) for c in self.cells}
        dead = set()
        queue = deque(c for c in self.cells if degree[c] <= 1)
        while queue:
            c = queue.popleft()
            if c in dead:
                continue
            dead.add(c)
            for n in self.neighbors[c]:
                if n not in dead:
                    degree[n] -= 1
                    if degree[n] == 1:
                        queue.append(n)

        self.depth = {c: 0 for c in self.cells}
        self.entrance = {c: c for c in self.cells}
        frontier = deque(c for c in self.cells if c not in dead)
        seen = set(frontier)
        while frontier:
            c = frontier.popleft()
            for n in self.neighbors[c]:
                if n in dead and n not in seen:
                    seen.add(n)
                    self.depth[n] = self.depth[c] + 1
                    self.entrance[n] = self.entrance[c]
                    frontier.append(n)

    def _compute_trap_rooms(self):
        """
        Trap rooms (F20d): enemy-side areas a single guard can seal. For every
        enemy-side cell a guard could stand on, block it and its neighbours
        (cells we never step into) and see which enemy-side cells can no
        longer reach our border. Rooms bigger than ROOM_MAX are half the map
        behind a choke, not a room. self.rooms[cell] = ids of rooms holding it.
        """
        self.rooms = {}
        border = set(self.home_border)
        room_id = {}
        for g in self.enemy_side:
            block = {g, *self.neighbors[g]}
            seen = {c for c in border if c not in block}
            frontier = deque(seen)
            while frontier:
                c = frontier.popleft()
                for n in self.neighbors[c]:
                    if n not in seen and n not in block:
                        seen.add(n)
                        frontier.append(n)
            sealed = frozenset(c for c in self.enemy_side if c not in seen and c not in block)
            if not sealed or len(sealed) > self.ROOM_MAX:
                continue
            rid = room_id.setdefault(sealed, len(room_id))
            for c in sealed:
                self.rooms.setdefault(c, set()).add(rid)

    def same_room(self, a, b):
        """a and b lie in one trap room (F20d)."""
        ra, rb = self.rooms.get(a), self.rooms.get(b)
        return bool(ra and rb and not ra.isdisjoint(rb))

    # ------------------------------------------------------------------ #
    # Turn wrapper: timing and crash protection                            #
    # ------------------------------------------------------------------ #

    def get_action(self, game_state):
        self.turn_start = time.time()
        return CaptureAgent.get_action(self, game_state)

    def choose_action(self, game_state):
        """
        Never let an exception or a bug lose the game: a crash or a timeout
        forfeits the match, a random legal move only loses one turn.
        """
        legal = game_state.get_legal_actions(self.index)
        self.went_home = False
        try:
            self.update_beliefs(game_state)
            action = self.decide(game_state)
            action = self.finish(game_state, action)
        except Exception:
            if DEBUG:
                raise
            action = None
        if action not in legal:
            non_stop = [a for a in legal if a != Directions.STOP]
            action = random.choice(non_stop or legal)
        self.recent.append(game_state.get_agent_position(self.index))
        self.track_trapped(game_state)
        return action

    def track_trapped(self, game_state):
        """
        Trapped (F20): as Pacman with food we kept trying to go home for
        TRAP_TURNS moves but stayed within TRAP_CELLS cells. Read next turn.
        """
        st = game_state.get_agent_state(self.index)
        if self.went_home and st.is_pacman and st.num_carrying > 0:
            self.home_trace.append(st.get_position())
        else:
            self.home_trace.clear()
        self.trapped = (len(self.home_trace) == self.TRAP_TURNS
                        and len(set(self.home_trace)) <= self.TRAP_CELLS)
        self.team()['trapped'][self.index] = self.trapped

    def decide(self, game_state):
        raise NotImplementedError

    def time_left(self):
        return self.TURN_BUDGET - (time.time() - self.turn_start)

    # ------------------------------------------------------------------ #
    # Belief tracking (where are the enemies we cannot see?)               #
    # ------------------------------------------------------------------ #

    def update_beliefs(self, game_state):
        """
        Exact inference over cells for every opponent, shared by both agents.
        The opponent that moved just before us is advanced one step, then all
        beliefs are filtered by the noisy distance reading, the side of the
        map the enemy is on and the fact that we cannot see it.
        """
        team = self.team()
        beliefs = team['beliefs']
        my_pos = game_state.get_agent_position(self.index)
        watchers = [game_state.get_agent_position(i) for i in self.get_team(game_state)]
        noisy = game_state.get_agent_distances()
        mover = (self.index - 1) % game_state.get_num_agents()

        if mover in beliefs:
            spread = {}
            for cell, p in beliefs[mover].items():
                options = self.neighbors[cell] + [cell]
                share = p / len(options)
                for n in options:
                    spread[n] = spread.get(n, 0.0) + share
            beliefs[mover] = spread

        for e in self.get_opponents(game_state):
            st = game_state.get_agent_state(e)
            pos = st.get_position()
            if st.is_pacman:
                team['invader_turns'][e] += 1
            if pos is not None:
                beliefs[e] = {pos: 1.0}
                continue

            def consistent(cell):
                if self.is_home(cell) != st.is_pacman:
                    return False  # an invader is on our side, a ghost on theirs
                if any(abs(cell[0] - w[0]) + abs(cell[1] - w[1]) <= self.SIGHT for w in watchers):
                    return False  # we would see it there
                return True

            def likelihood(cell):
                if noisy is None:
                    return 1.0
                d = abs(cell[0] - my_pos[0]) + abs(cell[1] - my_pos[1])
                return game_state.get_distance_prob(d, noisy[e])

            new = {}
            for cell, p in beliefs[e].items():
                if consistent(cell):
                    w = p * likelihood(cell)
                    if w > 0:
                        new[cell] = w
            if not new:
                # Lost track (usually the enemy died and respawned): restart
                # from its spawn if that fits, else from every plausible cell.
                spawn = game_state.get_initial_agent_position(e)
                if consistent(spawn) and likelihood(spawn) > 0:
                    new = {spawn: 1.0}
                else:
                    new = {c: likelihood(c) for c in self.cells if consistent(c)}
                    new = {c: w for c, w in new.items() if w > 0} or \
                          {c: 1.0 for c in self.cells if self.is_home(c) == st.is_pacman}
            total = sum(new.values())
            beliefs[e] = {c: w / total for c, w in new.items()}

        # Food that vanished from our side pins down an unseen invader.
        for cell in self.eaten_food(game_state):
            hidden = [e for e in self.get_opponents(game_state)
                      if game_state.get_agent_state(e).is_pacman
                      and game_state.get_agent_state(e).get_position() is None]
            if hidden:
                e = max(hidden, key=lambda i: sum(p for c, p in beliefs[i].items()
                                                  if abs(c[0] - cell[0]) + abs(c[1] - cell[1]) <= 2))
                beliefs[e] = {cell: 1.0}

    def most_likely(self, enemy):
        belief = self.team()['beliefs'][enemy]
        return max(belief, key=belief.get)

    def eaten_food(self, game_state):
        prev = self.get_previous_observation()
        if prev is None:
            return []
        before = set(self.get_food_you_are_defending(prev).as_list())
        now = set(self.get_food_you_are_defending(game_state).as_list())
        return list(before - now)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def team(self):
        return TEAM_INFO[self.red]

    def dist(self, a, b):
        return self.get_maze_distance(a, b)

    def is_home(self, pos):
        mid = self.width // 2
        return pos[0] < mid if self.red else pos[0] >= mid

    def moves_left(self, game_state):
        """Moves this agent still gets to make."""
        return game_state.data.timeleft // 4

    def deadlocked(self, game_state):
        """
        Tied in the second half. A single banked dot turns the tie (1 point)
        into a win (3), and a death only costs time (the food is dropped back
        on the map), so the usual caution no longer pays.
        """
        return self.get_score(game_state) == 0 and self.moves_left(game_state) <= self.DEADLOCK_MOVES

    def home_distance(self, pos):
        d = self.home_dist_cache.get(pos)
        if d is None:
            d = min(self.dist(pos, b) for b in self.home_border)
            self.home_dist_cache[pos] = d
        return d

    def enemy_ghosts(self, game_state):
        """Visible enemy ghosts as (position, scared_timer)."""
        result = []
        for i in self.get_opponents(game_state):
            st = game_state.get_agent_state(i)
            pos = st.get_position()
            if pos is not None and not st.is_pacman:
                result.append((pos, st.scared_timer))
        return result

    def dangerous_ghosts(self, game_state, my_pos):
        """Ghosts that can still eat us (not scared for long enough)."""
        return [g for g, t in self.enemy_ghosts(game_state)
                if t <= self.dist(my_pos, g) + 2]

    def invaders(self, game_state):
        """Enemy pacmen as (index, position-or-None)."""
        result = []
        for i in self.get_opponents(game_state):
            st = game_state.get_agent_state(i)
            if st.is_pacman:
                result.append((i, st.get_position()))
        return result

    def invader_positions(self, game_state):
        """Seen or best-guess positions of every invader."""
        return [(i, p if p is not None else self.most_likely(i))
                for i, p in self.invaders(game_state)]

    def action_to(self, game_state, target_pos):
        """The legal action that moves us onto target_pos (an adjacent cell)."""
        my_pos = game_state.get_agent_position(self.index)
        for a in game_state.get_legal_actions(self.index):
            dx, dy = Actions.direction_to_vector(a)
            if (int(my_pos[0] + dx), int(my_pos[1] + dy)) == target_pos:
                return a
        return Directions.STOP

    def plan(self, game_state, goals, cost_fn=None, blocked=frozenset()):
        """
        Dijkstra from our position to the nearest goal. cost_fn(cell) adds
        an extra cost for entering a cell. Returns (first_step, cost) or
        (None, INF) when no goal is reachable.
        """
        start = game_state.get_agent_position(self.index)
        goals = set(goals)
        if not goals:
            return None, INF
        if start in goals:
            return start, 0
        best = {start: 0}
        heap = [(0, 0, start, None)]
        counter = 0
        while heap:
            cost, _, cell, first = heapq.heappop(heap)
            if cost > best.get(cell, INF):
                continue
            if cell in goals:
                return first, cost
            for n in self.neighbors[cell]:
                if n in blocked:
                    continue
                step = 1 + (cost_fn(n) if cost_fn else 0)
                new_cost = cost + step
                if new_cost < best.get(n, INF):
                    best[n] = new_cost
                    counter += 1
                    heapq.heappush(heap, (new_cost, counter, n, first or n))
        return None, INF

    def step_towards(self, game_state, goals, cost_fn=None, blocked=frozenset()):
        step, _ = self.plan(game_state, goals, cost_fn, blocked)
        my_pos = game_state.get_agent_position(self.index)
        if step is None or step == my_pos:
            return None
        return self.action_to(game_state, step)

    def ghost_cost_fn(self, ghosts):
        """Penalty for cells close to dangerous ghosts."""
        if not ghosts:
            return None

        def cost(cell):
            penalty = 0
            for g in ghosts:
                d = self.dist(cell, g)
                if d <= 1:
                    penalty += 1000
                elif d <= 3:
                    penalty += (4 - d) * 20
                if d <= 5 and self.depth[cell] > 0:
                    penalty += 10 * self.depth[cell]
            return penalty
        return cost

    def ghost_blocked(self, ghosts):
        """Cells we must never step into: ghost cells and their neighbours."""
        blocked = set()
        for g in ghosts:
            blocked.add(g)
            blocked.update(self.neighbors.get(g, []))
        return blocked

    # ------------------------------------------------------------------ #
    # Adversarial search for close fights                                  #
    # ------------------------------------------------------------------ #

    def fight_opponents(self, game_state):
        """Visible enemies we are in a fight with, nearest first."""
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        found = []
        for e in self.get_opponents(game_state):
            st = game_state.get_agent_state(e)
            pos = st.get_position()
            if pos is None:
                continue
            d = self.dist(my_pos, pos)
            if my_state.is_pacman:
                relevant = not st.is_pacman and st.scared_timer <= d + 2  # a ghost that can eat us
            else:
                relevant = st.is_pacman and my_state.scared_timer == 0 and self.is_home(pos)
            if relevant and d <= self.FIGHT_RANGE:
                found.append((d, e))
        found.sort()
        return [e for _, e in found]

    def finish(self, game_state, action):
        """Overrides the behaviour's action with a search when a fight is on."""
        enemies = self.fight_opponents(game_state)
        baiting, self.baiting = getattr(self, 'baiting', False), False
        if baiting:
            return action   # the search would pull the bait back to safety
        if enemies and self.time_left() > self.SEARCH_TIME:
            action = self.search(game_state, enemies, action)
        return action

    def search(self, game_state, enemies, default):
        """Iterative-deepening alpha-beta: us against the nearby enemies."""
        deadline = time.time() + min(self.SEARCH_TIME, self.time_left() - 0.1)
        my_state = game_state.get_agent_state(self.index)
        self.root = {
            'pacman': my_state.is_pacman,
            'carrying': my_state.num_carrying,
            'enemies': enemies,
            'enemy_start': {e: game_state.get_initial_agent_position(e) for e in enemies},
            'food': self.get_food(game_state).as_list(),
            'capsules': self.get_capsules(game_state),
        }
        self.root['far_from_start'] = {
            e: self.dist(game_state.get_agent_position(e), self.root['enemy_start'][e]) > 1
            for e in enemies}
        if not my_state.is_pacman:
            # Teammates that are home, unscared ghosts also block the invader;
            # the search keeps them where they stand.
            mates = []
            for i in self.get_team(game_state):
                st = game_state.get_agent_state(i)
                if i != self.index and not st.is_pacman and st.scared_timer == 0:
                    p = st.get_position()
                    mates.append((int(p[0]), int(p[1])))
            self.root['mates'] = mates
            self.root['def_food'] = self.get_food_you_are_defending(game_state).as_list()
            self.root['def_caps'] = self.get_capsules_you_are_defending(game_state)
            self.root['race'] = {}
        order = [self.index] + list(enemies)
        best = default
        plies = len(order)
        depth = plies
        try:
            while depth <= 4 * plies:
                _, action = self.ab(game_state, order, 0, depth, -INF, INF, deadline, default)
                if action is not None:
                    best = action
                depth += plies
        except SearchTimeout:
            pass
        return best

    def ordered_actions(self, state, agent, first=None):
        actions = [a for a in state.get_legal_actions(agent) if a != Directions.STOP] or \
            state.get_legal_actions(agent)
        if first in actions:
            actions.remove(first)
            actions.insert(0, first)
        return actions

    def ab(self, state, order, turn, depth, alpha, beta, deadline, first=None):
        if time.time() > deadline:
            raise SearchTimeout()
        if depth == 0 or state.is_over() or self.fight_over(state):
            return self.evaluate_fight(state), None
        agent = order[turn]
        nxt = (turn + 1) % len(order)
        if agent == self.index:
            best_v, best_a = -INF, None
            for a in self.ordered_actions(state, agent, first):
                v, _ = self.ab(state.generate_successor(agent, a), order, nxt, depth - 1,
                               alpha, beta, deadline)
                if v > best_v:
                    best_v, best_a = v, a
                if best_v >= beta:
                    break
                alpha = max(alpha, best_v)
            return best_v, best_a
        best_v = INF
        for a in self.ordered_actions(state, agent):
            v, _ = self.ab(state.generate_successor(agent, a), order, nxt, depth - 1,
                           alpha, beta, deadline)
            best_v = min(best_v, v)
            if best_v <= alpha:
                break
            beta = min(beta, best_v)
        return best_v, None

    def fight_over(self, state):
        """Someone got eaten: no point searching further down this line."""
        if self.root['pacman'] and state.get_agent_position(self.index) == self.start:
            return True
        for e in self.root['enemies']:
            if self.root['far_from_start'][e] and state.get_agent_position(e) == self.root['enemy_start'][e]:
                return True
        return False

    def evaluate_fight(self, state):
        me = state.get_agent_state(self.index)
        pos = me.get_position()
        cell = (int(pos[0]), int(pos[1]))

        if self.root['pacman'] and pos == self.start:
            return -100000 - 100 * self.root['carrying']  # we were eaten
        value = 1000 * self.get_score(state)
        for e in self.root['enemies']:
            if self.root['far_from_start'][e] and state.get_agent_position(e) == self.root['enemy_start'][e]:
                value += 5000   # we ate an enemy

        if self.root['pacman']:
            # Survive, keep the food we carry, get closer to home and to food.
            carrying = me.num_carrying
            value += 50 * carrying
            if carrying > 0:
                value -= (3 + carrying) * self.home_distance(cell)
            food = [f for f in self.root['food'] if state.has_food(f[0], f[1])]
            if food:
                value -= min(self.dist(cell, f) for f in food)
            caps_left = [c for c in self.root['capsules'] if c in state.get_capsules()]
            value -= 300 * len(caps_left)  # eating a capsule is great in a fight
            for e in self.root['enemies']:
                enemy = state.get_agent_state(e)
                enemy_pos = enemy.get_position()
                if enemy_pos is None or enemy.is_pacman:
                    continue
                d = self.dist(cell, enemy_pos)
                if enemy.scared_timer > d + 1:
                    continue
                if d <= 1:
                    value -= 600
                elif d == 2:
                    value -= 150
                elif d <= 4:
                    value -= 30
                if d <= 5:
                    value -= 25 * self.depth.get(cell, 0)  # don't get trapped in a pocket
                    value += 15 * min(len(self.neighbors[cell]), 3)
        else:
            # Defender: close in on the invaders and stop them eating.
            if me.is_pacman:
                value -= 1000   # never chase across the border
            if me.scared_timer > 0:
                value -= self.SCARED_PENALTY   # the invader got a capsule
            for e in self.root['enemies']:
                enemy = state.get_agent_state(e)
                enemy_pos = enemy.get_position()
                if enemy_pos is None:
                    continue
                epos = (int(enemy_pos[0]), int(enemy_pos[1]))
                value -= 20 * self.dist(cell, epos)
                value -= 30 * enemy.num_carrying
                if enemy.is_pacman:
                    value -= self.invader_race(cell, epos)
        return value

    def invader_race(self, cell, invader):
        """
        Penalty for what the invader can reach before any of our ghosts (us at
        `cell` plus home teammates where they stand): a way out over the
        border, its lead to the best exit, our food and our capsules. Getting
        in front of the invader, rather than following it, lowers this.
        """
        key = (cell, invader)
        race = self.root['race']
        if key in race:
            return race[key]
        guards = [cell] + self.root['mates']

        def first(target):
            return self.dist(invader, target) < min(self.dist(g, target) for g in guards)

        lead = max(min(self.dist(g, b) for g in guards) - self.dist(invader, b) for b in self.home_border)
        penalty = self.EXIT_LEAD_WEIGHT * max(-self.EXIT_LEAD_CAP, min(lead, self.EXIT_LEAD_CAP))
        if lead > 0:
            penalty += self.ESCAPE_PENALTY
        penalty += self.FOOD_FIRST_WEIGHT * sum(1 for f in self.root['def_food'] if first(f))
        penalty += self.CAPSULE_FIRST_PENALTY * sum(1 for c in self.root['def_caps'] if first(c))
        race[key] = penalty
        return penalty

    def home_escape_gap(self, me, invader):
        """How much closer we are than the invader to the border it would flee over."""
        exit_cell = min(self.home_border, key=lambda b: self.dist(invader, b))
        return self.dist(invader, exit_cell) - self.dist(me, exit_cell)

    # ------------------------------------------------------------------ #
    # Attack                                                              #
    # ------------------------------------------------------------------ #

    def attack(self, game_state, carry_limit=None):
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        carrying = my_state.num_carrying
        food = self.get_food(game_state).as_list()
        capsules = self.get_capsules(game_state)
        ghosts = self.dangerous_ghosts(game_state, my_pos)
        deadlock = self.deadlocked(game_state)
        seen_ghosts = list(ghosts)
        if deadlock:
            # Also count unseen guards at their believed cells, so stepping
            # across the border (and seeing them) doesn't flip the plan (F19).
            for e in self.get_opponents(game_state):
                st = game_state.get_agent_state(e)
                if st.get_position() is None and not st.is_pacman and st.scared_timer == 0:
                    g = self.most_likely(e)
                    if not self.is_home(g):
                        ghosts.append(g)
        home_dist = self.home_distance(my_pos)
        cost_fn = self.ghost_cost_fn(ghosts)
        blocked = self.ghost_blocked(ghosts) if my_state.is_pacman else set()
        nearest_ghost = min((self.dist(my_pos, g) for g in ghosts), default=INF)
        moves_left = self.moves_left(game_state)
        if not my_state.is_pacman or carrying == 0:
            self.banking = False

        # 1. Out of time, or carrying the win: bank what we carry.
        must_return = carrying > 0 and moves_left <= home_dist + self.SAFETY_MARGIN
        wins_game = carrying > 0 and len(food) <= 2
        if must_return or wins_game:
            return self.go_home(game_state, cost_fn, blocked)

        # 2. A scared ghost we can surely catch: eat it, it costs the enemy a
        #    long walk. Only when it is adjacent (stepping on it eats it) or
        #    trapped in a pocket we block; chasing a free one just loops
        #    around a block until its timer runs out (F16).
        prey = [g for g, t in self.enemy_ghosts(game_state)
                if t > 2 and not self.is_home(g) and self.catchable(my_pos, g, t)]
        if prey and my_state.is_pacman:
            act = self.step_towards(game_state, prey, cost_fn, self.ghost_blocked(ghosts))
            if act:
                return act

        # 3. Chased: grab a capsule if we win the race, else run home.
        if ghosts and nearest_ghost <= self.DANGER_RADIUS and my_state.is_pacman:
            safe_caps = [c for c in capsules
                         if all(self.dist(my_pos, c) < self.dist(g, c) for g in ghosts)]
            if safe_caps:
                act = self.step_towards(game_state, safe_caps, cost_fn, blocked)
                if act:
                    return act
            if carrying > 0 or nearest_ghost <= 2:
                return self.go_home(game_state, cost_fn, blocked)

        # 4. Carrying enough: go bank it. Carry more while the guards are
        #    scared, less when home is far or the score is close to winning.
        if carry_limit is None:
            carry_limit = self.CARRY_LIMIT
            if home_dist > 15:
                carry_limit -= 2
            min_scared = min((t for _, t in self.enemy_ghosts(game_state)), default=0)
            if self.enemies_scared(game_state) > home_dist + 5:
                carry_limit = 100
            elif min_scared:
                carry_limit += 3
            if deadlock and carry_limit < 100:
                carry_limit = 1   # one dot wins a tied game: bank it
        # Once we decide to bank, stick to it: the limit changes as we move
        # (e.g. at 15 steps from home), which used to flip us back and forth.
        if carry_limit >= 100:
            self.banking = False
        if carrying >= carry_limit or self.banking:
            self.banking = True
            return self.go_home(game_state, cost_fn, blocked)

        # 4b. The guards are about to recover: bank what we carry while the
        #     way home is still free (F16, user's idea).
        scared_left = self.enemies_scared(game_state)
        if scared_left and carrying > 0 and scared_left <= home_dist + self.SCARED_BANK_MARGIN:
            self.banking = True
            return self.go_home(game_state, cost_fn, blocked)

        # 5. Eat safe food, avoiding the teammate's target.
        targets = self.safe_food(my_pos, food, ghosts)
        if scared_left and carrying > 0:
            # Only food we can still bring home before the guards recover.
            in_time = [f for f in targets if self.dist(my_pos, f) + self.home_distance(f)
                       + self.SCARED_BANK_MARGIN < scared_left]
            if not in_time:
                self.banking = True
                return self.go_home(game_state, cost_fn, blocked)
            targets = in_time
        mate_target = self.mate_target()
        if mate_target is not None and len(targets) > 3:
            targets = [f for f in targets if self.dist(f, mate_target) > 4] or targets
        if self.AVOID_MATE_ROOM:
            # F20d: one guard can seal a trap room; never be in it together.
            mate = [i for i in self.get_team(game_state) if i != self.index][0]
            spots = [p for p in (game_state.get_agent_position(mate), mate_target) if p is not None]
            spots = [(int(p[0]), int(p[1])) for p in spots if p in self.rooms]
            if spots and not any(self.same_room(my_pos, p) for p in spots):
                targets = [f for f in targets
                           if not any(self.same_room(f, p) for p in spots)] or targets
        if not targets:
            if carrying > 0:
                return self.go_home(game_state, cost_fn, blocked)
            if deadlock:
                # Standoff in a tied game: go for the cheapest food anyway
                # (never next to a ghost) instead of sliding along the border.
                # Same blocked cells on both sides of the border, or the route
                # flips every time we step across.
                # Only guards we see block the way; believed ones (often a few
                # cells off) just cost, or they can seal every corridor (F19b).
                # The bait (Raider) walks right up to the guards: it carries
                # nothing, so being eaten only costs time, and a guard that
                # chases it leaves its corridor to the teammate.
                bold_block = set(seen_ghosts) if self.BAIT else self.ghost_blocked(seen_ghosts)
                step, _ = self.plan(game_state, [f for f in food if f not in bold_block], cost_fn, bold_block)
                if step is not None:
                    self.baiting = self.BAIT
                    return self.action_to(game_state, step)
            return self.reposition(game_state, ghosts, cost_fn, blocked)

        # Prefer food close to us, far from where the guards probably are,
        # and (when carrying) not too far from home.
        guards = [self.most_likely(e) for e in self.get_opponents(game_state)
                  if not game_state.get_agent_state(e).is_pacman]
        guards = [g for g in guards if not self.is_home(g)]
        scared = self.enemies_scared(game_state)

        def appeal(f):
            v = self.dist(my_pos, f)
            if guards and not scared:
                v -= 0.3 * min(self.dist(g, f) for g in guards)
            if carrying > 0:
                v += 0.15 * carrying * self.home_distance(f)
            return v
        target = min(targets, key=appeal)

        # Close to home with a decent haul and the next dot far away: bank first.
        if carrying >= 3 and self.dist(my_pos, target) > 2 * home_dist + 2:
            self.banking = True
            return self.go_home(game_state, cost_fn, blocked)

        step, _ = self.plan(game_state, [target], cost_fn, blocked)
        if step is None:
            step, _ = self.plan(game_state, targets, cost_fn, blocked)
        if step is None:
            return self.go_home(game_state, cost_fn, blocked)
        self.team()['targets'][self.index] = target
        return self.action_to(game_state, step)

    def catchable(self, my_pos, ghost, scared):
        """A scared ghost we can surely eat before its timer runs out."""
        d = self.dist(my_pos, ghost)
        if d == 1:
            return True   # we move now: stepping onto it eats it
        if d > min(scared - 1, self.PREY_TRAP_RANGE) or self.depth.get(ghost, 0) == 0:
            return False
        mouth = self.entrance[ghost]
        # Trapped: we are closer to the pocket's only way out than it is.
        return self.dist(my_pos, mouth) < self.dist(ghost, mouth)

    def enemies_scared(self, game_state):
        """Moves the enemy ghosts stay scared for (0 if any is not scared)."""
        timers = [game_state.get_agent_state(e).scared_timer for e in self.get_opponents(game_state)
                  if not game_state.get_agent_state(e).is_pacman]
        return min(timers) if timers else 0

    def reposition(self, game_state, ghosts, cost_fn=None, blocked=frozenset()):
        """
        Blocked by a guard: slide along our border to the crossing point that
        is furthest from every enemy ghost, seen or believed.
        """
        my_pos = game_state.get_agent_position(self.index)
        guards = list(ghosts) + [self.most_likely(e) for e in self.get_opponents(game_state)
                                 if not game_state.get_agent_state(e).is_pacman
                                 and game_state.get_agent_state(e).get_position() is None]
        if not guards:
            return self.go_home(game_state, cost_fn, blocked)

        def appeal(b):
            return min(self.dist(g, b) for g in guards) - 0.3 * self.dist(my_pos, b)
        target = max(self.home_border, key=appeal)
        act = self.step_towards(game_state, [target], cost_fn, blocked)
        return act or self.go_home(game_state, cost_fn, blocked)

    def safe_food(self, my_pos, food, ghosts):
        """Food not inside a pocket where a ghost could trap us."""
        if not ghosts:
            return food
        safe = []
        for f in food:
            d_me = self.dist(my_pos, f)
            if any(self.dist(g, f) <= d_me for g in ghosts):
                continue  # ghost is closer to it than we are
            if self.depth[f] > 0:
                e = self.entrance[f]
                escape = d_me + self.depth[f]
                if any(self.dist(g, e) <= escape for g in ghosts):
                    continue  # ghost reaches the pocket exit before we get out
            safe.append(f)
        return safe

    def mate_target(self):
        for idx, target in self.team()['targets'].items():
            if idx != self.index:
                return target
        return None

    def go_home(self, game_state, cost_fn=None, blocked=frozenset()):
        self.went_home = True
        self.team()['targets'].pop(self.index, None)
        step, _ = self.plan(game_state, self.home_border, cost_fn, blocked)
        if step is None:
            step, _ = self.plan(game_state, self.home_border, cost_fn)
        if step is None:
            return self.flee(game_state)
        return self.action_to(game_state, step)

    def flee(self, game_state):
        """Move that maximises distance from the nearest dangerous ghost."""
        my_pos = game_state.get_agent_position(self.index)
        ghosts = self.dangerous_ghosts(game_state, my_pos)
        best, best_score = Directions.STOP, -INF
        for a in game_state.get_legal_actions(self.index):
            succ = game_state.generate_successor(self.index, a)
            pos = succ.get_agent_position(self.index)
            score = min((self.dist(pos, g) for g in ghosts), default=0)
            score -= self.depth.get(pos, 0) * 0.5
            if score > best_score:
                best, best_score = a, score
        return best

    # ------------------------------------------------------------------ #
    # Defence                                                             #
    # ------------------------------------------------------------------ #

    def defend(self, game_state, others=()):
        """
        Guard our half. `others` are invader positions a teammate is already
        handling: we take a different one when there is a choice.
        """
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()

        if not self.is_home(my_pos):
            ghosts = self.dangerous_ghosts(game_state, my_pos)
            return self.go_home(game_state, self.ghost_cost_fn(ghosts), self.ghost_blocked(ghosts))

        invaders = self.invader_positions(game_state)
        mine = [p for i, p in invaders if p not in others] or [p for _, p in invaders]
        mine = [p for p in mine if self.is_home(p)]

        if mine:
            target = min(mine, key=lambda p: self.dist(my_pos, p))
            if my_state.scared_timer > 0:
                # Scared: shadow the invader at distance 2 without touching it,
                # ready to pounce the moment the timer runs out.
                ring = [c for c in self.home_cells if self.dist(c, target) == 2]
                act = self.step_towards(game_state, ring or self.home_border,
                                        self.ghost_cost_fn([target]), self.enemy_side | {target})
                if act:
                    return act
                return self.flee_from(game_state, target)
            goal = self.intercept_point(my_pos, target)
            act = self.step_towards(game_state, [goal], blocked=self.enemy_side)
            if act:
                return act

        # Nobody inside: patrol the border where the next attack most likely comes.
        act = self.step_towards(game_state, [self.patrol_point(game_state)], blocked=self.enemy_side)
        if act:
            return act
        # Already at the patrol point: hold position (stopping keeps us on the choke point).
        nearby = [b for b in self.home_border if 0 < self.dist(my_pos, b) <= 2]
        if nearby and random.random() < 0.3:
            act = self.step_towards(game_state, [random.choice(nearby)], blocked=self.enemy_side)
            if act:
                return act
        return Directions.STOP

    def intercept_point(self, my_pos, invader):
        """
        Where to run to catch an invader. If it is inside a pocket and we can
        reach the pocket's mouth first, close the mouth; if we can reach its
        escape crossing first, go there; otherwise chase it directly.
        """
        d_me = self.dist(my_pos, invader)
        if d_me <= 2:
            return invader
        if self.depth.get(invader, 0) > 0:
            mouth = self.entrance[invader]
            if self.is_home(mouth) and self.dist(my_pos, mouth) < self.dist(invader, mouth):
                return mouth
        exit_cell = min(self.home_border, key=lambda b: self.dist(invader, b))
        if self.dist(my_pos, exit_cell) + 1 < self.dist(invader, exit_cell) and d_me > 5:
            # Ahead of it on its way out: step towards it from the exit side.
            path_cells = [c for c in self.home_cells
                          if self.dist(c, invader) + self.dist(c, exit_cell) == self.dist(invader, exit_cell)
                          and self.dist(my_pos, c) < self.dist(invader, c)]
            if path_cells:
                return min(path_cells, key=lambda c: self.dist(c, invader))
        return invader

    def flee_from(self, game_state, threat):
        best, best_d = Directions.STOP, -INF
        for a in game_state.get_legal_actions(self.index):
            succ = game_state.generate_successor(self.index, a)
            pos = succ.get_agent_position(self.index)
            if not self.is_home(pos):
                continue
            d = self.dist(pos, threat)
            if d > best_d:
                best, best_d = a, d
        return best

    def patrol_point(self, game_state):
        food = self.get_food_you_are_defending(game_state).as_list()
        caps = self.get_capsules_you_are_defending(game_state)
        guarded = food + caps
        if not guarded:
            return random.choice(self.home_border)
        threats = [self.most_likely(e) for e in self.get_opponents(game_state)
                   if not game_state.get_agent_state(e).is_pacman]
        threat = min(threats, key=lambda c: self.home_distance(c)) if threats else None

        def score(b):
            food_term = sum(self.dist(b, f) for f in guarded) / len(guarded)
            threat_term = self.dist(b, threat) if threat else 0
            return 0.5 * food_term + threat_term
        return min(self.home_border, key=score)

    def hunt_nearby_invader(self, game_state, radius=4):
        """A ghost at home eats any invader close by, whatever its role."""
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        if my_state.is_pacman or my_state.scared_timer > 0:
            return None
        close = [p for _, p in self.invaders(game_state)
                 if p is not None and self.dist(my_pos, p) <= radius]
        if not close:
            return None
        return self.step_towards(game_state, close, blocked=self.enemy_side)


class RaiderAgent(SmartAgent):
    """
    Mostly collects food. Turns back to help when the defence is overrun,
    and guards a lead at the end of the game.
    """

    BAIT = True

    def decide(self, game_state):
        score = self.get_score(game_state)
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        moves_left = self.moves_left(game_state)
        carrying = my_state.num_carrying

        # Protect a lead at the end: there is no time left to score more safely.
        late = moves_left < 50 + self.home_distance(my_pos)
        if late and score > 0 and carrying == 0:
            return self.defend(game_state, others=self.mate_handling(game_state))

        # Two invaders at once overwhelm a single defender: help out while we
        # are still on our side and one of them is close to us.
        if not my_state.is_pacman and carrying == 0 and my_state.scared_timer == 0:
            invaders = self.invader_positions(game_state)
            if len(invaders) >= 2:
                near = [p for _, p in invaders if self.dist(my_pos, p) <= 8]
                if near:
                    return self.defend(game_state, others=self.mate_handling(game_state))

        return self.hunt_nearby_invader(game_state) or self.attack(game_state)

    def mate_handling(self, game_state):
        """Invader positions closest to our teammate (it will take those)."""
        mate = [i for i in self.get_team(game_state) if i != self.index][0]
        mate_pos = game_state.get_agent_position(mate)
        invaders = [p for _, p in self.invader_positions(game_state)]
        if len(invaders) < 2:
            return ()
        return (min(invaders, key=lambda p: self.dist(mate_pos, p)),)


class WardenAgent(SmartAgent):
    """
    Guards home, but raids when nobody is coming and joins the attack
    when the opponents do not attack or when we are behind late on.
    """

    def decide(self, game_state):
        score = self.get_score(game_state)
        my_state = game_state.get_agent_state(self.index)
        moves_left = self.moves_left(game_state)
        invaders = self.invaders(game_state)
        team = self.team()

        # Already over there with food: finish the job sensibly.
        if my_state.is_pacman and my_state.num_carrying > 0 and not invaders:
            return self.attack(game_state, carry_limit=self.RAID_CARRY + 2)

        if invaders:
            return self.defend(game_state)

        # Behind late in the game: everyone attacks.
        if score <= 0 and moves_left < 150:
            return self.attack(game_state)

        # Opponents that hardly ever attack (turtles) need no full-time guard.
        turns = max(1, len(self.observation_history))
        attacks = max(team['invader_turns'].values()) / (2.0 * turns)
        passive = turns > 60 and attacks < 0.05

        # Raid: the beliefs say both enemies are far from our border, so
        # grab a few dots and be back before they can reach our food.
        threats = [self.home_distance(self.most_likely(e)) for e in self.get_opponents(game_state)
                   if not game_state.get_agent_state(e).is_pacman]
        raid = len(threats) == 2 and min(threats) >= self.RAID_DIST
        if passive and score <= 3:
            return self.attack(game_state, carry_limit=self.RAID_CARRY + 2)
        if raid and my_state.num_carrying < self.RAID_CARRY and not (score > 0 and moves_left < 100):
            return self.attack(game_state, carry_limit=self.RAID_CARRY)
        return self.defend(game_state)


class FlexAgent(RaiderAgent):
    """
    Attacks by default like the Raider, but drops back to defend when an
    invader comes close to it on our side, or always when an invader is
    carrying a dangerous haul. Defence is adaptive: if many turns spent
    defending have not caught anyone (an evasive opponent), it stops
    chasing nearby invaders and only reacts to big hauls.
    """

    DEFEND_RADIUS = 8
    DANGER_HAUL = 4
    FREE_DEFENCE = 40       # defend turns allowed before catches are required
    TURNS_PER_CATCH = 40    # each catch buys this many more defend turns
    BAIT = False            # in a deadlock Flex is the runner, not the bait
    AVOID_MATE_ROOM = True  # don't follow the Raider into a trap room (F20d)

    def register_initial_state(self, game_state):
        RaiderAgent.register_initial_state(self, game_state)
        self.defend_turns = 0
        self.catches = 0

    def give_up_haul(self, game_state):
        """
        F20a: pinned with food and unable to bank, Flex walks into the guard.
        The food goes back on the map (it was never reaching home anyway) and
        Flex respawns at home, where it can defend again. Only when that
        defence matters: an enemy is attacking or we are not ahead.
        """
        my_state = game_state.get_agent_state(self.index)
        if not my_state.is_pacman or my_state.num_carrying == 0:
            self.sacrificing = False
            return None
        if not self.sacrificing:
            if not self.trapped:
                return None
            if not self.invaders(game_state) and self.get_score(game_state) > 0:
                return None
            self.sacrificing = True
        my_pos = my_state.get_position()
        ghosts = self.dangerous_ghosts(game_state, my_pos)
        if not ghosts:
            self.sacrificing = False   # the guard left: banking is possible again
            return None
        act = self.step_towards(game_state, ghosts)
        if act is None:
            return None
        self.baiting = True            # keep the fight search from pulling us back
        return act

    def count_catches(self, game_state):
        """An invader that was next to us last turn and is now gone or back at spawn was eaten by us."""
        prev = self.get_previous_observation()
        if prev is None or prev.get_agent_state(self.index).is_pacman:
            return
        my_prev = prev.get_agent_position(self.index)
        for e in self.get_opponents(game_state):
            st = prev.get_agent_state(e)
            p = st.get_position()
            if p is None or not st.is_pacman or self.dist(my_prev, p) > 1:
                continue
            now = game_state.get_agent_position(e)
            if now is None or now == game_state.get_initial_agent_position(e):
                self.catches += 1

    def decide(self, game_state):
        self.count_catches(game_state)
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        worth_it = self.defend_turns < self.FREE_DEFENCE + self.TURNS_PER_CATCH * self.catches
        act = self.give_up_haul(game_state)
        if act is not None:
            return act
        if my_state.num_carrying == 0 and self.deadlocked(game_state):
            # Tied late: the Raider pushes alone; Flex guards home so the push
            # can't hand the opponent the winning dot (F19c).
            return self.defend(game_state, others=self.mate_handling(game_state))
        if my_state.num_carrying == 0 and my_state.scared_timer == 0:
            for i, p in self.invader_positions(game_state):
                carrying = game_state.get_agent_state(i).num_carrying
                close = self.dist(my_pos, p) <= self.DEFEND_RADIUS and not my_state.is_pacman
                if close and carrying == 0 and self.deadlocked(game_state):
                    close = False   # an empty-handed invader can't score: don't let it pin us (F19)
                if (close and worth_it) or carrying >= self.DANGER_HAUL:
                    self.defend_turns += 1
                    return self.defend(game_state, others=self.mate_handling(game_state))
        return RaiderAgent.decide(self, game_state)
