from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Literal

MAX_COMMANDERS = 2

ResolvedPolicyName = Literal["casual", "optimized", "cedh", "commander-centric", "hold commander"]


def normalize_commanders(commander: str | Iterable[str] | None) -> tuple[str, ...]:
    if commander is None:
        return ()
    if isinstance(commander, str):
        name = commander.strip()
        return (name,) if name else ()
    out: list[str] = []
    seen: set[str] = set()
    for raw in commander:
        name = str(raw or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return tuple(out)


def build_commander_slots(commander: str | Iterable[str] | None, max_commanders: int = MAX_COMMANDERS) -> tuple[str | None, ...]:
    names = list(normalize_commanders(commander))[:max_commanders]
    while len(names) < max_commanders:
        names.append(None)
    return tuple(names)


def normalize_selected_wincons(primary_wincons: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not primary_wincons:
        return (
            "Combo",
            "Alt Win",
            "Poison",
            "Commander Damage",
            "Drain/Burn",
            "Mill",
            "Combat",
        )
    return tuple(str(item) for item in primary_wincons if str(item or "").strip())


def resolve_policy_name(requested_policy: str, bracket: int) -> ResolvedPolicyName:
    requested = str(requested_policy or "auto").strip()
    if requested == "auto":
        if bracket >= 5:
            return "cedh"
        if bracket <= 2:
            return "casual"
        return "optimized"
    return requested  # type: ignore[return-value]


@dataclass(frozen=True)
class PolicyConfig:
    requested_policy: str
    resolved_policy: str
    bracket: int
    turn_limit: int
    multiplayer: bool
    threat_model: bool
    max_commanders: int = MAX_COMMANDERS

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpponentProfile:
    profile_id: str
    multiplayer: bool
    threat_model: bool
    life_pressure: float
    blocker_density: float
    spot_removal_budget: int
    counter_budget: int
    wipe_budget: int
    table_noise: float
    threat_tolerance: float

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedSimConfig:
    policy: PolicyConfig
    opponent: OpponentProfile
    commander_slots: tuple[str | None, ...]
    selected_wincons: tuple[str, ...]
    color_identity_size: int
    seed: int

    def to_payload(self) -> Dict[str, Any]:
        return {
            "policy": self.policy.to_payload(),
            "opponent": self.opponent.to_payload(),
            "commander_slots": list(self.commander_slots),
            "selected_wincons": list(self.selected_wincons),
            "color_identity_size": self.color_identity_size,
            "seed": self.seed,
        }


def resolve_opponent_profile(
    resolved_policy: str,
    multiplayer: bool,
    threat_model: bool,
) -> OpponentProfile:
    if not multiplayer or not threat_model:
        return OpponentProfile(
            profile_id="goldfish",
            multiplayer=multiplayer,
            threat_model=threat_model,
            life_pressure=0.0,
            blocker_density=0.0,
            spot_removal_budget=0,
            counter_budget=0,
            wipe_budget=0,
            table_noise=0.0,
            threat_tolerance=1.0,
        )

    if resolved_policy == "cedh":
        return OpponentProfile(
            profile_id="high_power_table",
            multiplayer=True,
            threat_model=True,
            life_pressure=0.72,
            blocker_density=0.35,
            spot_removal_budget=2,
            counter_budget=1,
            wipe_budget=0,
            table_noise=0.55,
            threat_tolerance=0.35,
        )
    if resolved_policy == "casual":
        return OpponentProfile(
            profile_id="casual_table",
            multiplayer=True,
            threat_model=True,
            life_pressure=0.35,
            blocker_density=0.5,
            spot_removal_budget=1,
            counter_budget=0,
            wipe_budget=1,
            table_noise=0.65,
            threat_tolerance=0.6,
        )
    return OpponentProfile(
        profile_id="optimized_table",
        multiplayer=True,
        threat_model=True,
        life_pressure=0.55,
        blocker_density=0.45,
        spot_removal_budget=1,
        counter_budget=1,
        wipe_budget=1,
        table_noise=0.6,
        threat_tolerance=0.45,
    )


def resolve_sim_config(
    commander: str | Iterable[str] | None,
    requested_policy: str,
    bracket: int,
    turn_limit: int,
    multiplayer: bool,
    threat_model: bool,
    primary_wincons: list[str] | tuple[str, ...] | None,
    color_identity_size: int,
    seed: int,
    max_commanders: int = MAX_COMMANDERS,
) -> ResolvedSimConfig:
    policy = PolicyConfig(
        requested_policy=str(requested_policy or "auto"),
        resolved_policy=resolve_policy_name(str(requested_policy or "auto"), int(bracket)),
        bracket=int(bracket),
        turn_limit=int(turn_limit),
        multiplayer=bool(multiplayer),
        threat_model=bool(threat_model),
        max_commanders=max_commanders,
    )
    return ResolvedSimConfig(
        policy=policy,
        opponent=resolve_opponent_profile(policy.resolved_policy, bool(multiplayer), bool(threat_model)),
        commander_slots=build_commander_slots(commander, max_commanders=max_commanders),
        selected_wincons=normalize_selected_wincons(primary_wincons),
        color_identity_size=max(0, int(color_identity_size)),
        seed=int(seed),
    )


def coerce_resolved_sim_config(
    value: ResolvedSimConfig | Dict[str, Any] | None,
    *,
    commander: str | Iterable[str] | None,
    requested_policy: str,
    bracket: int,
    turn_limit: int,
    multiplayer: bool,
    threat_model: bool,
    primary_wincons: list[str] | tuple[str, ...] | None,
    color_identity_size: int,
    seed: int,
) -> ResolvedSimConfig:
    if isinstance(value, ResolvedSimConfig):
        return value
    if isinstance(value, dict) and value.get("policy") and value.get("opponent"):
        policy_payload = dict(value["policy"])
        opponent_payload = dict(value["opponent"])
        return ResolvedSimConfig(
            policy=PolicyConfig(**policy_payload),
            opponent=OpponentProfile(**opponent_payload),
            commander_slots=tuple(value.get("commander_slots") or build_commander_slots(commander)),
            selected_wincons=tuple(value.get("selected_wincons") or normalize_selected_wincons(primary_wincons)),
            color_identity_size=int(value.get("color_identity_size", color_identity_size)),
            seed=int(value.get("seed", seed)),
        )
    return resolve_sim_config(
        commander=commander,
        requested_policy=requested_policy,
        bracket=bracket,
        turn_limit=turn_limit,
        multiplayer=multiplayer,
        threat_model=threat_model,
        primary_wincons=primary_wincons,
        color_identity_size=color_identity_size,
        seed=seed,
    )
