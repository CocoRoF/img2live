"""Names and groups of the layer tags, as the studio shows them."""
from __future__ import annotations

LABELS = {
    "front hair": "앞머리", "back hair": "뒷머리", "face": "얼굴", "eyewhite": "눈 흰자", "irides": "홍채",
    "eyelash": "속눈썹", "eyebrow": "눈썹", "nose": "코", "mouth": "입", "ears": "귀", "earwear": "귀걸이",
    "eyewear": "안경", "headwear": "머리 장식", "neck": "목", "neckwear": "목걸이·목 장식", "topwear": "상의",
    "handwear": "팔·손", "bottomwear": "하의", "legwear": "다리", "footwear": "신발", "tail": "꼬리",
    "wings": "날개", "objects": "소품",
}
GROUPS = {
    "hair": ["front hair", "back hair"],
    "face": ["face", "eyewhite", "irides", "eyelash", "eyebrow", "nose", "mouth", "ears", "earwear", "eyewear", "headwear"],
    "body": ["neck", "neckwear", "topwear", "handwear", "bottomwear", "legwear", "footwear"],
    "other": ["tail", "wings", "objects"],
}
GROUP_LABELS = {"hair": "머리카락", "face": "얼굴", "body": "몸", "other": "기타"}
TAG_GROUP = {t: g for g, ts in GROUPS.items() for t in ts}
# the layers the model draws on the enlarged head square (their edit grid is the head grid)
HEAD_TAGS = GROUPS["face"]
