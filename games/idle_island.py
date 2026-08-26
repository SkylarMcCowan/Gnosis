"""Idle Island - a long-form idle/incremental fishing game. Cast a line by
hand on the dock, buy better rods and bait, then buy boats that fish for
you even while the app is closed (offline progress is calculated on load).
Rare talking fish are a random bonus on top of every catch - each one is a
permanent collectible with a toggleable buff, competing for a limited
number of active "buff slots" that only grows through prestige.

Pure PyQt6, no extra dependencies. Split into two halves: the top of this
file is plain-Python economy/content (RODS, BAITS, BOATS, RARE_FISH, and
the math functions) with zero Qt imports, so the whole simulation can be
unit-tested without a QApplication; IdleIslandWidget below is just a thin
UI layer over that state.
"""
import json
import math
import os
import random
import time

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QStackedLayout, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from core import config as core_config
from games.audio import SoundPlayer

# ----------------------------------------------------------------------
# Economy content
# ----------------------------------------------------------------------
RODS = [
    {"name": "Bare Hands", "cost": 0, "power": 1},
    {"name": "Bent Twig Rod", "cost": 10, "power": 2},
    {"name": "Bamboo Rod", "cost": 100, "power": 5},
    {"name": "Steel Rod", "cost": 1_000, "power": 15},
    {"name": "Carbon Fiber Rod", "cost": 10_000, "power": 50},
    {"name": "Enchanted Rod", "cost": 100_000, "power": 200},
    {"name": "Laser Rod 3000", "cost": 1_000_000, "power": 1_000},
    {"name": "Quantum Entanglement Rod", "cost": 10_000_000, "power": 6_000},
]

BAITS = [
    {"name": "No Bait", "cost": 0, "mult": 1.0},
    {"name": "Wriggly Worms", "cost": 50, "mult": 1.2},
    {"name": "Stinky Shrimp", "cost": 500, "mult": 1.5},
    {"name": "Glowing Lure", "cost": 5_000, "mult": 2.0},
    {"name": "Mermaid's Tears", "cost": 50_000, "mult": 3.0},
    {"name": "Forbidden Chum", "cost": 500_000, "mult": 5.0},
]

BOAT_COST_GROWTH = 1.15
BOATS = [
    {"key": "rowboat", "name": 'Rowboat "The Squeaky Oar"', "base_cost": 15, "base_yield": 0.1},
    {"key": "dinghy", "name": 'Dinghy "Lil\' Puddle Jumper"', "base_cost": 100, "base_yield": 1},
    {"key": "skiff", "name": 'Fishing Skiff "Net Worth"', "base_cost": 1_100, "base_yield": 8},
    {"key": "trawler", "name": 'Trawler "Reel Deal"', "base_cost": 12_000, "base_yield": 47},
    {"key": "yacht", "name": 'Yacht "S.S. Disappointment"', "base_cost": 130_000, "base_yield": 260},
    {"key": "cargo", "name": 'Cargo Ship "Codependent"', "base_cost": 1_400_000, "base_yield": 1_400},
    {"key": "flagship", "name": 'Command Vessel "Admiral Awesome"', "base_cost": 20_000_000, "base_yield": 7_800},
    {"key": "kraken", "name": 'Mega Trawler "Nope Rope"', "base_cost": 330_000_000, "base_yield": 44_000},
]

TIER_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"]
TIER_COLOR = {
    "Common": "#b4b4c4", "Uncommon": "#3ecf8e", "Rare": "#4c8bf5",
    "Epic": "#a855f7", "Legendary": "#f5a524", "Mythic": "#e5484d",
}
TIER_DISCOVERY_BONUS = {
    "Common": 500, "Uncommon": 2_500, "Rare": 15_000,
    "Epic": 100_000, "Legendary": 750_000, "Mythic": 5_000_000,
}

# 50 rare fish. `effect.type` is one of:
#   click_mult / boat_mult / global_mult / rare_chance_mult / boat_cost_mult /
#   resistance_mult  - ongoing, toggleable in Settings, value is a fraction (0.05 = +5%)
#   buff_slot        - permanent, applied once on first catch, never toggleable
#   cosmetic         - toggleable but mechanically inert, pure flavor
RARE_FISH = [
    # Common (weight 100)
    {"name": "Sir Nibbles the Wise", "tier": "Common", "weight": 100,
     "quote": "I have eaten this same worm for three generations. Worth it.",
     "effect": {"type": "click_mult", "value": 0.03}},
    {"name": "Two-Buck Chuck", "tier": "Common", "weight": 100,
     "quote": "I taste like regret and dollar-store crackers.",
     "effect": {"type": "boat_mult", "value": 0.03}},
    {"name": "Fintendo Switch", "tier": "Common", "weight": 100,
     "quote": "I have exactly 47% battery and I am judging your backlog.",
     "effect": {"type": "rare_chance_mult", "value": 0.03}},
    {"name": "Karen the Complaint Cod", "tier": "Common", "weight": 100,
     "quote": "I'd like to speak to your manager. Also please don't eat me.",
     "effect": {"type": "global_mult", "value": 0.03}},
    {"name": "Beluga Cage", "tier": "Common", "weight": 100,
     "quote": "NOT THE BAIT! NOT THE BAIT!",
     "effect": {"type": "click_mult", "value": 0.03}},
    {"name": "Lil' Bass Pro", "tier": "Common", "weight": 100,
     "quote": "I unionized. We have dental now.",
     "effect": {"type": "boat_cost_mult", "value": 0.04}},
    {"name": "A Very Suspicious Rubber Duck", "tier": "Common", "weight": 100,
     "quote": "Squeak. (This is not a fish. This is deeply, deeply not a fish.)",
     "effect": {"type": "cosmetic", "value": 0}},
    {"name": "Anchovy Stark", "tier": "Common", "weight": 100,
     "quote": "I am inevitable. Also I am three inches long.",
     "effect": {"type": "global_mult", "value": 0.04}},
    {"name": "The Notorious C.O.D.", "tier": "Common", "weight": 100,
     "quote": "Mo' fish, mo' problems.",
     "effect": {"type": "boat_mult", "value": 0.03}},
    {"name": "Salmon Rushdie", "tier": "Common", "weight": 100,
     "quote": "My opinions on this river are, frankly, controversial.",
     "effect": {"type": "click_mult", "value": 0.03}},
    {"name": "Cousin Eddie the Catfish", "tier": "Common", "weight": 100,
     "quote": "This here's a genuine Fishzilla, folks.",
     "effect": {"type": "boat_mult", "value": 0.04}},
    {"name": "Wanda the Sole Survivor", "tier": "Common", "weight": 100,
     "quote": "I've been through eight nets and a wasabi factory. Built different.",
     "effect": {"type": "rare_chance_mult", "value": 0.04}},
    {"name": "Perch Hilton", "tier": "Common", "weight": 100,
     "quote": "That's hot. Also I'm stuck in a bucket, please help.",
     "effect": {"type": "global_mult", "value": 0.03}},
    {"name": "Grouper Oprah", "tier": "Common", "weight": 100,
     "quote": "YOU get a buff! YOU get a buff! EVERYBODY gets a buff!",
     "effect": {"type": "click_mult", "value": 0.04}},
    {"name": "Disco Flounder", "tier": "Common", "weight": 100,
     "quote": "Ah, ah, ah, ah, stayin' aliiive. Also I glow under blacklight.",
     "effect": {"type": "cosmetic", "value": 0}},

    # Uncommon (weight 40)
    {"name": "Cod Vader", "tier": "Uncommon", "weight": 40,
     "quote": "I find your lack of bait disturbing.",
     "effect": {"type": "boat_mult", "value": 0.06}},
    {"name": "Tuna Turner", "tier": "Uncommon", "weight": 40,
     "quote": "Rolling, rolling, rolling on the river. Get it? I'm a fish.",
     "effect": {"type": "click_mult", "value": 0.07}},
    {"name": "Sushi Rogers", "tier": "Uncommon", "weight": 40,
     "quote": "It's a beautiful day in this neighborhood. Please don't roll me.",
     "effect": {"type": "global_mult", "value": 0.07}},
    {"name": "The Trout of Cthulhu", "tier": "Uncommon", "weight": 40,
     "quote": "Ph'nglui mglw'nafh... anyway, got any bread crumbs?",
     "effect": {"type": "rare_chance_mult", "value": 0.08}},
    {"name": "Eel Musk", "tier": "Uncommon", "weight": 40,
     "quote": "I bought this river. It's called X-quarium now.",
     "effect": {"type": "boat_cost_mult", "value": 0.08}},
    {"name": "Mackerel Poppins", "tier": "Uncommon", "weight": 40,
     "quote": "Practically perfectly filleted in every way.",
     "effect": {"type": "click_mult", "value": 0.06}},
    {"name": "Pikeachu", "tier": "Uncommon", "weight": 40,
     "quote": "Pika-- wait, wrong universe. Splash splash.",
     "effect": {"type": "rare_chance_mult", "value": 0.07}},
    {"name": "Bishop Herring the Reformed", "tier": "Uncommon", "weight": 40,
     "quote": "I have seen the light. The light is a fishing lantern. Turn it off.",
     "effect": {"type": "boat_mult", "value": 0.07}},
    {"name": "Kevin Bacon Fish (no relation)", "tier": "Uncommon", "weight": 40,
     "quote": "Everyone's connected to me within six casts.",
     "effect": {"type": "global_mult", "value": 0.08}},
    {"name": "Sir Swims-a-Lot", "tier": "Uncommon", "weight": 40,
     "quote": "I was knighted for services to floating around.",
     "effect": {"type": "click_mult", "value": 0.06}},
    {"name": "The Big Lebowfish", "tier": "Uncommon", "weight": 40,
     "quote": "The Dude abides. The current also abides. Very relaxing, man.",
     "effect": {"type": "boat_mult", "value": 0.08}},
    {"name": "Dora the Explorer Fish", "tier": "Uncommon", "weight": 40,
     "quote": "Swiper, no swiping my lake!",
     "effect": {"type": "rare_chance_mult", "value": 0.07}},
    {"name": "Free Willy Jr.", "tier": "Uncommon", "weight": 40,
     "quote": "Nobody puts baby in a tank.",
     "effect": {"type": "global_mult", "value": 0.08}},
    {"name": "Moby's Cousin Dick", "tier": "Uncommon", "weight": 40,
     "quote": "Call me... actually just call me Steve.",
     "effect": {"type": "boat_mult", "value": 0.07}},
    {"name": "Han Solo-mon", "tier": "Uncommon", "weight": 40,
     "quote": "I fished the Kessel Run in twelve parsecs. Distance thing, don't worry about it.",
     "effect": {"type": "click_mult", "value": 0.09}},

    # Rare (weight 15)
    {"name": "The Godfisher", "tier": "Rare", "weight": 15,
     "quote": "I'm gonna make you an offer you can't refuse: 15% off bait.",
     "effect": {"type": "boat_mult", "value": 0.15}},
    {"name": "Gandalf the Grey Mullet", "tier": "Rare", "weight": 15,
     "quote": "YOU. SHALL NOT. GET NETTED.",
     "effect": {"type": "rare_chance_mult", "value": 0.15}},
    {"name": "Bilbo Baggins the Bass", "tier": "Rare", "weight": 15,
     "quote": "I'm going on an adventure! Right after this nap.",
     "effect": {"type": "click_mult", "value": 0.12}},
    {"name": "Darth Trader", "tier": "Rare", "weight": 15,
     "quote": "Join the dark side. We have discounted rods.",
     "effect": {"type": "boat_cost_mult", "value": 0.15}},
    {"name": "Neo the One (Betta Fish)", "tier": "Rare", "weight": 15,
     "quote": "There is no spoon. There is also, apparently, no net.",
     "effect": {"type": "rare_chance_mult", "value": 0.18}},
    {"name": "Aragorn, Son of Arasole", "tier": "Rare", "weight": 15,
     "quote": "You have my rod, my reel, and my tackle box.",
     "effect": {"type": "global_mult", "value": 0.15}},
    {"name": "Shrek the Herring", "tier": "Rare", "weight": 15,
     "quote": "Fish are like onions. We have layers. We also smell.",
     "effect": {"type": "boat_mult", "value": 0.18}},
    {"name": "Marty McFish", "tier": "Rare", "weight": 15,
     "quote": "Great Scott! I need 1.21 gigawatts of bait!",
     "effect": {"type": "rare_chance_mult", "value": 0.15}},
    {"name": "The Mandalorian Manta", "tier": "Rare", "weight": 15,
     "quote": "This is the way. The way to the shallows, specifically.",
     "effect": {"type": "global_mult", "value": 0.15}},
    {"name": "The Duke of Herring, 3rd Baronet", "tier": "Rare", "weight": 15,
     "quote": "One does not simply swim into the shallows unannounced.",
     "effect": {"type": "cosmetic", "value": 0}},

    # Epic (weight 5)
    {"name": "The Kraken's Nephew, Gary", "tier": "Epic", "weight": 5,
     "quote": "Uncle's busy today. He said to give you this instead.",
     "effect": {"type": "buff_slot", "value": 1}},
    {"name": "Poseidon's Intern", "tier": "Epic", "weight": 5,
     "quote": "He's on lunch. I'm covering. I get 30% of his powers, unpaid.",
     "effect": {"type": "boat_mult", "value": 0.30}},
    {"name": "The Loch Ness Minnow", "tier": "Epic", "weight": 5,
     "quote": "I'm real. I'm just very, very small and easily overlooked.",
     "effect": {"type": "rare_chance_mult", "value": 0.35}},
    {"name": "Jean-Luc Pickerel", "tier": "Epic", "weight": 5,
     "quote": "Make it so. The 'it' being a really strong bass boat.",
     "effect": {"type": "global_mult", "value": 0.30}},
    {"name": "Aquaman's Roommate, Steve", "tier": "Epic", "weight": 5,
     "quote": "He gets all the press. I do the actual talking to fish.",
     "effect": {"type": "buff_slot", "value": 1}},
    {"name": "Baby Yodabass", "tier": "Epic", "weight": 5,
     "quote": "This is not a Pokemon. This is not a Pokemon. This is not a—",
     "effect": {"type": "click_mult", "value": 0.35}},

    # Legendary (weight 2)
    {"name": "The Ancient One, Steve Sr.", "tier": "Legendary", "weight": 2,
     "quote": "I am older than the concept of Mondays. I've earned this.",
     "effect": {"type": "global_mult", "value": 0.60}},
    {"name": "Wilson (He Learned to Swim)", "tier": "Legendary", "weight": 2,
     "quote": "WIIIILSOOOON— wait, that's my catchphrase, not yours.",
     "effect": {"type": "buff_slot", "value": 2}},
    {"name": "The Fisherman's Ex, Karen 2.0", "tier": "Legendary", "weight": 2,
     "quote": "I'm not rare, I'm LIMITED EDITION. There's a difference.",
     "effect": {"type": "resistance_mult", "value": 0.75}},

    # Mythic (weight 1)
    {"name": "THE ONE FISH, Chosen of the Tides", "tier": "Mythic", "weight": 1,
     "quote": "You have freed me from the deep fryer of fate. I want a Netflix deal.",
     "effect": {"type": "global_mult", "value": 1.00}},
]

assert len(RARE_FISH) == 50, f"expected exactly 50 rare fish, got {len(RARE_FISH)}"

BASE_CLICK_RARE_CHANCE = 0.005   # 0.5% per manual cast
BASE_BOAT_RARE_CHANCE_PER_SEC = 0.0006  # per boat owned, per second
CLICK_COOLDOWN_SECONDS = 1.0
DEFAULT_OFFLINE_CAP_HOURS = 8.0
STARTING_BUFF_SLOTS = 3

INTRO_TEXT = (
    "CAPTAIN'S LOG, DAY 1.\n\n"
    "So. Here's the thing. I was a software developer. Senior, even - it said so on the "
    "business cards I definitely paid for myself. My job was 40% writing code, 40% attending "
    "meetings about the code, and 20% explaining to those meetings why the code was late.\n\n"
    "Then came the Company Team-Building Cruise. Mandatory fun. Someone said the words "
    "'trust fall' un-ironically. I do not remember agreeing to any of this.\n\n"
    "I remember a storm. I remember a life raft shaped suspiciously like a beanbag chair "
    "from the old office. I remember waking up on a beach with sand in places sand should "
    "legally not be allowed to go.\n\n"
    "And I remember thinking: well, there's no Wi-Fi, no standup meetings, and no one asking "
    "if I 'have a sec.' Could be worse.\n\n"
    "There's a dock. There's fish. As it turns out, on Idle Island, the fish TALK - and they "
    "are, without exception, extremely opinionated. Some of them, I am told, are part of a "
    "'Resistance.' I did not ask what they are resisting. I am a lazy developer, not a war "
    "correspondent.\n\n"
    "But I know an idle loop when I see one. Cast a line. Get fish. Get a better rod. Get a "
    "boat. Get MORE boats. Retire to a beach chair and let the fleet do the work while I take "
    "a nap that may or may not last several fiscal quarters.\n\n"
    "This is Idle Island. Let's go catch some weird, talkative fish."
)


# ----------------------------------------------------------------------
# Pure economy functions - no Qt, safe to unit test directly
# ----------------------------------------------------------------------
def format_number(n):
    """K/M/B/T/... suffix formatting for the large numbers an idle game
    produces - a bare float would be unreadable within a few minutes of
    play."""
    n = float(n)
    if n < 1000:
        return f"{n:.1f}" if n != int(n) else f"{int(n)}"
    suffixes = ["", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc"]
    magnitude = 0
    while abs(n) >= 999.995 and magnitude < len(suffixes) - 1:
        n /= 1000.0
        magnitude += 1
    return f"{n:.2f}{suffixes[magnitude]}"


def boat_cost(boat_index, owned, boat_cost_mult=1.0):
    base = BOATS[boat_index]["base_cost"]
    return base * (BOAT_COST_GROWTH ** owned) * boat_cost_mult


def boat_bulk_cost(boat_index, owned, count, boat_cost_mult=1.0):
    """Cost to buy `count` more of a boat starting from `owned` already
    owned - the closed-form sum of a geometric series (base * growth^owned
    + base * growth^(owned+1) + ...), not a loop, since count can be large
    ("buy 10" / "buy max")."""
    base = BOATS[boat_index]["base_cost"]
    growth = BOAT_COST_GROWTH
    return base * (growth ** owned) * (growth ** count - 1) / (growth - 1) * boat_cost_mult


def total_boat_yield_per_sec(boats_owned):
    return sum(BOATS[i]["base_yield"] * boats_owned.get(BOATS[i]["key"], 0) for i in range(len(BOATS)))


def compute_multipliers(caught_fish_names, active_buff_names):
    """Aggregates every ACTIVE (toggled-on) buff's effect into one dict of
    multipliers, plus the running total of permanent buff-slot bonuses
    granted by fish whose effect type is "buff_slot" - those are never
    toggleable, so every caught one that grants a slot always counts,
    regardless of what's in active_buff_names."""
    mult = {
        "click": 1.0, "boat": 1.0, "global": 1.0,
        "rare_chance": 1.0, "boat_cost": 1.0, "resistance": 1.0,
    }
    bonus_slots = 0
    active_set = set(active_buff_names)
    for fish in RARE_FISH:
        if fish["name"] not in caught_fish_names:
            continue
        effect = fish["effect"]
        if effect["type"] == "buff_slot":
            bonus_slots += effect["value"]
        elif effect["type"] == "cosmetic":
            continue
        elif fish["name"] in active_set:
            key = {
                "click_mult": "click", "boat_mult": "boat", "global_mult": "global",
                "rare_chance_mult": "rare_chance", "boat_cost_mult": "boat_cost",
                "resistance_mult": "resistance",
            }[effect["type"]]
            if key == "boat_cost":
                mult[key] *= max(0.1, 1.0 - effect["value"])
            else:
                mult[key] += effect["value"]
    return mult, bonus_slots


def roll_rare_fish(caught_fish_names):
    """Weighted-random pick across all 50 fish. Landing on an
    already-caught one is handled by the caller (converted to a small
    currency bonus instead of a duplicate "new discovery")."""
    total_weight = sum(f["weight"] for f in RARE_FISH)
    roll = random.uniform(0, total_weight)
    upto = 0.0
    for fish in RARE_FISH:
        upto += fish["weight"]
        if roll <= upto:
            return fish
    return RARE_FISH[-1]


def resistance_points_for_prestige(lifetime_fish, resistance_mult=1.0):
    if lifetime_fish < 1_000_000:
        return 0
    return int(math.floor(math.sqrt(lifetime_fish / 1_000_000.0) * resistance_mult))


def offline_progress(elapsed_seconds, boats_owned, mult, offline_cap_hours=DEFAULT_OFFLINE_CAP_HOURS):
    capped_seconds = min(elapsed_seconds, offline_cap_hours * 3600)
    yield_per_sec = total_boat_yield_per_sec(boats_owned) * mult["boat"] * mult["global"]
    return capped_seconds * yield_per_sec, capped_seconds


def new_save_state():
    now = time.time()
    return {
        "fish": 0.0, "lifetime_fish": 0.0, "fish_since_prestige": 0.0, "resistance_points": 0,
        "rod_index": 0, "bait_index": 0,
        "boats_owned": {},
        "caught_fish": [], "active_buffs": [],
        "seen_intro": False, "sound_enabled": True,
        "created_at": now, "last_saved": now,
    }


def format_time_ago(seconds):
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} minute(s) ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hour(s) ago"
    return f"{int(seconds // 86400)} day(s) ago"


# ----------------------------------------------------------------------
# Save-slot persistence - up to SAVE_SLOTS separate campaigns, each its own
# JSON file. Same lazy-mkdir-on-write-only pattern as core/activity_log.py
# and core/subscriptions.py: a read must never create the directory.
# ----------------------------------------------------------------------
SAVE_SLOTS = (1, 2, 3)


def save_path(slot):
    return os.path.join(core_config.path("games"), f"idle_island_save_{slot}.json")


def load_slot(slot):
    path = save_path(slot)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    merged = new_save_state()
    merged.update(data)
    return merged


def save_slot(slot, state):
    state["last_saved"] = time.time()
    path = save_path(slot)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        pass


def delete_slot(slot):
    try:
        os.remove(save_path(slot))
    except FileNotFoundError:
        pass


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------
TOGGLEABLE_EFFECT_LABELS = {
    "click_mult": "+{pct}% fish per cast",
    "boat_mult": "+{pct}% fleet fishing speed",
    "global_mult": "+{pct}% ALL fish gain",
    "rare_chance_mult": "+{pct}% rare fish chance",
    "boat_cost_mult": "-{pct}% boat cost",
    "resistance_mult": "+{pct}% Resistance Points on prestige",
    "cosmetic": "purely cosmetic - no mechanical effect",
}


def _effect_description(effect):
    if effect["type"] == "buff_slot":
        return f"+{effect['value']} permanent buff slot (always active)"
    if effect["type"] == "cosmetic":
        return TOGGLEABLE_EFFECT_LABELS["cosmetic"]
    return TOGGLEABLE_EFFECT_LABELS[effect["type"]].format(pct=round(effect["value"] * 100))


# Consistent "this is a choice you can make" affordance across the whole
# game: a blue outline on anything clickable/selectable, dimmed to a plain
# grey outline when disabled (can't afford it / not a valid choice right
# now) so the two states are visually obvious at a glance, not just a
# faint opacity change. STYLE_TOGGLE_ON/OFF give the same treatment to a
# binary on/off choice (a buff, sound) in green/red instead of blue, so
# "this is currently active" reads instantly without needing to read the
# label text.
STYLE_SELECTABLE = """
    QPushButton {
        border: 2px solid #4c8bf5;
        border-radius: 6px;
        padding: 4px 10px;
        background-color: #16233b;
        color: #eaeaf2;
    }
    QPushButton:hover {
        background-color: #1f3255;
    }
    QPushButton:disabled {
        border: 2px solid #33333f;
        background-color: #1a1a24;
        color: #5a5a6a;
    }
"""

STYLE_TOGGLE_ON = """
    QPushButton {
        border: 2px solid #3ecf8e;
        border-radius: 6px;
        padding: 4px 10px;
        background-color: #16332a;
        color: #3ecf8e;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #1c4536;
    }
"""

STYLE_TOGGLE_OFF = """
    QPushButton {
        border: 2px solid #e5484d;
        border-radius: 6px;
        padding: 4px 10px;
        background-color: #33191c;
        color: #e5484d;
    }
    QPushButton:hover {
        background-color: #422226;
    }
"""


WAVE_LAYERS = [
    # (color, speed, amplitude, y_fraction, wavelength) - back-to-front,
    # slower/dimmer layers first so the effect reads as depth, not noise.
    (QColor(20, 60, 90), 0.25, 10, 0.78, 220),
    (QColor(28, 84, 120), 0.4, 14, 0.85, 160),
    (QColor(38, 110, 150), 0.6, 18, 0.93, 120),
]


class OceanBackgroundWidget(QWidget):
    """A quiet animated water backdrop for the Dock tab, plus the two
    "juice" effects that make catching a fish feel like something actually
    happened: an expanding ripple wherever a splash is spawned, and a
    brief full-widget color flash for a new rare-fish discovery. Purely
    decorative - carries no game state - so it's fine to let it free-run
    its own animation clock rather than being driven by IdleIslandWidget's
    tick() the way the economy simulation is.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._phase = 0.0
        self.particles = []  # each: {"x","y","radius","max_radius","alpha"}
        self.flash_color = None
        self.flash_alpha = 0.0

    def spawn_splash(self, x=None, y=None, big=False):
        if x is None:
            x = self.width() * random.uniform(0.35, 0.65)
        if y is None:
            y = self.height() * random.uniform(0.55, 0.7)
        count = 3 if big else 1
        for _ in range(count):
            self.particles.append({
                "x": x + random.uniform(-12, 12), "y": y + random.uniform(-6, 6),
                "radius": 2.0, "max_radius": 46 if big else 26, "alpha": 0.8,
            })

    def spawn_flash(self, color):
        self.flash_color = color
        self.flash_alpha = 0.35

    def tick(self, dt):
        self._phase += dt
        survivors = []
        for p in self.particles:
            p["radius"] += (60 if p["max_radius"] > 30 else 40) * dt
            p["alpha"] -= dt * 1.1
            if p["alpha"] > 0 and p["radius"] < p["max_radius"]:
                survivors.append(p)
        self.particles = survivors
        if self.flash_alpha > 0:
            self.flash_alpha = max(0.0, self.flash_alpha - dt * 1.2)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(10, 24, 36))

        w, h = self.width(), self.height()
        for color, speed, amplitude, y_fraction, wavelength in WAVE_LAYERS:
            base_y = h * y_fraction
            points = [(0, h)]
            step = 8
            x = 0
            while x <= w:
                y = base_y + amplitude * math.sin((x / wavelength) + self._phase * speed * 2 * math.pi)
                points.append((x, y))
                x += step
            points.append((w, h))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(QPolygonF([QPointF(px, py) for px, py in points]))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for p in self.particles:
            pen = QPen(QColor(200, 230, 255, max(0, int(p["alpha"] * 180))))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawEllipse(int(p["x"] - p["radius"]), int(p["y"] - p["radius"]), int(p["radius"] * 2), int(p["radius"] * 2))

        if self.flash_alpha > 0 and self.flash_color is not None:
            color = QColor(self.flash_color)
            color.setAlphaF(min(1.0, self.flash_alpha))
            painter.fillRect(self.rect(), color)
        painter.end()


class IdleIslandWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self.current_slot = None
        self.mult = {"click": 1.0, "boat": 1.0, "global": 1.0, "rare_chance": 1.0, "boat_cost": 1.0, "resistance": 1.0}
        self.buff_slots_total = STARTING_BUFF_SLOTS
        self.click_ready_at = 0.0
        self.boat_rows = {}
        self.sound = SoundPlayer()
        self._last_tick = time.monotonic()

        outer = QVBoxLayout(self)
        self.stack = QStackedLayout()
        outer.addLayout(self.stack)

        self.slot_select_page = self._build_slot_select_page()
        self.stack.addWidget(self.slot_select_page)
        self.game_page = None

        self._refresh_slot_select_page()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._tick)
        self.tick_timer.start(200)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start(30_000)

    # ------------------------------------------------------------------
    # Slot-select screen
    # ------------------------------------------------------------------
    def _build_slot_select_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("🏝️ Idle Island")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Choose a save file:"))

        self.slot_cards = {}
        for slot in SAVE_SLOTS:
            card = self._build_slot_card(slot)
            layout.addWidget(card["widget"])
            self.slot_cards[slot] = card
        layout.addStretch()
        return page

    def _build_slot_card(self, slot):
        container = QWidget()
        container.setStyleSheet("background-color:#1e1e28; border:1px solid #33333f; border-radius:8px;")
        row = QHBoxLayout(container)
        label = QLabel("")
        label.setWordWrap(True)
        row.addWidget(label, 1)
        play_button = QPushButton("Play")
        play_button.setStyleSheet(STYLE_SELECTABLE)
        play_button.clicked.connect(lambda checked=False, slot=slot: self._enter_slot(slot))
        row.addWidget(play_button)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(lambda checked=False, slot=slot: self._delete_slot_clicked(slot))
        row.addWidget(delete_button)
        return {"widget": container, "label": label, "play_button": play_button, "delete_button": delete_button}

    def _refresh_slot_select_page(self):
        for slot in SAVE_SLOTS:
            data = load_slot(slot)
            card = self.slot_cards[slot]
            if data is None:
                card["label"].setText(f"Slot {slot}: empty - start a new game")
                card["play_button"].setText("New Game")
                card["delete_button"].setEnabled(False)
            else:
                ago = format_time_ago(time.time() - data.get("last_saved", 0))
                card["label"].setText(
                    f"Slot {slot}: {format_number(data.get('lifetime_fish', 0))} lifetime fish, "
                    f"{data.get('resistance_points', 0)} Resistance Points, "
                    f"{len(data.get('caught_fish', []))}/50 fish caught - last played {ago}"
                )
                card["play_button"].setText("Continue")
                card["delete_button"].setEnabled(True)

    def _delete_slot_clicked(self, slot):
        reply = QMessageBox.question(
            self, "Delete Save", f"Permanently delete Slot {slot}? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_slot(slot)
            self._refresh_slot_select_page()

    def _enter_slot(self, slot):
        data = load_slot(slot)
        is_new = data is None
        if data is None:
            data = new_save_state()
        self.current_slot = slot
        self.state = data
        self.sound.enabled = self.state.get("sound_enabled", True)
        self._recompute_multipliers()
        self._ensure_game_page()
        self._load_state_into_ui()

        if not is_new:
            elapsed = max(0.0, time.time() - data.get("last_saved", time.time()))
            gained, capped_seconds = offline_progress(elapsed, self.state["boats_owned"], self.mult)
            if gained > 0:
                self.state["fish"] += gained
                self.state["lifetime_fish"] += gained
                self.state["fish_since_prestige"] += gained
                hours = capped_seconds / 3600
                self._log(
                    f"⚓ Welcome back! Your fleet caught {format_number(gained)} fish while you were "
                    f"away ({hours:.1f}h of offline fishing)."
                )
                self._refresh_dock()

        self.stack.setCurrentWidget(self.game_page)
        if not self.state.get("seen_intro"):
            self.state["seen_intro"] = True
            self._show_intro_dialog()
        self._save_current()

    def _show_intro_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Idle Island")
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(INTRO_TEXT)
        layout.addWidget(text)
        start_button = QPushButton("Start Fishing")
        start_button.clicked.connect(dialog.accept)
        layout.addWidget(start_button)
        dialog.resize(520, 480)
        dialog.exec()

    def _switch_slot_clicked(self):
        self._save_current()
        self._refresh_slot_select_page()
        self.stack.setCurrentWidget(self.slot_select_page)

    # ------------------------------------------------------------------
    # Game page (built once, contents refreshed per slot)
    # ------------------------------------------------------------------
    def _ensure_game_page(self):
        if self.game_page is not None:
            return
        self.game_page = QWidget()
        layout = QVBoxLayout(self.game_page)

        header = QHBoxLayout()
        self.slot_header_label = QLabel("")
        self.slot_header_label.setStyleSheet("font-weight: bold;")
        header.addWidget(self.slot_header_label)
        header.addStretch()
        story_button = QPushButton("Read Story Again")
        story_button.setStyleSheet(STYLE_SELECTABLE)
        story_button.clicked.connect(self._show_intro_dialog)
        header.addWidget(story_button)
        switch_button = QPushButton("Switch Save Slot")
        switch_button.setStyleSheet(STYLE_SELECTABLE)
        switch_button.clicked.connect(self._switch_slot_clicked)
        header.addWidget(switch_button)
        layout.addLayout(header)

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        tabs.addTab(self._build_dock_tab(), "Dock")
        tabs.addTab(self._build_fleet_tab(), "Fleet")
        tabs.addTab(self._build_collection_tab(), "Collection")
        tabs.addTab(self._build_settings_tab(), "Settings")

        self.stack.addWidget(self.game_page)

    def _build_dock_tab(self):
        page = QWidget()
        outer_stack = QStackedLayout(page)
        outer_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        outer_stack.setContentsMargins(0, 0, 0, 0)

        self.ocean_bg = OceanBackgroundWidget()
        outer_stack.addWidget(self.ocean_bg)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        outer_stack.addWidget(content)
        outer_stack.setCurrentWidget(content)

        layout = QVBoxLayout(content)

        self.fish_label = QLabel("")
        self.fish_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(self.fish_label)
        self.fish_per_sec_label = QLabel("")
        layout.addWidget(self.fish_per_sec_label)
        self.resistance_label = QLabel("")
        layout.addWidget(self.resistance_label)

        cast_row = QHBoxLayout()
        self.cast_button = QPushButton("🎣 Cast Line")
        self.cast_button.setStyleSheet(STYLE_SELECTABLE + "QPushButton { font-size: 16px; }")
        self.cast_button.clicked.connect(self._cast_line)
        cast_row.addWidget(self.cast_button)
        self.cooldown_bar = QProgressBar()
        self.cooldown_bar.setRange(0, 100)
        self.cooldown_bar.setTextVisible(False)
        cast_row.addWidget(self.cooldown_bar)
        layout.addLayout(cast_row)

        gear_row = QHBoxLayout()
        self.rod_label = QLabel("")
        gear_row.addWidget(self.rod_label)
        self.rod_upgrade_button = QPushButton("")
        self.rod_upgrade_button.setStyleSheet(STYLE_SELECTABLE)
        self.rod_upgrade_button.clicked.connect(self._buy_rod)
        gear_row.addWidget(self.rod_upgrade_button)
        layout.addLayout(gear_row)

        bait_row = QHBoxLayout()
        self.bait_label = QLabel("")
        bait_row.addWidget(self.bait_label)
        self.bait_upgrade_button = QPushButton("")
        self.bait_upgrade_button.setStyleSheet(STYLE_SELECTABLE)
        self.bait_upgrade_button.clicked.connect(self._buy_bait)
        bait_row.addWidget(self.bait_upgrade_button)
        layout.addLayout(bait_row)

        self.prestige_button = QPushButton("")
        self.prestige_button.setStyleSheet(STYLE_SELECTABLE)
        self.prestige_button.clicked.connect(self._prestige)
        layout.addWidget(self.prestige_button)

        layout.addWidget(QLabel("Catch Log:"))
        self.catch_log = QTextEdit()
        self.catch_log.setReadOnly(True)
        layout.addWidget(self.catch_log, 1)
        return page

    def _build_fleet_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addWidget(QLabel("Boats fish for you automatically, all the time, even while you're away."))
        self.fleet_fish_label = QLabel("")
        self.fleet_fish_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        outer.addWidget(self.fleet_fish_label)
        grid = QGridLayout()
        outer.addLayout(grid)
        for i, boat in enumerate(BOATS):
            name_label = QLabel(boat["name"])
            owned_label = QLabel("")
            yield_label = QLabel("")
            cost_label = QLabel("")
            buy1 = QPushButton("+1")
            buy1.setStyleSheet(STYLE_SELECTABLE)
            buy1.clicked.connect(lambda checked=False, i=i: self._buy_boat(i, 1))
            buy10 = QPushButton("+10")
            buy10.setStyleSheet(STYLE_SELECTABLE)
            buy10.clicked.connect(lambda checked=False, i=i: self._buy_boat(i, 10))
            grid.addWidget(name_label, i, 0)
            grid.addWidget(owned_label, i, 1)
            grid.addWidget(yield_label, i, 2)
            grid.addWidget(cost_label, i, 3)
            grid.addWidget(buy1, i, 4)
            grid.addWidget(buy10, i, 5)
            self.boat_rows[boat["key"]] = {
                "owned_label": owned_label, "yield_label": yield_label,
                "cost_label": cost_label, "buy1": buy1, "buy10": buy10,
            }
        outer.addStretch()
        return page

    def _build_collection_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        self.collection_summary_label = QLabel("")
        outer.addWidget(self.collection_summary_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.collection_content = QWidget()
        self.collection_layout = QVBoxLayout(self.collection_content)
        scroll.setWidget(self.collection_content)
        outer.addWidget(scroll, 1)
        return page

    def _build_settings_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)

        sound_row = QHBoxLayout()
        sound_row.addWidget(QLabel("Sound effects:"))
        self.sound_toggle_button = QPushButton("")
        self.sound_toggle_button.setCheckable(True)
        self.sound_toggle_button.clicked.connect(self._toggle_sound)
        sound_row.addWidget(self.sound_toggle_button)
        sound_row.addStretch()
        outer.addLayout(sound_row)

        self.buff_slots_label = QLabel("")
        outer.addWidget(self.buff_slots_label)
        outer.addWidget(QLabel(
            "Turn on the buffs from fish you've caught - you can only have a limited number active "
            "at once, so choose wisely. Buff-slot fish and cosmetic fish are always/never active and "
            "aren't listed here."
        ))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.settings_content = QWidget()
        self.settings_layout = QVBoxLayout(self.settings_content)
        scroll.setWidget(self.settings_content)
        outer.addWidget(scroll, 1)
        return page

    # ------------------------------------------------------------------
    # State loading into the (already-built) UI
    # ------------------------------------------------------------------
    def _load_state_into_ui(self):
        self.slot_header_label.setText(f"Playing: Slot {self.current_slot}")
        self._refresh_dock()
        self._refresh_fleet()
        self._rebuild_collection()
        self._rebuild_settings()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _cast_line(self):
        if self.state is None:
            return
        now = time.monotonic()
        if now < self.click_ready_at:
            return
        self.click_ready_at = now + CLICK_COOLDOWN_SECONDS
        rod = RODS[self.state["rod_index"]]
        gained = rod["power"] * self.mult["click"] * self.mult["global"]
        self.state["fish"] += gained
        self.state["lifetime_fish"] += gained
        self.state["fish_since_prestige"] += gained
        self._log(f"You cast your {rod['name']} and reel in {format_number(gained)} fish.")
        self.sound.play("cast")
        self.ocean_bg.spawn_splash()
        chance = BASE_CLICK_RARE_CHANCE * BAITS[self.state["bait_index"]]["mult"] * self.mult["rare_chance"]
        if random.random() < chance:
            self._trigger_rare_catch()
        self._refresh_dock()

    def _buy_rod(self):
        next_index = self.state["rod_index"] + 1
        if next_index >= len(RODS):
            return
        cost = RODS[next_index]["cost"]
        if self.state["fish"] < cost:
            return
        self.state["fish"] -= cost
        self.state["rod_index"] = next_index
        self._log(f"Upgraded to the {RODS[next_index]['name']}!")
        self.sound.play("purchase")
        self._refresh_dock()

    def _buy_bait(self):
        next_index = self.state["bait_index"] + 1
        if next_index >= len(BAITS):
            return
        cost = BAITS[next_index]["cost"]
        if self.state["fish"] < cost:
            return
        self.state["fish"] -= cost
        self.state["bait_index"] = next_index
        self._log(f"Stocked up on {BAITS[next_index]['name']}!")
        self.sound.play("purchase")
        self._refresh_dock()

    def _buy_boat(self, boat_index, count):
        boat = BOATS[boat_index]
        owned = self.state["boats_owned"].get(boat["key"], 0)
        cost = boat_bulk_cost(boat_index, owned, count, self.mult["boat_cost"])
        if self.state["fish"] < cost:
            return
        self.state["fish"] -= cost
        self.state["boats_owned"][boat["key"]] = owned + count
        self._log(f"Bought {count}x {boat['name']}.")
        self.sound.play("purchase")
        self._refresh_fleet()
        self._refresh_dock()

    def _prestige(self):
        rp_gain = resistance_points_for_prestige(self.state["fish_since_prestige"], self.mult["resistance"])
        if rp_gain <= 0:
            return
        reply = QMessageBox.question(
            self, "Set Sail for the Mainland",
            f"This resets your Fish, rod, bait, and boats - but your Collection and Resistance Points "
            f"are permanent. You'll gain {rp_gain} Resistance Point(s). Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.state["resistance_points"] += rp_gain
        self.state["fish"] = 0.0
        self.state["fish_since_prestige"] = 0.0
        self.state["rod_index"] = 0
        self.state["bait_index"] = 0
        self.state["boats_owned"] = {}
        self._log(f"⛵ You set sail for the mainland... and immediately turn back. +{rp_gain} Resistance Point(s)!")
        self.sound.play("prestige")
        self.ocean_bg.spawn_flash(QColor(TIER_COLOR["Legendary"]))
        self._recompute_multipliers()
        self._refresh_dock()
        self._refresh_fleet()
        self._save_current()

    # Tiers below Rare use the smaller fanfare, Rare/Epic the mid one, and
    # Legendary/Mythic the biggest - matches how big a deal the catch
    # actually is instead of playing the same sound for everything.
    _TIER_CATCH_SOUND = {
        "Common": "catch_common", "Uncommon": "catch_common",
        "Rare": "catch_epic", "Epic": "catch_epic",
        "Legendary": "catch_legendary", "Mythic": "catch_legendary",
    }

    def _trigger_rare_catch(self):
        fish = roll_rare_fish(self.state["caught_fish"])
        if fish["name"] in self.state["caught_fish"]:
            bonus = TIER_DISCOVERY_BONUS[fish["tier"]] * 0.1
            self.state["fish"] += bonus
            self.state["lifetime_fish"] += bonus
            self.state["fish_since_prestige"] += bonus
            self._log(f'{fish["name"]} swims by again: "{fish["quote"]}" (+{format_number(bonus)} fish)')
            self.sound.play("catch_common")
            self.ocean_bg.spawn_splash()
            return
        self.state["caught_fish"].append(fish["name"])
        bonus = TIER_DISCOVERY_BONUS[fish["tier"]]
        self.state["fish"] += bonus
        self.state["lifetime_fish"] += bonus
        self.state["fish_since_prestige"] += bonus
        color = TIER_COLOR[fish["tier"]]
        self.catch_log.append(
            f'<b style="color:{color}">🎣 NEW CATCH! {fish["name"]} ({fish["tier"]})</b><br>'
            f'"{fish["quote"]}"<br>+{format_number(bonus)} fish - check Settings to activate its buff.'
        )
        self.sound.play(self._TIER_CATCH_SOUND[fish["tier"]])
        self.ocean_bg.spawn_splash(big=True)
        self.ocean_bg.spawn_flash(QColor(color))
        self._recompute_multipliers()
        self._rebuild_collection()
        self._rebuild_settings()

    def _toggle_buff(self, name):
        active = self.state["active_buffs"]
        if name in active:
            active.remove(name)
        elif len(active) >= self.buff_slots_total:
            QMessageBox.warning(self, "No Slots Free", f"You only have {self.buff_slots_total} buff slot(s). Turn one off first.")
            return
        else:
            active.append(name)
        self._recompute_multipliers()
        self._rebuild_settings()
        self._refresh_dock()

    # ------------------------------------------------------------------
    # Refresh / tick
    # ------------------------------------------------------------------
    def _recompute_multipliers(self):
        self.mult, bonus_slots = compute_multipliers(self.state["caught_fish"], self.state["active_buffs"])
        self.buff_slots_total = STARTING_BUFF_SLOTS + bonus_slots + self.state["resistance_points"] // 5

    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.5)
        self._last_tick = now
        if self.state is None:
            return
        self.ocean_bg.tick(dt)
        boat_yield = total_boat_yield_per_sec(self.state["boats_owned"]) * self.mult["boat"] * self.mult["global"]
        gained = boat_yield * dt
        if gained:
            self.state["fish"] += gained
            self.state["lifetime_fish"] += gained
            self.state["fish_since_prestige"] += gained

        num_boats = sum(self.state["boats_owned"].values())
        if num_boats > 0:
            chance = BASE_BOAT_RARE_CHANCE_PER_SEC * num_boats * self.mult["rare_chance"] * dt
            if random.random() < chance:
                self._trigger_rare_catch()

        remaining = max(0.0, self.click_ready_at - now)
        self.cooldown_bar.setValue(int(100 * (1 - remaining / CLICK_COOLDOWN_SECONDS)) if CLICK_COOLDOWN_SECONDS else 100)
        self.cast_button.setEnabled(remaining <= 0)
        self._refresh_dock_labels_only()

    def _refresh_dock(self):
        self._refresh_dock_labels_only()
        rod_index = self.state["rod_index"]
        if rod_index + 1 < len(RODS):
            next_rod = RODS[rod_index + 1]
            self.rod_upgrade_button.setText(f"Upgrade to {next_rod['name']} ({format_number(next_rod['cost'])} fish)")
            self.rod_upgrade_button.setEnabled(self.state["fish"] >= next_rod["cost"])
            self.rod_upgrade_button.setVisible(True)
        else:
            self.rod_upgrade_button.setVisible(False)

        bait_index = self.state["bait_index"]
        if bait_index + 1 < len(BAITS):
            next_bait = BAITS[bait_index + 1]
            self.bait_upgrade_button.setText(f"Buy {next_bait['name']} ({format_number(next_bait['cost'])} fish)")
            self.bait_upgrade_button.setEnabled(self.state["fish"] >= next_bait["cost"])
            self.bait_upgrade_button.setVisible(True)
        else:
            self.bait_upgrade_button.setVisible(False)

        rp_gain = resistance_points_for_prestige(self.state["fish_since_prestige"], self.mult["resistance"])
        self.prestige_button.setText(f"⛵ Set Sail for the Mainland (+{rp_gain} Resistance Points)")
        self.prestige_button.setEnabled(rp_gain > 0)
        self._refresh_fleet_afford_state()

    def _refresh_dock_labels_only(self):
        if self.state is None:
            return
        self.fish_label.setText(f"🐟 {format_number(self.state['fish'])} fish")
        boat_yield = total_boat_yield_per_sec(self.state["boats_owned"]) * self.mult["boat"] * self.mult["global"]
        self.fish_per_sec_label.setText(f"Fleet income: {format_number(boat_yield)} fish/sec")
        self.resistance_label.setText(
            f"Resistance Points: {self.state['resistance_points']} | "
            f"Buff slots: {len(self.state['active_buffs'])}/{self.buff_slots_total} | "
            f"Collection: {len(self.state['caught_fish'])}/50"
        )
        rod = RODS[self.state["rod_index"]]
        self.rod_label.setText(f"Rod: {rod['name']} (+{format_number(rod['power'])} fish/cast)")
        bait = BAITS[self.state["bait_index"]]
        self.bait_label.setText(f"Bait: {bait['name']} ({bait['mult']}x rare chance)")

    def _refresh_fleet(self):
        for i, boat in enumerate(BOATS):
            owned = self.state["boats_owned"].get(boat["key"], 0)
            row = self.boat_rows[boat["key"]]
            row["owned_label"].setText(f"Owned: {owned}")
            row["yield_label"].setText(f"{format_number(boat['base_yield'] * owned)} fish/sec")
        self._refresh_fleet_afford_state()

    def _refresh_fleet_afford_state(self):
        self.fleet_fish_label.setText(f"🐟 Fish available: {format_number(self.state['fish'])}")
        for i, boat in enumerate(BOATS):
            owned = self.state["boats_owned"].get(boat["key"], 0)
            row = self.boat_rows[boat["key"]]
            cost1 = boat_bulk_cost(i, owned, 1, self.mult["boat_cost"])
            cost10 = boat_bulk_cost(i, owned, 10, self.mult["boat_cost"])
            row["cost_label"].setText(f"Next: {format_number(cost1)} fish")
            row["buy1"].setText(f"+1 ({format_number(cost1)})")
            row["buy10"].setText(f"+10 ({format_number(cost10)})")
            row["buy1"].setEnabled(self.state["fish"] >= cost1)
            row["buy10"].setEnabled(self.state["fish"] >= cost10)

    def _rebuild_collection(self):
        self._clear_layout(self.collection_layout)
        caught = set(self.state["caught_fish"])
        self.collection_summary_label.setText(f"{len(caught)}/50 fish discovered")
        for tier in TIER_ORDER:
            tier_fish = [f for f in RARE_FISH if f["tier"] == tier]
            caught_in_tier = sum(1 for f in tier_fish if f["name"] in caught)
            header = QLabel(f'<b style="color:{TIER_COLOR[tier]}">{tier} ({caught_in_tier}/{len(tier_fish)})</b>')
            self.collection_layout.addWidget(header)
            for fish in tier_fish:
                if fish["name"] in caught:
                    text = f'<b>{fish["name"]}</b> - "{fish["quote"]}"<br><i>{_effect_description(fish["effect"])}</i>'
                else:
                    text = "??? - not yet discovered"
                label = QLabel(text)
                label.setWordWrap(True)
                self.collection_layout.addWidget(label)
        self.collection_layout.addStretch()

    def _toggle_sound(self):
        self.state["sound_enabled"] = not self.state.get("sound_enabled", True)
        self.sound.enabled = self.state["sound_enabled"]
        self._refresh_sound_toggle_button()

    def _refresh_sound_toggle_button(self):
        enabled = self.state.get("sound_enabled", True) if self.state else True
        self.sound_toggle_button.setChecked(enabled)
        self.sound_toggle_button.setText("🔊 ON" if enabled else "🔇 OFF")
        self.sound_toggle_button.setStyleSheet(STYLE_TOGGLE_ON if enabled else STYLE_TOGGLE_OFF)

    def _rebuild_settings(self):
        self._refresh_sound_toggle_button()
        self._clear_layout(self.settings_layout)
        self.buff_slots_label.setText(
            f"Active buffs: {len(self.state['active_buffs'])}/{self.buff_slots_total} slots used"
        )
        caught = self.state["caught_fish"]
        toggleable = [f for f in RARE_FISH if f["name"] in caught and f["effect"]["type"] != "buff_slot"]
        if not toggleable:
            self.settings_layout.addWidget(QLabel("Catch some rare fish to unlock buffs here."))
        for fish in toggleable:
            row = QHBoxLayout()
            label = QLabel(f'<span style="color:{TIER_COLOR[fish["tier"]]}">{fish["name"]}</span> - {_effect_description(fish["effect"])}')
            label.setWordWrap(True)
            row.addWidget(label, 1)
            is_active = fish["name"] in self.state["active_buffs"]
            toggle = QPushButton("ON" if is_active else "OFF")
            toggle.setCheckable(True)
            toggle.setChecked(is_active)
            toggle.setStyleSheet(STYLE_TOGGLE_ON if is_active else STYLE_TOGGLE_OFF)
            toggle.clicked.connect(lambda checked=False, name=fish["name"]: self._toggle_buff(name))
            row.addWidget(toggle)
            container = QWidget()
            container.setLayout(row)
            self.settings_layout.addWidget(container)
        self.settings_layout.addStretch()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                child_layout = item.layout()
                if child_layout is not None:
                    self._clear_layout(child_layout)

    def _log(self, text):
        if hasattr(self, "catch_log"):
            self.catch_log.append(text)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _save_current(self):
        if self.state is not None and self.current_slot is not None:
            save_slot(self.current_slot, self.state)

    def _autosave(self):
        self._save_current()

    def save_now(self):
        """Called by the main window before it closes, so an in-progress
        run is never lost - see webagent_gui.py's closeEvent."""
        self._save_current()
