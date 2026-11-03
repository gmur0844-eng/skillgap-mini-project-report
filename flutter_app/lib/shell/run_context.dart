import 'dart:async';

import 'package:flutter/widgets.dart';

import '../services/api_client.dart';
import 'evidence_draft.dart';

/// Which analysis the dashboard shows. States follow the backend's analysis-job vocabulary:
///   LATEST            the latest published run (no upload in this session)
///   ANALYSIS_PENDING  an uploaded curriculum is being analysed -- the dashboard shows the pending state, never an
///                     older run's results
///   ANALYSIS_READY    the new run exists; every request is scoped to it (ApiClient.runId)
///   ANALYSIS_NOT_RUN  the upload is extracted, but analysis could not be started here (Run analysis is offered)
///   ANALYSIS_FAILED / NEEDS_REVIEW   the analysis ended without a usable run (reason shown)
///
/// The analysis job is the source of truth: the backend persists its live phases (built from the pipeline's real
/// stage events), so any page can show them, the person can move around the app while it runs, and after a page
/// reload [recover] finds the running job again. The job record is read once a second ([pollInterval]); the backend
/// also offers the same record as Server-Sent Events (/events) for clients that can stream.
class AnalysisContext extends ChangeNotifier {
  AnalysisContext(this.api, {this.pollInterval = const Duration(seconds: 1)});
  final ApiClient api;
  final Duration pollInterval;

  /// The Add evidence form, kept for the whole session (see EvidenceDraft).
  final EvidenceDraft draft = EvidenceDraft();

  String status = 'LATEST';
  Map<String, dynamic>? upload; // the ingestion result of the uploaded document (counts, metadata, outcome)
  Map<String, dynamic>? job; // the analysis job record
  String? reason;
  Timer? _timer;
  bool _disposed = false;

  String? get runId => api.runId;
  bool get blocksOldResults => status == 'ANALYSIS_PENDING' || status == 'ANALYSIS_NOT_RUN' ||
      status == 'ANALYSIS_FAILED' || status == 'NEEDS_REVIEW';

  void _set(String s, {String? why}) {
    status = s;
    reason = why;
    if (!_disposed) notifyListeners();
  }

  /// A usable upload: start its analysis. When the job cannot be started here the dashboard stays scoped to the
  /// upload with ANALYSIS_NOT_RUN (and offers Run analysis) -- it never falls back to the old run silently.
  /// The options the current analysis was started with ({'peers': bool, 'industry': bool, 'peer_ids'?: [ids]}),
  /// null = defaults.
  Map<String, dynamic>? options;

  /// A job record's options as sent ({'peers': bool, 'industry': bool} plus the chosen peers, when any).
  static Map<String, dynamic>? optionsOf(dynamic o) {
    if (o is! Map) return null;
    return {
      for (final e in o.entries)
        if (e.value is bool) e.key.toString(): e.value as bool
        else if (e.key == 'peer_ids' && e.value is List) 'peer_ids': [for (final v in e.value as List) v.toString()],
    };
  }

  Future<void> analyseUpload(Map<String, dynamic> ingestion, {String? reviewedBy, Map<String, dynamic>? options}) async {
    upload = ingestion;
    job = null;
    this.options = options;
    _timer?.cancel();
    final id = ingestion['upload_id']?.toString();
    if (id == null) {
      _set('ANALYSIS_NOT_RUN', why: 'the upload was not staged for analysis');
      return;
    }
    _set('ANALYSIS_PENDING');
    try {
      final res = await api.postJson('/api/v1/analysis/jobs', {
        'upload_id': id,
        if (reviewedBy != null) 'reviewed_by': reviewedBy,
        if (options != null) 'options': options,
      });
      job = res is Map<String, dynamic> ? res : null;
      _poll();
    } on ApiException catch (e) {
      _set('ANALYSIS_NOT_RUN', why: e.message);
    } catch (_) {
      _set('ANALYSIS_NOT_RUN', why: 'the analysis service is unavailable');
    }
  }

  /// Run the analysis again: a finished job is retried by the server with the same options and reviewer; without a
  /// job (it could not be started) the upload is submitted again.
  Future<void> retry() async {
    final id = job?['job_id']?.toString();
    final s = job?['status']?.toString();
    if (id != null && (s == 'ANALYSIS_FAILED' || s == 'NEEDS_REVIEW')) {
      _timer?.cancel();
      _set('ANALYSIS_PENDING');
      try {
        final res = await api.postJson('/api/v1/analysis/jobs/$id/retry', const {});
        job = res is Map<String, dynamic> ? res : job;
        _poll();
      } on ApiException catch (e) {
        _set('ANALYSIS_NOT_RUN', why: e.message);
      } catch (_) {
        _set('ANALYSIS_NOT_RUN', why: 'the analysis service is unavailable');
      }
      return;
    }
    final u = upload;
    if (u != null) await analyseUpload(u, options: options);
  }

  /// After a page reload: if the server is running an analysis, follow it again. Its upload's metadata is loaded so
  /// the page can say which curriculum it is. Silent when nothing runs or the service is unreachable.
  Future<void> recover() async {
    if (status != 'LATEST') return;
    try {
      final res = await api.getJson('/api/v1/analysis/jobs/active');
      final active = res is Map<String, dynamic> ? res['job'] : null;
      if (active is! Map<String, dynamic> || _disposed || status != 'LATEST') return;
      job = active;
      options = optionsOf(active['options']) ?? options;
      final uploadId = active['upload_id']?.toString();
      if (uploadId != null) {
        try {
          final up = await api.getJson('/api/v1/uploads/$uploadId');
          if (up is Map<String, dynamic>) {
            upload = {'upload_id': uploadId, 'outcome': up['outcome'], 'metadata': {'values': up['metadata']}};
          }
        } catch (_) {}
      }
      if (_disposed) return;
      _set('ANALYSIS_PENDING');
      _poll();
    } catch (_) {
      // no active job information: nothing to recover
    }
  }

  void _poll() {
    final id = job?['job_id']?.toString();
    if (id == null) {
      _set('ANALYSIS_NOT_RUN', why: 'no analysis job was created');
      return;
    }
    Future<void> check() async {
      try {
        final res = await api.getJson('/api/v1/analysis/jobs/$id');
        if (_disposed) return;
        job = res is Map<String, dynamic> ? res : job;
        reason = null;
        final s = job?['status']?.toString();
        if (s == 'ANALYSIS_READY' && job?['run_id'] != null) {
          api.runId = job!['run_id'].toString();
          _set('ANALYSIS_READY');
          return;
        }
        if (s == 'ANALYSIS_FAILED' || s == 'NEEDS_REVIEW') {
          _set(s!, why: job?['reason']?.toString());
          return;
        }
      } on ApiException catch (e) {
        // the job endpoint is temporarily unavailable: keep the pending state (no stale data), keep checking
        reason = 'analysis status unavailable (${e.message}); retrying';
        if (!_disposed) notifyListeners();
      } catch (_) {
        reason = 'analysis status unavailable; retrying';
        if (!_disposed) notifyListeners();
      }
      if (!_disposed && status == 'ANALYSIS_PENDING') {
        notifyListeners(); // live phases changed
        _timer = Timer(pollInterval, check);
      }
    }

    check();
  }

  /// Open a finished analysis from History: every page is scoped to its run (explicit user choice). Only a job that
  /// is ready can be opened; one that failed or needs review shows its reason and can be run again ([retryJob]).
  bool openJob(Map<String, dynamic> record) {
    final runId = record['run_id']?.toString();
    if (runId == null || runId.isEmpty) return false;
    if (record['status']?.toString() != 'ANALYSIS_READY') return false;
    _timer?.cancel();
    job = record;
    options = optionsOf(record['options']);
    final doc = asMapOrNull(record['document']);
    upload = {'upload_id': record['upload_id'], 'metadata': {'values': doc ?? const {}}};
    api.runId = runId;
    _set('ANALYSIS_READY');
    return true;
  }

  /// Run a failed or reviewed job again from History (the server keeps its options and reviewer).
  Future<void> retryJob(Map<String, dynamic> record) async {
    _timer?.cancel();
    job = record;
    options = optionsOf(record['options']);
    final doc = asMapOrNull(record['document']);
    upload = {'upload_id': record['upload_id'], 'metadata': {'values': doc ?? const {}}};
    await retry();
  }

  static Map<String, dynamic>? asMapOrNull(dynamic v) =>
      v is Map ? {for (final e in v.entries) e.key.toString(): e.value} : null;

  /// Back to the latest published run (explicit user choice).
  void showLatest() {
    _timer?.cancel();
    api.runId = null;
    upload = null;
    job = null;
    options = null;
    _set('LATEST');
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}

/// Makes the analysis context available to every page.
class RunScope extends InheritedNotifier<AnalysisContext> {
  const RunScope({super.key, required AnalysisContext context, required super.child}) : super(notifier: context);

  static AnalysisContext? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<RunScope>()?.notifier;
}
