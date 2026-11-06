"""Find dates and numbers with rules, keeping the context that later checks need.

These two types do not need a model, so they still work when the NER model is
missing. Names and places come only from the model (see ``ner.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("January", "Jan"), ("February", "Feb"), ("March", "Mar"), ("April", "Apr"), ("May",), ("June", "Jun"),
            ("July", "Jul"), ("August", "Aug"), ("September", "Sep", "Sept"), ("October", "Oct"),
            ("November", "Nov"), ("December", "Dec"),
        ),
        start=1,
    )
    for name in names
}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTH_WORDS = {name.casefold() for name in _MONTHS}
WEEKDAY_WORDS = {name.casefold() for name in WEEKDAYS}

# Capitals only, so that "may" and "march" as ordinary words are not read as months.
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ORDINAL = r"(?:st|nd|rd|th)?"
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}}){_ORDINAL}\s+(?:of\s+)?({_MONTH})\b\.?(?:,?\s+(\d{{4}})\b)?")
_MONTH_DAY = re.compile(rf"\b({_MONTH})\b\.?\s+(\d{{1,2}}){_ORDINAL}\b(?:,?\s+(\d{{4}})\b)?")
_MONTH_YEAR = re.compile(rf"\b({_MONTH})\b\.?,?\s+(\d{{4}})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")
_YEAR = re.compile(r"\b(?:in|since|by|during|from|until|year|early|late|mid)[ -]((?:19|20)\d{2})\b", re.IGNORECASE)
_RELATIVE = re.compile(
    r"\b(yesterday|today|tomorrow|tonight|last (?:night|week|month|year)|next (?:week|month|year)|this (?:morning|week|month|year))\b",
    re.IGNORECASE,
)
_WEEKDAY_BEFORE = re.compile(rf"\b({'|'.join(WEEKDAYS)})\b,?\s*(?:the\s+)?$")

_CURRENCY = r"₹|\$|€|£|Rs\.?\s?|INR\s?|USD\s?"
_SCALE = {
    "thousand": 1e3, "k": 1e3, "lakh": 1e5, "lakhs": 1e5, "million": 1e6, "crore": 1e7, "crores": 1e7,
    "billion": 1e9, "trillion": 1e12,
}
_NUMBER = re.compile(
    rf"(?<![\w.,/-])(?P<currency>{_CURRENCY})?"
    r"(?P<digits>\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)(?!st\b|nd\b|rd\b|th\b)"
    r"(?P<percent>\s?(?:%|percent\b|per cent\b))?"
    r"(?:\s*(?P<scale>thousand|lakhs?|million|crores?|billion|trillion|k)\b)?",
    re.IGNORECASE,
)
_NEXT_WORD = re.compile(r"\s*([A-Za-z][A-Za-z'-]*)")
_NOT_A_UNIT = {
    "a", "an", "and", "are", "as", "at", "by", "for", "from", "had", "has", "have", "in", "is", "of", "on", "or",
    "the", "to", "was", "were", "who", "with",
}
_UNIT_FILLERS = {"more", "other", "additional", "new", "further", "extra"}
# "Sector 9" and "Section 144" name something. They do not count anything.
_LABEL_BEFORE = re.compile(
    r"\b(?:sector|section|phase|ward|block|gate|platform|route|highway|room|article|chapter|rule|act|covid|level|"
    r"version|page|number|no\.|flight|terminal|plot|pier|lane|road|street)\s+$",
    re.IGNORECASE,
)
_APPROXIMATE = re.compile(r"\b(?:about|around|approximately|roughly|nearly|almost|some|close to|an estimated)\s*$", re.IGNORECASE)
_LOWER_BOUND = re.compile(r"\b(?:at least|over|more than|above|upwards of|no fewer than)\s*$", re.IGNORECASE)
_UPPER_BOUND = re.compile(r"\b(?:at most|up to|less than|under|fewer than|below|as many as)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class DateMention:
    text: str
    start: int
    end: int
    year: int | None = None
    month: int | None = None
    day: int | None = None
    weekday: str | None = None
    relative: bool = False
    # The calendar has no such day, such as 31 February.
    impossible: bool = False

    @property
    def value(self) -> str | None:
        """ISO text at the precision stated. A relative or ambiguous date has none."""
        if self.impossible or self.relative or (self.year is None and self.month is None):
            return None
        if self.year is None:
            return f"--{self.month:02d}-{self.day:02d}" if self.day else f"--{self.month:02d}"
        if self.month is None:
            return f"{self.year:04d}"
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}" if self.day else f"{self.year:04d}-{self.month:02d}"

    def conflicts_with(self, other: DateMention) -> bool:
        """Different only where both state a value, so "March 2024" and "5 March 2024" agree."""
        if self.value is None or other.value is None:
            return False
        pairs = ((self.year, other.year), (self.month, other.month), (self.day, other.day))
        return any(left is not None and right is not None and left != right for left, right in pairs)


@dataclass(frozen=True)
class NumberMention:
    text: str
    start: int
    end: int
    value: float
    # "people", "%", "inr" and so on. None when the words after it name nothing.
    unit: str | None = None
    # None means stated exactly; otherwise "approximate", "at_least" or "at_most".
    bound: str | None = None


def _full_date(text: str, match: re.Match[str], year: str | None, month: int, day: int) -> DateMention:
    weekday = _WEEKDAY_BEFORE.search(text[: match.start()])
    stated_year = int(year) if year else None
    # A leap year allows any 29 February when no year is stated.
    try:
        date(stated_year or 2000, month, day)
        impossible = False
    except ValueError:
        impossible = True
    return DateMention(
        match.group(0).rstrip(" ,."),
        match.start(),
        match.end(),
        stated_year,
        month,
        day,
        weekday.group(1) if weekday else None,
        impossible=impossible,
    )


def _overlaps(start: int, end: int, taken: list[tuple[int, int]]) -> bool:
    return any(start < other_end and other_start < end for other_start, other_end in taken)


def find_dates(text: str) -> list[DateMention]:
    found: list[DateMention] = []
    for match in _ISO.finditer(text):
        found.append(_full_date(text, match, match.group(1), int(match.group(2)), int(match.group(3))))
    for match in _NUMERIC.finditer(text):
        first, second, year = int(match.group(1)), int(match.group(2)), match.group(3)
        if first <= 12 and second <= 12 and first != second:
            # 05/03/2024 reads differently in different countries, so no value is claimed.
            found.append(DateMention(match.group(0), match.start(), match.end()))
            continue
        day, month = (second, first) if second > 12 else (first, second)
        found.append(_full_date(text, match, year, month, day))
    for pattern, day_group, month_group in ((_DAY_MONTH, 1, 2), (_MONTH_DAY, 2, 1)):
        for match in pattern.finditer(text):
            found.append(
                _full_date(text, match, match.group(3), _MONTHS[match.group(month_group)], int(match.group(day_group)))
            )
    taken = [(item.start, item.end) for item in found]
    for match in _MONTH_YEAR.finditer(text):
        if not _overlaps(match.start(), match.end(), taken):
            found.append(
                DateMention(match.group(0), match.start(), match.end(), int(match.group(2)), _MONTHS[match.group(1)])
            )
            taken.append((match.start(), match.end()))
    for match in _YEAR.finditer(text):
        if not _overlaps(match.start(1), match.end(1), taken):
            found.append(DateMention(match.group(1), match.start(1), match.end(1), int(match.group(1))))
            taken.append((match.start(1), match.end(1)))
    for match in _RELATIVE.finditer(text):
        found.append(DateMention(match.group(0), match.start(), match.end(), relative=True))
    return sorted(found, key=lambda item: item.start)


def _unit_after(text: str, position: int) -> str | None:
    match = _NEXT_WORD.match(text, position)
    if match and match.group(1).casefold() in _UNIT_FILLERS:
        match = _NEXT_WORD.match(text, match.end())
    if not match or match.group(1).casefold() in _NOT_A_UNIT:
        return None
    return match.group(1).casefold()


def _bound_before(text: str, position: int) -> str | None:
    before = text[max(0, position - 24) : position]
    if _APPROXIMATE.search(before):
        return "approximate"
    if _LOWER_BOUND.search(before):
        return "at_least"
    if _UPPER_BOUND.search(before):
        return "at_most"
    return None


def find_numbers(text: str, dates: list[DateMention]) -> list[NumberMention]:
    taken = [(item.start, item.end) for item in dates]
    found: list[NumberMention] = []
    for match in _NUMBER.finditer(text):
        if _overlaps(match.start(), match.end(), taken) or _LABEL_BEFORE.search(text[max(0, match.start() - 16) : match.start()]):
            continue
        digits, currency, percent, scale = (
            match.group("digits"), match.group("currency"), match.group("percent"), match.group("scale")
        )
        unit = "%" if percent else None
        if currency:
            unit = currency.strip(" .").casefold()
        elif not percent:
            unit = _unit_after(text, match.end())
        # A bare 2024 with nothing counted is a year, not a quantity.
        if re.fullmatch(r"(?:19|20)\d{2}", digits) and not (currency or percent or scale or unit):
            continue
        value = float(digits.replace(",", "")) * _SCALE.get((scale or "").casefold(), 1.0)
        found.append(
            NumberMention(match.group(0).strip(), match.start(), match.end(), value, unit, _bound_before(text, match.start()))
        )
    return found
