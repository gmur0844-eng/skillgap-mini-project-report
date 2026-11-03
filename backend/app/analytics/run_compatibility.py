"""
Run/evidence compatibility checking (hardening phase, per the limitation
flagged in the gap-classification report: "trend/drift integration uses
latest successful run without verifying it corresponds to the exact same
programme/population being classified").

Pure, deterministic, no DB. The caller (app.analytics.run_gap_classification)
builds the plain-dict `run_meta` inputs from real AnalysisRun rows
(specifically their `population_scope` field) and uses this module's verdict
to decide whether to attach an evidence dimension un-flagged, flagged, or
not at all -- it never re-derives compatibility itself, and this module
never invents scope information that isn't present.
"""

COMPATIBLE = "COMPATIBLE"
INCOMPATIBLE_SCOPE = "INCOMPATIBLE_SCOPE"
UNKNOWN_SCOPE = "UNKNOWN_SCOPE"
NO_RUN = "NO_RUN"


def check_dimension_compatibility(reference_scope, dimension_scope, dimension_run_exists):
    """
    reference_scope: the population_scope of the "base" evidence gap
        classification is built on (typically "global").
    dimension_scope: the population_scope of the OTHER evidence dimension
        being considered for attachment (e.g. a curriculum_drift run's
        "programme:<id>").
    dimension_run_exists: False if there is no run of that type at all
        (distinct from a run existing but having an unknown/NULL scope).

    Never guesses: two NULL/unknown scopes are NOT assumed compatible just
    because they're equally None -- an unknown scope is always
    UNKNOWN_SCOPE, never COMPATIBLE.
    """
    if not dimension_run_exists:
        return NO_RUN
    if reference_scope is None or dimension_scope is None:
        return UNKNOWN_SCOPE
    if reference_scope == dimension_scope:
        return COMPATIBLE
    return INCOMPATIBLE_SCOPE


def check_run_compatibility(reference_scope, dimensions):
    """
    dimensions: {dimension_name: {"scope": str|None, "exists": bool}, ...}
    Returns {dimension_name: verdict, ...}.
    """
    return {
        name: check_dimension_compatibility(reference_scope, info.get("scope"), info.get("exists", False))
        for name, info in dimensions.items()
    }
