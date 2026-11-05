"""Name the warning signs of a scam, using context as well as words.

A bank's "never share your OTP" and a news story about fake jobs use the same
words as the scams themselves, so a sentence that warns or reports is not treated
as a request. Finding no sign never means something is safe. A sign is a reason to
look closer, not proof.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STRONG = "strong"
WEAK = "weak"
WARNING_SIGNS = "warning_signs_found"
WEAK_ONLY = "weak_signs_only"
NONE_FOUND = "none_found"

_SENTENCE = re.compile(r"(?<=[.!?।])\s+|\n+")
_FLAGS = re.IGNORECASE

# Someone warning about or reporting a scam, rather than running one. It covers the
# whole sentence. "Police said" alone is not enough, since scammers pose as police.
_DISCUSSES_SCAM = re.compile(
    r"\b(?:scam\w*|fraud\w*|beware|fake job|fake offer|how to spot|victims?|cyber ?crime|warned|regulator warned)\b",
    _FLAGS,
)
# "Never share", "do not pay", "real employers do not ask". The requested action is denied.
_DENIED = re.compile(
    r"\b(?:never|do not|don't|dont|will not|won't|not|no one|nobody|without|avoid|no)\b[^.!?,;]{0,40}$",
    _FLAGS,
)
# Telling someone how to use their own account is not asking them to hand it over.
_OWN_ACCOUNT_HELP = re.compile(r"\b(?:when you (?:sign|log) in|your own account|in settings)\b", _FLAGS)
_MONEY = r"(?:(?:rs\.?|inr|₹|\$|usd)\s?\d[\d,.]*|\d[\d,.]*\s?(?:rupees|rs\b|lakhs?|crores?|dollars)|\b\d[\d,]{2,})"
_PAY = r"(?:pay|send|deposit|transfer|wire|give)"
_FEE_WORD = (
    r"(?:registration|joining|training|processing|security|verification|document|clearance|delivery|shipping|"
    r"insurance|tax|booking|transport|re-?delivery|kit|handling|release|advance)\s+"
    r"(?:fee|fees|charge|charges|amount|deposit|advance)"
)
_JOB = re.compile(
    r"\b(?:jobs?|hiring|vacanc\w+|recruit\w*|work from home|work at home|part[- ]time|offer letter|appointment letter|"
    r"salary|typing|data entry|resume|cv|requirement for|airline|overseas)\b",
    _FLAGS,
)
_CREDENTIAL = (
    r"(?:otp|one[- ]time password|password|passcode|(?:atm |upi )?pin|cvv|card (?:number|details)|"
    r"account number|bank (?:account|details)|net ?banking(?: login)?|aadhaar(?: number)?|(?:six|6|four|4)[- ]digit code|"
    r"code you (?:just )?(?:got|received)|login details|username and password)"
)
_CREDENTIAL_REQUEST = re.compile(
    r"\b(?:send|share|enter|re-?enter|provide|confirm|give|tell|reply with|submit|update|verify|type|bata\w*)\b"
    rf"(?:\s+(?:me|us|the|your|our|and|in|here|with|please|all|a|this))*\s+[^.!?]{{0,30}}?{_CREDENTIAL}\b",
    _FLAGS,
)
_HINDI_CREDENTIAL = re.compile(r"(?:ओटीपी|पिन|पासवर्ड|बैंक खाता|कार्ड नंबर)[^।]{0,40}(?:भेजें|बताएं|बताइए|दें|दीजिए)")
_HINDI_DENIED = re.compile(r"(?:कभी|किसी को)[^।]{0,30}(?:न|नहीं)|(?:न|नहीं)\s+(?:बताएं|दें|भेजें)")
_THREAT = re.compile(
    r"\b(?:account|net ?banking|card|sim|connection|kyc|pan|number|service|profile)\b[^.!?]{0,50}?"
    r"\b(?:block\w*|suspend\w*|freez\w*|frozen|deactivat\w*|disconnect\w*|clos\w*|delet\w*|expired?|not linked|compromised)\b",
    _FLAGS,
)
_ACTION = re.compile(
    r"\b(?:click|open|link|update|call|press|contact|log ?in|login|verify|submit|reply|download|install|enter|tap)\b", _FLAGS
)
_AUTHORITY = re.compile(
    r"\b(?:customer care|customer support|microsoft support|tech(?:nical)? support|income tax|telecom authority|cbi|crime branch|"
    r"customs|police|officer|rbi|sbi|hdfc|icici|axis bank|electricity (?:board|department)|income-tax|security team|bank verification)\b",
    _FLAGS,
)
_ARREST = re.compile(
    r"\b(?:digital arrest|case has been filed|under arrest|arrest warrant|stay on this (?:video )?call|do not disconnect|"
    r"parcel with drugs)\b",
    _FLAGS,
)
_RELATIVE_NEED = re.compile(
    r"\b(?:lost my phone|my new number|new number|friend's phone|had an accident|stuck abroad|wallet was stolen)\b", _FLAGS
)
_NEED_MONEY = re.compile(
    rf"\b(?:{_PAY}|buy)\b[^.!?]{{0,30}}\b(?:money|it now|\d[\d,]*|cards?)\b|\bneed money\b", _FLAGS
)
_REMOTE_ACCESS = re.compile(r"\b(?:remote access|allow access|anydesk|teamviewer)\b", _FLAGS)


@dataclass(frozen=True)
class _Rule:
    sign: str
    category: str
    strength: str
    pattern: re.Pattern[str]
    why: str
    # When set, the sentence or post must also match this.
    needs: re.Pattern[str] | None = None
    # The post, not only the sentence, must match ``needs``.
    needs_whole_post: bool = False


_RULES = (
    # Fake jobs
    _Rule(
        "job_upfront_fee", "fake_job", STRONG,
        re.compile(
            rf"\b(?:{_FEE_WORD}|refundable\s+(?:security\s+)?(?:amount|deposit)|{_PAY}\s+(?:the\s+)?(?:\w+\s+){{0,2}}fee)\b|\b{_PAY}\s+{_MONEY}\s+for\b",
            _FLAGS,
        ),
        "Asks for money before a job starts. Real employers do not charge to hire.",
        _JOB, True,
    ),
    _Rule(
        "job_easy_money", "fake_job", WEAK,
        re.compile(
            rf"\b(?:earn|make)\s+(?:up to\s+)?{_MONEY}(?:\s+to\s+{_MONEY})?\s*(?:\w+\s+)?(?:per|a|each|every)?\s*(?:day|daily|hour|week)\b|\bsalary\s+{_MONEY}\s+a\s+month\b.*\bat home\b",
            _FLAGS,
        ),
        "Promises high pay for easy work.",
    ),
    _Rule(
        "job_no_checks", "fake_job", WEAK,
        re.compile(
            r"\b(?:no (?:interview|experience|skills?|exam)|without (?:any )?(?:interview|exam|written test)|no skills required)\b", _FLAGS
        ),
        "Offers work without normal hiring checks.",
        _JOB, True,
    ),
    _Rule(
        "job_chat_app", "fake_job", WEAK,
        re.compile(r"\b(?:telegram|whatsapp)\b", _FLAGS),
        "Moves hiring to a chat app.",
        _JOB, True,
    ),
    # Investment
    _Rule(
        "guaranteed_returns", "investment", STRONG,
        re.compile(
            r"\b(?:guaranteed?|assured)\s+(?:\w+\s+){0,2}(?:returns?|profits?|income)\b|\b(?:returns?|profits?)\b[^.!?]{0,30}\b(?:guaranteed|assured)\b",
            _FLAGS,
        ),
        "Promises guaranteed returns. No real investment can.",
    ),
    _Rule(
        "money_multiplier", "investment", STRONG,
        re.compile(
            r"\b(?:double|triple|multiply)\s+your\s+\w+|\b\d+\s+times\s+your\s+capital\b"
            rf"|\b(?:put in|invest)\s+{_MONEY}[^.!?]{{0,30}}\b(?:get|back)\b"
            rf"|\bturn(?:ed)?\s+{_MONEY}\s+into\s+{_MONEY}",
            _FLAGS,
        ),
        "Promises to multiply money quickly.",
    ),
    _Rule(
        "unrealistic_rate", "investment", STRONG,
        re.compile(r"\b\d+(?:\.\d+)?\s?%\s+(?:\w+\s+){0,2}(?:per|every|each|a)?\s*(?:day|daily|week|weekly|month)\b", _FLAGS),
        "Promises a return far above any normal rate.",
        re.compile(r"\b(?:invest\w*|returns?|profits?|interest|scheme|trading|mining|pool)\b", _FLAGS), False,
    ),
    _Rule(
        "no_risk", "investment", WEAK,
        re.compile(r"\b(?:zero risk|no risk|risk[- ]free|without any risk)\b", _FLAGS),
        "Claims there is no risk. All investments carry some.",
    ),
    _Rule(
        "invest_quick_riches", "investment", WEAK,
        re.compile(rf"\b(?:made|make)\s+(?:me\s+)?{_MONEY}\s+(?:in|this)\s+(?:a|one|\d+)?\s*(?:day|week|month)|\b(?:vip|premium)\s+(?:trading\s+)?group\b", _FLAGS),
        "Uses a story of quick riches or a paid tips group to attract money.",
    ),
    # Giveaways
    _Rule(
        "you_won", "giveaway", STRONG,
        re.compile(
            r"\byou (?:have|'ve) (?:won|been chosen|been selected)\b|\byou were picked\b|\byou are the lucky winner\b|"
            r"\byour (?:mobile )?number (?:has )?won\b|\blucky (?:draw|winner)\b|\bwinner alert\b|\bcollect your (?:prize|reward)\b|"
            r"\bclaim your (?:prize|reward)\b",
            _FLAGS,
        ),
        "Says you won something you did not enter.",
    ),
    _Rule(
        "pay_to_claim", "giveaway", STRONG,
        re.compile(
            rf"\b(?:pay|transfer)\b[^.!?]{{0,40}}\b(?:{_FEE_WORD}|shipping|charge|tax amount)\b[^.!?]{{0,40}}\b(?:prize|claim|receive|release|free|get your)\b"
            rf"|\b(?:to receive|to claim)\b[^.!?]{{0,30}}\b(?:transfer|pay)\b",
            _FLAGS,
        ),
        "Asks for payment to collect a prize. Real prizes do not cost money to collect.",
    ),
    _Rule(
        "share_to_win", "giveaway", STRONG,
        re.compile(
            r"\bfree\b[^.!?]{0,60}\b(?:for all|first \d+|worth)\b[^.!?]{0,60}"
            r"|\b(?:share|forward)\s+(?:this\s+)?(?:with|to)\s+\d+\s+(?:groups?|friends?|people)\b",
            _FLAGS,
        ),
        "Offers something free in return for spreading a message or giving details.",
        re.compile(r"\b(?:share|forward|form|enter your|details)\b", _FLAGS), False,
    ),
    _Rule(
        "crypto_giveaway", "giveaway", STRONG,
        re.compile(rf"\b{_PAY}\s+[\d.]+\s*(?:btc|eth|usdt|bitcoin)\b", _FLAGS),
        "Asks for crypto and promises more back.",
    ),
    # Impersonation
    _Rule(
        "account_threat", "impersonation", STRONG,
        _THREAT,
        "Threatens to close an account or service and asks you to act now.",
        _ACTION, True,
    ),
    _Rule(
        "official_threat", "impersonation", STRONG,
        _ARREST,
        "Uses a legal threat. Real police do not hold anyone on a call.",
    ),
    _Rule(
        "official_refund_bait", "impersonation", WEAK,
        re.compile(r"\b(?:refund|cashback)\b[^.!?]{0,40}\b(?:pending|receive|get)\b|\byour\s+(?:computer|device)\s+is\s+infected\b", _FLAGS),
        "Offers a refund or warns of a problem to start a conversation.",
        _AUTHORITY, True,
    ),
    _Rule(
        "remote_access", "impersonation", STRONG,
        _REMOTE_ACCESS,
        "Asks for remote access to your device.",
    ),
    _Rule(
        "relative_in_trouble", "impersonation", STRONG,
        _RELATIVE_NEED,
        "Claims to be someone you know, on a new number, in sudden need of money.",
        _NEED_MONEY, True,
    ),
    # Payment requests
    _Rule(
        "gift_card_payment", "payment_request", STRONG,
        re.compile(r"\b(?:buy|send|purchase)\b[^.!?]{0,30}\b(?:gift cards?|play cards?|itunes cards?|steam cards?)\b", _FLAGS),
        "Asks for payment in gift cards, which cannot be traced or refunded.",
    ),
    _Rule(
        "payment_handle", "payment_request", STRONG,
        re.compile(r"\b[\w.-]+@(?:ybl|oksbi|okhdfcbank|okaxis|okicici|paytm|upi|ibl|axl)\b", _FLAGS),
        "Asks for money to a personal payment handle.",
    ),
    _Rule(
        "crypto_payment", "payment_request", STRONG,
        re.compile(r"\b(?:transfer|send|pay)\b[^.!?]{0,20}\b(?:usdt|bitcoin|btc|crypto|eth)\b[^.!?]{0,30}\bwallet\b", _FLAGS),
        "Asks for crypto, which cannot be reversed.",
    ),
    _Rule(
        "pay_to_receive", "payment_request", STRONG,
        re.compile(
            r"\b(?:to get your refund|to receive (?:your )?(?:refund|money))\b[^.!?]{0,50}\b(?:scan|enter|pay)\b"
            r"|\bscan\b[^.!?]{0,30}\bqr\b[^.!?]{0,40}\bpin\b"
            r"|\bto release your\b[^.!?]{0,30}\bpay\b",
            _FLAGS,
        ),
        "Asks you to pay or enter a PIN in order to receive money. A PIN is only used to send money.",
    ),
    _Rule(
        "fee_with_deadline", "payment_request", STRONG,
        re.compile(
            r"\bpay\b[^.!?]{0,40}\b(?:charge|fee|fine)\b[^.!?]{0,60}\b(?:today|or it|so your|immediately|right away|within)\b"
            r"|\bwire transfer\b|\bdo not tell (?:anyone|your family)\b",
            _FLAGS,
        ),
        "Demands a small fee or secrecy under time pressure.",
    ),
    # Credential requests
    _Rule(
        "credential_request", "credential_request", STRONG,
        _CREDENTIAL_REQUEST,
        "Asks for a code, password or bank detail. Real services do not ask for these in a message.",
    ),
    _Rule(
        "credential_request_hindi", "credential_request", STRONG,
        _HINDI_CREDENTIAL,
        "Asks for a code, password or bank detail. Real services do not ask for these in a message.",
    ),
)

# The pieces that ask for something, and so are denied by a "never" or "do not" before them.
_DENIABLE_CATEGORIES = {"credential_request", "payment_request", "fake_job"}


@dataclass(frozen=True)
class ScamSign:
    sign: str
    category: str
    strength: str
    why: str
    # A short quote from the submission, so the user can see what triggered it.
    quote: str


@dataclass(frozen=True)
class ScamRuleReport:
    assessment: str
    signs: list[ScamSign]
    categories: list[str]


def _is_denied(sentence: str, start: int) -> bool:
    return bool(_DENIED.search(sentence[:start]) or _OWN_ACCOUNT_HELP.search(sentence))


def _matches(rule: _Rule, sentence: str, post: str) -> re.Match[str] | None:
    if rule.needs is not None and not rule.needs.search(post if rule.needs_whole_post else sentence):
        return None
    return next(
        (
            match
            for match in rule.pattern.finditer(sentence)
            if not (rule.category in _DENIABLE_CATEGORIES and _is_denied(sentence, match.start()))
        ),
        None,
    )


def find_signs(text: str) -> ScamRuleReport:
    post = text.strip()
    # A post that warns about scams or reports one is talking about them, in every sentence.
    discussing = bool(_DISCUSSES_SCAM.search(post))
    signs: list[ScamSign] = []
    seen: set[str] = set()
    for sentence in _SENTENCE.split(post):
        if discussing or _HINDI_DENIED.search(sentence):
            continue
        for rule in _RULES:
            if rule.sign in seen:
                continue
            match = _matches(rule, sentence, post)
            if match:
                seen.add(rule.sign)
                signs.append(ScamSign(rule.sign, rule.category, rule.strength, rule.why, match.group(0).strip()[:120]))

    if any(sign.strength == STRONG for sign in signs) or len(signs) >= 2:
        assessment = WARNING_SIGNS
    elif signs:
        assessment = WEAK_ONLY
    else:
        assessment = NONE_FOUND
    return ScamRuleReport(assessment, signs, sorted({sign.category for sign in signs}))
