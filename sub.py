import os
import random
import select
import sys
import termios
import time
import tty
from PIL import Image, ImageDraw, ImageFont

# --- Linux Non-blocking Raw Input ---
class LinuxRawInput:
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old_settings = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)

def get_keys():
    keys = []
    while select.select([sys.stdin], [], [], 0)[0]:
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            seq = sys.stdin.read(2)
            if seq == '[A': keys.append('UP')
            elif seq == '[B': keys.append('DOWN')
            elif seq == '[D': keys.append('LEFT')
            elif seq == '[C': keys.append('RIGHT')
        else:
            keys.append(ch.lower())
    return keys

# --- Enhanced High-Resolution Constants ---
CANVAS_W = 80   # 80 Pixels Wide
CANVAS_H = 80   # 80 Pixels High (Rendered into 40 terminal rows)
VANISHING_X = 40
VANISHING_Y = 18

LANES_BASE_X = [18, 40, 62]  # Target ground positions for Left, Center, Right

class SubwayEngineHD:
    def __init__(self):
        # Player State
        self.lane = 1              # 0: Left, 1: Center, 2: Right
        self.player_x = float(LANES_BASE_X[1])
        self.player_y = 68.0       # Ground base y
        self.jump_z = 0.0          # Height off ground
        self.vz = 0.0              # Jump velocity
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
        self.popups = []           # Dynamic text popups
        self.entities = []
        self.spawn_timer = 0

    def process_input(self, keys):
        for k in keys:
            if k in ['q', '\x03']:
                sys.exit()
            elif k in ['a', 'LEFT'] and self.lane > 0:
                self.lane -= 1
            elif k in ['d', 'RIGHT'] and self.lane < 2:
                self.lane += 1
            elif k in ['w', 'UP'] and self.jump_z == 0.0 and not self.is_rolling:
                self.vz = 9.5      # Launch force
            elif k in ['s', 'DOWN']:
                if self.jump_z > 0.0:
                    self.vz = -14.0 # Fast fall slam
                else:
                    self.is_rolling = True
                    self.roll_timer = 22

    def update_physics(self):
        self.distance += self.speed
        self.score = int(self.distance * self.multiplier)
        self.speed += 0.0007  # Progressive speed acceleration
        
        # Track tie perspective animation cycle
        self.track_offset = (self.track_offset + self.speed * 2.2) % 18

        # Lateral Interpolation (Smooth Lane Swapping)
        target_x = LANES_BASE_X[self.lane]
        self.player_x += (target_x - self.player_x) * 0.38

        # Jump & Gravity Physics
        if self.jetpack_timer > 0:
            self.jetpack_timer -= 1
            self.jump_z = 32.0  # Fly safely above all ground hazards
        else:
            if self.jump_z > 0.0 or self.vz > 0.0:
                self.jump_z += self.vz
                self.vz -= self.gravity
                if self.jump_z <= 0.0:
                    self.jump_z = 0.0
                    self.vz = 0.0

        # Roll State
        if self.is_rolling:
            self.roll_timer -= 1
            if self.roll_timer <= 0:
                self.is_rolling = False

        # Power-up Timers
        if self.magnet_timer > 0:
            self.magnet_timer -= 1

        # Camera Shake Decoupling
        if self.shake_timer > 0:
            self.shake_timer -= 1

        # Dynamic Obstacle & Power-up Spawning
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

        # Entity Movement & Hitbox Collisions
        remaining = []
        px = self.player_x

        for e in self.entities:
            e['y'] += self.speed * 1.25
            
            # 3D projection scale factor
            depth_ratio = (e['y'] - VANISHING_Y) / (CANVAS_H - VANISHING_Y)
            e_x = VANISHING_X + (LANES_BASE_X[e['lane']] - VANISHING_X) * depth_ratio

            # Magnet Pull Physics
            if self.magnet_timer > 0 and e['type'] == 'COIN' and e['y'] > 32:
                e_x += (px - e_x) * 0.50

            # Hitbox Collision Checks
            if abs(e['y'] - self.player_y) < 4.5 and abs(e_x - px) < 7.0:
                if e['type'] == 'COIN':
                    self.coins += 1
                    self.popups.append({'text': '+10', 'x': px, 'y': self.player_y - 12, 'life': 12})
                    continue
                elif e['type'] == 'MAGNET':
                    self.magnet_timer = 200
                    self.popups.append({'text': 'MAGNET!', 'x': px, 'y': self.player_y - 14, 'life': 22})
                    continue
                elif e['type'] == 'JETPACK':
                    self.jetpack_timer = 180
                    self.popups.append({'text': 'JETPACK!', 'x': px, 'y': self.player_y - 14, 'life': 22})
                    continue
                
                # Obstacle Lethal Collisions (Bypassed by Jetpack)
                if self.jetpack_timer == 0:
                    if e['type'] == 'LOW_BARRIER' and self.jump_z < 10.0:
                        self.shake_timer = 10
                        self.game_over = True
                    elif e['type'] == 'HIGH_BARRIER' and not self.is_rolling:
                        self.shake_timer = 10
                        self.game_over = True
                    elif e['type'] == 'TRAIN' and self.jump_z < 22.0:
                        self.shake_timer = 10
                        self.game_over = True

            if e['y'] < CANVAS_H + 8:
                remaining.append(e)

        self.entities = remaining

        # Update Floating Popups
        for p in self.popups[:]:
            p['y'] -= 0.6
            p['life'] -= 1
            if p['life'] <= 0:
                self.popups.remove(p)

    def render_frame(self):
        # Screen Shake Displacement
        off_x = random.randint(-1, 1) if self.shake_timer > 0 else 0
        off_y = random.randint(-1, 1) if self.shake_timer > 0 else 0

        # Background Canvas Creation
        img = Image.new("RGB", (CANVAS_W, CANVAS_H), (10, 12, 22))
        draw = ImageDraw.Draw(img)

        # 1. High-Contrast Sky & Horizon Gradient Line
        draw.rectangle([0, 0, CANVAS_W, VANISHING_Y], fill=(18, 22, 38))
        draw.line([(0, VANISHING_Y), (CANVAS_W, VANISHING_Y)], fill=(0, 180, 255), width=1)

        # 2. 3D Perspective Track Bed
        draw.polygon([
            (VANISHING_X - 6 + off_x, VANISHING_Y + off_y),
            (VANISHING_X + 6 + off_x, VANISHING_Y + off_y),
            (CANVAS_W + 18 + off_x, CANVAS_H + off_y),
            (-18 + off_x, CANVAS_H + off_y)
        ], fill=(32, 36, 48))

        # Animated Track Ties
        for i in range(8):
            z_pos = (self.track_offset + i * 9) % 62
            y_tie = VANISHING_Y + z_pos
            if y_tie < CANVAS_H:
                ratio = (y_tie - VANISHING_Y) / (CANVAS_H - VANISHING_Y)
                x_left = VANISHING_X + (-22 - VANISHING_X) * ratio
                x_right = VANISHING_X + (102 - VANISHING_X) * ratio
                draw.line([(x_left + off_x, y_tie + off_y), (x_right + off_x, y_tie + off_y)], fill=(55, 60, 75), width=1)

        # 3 Glowing Perspective Track Rails
        for lane_idx in range(3):
            base_x = LANES_BASE_X[lane_idx]
            draw.line([
                (VANISHING_X + off_x, VANISHING_Y + off_y),
                (base_x + off_x, CANVAS_H + off_y)
            ], fill=(0, 220, 255), width=1)

        # 3. High-Detail Entity Rendering
        for e in sorted(self.entities, key=lambda item: item['y']):
            ratio = (e['y'] - VANISHING_Y) / (CANVAS_H - VANISHING_Y)
            if ratio <= 0: continue
            
            ex = VANISHING_X + (LANES_BASE_X[e['lane']] - VANISHING_X) * ratio + off_x
            ey = e['y'] + off_y
            size = max(1, int(8 * ratio))

            if e['type'] == 'COIN':
                # Bright Gold Coin with Dark Outline
                draw.ellipse([ex - size, ey - size, ex + size, ey + size], fill=(255, 215, 0), outline=(150, 100, 0))
                if size > 2:
                    draw.ellipse([ex - size + 1, ey - size + 1, ex + size - 1, ey + size - 1], fill=(255, 235, 120))
            
            elif e['type'] == 'MAGNET':
                # Glowing Red Magnet Icon
                draw.rectangle([ex - size, ey - size, ex + size, ey + size], fill=(255, 40, 60), outline=(255, 255, 255))
                if size > 2:
                    draw.rectangle([ex - size + 2, ey - size + 2, ex + size - 2, ey], fill=(200, 20, 20))
            
            elif e['type'] == 'JETPACK':
                # Bright Green Jetpack Icon
                draw.rectangle([ex - size, ey - size, ex + size, ey + size], fill=(40, 230, 90), outline=(255, 255, 255))
            
            elif e['type'] == 'LOW_BARRIER':
                # High-Visibility Striped Wooden Barrier
                draw.rectangle([ex - size * 2.2, ey - size, ex + size * 2.2, ey], fill=(240, 60, 40), outline=(255, 255, 255))
                draw.rectangle([ex - size * 2.2, ey - size, ex - size, ey], fill=(255, 255, 255))
                draw.rectangle([ex + size, ey - size, ex + size * 2.2, ey], fill=(255, 255, 255))
            
            elif e['type'] == 'HIGH_BARRIER':
                # Overhead Clearance Barrier
                draw.rectangle([ex - size * 2.2, ey - size * 3.5, ex + size * 2.2, ey - size * 2.0], fill=(255, 200, 0), outline=(0, 0, 0))
                draw.line([(ex - size * 2.0, ey), (ex - size * 2.0, ey - size * 3.5)], fill=(200, 200, 200), width=1)
                draw.line([(ex + size * 2.0, ey), (ex + size * 2.0, ey - size * 3.5)], fill=(200, 200, 200), width=1)
            
            elif e['type'] == 'TRAIN':
                # Detailed 3D Subway Train Engine
                draw.rectangle([ex - size * 2.8, ey - size * 5.0, ex + size * 2.8, ey], fill=(200, 30, 50), outline=(255, 255, 255))
                # Train Front Windshield
                draw.rectangle([ex - size * 2.0, ey - size * 4.2, ex + size * 2.0, ey - size * 2.5], fill=(130, 210, 255))
                # Headlights
                if size > 2:
                    draw.ellipse([ex - size * 2.0, ey - size * 1.5, ex - size * 1.0, ey - size * 0.5], fill=(255, 255, 180))
                    draw.ellipse([ex + size * 1.0, ey - size * 1.5, ex + size * 2.0, ey - size * 0.5], fill=(255, 255, 180))

        # 4. Player Character & Animation Effects
        px = self.player_x + off_x
        py = self.player_y - self.jump_z + off_y
        shadow_y = self.player_y + off_y

        # Dynamic Drop Shadow
        shadow_r = max(2, int(7 - self.jump_z * 0.18))
        draw.ellipse([px - shadow_r, shadow_y - 2, px + shadow_r, shadow_y + 2], fill=(8, 10, 16))

        if self.jetpack_timer > 0:
            # Jetpack Thruster Flame Effect
            draw.polygon([(px - 4, py + 2), (px + 4, py + 2), (px, py + 12 + random.randint(0, 4))], fill=(255, 120, 0))
            draw.polygon([(px - 2, py + 2), (px + 2, py + 2), (px, py + 8)], fill=(255, 230, 0))
            draw.rectangle([px - 4, py - 8, px + 4, py + 2], fill=(40, 230, 90), outline=(255, 255, 255))
        elif self.is_rolling:
            # Rolling Spin Ball
            draw.ellipse([px - 5, py - 5, px + 5, py + 2], fill=(255, 180, 0), outline=(255, 255, 255))
        else:
            # Standard Surfer Character
            draw.rectangle([px - 3, py - 10, px + 3, py - 3], fill=(0, 230, 255), outline=(255, 255, 255))  # Hoodie Body
            draw.ellipse([px - 3, py - 15, px + 3, py - 10], fill=(255, 210, 170))                          # Head
            draw.rectangle([px - 3, py - 16, px + 3, py - 14], fill=(255, 40, 60))                           # Cap
            draw.line([(px - 6, py - 2), (px + 6, py - 2)], fill=(255, 215, 0), width=2)                     # Hoverboard

        # Draw Text Popups
        for p in self.popups:
            draw.text((int(p['x']), int(p['y'])), p['text'], fill=(255, 255, 255))

        # 5. Clean Modern ASCII HUD & Frame Stream Render
        rgb = img.convert("RGB")
        pixels = list(rgb.getdata())
        
        buffer = ["\033[H"]  # Reset cursor home
        
        # Clean Bordered HUD Panel Header
        buffer.append("\033[1;36m┌" + "─" * (CANVAS_W + 2) + "┐\033[0m")
        hud_line = f"\033[1;36m│ \033[1;37mSCORE: \033[1;36m{self.score:06d} \033[1;37m│ \033[1;33mCOINS: 🪙 {self.coins:03d} \033[1;37m│ \033[1;35mMULTI: x{self.multiplier} \033[1;36m│\033[0m"
        buffer.append(hud_line.center(CANVAS_W + 36))
        
        # Power-Up Status Indicators
        pwr_status = ""
        if self.magnet_timer > 0: pwr_status += f"\033[1;31m[🧲 MAGNET {self.magnet_timer//10}s] \033[0m"
        if self.jetpack_timer > 0: pwr_status += f"\033[1;32m[🚀 JETPACK {self.jetpack_timer//10}s] \033[0m"
        
        if pwr_status:
            buffer.append(f"\033[1;36m│ \033[0m{pwr_status.center(CANVAS_W - 4)}\033[1;36m │\033[0m")
        buffer.append("\033[1;36m└" + "─" * (CANVAS_W + 2) + "┘\033[0m")

        # Half-block Truecolor Screen Rendering Loop
        for y in range(0, CANVAS_H, 2):
            line = []
            y1_offset = y * CANVAS_W
            y2_offset = (y + 1) * CANVAS_W

            for x in range(CANVAS_W):
                r1, g1, b1 = pixels[y1_offset + x]
                r2, g2, b2 = pixels[y2_offset + x]
                line.append(f"\033[38;2;{r1};{g1};{b1}m\033[48;2;{r2};{g2};{b2}m▀")

            buffer.append("".join(line) + "\033[0m")

        buffer.append("\033[1;30m Controls: A/D = Move │ W = Jump │ S = Roll/Fast Fall │ Q = Quit\033[0m")
        sys.stdout.write("\n".join(buffer) + "\n")
        sys.stdout.flush()

    def run(self):
        sys.stdout.write("\033[?25l\033[2J")  # Hide terminal cursor & clear screen
        sys.stdout.flush()

        with LinuxRawInput():
            try:
                while not self.game_over:
                    t_start = time.perf_counter()

                    keys = get_keys()
                    self.process_input(keys)
                    self.update_physics()
                    self.render_frame()

                    # Precise 60 FPS Engine Timing
                    elapsed = time.perf_counter() - t_start
                    if 0.0166 > elapsed:
                        time.sleep(0.0166 - elapsed)

                sys.stdout.write("\033[1;31m\n  ==================== GAME OVER ====================\033[0m\n")
                sys.stdout.write(f"   Final Score: \033[1;36m{self.score}\033[0m | Total Coins: \033[1;33m{self.coins}\033[0m\n\n")

            finally:
                sys.stdout.write("\033[?25h\033[0m")  # Restore cursor

if __name__ == "__main__":
    game = SubwayEngineHD()
    game.run()
