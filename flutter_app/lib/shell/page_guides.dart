import 'navigation.dart';

/// One page in plain words: what it shows, why it matters, the evidence behind it and what to do next. The page's own
/// headline says what was found; the guide frames it. Written for any curriculum and any institution.
class PageGuide {
  const PageGuide({required this.shows, required this.why, required this.evidence, required this.next, this.nextDest});
  final String shows;
  final String why;
  final String evidence;
  final String next;
  final Dest? nextDest;
}

const pageGuides = <Dest, PageGuide>{
  Dest.overview: PageGuide(
      shows: 'The main findings of the analysis in view, and where the evidence is strong or limited.',
      why: 'It is the shortest route from the evidence to a decision about the curriculum.',
      evidence: 'Every figure comes from the analysis run named in the top bar: the curriculum documents, the job postings and the skills reference used for it.',
      next: 'Open a finding to follow its evidence, or go to Skill-gap analysis for the full list.',
      nextDest: Dest.skillGaps),
  Dest.industryIntelligence: PageGuide(
      shows: 'Which skills the supplied job postings ask for, and how strongly.',
      why: 'Demand is one side of every skill gap: a skill matters here only when postings actually ask for it.',
      evidence: 'Job-posting files you supplied, read sentence by sentence and matched to the ESCO skills reference only when the context confirms the skill.',
      next: 'See how this demand compares with the curriculum on Skill-gap analysis.',
      nextDest: Dest.skillGaps),
  Dest.skillGaps: PageGuide(
      shows: 'Skills industry asks for, compared with how deeply the curriculum teaches them.',
      why: 'A confirmed gap is a skill with real demand that the curriculum does not teach, or teaches only in passing.',
      evidence: 'Demand from the job postings and coverage from the curriculum\'s own courses and topics; a gap is confirmed only when both are sufficient.',
      next: 'Open a gap to see its evidence, then review the related Recommendations.',
      nextDest: Dest.recommendations),
  Dest.courseDrift: PageGuide(
      shows: 'How courses changed between two versions of the same programme.',
      why: 'It shows whether the curriculum has moved with the field, and which courses were added, dropped or changed.',
      evidence: 'Courses of both versions in the semesters they share, matched by title and content.',
      next: 'Without an earlier version, add one under New analysis to see changes.',
      nextDest: Dest.ingestion),
  Dest.peers: PageGuide(
      shows: 'How the curriculum compares with the peer and reference curricula that were supplied.',
      why: 'It shows what comparable programmes teach that this one does not, and the reverse. There is no ranking or score.',
      evidence: 'Topics of each supplied curriculum, compared concept by concept. Only curricula you supplied (and chose, when you chose) are used, and only those of the same discipline.',
      next: 'Add more official peer curricula under New analysis to widen the comparison.',
      nextDest: Dest.ingestion),
  Dest.recommendations: PageGuide(
      shows: 'Suggested changes to the curriculum for the confirmed gaps, preferring existing courses over new ones.',
      why: 'These are considerations for the curriculum committee, never automatic decisions.',
      evidence: 'Each suggestion rests on a confirmed gap, the courses that already touch the skill and the demand behind it.',
      next: 'Check each suggestion\'s evidence before taking it to the committee.',
      nextDest: Dest.skillGaps),
  Dest.curriculumExplorer: PageGuide(
      shows: 'The courses, units and topics recognised in each curriculum document.',
      why: 'Everything else in the analysis is built on this reading of the curriculum, so it is worth checking.',
      evidence: 'The curriculum PDFs, page by page; every course and topic keeps the page it came from.',
      next: 'If a course is missing or garbled, review the extraction in Preprocessing preview.',
      nextDest: Dest.preprocessing),
  Dest.skillContext: PageGuide(
      shows: 'The skills found in the curriculum and the job postings, with their place in the ESCO skills reference.',
      why: 'A shared skills vocabulary lets the curriculum and industry be compared on the same terms.',
      evidence: 'Skill mentions with their original wording, matched to ESCO only when the context confirms the concept.',
      next: 'Open a skill to see where it is taught and where it is asked for.'),
  Dest.concepts: PageGuide(
      shows: 'Groups of related topics (concepts) discovered across the curricula.',
      why: 'Concepts let different wordings of the same idea be compared across versions and institutions.',
      evidence: 'Topics clustered by their wording within each course family; the grouping is inferred, not independently validated.',
      next: 'Use the Knowledge graph to see how a concept links to courses and skills.',
      nextDest: Dest.graph),
  Dest.occupations: PageGuide(
      shows: 'The occupations the job postings belong to.',
      why: 'It shows which roles the demand comes from, so a gap can be read in context.',
      evidence: 'Job titles checked against each posting\'s own skills and the ESCO occupation profiles.',
      next: 'See the skills these roles ask for under Industry.',
      nextDest: Dest.industryIntelligence),
  Dest.graph: PageGuide(
      shows: 'Courses, topics, concepts, skills and job postings, and the links between them.',
      why: 'It shows the full chain from a curriculum topic to the demand for a skill.',
      evidence: 'Only links the analysis derived from the documents; AI suggestions appear only when validated.',
      next: 'Search for a skill or course to start from it.'),
  Dest.ingestion: PageGuide(
      shows: 'Where new evidence enters: curricula, peer or reference curricula, reference documents and job postings.',
      why: 'An analysis is only as good as its evidence; every file is checked before it is used.',
      evidence: 'Your file. The required details identify it; values read from the document are offered for you to check.',
      next: 'After the upload, the analysis runs in the background; you can keep using the app.'),
  Dest.dataSources: PageGuide(
      shows: 'Every source evidence can come from, how it is accessed and under what licence.',
      why: 'It makes clear what the analysis may use and what it never collects by itself.',
      evidence: 'The source registry: listing a source never means the application may collect from it.',
      next: 'Add evidence you are permitted to use under New analysis.',
      nextDest: Dest.ingestion),
  Dest.evidenceStatus: PageGuide(
      shows: 'For each part of the analysis, whether the evidence it needs is available.',
      why: 'A part of the analysis without enough evidence is marked as such instead of showing guesses.',
      evidence: 'The analysis run\'s own requirement checks.',
      next: 'Add the missing evidence named here under New analysis.',
      nextDest: Dest.ingestion),
  Dest.semanticDecisions: PageGuide(
      shows: 'Interpretations suggested by the AI model, whether they were allowed to affect results, and how '
          'reviewers judged the validation questions.',
      why: 'AI is advisory here: its suggestions affect results only after they pass validation.',
      evidence: 'Each decision with the question asked, the model\'s answer and its validation status; each reviewer '
          'answer with the workbook cell it came from.',
      next: 'Review the decisions that are marked for review, and the questions where reviewers disagree.'),
  Dest.lineage: PageGuide(
      shows: 'The sources behind this analysis and how it relates to the analysis before it.',
      why: 'Every number can be traced back to a file, and every change between analyses is explained.',
      evidence: 'File hashes, the analysis run identifiers and what changed when the analysis was recomputed.',
      next: 'Open System health to see whether the analysis in view is complete.',
      nextDest: Dest.systemHealth),
  Dest.dataQuality: PageGuide(
      shows: 'The validation checks every document and the job postings passed or failed.',
      why: 'A failed check stops the affected results rather than letting them look trustworthy.',
      evidence: 'Per-document checks: readable text, recognised courses, titled courses, topic quality and traceability.',
      next: 'If a document failed, review its extraction in Preprocessing preview.',
      nextDest: Dest.preprocessing),
  Dest.gapReview: PageGuide(
      shows: 'An experimental second reading of the skill gaps, kept apart from the published results.',
      why: 'It is evaluated before it may replace the authoritative gap classification.',
      evidence: 'The same demand and coverage evidence, reasoned over with extra context.',
      next: 'Use Skill-gap analysis for the authoritative results.',
      nextDest: Dest.skillGaps),
  Dest.systemHealth: PageGuide(
      shows: 'Whether the analysis in view is complete, and which services are running.',
      why: 'It tells you how far the current results can be relied on.',
      evidence: 'The analysis run\'s health record and the live status of the application\'s services.',
      next: 'If something is limited, Evidence status names what is missing.',
      nextDest: Dest.evidenceStatus),
  Dest.agents: PageGuide(
      shows: 'The five analysis agents, what each is responsible for and whether its output exists for this analysis.',
      why: 'It shows how a curriculum is turned into recommendations, step by step.',
      evidence: 'Each agent\'s stored outputs for the analysis in view; nothing is recomputed here.',
      next: 'Follow an agent\'s output to the page that shows it.'),
  Dest.trends: PageGuide(
      shows: 'How demand for skills changed over the periods the job postings cover.',
      why: 'A rising skill may need attention before it becomes a gap.',
      evidence: 'Job postings grouped by period; a trend is shown only with enough periods.',
      next: 'Compare a rising skill with its coverage under Skill-gap analysis.',
      nextDest: Dest.skillGaps),
  Dest.industryDemand: PageGuide(
      shows: 'The full table of skill demand from the job postings.',
      why: 'It is the detailed basis of the Industry page.',
      evidence: 'Job postings, with each skill counted once per posting.',
      next: 'Return to Industry for the summary.',
      nextDest: Dest.industryIntelligence),
  Dest.coverage: PageGuide(
      shows: 'How deeply each in-demand skill is taught: absent, mentioned, introduced, substantial or advanced.',
      why: 'Depth, not just presence, decides whether a skill is really covered.',
      evidence: 'Where the skill appears in courses, units, topics and learning outcomes.',
      next: 'See the resulting gaps under Skill-gap analysis.',
      nextDest: Dest.skillGaps),
  Dest.curriculumDrift: PageGuide(
      shows: 'How concepts changed between two versions of the same programme.',
      why: 'It shows which ideas the programme added or dropped over time.',
      evidence: 'Concepts of both versions in the semesters they share.',
      next: 'Course-level changes are under Curriculum changes.',
      nextDest: Dest.courseDrift),
  Dest.topicHierarchy: PageGuide(
      shows: 'The topics of each course, arranged as the curriculum arranges them.',
      why: 'It is the finest level the analysis reads the curriculum at.',
      evidence: 'Topic lines read from the curriculum pages, with their page numbers.',
      next: 'Check a course\'s topics against the PDF if something looks wrong.'),
  Dest.evidenceTrace: PageGuide(
      shows: 'The full chain of evidence behind one skill or result.',
      why: 'It lets anyone check a result without trusting the summary.',
      evidence: 'Quoted curriculum lines and job-posting sentences, with their sources.',
      next: 'Enter a skill to trace it.'),
  Dest.aiEvaluation: PageGuide(
      shows: 'How the AI model\'s suggestions were evaluated against independent labels.',
      why: 'AI may affect results only after it is shown to be reliable on this kind of decision.',
      evidence: 'Frozen evaluation sets and their scores.',
      next: 'See the individual decisions under Semantic review.',
      nextDest: Dest.semanticDecisions),
  Dest.humanReview: PageGuide(
      shows: 'Items the analysis could not settle on its own, queued for a person.',
      why: 'A person\'s decision is recorded and reused, so uncertain items are never resolved by guessing.',
      evidence: 'Each item with the evidence that made it uncertain.',
      next: 'Record decisions where you have the expertise.'),
  Dest.contradictions: PageGuide(
      shows: 'Consistency checks over the knowledge graph.',
      why: 'Contradictory links would make results unreliable; they are listed so they can be fixed.',
      evidence: 'Automatic checks over every link in the graph.',
      next: 'Open the Knowledge graph to inspect a flagged link.',
      nextDest: Dest.graph),
  Dest.escoAudit: PageGuide(
      shows: 'How the ESCO skills reference was loaded and how much of it is available.',
      why: 'Skill matching is only as complete as the reference behind it.',
      evidence: 'The ESCO files supplied and the parts reconstructed from them.',
      next: 'See matched skills under Skills.',
      nextDest: Dest.skillContext),
  Dest.occupationsV1: PageGuide(
      shows: 'The occupation table behind the Occupations page.',
      why: 'It is the detailed basis of the occupation summary.',
      evidence: 'Job titles and ESCO occupation profiles.',
      next: 'Return to Occupations for the summary.',
      nextDest: Dest.occupations),
  Dest.preprocessing: PageGuide(
      shows: 'What was read from a document: raw text, cleaned text and the structured record.',
      why: 'If a result looks wrong, this is where to check whether the document was read correctly.',
      evidence: 'The uploaded file itself, before and after cleaning.',
      next: 'If the reading is wrong, upload a clearer copy under New analysis.',
      nextDest: Dest.ingestion),
  Dest.pipelineRuns: PageGuide(
      shows: 'Every ingestion run with its status and counts.',
      why: 'It records what was processed and when.',
      evidence: 'The application\'s run records.',
      next: 'Open a run to see its details.'),
  Dest.history: PageGuide(
      shows: 'Every analysis started in this workspace, with its state, when it ran and what it included.',
      why: 'It lets you return to an earlier analysis, or run one again that failed or needs review, without uploading again.',
      evidence: 'The analysis records the service keeps for each run; the published analysis itself is never changed by them.',
      next: 'Open a ready analysis to see its results, or start a new one.',
      nextDest: Dest.ingestion),
  Dest.assistant: PageGuide(
      shows: 'A conversation with a local AI assistant about the analysis, and the syllabus drafts it writes.',
      why: 'It answers questions in plain words and drafts course syllabi, programme structures and course revisions '
          'from the analysis evidence.',
      evidence: 'Every answer lists what it looked up; drafts cite their evidence, and anything uncited is marked as a '
          'model suggestion. Drafts are for faculty review, never analysis results.',
      next: 'Ask a question, or ask for a draft.'),
  Dest.settings: PageGuide(
      shows: 'Which disciplines this workspace can analyse, and with what evidence, plus this session\'s connection.',
      why: 'An analysis is only as good as the evidence of its own discipline; this page says plainly what is and is not available.',
      evidence: 'The discipline profiles and the evidence actually supplied: job postings listed for each discipline, and reference and peer curricula of the same discipline.',
      next: 'Supply the evidence a discipline lacks under New analysis.',
      nextDest: Dest.ingestion),
};
