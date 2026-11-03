"""
ESCO DELTA handling with explicit delta semantics.

The supplied file (ESCO dataset v1.2.1 "delta", one CSV inside a ZIP) is a
CHANGE LOG between two ESCO releases, not a taxonomy. Columns:

    concept URI, concept prefLabel, field, old value, new value, action, language

  action     Added | Removed | Updated
  field      altLabel, prefLabel, description, hiddenLabel, broader, inScheme,
             isEssentialSkillFor, ... (a property of the concept that changed)
  old value  "None" for Added; the previous value for Updated / Removed
  new value  "None" for Removed; the new value for Added / Updated
  language   ISO code for language-tagged fields, "None" for relations
  concept prefLabel   the concept's CURRENT English preferred label (verified:
             for all 111 English prefLabel updates it equals the new value)

What CAN be reconstructed (and is used for mapping):
  * the set of skill concepts that the delta touches (URI + current English
    prefLabel, whitespace-normalized);
  * English altLabels that are ACTIVE after the delta: Added -> active,
    Updated -> new value active and old value retired, Removed -> retired.

What CANNOT be reconstructed without the full v1.2.x baseline (not supplied):
  * skill concepts the delta does not touch (absent from this vocabulary);
  * English altLabels that did not change (only changed labels are listed);
  * skill type (skill / knowledge / language / transversal) except the 2
    concepts whose skillType changed;
  * the complete skill hierarchy and occupation-skill relations.
Consequently: a job skill that is not found here is "not found in the
supplied delta subset" -- it is NOT evidence that ESCO lacks the skill.
"""
import csv
import io
import re
import zipfile
from collections import Counter, defaultdict

ESCO_URI_RE = re.compile(r"^http://data\.europa\.eu/esco/([a-z-]+)/[0-9a-f-]{36}$")
# skill hierarchy groups use codes instead of UUIDs (".../esco/skill/A1.9.0");
# they are grouping nodes, not skills, and are never used as mapping targets
ESCO_SKILL_GROUP_RE = re.compile(r"^http://data\.europa\.eu/esco/skill/[A-Z]\d*(\.\d+)*$")
_WS_RE = re.compile(r"\s+")
_QUALIFIER_RE = re.compile(r"^(?P<base>.+?)\s*\((?P<qualifier>[^()]+)\)\s*$")
EXPECTED_COLUMNS = ["concept URI", "concept prefLabel", "field", "old value", "new value", "action", "language"]


def _clean(text):
    return _WS_RE.sub(" ", (text or "").replace(" ", " ")).strip()


def _none(value):
    return None if value in (None, "None") else value


def read_delta_rows(zip_path):
    """Yield dict rows from the single CSV in the ZIP (members with absolute
    paths are handled; the header is verified)."""
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"expected exactly one CSV in the ESCO ZIP, found {members}")
        with zf.open(members[0]) as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", newline=""))
            if reader.fieldnames != EXPECTED_COLUMNS:
                raise ValueError(f"unexpected ESCO delta header: {reader.fieldnames}")
            for row in reader:
                yield row


def build_skill_vocabulary(rows):
    """
    Returns (vocabulary, audit). vocabulary = {
      "concepts": {uri: {"uri", "pref_label", "skill_type_change": ...}},
      "labels":   [{"uri", "label", "label_kind": prefLabel|altLabel|qualifier_stripped, "delta_action"}],
      "retired_labels": [{"uri", "label", "reason"}],
    }
    Only concept type "skill" (URI path /esco/skill/) is used for skills.
    """
    audit = {
        "rows": 0, "rows_by_action": Counter(), "rows_by_field": Counter(), "rows_by_language": Counter(),
        "rows_by_concept_type": Counter(), "distinct_uris": set(), "unresolvable_rows": 0,
        "unresolvable_examples": [], "english_label_changes": Counter(),
        "prefLabel_updates_whitespace_only": 0, "prefLabel_updates_substantive": 0,
    }
    pref = {}
    alt_new = defaultdict(dict)  # uri -> {label: action}  (value present AFTER the delta)
    alt_old = defaultdict(dict)  # uri -> {label: action}  (value present only BEFORE the delta)
    skill_type_change = {}
    for row in rows:
        audit["rows"] += 1
        action, field, lang = row["action"], row["field"], row["language"]
        uri = row["concept URI"].strip()
        audit["rows_by_action"][action] += 1
        audit["rows_by_field"][field] += 1
        audit["rows_by_language"][lang] += 1
        audit["distinct_uris"].add(uri)
        match = ESCO_URI_RE.match(uri)
        ctype = match.group(1) if match else ("skill-group" if ESCO_SKILL_GROUP_RE.match(uri) else None)
        audit["rows_by_concept_type"][ctype or "non-ESCO-URI (e.g. NACE)"] += 1
        if action not in ("Added", "Removed", "Updated"):
            audit["unresolvable_rows"] += 1
            if len(audit["unresolvable_examples"]) < 5:
                audit["unresolvable_examples"].append({"uri": uri, "action": action, "field": field})
            continue
        if ctype != "skill":
            continue
        label = _clean(row["concept prefLabel"])
        if label:
            pref.setdefault(uri, label)
        old, new = _none(row["old value"]), _none(row["new value"])
        if field == "skillType":
            skill_type_change[uri] = {"old": old, "new": new}
        if lang != "en":
            continue
        if field == "prefLabel":
            audit["english_label_changes"][f"prefLabel.{action}"] += 1
            if _clean(old) == _clean(new):
                audit["prefLabel_updates_whitespace_only"] += 1
            else:
                audit["prefLabel_updates_substantive"] += 1
        elif field == "altLabel":
            audit["english_label_changes"][f"altLabel.{action}"] += 1
            if action in ("Added", "Updated") and new:
                alt_new[uri][_clean(new)] = action
            if action in ("Removed", "Updated") and old and _clean(old) != _clean(new):
                alt_old[uri][_clean(old)] = action
        elif field == "hiddenLabel":
            audit["english_label_changes"][f"hiddenLabel.{action}"] += 1

    concepts = {uri: {"uri": uri, "pref_label": lab, "skill_type_change": skill_type_change.get(uri)}
                for uri, lab in sorted(pref.items())}
    labels, retired = [], []
    for uri, c in concepts.items():
        labels.append({"uri": uri, "label": c["pref_label"], "label_kind": "prefLabel", "delta_action": None})
        m = _QUALIFIER_RE.match(c["pref_label"])
        if m and len(m.group("base").split()) <= 3:
            # "Python (computer programming)" -> "Python": ESCO's disambiguating
            # qualifier removed. Kept as a separate, weaker label kind.
            labels.append({"uri": uri, "label": m.group("base").strip(), "label_kind": "qualifier_stripped",
                           "delta_action": None, "qualifier": m.group("qualifier").strip()})
    # Delta semantics: a label is active after the release if it is the new
    # value of an Added/Updated row; it is retired if it is the old value of a
    # Removed/Updated row and not re-added. Order of rows does not matter.
    for uri in sorted(set(alt_new) | set(alt_old)):
        if uri not in concepts:
            continue
        for label, how in sorted(alt_new.get(uri, {}).items()):
            labels.append({"uri": uri, "label": label, "label_kind": "altLabel", "delta_action": how})
        for label, how in sorted(alt_old.get(uri, {}).items()):
            if label not in alt_new.get(uri, {}):
                retired.append({"uri": uri, "label": label, "reason": f"altLabel {how} (old value) in v1.2.1 delta"})

    audit["distinct_uris"] = len(audit["distinct_uris"])
    for key in ("rows_by_action", "rows_by_field", "rows_by_language", "rows_by_concept_type", "english_label_changes"):
        audit[key] = dict(sorted(audit[key].items()))
    audit["skill_concepts_reconstructed"] = len(concepts)
    audit["active_english_labels"] = dict(Counter(l["label_kind"] for l in labels))
    audit["retired_english_altlabels"] = len(retired)
    audit["skill_type_known_for"] = len(skill_type_change)
    audit["concept_level"] = {
        "added": 0, "removed": 0,
        "changed": len(concepts),
        "unchanged_baseline": None,
        "note": ("No English skill concept is Added or Removed as a whole in this delta (English prefLabel rows "
                 "are Updated only; non-English prefLabel Added/Removed pairs are translation replacements). "
                 "'changed' = skill concepts with at least one row in the delta. Unchanged baseline concepts "
                 "are not in the supplied file, so their count is unknown (None), not zero."),
    }
    audit["reconstruction_scope"] = "PARTIAL_DELTA_SUBSET"
    return {"concepts": concepts, "labels": labels, "retired_labels": retired}, audit
