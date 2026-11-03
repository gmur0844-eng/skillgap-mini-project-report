"""
Pure skill-mention extraction logic (no DB, no I/O) -- spec Section 5/6:
controlled-vocabulary + alias + technical-token matching, deliberately NOT
blind fuzzy matching and NOT a transformer model.

Design note on matching: whole-word boundaries are checked with Unicode-aware
lookarounds (LEFT_BOUNDARY / RIGHT_BOUNDARY below) rather than \\b, because \\b
treats punctuation as a boundary -- which would let "C++" incorrectly match
just "C", or let a bare ".NET" search match the ".NET" inside "ASP.NET". The
lookaround approach only treats adjacency to another alphanumeric character as
disqualifying, so technical tokens with trailing/internal punctuation are
matched as whole, exact units.
"""
import re
import hashlib
from dataclasses import dataclass

from app.pipelines.preprocessing.skill_normalization import (
    normalize_skill_text,
    TECHNICAL_TOKENS,
    METHOD_CONFIDENCE,
)


@dataclass
class VocabTerm:
    term_text: str          # the label/alias exactly as stored (e.g. ESCO preferred_label)
    skill_id: int | None    # canonical Skill.id this term resolves to; None for a bare technical token
    external_id: str | None
    method_if_exact: str    # "exact_label" | "alias" | "technical_token"


@dataclass
class Mention:
    original_text: str
    normalized_text: str
    method: str
    confidence: float
    skill_id: int | None
    external_id: str | None
    mapping_status: str  # "mapped" | "unmapped"
    start: int | None = None
    end: int | None = None


def build_vocabulary_index(skill_rows: list[dict], alias_rows: list[dict]) -> list[VocabTerm]:
    """
    skill_rows: [{"id": int, "external_id": str, "preferred_label": str}, ...]
    alias_rows: [{"skill_id": int, "external_id": str, "alias_label": str}, ...]
    Pure transformation -- callers (app.pipelines.ingestion.skill_extraction)
    are responsible for querying these from the DB and passing plain dicts in,
    so this function itself never touches SQLAlchemy.
    """
    terms = []
    for row in skill_rows:
        if row.get("preferred_label"):
            terms.append(VocabTerm(row["preferred_label"], row["id"], row.get("external_id"), "exact_label"))
    for row in alias_rows:
        if row.get("alias_label"):
            terms.append(VocabTerm(row["alias_label"], row.get("skill_id"), row.get("external_id"), "alias"))
    for token in TECHNICAL_TOKENS:
        terms.append(VocabTerm(token, None, None, "technical_token"))
    return terms


# Word boundaries, Unicode-aware. A match may not start or end inside a word (any script's letters or digits),
# and may not start right after "<letter><apostrophe>": the tail of a contraction or possessive
# ("We're", "don’t", "company’s") is not a free-standing word. Apostrophe forms: ASCII ' and the Unicode
# right/left single quotation marks and modifier letter apostrophe.
APOSTROPHES = "'\u2019\u2018\u02bc"
LEFT_BOUNDARY = rf"(?<![^\W_])(?<![^\W_][{APOSTROPHES}])"
RIGHT_BOUNDARY = r"(?![^\W_])"


def _term_body(term_text: str) -> str:
    escaped = re.escape(term_text.strip())
    return escaped.replace(r"\ ", r"\s+")  # allow flexible whitespace in multi-word terms


def _term_pattern(term_text: str) -> re.Pattern:
    return re.compile(LEFT_BOUNDARY + _term_body(term_text) + RIGHT_BOUNDARY, re.IGNORECASE)


def _bounded(text, start, end):
    """LEFT_BOUNDARY at start and RIGHT_BOUNDARY at end, in Python. [^\\W_] (a word character that is not "_") is
    exactly str.isalnum(): both are Unicode alphabetic, decimal, digit or numeric."""
    if start > 0:
        before = text[start - 1]
        if before.isalnum() or (before in APOSTROPHES and start > 1 and text[start - 2].isalnum()):
            return False
    return not (end < len(text) and text[end].isalnum())


def extract_mentions_from_text(text: str, vocabulary: list[VocabTerm]) -> list[Mention]:
    """
    Scans free text (a job description, a curriculum topic, a course title...)
    for whole-token matches against the vocabulary. Longer terms are checked
    first and matched spans are marked "consumed" so e.g. "machine learning"
    and a separate "learning" vocabulary entry don't both fire on the same
    text and produce a redundant, overlapping mention.
    """
    if not text:
        return []

    sorted_terms = sorted(vocabulary, key=lambda t: len(t.term_text), reverse=True)
    consumed = [False] * len(text)
    mentions: list[Mention] = []

    for term in sorted_terms:
        pattern = _term_pattern(term.term_text)
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if any(consumed[start:end]):
                continue
            for i in range(start, end):
                consumed[i] = True
            raw = m.group(0)
            normalized = normalize_skill_text(raw)
            method = term.method_if_exact
            if method == "exact_label" and raw != term.term_text:
                method = "normalized_label"
            skill_id = term.skill_id
            mentions.append(
                Mention(
                    original_text=raw,
                    normalized_text=normalized,
                    method=method,
                    confidence=METHOD_CONFIDENCE[method],
                    skill_id=skill_id,
                    external_id=term.external_id,
                    mapping_status="mapped" if skill_id is not None else "unmapped",
                    start=start,
                    end=end,
                )
            )

    return mentions


def extract_mentions_from_tag_field(tag_string: str, vocabulary: list[VocabTerm]) -> list[Mention]:
    """
    Splits a structured tags/skills field (e.g. Naukri's comma-separated
    "skills" column) into individual candidate mentions, then tries to match
    each one against the vocabulary. An explicit human-provided tag is always
    recorded as a mention (method "structured_tag") even if it does not
    resolve to any canonical skill -- an unmapped structured tag is still
    useful evidence, never discarded.
    """
    if not tag_string:
        return []

    raw_tags = [t.strip() for t in re.split(r"[,;|/]", tag_string) if t.strip()]
    mentions = []
    normalized_lookup = {normalize_skill_text(t.term_text): t for t in vocabulary}

    for raw_tag in raw_tags:
        normalized = normalize_skill_text(raw_tag)
        match = normalized_lookup.get(normalized)
        if match:
            mentions.append(
                Mention(
                    original_text=raw_tag,
                    normalized_text=normalized,
                    method="structured_tag",
                    confidence=METHOD_CONFIDENCE["structured_tag"],
                    skill_id=match.skill_id,
                    external_id=match.external_id,
                    mapping_status="mapped" if match.skill_id is not None else "unmapped",
                )
            )
        else:
            mentions.append(
                Mention(
                    original_text=raw_tag,
                    normalized_text=normalized,
                    method="structured_tag",
                    confidence=METHOD_CONFIDENCE["structured_tag"],
                    skill_id=None,
                    external_id=None,
                    mapping_status="unmapped",
                )
            )
    return mentions


def deduplicate_mentions(mentions: list[Mention]) -> list[Mention]:
    """
    Within one source record, collapse mentions that share the same
    (normalized_text, method). Order-preserving: keeps the first occurrence.
    """
    seen = set()
    result = []
    for m in mentions:
        key = (m.normalized_text, m.method)
        if key in seen:
            continue
        seen.add(key)
        result.append(m)
    return result


def mention_hash_for(source_type: str, source_id: int, normalized_text: str, method: str) -> str:
    """
    Idempotency key (reuses the Phase-1 hardening pattern from job postings):
    a stable hash of (where this mention came from, what it normalized to,
    how it was found). Re-running extraction on the same source produces the
    same hash, so app.pipelines.ingestion.skill_extraction can skip
    already-persisted mentions instead of duplicating them.
    """
    raw = f"{source_type}|{source_id}|{normalized_text}|{method}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def partition_new_mentions(
    mentions: list, source_type: str, source_id: int, existing_hashes: set
) -> tuple:
    """
    Pure idempotency decision: given a batch of Mention objects plus the set
    of mention_hash values already known (from the DB, or from earlier in
    this same run), returns (new_with_hash, skipped) where new_with_hash is a
    list of (mention, hash) pairs to actually persist, and skipped is the
    list of mentions that already exist and should NOT be re-inserted.

    Deliberately separated from any session.add() call so the orchestration's
    core idempotency behavior -- "run the same source twice, second run finds
    everything already there" -- is testable without a live database. The
    DB-dependent caller (app.pipelines.ingestion.skill_extraction) is
    responsible for actually persisting `new_with_hash` and for updating
    `existing_hashes` with the new hashes afterward (or before the next call,
    for within-run duplicate protection).
    """
    new_with_hash, skipped = [], []
    for m in mentions:
        h = mention_hash_for(source_type, source_id, m.normalized_text, m.method)
        if h in existing_hashes:
            skipped.append(m)
        else:
            new_with_hash.append((m, h))
    return new_with_hash, skipped


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class IndexedVocabulary:
    """
    Pre-compiled form of a vocabulary for large term lists (thousands of
    ESCO labels x thousands of texts). Semantics are IDENTICAL to
    extract_mentions_from_text -- same longest-first order, same
    case-insensitive whole-token patterns, same consumed-span rule -- it only
    skips terms that cannot match: a term can only match if its first
    ASCII alphanumeric run occurs as a whole alphanumeric run in the text
    (the pattern's lookarounds guarantee that). Equivalence is regression-tested.
    """

    def __init__(self, vocabulary):
        ordered = sorted(vocabulary, key=lambda t: len(t.term_text), reverse=True)
        self.entries = []
        self._patterns = {}
        self._offsets = {}
        for position, term in enumerate(ordered):
            tokens = [t.lower() for t in _ASCII_TOKEN_RE.findall(term.term_text)]
            # every ASCII alphanumeric run of the term is bounded by the term's own
            # non-alphanumeric characters (matched literally) or by the pattern's
            # lookarounds, so each must occur as a whole run in a matching text
            self.entries.append((position, term, frozenset(tokens), tokens[0] if tokens else None))
            # where a match starts relative to the term's first run: the characters before it are matched literally,
            # one text character each, unless they include whitespace (matched by \s+, any length)
            stripped = term.term_text.strip()
            first = _ASCII_TOKEN_RE.search(stripped)
            if first and not any(c.isspace() for c in stripped[:first.start()]):
                self._offsets[term.term_text] = first.start()
        self.by_first = {}      # first run -> second run -> terms with more runs (all must occur in the text)
        self.by_first_one = {}  # first run -> terms whose only distinct run it is (it occurs whenever the key does)
        self.always = []
        self._bodies = {}
        for entry in self.entries:
            if entry[3] is None:
                self.always.append(entry)
            elif len(entry[2]) == 1:
                self.by_first_one.setdefault(entry[3], []).append(entry)
            else:
                second = next(t for t in (r.lower() for r in _ASCII_TOKEN_RE.findall(entry[1].term_text)) if t != entry[3])
                self.by_first.setdefault(entry[3], {}).setdefault(second, []).append(entry)

    def pattern(self, term):
        p = self._patterns.get(term.term_text)
        if p is None:
            p = self._patterns[term.term_text] = _term_pattern(term.term_text)
        return p

    def body(self, term):
        """The term's pattern without its boundary lookarounds (checked by _bounded instead): compiling the
        lookarounds' Unicode classes for every term costs several times more than the term itself."""
        p = self._bodies.get(term.term_text)
        if p is None:
            p = self._bodies[term.term_text] = re.compile(_term_body(term.term_text), re.IGNORECASE)
        return p

    def candidates(self, text):
        """(position, term, first run) of the terms that can occur in the text, longest term first. The runs are read
        with the four characters that match ASCII letters case-insensitively read as those letters, so a term written
        with one of them in the text ("ıt" for "it") is still a candidate."""
        tokens = {t.lower() for t in _ASCII_TOKEN_RE.findall(text.translate(_ASCII_CASEFOLD_MAP))}
        chosen = list(self.always)
        for token in tokens:
            chosen.extend(self.by_first_one.get(token, ()))
            for second, entries in self.by_first.get(token, {}).items():
                if second in tokens:  # a term's second distinct run must occur too: most terms are skipped here
                    chosen.extend([e for e in entries if e[2] <= tokens])
        chosen.sort(key=lambda e: e[0])
        return [(pos, term, first) for pos, term, _, first in chosen]

    def starts(self, term, first, runs):
        """Every position where the term can start in the text whose ASCII runs (lower-cased) start at runs[token],
        or None when the term must be searched for over the whole text."""
        offset = self._offsets.get(term.term_text)
        if offset is None or first is None:
            return None
        return [p - offset for p in runs.get(first, ()) if p >= offset]


# Non-ASCII characters that a case-insensitive pattern matches to an ASCII letter (KELVIN SIGN = k, LATIN SMALL LONG
# S = s, dotless i and dotted capital I = i). A text containing one is searched in full, so the run positions below
# are never relied on for it.
_ASCII_CASEFOLD = frozenset("\u212a\u017f\u0131\u0130")
_ASCII_CASEFOLD_MAP = str.maketrans({"\u212a": "k", "\u017f": "s", "\u0131": "i", "\u0130": "i"})


def _matches(index, term, text, starts):
    """index.pattern(term).finditer(text), trying only the given start positions (None: the whole text). Identical
    results: every match of a term starts at one of them (its first ASCII run occurs as a whole run, preceded by its
    fixed-length prefix); at a start, the term's body matches with one possible end (literal characters, and \\s+
    runs followed by a non-space character), so checking the boundaries after it decides exactly what the pattern's
    lookarounds decide; and a start inside the previous match is skipped exactly as finditer resumes its search at
    the previous match's end."""
    if starts is None:
        yield from index.pattern(term).finditer(text)
        return
    if not starts:
        return
    body = index.body(term)
    resume = 0
    for s in starts:
        if s < resume:
            continue
        m = body.match(text, s)
        if m and _bounded(text, s, m.end()):
            resume = m.end()
            yield m


def extract_mentions_indexed(text, index):
    """Same output as extract_mentions_from_text(text, vocabulary) for the
    vocabulary the index was built from. Instead of searching the whole text once per candidate term, each term is
    tried only where its first word occurs (see _matches)."""
    if not text:
        return []
    consumed = [False] * len(text)
    mentions = []
    runs = None
    if not (_ASCII_CASEFOLD & set(text)):
        runs = {}
        for r in _ASCII_TOKEN_RE.finditer(text):
            runs.setdefault(r.group(0).lower(), []).append(r.start())
    for _, term, first in index.candidates(text):
        for m in _matches(index, term, text, index.starts(term, first, runs) if runs is not None else None):
            start, end = m.start(), m.end()
            if any(consumed[start:end]):
                continue
            for i in range(start, end):
                consumed[i] = True
            raw = m.group(0)
            method = term.method_if_exact
            if method == "exact_label" and raw != term.term_text:
                method = "normalized_label"
            mentions.append(Mention(
                original_text=raw, normalized_text=normalize_skill_text(raw), method=method,
                confidence=METHOD_CONFIDENCE[method], skill_id=term.skill_id, external_id=term.external_id,
                mapping_status="mapped" if term.skill_id is not None else "unmapped", start=start, end=end))
    return mentions
