import 'dart:convert';
import 'package:http/http.dart' as http;

/// Thin HTTP client for the FastAPI backend. No mock/fake data anywhere here —
/// every method hits a real endpoint and surfaces failures/empty states
/// honestly rather than substituting placeholder numbers.
class ApiClient {
  /// Base URL from `--dart-define=API_URL=...` (default http://localhost:8000).
  ApiClient({this.baseUrl = const String.fromEnvironment('API_URL', defaultValue: 'http://localhost:8000')});

  final String baseUrl;

  /// The analysis run every analytics request is scoped to (null = the latest published run). Set by the shell
  /// after an upload produced a new run, so no screen can silently show an older run's results.
  String? runId;

  static const _unscoped = ['/api/v1/metadata', '/api/v1/analysis', '/api/v1/uploads', '/api/v1/ingestion',
    '/api/v1/data-sources', '/api/v1/data-quality', '/api/v1/pipeline-runs', '/api/v1/jobs', '/api/v1/datasets',
    '/api/v1/evaluation'];

  /// The query actually sent: [query] plus run_id when a run context is set and the path is run-scoped.
  Map<String, String>? scopedQuery(String path, Map<String, String>? query) {
    final id = runId;
    if (id == null || !path.startsWith('/api/v1/') || _unscoped.any(path.startsWith)) return query;
    return {...?query, 'run_id': id};
  }

  /// Generic GET for the read-only knowledge APIs (/api/v1/curriculum, /industry,
  /// /semantic, /intelligence). Returns the decoded JSON body unchanged.
  Future<dynamic> getJson(String path, {Map<String, String>? query}) async {
    final q = scopedQuery(path, query);
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: q);
    final res = await http.get(uri);
    _checkOk(res);
    return jsonDecode(res.body);
  }

  /// Generic JSON POST (analysis jobs).
  Future<dynamic> postJson(String path, Map<String, dynamic> body) async {
    final res = await http.post(Uri.parse('$baseUrl$path'),
        headers: {'Content-Type': 'application/json'}, body: jsonEncode(body));
    _checkOk(res);
    return jsonDecode(res.body);
  }

  Future<Map<String, dynamic>> getDataQuality() async {
    final res = await http.get(Uri.parse('$baseUrl/api/v1/data-quality'));
    _checkOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<List<dynamic>> getDataSources() async {
    final res = await http.get(Uri.parse('$baseUrl/api/v1/data-sources'));
    _checkOk(res);
    return jsonDecode(res.body) as List<dynamic>;
  }

  Future<Map<String, dynamic>> getHealth() async {
    final res = await http.get(Uri.parse('$baseUrl/health'));
    _checkOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<List<dynamic>> getPipelineRuns() async {
    final res = await http.get(Uri.parse('$baseUrl/api/v1/pipeline-runs'));
    _checkOk(res);
    return jsonDecode(res.body) as List<dynamic>;
  }

  Future<Map<String, dynamic>> getPipelineRunDetail(int runId) async {
    final res = await http.get(Uri.parse('$baseUrl/api/v1/pipeline-runs/$runId'));
    _checkOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<List<dynamic>> getDatasets() async {
    final res = await http.get(Uri.parse('$baseUrl/api/v1/datasets'));
    _checkOk(res);
    return jsonDecode(res.body) as List<dynamic>;
  }

  Future<Map<String, dynamic>> getJobs({int limit = 50, int offset = 0}) async {
    final res = await http.get(
      Uri.parse('$baseUrl/api/v1/jobs?limit=$limit&offset=$offset'),
    );
    _checkOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getJobPreview(int jobId) async {
    final res = await http.get(Uri.parse('$baseUrl/api/v1/jobs/$jobId/preview'));
    _checkOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  /// Uploads a job-postings CSV and triggers ingestion. [datasetPreset] must be
  /// one of the backend's known column-map presets ("naukri", "linkedin",
  /// "fixture").
  Future<Map<String, dynamic>> ingestJobPostings({
    required List<int> fileBytes,
    required String fileName,
    required String datasetPreset,
    Map<String, String>? fields,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/ingestion/jobs');
    final request = http.MultipartRequest('POST', uri)
      ..fields['dataset'] = datasetPreset
      ..files.add(http.MultipartFile.fromBytes('file', fileBytes, filename: fileName));
    fields?.forEach((k, v) {
      if (v.trim().isNotEmpty) request.fields[k] = v.trim();
    });
    final streamed = await request.send();
    final res = await http.Response.fromStream(streamed);
    _checkOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> ingestCurriculum({
    required List<int> fileBytes,
    required String fileName,
    String? institution,
    String? programme,
    Map<String, String>? fields,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/ingestion/curriculum');
    final request = http.MultipartRequest('POST', uri)
      ..files.add(http.MultipartFile.fromBytes('file', fileBytes, filename: fileName));
    if (institution != null) request.fields['institution'] = institution;
    if (programme != null) request.fields['programme'] = programme;
    fields?.forEach((k, v) {
      if (v.trim().isNotEmpty) request.fields[k] = v.trim();
    });
    final streamed = await request.send();
    final res = await http.Response.fromStream(streamed);
    _checkOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  /// Metadata suggestions read from a curriculum's first pages (POST /api/v1/ingestion/curriculum/inspect). Nothing is
  /// stored on the server; the suggestions only pre-fill the form.
  Future<Map<String, dynamic>> inspectCurriculum({required List<int> fileBytes, required String fileName}) async {
    final request = http.MultipartRequest('POST', Uri.parse('$baseUrl/api/v1/ingestion/curriculum/inspect'))
      ..files.add(http.MultipartFile.fromBytes('file', fileBytes, filename: fileName));
    final res = await http.Response.fromStream(await request.send());
    _checkOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  void _checkOk(http.Response res) {
    if (res.statusCode < 200 || res.statusCode >= 300) {
      // the backend answers errors as {"error","code","message","details","request_id"}
      String? code, message, requestId;
      dynamic details;
      try {
        final body = jsonDecode(res.body);
        if (body is Map<String, dynamic>) {
          code = body['code']?.toString();
          message = body['message']?.toString();
          requestId = body['request_id']?.toString();
          details = body['details'];
        }
      } catch (_) {}
      throw ApiException(message ?? 'Request failed (${res.statusCode})',
          statusCode: res.statusCode, code: code, requestId: requestId, details: details);
    }
  }
}

class ApiException implements Exception {
  ApiException(this.message, {this.statusCode, this.code, this.requestId, this.details});
  final String message;
  final int? statusCode;
  final String? code;
  final String? requestId;
  final dynamic details; // structured detail from the API (shown only in technical views)

  /// One line for the UI: HTTP status, machine code and message (no stack traces exist in the API's errors).
  String describe() => [
        if (statusCode != null) 'HTTP $statusCode',
        if (code != null) code!,
        message,
        if (requestId != null) '(request $requestId)',
      ].join(' · ');

  @override
  String toString() => describe();
}
