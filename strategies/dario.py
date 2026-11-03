import random
import contest.util as util
import math
from contest.util import nearest_point
from contest.game import Directions
from contest.capture_agents import CaptureAgent



def create_team(first_index, second_index, is_red,
                first='OffensiveReflexAgent', second='DefensiveReflexAgent', num_training=0):
    """
    This function should return a list of two agents that will form the
    team, initialized using firstIndex and secondIndex as their agent
    index numbers.  isRed is True if the red team is being created, and
    will be False if the blue team is being created.

    As a potentially helpful development aid, this function can take
    additional string-valued keyword arguments ("first" and "second" are
    such arguments in the case of this function), which will come from
    the --red_opts and --blue_opts command-line arguments to capture.py.
    For the nightly contest, however, your team will be created without
    any extra arguments, so you should make sure that the default
    behavior is what you want for the nightly contest.
    """
    return [eval(first)(first_index), eval(second)(second_index)]


class ReflexCaptureAgent(CaptureAgent):

    def choose_action(self, game_state):
        try:
            return self.choose_action_method(game_state)
        except Exception as e:
            print(e)
            return random.choice(game_state.get_legal_actions(self.index))
        
    def choose_action_method(self, game_state):
        return random.choice(game_state.get_legal_actions(self.index))

    def get_successor(self, game_state, action):
        """
        Finds the next successor which is a grid position (location tuple).
        """
        successor = game_state.generate_successor(self.index, action)
        pos = successor.get_agent_state(self.index).get_position()
        if pos != nearest_point(pos):
            # Only half a grid position was covered
            return successor.generate_successor(self.index, action)
        else:
            return successor

    def evaluate(self, game_state, action, prev_game_state=None):
        """
        Computes a linear combination of features and feature weights
        """
        features = self.get_features(game_state, action, prev_game_state=prev_game_state)
        weights = self.get_weights(game_state, action)
        return features * weights

class OffensiveReflexAgent(ReflexCaptureAgent):
    """
  A reflex agent that seeks food. This is an agent
  we give you to get an idea of what an offensive agent might look like,
  but it is by no means the best or only way to build an offensive agent.
  """
    def __init__(self, index):
        CaptureAgent.__init__(self, index)        
        self.justSpawned = 0
        self.position = None
        self.currTarget = None
        self.entryPoint = None
        self.power = False
        self.powerPath = []
        self.ghostMoves = 0
        self.prevNumPowerCapsules = 0
        self.possibleEntryPoints = []
        self.endgame = False

        self.last10positions = [ None ] * 10

    def register_initial_state(self, game_state):
        CaptureAgent.register_initial_state(self, game_state)
        self.spawnPosition = game_state.get_agent_state(self.index).get_position()
        self.findPossibleEntryPoints(game_state)
        self.get_home_midline_points(game_state)

    # This method initializes the home_midline_points list with the coordinates of the points in the middle of the board (on home side)
    def get_home_midline_points(self, game_state):
        width = game_state.data.layout.width
        height = game_state.data.layout.height
        mid_x = (width // 2) - 1 if self.red else (width // 2)
        
        self.home_midline_points = [
            (mid_x, y) 
            for y in range(1, height - 1) 
            if not game_state.has_wall(mid_x, y)
        ]
          
    # This method looks at all the empty spaces in the middle of the board
    def findPossibleEntryPoints(self, game_state):
        width = game_state.data.layout.width
        height = game_state.data.layout.height
        mid_x = (width // 2) + 1 if not self.red else (width // 2)

        self.possibleEntryPoints = [
            (mid_x, y) 
            for y in range(1, height - 1) 
            if not game_state.has_wall(mid_x, y)
        ]

    # This method chooses a random point from the self.possibleEntryPoints as the initial target
    def chooseEntryPoint(self, game_state):
        self.entryPoint = random.choice(self.home_midline_points)
  
    
    # This method returns the features relevant to the offensive agent at a given state after taking a given action
    def get_features(self, game_state, action, prev_game_state=None):
        features = util.Counter()
        successor = self.get_successor(game_state, action) 
        pos = successor.get_agent_state(self.index).get_position() 

        # The score after taking the given action
        features['successor_score'] = self.get_score(successor) 

        # The distance to the closest food after taking the given action
        foodList = self.get_food(successor).as_list() 
        features['foodDistance'] = min([self.get_maze_distance(pos, food) for food in foodList]) if foodList else 0

        # The distance to the closest power capsule after taking the given action
        features['capsuleDistance'] = min([self.get_maze_distance(pos, capsule) for capsule in self.get_capsules(successor)]) if self.get_capsules(successor) else 0
        features['capsuleDistance'] = math.sqrt(features['capsuleDistance']) if features['capsuleDistance'] else 0

        # The number of food items that the agent is carrying
        features['num_carrying'] = game_state.get_agent_state(self.index).num_carrying

        # If the agent has eaten a power capsule
        features['capsulePower'] = 1 if (prev_game_state and self.get_capsules(successor) < self.get_capsules(prev_game_state)) else 0

        # If the agent has eaten a power capsule, then the distance to other capsules doesn't matter, so it is set to 0
        if features['capsulePower']: features['capsuleDistance'] = 0

        # The distance to the closest ghost after taking the given action
        ghost_distances = [ 
            self.get_maze_distance(pos, enemy.get_position()) 
            for enemy in [ successor.get_agent_state(i) for i in self.get_opponents(successor) ] 
            if not enemy.is_pacman and enemy.get_position() != None and enemy.scared_timer == 0
        ]
        features['distanceToGhost'] = min(min(ghost_distances), 5) if ghost_distances else 0

        if self.endgame: features['distance_from_home'] = self.distance_from_home(pos)[0]

        return features

    def get_weights(self, game_state, action):
        position_repetitions = len([ pos for pos in self.last10positions if pos == self.position ])
        # multiplier = math.sqrt(max(1, position_repetitions))
        multiplier = max(1, position_repetitions)

        
        if not self.endgame: return {
            'successor_score': 60 * multiplier,
            'foodDistance': -2 * multiplier,
            'capsuleDistance': -10 * multiplier,
            'distancesToGhost': 20,
            'num_carrying': 10,
            'capsulePower': 0,
            'distance_from_home': 0,
        }
        else: return {
            'successor_score': 1000 * multiplier,
            'foodDistance': -2 * multiplier,
            'capsuleDistance': -5 *  multiplier,
            'distancesToGhost': 15,
            'num_carrying': 0,
            'capsulePower': 0,
            'distance_from_home': -10,
        }


    # This method chooses a random forward (not staying in place and not going backwards) move for the given position
    def randomForwardMove(self ,game_state):
        actions = game_state.get_legal_actions(self.index)
        actions.remove(Directions.STOP)

        if len(actions) == 1:
            return actions[0]
        
        prevAction = game_state.get_agent_state(self.index).configuration.direction
        backwardAction = Directions.REVERSE[prevAction]
        if backwardAction in actions:
            actions.remove(backwardAction)
        return random.choice(actions)


    # This is a method which gives the best action for the enemy ghosts to follow the agent (NOT USED IN THE FINAL IMPLEMENTATION)
    def ghosts_following_simulation(self, game_state, agent_position):
        """
        For each visible enemy ghost, choose the action that brings them closest to a predefined position.
        
        Args:
        - game_state (GameState): The current state of the game.
        - self (CaptureAgent): The agent for which you want to compute enemy actions.
        - agent_position (tuple): The (x, y) position to move towards.
        
        Returns:
        - Dictionary where keys are enemy indices and values are the best action for that enemy.
        """
        best_actions = {}

        # Get indices of enemy agents
        enemy_indices = self.get_opponents(game_state)

        for enemy_index in enemy_indices:
            # Get position and agent state of the enemy
            enemy_position = game_state.get_agent_position(enemy_index)
            if enemy_position is None or self.get_maze_distance(enemy_position, agent_position) > 5:  # Enemy not visible by our agent
                continue
            
            agent_state = game_state.get_agent_state(enemy_index)
            if agent_state.is_pacman:  # Ignore pacmen, only consider ghosts
                continue
            
            # Get legal actions for the enemy
            legal_moves = game_state.get_legal_actions(enemy_index)
            
            # Choose the action that gets closest to the target position
            min_distance = float('inf')
            best_action = None
            
            for action in legal_moves:
                if action == Directions.STOP: continue

                # Calculate new position based on the action
                new_position = game_state.generate_successor(enemy_index, action).get_agent_position(enemy_index)
                
                # Calculate maze distance to the target position using the agent's self.get_maze_distance method
                distance = self.get_maze_distance(new_position, agent_position)
                
                if distance < min_distance:
                    min_distance = distance
                    best_action = action

            # If no action is found (shouldn't happen), pick a random action
            if best_action is None and legal_moves:
                continue
                best_action = random.choice(legal_moves)
            
            # Store the best action for this enemy
            best_actions[enemy_index] = best_action
        
        return best_actions

    # This method simulates the game state many moves in advance and returns the evaluation of the game state at key evaluation steps
    def lookaheadSimulation(self ,game_state ,depth, evaluationSteps):
        """
        evaluationSteps: A list of [step, weight] pairs. The evaluation function is called at each step in the list and the results are multiplied by the corresponding weight.
        
        Why? It is introduced to make the model capture immediate rewards more effectively, while also considering the long-term rewards.
        """
        new_game_state = game_state.deep_copy()
        step = 1
        evaluationIndex = 0
        eval_sum = 0
        while depth-step >= 0:
            # Choosing a random move
            new_game_state = new_game_state.generate_successor(self.index ,self.randomForwardMove(new_game_state))

            # region Not Used in the final implementation
            # # Getting the position of the agent
            # position = new_game_state.get_agent_state(self.index).get_position()

            # # Making the opponents follow the agent
            # opponents_moves = self.ghosts_following_simulation(new_game_state, position)
            # for enemy_index, enemy_action in opponents_moves.items():
            #     new_game_state = new_game_state.generate_successor(enemy_index, enemy_action)

            # if new_game_state.get_agent_state(self.index).get_position() == self.spawnPosition: eaten += 1
            # else: not_eaten +=1
            # endregion

            if step == evaluationSteps[evaluationIndex][0]:
                eval_sum += self.evaluate(new_game_state ,Directions.STOP, prev_game_state=game_state) * evaluationSteps[evaluationIndex][1]
                evaluationIndex += 1

            step+=1

        return eval_sum # + self.evaluate(new_game_state, Directions.STOP)


    # This method returns the best action to reach the entry point into enemy territory
    def towardEntryPoint(self,legalActions,game_state):
        distanceToTarget = []
        shortestDistance = 9999999999
        legalActionsToChoose = []
        for i in range (0,len(legalActions)):    
            action = legalActions[i]
            nextState = game_state.generate_successor(self.index, action)
            nextPosition = nextState.get_agent_position(self.index)
            distance = self.get_maze_distance(nextPosition, self.entryPoint)
            # if distance == 0: print("Reached Entry Point!!!!!!!!!! (Distance is 0)")
            # print(action, distance, (distance<=shortestDistance and (not nextState.get_agent_state(self.index).is_pacman or distance == 0)))
            # if distance<=shortestDistance and (not nextState.get_agent_state(self.index).is_pacman or distance == 0):
            if distance<=shortestDistance:
                shortestDistance = distance
                distanceToTarget.append(distance)
                legalActionsToChoose.append(action)

        bestActionsList = [a for a, distance in zip(legalActionsToChoose, distanceToTarget) if distance == shortestDistance]
        # print(shortestDistance, bestActionsList)

        if len(bestActionsList) == 0:
            print("Damn this shouldn't have happened. Random action chosen.")
            return random.choice(legalActions)

        bestAction = random.choice(bestActionsList)
        return bestAction
    
    # This method uses the midline points on the home side to calculate the distance from the given position to the closest midline point
    def distance_from_home(self, pos):
        """
        Returns a pair [ distance, [x, y] ] where [x, y] is the closest point on the home midline to pos
        """
        return min([[self.get_maze_distance(pos, home_midline_point), home_midline_point] for home_midline_point in self.home_midline_points], key=lambda x: x[0])


    # This method returns the best path to take to maximise food eaten after consuming a power capsule
    def best_capsule_path(self, game_state, eaten_capsule_pos):
        # PADDING FOR THE NUMBER OF STEPS
        padding = 5

        # pos = game_state.get_agent_state(self.index).get_position()
        capsules = self.get_capsules(game_state)
        food_list = self.get_food(game_state).as_list()

        # get the 5 closest foods
        closest_foods = sorted(food_list, key=lambda x: self.get_maze_distance(eaten_capsule_pos, x))[:5]

        best_path = []
        for starting_food in closest_foods:
            steps = 40 + padding
            steps = min(steps, game_state.data.timeleft // 4)

            steps = steps - self.get_maze_distance(eaten_capsule_pos, starting_food)

            food_list_cpy = [f for f in food_list]
            curr_food = starting_food
            order = []
            while steps>=self.distance_from_home(curr_food)[0]:
                order.append(curr_food) # add the food to the solution order
                food_list_cpy.remove(curr_food) # remove the eaten food from the list
                next_food = min([food for food in food_list_cpy], key=lambda x: self.get_maze_distance(curr_food, x)) # chosing the closest food
                steps -= self.get_maze_distance(curr_food, next_food) # decrement the steps
                curr_food = next_food
            if len(order) > len(best_path):
                best_path = order


        
        if not best_path:
            return []
        if len(best_path) == 1:
            return [best_path[0], self.distance_from_home(best_path[0])[1]]
        
        res = [*best_path[:-1], self.distance_from_home(best_path[-2])[1]]

        path_length = self.get_maze_distance(eaten_capsule_pos, res[0])
        # print("Distance from", eaten_capsule_pos, "to", res[0], "is", self.get_maze_distance(eaten_capsule_pos, res[0]))
        # for i in range(1, len(res)):
        #     print("Distance from", res[i-1], "to", res[i], "is", self.get_maze_distance(res[i-1], res[i]))
        #     path_length += self.get_maze_distance(res[i-1], res[i])
        # print("Path Length:", path_length)
        # print("Best Path:", res)

        return res
            

    def choose_action_method(self, game_state):

        self.position = game_state.get_agent_state(self.index).get_position()

        self.last10positions = [ *self.last10positions[1:], self.position ]
    
        # Checking if the pacman has just spawned
        if self.position == self.spawnPosition:
            self.chooseEntryPoint(game_state)
            self.justSpawned = 1
        
        # Checking if the pacman has reached the desired entry point into enemy territory
        if self.justSpawned == 1 and (self.position == self.entryPoint or game_state.get_agent_state(self.index).is_pacman):
            self.justSpawned = 0

        # PACMAN JUST SPAWNED - finding the best action to reach the entry point into enemy territory
        if self.justSpawned == 1:
            legalActions = game_state.get_legal_actions(self.index)
            legalActions.remove(Directions.STOP)

            bestAction=self.towardEntryPoint(legalActions, game_state)
            return bestAction
        

        # ENDGAME CHECK - Checking if there are not many moves left until the game ends
        if game_state.data.timeleft < 200:
            self.endgame = True

        
        # PACMAN HAS ALREADY REACHED THE ENTRY POINT
        numPowerCapsules = len(self.get_capsules(game_state))
        prevNumPowerCapsules = self.prevNumPowerCapsules

        self.prevNumPowerCapsules = numPowerCapsules

        legal_actions = game_state.get_legal_actions(self.index)
        legal_actions.remove(Directions.STOP) # almaost always a bad move

        # Finding how close a non-scared enemy ghost is        
        enemyGhosts = [
            ghost for ghost in [game_state.get_agent_state(i) for i in self.get_opponents(game_state)] 
            if not ghost.is_pacman and ghost.get_position() != None and ghost.scared_timer == 0
        ]
        distanceToEnemy = min([self.get_maze_distance(self.position, ghost.get_position()) for ghost in enemyGhosts]) if len(enemyGhosts) > 0 else 10000000
        
        if numPowerCapsules < prevNumPowerCapsules:
            self.power = True
            self.powerPath = self.best_capsule_path(game_state, self.position)
            self.capsulePathIndex = 0
        if not game_state.get_agent_state(self.index).is_pacman:
            # if self.power: print("Capsule Power Over because agent is not pacman")
            self.power = False
        if distanceToEnemy <= 5:
            # if self.power: print("Capsule Power Over because enemy is closeby")
            self.power = False
        
        if len(self.powerPath)==0 or (self.power and self.position == self.powerPath[-1]):
            self.power = False


        # CHECK IF CAPSULE POWER IS ACTIVE
        if self.power:
            if self.position == self.powerPath[self.capsulePathIndex]:
                self.capsulePathIndex += 1
            self.currTarget = self.powerPath[self.capsulePathIndex]

            distanceToTarget = []

            for action in legal_actions:
                distanceToTarget.append(self.get_maze_distance(game_state.generate_successor(self.index, action).get_agent_position(self.index), self.currTarget))
            
            bestActions = [action for action, dis in zip(legal_actions, distanceToTarget) if dis==min(distanceToTarget)]
            return random.choice(bestActions)
        

        # CHECK IF THE AGENT CAN EAT A POWER CAPSULE IN THE NEXT MOVE
        if self.get_capsules(game_state):
            for action in legal_actions:
                if game_state.generate_successor(self.index, action).get_agent_state(self.index).get_position() in self.get_capsules(game_state):
                    return action

        # LOOKAHEAD SIMULATION
        if self.ghostMoves >= 4:
            self.justSpawned = 1
            self.ghostMoves = 0
            self.chooseEntryPoint(game_state)
            # print("Made 4 moves as ghost, choosing a new entry point into enemy territory")
            return self.choose_action_method(game_state)
        if not game_state.get_agent_state(self.index).is_pacman:
            self.ghostMoves += 1
        else:
            self.ghostMoves = 0

        expected_value_list = []
        simulations = 24
        for action in legal_actions:
            nextState = game_state.generate_successor(self.index, action)
            expected_value = 0
            for _ in range(1, simulations): expected_value += self.lookaheadSimulation(nextState, 20, [[1, 2], [5, 1.5], [20, 1]])
            expected_value /= simulations
            expected_value_list.append(expected_value)

        return random.choice([action for action, value in zip(legal_actions, expected_value_list) if value == max(expected_value_list)])


class DefensiveReflexAgent(ReflexCaptureAgent):
    """
    A reflex agent that keeps its side Pacman-free with enhanced patrol behavior.
    """

    def __init__(self, index, time_for_computing=0.1):
        super().__init__(index, time_for_computing)
        self.patrol_positions = []  # Define patrol positions dynamically
        self.patrol_position = None  # To cycle through patrol points dynamically
        self.home_midline_points = []  # List of points in the middle of the board (on home side)

    def register_initial_state(self, game_state):
        super().register_initial_state(game_state)

        self.get_home_midline_points(game_state)
        self.define_patrol_area(game_state)
        self.choose_patrol_position(game_state)

    # This method initializes the home_midline_points list with the coordinates of the points in the middle of the board (on home side)
    def get_home_midline_points(self, game_state):
        layoutInfo = []
        x = (game_state.data.layout.width) // 2
        if self.red:
            x -=1
        y = (game_state.data.layout.height) // 2
        layoutInfo.extend((game_state.data.layout.width , game_state.data.layout.height ,x ,y))
        
        for i in range(1, layoutInfo[1] - 1):
            if not game_state.has_wall(layoutInfo[2], i):
                self.home_midline_points.append((layoutInfo[2], i))

        # print("home midline points:",self.home_midline_points)

    def distance_from_midline(self, pos):
        """
        Returns a pair [ distance, [x, y] ] where [x, y] is the closest point on the home midline to pos
        """
        return min([[self.get_maze_distance(pos, home_midline_point), home_midline_point] for home_midline_point in self.home_midline_points], key=lambda x: x[0])
         
    def define_patrol_area(self, game_state):
        """
        Defines patrol points in the 4 columns closest to the middle on the agent's side.
        """
        mid_x = game_state.data.layout.width // 2
        walls = game_state.get_walls()

        # Determine patrol columns based on the agent's team
        if self.red:
            patrol_columns = range(mid_x - 4, mid_x)  # 4 columns on the left side
        else:
            patrol_columns = range(mid_x, mid_x + 4)  # 4 columns on the right side

        # Identify all valid positions in these columns
        self.patrol_positions = [
            (x, y) for x in patrol_columns for y in range(walls.height) if not walls[x][y]
        ]

        # print(min([ x for x, y in self.patrol_positions]), max([ x for x, y in self.patrol_positions]))

        self.patrol_positions = [ p for p in self.patrol_positions if self.distance_from_midline(p)[0] <= 2 ]

        # print(self.patrol_positions)

        random.shuffle(self.patrol_positions)  # Shuffle patrol points for varied movement

    def choose_patrol_position(self, game_state, curr_patrol_point=None):
        """
        Chooses the index of the patrol point with the best score.
        """
        myFoodList = self.get_food_you_are_defending(game_state).as_list()
        myCapsules = self.get_capsules_you_are_defending(game_state)

        foodWeight = 1
        capsuleWeight = 3

        scores = []

        for patrolPoint in self.patrol_positions:
            # Get the 5 closest foods
            closest_foods = sorted(myFoodList, key=lambda x: self.get_maze_distance(patrolPoint, x))[:5]
            foodDistanceSum = sum([self.get_maze_distance(patrolPoint, food) for food in closest_foods])

            capsuleDistanceSum = sum([self.get_maze_distance(patrolPoint, capsule) for capsule in myCapsules])

            scores.append(foodDistanceSum * foodWeight + capsuleDistanceSum * capsuleWeight)
        
        
        # new_patrol_point = random.choice([ p for p, s in zip(self.patrol_positions, scores) if s == min(scores) ])

        if not curr_patrol_point:
            first_patrol_point = random.choice([ p for p, s in zip(self.patrol_positions, scores) if s == min(scores) ])
            # print("First Patrol Point:", first_patrol_point)
            return first_patrol_point

        # top 3 scores:
        top_scores = sorted(scores)[:3]
        top_patrol_points = [ p for p, s in zip(self.patrol_positions, scores) if s in top_scores ]


        sampled_patrol_point = random.choice(top_patrol_points)

        # sampled_patrol_point = random.choices(self.patrol_positions, [(s+min(scores))*10 for s in scores], k=1)[0]

        # the patrol point can change only if the agent is within 4 units of the current patrol point
        change_probability = 0.08 if self.get_maze_distance(game_state.get_agent_state(self.index).get_position(), curr_patrol_point) < 5 else 0.0
        # print("Change Probability:", change_probability)
        new_patrol_point = random.choices([sampled_patrol_point, curr_patrol_point], [change_probability, 1 - change_probability], k=1)[0]

        # if new_patrol_point != curr_patrol_point: print("New Patrol Point:", new_patrol_point)
        return new_patrol_point

    def get_features(self, game_state, action, prev_game_state=None):
        features = util.Counter()
        successor = self.get_successor(game_state, action)

        my_state = successor.get_agent_state(self.index)
        my_pos = my_state.get_position()

        # Determine whether the agent is on defense
        features['on_defense'] = 1 if not my_state.is_pacman else 0

        # Compute distance to visible invaders
        enemies = [successor.get_agent_state(i) for i in self.get_opponents(successor)]
        invaders = [a for a in enemies if a.is_pacman and a.get_position() is not None]
        features['num_invaders'] = len(invaders)

        if len(invaders) > 0:
            # Chase the nearest visible invader
            dists = [self.get_maze_distance(my_pos, a.get_position()) for a in invaders]
            features['invader_distance'] = min(dists)
        else:
            # Patrol the middle columns on the agent's side
            patrol_target = self.patrol_position
            features['distance_to_patrol'] = self.get_maze_distance(my_pos, patrol_target)

        # Penalize stopping or reversing direction
        if action == Directions.STOP:
            features['stop'] = 1
        rev = Directions.REVERSE[game_state.get_agent_state(self.index).configuration.direction]
        if action == rev:
            features['reverse'] = 1

        return features

    def get_weights(self, game_state, action):
        """
        Weights for the features to guide behavior.
        """
        return {
            'num_invaders': -1000,     # Strongly prioritize chasing invaders
            'on_defense': 100,        # Stay on defense
            'invader_distance': -10,  # Get close to invaders
            'distance_to_patrol': -5, # Patrol the middle area on its side
            'stop': -100,             # Avoid stopping
            'reverse': -2             # Discourage reversing direction
        }

    def choose_action_method(self, game_state):
        """
        Chooses an action based on feature evaluation.
        """
        actions = game_state.get_legal_actions(self.index)

        # Cycle through patrol points if no invaders are visible
        enemies = [game_state.get_agent_state(i) for i in self.get_opponents(game_state)]
        invaders = [a for a in enemies if a.is_pacman and a.get_position() is not None]

        if len(invaders) == 0:
            # Advance to the next patrol position
            self.patrol_position = self.choose_patrol_position(game_state, self.patrol_position)

        # Evaluate actions and select the best one
        values = [self.evaluate(game_state, a) for a in actions]
        max_value = max(values)
        best_actions = [a for a, v in zip(actions, values) if v == max_value]

        return random.choice(best_actions)
   