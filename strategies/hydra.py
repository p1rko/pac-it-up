# hydra.py
# ---------
# Sparring opponent "Hydra", written from scratch (not derived from my_team.py
# or the strategies/ drafts) so the field has a design that plays differently:
#
#   * two identical agents; a shared coordinator re-assigns attack / defend
#     every turn by cost (no fixed attacker or defender);
#   * the enemy food is split into two clusters (k-medoids on maze distance)
#     and each attacker owns one, so they cross at different points;
#   * risk-based banking: bank when carried x P(caught before home) is high,
#     not at a fixed carry limit;
#   * planned capsules: take one early when the guards sit on our cluster;
#   * choke-point defence: hold the home cell that cuts the most
#     border-to-food paths, and intercept invaders on their way out;
#   * no game-tree search: danger-weighted Dijkstra plus a 1-ply safety check.
#
# Frozen once tuned: never tune it against our own agent (it is a test).

import heapq
import os
import random
from collections import deque

from contest.capture_agents import CaptureAgent
from contest.game import Directions, Actions

HYDRA = {}
DEBUG = bool(os.environ.get('PACKITUP_DEBUG'))
INF = float('inf')


def create_team(first_index, second_index, is_red,
                first='HydraAgent', second='HydraAgent', num_training=0):
    return [eval(first)(first_index), eval(second)(second_index)]


class HydraAgent(CaptureAgent):
    SIGHT = 5
    BANK_RISK = 1.2       # bank when carried * risk reaches this
    HARD_CAP = 10         # always bank at this many
    LONE_CARRY = 5        # an attacker carrying this many never turns back to defend
    BIG_HAUL = 6          # an invader carrying this many pulls both agents home
    DEFEND_REACH = 25     # a lone empty-handed invader is only answered from this close
    GUARD_LEAD = 6        # late lead that sends one agent home to guard ...
    GUARD_MOVES = 200     # ... with this many own moves left
    SWITCH_MARGIN = 3     # hysteresis for swapping the defender
    CAPSULE_DETOUR = 10   # proactive capsule only this far away
    TRAP_PENALTY = 30     # cost of entering a pocket a ghost can seal
    STALL_WINDOW = 10

    # ------------------------------------------------------------------ #
    # Setup                                                                #
    # ------------------------------------------------------------------ #

    def register_initial_state(self, gs):
        CaptureAgent.register_initial_state(self, gs)
        walls = gs.get_walls()
        self.W, self.H = walls.width, walls.height
        self.cells = [(x, y) for x in range(self.W) for y in range(self.H) if not walls[x][y]]
        cellset = set(self.cells)
        self.nbrs = {c: [(c[0] + dx, c[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                         if (c[0] + dx, c[1] + dy) in cellset] for c in self.cells}
        mid = self.W // 2
        hx = mid - 1 if self.red else mid
        ex = mid if self.red else mid - 1
        self.home_border = [(hx, y) for y in range(self.H) if (hx, y) in cellset and (ex, y) in cellset]
        self.enemy_border = [(ex, y) for (_, y) in self.home_border]
        self.home_dist = self._bfs(self.home_border)
        self._pockets()
        self.hist = deque(maxlen=self.STALL_WINDOW)
        self.detour = None
        self.detour_left = 0

        team = HYDRA.get(self.red)
        if team is None or team['registered'] >= 2:
            team = HYDRA[self.red] = {
                'registered': 0,
                'bel': {e: {gs.get_initial_agent_position(e): 1.0} for e in self.get_opponents(gs)},
                'targets': {},
                'defender': None,
                'cap_claim': None,
            }
        team['registered'] += 1

    def _bfs(self, sources):
        dist = {s: 0 for s in sources}
        q = deque(sources)
        while q:
            c = q.popleft()
            for n in self.nbrs[c]:
                if n not in dist:
                    dist[n] = dist[c] + 1
                    q.append(n)
        return dist

    def _pockets(self):
        """Dead-end pockets by leaf pruning: depth from the mouth and the mouth cell."""
        deg = {c: len(self.nbrs[c]) for c in self.cells}
        removed = set()
        q = deque(c for c in self.cells if deg[c] <= 1)
        while q:
            c = q.popleft()
            if c in removed:
                continue
            removed.add(c)
            for n in self.nbrs[c]:
                if n not in removed:
                    deg[n] -= 1
                    if deg[n] == 1:
                        q.append(n)
        self.depth = {c: 0 for c in self.cells}
        self.mouth = {}
        for c in self.cells:
            if c in removed:
                continue
            for n in self.nbrs[c]:
                if n in removed and n not in self.mouth:
                    self.mouth[n], self.depth[n] = c, 1
                    stack = [n]
                    while stack:
                        p = stack.pop()
                        for m in self.nbrs[p]:
                            if m in removed and m not in self.mouth:
                                self.mouth[m], self.depth[m] = c, self.depth[p] + 1
                                stack.append(m)

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    def choose_action(self, gs):
        legal = gs.get_legal_actions(self.index)
        try:
            self.observe(gs)
            action = self.decide(gs)
        except Exception:
            if DEBUG:
                raise
            action = None
        if action not in legal:
            action = random.choice([a for a in legal if a != Directions.STOP] or legal)
        self.hist.append(gs.get_agent_position(self.index))
        return action

    def decide(self, gs):
        roles = self.assign(gs)
        if roles[self.index] == 'defend':
            self.team()['targets'].pop(self.index, None)
            others = [t for i, t in self.team().get('def_targets', {}).items() if i != self.index]
            return self.defend(gs, others)
        self.team().get('def_targets', {}).pop(self.index, None)
        return self.attack(gs, roles)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def team(self):
        return HYDRA[self.red]

    def dist(self, a, b):
        return self.get_maze_distance(a, b)

    def is_home(self, c):
        mid = self.W // 2
        return c[0] < mid if self.red else c[0] >= mid

    def moves_left(self, gs):
        return gs.data.timeleft // 4

    def guess(self, e):
        b = self.team()['bel'][e]
        return max(b, key=b.get)

    def step_to(self, gs, cell):
        """Action that moves us onto the neighbouring cell `cell`."""
        pos = gs.get_agent_position(self.index)
        for a in gs.get_legal_actions(self.index):
            dx, dy = Actions.direction_to_vector(a)
            if (int(pos[0] + dx), int(pos[1] + dy)) == cell:
                return a
        return None

    def dijkstra(self, src, danger=None, blocked=()):
        danger = danger or {}
        cost = {src: 0}
        first = {src: None}
        pq = [(0, src)]
        while pq:
            d, c = heapq.heappop(pq)
            if d > cost[c]:
                continue
            for n in self.nbrs[c]:
                if n in blocked:
                    continue
                nd = d + 1 + danger.get(n, 0)
                if nd < cost.get(n, INF):
                    cost[n] = nd
                    first[n] = n if c == src else first[c]
                    heapq.heappush(pq, (nd, n))
        return cost, first

    def go_to(self, gs, goals, danger=None, blocked=()):
        """Step towards the cheapest of `goals`; None if none is reachable."""
        pos = gs.get_agent_position(self.index)
        if pos in goals:
            return None
        cost, first = self.dijkstra(pos, danger, blocked)
        reach = [g for g in goals if g in cost and g != pos]
        if not reach:
            return None
        g = min(reach, key=cost.get)
        return self.step_to(gs, first[g])

    # ------------------------------------------------------------------ #
    # Beliefs                                                              #
    # ------------------------------------------------------------------ #

    def observe(self, gs):
        team = self.team()
        bel = team['bel']
        me = gs.get_agent_position(self.index)
        mates = [gs.get_agent_position(i) for i in self.get_team(gs)]
        noisy = gs.get_agent_distances()
        mover = (self.index - 1) % gs.get_num_agents()
        for e in self.get_opponents(gs):
            st = gs.get_agent_state(e)
            pos = st.get_position()
            if pos is not None:
                bel[e] = {pos: 1.0}
                continue
            b = bel[e]
            if e == mover:
                moved = {}
                for c, p in b.items():
                    opts = self.nbrs[c] + [c]
                    for o in opts:
                        moved[o] = moved.get(o, 0.0) + p / len(opts)
                b = moved

            def ok(c):
                if self.is_home(c) != st.is_pacman:
                    return False
                return all(abs(c[0] - m[0]) + abs(c[1] - m[1]) > self.SIGHT for m in mates)

            def like(c):
                return gs.get_distance_prob(abs(c[0] - me[0]) + abs(c[1] - me[1]), noisy[e])

            new = {}
            for c, p in b.items():
                if ok(c):
                    w = p * like(c)
                    if w > 0:
                        new[c] = w
            if not new:
                spawn = gs.get_initial_agent_position(e)
                if ok(spawn) and like(spawn) > 0:
                    new = {spawn: 1.0}
                else:
                    new = {c: like(c) for c in self.cells if ok(c) and like(c) > 0} or \
                          {c: 1.0 for c in self.cells if self.is_home(c) == st.is_pacman}
            tot = sum(new.values())
            bel[e] = {c: w / tot for c, w in new.items()}

        prev = self.get_previous_observation()
        if prev is not None:
            gone = set(self.get_food_you_are_defending(prev).as_list()) - \
                set(self.get_food_you_are_defending(gs).as_list())
            gone |= set(self.get_capsules_you_are_defending(prev)) - set(self.get_capsules_you_are_defending(gs))
            hidden = [e for e in self.get_opponents(gs)
                      if gs.get_agent_state(e).is_pacman and gs.get_agent_state(e).get_position() is None]
            for cell in gone:
                if hidden:
                    e = max(hidden, key=lambda i: sum(p for c, p in bel[i].items()
                                                      if abs(c[0] - cell[0]) + abs(c[1] - cell[1]) <= 2))
                    bel[e] = {cell: 1.0}

    def invaders(self, gs):
        """(enemy, position, carrying) for every enemy Pacman, seen or believed."""
        out = []
        for e in self.get_opponents(gs):
            st = gs.get_agent_state(e)
            if st.is_pacman:
                pos = st.get_position() or self.guess(e)
                out.append((e, pos, st.num_carrying))
        return out

    def threats(self, gs, me):
        """Enemy ghosts that can eat us: (position, seen?)."""
        out = []
        for e in self.get_opponents(gs):
            st = gs.get_agent_state(e)
            if st.is_pacman:
                continue
            pos = st.get_position()
            seen = pos is not None
            if not seen:
                pos = self.guess(e)
                if self.dist(me, pos) > 7:
                    continue
            if st.scared_timer > self.dist(me, pos) + 1:
                continue   # scared long enough to be harmless here
            out.append((pos, seen))
        return out

    # ------------------------------------------------------------------ #
    # Coordinator                                                          #
    # ------------------------------------------------------------------ #

    def assign(self, gs):
        team = self.team()
        mates = self.get_team(gs)
        st = {i: gs.get_agent_state(i) for i in mates}
        pos = {i: gs.get_agent_position(i) for i in mates}
        inv = [x for x in self.invaders(gs) if self.is_home(x[1])]
        score = self.get_score(gs)
        ml = self.moves_left(gs)
        roles = {i: 'attack' for i in mates}

        if len(inv) >= 2 or any(c >= self.BIG_HAUL for _, _, c in inv):
            for i in mates:
                if st[i].num_carrying <= 2:
                    roles[i] = 'defend'
        elif len(inv) == 1:
            _, p, carried = inv[0]
            behind_late = score < 0 and ml < 120 and carried < 3
            cand = [i for i in mates if st[i].num_carrying < self.LONE_CARRY]

            def cost(i):
                return self.dist(pos[i], p) + 3 * st[i].num_carrying
            if cand and not behind_late:
                best = min(cand, key=cost)
                prev = team.get('defender')
                if prev in cand and prev != best and cost(prev) <= cost(best) + self.SWITCH_MARGIN:
                    best = prev
                if cost(best) <= self.DEFEND_REACH or carried >= 3:
                    roles[best] = 'defend'
                    team['defender'] = best
        if 'defend' not in roles.values() and score >= self.GUARD_LEAD and ml < self.GUARD_MOVES:
            guard = min(mates, key=lambda i: (st[i].num_carrying > 0, self.home_dist[pos[i]]))
            roles[guard] = 'defend'
        return roles

    # ------------------------------------------------------------------ #
    # Attack                                                               #
    # ------------------------------------------------------------------ #

    def danger_map(self, gs, me, ghosts):
        """Extra cost per cell on the enemy side near ghosts and in sealable pockets."""
        danger = {}
        for g, _ in ghosts:
            seen = {g: 0}
            q = deque([g])
            while q:
                c = q.popleft()
                d = seen[c]
                if not self.is_home(c):
                    danger[c] = danger.get(c, 0) + (5 - d) * 8
                if d < 4:
                    for n in self.nbrs[c]:
                        if n not in seen:
                            seen[n] = d + 1
                            q.append(n)
        if ghosts:
            for c, dep in self.depth.items():
                if dep == 0 or self.is_home(c):
                    continue
                m = self.mouth[c]
                reach = self.dist(me, c) + dep + 1
                if any(self.dist(g, m) <= reach for g, _ in ghosts):
                    danger[c] = danger.get(c, 0) + self.TRAP_PENALTY
        return danger

    def blocked_cells(self, ghosts, me):
        out = set()
        for g, seen in ghosts:
            if not seen:
                continue
            for c in [g] + self.nbrs[g]:
                if not self.is_home(c) and c != me:
                    out.add(c)
        return out

    def clusters(self, gs):
        """Split the enemy food into two clusters (k-medoids), cached per food count."""
        food = self.get_food(gs).as_list()
        team = self.team()
        if team.get('clu_key') == len(food):
            return team['clu']
        if len(food) < 6:
            clu = [food, food]
        else:
            a = max(food, key=lambda f: f[1])
            b = min(food, key=lambda f: f[1])
            A, B = food, []
            for _ in range(4):
                A = [f for f in food if self.dist(f, a) <= self.dist(f, b)]
                B = [f for f in food if f not in A]
                if not A or not B:
                    break
                a = min(A, key=lambda x: sum(self.dist(x, f) for f in A))
                b = min(B, key=lambda x: sum(self.dist(x, f) for f in B))
            clu = [A, B] if A and B else [food, food]
        team['clu_key'] = len(food)
        team['clu'] = clu
        team['owner'] = None
        return clu

    def my_food(self, gs, roles):
        food = self.get_food(gs).as_list()
        attackers = [i for i in self.get_team(gs) if roles[i] == 'attack']
        if len(attackers) < 2:
            return food
        A, B = self.clusters(gs)
        team = self.team()
        if team.get('owner') is None:
            i, j = attackers
            pi, pj = gs.get_agent_position(i), gs.get_agent_position(j)
            ca = min(A, key=lambda f: self.dist(pi, f))
            cb = min(B, key=lambda f: self.dist(pi, f))
            # pairing with the smaller total distance to each cluster's nearest dot
            straight = self.dist(pi, ca) + min(self.dist(pj, f) for f in B)
            crossed = self.dist(pi, cb) + min(self.dist(pj, f) for f in A)
            team['owner'] = {i: 0, j: 1} if straight <= crossed else {i: 1, j: 0}
        k = team['owner'].get(self.index, 0)
        mine = [f for f in (A, B)[k] if f in set(food)]
        return mine or food

    def attack(self, gs, roles):
        my = gs.get_agent_state(self.index)
        me = my.get_position()
        carrying = my.num_carrying
        food = self.get_food(gs).as_list()
        caps = self.get_capsules(gs)
        ghosts = self.threats(gs, me)
        danger = self.danger_map(gs, me, ghosts)
        blocked = self.blocked_cells(ghosts, me) if my.is_pacman else set()
        hd = self.home_dist[me]
        ml = self.moves_left(gs)
        score = self.get_score(gs)
        gap = min((self.dist(me, g) for g, _ in ghosts), default=INF)
        scared = [gs.get_agent_state(e).scared_timer for e in self.get_opponents(gs)
                  if not gs.get_agent_state(e).is_pacman]
        window = min(scared) if scared else 0

        # Out of time / winning haul / scared window ending: bank.
        if carrying and (ml <= hd + 4 or len(food) <= 2 or (window and window <= hd + 3)):
            return self.bank(gs, danger, blocked)
        if carrying and ml < 100 and score <= 0 < score + carrying:
            return self.bank(gs, danger, blocked)

        # Eat a scared ghost right next to us.
        for e in self.get_opponents(gs):
            st = gs.get_agent_state(e)
            p = st.get_position()
            if p and not st.is_pacman and st.scared_timer > 2 and self.dist(me, p) <= 2 and my.is_pacman:
                act = self.go_to(gs, [p], danger, blocked)
                if act:
                    return act

        # Under pressure: capsule if we win the race, else run home.
        if my.is_pacman and gap <= 3:
            safe_caps = [c for c in caps if all(self.dist(me, c) < self.dist(g, c) for g, _ in ghosts)]
            if safe_caps:
                act = self.go_to(gs, safe_caps, danger, blocked)
                if act:
                    return act
            if carrying or gap <= 2:
                return self.bank(gs, danger, blocked)

        # Risk-based banking.
        if carrying:
            if ghosts and not window:
                risk = min(1.0, max(0.05, (hd - gap + 4.0) / (hd + 4.0)))
            else:
                risk = 0.02 + hd / 100.0
            if carrying >= self.HARD_CAP and not window:
                return self.bank(gs, danger, blocked)
            if carrying * risk >= self.BANK_RISK:
                return self.bank(gs, danger, blocked)

        cost, first = self.dijkstra(me, danger, blocked)

        # Planned capsule: the guards sit on our food, a capsule is close.
        team = self.team()
        if team.get('cap_claim') not in (None, self.index) and team['cap_claim'] not in caps:
            team['cap_claim'] = None
        if caps and not window:
            guards = [self.guess(e) for e in self.get_opponents(gs) if not gs.get_agent_state(e).is_pacman]
            mine = self.my_food(gs, roles)
            dense = len(guards) == 2 and all(min((self.dist(g, f) for f in mine), default=INF) <= 6
                                             for g in guards)
            near_caps = [c for c in caps if cost.get(c, INF) <= self.CAPSULE_DETOUR]
            claim = team.get('cap_claim')
            if near_caps and (dense or claim == self.index):
                team['cap_claim'] = self.index
                act = self.go_to(gs, near_caps, danger, blocked)
                if act:
                    return act
        if team.get('cap_claim') == self.index and (window or not caps):
            team['cap_claim'] = None

        # Food: our cluster first, avoiding the teammate's target.
        mine = self.my_food(gs, roles)
        mate_t = [t for i, t in team['targets'].items() if i != self.index]

        def value(f):
            v = cost.get(f, INF)
            if carrying:
                v += 0.3 * self.home_dist[f]
            if mate_t and self.dist(f, mate_t[0]) <= 3:
                v += 6
            return v
        options = [f for f in mine if cost.get(f, INF) < INF] or [f for f in food if cost.get(f, INF) < INF]
        target = min(options, key=value) if options else None
        if target is not None and cost[target] - self.dist(me, target) >= 40:
            target = None   # every route is through a guard

        if target is None:
            if carrying:
                return self.bank(gs, danger, blocked)
            return self.probe(gs, danger)

        # Banking first is cheap and the next dot is far.
        if carrying >= 3 and cost[target] > 2 * hd + 2:
            return self.bank(gs, danger, blocked)

        # Stalled at the border: try another crossing for a while.
        if not my.is_pacman and len(self.hist) == self.STALL_WINDOW and len(set(self.hist)) <= 3:
            far = [b for b in self.home_border if self.dist(me, b) >= 5]
            if far:
                self.detour, self.detour_left = random.choice(far), 8
        if self.detour_left > 0 and not my.is_pacman:
            self.detour_left -= 1
            act = self.go_to(gs, [self.detour], danger)
            if act:
                return act
        self.detour_left = 0

        team['targets'][self.index] = target
        return self.safe(gs, self.step_to(gs, first[target]), ghosts)

    def bank(self, gs, danger, blocked):
        act = self.go_to(gs, self.home_border, danger, blocked) or self.go_to(gs, self.home_border, danger)
        if act:
            return act
        return self.flee(gs)

    def probe(self, gs, danger):
        """No safe food: wait on our side at the crossing furthest from the guards."""
        me = gs.get_agent_position(self.index)
        guards = [self.guess(e) for e in self.get_opponents(gs) if not gs.get_agent_state(e).is_pacman]
        if not guards:
            return self.go_to(gs, self.home_border, danger) or Directions.STOP
        target = max(self.home_border,
                     key=lambda b: min(self.dist(g, self.enemy_border[self.home_border.index(b)])
                                       for g in guards) - 0.2 * self.dist(me, b))
        return self.go_to(gs, [target], danger) or Directions.STOP

    def flee(self, gs):
        me = gs.get_agent_position(self.index)
        ghosts = self.threats(gs, me)
        best, best_v = Directions.STOP, -INF
        for a in gs.get_legal_actions(self.index):
            dx, dy = Actions.direction_to_vector(a)
            p = (int(me[0] + dx), int(me[1] + dy))
            v = min((self.dist(p, g) for g, _ in ghosts), default=0) - 0.5 * self.depth.get(p, 0)
            if v > best_v:
                best, best_v = a, v
        return best

    def safe(self, gs, action, ghosts):
        """1-ply check: never step next to a seen ghost on its side."""
        me = gs.get_agent_position(self.index)
        seen = [g for g, s in ghosts if s]
        if action is None or not seen:
            return action

        def bad(a):
            dx, dy = Actions.direction_to_vector(a)
            p = (int(me[0] + dx), int(me[1] + dy))
            return not self.is_home(p) and any(self.dist(p, g) <= 1 for g in seen)
        if not bad(action):
            return action
        alts = [a for a in gs.get_legal_actions(self.index) if not bad(a)]
        if not alts:
            return action

        def home_after(a):
            dx, dy = Actions.direction_to_vector(a)
            return self.home_dist[(int(me[0] + dx), int(me[1] + dy))]
        return min(alts, key=home_after)

    # ------------------------------------------------------------------ #
    # Defence                                                              #
    # ------------------------------------------------------------------ #

    def defend(self, gs, others):
        my = gs.get_agent_state(self.index)
        me = my.get_position()
        if my.is_pacman:
            ghosts = self.threats(gs, me)
            return self.bank(gs, self.danger_map(gs, me, ghosts), self.blocked_cells(ghosts, me))
        enemy_side = {c for c in self.cells if not self.is_home(c)}
        inv = [x for x in self.invaders(gs) if self.is_home(x[1])]
        defs = self.team().setdefault('def_targets', {})
        if inv:
            pick = [x for x in inv if x[1] not in others] or inv
            e, t, carried = min(pick, key=lambda x: self.dist(me, x[1]))
            defs[self.index] = t
            if my.scared_timer > 0:
                return self.shadow(gs, t)
            goal = self.intercept(gs, me, t, carried)
            return self.go_to(gs, [goal], blocked=enemy_side) or Directions.STOP
        defs.pop(self.index, None)
        post = self.guard_post(gs)
        return self.go_to(gs, [post], blocked=enemy_side) or Directions.STOP

    def shadow(self, gs, t):
        """Scared: stay two steps from the invader, ready for when the timer ends."""
        me = gs.get_agent_position(self.index)
        best, best_v = Directions.STOP, INF
        for a in gs.get_legal_actions(self.index):
            dx, dy = Actions.direction_to_vector(a)
            p = (int(me[0] + dx), int(me[1] + dy))
            if not self.is_home(p):
                continue
            d = self.dist(p, t)
            v = (100 if d <= 1 else 0) + abs(d - 2)
            if v < best_v:
                best, best_v = a, v
        return best

    def intercept(self, gs, me, t, carried):
        d_me = self.dist(me, t)
        if d_me <= 3:
            return t
        if self.depth.get(t, 0) > 0:
            m = self.mouth[t]
            if self.is_home(m) and self.dist(me, m) < self.dist(t, m):
                return m
        if carried > 0:
            goal = min(self.home_border, key=lambda b: self.dist(t, b))
        else:
            ours = self.get_food_you_are_defending(gs).as_list()
            if not ours:
                return t
            goal = min(ours, key=lambda f: self.dist(t, f))
        if self.dist(me, goal) >= self.dist(t, goal):
            return t
        line = self.dist(t, goal)
        on_path = [c for c in self.cells if self.is_home(c)
                   and self.dist(t, c) + self.dist(c, goal) == line
                   and self.dist(me, c) < self.dist(t, c)]
        return min(on_path, key=lambda c: self.dist(t, c)) if on_path else goal

    def guard_post(self, gs):
        """Home cell cutting the most border-to-food paths, near the likeliest attacker."""
        team = self.team()
        guarded = self.get_food_you_are_defending(gs).as_list() + self.get_capsules_you_are_defending(gs)
        key = len(guarded)
        if team.get('post_key') != key:
            cand = [c for c in self.cells if self.is_home(c) and self.home_dist[c] <= 6]
            score = {c: 0 for c in cand}
            for b in self.home_border:
                for f in guarded:
                    line = self.dist(b, f)
                    for c in cand:
                        if self.dist(b, c) + self.dist(c, f) == line:
                            score[c] += 1
            top = max(score.values()) if score else 1
            team['post_key'] = key
            team['posts'] = {c: 10.0 * s / max(top, 1) for c, s in score.items() if s > 0}
        posts = team['posts']
        if not posts:
            return random.choice(self.home_border)
        attackers = [self.guess(e) for e in self.get_opponents(gs) if not gs.get_agent_state(e).is_pacman]
        if not attackers:
            return max(posts, key=posts.get)
        near = min(attackers, key=lambda a: self.home_dist.get(a, INF))
        return max(posts, key=lambda c: posts[c] - 0.5 * self.dist(c, near))
