"""
Curriculum version comparison / drift (spec Section 8/9). All statuses are
purely DESCRIPTIVE ("this changed") -- never interpreted as good/bad, never
labeled "outdated" automatically. Caller resolves None-vs-zero for
previous/current coverage BEFORE calling this (via
app.analytics.skill_set_alignment.resolve_evidence_value), same as the
industry-vs-curriculum alignment logic -- this module never guesses that.
"""

STATUS_SKILL_ADDED = "SKILL_ADDED"
STATUS_SKILL_REMOVED = "SKILL_REMOVED"
STATUS_COVERAGE_INCREASED = "COVERAGE_INCREASED"
STATUS_COVERAGE_DECREASED = "COVERAGE_DECREASED"
STATUS_UNCHANGED = "UNCHANGED"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def compare_curriculum_versions(previous_coverage: dict, current_coverage: dict) -> dict:
    """
    previous_coverage / current_coverage: {skill_id: percentage_or_None}.
    A value of None here must already mean "no curriculum evidence at all
    for this version" (resolved by the caller) -- NOT "not yet resolved".

    Returns {skill_id: {"previous_coverage": .., "current_coverage": .., "absolute_change": .., "status": ..}}
    """
    all_skill_ids = set(previous_coverage) | set(current_coverage)
    results = {}
    for skill_id in all_skill_ids:
        prev = previous_coverage.get(skill_id)
        curr = current_coverage.get(skill_id)

        if prev is None and curr is None:
            status = STATUS_INSUFFICIENT_DATA
        elif prev is None:
            status = STATUS_SKILL_ADDED
        elif curr is None:
            status = STATUS_SKILL_REMOVED
        else:
            change = curr - prev
            if change > 0:
                status = STATUS_COVERAGE_INCREASED
            elif change < 0:
                status = STATUS_COVERAGE_DECREASED
            else:
                status = STATUS_UNCHANGED

        absolute_change = (curr - prev) if (prev is not None and curr is not None) else None
        results[skill_id] = {
            "previous_coverage": prev,
            "current_coverage": curr,
            "absolute_change": round(absolute_change, 4) if absolute_change is not None else None,
            "status": status,
        }
    return results


def compare_courses(previous_course_codes: set, current_course_codes: set) -> dict:
    """Courses identified by course_code, matched across two versions of the same programme."""
    return {
        "added": current_course_codes - previous_course_codes,
        "removed": previous_course_codes - current_course_codes,
        "unchanged": previous_course_codes & current_course_codes,
    }


def compare_course_skills(previous_course_skills: dict, current_course_skills: dict) -> dict:
    """
    previous_course_skills / current_course_skills: {course_code: set(skill_id)}.
    Only meaningful for courses present in BOTH versions (a course that was
    itself added/removed is reported by compare_courses, not here).

    Returns {course_code: {"added": set(skill_id), "removed": set(skill_id)}}
    for every course_code present in both inputs.
    """
    common_courses = set(previous_course_skills) & set(current_course_skills)
    results = {}
    for course_code in common_courses:
        prev_skills = previous_course_skills.get(course_code, set())
        curr_skills = current_course_skills.get(course_code, set())
        results[course_code] = {
            "added": curr_skills - prev_skills,
            "removed": prev_skills - curr_skills,
        }
    return results
