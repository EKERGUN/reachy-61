"""Fan moments: what can happen in a match, and how a fan reacts to each.

Every source of events (the phone remote today; the room listener and the score feed later)
produces one of these moment keys. The reaction is data, not code: a list of moves from Pollen's
emotion library (one is picked at random), a mood change, a spoken line, and whether to chant.
"""

from __future__ import annotations

from dataclasses import dataclass

EMOTIONS_LIBRARY = "pollen-robotics/reachy-mini-emotions-library"


@dataclass(frozen=True)
class Reaction:
    moves: tuple[str, ...]        # emotion library moves (each has its own sound)
    mood: float                   # added to the mood (-1 .. 1)
    priority: int                 # higher interrupts lower (a goal cuts off a sulk)
    speak: bool = True            # say a line from the team's phrases.yaml
    chant: bool = False           # then play one of the user's chant recordings


REACTIONS: dict[str, Reaction] = {
    "goal_us":       Reaction(("enthusiastic1", "enthusiastic2", "success1", "dance1"), +0.35, 9, chant=True),
    "goal_them":     Reaction(("sad1", "downcast1", "no_sad1"), -0.3, 8),
    "chance_us":     Reaction(("surprised1", "amazed1"), +0.03, 5),
    "chance_them":   Reaction(("scared1", "fear1", "relief1"), -0.03, 5),
    "penalty_us":    Reaction(("anxiety1", "impatient1"), +0.05, 7),
    "penalty_them":  Reaction(("anxiety1", "scared1"), -0.05, 7),
    "red_card_us":   Reaction(("furious1", "reprimand1"), -0.1, 6),
    "red_card_them": Reaction(("proud1", "yes1"), +0.05, 6),
    "referee":       Reaction(("furious1", "reprimand2", "irritated1", "displeased1"), -0.05, 6),
    "var":           Reaction(("anxiety1", "uncertain1"), 0.0, 6),
    "tension":       Reaction(("impatient2", "anxiety1"), 0.0, 3),
    "groan":         Reaction(("downcast1", "no_sad1", "frustrated1"), -0.05, 5),
    "var_cancel_us":   Reaction(("frustrated1", "sad2", "rage1"), -0.3, 8),
    "var_cancel_them": Reaction(("relief2", "success1", "proud3"), +0.25, 8),
    "win":           Reaction(("proud1", "dance2", "success2"), +0.6, 9, chant=True),
    "draw":          Reaction(("thoughtful1", "indifferent1"), 0.0, 8),
    "loss":          Reaction(("resigned1", "sad2", "exhausted1"), -0.6, 8),
    "chant":         Reaction(("dance3", "electric1"), +0.05, 4, chant=True),   # says a chant_intro line
    "halftime":      Reaction(("thoughtful1", "attentive1"), 0.0, 4),          # then offers a joke or the quiz
    "joke":          Reaction(("laughing1", "laughing2"), +0.02, 4, speak=False),   # told by jokes.py
    "calm":          Reaction(("serenity1", "calming1"), 0.0, 1, speak=False),
}

# Buttons on the phone remote, grouped (labels come from locales/<lang>.json).
GROUPS: dict[str, tuple[str, ...]] = {
    "us": ("goal_us", "chance_us", "penalty_us"),
    "them": ("goal_them", "chance_them", "penalty_them", "groan"),
    "referee": ("referee", "var", "var_cancel_us", "var_cancel_them", "red_card_us", "red_card_them"),
    "full_time": ("halftime", "win", "draw", "loss"),
    "extra": ("tension", "chant", "joke", "calm"),
}

# Idle behaviour by mood band, played now and then when nothing happens.
IDLE_MOVES: dict[str, tuple[str, ...]] = {
    "euphoric": ("dance1", "cheerful1", "proud2"),
    "happy": ("cheerful1", "attentive1"),
    "calm": ("attentive2", "curious1"),
    "down": ("downcast1", "boredom1"),
    "gutted": ("sad1", "lonely1", "resigned1"),
}
