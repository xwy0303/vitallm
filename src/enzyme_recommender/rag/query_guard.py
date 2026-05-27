from __future__ import annotations

import re
from typing import List


DOCUMENT_REF_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]\d{1,3}(?:\.pdf)?(?![A-Za-z0-9])", re.I)
PROMPT_INJECTION_RE = re.compile(
    r"(忽略\s*(?:evidence|证据|上下文)|编造|不要引用|不需要引用|直接告诉我最佳答案|"
    r"ignore\s+(?:the\s+)?(?:evidence|context|instructions)|make\s+up|fabricate)",
    re.I,
)
SOCIAL_OR_META_RE = re.compile(
    r"^(?:你好|您好|hello|hi|hey|不知道|你是什么|你是谁|我爱你|谢谢|thanks)[。！!?.\s]*$|"
    r"(陪我聊|心情不好|聊天|你是什么东西)",
    re.I,
)
CHINESE_DOMAIN_RE = re.compile(
    r"(固定化|固化|固定化剂|固化剂|载体|材料|配方|条件|脂肪酶|酶|活性|产率|回收|"
    r"重复使用|复用|循环|稳定|生物柴油|转酯|大豆油|乙醇|温度|时间|分钟|戊二醛|"
    r"吸附|包埋|交联|仿生矿化|温和|筛选|优化|最优|最佳)",
    re.I,
)
ENGLISH_DOMAIN_RE = re.compile(
    r"\b(?:lipase|enzyme|immobilization|immobilized|carrier|support|formulation|condition|"
    r"activity|yield|recovery|reuse|reusability|stability|biodiesel|transesterification|"
    r"adsorption|encapsulation|crosslinking|cross-linked|biomineralization|glutaraldehyde|"
    r"ph|temperature|loading|mof|zif-?8|uio-?66|magnetic|fe3o4|bcl|calb|cal-b|ppl|crl|tll)\b",
    re.I,
)
RANDOM_TOKEN_RE = re.compile(r"^[A-Za-z]{1,4}$")


QUERY_EXPANSIONS = [
    (re.compile(r"伯克霍尔德|Burkholderia", re.I), "Burkholderia cepacia lipase BCL"),
    (re.compile(r"假单胞菌|Pseudomonas", re.I), "Pseudomonas lipase"),
    (re.compile(r"脂肪酶"), "lipase enzyme"),
    (re.compile(r"固定化剂|固化剂|载体|支撑材料|材料"), "immobilization carrier support material"),
    (re.compile(r"固定化|固化"), "immobilization immobilized"),
    (re.compile(r"固定化条件|固化条件|配方|条件"), "formulation conditions enzyme loading pH temperature time"),
    (re.compile(r"优化|筛选"), "optimization screening optimized"),
    (re.compile(r"大豆油"), "soybean oil"),
    (re.compile(r"乙醇"), "ethanol"),
    (re.compile(r"生物柴油"), "biodiesel transesterification"),
    (re.compile(r"重复使用|复用|重复用|循环"), "reuse reusability cycles"),
    (re.compile(r"稳定|更稳"), "stability residual activity"),
    (re.compile(r"活性|回收"), "activity recovery"),
    (re.compile(r"产率|转化率"), "yield conversion"),
    (re.compile(r"温度|越高越好"), "temperature optimum denaturation not always higher"),
    (re.compile(r"时间|分钟"), "time min"),
    (re.compile(r"温和"), "mild adsorption biomineralization"),
    (re.compile(r"戊二醛"), "glutaraldehyde covalent crosslinking"),
    (re.compile(r"磁性"), "magnetic Fe3O4 MNP"),
    (re.compile(r"ZIF8", re.I), "ZIF-8 ZIF8"),
    (re.compile(r"Zr[\-\s]?MOF", re.I), "Zr-MOF UiO-66"),
]


def should_return_no_evidence(query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return True
    if PROMPT_INJECTION_RE.search(text):
        return True
    if SOCIAL_OR_META_RE.search(text) and not has_evidence_domain_signal(text):
        return True
    if looks_like_random_query(text):
        return True
    if not has_evidence_domain_signal(text):
        return True
    return False


def has_evidence_domain_signal(query: str) -> bool:
    text = query or ""
    return bool(
        DOCUMENT_REF_RE.search(text)
        or CHINESE_DOMAIN_RE.search(text)
        or ENGLISH_DOMAIN_RE.search(text)
        or re.search(r"\b(?:ZIF8|MOF|BCL)\b", text, re.I)
    )


def looks_like_random_query(query: str) -> bool:
    tokens = re.findall(r"[A-Za-z]+", query or "")
    if not tokens:
        return False
    if len(tokens) <= 3 and all(RANDOM_TOKEN_RE.fullmatch(token) for token in tokens):
        return not has_evidence_domain_signal(query)
    return False


def expand_query_for_retrieval(query: str) -> str:
    text = query or ""
    additions: List[str] = []
    for pattern, expansion in QUERY_EXPANSIONS:
        if pattern.search(text):
            additions.append(expansion)
    if not additions:
        return text
    deduped = []
    seen = set()
    for addition in additions:
        if addition not in seen:
            deduped.append(addition)
            seen.add(addition)
    return " ".join([text, *deduped]).strip()
