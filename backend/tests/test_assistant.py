"""
The assistant: tools read the run correctly; actions wait for the user; figures in answers are checked; drafts keep
only real citations; revisions cannot remove topics the course does not have; the JSON fallback for models without
tool support. A synthetic run and a scripted model are used: no real data, no real model.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assistant import agent, llm, syllabus  # noqa: E402
from app.assistant import tools as tools_mod  # noqa: E402
from app.assistant.store import Store  # noqa: E402
from tests.assistant_fixture import ScriptedModel, call, load  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = load(self.tmp.name)
        self.store = Store(Path(self.tmp.name) / "assistant")

    def tearDown(self):
        self.tmp.cleanup()

    def ctx(self, model=None):
        c = tools_mod.Context(None, model, self.store)
        c._run = self.run
        return c


class Tools(_Base):
    def test_overview_counts_only_supported_unreviewed_partial_or_missing_gaps_as_confirmed(self):
        data = tools_mod.overview(self.ctx(), {})["data"]
        self.assertEqual([g["skill"] for g in data["confirmed_gaps"]], ["docker"])  # NoSQL is marked for review
        self.assertEqual(data["eligible_job_postings"], 200)
        self.assertEqual(data["recommendations"], 1)

    def test_explain_skill_and_unknown_skill(self):
        d = tools_mod.explain_skill(self.ctx(), {"skill": "Docker"})["data"]
        self.assertEqual((d["postings"], d["gap"], d["recommended"]), (31, "MISSING", True))
        with self.assertRaises(tools_mod.ToolError):
            tools_mod.explain_skill(self.ctx(), {"skill": "quantum basket weaving"})

    def test_search_and_course(self):
        hits = tools_mod.search_curriculum(self.ctx(), {"query": "docker containers", "role": "REFERENCE"})
        self.assertEqual(hits["data"][0]["course_code"], "PC10")
        course = tools_mod.get_course(self.ctx(), {"course_code": "cs301"})["data"][0]
        self.assertEqual(course["title"], "Database Systems")
        self.assertIn("relational model and SQL queries", course["units"]["Unit I"])


class Agent(_Base):
    def turn(self, replies, text="What are the gaps?", conv=None):
        model = ScriptedModel(replies)
        conv = conv or self.store.new_conversation()
        return agent.run_turn(conv, text, model, self.ctx(model)), conv, model

    def test_tool_then_grounded_answer(self):
        turn, conv, model = self.turn([call("analysis_overview"),
                                       "The confirmed gap is docker, asked for in 31 of 200 postings."])
        self.assertEqual(turn["tool_trace"][0]["tool"], "analysis_overview")
        self.assertEqual(turn["warnings"], [])
        self.assertIn("31 of 200", turn["reply"])
        self.assertEqual(model.calls[1]["messages"][-1]["role"], "tool")  # the result went back to the model
        self.assertEqual(conv["title"], "What are the gaps?")

    def test_an_invented_figure_is_flagged(self):
        turn, _, _ = self.turn([call("analysis_overview"), "Docker appears in 45% of postings."])
        self.assertTrue(any("45" in w for w in turn["warnings"]))

    def test_an_action_waits_for_confirmation_and_runs_only_when_approved(self):
        with mock.patch.object(tools_mod.analysis_jobs, "start_job",
                               return_value=({"job_id": "job-1", "status": "PENDING", "upload_id": "upl-1"}, None)) as start, \
             mock.patch.object(tools_mod.analysis_jobs, "upload", return_value={"file_name": "s.pdf", "metadata": {}}):
            turn, conv, _ = self.turn([call("start_analysis", upload_id="upl-000000000001")], "Analyse my upload")
            start.assert_not_called()  # the model's request alone never acts
            action = conv["pending_action"]
            self.assertEqual(turn["pending_action"]["id"], action["id"])
            self.assertIn("confirmation", turn["reply"])
            self.assertIsNone(agent.confirm_action(conv, "act-000000000000", True, self.ctx()))  # wrong id
            done = agent.confirm_action(conv, action["id"], True, self.ctx())
            start.assert_called_once()
            self.assertIn("job-1", done["reply"])
            self.assertIsNone(conv["pending_action"])

    def test_rejecting_or_moving_on_never_runs_the_action(self):
        with mock.patch.object(tools_mod.analysis_jobs, "start_job") as start, \
             mock.patch.object(tools_mod.analysis_jobs, "upload", return_value=None):
            _, conv, _ = self.turn([call("start_analysis", upload_id="upl-000000000001")])
            self.assertIn("Cancelled", agent.confirm_action(conv, conv["pending_action"]["id"], False, self.ctx())["reply"])
            _, conv, _ = self.turn([call("start_analysis", upload_id="upl-000000000001")])
            turn, _, _ = self.turn(["OK."], "never mind", conv)
            self.assertIsNone(conv["pending_action"])
            self.assertTrue(any("lapsed" in w for w in turn["warnings"]))
            start.assert_not_called()

    def test_unknown_tool_and_tool_errors_are_reported_to_the_model(self):
        turn, _, model = self.turn([call("delete_everything"), call("explain_skill", skill="nope"), "I could not find it."])
        self.assertEqual(turn["tool_trace"][0]["error"], "unknown tool")
        self.assertIn("ToolError", turn["tool_trace"][1]["error"])
        self.assertIn("error", model.calls[2]["messages"][-1]["content"])

    def test_model_unavailable_is_a_clear_error_not_a_reply(self):
        class Down:
            def chat(self, *a, **k):
                raise llm.ModelUnavailable("the model service could not be reached")
        conv = self.store.new_conversation()
        turn = agent.run_turn(conv, "hi", Down(), self.ctx())
        self.assertEqual(turn["error"]["code"], "MODEL_UNAVAILABLE")
        self.assertEqual(turn["reply"], "")


COURSE = {
    "title": "Cloud and Containers", "description": "Containers in practice.",
    "objectives": ["Deploy services with containers"], "prerequisites": ["Operating systems"],
    "units": [{"title": "Containers", "hours": 9, "topics": [
        {"text": "Docker images and containers", "evidence": ["D1", "R1"]},
        {"text": "A topic the model made up", "evidence": []},
        {"text": "Orchestration", "evidence": ["Z9"]}]},
        {"title": "Data stores", "hours": 6, "topics": [{"text": "Document databases", "evidence": ["R2"]}]}],
    "outcomes": ["Build a containerised service"], "lab_experiments": ["Containerise a web app"],
    "assessment": ["Lab record"], "reading": [{"title": "A Book That May Not Exist", "authors": "Someone"}]}


class Drafting(_Base):
    def test_course_draft_keeps_only_real_citations_and_labels_suggestions(self):
        d = syllabus.draft_course(ScriptedModel([COURSE]), self.run, "Cloud and Containers", ["docker", "SQL", "NoSQL"])
        ev = d["evidence"]
        self.assertEqual(ev["R2"]["text"], "NoSQL databases and document stores")
        self.assertEqual(ev["D1"]["skill"], "SQL")  # most demanded first
        topics = [t for u in d["content"]["units"] for t in u["topics"]]
        self.assertEqual([t["basis"] for t in topics], ["EVIDENCE", "MODEL_SUGGESTION", "MODEL_SUGGESTION", "EVIDENCE"])
        self.assertEqual(d["checks"]["unknown_evidence_ids_removed"], ["Z9"])
        self.assertEqual(d["checks"]["total_hours"], 15)  # computed here, not taken from the model
        self.assertEqual(d["content"]["reading"][0]["status"], syllabus.READING_NOTE)
        self.assertIn("faculty", d["label"])
        md = syllabus.to_markdown({**d, "created_at": "today"})
        self.assertIn("*(model suggestion)*", md)
        self.assertIn("## Evidence", md)

    def test_skills_addressed_are_computed_from_citations(self):
        d = syllabus.draft_course(ScriptedModel([COURSE]), self.run, "Containers", ["docker", "SQL"])
        by_id = {e["skill"]: i for i, e in d["evidence"].items() if e["type"] == "industry_demand"}
        cited = {i for u in d["content"]["units"] for t in u["topics"] for i in t["evidence"]}
        self.assertEqual(set(d["checks"]["skills_addressed"]), {s for s, i in by_id.items() if i in cited})

    def test_invalid_model_output_is_retried_then_refused(self):
        with self.assertRaises(syllabus.DraftError):
            syllabus.draft_course(ScriptedModel(["not json", "{}"]), self.run, "X", [])
        d = syllabus.draft_course(ScriptedModel(["not json", COURSE]), self.run, "X", ["docker"])
        self.assertEqual(d["content"]["title"], "Cloud and Containers")

    def test_revision_cannot_touch_topics_the_course_does_not_have(self):
        rev = {"summary": "Modernise", "add": [{"topic": "NoSQL document stores", "unit": "Unit III", "reason": "demand",
                                                "evidence": ["D1"]}],
               "update": [{"from": "Punch cards", "to": "Cloud databases", "reason": "obsolete", "evidence": []},
                          {"from": "a topic that is not there", "to": "x", "reason": "y", "evidence": []}],
               "remove": [{"topic": "relational model and SQL queries", "reason": "?", "evidence": []},
                          {"topic": "invented topic", "reason": "?", "evidence": []}]}
        d = syllabus.draft_revision(ScriptedModel([rev]), self.run, "CS301")
        c = d["content"]
        self.assertEqual(c["update"][0]["from"], "punch cards")  # matched to the real topic text
        self.assertEqual(len(c["update"]), 1)
        self.assertEqual([r["topic"] for r in c["remove"]], ["relational model and SQL queries"])
        self.assertEqual(sorted(r["topic"] for r in d["checks"]["rejected_changes"]),
                         ["a topic that is not there", "invented topic"])
        with self.assertRaises(syllabus.DraftError):
            syllabus.draft_revision(ScriptedModel([rev]), self.run, "NOPE1")

    def test_programme_semesters_are_validated_and_totalled(self):
        prog = {"title": "B.Tech", "semesters": [
            {"number": 1, "courses": [{"title": "Data Structures", "credits": 4, "evidence": ["C2"]},
                                      {"title": "Docker Lab", "credits": 2, "evidence": ["D1"]}]},
            {"number": 1, "courses": [{"title": "duplicate semester", "credits": 3, "evidence": []}]},
            {"number": 12, "courses": [{"title": "out of range", "credits": 3, "evidence": []}]},
            {"number": 2, "courses": [{"title": "Cloud", "credits": "3", "evidence": ["C1", "Q7"]}]}]}
        d = syllabus.draft_programme(ScriptedModel([prog]), self.run, "CSE")
        self.assertEqual([s["number"] for s in d["content"]["semesters"]], [1, 2])
        self.assertEqual(d["checks"]["total_credits"], 9)
        self.assertEqual(d["checks"]["unknown_evidence_ids_removed"], ["Q7"])

    def test_draft_tool_saves_the_draft(self):
        model = ScriptedModel([call("draft_course_syllabus", title="Containers", skills=["docker"]), COURSE,
                               "I drafted it: an AI-generated draft for faculty review."])
        conv = self.store.new_conversation()
        turn = agent.run_turn(conv, "Draft a course for the docker gap", model, self.ctx(model))
        self.assertEqual(len(turn["draft_ids"]), 1)
        self.assertEqual(self.store.draft(turn["draft_ids"][0])["kind"], "course")
        self.assertEqual(self.store.drafts()[0]["id"], turn["draft_ids"][0])


class Resources(_Base):
    def setUp(self):
        super().setUp()
        from app.assistant import resources
        self.res = resources
        patch = mock.patch.object(resources, "BRONZE", Path(self.tmp.name) / "bronze")
        patch.start()
        self.addCleanup(patch.stop)
        resources._pages.cache_clear()
        self.addCleanup(resources._pages.cache_clear)

    def test_books_and_links_are_read_from_the_course_pages(self):
        found = self.res.course_resources(self.run, self.run.courses["c:ref1"])
        books = [f["text"] for f in found if f["type"] == "book"]
        self.assertEqual(books, ["A. Author, Cloud Computing Concepts, Pearson, 2019",
                                 "B. Writer and C. Writer, Containers in Practice, 2nd Edition, Manning, 2021"])
        self.assertIn("https://docs.docker.com/get-started/", [f["url"] for f in found if f["type"] == "web_link"])
        self.assertTrue(all(f["status"] == "LISTED_IN_CURRICULUM" and f["page"] == 2 for f in found))

    def test_resource_draft_uses_evidence_titles_and_removes_dead_links(self):
        ev = syllabus.resource_evidence(self.run, "cloud computing docker containers", ["docker"])
        book = next(i for i, e in ev.items() if e["type"] == "book")
        curated = next(i for i, e in ev.items() if e["type"] == "curated_resource")
        reply = {"summary": "s", "items": [
            {"title": "the model's garbled title", "evidence": [book], "use": "main text"},
            {"title": "x", "evidence": [curated]},
            {"kind": "book", "title": "Invented Book", "authors": "Nobody", "evidence": []},
            {"kind": "website", "title": "Dead site", "url": "https://no-such-site.example/x", "evidence": []},
            {"title": "duplicate", "evidence": [book]}]}

        def link(url, timeout=6):
            return {"check": "LINK_NOT_FOUND" if "no-such-site" in url else "LINK_OK"}
        with mock.patch.object(self.res, "check_link", side_effect=link), \
             mock.patch.object(self.res, "check_book", return_value={"check": "NOT_FOUND_IN_OPEN_LIBRARY"}):
            d = syllabus.draft_resources(ScriptedModel([reply]), self.run, "Cloud Computing", ["docker"])
        items = d["content"]["items"]
        self.assertEqual(items[0]["title"], ev[book]["text"])  # the curriculum's text, not the model's
        self.assertEqual(items[0]["status"], "LISTED_IN_CURRICULUM")
        self.assertEqual(items[1]["status"], "CURATED")
        invented = next(i for i in items if i["title"] == "Invented Book")
        self.assertEqual((invented["status"], invented["check"]["check"]), ("MODEL_SUGGESTION", "NOT_FOUND_IN_OPEN_LIBRARY"))
        self.assertEqual(d["checks"]["removed_links_not_found"], ["https://no-such-site.example/x"])
        self.assertEqual(len(items), 3)  # duplicate and dead link gone
        self.assertIn("not found in Open Library", syllabus.to_markdown({**d, "created_at": ""}))

    def test_checks_can_be_switched_off(self):
        with mock.patch.dict("os.environ", {"RESOURCE_CHECK": "off"}):
            self.assertEqual(self.res.check_link("https://example.org")["check"], "NOT_CHECKED")
            self.assertEqual(self.res.check_book("Anything")["check"], "NOT_CHECKED")
        self.assertEqual(self.res.check_link("not a url")["check"], "LINK_NOT_FOUND")


class LessonPlan(_Base):
    def test_sessions_are_renumbered_and_coverage_is_computed(self):
        plan = {"sessions": [
            {"title": "Relational model", "covers": ["S1", "S9"], "objectives": ["explain relations"],
             "activities": ["lecture", "group work"], "resources": ["W1", "a textbook chapter"], "assessment": "quiz",
             "minutes": 50},
            {"title": "", "covers": ["S2"]},
            {"title": "Normalisation", "covers": ["S2"], "minutes": "abc"}]}
        with mock.patch.dict("os.environ", {"RESOURCE_CHECK": "off"}):
            d = syllabus.draft_lesson_plan(ScriptedModel([plan]), self.run, "CS301", minutes=55)
        s = d["content"]["sessions"]
        self.assertEqual([x["number"] for x in s], [1, 2])
        self.assertEqual(s[0]["topics"], ["relational model and SQL queries"])
        self.assertEqual(s[1]["minutes"], 55)
        self.assertEqual(d["checks"]["topics_not_covered"], ["punch cards"])
        self.assertEqual(d["checks"]["unknown_evidence_ids_removed"], ["S9"])
        self.assertEqual([r["status"] for r in s[0]["resources"]], ["CURATED", "MODEL_SUGGESTION"])
        self.assertIn("## Session 2: Normalisation", syllabus.to_markdown({**d, "created_at": ""}))

    def test_from_a_course_draft(self):
        source = {"title": "Containers", "units": [{"title": "U1", "topics": [{"text": "images"}, {"text": "volumes"}]}]}
        plan = {"sessions": [{"title": "All of it", "covers": ["S1", "S2"]}]}
        with mock.patch.dict("os.environ", {"RESOURCE_CHECK": "off"}):
            d = syllabus.draft_lesson_plan(ScriptedModel([plan]), self.run, source=source)
        self.assertEqual(d["checks"]["topics_not_covered"], [])
        with self.assertRaises(syllabus.DraftError):
            syllabus.draft_lesson_plan(ScriptedModel([plan]), self.run, "NOPE")


class Relevance(_Base):
    def test_labels(self):
        from app.assistant.relevance import classify
        self.assertEqual(classify({"reuse_level": "transversal"}, None, "cse")["relevance"], "PROFESSIONAL_PRACTICE")
        self.assertEqual(classify({"top_skill_groups": ["information and communication technologies (icts)",
                                                        "knowledge"]}, None, "cse")["relevance"], "CORE_CONTENT")
        self.assertEqual(classify({"top_skill_groups": ["business, administration and law", "knowledge"]}, None,
                                  "cse")["relevance"], "OTHER_FIELD")
        self.assertEqual(classify({"top_skill_groups": ["natural sciences, mathematics and statistics"]}, None,
                                  "cse")["relevance"], "SUPPORTING_CONTENT")
        self.assertEqual(classify({"top_skill_groups": ["natural sciences, mathematics and statistics"]}, None,
                                  "aids")["relevance"], "CORE_CONTENT")
        self.assertEqual(classify({"top_skill_groups": ["management skills", "skills"]}, None, "cse")["relevance"],
                         "PROFESSIONAL_PRACTICE")
        self.assertEqual(classify(None, {"skill_category": "TECHNOLOGY_TOOL"}, "cse")["relevance"], "CORE_CONTENT")
        self.assertEqual(classify(None, {}, "cse")["relevance"], "UNCLASSIFIED")

    def test_tools_and_drafts_carry_the_label(self):
        gaps = tools_mod.skill_gaps(self.ctx(), {"limit": 10})["data"]["items"]
        self.assertTrue(all("syllabus_relevance" in g for g in gaps))
        ev = syllabus.demand_evidence(self.run, ["docker"])
        self.assertIn("syllabus_relevance", ev[0])


class JsonProtocol(unittest.TestCase):
    def test_extract_json_from_fenced_or_chatty_replies(self):
        self.assertEqual(llm._extract_json('Sure! ```json\n{"a": {"b": "}"}}\n```'), {"a": {"b": "}"}})
        self.assertEqual(llm._extract_json('noise {"tool": "x", "arguments": {}} trailing'), {"tool": "x", "arguments": {}})
        with self.assertRaises(ValueError):
            llm._extract_json("no json here")

    def test_a_model_without_tool_support_falls_back_to_the_json_protocol(self):
        m = llm.OllamaChat(base_url="http://127.0.0.1:9", model="m")
        replies = [llm.ModelUnavailable('HTTP 400: {"error":"m does not support tools"}'),
                   {"message": {"content": '{"tool": "explain_skill", "arguments": {"skill": "docker"}}'}}]

        def fake(path, payload=None, timeout=None):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(m, "_request", side_effect=fake):
            out = m.chat([{"role": "user", "content": "docker?"}], tools=[{"name": "explain_skill", "description": "d",
                                                                         "parameters": {}}])
        self.assertFalse(m.native_tools)
        self.assertEqual(out["tool_calls"], [{"name": "explain_skill", "arguments": {"skill": "docker"}}])

    def test_status_never_raises(self):
        s = llm.OllamaChat(base_url="http://127.0.0.1:9", model="m").status()
        self.assertEqual((s["service"], s["installed"]), ("UNREACHABLE", False))


class Api(_Base):
    def setUp(self):
        super().setUp()
        try:
            from fastapi.testclient import TestClient
            from app.api.v1 import assistant_api
            from app.main import app
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"FastAPI not available: {exc}") from exc
        from app.services import knowledge_service as ks
        gold = Path(self.tmp.name) / "gold"
        patches = [mock.patch.object(ks, "GOLD_ROOT", gold), mock.patch.object(ks, "SILVER_ROOT", Path(self.tmp.name) / "silver"),
                   mock.patch.object(assistant_api, "store", self.store)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        ks.load_run.cache_clear()
        self.addCleanup(ks.load_run.cache_clear)
        self.api = assistant_api
        self.client = TestClient(app)

    def test_conversation_round_trip_and_draft_markdown(self):
        model = ScriptedModel([call("analysis_overview"), "docker is the confirmed gap (31 postings).",
                               COURSE])
        with mock.patch.object(self.api, "model_factory", lambda: model):
            conv = self.client.post("/api/v1/assistant/conversations", json={}).json()
            r = self.client.post(f"/api/v1/assistant/conversations/{conv['id']}/messages", json={"text": "gaps?"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["turn"]["warnings"], [])
            self.assertEqual(len(self.client.get(f"/api/v1/assistant/conversations/{conv['id']}").json()["turns"]), 1)
            d = self.client.post("/api/v1/assistant/drafts", json={"kind": "course", "title": "Containers",
                                                                    "skills": ["docker"]})
            self.assertEqual(d.status_code, 200, d.text)
            md = self.client.get(f"/api/v1/assistant/drafts/{d.json()['id']}/markdown")
            self.assertIn("AI-generated draft", md.text)
        self.assertEqual(self.client.post("/api/v1/assistant/drafts", json={"kind": "poem"}).json()["code"], "INVALID_KIND")
        self.assertEqual(self.client.get("/api/v1/assistant/conversations/conv-000000000000").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/assistant/drafts/../../etc").status_code, 404)

    def test_status_reports_how_to_fix_when_the_model_is_missing(self):
        with mock.patch.object(self.api, "model_factory", lambda: llm.OllamaChat(base_url="http://127.0.0.1:9", model="m")):
            s = self.client.get("/api/v1/assistant/status").json()
        self.assertFalse(s["ready"])
        self.assertIn("ollama pull m", s["how_to_fix"])


if __name__ == "__main__":
    unittest.main()
