"""Temporal + industry intelligence v2. Multi-period data here is a synthetic TEST fixture only; product outputs
are computed from supplied postings and never from fixtures."""
import unittest

from app.knowledge_engine import industry_intel as ii

SETTINGS = {"min_periods_for_trend": 2, "min_eligible_postings_per_period": 30, "min_skill_postings_for_trend": 5}
TCFG = {"min_pp_change": 5.0, "min_relative_change": 0.25, "persistent_min_pct": 10.0, "require_monotonic": True,
        "segment_dimensions": ["seniority"]}
SKILLS = {k: {"label": k.upper(), "eligible_for_analytics": True} for k in ("a", "b", "c", "d", "e")}


def postings(period_dates, per_period, source="s1", extra=None):
    out = []
    for d in period_dates:
        for i in range(per_period):
            out.append({"posting_uid": f"p:{d}:{source}:{i}", "posted_date": d, "source_id": source, "country_code": "IN",
                        "source_file": f"{source}.xlsx", **(extra(i) if extra else {})})
    return out


class Periods(unittest.TestCase):
    def test_period_keys(self):
        self.assertEqual(ii.period_key("2026-09-22", "month"), "2026-09")
        self.assertEqual(ii.period_key("2026-09-22", "quarter"), "2026-Q3")
        self.assertEqual(ii.period_key("2026-09-22", "week"), "2026-W39")
        self.assertEqual(ii.period_key(None, "month"), ii.UNDATED)
        self.assertEqual(ii.period_key("22/09/2026", "month"), ii.UNDATED)

    def test_single_period_never_qualifies(self):
        chosen, ev = ii.evaluate_granularities(postings(["2026-09-22"], 100), SETTINGS)
        self.assertIsNone(chosen)
        self.assertFalse(any(g["qualifies"] for g in ev.values()))

    def test_finest_qualifying_granularity_is_chosen(self):
        chosen, ev = ii.evaluate_granularities(postings(["2026-09-01", "2026-09-15"], 40), SETTINGS)
        self.assertEqual(chosen, "week")
        chosen, _ = ii.evaluate_granularities(postings(["2026-07-01", "2026-09-15"], 40), SETTINGS)
        self.assertEqual(chosen, "week")
        small = postings(["2026-09-01", "2026-09-02", "2026-09-15", "2026-09-16"], 16)
        chosen, ev = ii.evaluate_granularities(small, SETTINGS)
        self.assertEqual(chosen, "week")  # two weeks of 32


class TrendStates(unittest.TestCase):
    def s(self, *pairs):
        return [(f"P{i}", c, d) for i, (c, d) in enumerate(pairs)]

    def test_states(self):
        c = lambda *p: ii.classify_trend(self.s(*p), sum(x for x, _ in p), SETTINGS, TCFG)[0]  # noqa: E731
        self.assertEqual(c((5, 50), (15, 50)), "TRENDING_UP")
        self.assertEqual(c((15, 50), (5, 50)), "TRENDING_DOWN")
        self.assertEqual(c((0, 50), (8, 50)), "EMERGING")
        self.assertEqual(c((8, 50), (0, 50)), "DECLINING")
        self.assertEqual(c((10, 50), (11, 50)), "PERSISTENT")
        self.assertEqual(c((3, 50), (4, 50)), "STABLE")
        self.assertEqual(c((5, 50), (15, 50), (8, 50), (16, 50)), "INSUFFICIENT_DATA")  # direction not consistent

    def test_gates(self):
        self.assertEqual(ii.classify_trend(self.s((1, 50)), 1, SETTINGS, TCFG)[0], "INSUFFICIENT_DATA")
        self.assertEqual(ii.classify_trend(self.s((1, 50), (3, 50)), 4, SETTINGS, TCFG)[0], "INSUFFICIENT_DATA")


class Populations(unittest.TestCase):
    def test_one_period_reports_what_is_missing_and_no_trend(self):
        ps = postings(["2026-09-22"], 100)
        pairs = {("a", p["posting_uid"]) for p in ps[:20]}
        scope, rows = ii.population_trends("POP", ps, pairs, SKILLS, {}, SETTINGS, TCFG)
        self.assertEqual(scope["trend_status"], "INSUFFICIENT_DATA")
        self.assertIn("required", scope["missing"])
        self.assertTrue(all(r["trend_state"] == "INSUFFICIENT_DATA" for r in rows))

    def test_two_periods_expose_both_denominators(self):
        ps = postings(["2026-08-03", "2026-09-07"], 50)
        aug = [p for p in ps if p["posted_date"].startswith("2026-08")]
        sep = [p for p in ps if p["posted_date"].startswith("2026-09")]
        pairs = {("a", p["posting_uid"]) for p in aug[:5]} | {("a", p["posting_uid"]) for p in sep[:15]}
        scope, rows = ii.population_trends("POP", ps, pairs, SKILLS, {}, SETTINGS, TCFG)
        self.assertEqual(scope["trend_status"], "COMPUTED")
        r = rows[0]
        self.assertEqual(r["trend_state"], "TRENDING_UP")
        self.assertEqual([(p["posting_count"], p["eligible_postings"]) for p in r["periods"]], [(5, 50), (15, 50)])
        self.assertIn("POP", r["statement"])

    def test_zero_is_absent_not_missing(self):
        ps = postings(["2026-08-03", "2026-09-07"], 50)
        sep = [p for p in ps if p["posted_date"].startswith("2026-09")]
        pairs = {("b", p["posting_uid"]) for p in sep[:10]}
        _, rows = ii.population_trends("POP", ps, pairs, SKILLS, {}, SETTINGS, TCFG)
        self.assertEqual(rows[0]["periods"][0]["posting_count"], 0)
        self.assertEqual(rows[0]["periods"][0]["demand_pct"], 0.0)
        self.assertEqual(rows[0]["trend_state"], "EMERGING")

    def test_populations_are_never_merged(self):
        a = postings(["2026-08-03"], 40, source="s1")
        b = postings(["2026-09-07"], 40, source="s2")
        sources = {"s1": {"population_id": "POP_A"}, "s2": {"population_id": "POP_B"}}
        extraction = {"skills": SKILLS, "posting_mentions": []}
        cfg = {"industry_v2": {"temporal": TCFG, "min_group_postings": 10, "top_n": 5,
                               "clusters": {"min_skill_postings": 3, "min_cooccurring_postings": 3, "min_lift": 2.0}}}
        out = ii.run(a + b, extraction, sources, SETTINGS, cfg, {}, "r")
        self.assertEqual(out["populations"], ["POP_A", "POP_B"])
        self.assertTrue(all(p["trend_status"] == "INSUFFICIENT_DATA" for p in out["temporal"]["populations"]))


class Dimensions(unittest.TestCase):
    def test_small_groups_are_not_ranked_and_missing_fields_are_reported(self):
        ps = postings(["2026-09-22"], 12, extra=lambda i: {"seniority": "entry" if i < 10 else "senior",
                                                           "location": "Pune, Maharashtra, India"})
        pairs = {("a", p["posting_uid"]) for p in ps}
        dims = ii.dimension_demand(ps, pairs, {}, SKILLS, {}, 10, 5)
        groups = {g["value"]: g for g in dims["seniority"]["groups"]}
        self.assertEqual(groups["entry"]["evidence_state"], "SUFFICIENT")
        self.assertEqual(groups["senior"]["evidence_state"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(dims["industry_domain"]["status"], "DATA_NOT_AVAILABLE")
        self.assertEqual(dims["location_region"]["groups"][0]["value"], "Maharashtra")

    def test_mentions_are_not_demand(self):
        mentions = [{"skill_key": "a"}] * 5 + [{"skill_key": "b"}]
        rows = ii.mention_vs_postings(mentions, {("a", "p1"), ("b", "p2")}, SKILLS)
        a = next(r for r in rows if r["skill_key"] == "a")
        self.assertEqual((a["mention_count"], a["distinct_postings"]), (5, 1))


class Clusters(unittest.TestCase):
    def test_cooccurrence_clusters_are_association_only(self):
        pairs = set()
        for i in range(4):
            pairs |= {("a", f"p{i}"), ("b", f"p{i}")}
        for i in range(4, 20):
            pairs |= {("c", f"p{i}")}
        pairs |= {("c", "p0")}
        out = ii.skill_clusters(pairs, SKILLS, 20, {"min_skill_postings": 3, "min_cooccurring_postings": 3, "min_lift": 2.0})
        self.assertEqual(len(out["clusters"]), 1)
        self.assertEqual({m["skill_key"] for m in out["clusters"][0]["members"]}, {"a", "b"})
        self.assertEqual(out["clusters"][0]["relationship"], "CO_OCCURS_IN_POSTINGS")


if __name__ == "__main__":
    unittest.main()
