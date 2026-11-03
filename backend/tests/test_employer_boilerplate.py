"""Employer text repeated across most of one employer's postings is not read for skills. Synthetic postings; no real
employer."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine.config import load_config
from app.knowledge_engine.jobs import employer_boilerplate

CFG = {"enabled": True, "min_employer_postings": 5, "min_share": 0.8, "min_titles": 3, "min_words": 3}
ABOUT = "Example Co builds payment software used by millions of shoppers."
VALUES = "Our leadership principles guide how we make decisions every day."
SOCIAL = "Follow us on Twitter, LinkedIn and Instagram."
SHARED_REQ = "Experience with Kubernetes and Docker in production is required."


def _postings(n=5, titles=("Backend Engineer", "Data Engineer", "SRE", "QA Engineer", "Frontend Engineer"),
              company="example co", shared_req_in=2):
    out = []
    for i in range(n):
        job = f"You will build service number {i} in Go and PostgreSQL for team {i}."
        if i < shared_req_in:
            job += f"\n{SHARED_REQ}"
        text = f"{ABOUT}\n{job}\n{VALUES} {SOCIAL}"
        out.append({"posting_uid": f"p{i}", "company_key": company, "job_title": titles[i % len(titles)],
                    "clean_description": text})
    return out


def test_employer_text_is_blanked_and_job_text_kept_at_the_same_offsets():
    ps = _postings()
    before = copy.deepcopy(ps)
    s = employer_boilerplate(ps, CFG)
    assert s["employers"] == {"example co": {"postings": 5, "repeated_sentences": 3}}
    assert s["sentences_removed"] == {"REPEATED": 15, "STATEMENT": 0} and s["postings_affected"] == 5
    for p, b in zip(ps, before):
        t = p["clean_description"]
        assert len(t) == len(b["clean_description"])  # every mention offset in the remaining text still holds
        assert ABOUT not in t and "make decisions" not in t and "Instagram" not in t
        start = b["clean_description"].index("You will build")
        assert t[start:start + 14] == "You will build"
        assert p["boilerplate_chars_removed"] > 0
    assert SHARED_REQ in ps[0]["clean_description"]  # requirement shared by 2 of 5 roles is job text


def test_small_employers_and_single_titles_keep_repeated_text():
    for ps in (_postings(n=4), _postings(titles=("Engineer",))):
        employer_boilerplate(ps, CFG)
        for p in ps:  # only the follow-us statement goes; the repeated about-us and values text stays
            t = p["clean_description"]
            assert ABOUT in t and VALUES in t and "Instagram" not in t


def test_switched_off_changes_nothing():
    for cfg in (None, dict(CFG, enabled=False)):
        ps = _postings()
        before = copy.deepcopy(ps)
        employer_boilerplate(ps, cfg)
        assert ps == before


def test_postings_of_other_employers_are_judged_separately():
    ps = _postings() + _postings(n=2, company="other co")
    for i, p in enumerate(ps[5:]):
        p["posting_uid"] = f"o{i}"
    employer_boilerplate(ps, CFG)
    assert all(ABOUT in p["clean_description"] for p in ps[5:])


def test_equal_opportunity_and_accommodation_statements_are_removed_in_any_posting():
    text = ("Build ETL jobs in Python and SQL.\nAccommodations may include changes to the application process or a "
            "sign language interpreter.\nWe are an equal opportunity employer.\nFollow Example on LinkedIn and X.")
    ps = [{"posting_uid": "s1", "company_key": "tiny co", "job_title": "Data Engineer", "clean_description": text}]
    s = employer_boilerplate(ps, CFG)
    t = ps[0]["clean_description"]
    assert t.startswith("Build ETL jobs in Python and SQL.") and len(t) == len(text)
    assert "sign language" not in t and "opportunity" not in t and "LinkedIn" not in t
    assert s["sentences_removed"] == {"REPEATED": 0, "STATEMENT": 3}


def test_job_lines_that_look_like_statements_are_kept():
    for line in ("Follow up on outstanding receivables with clients.", "Ability to follow through on commitments.",
                 "Give decisive feedback regardless of seniority.", "Coordinate travel and accommodation bookings."):
        ps = [{"posting_uid": "k", "company_key": "x", "job_title": "Analyst", "clean_description": line}]
        employer_boilerplate(ps, CFG)
        assert ps[0]["clean_description"] == line, line


def test_configured_rule():
    rule = load_config()["industry"]["employer_boilerplate"]
    assert rule["enabled"] is True
    assert {k: rule[k] for k in CFG if k != "enabled"} == {k: v for k, v in CFG.items() if k != "enabled"}
    assert rule["statements"] is True
