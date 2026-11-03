import 'dart:async';
import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../shell/evidence_draft.dart';
import '../shell/navigation.dart';
import '../shell/run_context.dart';
import '../theme/design_system.dart';
import '../theme/plain_language.dart';
import '../widgets/ui_kit.dart';
import 'premium/pages.dart';

export '../shell/evidence_draft.dart' show PickedUpload;

typedef UploadPicker = Future<PickedUpload?> Function(List<String> extensions);

/// New analysis (adding evidence) -> Validate -> Extract -> Review -> Publish -> Analyse.
///
/// What is being added decides the form: a curriculum (the analysed programme), a peer curriculum, a reference
/// curriculum, a general reference document, or industry job postings. The metadata policy per role, the known
/// disciplines, the posting file formats and the source registry all come from the API (data, not code).
///
/// The form shows only what the role requires, each with the reason it is needed; everything else sits under "More
/// details (optional)". When a curriculum file is chosen, its first pages are read for suggestions (institution,
/// programme, discipline, regulation, year), each shown with the page and line it came from for the person to check;
/// conflicting readings are offered as choices, never picked silently. The whole form is a draft kept for the session
/// (EvidenceDraft): leaving the page and coming back restores it.
///
/// The result is shown as a decision -- ready / needs review / no usable content / failed -- never as raw ingestion
/// output; the raw details stay one click away for administrators.
class IngestionScreen extends StatefulWidget {
  const IngestionScreen({super.key, required this.apiClient, this.navigate, this.draft});
  final ApiClient apiClient;
  final Navigate? navigate;

  /// The draft to edit; by default the session's (RunScope), so it survives navigation.
  final EvidenceDraft? draft;

  /// Replaces the platform file picker in widget tests.
  static UploadPicker? debugPicker;

  @override
  State<IngestionScreen> createState() => _IngestionScreenState();
}

const _kinds = [
  ('TARGET', 'Curriculum', 'The programme curriculum you want analysed'),
  ('PEER', 'Peer', 'An official curriculum of another institution, for comparison'),
  ('REFERENCE', 'Reference', 'A model or regulatory curriculum (may belong to no institution)'),
  ('GENERAL_REFERENCE', 'Skills reference', 'A skills framework or other reference that is not a curriculum'),
  ('INDUSTRY', 'Industry', 'Job postings you are permitted to use'),
];

/// Why a field is required, in the reader's terms.
const _whyRequired = {
  'institution': 'Says whose curriculum this is, so no other institution\'s results are ever mixed in.',
  'programme': 'Tells this programme apart from the institution\'s other programmes.',
  'discipline': 'Decides which reference curriculum, job postings and peers the analysis may use: only those of the '
      'same discipline.',
  'curriculum_version': 'Tells versions of the same programme apart, so changes are measured between the right ones.',
  'source_url': 'A peer curriculum must be official and traceable to where it was published.',
  'source_name': 'Records where the file came from.',
  'licence_note': 'You must be permitted to use the file; its licence or terms are recorded with it.',
};

class _IngestionScreenState extends State<IngestionScreen> {
  EvidenceDraft? _d;
  Map<String, dynamic>? _roles;
  List<String> _disciplines = const [];
  Map<String, dynamic>? _profiles; // GET /api/v1/metadata/discipline-profiles (null: unavailable)
  Map<String, dynamic>? _targets; // GET /api/v1/analysis/comparison-targets for the typed discipline (null: unavailable)
  String? _targetsFor; // the discipline text _targets answers
  int _targetsSeq = 0; // only the answer to the latest request is used
  Map<String, dynamic>? _formats;
  final Map<String, TextEditingController> _fields = {};
  bool _uploading = false;
  bool _inspecting = false;
  Object? _error;
  int _fillVersion = 0; // bumps when suggestions or a reset change field text from outside the field
  final _reviewer = TextEditingController();

  ApiClient get api => widget.apiClient;
  EvidenceDraft get draft => _d!;
  String get _kind => draft.kind;
  PickedUpload? get _file => draft.file;
  Map<String, dynamic>? get _result => draft.result;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_d == null) {
      _d = widget.draft ?? RunScope.of(context)?.draft ?? EvidenceDraft();
      _c('discipline').addListener(_disciplineChanged);
    }
  }

  void _disciplineChanged() {
    if (_kind == 'TARGET' && _c('discipline').text.trim() != _targetsFor) unawaited(_loadTargets());
  }

  /// The peers this curriculum can be compared with, for the discipline typed so far. The person chooses among the
  /// comparable ones; peers of another discipline are listed but cannot be chosen (and are never used instead).
  Future<void> _loadTargets() async {
    final disc = _c('discipline').text.trim();
    final seq = ++_targetsSeq;
    _targetsFor = disc;
    Map<String, dynamic>? res;
    try {
      final r = await api.getJson('/api/v1/analysis/comparison-targets', query: {if (disc.isNotEmpty) 'discipline': disc});
      res = r is Map<String, dynamic> ? r : null;
    } catch (_) {
      res = null;
    }
    if (!mounted || seq != _targetsSeq) return;
    setState(() {
      _targets = res;
      if (res == null) return; // no list: no choice is offered and none is invented
      if (disc.isEmpty) {
        draft.peerIds = null; // without a discipline nothing can be judged comparable yet
        return;
      }
      final comparable = {
        for (final p in asList(res['peers']).map(asMap))
          if (p['comparable'] == true) fmt(p['doc_id'])
      };
      // a first choice selects every comparable peer; later, peers that stopped being comparable are unticked
      draft.peerIds = draft.peerIds == null ? comparable : draft.peerIds!.intersection(comparable);
    });
  }

  @override
  void initState() {
    super.initState();
    _loadMetadata();
  }

  @override
  void dispose() {
    for (final c in _fields.values) {
      c.dispose();
    }
    _reviewer.dispose();
    super.dispose();
  }

  Future<void> _loadMetadata() async {
    Future<dynamic> safe(String p) async {
      try {
        return await api.getJson(p);
      } catch (_) {
        return null;
      }
    }

    final r = await Future.wait([
      safe('/api/v1/metadata/document-roles'),
      safe('/api/v1/metadata/disciplines'),
      safe('/api/v1/metadata/upload-formats'),
      safe('/api/v1/metadata/discipline-profiles'),
    ]);
    if (!mounted) return;
    setState(() {
      _roles = r[0] is Map<String, dynamic> ? r[0] as Map<String, dynamic> : null;
      _formats = r[2] is Map<String, dynamic> ? r[2] as Map<String, dynamic> : null;
      _profiles = r[3] is Map<String, dynamic> ? r[3] as Map<String, dynamic> : null;
      // configured disciplines first, then those already seen in analysed documents
      final names = <String>[
        for (final p in asList(_profiles?['profiles'])) fmt(at(p, 'name')),
        for (final d in asList(at(r[1], 'items'))) fmt(at(d, 'name')),
      ];
      final seen = <String>{};
      _disciplines = [for (final n in names) if (n.trim().isNotEmpty && seen.add(n.toLowerCase())) n];
    });
    if (_kind == 'TARGET') unawaited(_loadTargets());
  }

  /// The controller of a field, created from the draft and writing back to it (so the draft is always current).
  TextEditingController _c(String f) => _fields.putIfAbsent(f, () {
        final c = TextEditingController(text: draft.values[f] ?? '');
        c.addListener(() {
          draft.values[f] = c.text;
          final s = asMap(draft.suggestions[f]);
          if (draft.suggested.contains(f) && c.text != '${s['value'] ?? ''}') draft.suggested.remove(f);
        });
        return c;
      });

  void _setField(String f, String value, {bool suggested = false}) {
    _c(f).text = value;
    if (suggested) draft.suggested.add(f);
  }

  Map<String, dynamic> get _policy {
    for (final r in asList(_roles?['roles'])) {
      if (at(r, 'role') == _kind) return asMap(r);
    }
    // the policy could not be loaded: nothing is marked required, the server still validates
    return const {'required': <String>[], 'recommended': <String>[]};
  }

  String _fieldLabel(String f) => fmt(at(_roles, 'fields.$f') ?? Plain.field(f));

  List<String> get _requiredFields =>
      _kind == 'INDUSTRY' ? const ['source_name', 'licence_note'] : asList(_policy['required']).map(fmt).toList();

  List<String> get _missing => [
        for (final f in _requiredFields)
          if (_c(f).text.trim().isEmpty) f
      ];

  bool get _curriculumKind => _kind == 'TARGET' || _kind == 'PEER' || _kind == 'REFERENCE';

  Future<void> _pick() async {
    final ext = _kind == 'INDUSTRY' ? ['csv'] : ['pdf', 'txt'];
    PickedUpload? f;
    final dbg = IngestionScreen.debugPicker;
    if (dbg != null) {
      f = await dbg(ext);
    } else {
      final picked = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ext, withData: true);
      final one = picked?.files.single;
      if (one?.bytes != null) f = PickedUpload(one!.name, one.bytes!);
    }
    if (f == null || !mounted) return;
    setState(() {
      draft.file = f;
      // suggestions belong to the file they were read from: values still untouched from the previous file go
      for (final field in draft.suggested.toList()) {
        _c(field).text = '';
      }
      draft.suggested.clear();
      draft.suggestions = {};
      _fillVersion++;
    });
    if (_curriculumKind) unawaited(_inspect(f));
  }

  /// Reads the chosen file's first pages for metadata suggestions; empty fields are pre-filled with values found
  /// unambiguously, conflicting readings are offered as choices. A failure only means no suggestions.
  Future<void> _inspect(PickedUpload file) async {
    setState(() => _inspecting = true);
    Map<String, dynamic> found = {};
    try {
      final res = await api.inspectCurriculum(fileBytes: file.bytes, fileName: file.name).timeout(const Duration(seconds: 30));
      found = asMap(res['suggestions']);
    } catch (_) {
      found = {};
    }
    if (!mounted || draft.file != file) return;
    setState(() {
      _inspecting = false;
      draft.suggestions = found;
      for (final e in found.entries) {
        final s = asMap(e.value);
        if (s['status'] == 'FOUND' && s['value'] != null && _c(e.key).text.trim().isEmpty) {
          _setField(e.key, '${s['value']}', suggested: true);
        }
      }
      _fillVersion++;
    });
  }

  Future<void> _upload() async {
    final file = _file;
    if (file == null || _missing.isNotEmpty) return;
    setState(() {
      _uploading = true;
      _error = null;
    });
    try {
      Map<String, dynamic> res;
      if (_kind == 'INDUSTRY') {
        res = await api.ingestJobPostings(fileBytes: file.bytes, fileName: file.name, datasetPreset: draft.preset, fields: {
          'source_name': _c('source_name').text,
          'source_url': _c('source_url').text,
          'licence_note': _c('licence_note').text,
        });
      } else {
        final fields = <String, String>{'document_role': _kind};
        for (final f in ['discipline', 'specialization', 'degree_level', 'academic_year', 'source_url', 'licence_note',
          'title', 'publisher']) {
          fields[f] = _c(f).text;
        }
        fields['curriculum_version_label'] = _c('curriculum_version').text;
        res = await api.ingestCurriculum(
            fileBytes: file.bytes,
            fileName: file.name,
            institution: _c('institution').text.trim().isEmpty ? null : _c('institution').text.trim(),
            programme: _c('programme').text.trim().isEmpty ? null : _c('programme').text.trim(),
            fields: fields);
      }
      if (!mounted) return;
      setState(() {
        _uploading = false;
        draft.result = res;
      });
      _afterResult(res);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _uploading = false;
        _error = e;
      });
    }
  }

  void _afterResult(Map<String, dynamic> res) {
    final outcome = at(res, 'outcome.outcome');
    if (outcome != 'SUCCESSFUL_AND_USABLE' || _kind == 'INDUSTRY' || _kind == 'GENERAL_REFERENCE') return;
    final c = asMap(at(res, 'outcome.counts'));
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(
      backgroundColor: AppColors.surfaceRaised,
      content: Text('Curriculum uploaded successfully — ${fmtCount(c['courses'])} courses · ${fmtCount(c['topics'])} topics · '
          '${fmtCount(c['outcomes'])} learning outcomes. Opening curriculum intelligence…',
          style: AppTypography.body),
    ));
    _analyse();
  }

  Future<void> _analyse({String? reviewedBy}) async {
    final ctx = RunScope.of(context);
    final res = _result;
    if (res == null) return;
    if (ctx != null) {
      // do not await: the Overview shows the live progress while the analysis runs
      ctx.analyseUpload(res, reviewedBy: reviewedBy, options: _kind == 'TARGET' ? draft.options : null);
    }
    widget.navigate?.call(Dest.overview);
  }

  /// Clears the draft after an explicit confirmation (nothing is discarded silently).
  Future<void> _confirmClear() async {
    if (!draft.isEmpty) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Clear this form?'),
          content: const Text('The chosen file and everything you entered will be discarded.'),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Keep editing')),
            FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Clear form')),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }
    setState(_resetDraft);
  }

  void _resetDraft() {
    draft.clear();
    for (final c in _fields.values) {
      c.text = '';
    }
    draft.values.clear();
    _error = null;
    _fillVersion++;
  }

  // ---------------------------------------------------------------- build

  @override
  Widget build(BuildContext context) {
    final done = _result != null;
    return PageFrame(children: [
      const PageHeader(
        eyebrow: 'Start',
        title: 'New analysis',
        subtitle: 'Upload a curriculum to analyse it, or add a peer or reference curriculum, a reference document or '
            'job postings. Every file is validated and extracted; nothing reaches the analysis until its extraction '
            'is usable.',
      ),
      WorkflowSteps(current: _step),
      const SizedBox(height: AppSpacing.xxl),
      if (done)
        IngestionResultView(
          result: _result!,
          kind: _kind,
          reviewer: _reviewer,
          onAnalyse: _analyse,
          onReview: () => widget.navigate?.call(Dest.preprocessing),
          onDashboard: () => widget.navigate?.call(Dest.overview),
          // the upload succeeded: the draft has served its purpose
          onAnother: () => setState(_resetDraft),
        )
      else if (_error != null) ...[
        UploadFailedView(error: _error, onRetry: _upload),
        // the draft is intact: the person can correct what the server rejected and upload again
        TextButton(onPressed: () => setState(() => _error = null), child: const Text('Back to the form')),
      ] else ...[
        _kindChooser(),
        const SizedBox(height: AppSpacing.xxl),
        _fileAndSubmit(),
        const SizedBox(height: AppSpacing.xl),
        _kind == 'INDUSTRY' ? _industryForm() : _documentForm(),
        if (_kind == 'TARGET') ...[
          const SizedBox(height: AppSpacing.xl),
          _analysisOptions(),
        ],
        const SizedBox(height: AppSpacing.xl),
        _submitRow(),
      ],
    ]);
  }

  int get _step {
    if (_uploading) return 2;
    if (_result != null) {
      final o = at(_result, 'outcome.outcome');
      return o == 'SUCCESSFUL_AND_USABLE' ? 4 : 3;
    }
    return _file == null ? 0 : 1;
  }

  Widget _kindChooser() {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('What are you adding?', style: AppTypography.title),
      const SizedBox(height: AppSpacing.md),
      Wrap(spacing: AppSpacing.md, runSpacing: AppSpacing.md, children: [
        for (final k in _kinds)
          Semantics(
            button: true,
            selected: _kind == k.$1,
            child: InkWell(
              onTap: _uploading
                  ? null
                  : () {
                      setState(() => draft.kind = k.$1);
                      if (k.$1 == 'TARGET' && _targets == null) unawaited(_loadTargets());
                    },
              child: AnimatedContainer(
                duration: AppMotion.fast,
                width: 210,
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  border: Border(
                      top: BorderSide(color: _kind == k.$1 ? AppColors.primary : AppColors.border, width: _kind == k.$1 ? 2 : 1)),
                ),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(k.$2, style: AppTypography.section.copyWith(color: _kind == k.$1 ? AppColors.text : AppColors.textMuted)),
                  const SizedBox(height: 2),
                  Text(k.$3, style: AppTypography.caption),
                ]),
              ),
            ),
          ),
      ]),
    ]);
  }

  /// Under a field: where a suggested value came from, the choices when the document disagrees with itself, or why
  /// a required field is needed.
  Widget? _fieldNote(String f, bool requiredField) {
    final s = asMap(draft.suggestions[f]);
    if (draft.suggested.contains(f) && s.isNotEmpty) {
      final ev = asMap(s['evidence']);
      // the document's own line, verbatim
      return Text('Found in the document (page ${ev['page']}: “${ev['text']}”). Please check it.',
          style: AppTypography.caption.copyWith(color: AppColors.warning));
    }
    if (s['status'] == 'UNCERTAIN' && _c(f).text.trim().isEmpty) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('The document gives more than one reading; choose one or type your own:', style: AppTypography.caption),
        const SizedBox(height: AppSpacing.xs),
        Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.xs, children: [
          for (final c in asList(s['candidates']).map(asMap))
            ActionChip(
              label: Text('${c['value']}'),
              tooltip: 'Page ${c['page']}: ${c['text']}',
              onPressed: () => setState(() {
                _setField(f, '${c['value']}');
                _fillVersion++;
              }),
            ),
        ]),
      ]);
    }
    if (requiredField && _whyRequired[f] != null) return Text(_whyRequired[f]!, style: AppTypography.caption);
    return null;
  }

  Widget _field(String f, {bool requiredField = false, String? hint}) {
    final label = '${_fieldLabel(f)}${requiredField ? ' (required)' : ''}';
    final note = _fieldNote(f, requiredField);
    Widget input;
    if (f == 'discipline') {
      input = Autocomplete<String>(
        key: ValueKey('discipline-$_fillVersion'),
        initialValue: TextEditingValue(text: _c(f).text),
        optionsBuilder: (v) => _disciplines.where((d) => d.toLowerCase().contains(v.text.toLowerCase())),
        onSelected: (v) => setState(() => _c(f).text = v),
        fieldViewBuilder: (context, controller, focus, onSubmit) {
          controller.addListener(() {
            if (_c(f).text != controller.text) _c(f).text = controller.text;
          });
          return TextField(
            controller: controller,
            focusNode: focus,
            decoration: InputDecoration(labelText: label, hintText: 'Any discipline; suggestions are those already analysed'),
            onChanged: (_) => setState(() {}),
          );
        },
      );
    } else {
      input = TextField(
        controller: _c(f),
        decoration: InputDecoration(labelText: label, hintText: hint),
        onChanged: (_) => setState(() {}),
      );
    }
    final support = f == 'discipline' ? _disciplineSupport() : null;
    return SizedBox(
      width: 360,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        input,
        if (note != null) Padding(padding: const EdgeInsets.only(top: AppSpacing.xs), child: note),
        if (support != null) Padding(padding: const EdgeInsets.only(top: AppSpacing.xs), child: support),
      ]),
    );
  }

  Widget _documentForm() {
    final req = asList(_policy['required']).map(fmt).toList();
    final rec = asList(_policy['recommended']).map(fmt).toSet();
    const order = ['title', 'publisher', 'institution', 'programme', 'discipline', 'curriculum_version', 'specialization',
      'degree_level', 'academic_year', 'source_url', 'licence_note', 'version'];
    // without a policy (service unavailable) the two fields every curriculum has stay in front
    final primary = req.isNotEmpty ? [for (final f in order) if (req.contains(f)) f] : const ['institution', 'programme'];
    final optional = [
      for (final f in order)
        if (!primary.contains(f) &&
            (rec.contains(f) || (req.isEmpty && const ['discipline', 'curriculum_version', 'academic_year'].contains(f))))
          f
    ];
    return SplitRow(
      leftFlex: 3,
      rightFlex: 7,
      left: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('About the document', style: AppTypography.title),
        const SizedBox(height: AppSpacing.sm),
        Text(fmt(_policy['description'] ?? 'Describe the document so the analysis can scope it correctly.'),
            style: AppTypography.muted),
        const SizedBox(height: AppSpacing.sm),
        Text(
            _kind == 'REFERENCE'
                ? 'A reference curriculum may belong to no institution: leave the institution empty or give the issuing body.'
                : _kind == 'GENERAL_REFERENCE'
                    ? 'It is registered with its provenance; curriculum extraction does not run on it.'
                    : 'Only what the analysis needs is asked for here. Values found in the document are filled in for '
                        'you to check.',
            style: AppTypography.caption),
        if (_inspecting) ...[
          const SizedBox(height: AppSpacing.sm),
          Text('Reading the document\'s first pages for suggestions…', style: AppTypography.caption),
        ],
      ]),
      right: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: AppSpacing.lg, runSpacing: AppSpacing.lg, children: [
          for (final f in primary) _field(f, requiredField: req.contains(f)),
        ]),
        if (optional.isNotEmpty)
          EvidenceDisclosure(
            title: 'More details (optional)',
            summary: 'Academic year, degree level, specialisation and similar: they make results easier to tell apart',
            initiallyExpanded: optional.any((f) => _c(f).text.trim().isNotEmpty),
            children: [
              Wrap(spacing: AppSpacing.lg, runSpacing: AppSpacing.lg, children: [for (final f in optional) _field(f)]),
            ],
          ),
      ]),
    );
  }

  /// What the analysis can do for the typed discipline, from the discipline profiles (never assumed).
  Widget? _disciplineSupport() {
    final disc = _c('discipline').text.trim();
    final t = _targets;
    if (_kind != 'TARGET' || disc.isEmpty || t == null || _targetsFor != disc) return null;
    final ref = asMap(t['discipline_profile']);
    if (ref.isEmpty) {
      return Text(
          'Not a configured discipline: the curriculum is analysed on its own, without industry evidence or '
          'comparisons. The configured disciplines are listed in Settings.',
          style: AppTypography.caption.copyWith(color: AppColors.warning));
    }
    var profile = <String, dynamic>{};
    for (final p in asList(_profiles?['profiles'])) {
      if (at(p, 'id') == ref['id']) profile = asMap(p);
    }
    final caps = asMap(profile['capabilities']);
    final industry = caps['industry_analysis'] == 'AVAILABLE'
        ? 'Job postings relevant to it are available.'
        : caps['industry_analysis'] == null
            ? null
            : 'No job postings for this discipline have been supplied, so industry demand and skill gaps do not apply.';
    return Text(['Recognised as ${fmt(ref['name'])}.', if (industry != null) industry].join(' '),
        style: AppTypography.caption);
  }

  /// Comparable peers for the typed discipline: null while that cannot be judged yet (no list from the server, or no
  /// discipline typed), so the option stays usable; 0 when the list says none is of this discipline.
  int? _comparablePeerCount() {
    final t = _targets;
    if (t == null || _c('discipline').text.trim().isEmpty) return null;
    return asList(t['peers']).map(asMap).where((p) => p['comparable'] == true).length;
  }

  /// The peer chooser under "Peer comparison": comparable peers are checkboxes; peers of another discipline are listed
  /// as plain text with the reason, never as controls that cannot be used.
  Widget _peerChooser() {
    final t = _targets;
    if (t == null) {
      return Text('The list of peer curricula is unavailable; the supplied peers of the same discipline are used.',
          style: AppTypography.caption);
    }
    final peers = asList(t['peers']).map(asMap).toList();
    if (peers.isEmpty) return Text('No peer curriculum has been supplied.', style: AppTypography.caption);
    if (_c('discipline').text.trim().isEmpty) {
      return Text('Enter the discipline above to choose which peers to compare with.', style: AppTypography.caption);
    }
    final chosen = draft.peerIds ?? const <String>{};
    final usable = peers.where((p) => p['comparable'] == true).toList();
    final other = peers.where((p) => p['comparable'] != true).toList();
    String name(Map<String, dynamic> p) => [fmt(p['institution']), fmt(p['programme'])].join(' · ');
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (usable.isNotEmpty) ...[
        Text('Compare with (${chosen.length} of ${usable.length} chosen):', style: AppTypography.caption),
        for (final p in usable)
          CheckboxListTile(
            dense: true,
            contentPadding: const EdgeInsets.only(left: AppSpacing.lg),
            controlAffinity: ListTileControlAffinity.leading,
            value: chosen.contains(fmt(p['doc_id'])),
            onChanged: _uploading
                ? null
                : (v) => setState(() {
                      final ids = {...?draft.peerIds};
                      v == true ? ids.add(fmt(p['doc_id'])) : ids.remove(fmt(p['doc_id']));
                      draft.peerIds = ids;
                    }),
            title: Text(name(p), style: AppTypography.body),
            subtitle: Text([fmt(p['discipline']), if (p['academic_year'] != null) fmt(p['academic_year'])].join('   '),
                style: AppTypography.caption),
          ),
      ],
      if (other.isNotEmpty) ...[
        SizedBox(height: AppSpacing.sm),
        Text(usable.isEmpty ? 'Supplied peer curricula, none of this discipline:' : 'Not comparable with this curriculum:',
            style: AppTypography.caption),
        for (final p in other)
          Padding(
            padding: const EdgeInsets.only(left: AppSpacing.lg, top: AppSpacing.xs),
            child: Text('${name(p)} (${fmt(p['discipline'])}): not comparable, ${fmt(p['reason'] ?? 'another discipline')}',
                style: AppTypography.caption),
          ),
      ],
    ]);
  }

  Widget _analysisOptions() {
    final noPeers = _comparablePeerCount() == 0;
    return SplitRow(
      leftFlex: 3,
      rightFlex: 7,
      left: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('What the analysis includes', style: AppTypography.title),
        SizedBox(height: AppSpacing.sm),
        Text('The curriculum is always analysed on its own. Comparisons are added when their evidence exists; you can '
            'leave them out for a faster, curriculum-only result.', style: AppTypography.muted),
      ]),
      right: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        CheckboxListTile(
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          value: draft.includeIndustry,
          onChanged: _uploading ? null : (v) => setState(() => draft.includeIndustry = v ?? true),
          title: Text('Industry evidence', style: AppTypography.body),
          subtitle: Text('Job-posting demand, skill gaps and recommendations. Without it, no gap or recommendation '
              'is produced.', style: AppTypography.caption),
        ),
        CheckboxListTile(
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          value: noPeers ? false : draft.includePeers,
          onChanged: _uploading || noPeers ? null : (v) => setState(() => draft.includePeers = v ?? true),
          title: Text('Peer comparison', style: AppTypography.body),
          subtitle: Text(
              noPeers
                  ? 'Not available for this discipline: none of the peer curricula in this installation is of it, and '
                      'a curriculum of another discipline is never used as a peer.'
                  : 'Compares with peer curricula of the same discipline that you choose. Another '
                      'institution\'s curriculum is never used in place of yours or of a peer you chose.',
              style: AppTypography.caption),
        ),
        if (draft.includePeers || noPeers) _peerChooser(),
      ]),
    );
  }

  Widget _industryForm() {
    final formats = asList(_formats?['formats']);
    return SplitRow(
      leftFlex: 3,
      rightFlex: 7,
      left: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('About the postings', style: AppTypography.title),
        SizedBox(height: AppSpacing.sm),
        Text('Choose the column layout of your CSV file. The application reads only the file you upload; it does not '
            'connect to, log in to or collect from any job platform.', style: AppTypography.muted),
      ]),
      right: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (formats.isEmpty)
          Text('File formats are unavailable (the upload service is not running).', style: AppTypography.caption)
        else
          Wrap(spacing: AppSpacing.md, runSpacing: AppSpacing.md, children: [
            for (final f in formats)
              ChoiceChip(
                label: Text(fmt(at(f, 'label'))),
                selected: draft.preset == at(f, 'preset'),
                onSelected: (_) => setState(() => draft.preset = fmt(at(f, 'preset'))),
              ),
          ]),
        const SizedBox(height: AppSpacing.lg),
        Wrap(spacing: AppSpacing.lg, runSpacing: AppSpacing.lg, children: [
          _field('source_name', requiredField: true, hint: 'Where the file came from'),
          _field('licence_note', requiredField: true, hint: 'Licence or terms of use'),
          _field('source_url'),
        ]),
      ]),
    );
  }

  Widget _fileAndSubmit() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.xl),
      decoration: BoxDecoration(borderRadius: AppRadius.card, color: AppColors.surface),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(_file == null ? 'Choose a file' : _file!.name, style: AppTypography.headline),
        const SizedBox(height: AppSpacing.xs),
        Text(
            _file == null
                ? (_kind == 'INDUSTRY' ? 'A CSV file of job postings.' : 'A text-based PDF or TXT curriculum.')
                : '${fmtCount(_file!.bytes.length)} bytes · kept while you use other pages; a browser reload clears '
                    'the form, so choose the file again after one',
            style: AppTypography.caption),
        const SizedBox(height: AppSpacing.lg),
        OutlinedButton.icon(
            onPressed: _uploading ? null : _pick,
            icon: const Icon(Icons.attach_file, size: 16),
            label: Text(_file == null ? 'Choose file' : 'Choose another file')),
      ]),
    );
  }

  Widget _submitRow() {
    final missing = _missing;
    if (_uploading) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        LinearProgressIndicator(),
        SizedBox(height: AppSpacing.sm),
        Text('Uploading and processing — the server extracts and validates the document…', style: AppTypography.muted),
      ]);
    }
    return Wrap(spacing: AppSpacing.md, runSpacing: AppSpacing.sm, crossAxisAlignment: WrapCrossAlignment.center, children: [
      FilledButton(
        onPressed: _file != null && missing.isEmpty ? _upload : null,
        child: const Text('Upload and extract'),
      ),
      if (_file == null)
        Text('Choose a file first.', style: AppTypography.caption)
      else if (missing.isNotEmpty)
        Text('Still needed: ${missing.map(_fieldLabel).join(', ')}', style: AppTypography.caption),
      if (!draft.isEmpty) TextButton(onPressed: _confirmClear, child: const Text('Clear form')),
    ]);
  }
}

/// The evidence workflow as a progress line: Select source → Upload evidence → Processing → Validation → Analysis.
class WorkflowSteps extends StatelessWidget {
  const WorkflowSteps({super.key, required this.current});
  final int current;
  static const steps = ['Select source', 'Upload evidence', 'Processing', 'Validation', 'Analysis'];

  @override
  Widget build(BuildContext context) {
    final reduce = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    return LayoutBuilder(builder: (context, box) {
      final fraction = (current.clamp(0, steps.length - 1)) / (steps.length - 1);
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Stack(children: [
          Container(height: 1, color: AppColors.border),
          AnimatedContainer(
            duration: reduce ? Duration.zero : AppMotion.complex,
            curve: AppMotion.curve,
            height: 2,
            width: box.maxWidth * fraction,
            color: AppColors.primary,
          ),
        ]),
        const SizedBox(height: AppSpacing.sm),
        Wrap(spacing: AppSpacing.xl, runSpacing: AppSpacing.xs, children: [
          for (var i = 0; i < steps.length; i++)
            Semantics(
              label: '${steps[i]}${i == current ? ', current step' : i < current ? ', done' : ''}',
              child: Text('${i + 1}  ${steps[i]}',
                  style: AppTypography.muted.copyWith(
                      color: i == current ? AppColors.text : (i < current ? AppColors.textMuted : AppColors.textFaint),
                      fontWeight: i == current ? FontWeight.w600 : FontWeight.w400)),
            ),
        ]),
      ]);
    });
  }
}

/// The ingestion result as a decision. Execution, extraction, quality and review status are shown separately, the
/// headline comes from the backend's single interpretation, and ids are never the primary result.
class IngestionResultView extends StatelessWidget {
  const IngestionResultView({
    super.key,
    required this.result,
    required this.kind,
    required this.onAnalyse,
    required this.onReview,
    required this.onDashboard,
    required this.onAnother,
    this.reviewer,
  });
  final Map<String, dynamic> result;
  final String kind;
  final void Function({String? reviewedBy}) onAnalyse;
  final VoidCallback onReview;
  final VoidCallback onDashboard;
  final VoidCallback onAnother;
  final TextEditingController? reviewer;

  @override
  Widget build(BuildContext context) {
    final o = asMap(result['outcome']);
    final outcome = fmt(o['outcome'] ?? (result['status'] == 'failed' ? 'EXECUTION_FAILED' : null));
    final counts = asMap(o['counts']);
    final ready = outcome == 'SUCCESSFUL_AND_USABLE';
    // three states never collapse into one "succeeded/failed" field (see the ingestion acceptance test)
    final headline = ready
        ? (kind == 'INDUSTRY' ? 'Industry evidence added' : 'Curriculum evidence added')
        : outcome == 'EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT'
            ? 'Processing completed, but no usable curriculum content was extracted — review required'
            : outcome == 'EXECUTION_FAILED'
                ? 'Processing failed — review error details'
                : outcome == 'NEEDS_REVIEW'
                    ? 'Extracted, but it needs review before analysis'
                    : fmt(o['headline'] ?? 'Result recorded');
    final conf = o['extraction_confidence'];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      StatusBadge(outcome),
      const SizedBox(height: AppSpacing.md),
      Text(headline, style: AppTypography.display),
      if (o['headline'] != null && headline != o['headline']) ...[
        const SizedBox(height: AppSpacing.sm),
        Text(Plain.sentence(fmt(o['headline'])), style: AppTypography.lede),
      ],
      const SizedBox(height: AppSpacing.xl),
      if (counts.isNotEmpty)
        Wrap(spacing: AppSpacing.xxl, runSpacing: AppSpacing.lg, children: [
          for (final e in counts.entries)
            _figure(fmtCount(e.value), e.key == 'topics_unattributed' ? 'topics in no course' : e.key),
          // share of pages where any course, unit or topic was read: text coverage, not proof that courses were found
          if (conf is num) _figure('${(conf * 100).round()}%', 'pages with recognised text'),
        ]),
      const SizedBox(height: AppSpacing.xl),
      SectionCard(
        title: 'Status',
        child: KeyValueList([
          MapEntry('Overall', outcome),
          MapEntry('Processing', _human(o['execution_status'])),
          MapEntry('Extraction', _human(o['extraction_status'])),
          if (o['structuring_status'] != null) MapEntry('Course structure', _human(o['structuring_status'])),
          MapEntry('Document quality', _human(o['quality_status'])),
          MapEntry('Review', _human(o['review_status'])),
          MapEntry('What you can do', o['next_action'] == null ? null : Plain.sentence(o['next_action'])),
        ]),
      ),
      if (asList(o['reasons']).isNotEmpty)
        SectionCard(
          title: 'Why',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final r in asList(o['reasons'])) Text('— ${Plain.sentence(fmt(r))}', style: AppTypography.body),
          ]),
        ),
      if (asList(at(result, 'metadata.missing_recommended')).isNotEmpty)
        Text('Metadata that would help: ${asList(at(result, 'metadata.missing_recommended')).map(fmt).join(', ')}',
            style: AppTypography.caption),
      const SizedBox(height: AppSpacing.lg),
      Wrap(spacing: AppSpacing.md, runSpacing: AppSpacing.sm, children: [
        if (ready && kind != 'INDUSTRY' && kind != 'GENERAL_REFERENCE')
          FilledButton(onPressed: () => onAnalyse(), child: const Text('Open curriculum intelligence →')),
        if (outcome == 'NEEDS_REVIEW' || outcome == 'EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT') ...[
          FilledButton(onPressed: onReview, child: const Text('Review extraction')),
          OutlinedButton(onPressed: onReview, child: const Text('View preprocessing')),
        ],
        OutlinedButton(onPressed: onDashboard, child: const Text('Return to dashboard')),
        TextButton(onPressed: onAnother, child: const Text('Add another file')),
      ]),
      if (outcome == 'NEEDS_REVIEW' && kind != 'INDUSTRY' && reviewer != null) ...[
        const SizedBox(height: AppSpacing.xl),
        SectionCard(
          title: 'Accept after review',
          subtitle: 'Only after you have checked the extraction: your name is recorded with the analysis.',
          child: Wrap(spacing: AppSpacing.md, crossAxisAlignment: WrapCrossAlignment.center, children: [
            SizedBox(
                width: 280, child: TextField(controller: reviewer, decoration: const InputDecoration(labelText: 'Reviewed by'))),
            OutlinedButton(
                onPressed: () {
                  final name = reviewer!.text.trim();
                  if (name.isNotEmpty) onAnalyse(reviewedBy: name);
                },
                child: const Text('Analyse this curriculum')),
          ]),
        ),
      ],
      const SizedBox(height: AppSpacing.xl),
      RawDetails(data: result),
    ]);
  }

  /// Known status codes stay codes (rendered as a labelled tag); other codes are written in sentence case.
  static dynamic _human(dynamic v) {
    if (v is! String) return v ?? '—';
    return StatusStyle.isKnown(v) ? v : StatusStyle.label(v);
  }

  Widget _figure(String value, String label) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(value, style: AppTypography.metric),
        Text(label, style: AppTypography.caption),
      ]);
}

/// "Upload failed" in human words; the technical details are collapsed; Retry.
class UploadFailedView extends StatelessWidget {
  const UploadFailedView({super.key, required this.error, required this.onRetry});
  final Object? error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final e = error;
    final human = e is ApiException
        ? (e.code == 'METADATA_INCOMPLETE'
            ? 'Some required information about the document is missing: ${e.message}'
            : e.code == 'UNSUPPORTED_FILE_TYPE'
                ? 'This file type is not accepted here.'
                : e.code == 'FILE_TOO_LARGE'
                    ? 'The file is larger than the upload limit.'
                    : Plain.sentence(e.message))
        : 'The upload service could not be reached.';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const StatusBadge('EXECUTION_FAILED'),
      const SizedBox(height: AppSpacing.md),
      Text('Upload failed', style: AppTypography.display),
      const SizedBox(height: AppSpacing.sm),
      Text(human, style: AppTypography.lede),
      const SizedBox(height: AppSpacing.lg),
      FilledButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh, size: 16), label: const Text('Retry')),
      const SizedBox(height: AppSpacing.lg),
      RawDetails(
          title: 'Technical details',
          data: e is ApiException
              ? {'status': e.statusCode, 'code': e.code, 'message': e.message, 'request_id': e.requestId, 'details': e.details}
              : {'error': '$e'}),
    ]);
  }
}

/// Administrator view of the raw payload, collapsed by default.
class RawDetails extends StatelessWidget {
  const RawDetails({super.key, required this.data, this.title = 'Technical details'});
  final Map<String, dynamic> data;
  final String title;

  @override
  Widget build(BuildContext context) {
    return EvidencePanel(
      title: title,
      summary: 'for administrators',
      children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(AppSpacing.md),
          color: AppColors.surfaceSunken,
          child: SelectableText(const JsonEncoder.withIndent('  ').convert(data), style: AppTypography.mono),
        ),
      ],
    );
  }
}
