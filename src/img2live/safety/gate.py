"""Input safety gate built on the WD tagger v3 (SmilingWolf/wd-vit-tagger-v3, Apache-2.0).

The gate runs BEFORE any GPU time is spent.  It rejects, with a reason the user can read:

* ``nsfw``                 questionable/explicit rating
* ``minor_sensitive``      a minor-looking tag (loli/shota/child/...) together with any suggestive rating
* ``not_illustration``     photographs / 3D renders (also keeps real people out of the pipeline)
* ``multiple_characters``  the decomposition model handles exactly one character
* ``no_character``         nothing character-like found
* ``blocked``              exact-file hash on the operator's blocklist

This is a best-effort filter, not a guarantee: a Danbooru-trained tagger has false negatives and false
positives on out-of-distribution images.  Every decision stores the scores it was based on so thresholds can be
audited and tuned.
"""
from __future__ import annotations

import csv
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

REPO = "SmilingWolf/wd-vit-tagger-v3"
MINOR_TAGS = ("loli", "shota", "child", "female_child", "male_child", "toddler", "baby", "aged_down", "infant")
PHOTO_TAGS = ("realistic", "photorealistic", "photo_(medium)", "3d", "real_life", "photo-referenced")
MULTI_TAGS = ("multiple_girls", "multiple_boys", "multiple_others", "2girls", "3girls", "4girls", "5girls",
              "6+girls", "2boys", "3boys", "4boys", "5boys", "6+boys", "crowd")
NO_CHAR_TAGS = ("no_humans",)
PERSON_TAGS = ("1girl", "1boy", "1other", "solo", "solo_focus")  # at least one must fire for a character image

MESSAGES = {
    "nsfw": "이 이미지는 성적/노골적 콘텐츠로 분류되어 처리할 수 없습니다. (This image was classified as sexual content.)",
    "minor_sensitive": "미성년으로 보이는 캐릭터의 선정적 이미지는 처리하지 않습니다. (Suggestive images of minor-looking characters are not processed.)",
    "not_illustration": "사진·실사·3D 렌더는 지원하지 않습니다. 일러스트(애니풍 캐릭터)를 올려 주세요. (Photos and 3D renders are not supported.)",
    "multiple_characters": "한 명의 캐릭터만 있는 이미지를 올려 주세요. (Please upload an image with a single character.)",
    "no_character": "캐릭터를 찾지 못했습니다. (No character was found.)",
    "blocked": "이 파일은 처리할 수 없습니다. (This file cannot be processed.)",
}


@dataclass
class GateConfig:
    nsfw: float = 0.50
    minor_tag: float = 0.35
    minor_sensitive: float = 0.50
    photo: float = 0.60
    multi: float = 0.60
    no_char: float = 0.70
    person: float = 0.40   # min score of any 1girl/1boy/1other/solo tag


@dataclass
class GateResult:
    allowed: bool
    reason: str = ""
    message: str = ""
    ratings: Dict[str, float] = field(default_factory=dict)
    flagged: Dict[str, float] = field(default_factory=dict)
    top_tags: List[List] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "ratings": self.ratings, "flagged": self.flagged,
                "top_tags": self.top_tags}


class SafetyGate:
    def __init__(self, cache_dir: Path, config: Optional[GateConfig] = None, blocklist: Optional[Path] = None):
        self.cache_dir = Path(cache_dir)
        self.cfg = config or GateConfig()
        self.blocklist = set()
        if blocklist and Path(blocklist).exists():
            self.blocklist = {l.strip().lower() for l in Path(blocklist).read_text().splitlines() if l.strip() and not l.startswith("#")}
        self.session = None
        self.tags: List[str] = []
        self.cats: List[int] = []

    def load(self) -> None:
        if self.session is not None:
            return
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download

        model = hf_hub_download(REPO, "model.onnx", cache_dir=str(self.cache_dir))
        tags = hf_hub_download(REPO, "selected_tags.csv", cache_dir=str(self.cache_dir))
        with open(tags, newline="", encoding="utf8") as f:
            rows = list(csv.DictReader(f))
        self.tags = [r["name"] for r in rows]
        self.cats = [int(r["category"]) for r in rows]
        so = ort.SessionOptions()
        so.intra_op_num_threads = 4
        self.session = ort.InferenceSession(model, sess_options=so, providers=["CPUExecutionProvider"])
        self.size = int(self.session.get_inputs()[0].shape[1])
        log.info("safety gate ready (%d tags, input %d)", len(self.tags), self.size)

    # ------------------------------------------------------------------ inference
    def _prep(self, img: Image.Image) -> np.ndarray:
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        rgb = bg.convert("RGB")
        w, h = rgb.size
        s = max(w, h)
        canvas = Image.new("RGB", (s, s), (255, 255, 255))
        canvas.paste(rgb, ((s - w) // 2, (s - h) // 2))
        canvas = canvas.resize((self.size, self.size), Image.BICUBIC)
        arr = np.asarray(canvas, dtype=np.float32)[:, :, ::-1]  # BGR, 0..255
        return np.ascontiguousarray(arr[None])

    def scores(self, img: Image.Image) -> Dict[str, float]:
        self.load()
        inp = self._prep(img)
        out = self.session.run(None, {self.session.get_inputs()[0].name: inp})[0][0]
        return {t: float(p) for t, p in zip(self.tags, out)}

    def check(self, img: Image.Image, file_sha256: str = "") -> GateResult:
        if file_sha256 and file_sha256.lower() in self.blocklist:
            return GateResult(False, "blocked", MESSAGES["blocked"])
        sc = self.scores(img)
        c = self.cfg
        ratings = {k: round(sc.get(k, 0.0), 3) for k in ("general", "sensitive", "questionable", "explicit")}
        general_tags = [(t, p) for t, p, cat in zip(self.tags, [sc[t] for t in self.tags], self.cats) if cat == 0]
        top = sorted(general_tags, key=lambda x: -x[1])[:12]
        res = GateResult(True, ratings=ratings, top_tags=[[t, round(p, 3)] for t, p in top])

        def hit(names, thr):
            return {n: round(sc[n], 3) for n in names if n in sc and sc[n] >= thr}

        if max(ratings["questionable"], ratings["explicit"]) >= c.nsfw:
            return self._reject(res, "nsfw", {k: ratings[k] for k in ("questionable", "explicit")})
        minor = hit(MINOR_TAGS, c.minor_tag)
        if minor and (ratings["sensitive"] >= c.minor_sensitive or ratings["questionable"] >= 0.25 or ratings["explicit"] >= 0.10):
            return self._reject(res, "minor_sensitive", {**minor, "sensitive": ratings["sensitive"]})
        photo = hit(PHOTO_TAGS, c.photo)
        if photo:
            return self._reject(res, "not_illustration", photo)
        multi = hit(MULTI_TAGS, c.multi)
        if multi:
            return self._reject(res, "multiple_characters", multi)
        nochar = hit(NO_CHAR_TAGS, c.no_char)
        if nochar:
            return self._reject(res, "no_character", nochar)
        person = max((sc.get(t, 0.0) for t in PERSON_TAGS), default=0.0)
        if person < c.person:
            return self._reject(res, "no_character", {"person_score": round(person, 3)})
        return res

    @staticmethod
    def _reject(res: GateResult, reason: str, flagged: Dict[str, float]) -> GateResult:
        res.allowed, res.reason, res.message, res.flagged = False, reason, MESSAGES[reason], flagged
        return res


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
