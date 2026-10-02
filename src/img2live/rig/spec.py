"""RigSpec: the user's free-text prompt turned into structured rig settings.

This is a deterministic keyword parser (Korean + English) — no LLM call.  What it understands is deliberately
small and every interpretation is returned so the UI can show the user what was understood.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import List


@dataclass
class RigSpec:
    motion_intensity: float = 1.0   # scales idle amplitudes
    head_range: float = 1.0         # scales head yaw/pitch/roll amplitudes
    hair_strength: float = 1.0      # hair / tail physics gain
    blink: bool = True
    idle: bool = True
    notes: List[str] = field(default_factory=list)   # human-readable interpretations
    raw_prompt: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_RULES = [
    # (regex, setter, note)
    (r"calm|gentle|soft|quiet|subtle|slow|차분|얌전|은은|부드럽|조용|천천히", lambda s: setattr(s, "motion_intensity", min(s.motion_intensity, 0.6)), "calm motion (idle x0.6)"),
    (r"energetic|lively|playful|active|bouncy|활발|역동|발랄|통통|신나", lambda s: setattr(s, "motion_intensity", max(s.motion_intensity, 1.5)), "energetic motion (idle x1.5)"),
    (r"exaggerat|dramatic|big movement|large movement|과장|큰 동작|크게 ?움직|동작.*크게", lambda s: (setattr(s, "motion_intensity", max(s.motion_intensity, 1.4)), setattr(s, "head_range", max(s.head_range, 1.2))), "exaggerated motion (idle x1.4, head x1.2)"),
    (r"minimal|tiny|small movement|조금만|작게|미세", lambda s: (setattr(s, "motion_intensity", min(s.motion_intensity, 0.5)), setattr(s, "head_range", min(s.head_range, 0.8))), "minimal motion (idle x0.5, head x0.8)"),
    (r"windy|flowy|fluffy|hair.*(more|stronger|strong|big|large|wild|wind)|바람|머리카락.*(많이|크게|세게|펄럭|풍성)|펄럭|하늘하늘", lambda s: setattr(s, "hair_strength", max(s.hair_strength, 1.7)), "stronger hair/tail sway (x1.7)"),
    (r"hair.*(little|slight|subtle|gentle|less)|(little|slight|subtle|gentle|less).*hair|머리카락.*(조금|살짝|약하게|적게|은은)", lambda s: setattr(s, "hair_strength", 0.5), "weaker hair/tail sway (x0.5)"),
    (r"stiff|rigid|no hair|hair.*(still|fixed|static)|머리카락.*(고정|가만|움직이지|흔들리지)", lambda s: setattr(s, "hair_strength", 0.0), "hair/tail physics off"),
    (r"no blink|don'?t blink|without blink|눈.*깜빡.*(없|말|안)|깜빡이지", lambda s: setattr(s, "blink", False), "auto-blink off"),
    (r"no idle|static|still pose|freeze|움직이지 ?마|정지|가만히", lambda s: setattr(s, "idle", False), "idle motion off"),
]


def parse_prompt(prompt: str) -> RigSpec:
    spec = RigSpec(raw_prompt=(prompt or "").strip()[:500])
    text = spec.raw_prompt.lower()
    for pattern, apply, note in _RULES:
        if re.search(pattern, text):
            apply(spec)
            spec.notes.append(note)
    if not spec.raw_prompt:
        spec.notes.append("no prompt: default settings")
    elif not spec.notes:
        spec.notes.append("no recognised keywords: default settings (the prompt cannot change which parts are separated)")
    return spec
