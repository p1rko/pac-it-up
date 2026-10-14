# my_team.py
# ---------------
# Licensing Information: Please do not distribute or publish solutions to this
# project. You are free to use and extend these projects for educational
# purposes. The Pacman AI projects were developed at UC Berkeley, primarily by
# John DeNero (denero@cs.berkeley.edu) and Dan Klein (klein@cs.berkeley.edu).
# For more info, see http://inst.eecs.berkeley.edu/~cs188/sp09/pacman.html
#
# strategies/blitz.py -- sparring opponent used for testing.
#
# Sparring team "Blitz": two AttackAgents from Strategy C (search.py), no dedicated defender.
#
# Strategy C ("Adversarial Search"): Strategy B, plus a time-boxed alpha-beta
# search whenever a fight is close -- a ghost hunting our Pacman, or an
# invader near our defender. Outside fights it plays exactly like B.
#
# Strategy B ("Tracking"): Strategy A plus a probability map of where every
# unseen enemy is (exact inference from noisy distances, vision and vanished
# food). With it the defender hunts invaders it cannot see, patrols where the
# next attacker will cross and raids when both enemies are far away; the
# attacker picks food far from the enemy guards and, when blocked, slides
# along the border to the crossing furthest from them.

import heapq
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
                first='AttackAgent', second='AttackAgent', num_training=0):
    """
    Returns the two agents that form the team. The tournament calls this
    without extra arguments, so the defaults are the submitted team.
    """
    return [eval(first)(first_index), eval(second)(second_index)]


##########
# Agents #
##########

INF = float('inf')


class SearchTimeout(Exception):
    pass


class SmartAgent(CaptureAgent):
    """
    Shared machinery: map analysis, path planning and opponent bookkeeping.
    """

    # Tunable parameters
    CARRY_LIMIT = 6         # return home after carrying this many dots
    DANGER_RADIUS = 5       # ghosts closer than this make us cautious
    SAFETY_MARGIN = 2       # extra moves kept to reach home before time runs out
    RAID_DIST = 6           # defender raids when both enemies are believed this far from our border
    RAID_CARRY = 4          # ... and comes back after eating this many dots

    def __init__(self, index, time_for_computing=.1):
        super().__init__(index, time_for_computing)
        self.start = None
        self.recent = deque(maxlen=8)

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

        mid = self.width // 2
        home_x = mid - 1 if self.red else mid
        enemy_x = mid if self.red else mid - 1
        self.home_border = [(home_x, y) for y in range(self.height)
                            if not self.walls[home_x][y] and not self.walls[enemy_x][y]]
        if not self.home_border:
            self.home_border = [(home_x, y) for y in range(self.height) if not self.walls[home_x][y]]

        self._compute_dead_ends()

        # Fresh shared state every game (agents are reused across games with -n).
        TEAM_INFO[self.red] = {'targets': {},
                               'beliefs': {e: {game_state.get_initial_agent_position(e): 1.0}
                                           for e in self.get_opponents(game_state)}}

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
        are pockets with one way in and out: dangerous when a ghost is near.
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

    # ------------------------------------------------------------------ #
    # Belief tracking (where are the enemies we cannot see?)               #
    # ------------------------------------------------------------------ #

    SIGHT = 5  # Manhattan distance within which enemies are visible

    def update_beliefs(self, game_state):
        """
        Exact inference over cells for every opponent, shared by both agents.
        The opponent that moved just before us is advanced one step, then all
        beliefs are filtered by the noisy distance reading, the side of the
        map the enemy is on and the fact that we cannot see it.
        """
        beliefs = self.team()['beliefs']
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

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def dist(self, a, b):
        return self.get_maze_distance(a, b)

    def is_home(self, pos):
        mid = self.width // 2
        return pos[0] < mid if self.red else pos[0] >= mid

    def moves_left(self, game_state):
        """Moves this agent still gets to make."""
        return game_state.data.timeleft // 4

    def home_distance(self, pos):
        return min(self.dist(pos, b) for b in self.home_border)

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
                if t <= self.dist(my_pos, g) + 1]

    def invaders(self, game_state):
        """Enemy pacmen as (index, position-or-None)."""
        result = []
        for i in self.get_opponents(game_state):
            st = game_state.get_agent_state(i)
            if st.is_pacman:
                result.append((i, st.get_position()))
        return result

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
    # Adversarial search for close fights                                 #
    # ------------------------------------------------------------------ #

    SEARCH_TIME = 0.35   # seconds of search per move (limit is 1 s on a slow machine)
    FIGHT_RANGE = 6      # search when the opponent is this close

    def get_action(self, game_state):
        self.turn_start = time.time()
        return CaptureAgent.get_action(self, game_state)

    def fight_opponent(self, game_state):
        """The visible enemy we are in a fight with, or None."""
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        best, best_d = None, INF
        for e in self.get_opponents(game_state):
            st = game_state.get_agent_state(e)
            pos = st.get_position()
            if pos is None:
                continue
            d = self.dist(my_pos, pos)
            if my_state.is_pacman:
                relevant = not st.is_pacman and st.scared_timer <= d + 1  # a ghost that can eat us
            else:
                relevant = st.is_pacman and my_state.scared_timer == 0 and self.is_home(pos)
            if relevant and d <= self.FIGHT_RANGE and d < best_d:
                best, best_d = e, d
        return best

    def search(self, game_state, enemy, default):
        """Iterative-deepening alpha-beta: us against one enemy."""
        deadline = getattr(self, 'turn_start', time.time()) + self.SEARCH_TIME
        enemy_state = game_state.get_agent_state(enemy)
        self.root = {
            'pacman': game_state.get_agent_state(self.index).is_pacman,
            'enemy': enemy,
            'enemy_start': game_state.get_initial_agent_position(enemy),
            'enemy_far_from_start': self.dist(enemy_state.get_position(),
                                              game_state.get_initial_agent_position(enemy)) > 1,
            'food': self.get_food(game_state).as_list(),
        }
        best = default
        depth = 2
        try:
            while depth <= 12:
                _, action = self.max_value(game_state, depth, -INF, INF, deadline, default)
                if action is not None:
                    best = action
                depth += 2
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

    def max_value(self, state, depth, alpha, beta, deadline, first=None):
        if time.time() > deadline:
            raise SearchTimeout()
        if depth == 0 or state.is_over() or self.fight_over(state):
            return self.evaluate_fight(state), None
        best_v, best_a = -INF, None
        for a in self.ordered_actions(state, self.index, first):
            v = self.min_value(state.generate_successor(self.index, a), depth - 1, alpha, beta, deadline)
            if v > best_v:
                best_v, best_a = v, a
            if best_v >= beta:
                break
            alpha = max(alpha, best_v)
        return best_v, best_a

    def min_value(self, state, depth, alpha, beta, deadline):
        if time.time() > deadline:
            raise SearchTimeout()
        enemy = self.root['enemy']
        if depth == 0 or state.is_over() or self.fight_over(state):
            return self.evaluate_fight(state)
        best_v = INF
        for a in self.ordered_actions(state, enemy):
            v, _ = self.max_value(state.generate_successor(enemy, a), depth - 1, alpha, beta, deadline)
            best_v = min(best_v, v)
            if best_v <= alpha:
                break
            beta = min(beta, best_v)
        return best_v

    def fight_over(self, state):
        """Someone got eaten: no point searching further down this line."""
        my_pos = state.get_agent_position(self.index)
        enemy_pos = state.get_agent_position(self.root['enemy'])
        died = self.root['pacman'] and my_pos == self.start
        ate = self.root['enemy_far_from_start'] and enemy_pos == self.root['enemy_start']
        return died or ate

    def evaluate_fight(self, state):
        me = state.get_agent_state(self.index)
        pos = me.get_position()
        cell = (int(pos[0]), int(pos[1]))
        enemy = state.get_agent_state(self.root['enemy'])
        enemy_pos = enemy.get_position()

        if self.root['pacman'] and pos == self.start:
            return -100000  # we were eaten
        value = 1000 * self.get_score(state)
        if self.root['enemy_far_from_start'] and enemy_pos == self.root['enemy_start']:
            value += 5000   # we ate the enemy

        if self.root['pacman']:
            # Survive, keep the food we carry, get closer to home and to food.
            carrying = me.num_carrying
            value += 50 * carrying
            if carrying > 0:
                value -= 5 * self.home_distance(cell)
            food = [f for f in self.root['food'] if state.has_food(f[0], f[1])]
            if food:
                value -= min(self.dist(cell, f) for f in food)
            if enemy_pos is not None and enemy.scared_timer <= 1:
                d = self.dist(cell, enemy_pos)
                if d <= 1:
                    value -= 500
                elif d == 2:
                    value -= 100
                if d <= 4:
                    value -= 15 * self.depth.get(cell, 0)  # don't get trapped in a pocket
        else:
            # Defender: close in on the invader and stop it eating.
            if me.is_pacman:
                value -= 1000   # never chase across the border
            if enemy_pos is not None:
                value -= 20 * self.dist(cell, enemy_pos)
            value -= 30 * enemy.num_carrying
        return value

    def finish(self, game_state, action):
        enemy = self.fight_opponent(game_state)
        if enemy is not None:
            action = self.search(game_state, enemy, action)
        legal = game_state.get_legal_actions(self.index)
        if action not in legal:
            non_stop = [a for a in legal if a != Directions.STOP]
            action = random.choice(non_stop or legal)
        self.recent.append(game_state.get_agent_position(self.index))
        return action

    def team(self):
        return TEAM_INFO[self.red]

    # ------------------------------------------------------------------ #
    # Behaviours                                                           #
    # ------------------------------------------------------------------ #

    def attack(self, game_state):
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        carrying = my_state.num_carrying
        food = self.get_food(game_state).as_list()
        capsules = self.get_capsules(game_state)
        ghosts = self.dangerous_ghosts(game_state, my_pos)
        home_dist = self.home_distance(my_pos)
        cost_fn = self.ghost_cost_fn(ghosts)
        blocked = self.ghost_blocked(ghosts) if my_state.is_pacman else set()
        nearest_ghost = min((self.dist(my_pos, g) for g in ghosts), default=INF)

        # 1. Out of time or nothing left to eat: bank what we carry.
        must_return = (carrying > 0 and
                       self.moves_left(game_state) <= home_dist + self.SAFETY_MARGIN)
        if len(food) <= 2 or must_return:
            return self.go_home(game_state, cost_fn, blocked)

        # 2. Chased: grab a capsule if we win the race, else run home.
        if ghosts and nearest_ghost <= self.DANGER_RADIUS and my_state.is_pacman:
            safe_caps = [c for c in capsules
                         if all(self.dist(my_pos, c) < self.dist(g, c) for g in ghosts)]
            if safe_caps:
                step, _ = self.plan(game_state, safe_caps, cost_fn, blocked)
                if step:
                    return self.action_to(game_state, step)
            if carrying > 0 or nearest_ghost <= 2:
                return self.go_home(game_state, cost_fn, blocked)

        # 3. Carrying enough: go bank it (sooner when home is far).
        limit = self.CARRY_LIMIT if home_dist < 15 else self.CARRY_LIMIT - 2
        if carrying >= limit:
            return self.go_home(game_state, cost_fn, blocked)

        # 4. Eat safe food, avoiding the teammate's target.
        targets = self.safe_food(my_pos, food, ghosts)
        mate_target = self.mate_target()
        if mate_target is not None and len(targets) > 3:
            targets = [f for f in targets if self.dist(f, mate_target) > 4] or targets
        if not targets:
            if carrying > 0:
                return self.go_home(game_state, cost_fn, blocked)
            return self.reposition(game_state, ghosts, cost_fn, blocked)
        # Prefer food that is close to us and far from where enemy ghosts probably are.
        guards = [self.most_likely(e) for e in self.get_opponents(game_state)
                  if not game_state.get_agent_state(e).is_pacman]
        guards = [g for g in guards if not self.is_home(g)]
        if guards:
            def appeal(f):
                return self.dist(my_pos, f) - 0.3 * min(self.dist(g, f) for g in guards)
            target = min(targets, key=appeal)
        else:
            target = min(targets, key=lambda f: self.dist(my_pos, f))
        step, _ = self.plan(game_state, [target], cost_fn, blocked)
        if step is None:
            step, _ = self.plan(game_state, targets, cost_fn, blocked)
        if step is None:
            return self.go_home(game_state, cost_fn, blocked)
        self.team()['targets'][self.index] = target
        return self.action_to(game_state, step)

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
        step, _ = self.plan(game_state, [target], cost_fn, blocked)
        if step is None or step == my_pos:
            return self.go_home(game_state, cost_fn, blocked)
        return self.action_to(game_state, step)

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

    def defend(self, game_state):
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        invaders = self.invaders(game_state)
        visible = [p for _, p in invaders if p is not None]

        if not self.is_home(my_pos):
            ghosts = self.dangerous_ghosts(game_state, my_pos)
            return self.go_home(game_state, self.ghost_cost_fn(ghosts), self.ghost_blocked(ghosts))

        # Stay on our side: never step across the border while defending.
        enemy_side = {c for c in self.cells if not self.is_home(c)}

        if visible:
            target = min(visible, key=lambda p: self.dist(my_pos, p))
            if my_state.scared_timer > 0:
                # Scared: shadow the invader at distance 2 without touching it.
                ring = [c for c in self.cells if self.is_home(c) and self.dist(c, target) == 2]
                step, _ = self.plan(game_state, ring or self.home_border,
                                    self.ghost_cost_fn([target]), enemy_side | {target})
            else:
                step, _ = self.plan(game_state, [target], blocked=enemy_side)
            if step:
                return self.action_to(game_state, step)

        # Invisible invaders: head for where the belief says they most likely are.
        hidden = [i for i, p in invaders if p is None]
        if hidden:
            guesses = [self.most_likely(i) for i in hidden]
            guess = min(guesses, key=lambda c: self.dist(my_pos, c))
            if self.is_home(guess):
                step, _ = self.plan(game_state, [guess], blocked=enemy_side)
                if step and step != my_pos:
                    return self.action_to(game_state, step)

        # Patrol the border cell nearest to the food we still defend.
        step, _ = self.plan(game_state, [self.patrol_point(game_state)], blocked=enemy_side)
        if step and step != my_pos:
            return self.action_to(game_state, step)
        # Already at the patrol point: wiggle along the border instead of stopping.
        nearby = [b for b in self.home_border if 0 < self.dist(my_pos, b) <= 3]
        if nearby:
            step, _ = self.plan(game_state, [random.choice(nearby)], blocked=enemy_side)
            if step:
                return self.action_to(game_state, step)
        return Directions.STOP

    def eaten_food(self, game_state):
        prev = self.get_previous_observation()
        if prev is None:
            return []
        before = set(self.get_food_you_are_defending(prev).as_list())
        now = set(self.get_food_you_are_defending(game_state).as_list())
        return list(before - now)

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

    def hunt_nearby_invader(self, game_state):
        """A ghost at home eats any invader close by, whatever its role."""
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        if my_state.is_pacman or my_state.scared_timer > 0:
            return None
        close = [p for _, p in self.invaders(game_state)
                 if p is not None and self.dist(my_pos, p) <= 4]
        if not close:
            return None
        enemy_side = {c for c in self.cells if not self.is_home(c)}
        step, _ = self.plan(game_state, close, blocked=enemy_side)
        return self.action_to(game_state, step) if step else None


class AttackAgent(SmartAgent):
    """Collects food; drops back to defence when protecting a late lead."""

    def choose_action(self, game_state):
        self.update_beliefs(game_state)
        score = self.get_score(game_state)
        my_state = game_state.get_agent_state(self.index)
        late = self.moves_left(game_state) < 60
        if late and score > 0 and my_state.num_carrying == 0:
            return self.finish(game_state, self.defend(game_state))
        action = self.hunt_nearby_invader(game_state) or self.attack(game_state)
        return self.finish(game_state, action)


class DefendAgent(SmartAgent):
    """Guards home; joins the attack when there is nothing to defend against."""

    def choose_action(self, game_state):
        self.update_beliefs(game_state)
        score = self.get_score(game_state)
        my_state = game_state.get_agent_state(self.index)
        no_invaders = not self.invaders(game_state)
        moves_left = self.moves_left(game_state)

        # Join the attack if we are not winning, nobody is invading and
        # the game is in its second half.
        join = no_invaders and score <= 0 and moves_left < 200

        # Raid: the beliefs say both enemies are deep in their own half, so
        # grab a couple of dots and be back before they can reach our food.
        threats = [self.home_distance(self.most_likely(e)) for e in self.get_opponents(game_state)
                   if not game_state.get_agent_state(e).is_pacman]
        raid = no_invaders and len(threats) == 2 and min(threats) >= self.RAID_DIST

        if join:
            action = self.attack(game_state)
        elif raid and my_state.num_carrying < self.RAID_CARRY:
            action = self.attack(game_state)
        else:
            action = self.defend(game_state)  # walks home first when on the enemy side
        return self.finish(game_state, action)
