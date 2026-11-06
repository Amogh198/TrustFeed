"""Split a post into individual claims and describe each one.

This is not fact checking. It decides what could be checked and finds the dates,
numbers, names and places in it, so later steps can search and compare. Every
claim keeps the verdict ``unverified`` here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from backend.text.entities import (
    MONTH_WORDS,
    WEEKDAY_WORDS,
    DateMention,
    NumberMention,
    find_dates,
    find_numbers,
)
from backend.text.ner import ModelEntity

# Clauses are only worth separating in a sentence long enough to hold two claims.
_MIN_WORDS_TO_SPLIT = 10

_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+|\n+")
_LIST_MARKER = re.compile(r"^(?:[-•*▪]\s+|\d{1,2}[.)]\s+)")
# These end in a full stop but do not end a sentence.
_ABBREVIATIONS = {
    "dr.", "mr.", "mrs.", "ms.", "prof.", "st.", "sr.", "jr.", "no.", "vs.", "e.g.", "i.e.", "rs.", "gov.", "sen.",
    "rep.", "gen.", "col.", "capt.", "lt.", "hon.", "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.", "sep.",
    "sept.", "oct.", "nov.", "dec.", "u.s.", "u.k.", "approx.", "dept.", "govt.",
}
_INITIAL = re.compile(r"(?:^|\s)[A-Z]\.$")
_CLAUSE_BREAK = re.compile(r";\s+|,?\s+(?:and|but|while|whereas|yet)\s+", re.IGNORECASE)

_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")
_AUXILIARIES = {
    "am", "is", "are", "was", "were", "be", "been", "has", "have", "had", "will", "would", "can", "could", "may",
    "might", "must", "shall", "should", "do", "does", "did",
}
_IRREGULAR_VERBS = {
    "ate", "became", "began", "bought", "broke", "built", "came", "caught", "cost", "cut", "drew", "fell", "fled",
    "found", "gave", "got", "grew", "had", "held", "hit", "kept", "knew", "led", "left", "lost", "made", "met",
    "paid", "put", "ran", "rose", "said", "sat", "saw", "says", "sent", "shot", "sold", "spent", "stood", "struck",
    "swore", "took", "told", "went", "won", "wrote",
}
_COMMON_VERB_STEMS = {
    "announc", "approv", "arrest", "attack", "ban", "clos", "confirm", "deni", "di", "explod", "injur", "kill",
    "lose", "open", "reject", "resign", "win",
}
STOPWORDS = _AUXILIARIES | {
    "a", "about", "after", "again", "all", "almost", "also", "an", "and", "any", "around", "as", "at", "because",
    "before", "being", "both", "but", "by", "during", "each", "for", "from", "he", "her", "here", "his", "how", "i",
    "if", "in", "into", "it", "its", "just", "least", "many", "me", "more", "most", "my", "near", "nearly", "of",
    "on", "only", "or", "our", "out", "over", "per", "she", "so", "some", "such", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "those", "to", "under", "until", "up", "us", "very", "we",
    "what", "when", "where", "which", "while", "who", "whom", "why", "with", "you", "your",
}
NEGATORS = {"not", "no", "never", "none", "neither", "nor", "without"}

# An instruction, not a statement. The word after the verb matters: "Share this"
# asks for something, while "Share prices fell" reports something.
_IMPERATIVE = re.compile(
    r"^(?:please\s+|do not\s+|don't\s+)?"
    r"(?:share|forward|retweet|repost|click|sign|join|subscribe|follow|send|act|pay|call|contact|wake|beware|claim|"
    r"register|buy|download|visit|read|watch|spread|tell|stop|avoid|vote|boycott|protect|check|verify)\b"
    r"\s*(?:this|it|now|these|those|your|the|to|with|our|us|immediately|here|today|before|out|on|up|a|an|for|$|[.!])",
    re.IGNORECASE,
)
_OPINION_START = re.compile(
    r"^(?:i|we)\s+(?:think|believe|feel|reckon|guess)\b|^in my (?:opinion|view)\b|^imo\b|^personally\b|^it seems to me\b",
    re.IGNORECASE,
)
_OPINION_INSIDE = re.compile(
    r"\b(?:should|ought to|must be (?:stopped|banned|removed))\b|"
    r"\b(?:is|are|was|were)\s+(?:a\s+|an\s+|the\s+|so\s+|very\s+|absolutely\s+)?"
    r"(?:disgrace|disgraceful|shameful|terrible|awful|wonderful|amazing|best|worst|beautiful|disgusting|ridiculous)\b",
    re.IGNORECASE,
)
_ATTRIBUTION = re.compile(
    # A leading "BREAKING:" label is not part of who is speaking.
    r"^(?:[A-Z][A-Z ]{2,20}:\s*)?(?:"
    r"according to (?P<after>[^,]{2,60}),\s*"
    r"|(?P<before>[^,]{2,40}?)\s+"
    r"(?:said|says|say|reported|reports|claimed|claims|stated|announced|confirmed|told\s+\w+)\s+(?:that\s+)?"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AnalyzedClaim:
    id: str
    text: str
    kind: str
    checkable: bool
    dates: tuple[DateMention, ...] = ()
    numbers: tuple[NumberMention, ...] = ()
    named: tuple[ModelEntity, ...] = ()

    @property
    def places(self) -> frozenset[str]:
        return frozenset(item.text.casefold() for item in self.named if item.type == "place")

    @property
    def attribution(self) -> str | None:
        match = _ATTRIBUTION.match(self.text)
        if not match:
            return None
        return (match.group("after") or match.group("before")).strip().casefold()


def _sentences(text: str) -> list[str]:
    pieces: list[str] = []
    for piece in _SENTENCE_END.split(text):
        piece = piece.strip()
        if not piece:
            continue
        previous = pieces[-1] if pieces else ""
        last_word = previous.rsplit(None, 1)[-1].casefold() if previous else ""
        # A lowercase start after a line with no closing mark is a wrapped line, not a new sentence.
        wrapped_line = previous and previous[-1] not in ".!?।:" and piece[0].islower()
        if previous and (
            wrapped_line
            or last_word in _ABBREVIATIONS
            or _INITIAL.search(previous)
            or re.fullmatch(r"\d{1,2}\.", previous)
        ):
            pieces[-1] = f"{previous} {piece}"
        else:
            pieces.append(piece)
    return [_LIST_MARKER.sub("", piece).strip() for piece in pieces]


def is_verb_like(word: str) -> bool:
    word = word.casefold()
    return (
        word in _AUXILIARIES
        or word in _IRREGULAR_VERBS
        or (len(word) > 3 and word.endswith("ed"))
        or stem(word) in _COMMON_VERB_STEMS
    )


def _has_verb(words: list[str]) -> bool:
    return any(is_verb_like(word) for word in words)


def _can_stand_alone(clause: str) -> bool:
    """A clause with its own subject and verb is a claim. "and left the city" is not."""
    words = _WORD.findall(clause)
    # Figures count towards the length, so "47 people died" stands alone.
    if len(clause.split()) < 3 or not _has_verb(words):
        return False
    return not (is_verb_like(words[0]) or words[0].casefold() in {"to", "that", "which", "who", "whom", "whose"})


def _clauses(sentence: str) -> list[str]:
    if len(sentence.split()) < _MIN_WORDS_TO_SPLIT:
        return [sentence]
    parts = [part.strip(" ,") for part in _CLAUSE_BREAK.split(sentence) if part.strip(" ,")]
    if len(parts) < 2 or not all(_can_stand_alone(part) for part in parts):
        return [sentence]
    return parts


def split_claims(text: str) -> list[str]:
    """Return each separate statement once, in order. An unpunctuated post stays whole."""
    seen: set[str] = set()
    claims: list[str] = []
    for sentence in _sentences(text):
        for clause in _clauses(sentence):
            key = " ".join(clause.casefold().split())
            if key and key not in seen:
                seen.add(key)
                claims.append(clause)
    return claims


def stem(word: str) -> str:
    """A light stemmer: enough to match "resigned" with "resign", and no more."""
    word = word.casefold().replace("'s", "")
    if len(word) > 3 and word.endswith("ies"):
        word = word[:-3] + "i"
    elif len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 3 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    if len(word) > 2 and word.endswith("e"):
        word = word[:-1]
    elif len(word) > 2 and word.endswith("y"):
        word = word[:-1] + "i"
    return word


def content_tokens(claim: AnalyzedClaim) -> frozenset[str]:
    """The words that say what a claim is about, without its figures, dates, places or source."""
    text = claim.text
    match = _ATTRIBUTION.match(text)
    start = match.end() if match else 0
    spans = [(item.start, item.end) for item in (*claim.dates, *claim.numbers, *claim.named) if item.end > start]
    pieces: list[str] = []
    position = start
    for span_start, span_end in sorted(spans):
        pieces.append(text[position : max(position, span_start)])
        position = max(position, span_end)
    pieces.append(text[position:])
    words = _WORD.findall(" ".join(pieces).replace("n't", " not"))
    skipped = STOPWORDS | NEGATORS | MONTH_WORDS | WEEKDAY_WORDS
    return frozenset(stem(word) for word in words if word.casefold() not in skipped)


def is_negated(claim: AnalyzedClaim) -> bool:
    text = claim.text.casefold().replace("n't", " not")
    return any(word in NEGATORS for word in _WORD.findall(text))


def _classify(text: str, has_figures: bool) -> tuple[str, bool]:
    stripped = text.strip()
    words = _WORD.findall(stripped)
    if stripped.endswith("?"):
        return "question", False
    if _IMPERATIVE.match(stripped):
        return "call_to_action", False
    # "I think 50 people died" is hedged but still names something that can be checked.
    if not has_figures and (_OPINION_START.match(stripped) or _OPINION_INSIDE.search(stripped)):
        return "opinion", False
    if not has_figures and len(words) < 4 and not _has_verb(words):
        return "fragment", False
    return "factual", True


def describe_claim(number: int, text: str, named: Sequence[ModelEntity] = ()) -> AnalyzedClaim:
    dates = find_dates(text)
    numbers = find_numbers(text, dates)
    kind, checkable = _classify(text, bool(dates or numbers))
    return AnalyzedClaim(f"claim-{number}", text, kind, checkable, tuple(dates), tuple(numbers), tuple(named))
