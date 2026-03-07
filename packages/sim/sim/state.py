from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Literal

from sim.config import MAX_COMMANDERS

Phase = Literal[
    "untap",
    "upkeep",
    "draw",
    "precombat_main",
    "cast",
    "etb",
    "declare_attackers",
    "attack",
    "combat_damage",
    "death",
    "end_step",
]


@dataclass(frozen=True)
class TokenSig:
    power: float
    toughness: float
    evasion_score: float = 0.0
    has_haste: bool = False
    infect: bool = False
    toxic: float = 0.0


@dataclass
class ManaState:
    floating: int = 0


@dataclass
class PermanentState:
    permanent_id: int
    card: Any
    card_exec: Any
    tapped: bool = False
    summoning_sick: bool = False
    used_this_turn: bool = False
    counters: Dict[str, int] = field(default_factory=dict)


@dataclass
class TriggerInstance:
    window: Phase
    source_id: int
    source_name: str
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0


@dataclass
class GameState:
    turn: int = 0
    phase: Phase = "untap"
    self_life: float = 40.0
    hand: list[Any] = field(default_factory=list)
    library: list[Any] = field(default_factory=list)
    graveyard: list[Any] = field(default_factory=list)
    exile: list[Any] = field(default_factory=list)
    battlefield: list[PermanentState] = field(default_factory=list)
    commander_zone: list[Any | None] = field(default_factory=lambda: [None for _ in range(MAX_COMMANDERS)])
    commander_tax: list[int] = field(default_factory=lambda: [0 for _ in range(MAX_COMMANDERS)])
    commander_casts: list[int] = field(default_factory=lambda: [0 for _ in range(MAX_COMMANDERS)])
    opp_life: list[float] = field(default_factory=lambda: [40.0, 40.0, 40.0])
    opp_poison: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    opp_library: list[int] = field(default_factory=lambda: [99, 99, 99])
    opp_cmdr_dmg: list[list[float]] = field(
        default_factory=lambda: [[0.0 for _ in range(3)] for _ in range(MAX_COMMANDERS)]
    )
    mana_state: ManaState = field(default_factory=ManaState)
    extra_land_plays: int = 0
    lands_played_this_turn: int = 0
    extra_combats: int = 0
    token_buckets: dict[TokenSig, int] = field(default_factory=dict)
    permanent_counters: dict[int, Dict[str, int]] = field(default_factory=dict)
    pending_triggers: Deque[TriggerInstance] = field(default_factory=deque)
    active_engines: set[str] = field(default_factory=set)
    active_locks: set[str] = field(default_factory=set)
    support_confidence_penalty: float = 0.0
    used_this_turn: set[int] = field(default_factory=set)
    next_permanent_id: int = 1
    burn_total: float = 0.0
    mill_total: float = 0.0
    combat_damage_total: float = 0.0

    @property
    def library_pos(self) -> int:
        return len(self.library)
