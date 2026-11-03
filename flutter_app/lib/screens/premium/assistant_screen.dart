import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/api_client.dart';
import '../../theme/design_system.dart';
import '../../widgets/ui_kit.dart';

/// The assistant: ask about the analysis, start analyses (after confirming), and draft syllabi. Answers come from the
/// analysis data through the backend's tools (shown under each answer); drafts are AI-generated and for faculty review.
class AssistantScreen extends StatefulWidget {
  const AssistantScreen({super.key, required this.api});
  final ApiClient api;

  static const suggestions = [
    'What are the confirmed skill gaps?',
    'Draft a course syllabus that covers the confirmed gaps',
    'Propose a revision of one of our courses',
    'Draft an 8-semester programme structure',
    'Make a lesson plan for one of our courses',
    'Find books, websites and YouTube channels for a course',
  ];

  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  int _tab = 0;
  Map<String, dynamic>? _status;
  Map<String, dynamic>? _conv;
  List<Map<String, dynamic>> _convs = [];
  List<Map<String, dynamic>> _drafts = [];
  Map<String, dynamic>? _draft;
  bool _busy = false;
  Object? _error;
  final _input = TextEditingController();

  ApiClient get api => widget.api;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final s = asMap(await api.getJson('/api/v1/assistant/status'));
      final c = asList(asMap(await api.getJson('/api/v1/assistant/conversations'))['items']).map(asMap).toList();
      final d = asList(asMap(await api.getJson('/api/v1/assistant/drafts'))['items']).map(asMap).toList();
      if (!mounted) return;
      setState(() {
        _status = s;
        _convs = c;
        _drafts = d;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _open(String id) async {
    try {
      final c = asMap(await api.getJson('/api/v1/assistant/conversations/$id'));
      if (mounted) setState(() => _conv = c);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _input.text).trim();
    if (text.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      var conv = _conv;
      conv ??= asMap(await api.postJson('/api/v1/assistant/conversations', {if (api.runId != null) 'run_id': api.runId}));
      final res = asMap(await api.postJson('/api/v1/assistant/conversations/${conv['id']}/messages', {'text': text}));
      _input.clear();
      if (!mounted) return;
      setState(() => _conv = asMap(res['conversation']));
      await _refresh();
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _decide(String actionId, bool approve) async {
    final conv = _conv;
    if (conv == null || _busy) return;
    setState(() => _busy = true);
    try {
      final res = asMap(await api.postJson(
          '/api/v1/assistant/conversations/${conv['id']}/actions/$actionId', {'approve': approve}));
      if (mounted) setState(() => _conv = asMap(res['conversation']));
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _openDraft(String id) async {
    try {
      final d = asMap(await api.getJson('/api/v1/assistant/drafts/$id'));
      if (mounted) {
        setState(() {
          _draft = d;
          _tab = 1;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      final pad = box.maxWidth < 600 ? AppSpacing.lg : AppSpacing.page;
      return ListView(padding: EdgeInsets.all(pad), children: [
        const ResearchHeader(
            title: 'Assistant',
            sentence: 'Ask about the analysis, start an analysis, or draft a syllabus. Answers come from the analysis '
                'data and show what they were looked up from; drafts are written by a local AI model for faculty '
                'review, never an analysis result.'),
        _modelNotice(),
        SegmentTabs(
            labels: ['Conversation', 'Drafts (${_drafts.length})'],
            selected: _tab,
            onSelect: (i) => setState(() => _tab = i)),
        SizedBox(height: AppSpacing.xl),
        if (_error != null) ErrorState(what: 'the assistant', error: _error, onRetry: _refresh),
        if (_tab == 0) _chat(box.maxWidth) else _draftsView(),
      ]);
    });
  }

  Widget _modelNotice() {
    final s = _status;
    if (s == null || s['ready'] == true) {
      if (s == null) return const SizedBox.shrink();
      return Padding(
        padding: EdgeInsets.only(bottom: AppSpacing.lg),
        child: Text('Model: ${_t(s['model'])} on this computer'
            '${s['tools'] == false ? ' (no native tool support: a simpler protocol is used)' : ''}.',
            style: AppTypography.caption),
      );
    }
    return StatusBanner(
        status: 'NOT_LOADED',
        title: 'The local AI model is not running',
        body: '${_t(s['how_to_fix'])} Drafts already made can still be read.');
  }

  // ------------------------------------------------------------------ conversation
  Widget _chat(double width) {
    final conv = _conv;
    final turns = asList(conv?['turns']).map(asMap).toList();
    final thread = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (turns.isEmpty) ...[
        Text('Try:', style: AppTypography.caption),
        SizedBox(height: AppSpacing.sm),
        Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.sm, children: [
          for (final s in AssistantScreen.suggestions)
            ActionChip(label: Text(s), onPressed: _busy ? null : () => _send(s)),
        ]),
        SizedBox(height: AppSpacing.xl),
      ],
      for (final t in turns) _Turn(turn: t, onDecide: _decide, onOpenDraft: _openDraft,
          pendingId: _t(asMap(conv?['pending_action'])['id'])),
      if (_busy)
        Padding(
          padding: EdgeInsets.symmetric(vertical: AppSpacing.lg),
          child: Row(children: [
            const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
            SizedBox(width: AppSpacing.md),
            Expanded(child: Text('Working: a local model can take up to a minute, longer for a draft.',
                style: AppTypography.caption)),
          ]),
        ),
      SizedBox(height: AppSpacing.lg),
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(
          child: TextField(
            controller: _input,
            enabled: !_busy,
            minLines: 1,
            maxLines: 5,
            textInputAction: TextInputAction.send,
            onSubmitted: (_) => _send(),
            decoration: const InputDecoration(labelText: 'Ask or give an instruction', border: OutlineInputBorder()),
          ),
        ),
        SizedBox(width: AppSpacing.md),
        FilledButton(onPressed: _busy ? null : () => _send(), child: const Text('Send')),
      ]),
    ]);
    final list = _ConversationList(
        items: _convs,
        selected: _t(conv?['id']),
        onOpen: _open,
        onNew: () => setState(() => _conv = null));
    if (width < 900) return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [list, thread]);
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(width: 240, child: list),
      SizedBox(width: AppSpacing.xl),
      Expanded(child: thread),
    ]);
  }

  // ------------------------------------------------------------------ drafts
  Widget _draftsView() {
    final d = _draft;
    if (d != null) return _DraftView(draft: d, onBack: () => setState(() => _draft = null));
    if (_drafts.isEmpty) {
      return const EmptyState(
          title: 'No drafts yet',
          body: 'Ask the assistant to draft a course syllabus, a programme structure or a course revision; drafts '
              'appear here.');
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final x in _drafts)
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(_t(x['title']), style: AppTypography.body),
          subtitle: Text('${_kind(x['kind'])} · ${_t(x['created_at'])}', style: AppTypography.caption),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => _openDraft(_t(x['id'])),
        ),
    ]);
  }
}

/// Text exactly as the backend or the model wrote it (fmt() would turn codes into words, which must not happen to
/// a model's reply or a draft); whole-number doubles without ".0".
String _t(dynamic v) {
  if (v == null) return '';
  if (v is double && v == v.roundToDouble()) return v.toStringAsFixed(0);
  return v.toString();
}

String _kind(dynamic k) => switch (k) {
      'course' => 'Course syllabus',
      'programme' => 'Programme structure',
      'revision' => 'Course revision',
      'lesson_plan' => 'Lesson plan',
      'resources' => 'Learning resources',
      _ => _t(k),
    };

class _ConversationList extends StatelessWidget {
  const _ConversationList({required this.items, required this.selected, required this.onOpen, required this.onNew});
  final List<Map<String, dynamic>> items;
  final String selected;
  final ValueChanged<String> onOpen;
  final VoidCallback onNew;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      OutlinedButton.icon(onPressed: onNew, icon: const Icon(Icons.add, size: 16), label: const Text('New conversation')),
      SizedBox(height: AppSpacing.md),
      for (final c in items.take(12))
        ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          selected: _t(c['id']) == selected,
          title: Text(_t(c['title']), maxLines: 2, overflow: TextOverflow.ellipsis, style: AppTypography.body),
          onTap: () => onOpen(_t(c['id'])),
        ),
      SizedBox(height: AppSpacing.lg),
    ]);
  }
}

const _toolNames = {
  'analysis_overview': 'analysis overview',
  'list_skill_gaps': 'skill gaps',
  'industry_demand': 'industry demand',
  'explain_skill': 'skill evidence',
  'list_recommendations': 'recommendations',
  'search_curriculum': 'curriculum search',
  'get_course': 'course',
  'list_analyses': 'analyses',
  'list_uploads': 'uploads',
  'start_analysis': 'start an analysis',
  'draft_course_syllabus': 'course syllabus draft',
  'draft_programme_structure': 'programme draft',
  'propose_course_revision': 'course revision draft',
  'draft_lesson_plan': 'lesson plan draft',
  'find_resources': 'learning resources',
};

class _Turn extends StatelessWidget {
  const _Turn({required this.turn, required this.onDecide, required this.onOpenDraft, required this.pendingId});
  final Map<String, dynamic> turn;
  final void Function(String id, bool approve) onDecide;
  final ValueChanged<String> onOpenDraft;
  final String pendingId;

  @override
  Widget build(BuildContext context) {
    final trace = asList(turn['tool_trace']).map(asMap).toList();
    final warnings = asList(turn['warnings']).map(_t).toList();
    final sources = asList(turn['sources']).map(_t).toSet().toList();
    final pending = asMap(turn['pending_action']);
    final error = asMap(turn['error']);
    return Padding(
      padding: EdgeInsets.only(bottom: AppSpacing.xl),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (turn['user'] != null) ...[
          Text('You', style: AppTypography.caption),
          SelectableText(_t(turn['user']), style: AppTypography.body),
          SizedBox(height: AppSpacing.md),
        ],
        Text('Assistant', style: AppTypography.caption),
        if (error.isNotEmpty)
          Text('The local AI model could not answer: ${_t(error['message'])}', style: AppTypography.muted)
        else
          SelectableText(_t(turn['reply']), style: AppTypography.body),
        if (trace.isNotEmpty) ...[
          SizedBox(height: AppSpacing.sm),
          Text(
              'Looked up: ${trace.map((t) => '${_toolNames[t['tool']] ?? _t(t['tool'])}${t['error'] != null ? ' (failed)' : ''}').join(', ')}',
              style: AppTypography.caption),
        ],
        if (sources.isNotEmpty) Text('Sources: ${sources.join('; ')}', style: AppTypography.caption),
        for (final w in warnings)
          Padding(
            padding: EdgeInsets.only(top: AppSpacing.xs),
            child: Text('Check: $w', style: AppTypography.caption.copyWith(color: AppColors.warning)),
          ),
        for (final id in asList(turn['draft_ids']).map(_t))
          Padding(
            padding: EdgeInsets.only(top: AppSpacing.sm),
            child: OutlinedButton.icon(
                onPressed: () => onOpenDraft(id),
                icon: const Icon(Icons.description_outlined, size: 16),
                label: const Text('Open the draft')),
          ),
        if (pending.isNotEmpty && _t(pending['id']) == pendingId)
          Padding(
            padding: EdgeInsets.only(top: AppSpacing.md),
            child: SectionCard(
              title: 'Confirm this action',
              subtitle: _t(pending['description']),
              child: Row(children: [
                FilledButton(onPressed: () => onDecide(_t(pending['id']), true), child: const Text('Confirm')),
                SizedBox(width: AppSpacing.md),
                OutlinedButton(onPressed: () => onDecide(_t(pending['id']), false), child: const Text('Cancel')),
              ]),
            ),
          ),
      ]),
    );
  }
}

class _DraftView extends StatelessWidget {
  const _DraftView({required this.draft, required this.onBack});
  final Map<String, dynamic> draft;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    final c = asMap(draft['content']);
    final checks = asMap(draft['checks']);
    final evidence = asMap(draft['evidence']);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Wrap(spacing: AppSpacing.md, children: [
        TextButton.icon(onPressed: onBack, icon: const Icon(Icons.arrow_back, size: 16), label: const Text('All drafts')),
        OutlinedButton.icon(
          onPressed: () => Clipboard.setData(ClipboardData(text: markdownOf(draft))),
          icon: const Icon(Icons.copy, size: 16),
          label: const Text('Copy as Markdown'),
        ),
      ]),
      SizedBox(height: AppSpacing.md),
      Text(_t(draft['title']), style: AppTypography.headline),
      SizedBox(height: AppSpacing.sm),
      Text(_t(draft['label']), style: AppTypography.caption.copyWith(color: AppColors.warning)),
      Text('${_kind(draft['kind'])} · analysis ${_t(draft['run_id'])} · model ${_t(asMap(draft['model'])['model'])}',
          style: AppTypography.caption),
      SizedBox(height: AppSpacing.xl),
      ..._body(_t(draft['kind']), c),
      SectionCard(
        title: 'Checks',
        subtitle: 'Computed by the application from the draft, not written by the model.',
        child: KeyValueList([
          for (final e in checks.entries)
            if (e.key != 'online_checks' && (e.value is! List || (e.value as List).isNotEmpty))
              MapEntry(_checkLabel(e.key), _checkValue(e.value)),
        ]),
      ),
      SectionCard(
        title: 'Evidence',
        subtitle: 'What the draft could cite, from the analysis. Items without a citation are model suggestions.',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final e in evidence.entries)
            Padding(
              padding: EdgeInsets.only(bottom: AppSpacing.xs),
              child: Text('${e.key}  ${_evidenceLine(asMap(e.value))}', style: AppTypography.caption),
            ),
        ]),
      ),
    ]);
  }

  static String _checkLabel(String k) => switch (k) {
        'total_hours' => 'Total hours',
        'topics' => 'Topics',
        'topics_with_evidence' => 'Topics with evidence',
        'total_credits' => 'Total credits',
        'semesters' => 'Semesters',
        'courses' => 'Courses',
        'courses_with_evidence' => 'Courses with evidence',
        'changes' => 'Changes',
        'changes_with_evidence' => 'Changes with evidence',
        'unknown_evidence_ids_removed' => 'Citations removed (not in the evidence)',
        'skills_addressed' => 'Requested skills addressed',
        'skills_not_addressed' => 'Requested skills not addressed',
        'rejected_changes' => 'Changes rejected (topic not in the course)',
        'professional_practice_skills' => 'Skills for teaching methods, not topics',
        'other_field_skills' => 'Skills of another field',
        'sessions' => 'Sessions',
        'sessions_requested' => 'Sessions requested',
        'total_minutes' => 'Total minutes',
        'topics_covered' => 'Course topics covered',
        'topics_not_covered' => 'Course topics no session covers',
        'items' => 'Resources',
        'by_source' => 'By source',
        'online_checks' => 'Online checks',
        'removed_links_not_found' => 'Removed: link does not exist',
        _ => k,
      };

  List<Widget> _body(String kind, Map<String, dynamic> c) {
    Widget item(String text, List ids) => Padding(
          padding: EdgeInsets.only(bottom: AppSpacing.xs),
          child: Text.rich(TextSpan(children: [
            TextSpan(text: '• $text', style: AppTypography.body),
            TextSpan(
                text: ids.isEmpty ? '   model suggestion' : '   ${ids.map(_t).join(', ')}',
                style: AppTypography.caption.copyWith(color: ids.isEmpty ? AppColors.warning : AppColors.textMuted)),
          ])),
        );
    List<Widget> plain(String title, dynamic list) => asList(list).isEmpty
        ? const []
        : [
            SectionCard(
                title: title,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final x in asList(list)) Text('• ${_t(x)}', style: AppTypography.body),
                ])),
          ];
    switch (kind) {
      case 'course':
        return [
          if (_t(c['description']).isNotEmpty)
            Padding(padding: EdgeInsets.only(bottom: AppSpacing.lg), child: Text(_t(c['description']), style: AppTypography.body)),
          ...plain('Objectives', c['objectives']),
          ...plain('Prerequisites', c['prerequisites']),
          for (final (i, u) in asList(c['units']).map(asMap).indexed)
            SectionCard(
              title: 'Unit ${i + 1}: ${_t(u['title'])}',
              subtitle: '${_t(u['hours'])} hours',
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final t in asList(u['topics']).map(asMap)) item(_t(t['text']), asList(t['evidence'])),
              ]),
            ),
          ...plain('Course outcomes', c['outcomes']),
          ...plain('Laboratory', c['lab_experiments']),
          ...plain('Assessment', c['assessment']),
          if (asList(c['reading']).isNotEmpty)
            SectionCard(
              title: 'Reading (unverified)',
              subtitle: 'Suggested by the model: check that each exists, and its edition, before use.',
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final r in asList(c['reading']).map(asMap))
                  Text('• ${_t(r['title'])}${_t(r['authors']).isEmpty ? '' : ' — ${_t(r['authors'])}'}',
                      style: AppTypography.body),
              ]),
            ),
        ];
      case 'resources':
        final items = asList(c['items']).map(asMap).toList();
        return [
          if (_t(c['summary']).isNotEmpty)
            Padding(padding: EdgeInsets.only(bottom: AppSpacing.lg), child: Text(_t(c['summary']), style: AppTypography.body)),
          for (final kind in const ['book', 'website', 'documentation', 'course_platform', 'youtube', 'other'])
            if (items.any((i) => i['kind'] == kind))
              SectionCard(
                title: _resourceHeading(kind),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final r in items.where((i) => i['kind'] == kind)) _ResourceRow(r),
                ]),
              ),
        ];
      case 'lesson_plan':
        return [
          for (final p in asList(c['sessions']).map(asMap))
            SectionCard(
              title: 'Session ${_t(p['number'])}: ${_t(p['title'])}',
              subtitle: '${_t(p['minutes'])} minutes',
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                _line('Topics', asList(p['topics']).map(_t).join('; '), empty: 'none of the course topics'),
                _line('Objectives', asList(p['objectives']).map(_t).join('; ')),
                _line('Activities', asList(p['activities']).map(_t).join('; ')),
                for (final r in asList(p['resources']).map(asMap)) _ResourceRow(r),
                _line('Assessment', _t(p['assessment'])),
              ]),
            ),
        ];
      case 'programme':
        return [
          for (final s in asList(c['semesters']).map(asMap))
            SectionCard(
              title: 'Semester ${_t(s['number'])}',
              subtitle: '${_t(s['credits'])} credits',
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final x in asList(s['courses']).map(asMap))
                  item('${_t(x['title'])} (${_t(x['credits'])} credits)', asList(x['evidence'])),
              ]),
            ),
        ];
      default:
        return [
          if (_t(c['summary']).isNotEmpty) Padding(padding: EdgeInsets.only(bottom: AppSpacing.lg), child: Text(_t(c['summary']), style: AppTypography.body)),
          for (final (title, key) in const [('Add', 'add'), ('Update', 'update'), ('Remove', 'remove')])
            SectionCard(
              title: title,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (asList(c[key]).isEmpty) Text('None proposed.', style: AppTypography.muted),
                for (final x in asList(c[key]).map(asMap))
                  item(
                      key == 'update'
                          ? '${_t(x['from'])} → ${_t(x['to'])}: ${_t(x['reason'])}'
                          : '${_t(x['topic'])}: ${_t(x['reason'])}',
                      asList(x['evidence'])),
              ]),
            ),
        ];
    }
  }
}

String _resourceHeading(String kind) => switch (kind) {
      'book' => 'Books',
      'website' => 'Websites',
      'documentation' => 'Documentation',
      'course_platform' => 'Course platforms',
      'youtube' => 'YouTube channels',
      _ => 'Other',
    };

String _checkValue(dynamic v) {
  if (v is List) return v.map(_t).join(', ');
  if (v is Map) {
    const words = {'LISTED_IN_CURRICULUM': 'listed in curricula', 'CURATED': 'curated', 'MODEL_SUGGESTION': 'model suggestions'};
    return v.entries.map((e) => '${words[e.key] ?? _t(e.key)}: ${_t(e.value)}').join(', ');
  }
  return _t(v);
}

Widget _line(String label, String text, {String? empty}) {
  if (text.isEmpty && empty == null) return const SizedBox.shrink();
  return Padding(
    padding: EdgeInsets.only(bottom: AppSpacing.xs),
    child: Text.rich(TextSpan(children: [
      TextSpan(text: '$label: ', style: AppTypography.caption),
      TextSpan(text: text.isEmpty ? empty : text, style: AppTypography.body),
    ])),
  );
}

/// Where a resource comes from and what the online check found, in words.
String resourceStatus(Map<String, dynamic> r) {
  final source = switch (r['status']) {
    'LISTED_IN_CURRICULUM' => 'listed in the curriculum${r['where'] == null ? '' : ' (${_t(r['where'])})'}',
    'CURATED' => 'curated',
    _ => 'suggested by the model',
  };
  final check = switch (asMap(r['check'])['check']) {
    'LINK_OK' => 'link checked',
    'FOUND_IN_OPEN_LIBRARY' => 'found in Open Library',
    'NOT_FOUND_IN_OPEN_LIBRARY' => 'not found in Open Library: verify before use',
    'NOT_CHECKED' => 'not checked online',
    _ => null,
  };
  return [source, if (check != null) check].join(' · ');
}

class _ResourceRow extends StatelessWidget {
  const _ResourceRow(this.r);
  final Map<String, dynamic> r;

  @override
  Widget build(BuildContext context) {
    final unverified = r['status'] == 'MODEL_SUGGESTION' && asMap(r['check'])['check'] != 'LINK_OK' &&
        asMap(r['check'])['check'] != 'FOUND_IN_OPEN_LIBRARY';
    return Padding(
      padding: EdgeInsets.only(bottom: AppSpacing.sm),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('• ${_t(r['title'])}${_t(r['authors']).isEmpty ? '' : ' — ${_t(r['authors'])}'}', style: AppTypography.body),
        if (r['url'] != null) SelectableText(_t(r['url']), style: AppTypography.caption),
        if (_t(r['use']).isNotEmpty) Text(_t(r['use']), style: AppTypography.caption),
        Text(resourceStatus(r),
            style: AppTypography.caption.copyWith(color: unverified ? AppColors.warning : AppColors.textMuted)),
      ]),
    );
  }
}

String _evidenceLine(Map<String, dynamic> e) {
  switch (e['type']) {
    case 'industry_demand':
      return 'skill "${_t(e['skill'])}": ${_t(e['posting_count'])} of ${_t(e['eligible_postings'])} postings; '
          'gap ${_t(e['gap'])}';
    case 'programme_course':
      return 'reference course ${_t(e['title'])} (${_t(e['course_code'])}), semester ${_t(e['semester'])}';
    case 'book':
      return 'textbook in ${_t(e['doc_id'])} ${_t(e['course_code'])}, page ${_t(e['page'])}: ${_t(e['text'])}';
    case 'web_link':
      return 'link in ${_t(e['doc_id'])} ${_t(e['course_code'])}, page ${_t(e['page'])}: ${_t(e['url'])}';
    case 'curated_resource':
      return 'curated: ${_t(e['title'])} ${_t(e['url'])}';
    case 'plan_topic':
      return 'course topic "${_t(e['text'])}"';
    default:
      return '${_t(e['role']).toLowerCase()} topic "${_t(e['text'])}" — ${_t(e['course_code'])}, page ${_t(e['page'])}';
  }
}

/// The draft as Markdown, for copying into a document (the server offers the same at /drafts/{id}/markdown).
String markdownOf(Map<String, dynamic> d) {
  final c = asMap(d['content']);
  final b = StringBuffer('# ${_t(d['title'])}\n\n> ${_t(d['label'])}\n\n');
  String cite(List ids) => ids.isEmpty ? ' *(model suggestion)*' : ' [${ids.map(_t).join(', ')}]';
  for (final (i, u) in asList(c['units']).map(asMap).indexed) {
    b.writeln('## Unit ${i + 1}: ${_t(u['title'])} (${_t(u['hours'])} h)');
    for (final t in asList(u['topics']).map(asMap)) {
      b.writeln('- ${_t(t['text'])}${cite(asList(t['evidence']))}');
    }
    b.writeln();
  }
  for (final s in asList(c['semesters']).map(asMap)) {
    b.writeln('## Semester ${_t(s['number'])} (${_t(s['credits'])} credits)');
    for (final x in asList(s['courses']).map(asMap)) {
      b.writeln('- ${_t(x['title'])}, ${_t(x['credits'])} credits${cite(asList(x['evidence']))}');
    }
    b.writeln();
  }
  for (final key in const ['add', 'update', 'remove']) {
    final rows = asList(c[key]).map(asMap).toList();
    if (rows.isEmpty) continue;
    b.writeln('## ${key[0].toUpperCase()}${key.substring(1)}');
    for (final x in rows) {
      b.writeln(key == 'update'
          ? '- ${_t(x['from'])} → ${_t(x['to'])}: ${_t(x['reason'])}${cite(asList(x['evidence']))}'
          : '- ${_t(x['topic'])}: ${_t(x['reason'])}${cite(asList(x['evidence']))}');
    }
    b.writeln();
  }
  for (final r in asList(c['items']).map(asMap)) {
    b.writeln('- ${_t(r['title'])}${r['url'] == null ? '' : ' <${_t(r['url'])}>'} *(${resourceStatus(r)})*');
  }
  for (final p in asList(c['sessions']).map(asMap)) {
    b.writeln('## Session ${_t(p['number'])}: ${_t(p['title'])} (${_t(p['minutes'])} min)');
    b.writeln('- Topics: ${asList(p['topics']).map(_t).join('; ')}');
    if (asList(p['activities']).isNotEmpty) b.writeln('- Activities: ${asList(p['activities']).map(_t).join('; ')}');
    if (_t(p['assessment']).isNotEmpty) b.writeln('- Assessment: ${_t(p['assessment'])}');
    b.writeln();
  }
  b.writeln('## Evidence');
  for (final e in asMap(d['evidence']).entries) {
    b.writeln('- **${e.key}**: ${_evidenceLine(asMap(e.value))}');
  }
  return b.toString();
}
