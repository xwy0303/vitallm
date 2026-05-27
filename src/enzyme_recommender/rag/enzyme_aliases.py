from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence


@dataclass(frozen=True)
class EnzymeAlias:
    key: str
    canonical: str
    aliases: tuple[str, ...]
    pattern: re.Pattern[str]


ENZYME_ALIASES: tuple[EnzymeAlias, ...] = (
    EnzymeAlias(
        key="bcl",
        canonical="Burkholderia cepacia lipase",
        aliases=(
            "BCL",
            "B. cepacia lipase",
            "Burkholderia cepacia lipase",
            "洋葱伯克霍尔德菌脂肪酶",
            "伯克霍尔德菌脂肪酶",
            "伯克霍尔德脂肪酶",
        ),
        pattern=re.compile(
            r"伯克霍尔德(?:菌)?脂肪酶|伯克霍尔德|Burkholderia(?:\s+cepacia)?\s+lipase|\bBCL\b",
            re.I,
        ),
    ),
    EnzymeAlias(
        key="pfl",
        canonical="Pseudomonas lipase",
        aliases=(
            "Pseudomonas fluorescens lipase",
            "PFL",
            "Pseudomonas lipase",
            "假单胞菌脂肪酶",
            "假单胞菌",
        ),
        pattern=re.compile(
            r"假单胞菌脂肪酶|假单胞菌|Pseudomonas(?:\s+\w+)?\s+lipase|\bPFL\b",
            re.I,
        ),
    ),
    EnzymeAlias(
        key="calb",
        canonical="Candida antarctica lipase B",
        aliases=(
            "CALB",
            "CAL-B",
            "Candida antarctica lipase B",
            "南极假丝酵母脂肪酶B",
            "南极假丝酵母脂肪酶 B",
            "南极假丝酵母脂肪酶",
        ),
        pattern=re.compile(
            r"南极假丝酵母脂肪酶\s*B?|南极假丝酵母|Candida\s+antarctica\s+lipase\s+B|\bCAL-?B\b",
            re.I,
        ),
    ),
    EnzymeAlias(
        key="crl",
        canonical="Candida rugosa lipase",
        aliases=(
            "CRL",
            "Candida rugosa lipase",
            "皱褶假丝酵母脂肪酶",
            "皱褶假丝酵母",
        ),
        pattern=re.compile(r"皱褶假丝酵母脂肪酶|皱褶假丝酵母|Candida\s+rugosa\s+lipase|\bCRL\b", re.I),
    ),
    EnzymeAlias(
        key="ppl",
        canonical="porcine pancreatic lipase",
        aliases=("PPL", "porcine pancreatic lipase", "猪胰脂肪酶", "猪胰腺脂肪酶"),
        pattern=re.compile(r"猪胰(?:腺)?脂肪酶|porcine\s+pancreatic\s+lipase|\bPPL\b", re.I),
    ),
    EnzymeAlias(
        key="rml",
        canonical="Rhizomucor miehei lipase",
        aliases=("RML", "Rhizomucor miehei lipase", "米根霉脂肪酶", "米黑根毛霉脂肪酶"),
        pattern=re.compile(r"米根霉脂肪酶|米黑根毛霉脂肪酶|Rhizomucor\s+miehei\s+lipase|\bRML\b", re.I),
    ),
    EnzymeAlias(
        key="tll",
        canonical="Thermomyces lanuginosus lipase",
        aliases=(
            "TLL",
            "Thermomyces lanuginosus lipase",
            "疏棉状嗜热丝孢菌脂肪酶",
            "嗜热真菌脂肪酶",
        ),
        pattern=re.compile(
            r"疏棉状嗜热丝孢菌脂肪酶|嗜热真菌脂肪酶|Thermomyces\s+lanuginosus\s+lipase|\bTLL\b",
            re.I,
        ),
    ),
)


def matched_enzyme_aliases(text: str) -> List[EnzymeAlias]:
    value = text or ""
    matches: List[EnzymeAlias] = []
    for item in ENZYME_ALIASES:
        if item.pattern.search(value):
            matches.append(item)
    return matches


def matched_enzyme_alias_keys(text: str) -> set[str]:
    return {item.key for item in matched_enzyme_aliases(text)}


def matched_enzyme_alias_terms(text: str) -> List[str]:
    terms: List[str] = []
    seen: set[str] = set()
    for item in matched_enzyme_aliases(text):
        for term in (item.canonical, *item.aliases):
            normalized = canonical_alias_term_key(term)
            if not term or normalized in seen:
                continue
            terms.append(term)
            seen.add(normalized)
    return terms


def expand_query_for_retrieval(text: str) -> str:
    value = (text or "").strip()
    alias_terms = terms_not_already_present(value, matched_enzyme_alias_terms(value))
    if not alias_terms:
        return value
    if not value:
        return " ".join(alias_terms)
    return " ".join([value, *alias_terms]).strip()


def terms_not_already_present(text: str, terms: Sequence[str]) -> List[str]:
    lowered = text.lower()
    output: List[str] = []
    seen: set[str] = set()
    for term in terms:
        key = canonical_alias_term_key(term)
        if not term or key in seen:
            continue
        if term.lower() in lowered:
            seen.add(key)
            continue
        output.append(term)
        seen.add(key)
    return output


def canonical_alias_term_key(term: str) -> str:
    return re.sub(r"\s+", "", (term or "").casefold())
