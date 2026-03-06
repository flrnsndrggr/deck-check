from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Literal


class DeckParseRequest(BaseModel):
    decklist_text: str
    bracket: int = Field(default=3, ge=1, le=5)
    multiplayer: bool = True


class DeckImportUrlRequest(BaseModel):
    url: str


class DeckImportUrlResponse(BaseModel):
    decklist_text: str
    source: str
    warnings: List[str] = Field(default_factory=list)


class CardEntry(BaseModel):
    qty: int
    name: str
    section: str = "deck"
    tags: List[str] = Field(default_factory=list)
    confidence: Dict[str, float] = Field(default_factory=dict)
    explanations: Dict[str, str] = Field(default_factory=dict)


class DeckParseResponse(BaseModel):
    commander: Optional[str] = None
    commanders: List[str] = Field(default_factory=list)
    companion: Optional[str] = None
    color_identity: List[str] = Field(default_factory=list)
    color_identity_size: int = 0
    cards: List[CardEntry]
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class TagRequest(BaseModel):
    cards: List[CardEntry]
    commander: Optional[str] = None
    commanders: List[str] = Field(default_factory=list)
    global_tags: bool = True


class TagResponse(BaseModel):
    tagged_lines: List[str]
    cards: List[CardEntry]
    archetype_weights: Dict[str, float] = Field(default_factory=dict)
    type_theme_profile: Dict = Field(default_factory=dict)
    card_display: Dict[str, Dict] = Field(default_factory=dict)
    color_identity: List[str] = Field(default_factory=list)
    color_identity_size: int = 0


class AnalyzeRequest(BaseModel):
    cards: List[CardEntry]
    commander: Optional[str] = None
    commanders: List[str] = Field(default_factory=list)
    bracket: int = Field(default=3, ge=1, le=5)
    template: str = "balanced"
    budget_max_usd: Optional[float] = Field(default=None, ge=0)
    sim_summary: Dict = Field(default_factory=dict)


class ComboIntelRequest(BaseModel):
    cards: List[str] = Field(default_factory=list)
    commander: Optional[str] = None
    commanders: List[str] = Field(default_factory=list)


class RulesWatchoutRequest(BaseModel):
    cards: List[CardEntry]
    commander: Optional[str] = None
    commanders: List[str] = Field(default_factory=list)


class StrictlyBetterRequest(BaseModel):
    cards: List[CardEntry]
    selected_card: str
    commander: Optional[str] = None
    commanders: List[str] = Field(default_factory=list)
    budget_max_usd: Optional[float] = Field(default=None, ge=0)


class StrictlyBetterOption(BaseModel):
    card: str
    reasons: List[str] = Field(default_factory=list)
    price_usd: Optional[float] = None
    role_overlap: List[str] = Field(default_factory=list)
    mana_value: Optional[float] = None
    selected_mana_value: Optional[float] = None
    scryfall_uri: str = ""
    cardmarket_url: str = ""


class StrictlyBetterResponse(BaseModel):
    selected_card: str
    options: List[StrictlyBetterOption] = Field(default_factory=list)


class ComboVariant(BaseModel):
    variant_id: str
    identity: str = ""
    recipe: str = ""
    cards: List[str] = Field(default_factory=list)
    present_cards: List[str] = Field(default_factory=list)
    missing_cards: List[str] = Field(default_factory=list)
    missing_count: int = 0
    card_coverage: float = 0.0
    score: float = 0.0
    status: Literal["complete", "near_miss", "not_close"] = "not_close"
    source_url: str = ""


class ComboIntel(BaseModel):
    source: str = "commanderspellbook"
    fetched_at: Optional[str] = None
    source_hash: str = ""
    combo_support_score: float = 0.0
    matched_variants: List[ComboVariant] = Field(default_factory=list)
    near_miss_variants: List[ComboVariant] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    deck_name: str = ""
    role_breakdown: Dict
    role_targets: Dict = Field(default_factory=dict)
    role_target_model: Dict = Field(default_factory=dict)
    role_cards_map: Dict = Field(default_factory=dict)
    bracket_report: Dict
    consistency_score: float = 0.0
    health_summary: Dict = Field(default_factory=dict)
    intent_summary: Dict = Field(default_factory=dict)
    actionable_actions: List[Dict] = Field(default_factory=list)
    combo_intel: ComboIntel = Field(default_factory=ComboIntel)
    graph_payloads: Dict = Field(default_factory=dict)
    graph_explanations: Dict[str, str] = Field(default_factory=dict)
    graph_deck_blurbs: Dict[str, str] = Field(default_factory=dict)
    rules_watchouts: List[Dict] = Field(default_factory=list)
    rules_interaction_notes: List[str] = Field(default_factory=list)
    systems_metrics: Dict = Field(default_factory=dict)
    tag_diagnostics: Dict = Field(default_factory=dict)
    color_profile: Dict = Field(default_factory=dict)
    manabase_analysis: Dict = Field(default_factory=dict)
    importance: List[Dict]
    cuts: List[Dict]
    adds: List[Dict]
    swaps: List[Dict]
    missing_roles: List[Dict]
    compliant_alternatives: List[Dict] = Field(default_factory=list)


class GuideRequest(BaseModel):
    analyze: AnalyzeResponse
    sim_summary: Dict


class GuideResponse(BaseModel):
    optimization_guide_md: str
    play_guide_md: str
    rule0_brief_md: str


class SimRunRequest(BaseModel):
    cards: List[CardEntry]
    commander: Optional[str] = None
    commanders: List[str] = Field(default_factory=list)
    runs: int = Field(default=1000, ge=10, le=100000)
    turn_limit: int = Field(default=8, ge=3, le=20)
    policy: str = "auto"
    bracket: int = Field(default=3, ge=1, le=5)
    multiplayer: bool = True
    threat_model: bool = False
    primary_wincons: List[str] = Field(default_factory=list)
    combo_variants: List[Dict] = Field(default_factory=list)
    combo_source_live: bool = False
    sim_backend: Literal["vectorized", "python_fallback"] = "vectorized"
    batch_size: int = Field(default=512, ge=64, le=4096)
    seed: int = 42


class SimRunResponse(BaseModel):
    job_id: str


class SimJobResponse(BaseModel):
    job_id: str
    status: str
    result: Dict = Field(default_factory=dict)


class RulesSearchResponse(BaseModel):
    hits: List[Dict]
