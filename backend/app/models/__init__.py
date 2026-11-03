from app.models.data_source import DataSource, DataQualityMetric  # noqa: F401
from app.models.curriculum import (  # noqa: F401
    Institution,
    Discipline,
    Department,
    Programme,
    CurriculumVersion,
    Document,
    Course,
    Module,
    CurriculumTopic,
    CourseLearningOutcome,
)
from app.models.skills import (  # noqa: F401
    Skill,
    SkillAlias,
    SkillRelationship,
    SkillCrosswalk,
    SkillEmbedding,
)
from app.models.jobs import (  # noqa: F401
    Occupation,
    IndustryDomain,
    JobDiscipline,
    JobPosting,
    ExtractedSkill,
    JobSkillRelation,
    CurriculumSkillRelation,
    SkillDemand,
)
from app.models.core_knowledge import (  # noqa: F401
    CoreKnowledgeDomain,
    CoreTopic,
    CoreSubtopic,
    CoreKnowledgeSkillMapping,
    CurriculumTopicCoreTopicMapping,
)
from app.models.analysis import (  # noqa: F401
    AnalysisRun,
    IngestionRejection,
    AlignmentResult,
    CurriculumSkillCoverage,
    SkillAlignment,
    CurriculumSkillDrift,
    SkillGap,
    DriftResult,
    Recommendation,
)
