"""
Curriculum coverage: OBSERVED DATA from real curriculum ExtractedSkill
evidence.

coverage_percentage = courses_with_skill / eligible_courses * 100

Per spec: a skill mentioned 5 times in one course counts that course ONCE.
Pure (no DB) -- the caller resolves each mention's owning course_id (a
CurriculumTopic-sourced mention's course is found via its module; a
CourseLearningOutcome-sourced mention's course is its own course_id) and
passes plain dicts in.
"""


def compute_curriculum_coverage(
    mentions: list[dict],
    eligible_course_ids: set,
) -> dict:
    """
    mentions: [{"course_id": int, "normalized_skill_id": int,
                 "mention_source": "course_title"|"curriculum_topic"|"course_learning_outcome",
                 "source_record_id": int}, ...]
        -- course_id must already be resolved to the OWNING course for every
        mention, regardless of whether it came from a topic, an outcome, or
        the course title itself. source_record_id is the specific
        CurriculumTopic.id / CourseLearningOutcome.id (used to dedupe "5
        mentions in one topic" down to "1 topic", the same principle applied
        at the course level). Pass only MAPPED mentions.
    eligible_course_ids: the exact denominator population (e.g. all courses
        in the programme/institution being analyzed). Never invented here.

    Returns {skill_id: {"courses_with_skill": int, "eligible_courses": int,
                         "coverage_percentage": float,
                         "topics_with_skill": int, "outcomes_with_skill": int}}
    """
    total_courses = len(eligible_course_ids)

    relevant = [m for m in mentions if m.get("normalized_skill_id") is not None and m.get("course_id") in eligible_course_ids]

    course_pairs_by_skill: dict = {}
    topic_pairs_by_skill: dict = {}
    outcome_pairs_by_skill: dict = {}

    for m in relevant:
        skill_id = m["normalized_skill_id"]
        course_pairs_by_skill.setdefault(skill_id, set()).add(m["course_id"])
        if m.get("mention_source") == "curriculum_topic" and m.get("source_record_id") is not None:
            topic_pairs_by_skill.setdefault(skill_id, set()).add(m["source_record_id"])
        elif m.get("mention_source") == "course_learning_outcome" and m.get("source_record_id") is not None:
            outcome_pairs_by_skill.setdefault(skill_id, set()).add(m["source_record_id"])

    result = {}
    for skill_id, course_ids in course_pairs_by_skill.items():
        count = len(course_ids)
        result[skill_id] = {
            "courses_with_skill": count,
            "eligible_courses": total_courses,
            "coverage_percentage": round(count / total_courses * 100, 2) if total_courses else None,
            "topics_with_skill": len(topic_pairs_by_skill.get(skill_id, set())),
            "outcomes_with_skill": len(outcome_pairs_by_skill.get(skill_id, set())),
        }
    return result
