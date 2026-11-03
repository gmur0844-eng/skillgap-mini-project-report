"""
Curriculum Knowledge Engine -- subject-agnostic.

RAW (hashed PDFs) -> BRONZE (per-page text, cached by document hash)
-> SILVER (courses / units / topics with provenance; noise and malformed
records quarantined, never deleted) -> HEALTH GATE -> GOLD (concept
families, concepts, relationships, reference mappings, concept drift, skill
candidates, review queue, evidence) -> optional PUBLISH (PostgreSQL).

Nothing in this package names a subject, discipline or institution.
Discipline, programme and institution arrive as DATA from the source
manifest and are used only as scoping context.
"""
PIPELINE_VERSION = "knowledge-engine-2.0.0"
