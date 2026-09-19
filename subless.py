import os
import random
import time
from PIL import Image, ImageDraw

# --- Enhanced High-Resolution Constants ---
CANVAS_W = 80   
CANVAS_H = 80   
VANISHING_X = 40
VANISHING_Y = 18

LANES_BASE_X = [18, 40, 62]  # Target ground positions for Left, Center, Right

class SubwayEnv:
    def __init__(self):
        self.reset()

    def reset(self):
        """Resets the game to start a new episode/game."""
        self.lane = 1              # 0: Left, 1: Center, 2: Right
        self.player_x = float(LANES_BASE_X[1])
        self.player_y = 68.0       
        self.jump_z = 0.0          
        self.vz = 0.0              
        self.gravity = 1.2
        
        self.is_rolling = False
        self.roll_timer = 0
        
        # Power-ups & States
        self.jetpack_timer = 0
        self.magnet_timer = 0
        
        # Stats & Progression
        self.score = 0
        self.coins = 0
        self.multiplier = 1
        self.speed = 1.9
        self.distance = 0.0
        self.game_over = False
        
        # FX & World
        self.shake_timer = 0
        self.track_offset = 0.0
        self.popups = []
        self.entities = []
        self.spawn_timer = 0
        
        return self.get_state()

    def step(self, action):
        """
        Takes an action:
        0: Do Nothing / Keep running
        1: Move Left
        2: Move Right
        3: Jump
        4: Roll / Fast Fall
        """
        reward = 1.0  # Small reward for every frame survived (encourages living longer)

        # 1. Process AI Action
        if action == 1 and self.lane > 0:
            self.lane -= 1
        elif action == 2 and self.lane < 2:
            self.lane += 1
        elif action == 3 and self.jump_z == 0.0 and not self.is_rolling:
            self.vz = 9.5
        elif action == 4:
            if self.jump_z > 0.0:
                self.vz = -14.0
            else:
                self.is_rolling = True
                self.roll_timer = 22

        # 2. Update Physics & Progress
        self.distance += self.speed
        self.score = int(self.distance * self.multiplier)
        self.speed += 0.0007  
        self.track_offset = (self.track_offset + self.speed * 2.2) % 18

        # Lateral Interpolation
        target_x = LANES_BASE_X[self.lane]
        self.player_x += (target_x - self.player_x) * 0.38

        # Jump & Gravity Physics
        if self.jetpack_timer > 0:
            self.jetpack_timer -= 1
            self.jump_z = 32.0
        else:
            if self.jump_z > 0.0 or self.vz > 0.0:
                self.jump_z += self.vz
                self.vz -= self.gravity
                if self.jump_z <= 0.0:
                    self.jump_z = 0.0
                    self.vz = 0.0

        if self.is_rolling:
            self.roll_timer -= 1
            if self.roll_timer <= 0:
                self.is_rolling = False

        if self.magnet_timer > 0:
            self.magnet_timer -= 1

        # 3. Spawn Entities
        self.spawn_timer += 1
        if self.spawn_timer > max(9, int(24 - self.speed)):
            self.spawn_timer = 0
            lane = random.choice([0, 1, 2])
            r = random.random()
            
            if r < 0.40:
                self.entities.append({'type': 'COIN', 'lane': lane, 'y': float(VANISHING_Y)})
            elif r < 0.62:
                self.entities.append({'type': 'LOW_BARRIER', 'lane': lane, 'y': float(VANISHING_Y)})
            elif r < 0.80:
                self.entities.append({'type': 'HIGH_BARRIER', 'lane': lane, 'y': float(VANISHING_Y)})
            elif r < 0.92:
                self.entities.append({'type': 'TRAIN', 'lane': lane, 'y': float(VANISHING_Y)})
            elif r < 0.96:
                self.entities.append({'type': 'MAGNET', 'lane': lane, 'y': float(VANISHING_Y)})
            else:
                self.entities.append({'type': 'JETPACK', 'lane': lane, 'y': float(VANISHING_Y)})

        # 4. Move Entities & Check Collisions
        remaining = []
        px = self.player_x

        for e in self.entities:
            e['y'] += self.speed * 1.25
            depth_ratio = (e['y'] - VANISHING_Y) / (CANVAS_H - VANISHING_Y)
            e_x = VANISHING_X + (LANES_BASE_X[e['lane']] - VANISHING_X) * depth_ratio

            if self.magnet_timer > 0 and e['type'] == 'COIN' and e['y'] > 32:
                e_x += (px - e_x) * 0.50

            # Hitbox Collisions
            if abs(e['y'] - self.player_y) < 4.5 and abs(e_x - px) < 7.0:
                if e['type'] == 'COIN':
                    self.coins += 1
                    reward += 10.0  # Reward for collecting coins
                    continue
                elif e['type'] == 'MAGNET':
                    self.magnet_timer = 200
                    reward += 5.0
                    continue
                elif e['type'] == 'JETPACK':
                    self.jetpack_timer = 180
                    reward += 10.0
                    continue
                
                # Lethal Obstacles
                if self.jetpack_timer == 0:
                    if e['type'] == 'LOW_BARRIER' and self.jump_z < 10.0:
                        self.game_over = True
                    elif e['type'] == 'HIGH_BARRIER' and not self.is_rolling:
                        self.game_over = True
                    elif e['type'] == 'TRAIN' and self.jump_z < 22.0:
                        self.game_over = True

            if e['y'] < CANVAS_H + 8:
                remaining.append(e)

        self.entities = remaining

        if self.game_over:
            reward = -100.0  # Heavy penalty for crashing/dying

        return self.get_state(), reward, self.game_over

    def get_state(self):
        """
        Returns a simplified numerical representation of the game 
        that we can feed directly into a PyTorch neural network.
        """
        # Find the closest obstacle ahead of the player
        closest_obs_dist = 100.0
        closest_obs_type = 0.0 # 0: None, 1: Low, 2: High, 3: Train
        obs_lane = 1.0

        for e in self.entities:
            if e['y'] <= self.player_y and e['type'] != 'COIN' and e['type'] != 'MAGNET' and e['type'] != 'JETPACK':
                dist = self.player_y - e['y']
                if dist < closest_obs_dist:
                    closest_obs_dist = dist
                    obs_lane = float(e['lane'])
                    if e['type'] == 'LOW_BARRIER': closest_obs_type = 1.0
                    elif e['type'] == 'HIGH_BARRIER': closest_obs_type = 2.0
                    elif e['type'] == 'TRAIN': closest_obs_type = 3.0

        # State vector: [player_lane, jump_z, is_rolling, closest_obs_dist, closest_obs_type, obs_lane]
        state = [
            float(self.lane),
            float(self.jump_z),
            1.0 if self.is_rolling else 0.0,
            closest_obs_dist / 80.0,  # Normalized
            closest_obs_type,
            obs_lane
        ]
        return state
