/// The Add evidence form as a draft that outlives the page.
///
/// The draft belongs to the analysis context (one per app session), so leaving Add evidence and coming back keeps
/// what was chosen and typed: the kind of evidence, every field, the chosen file (its bytes stay in memory), the
/// document's metadata suggestions and the analysis options. It is cleared only after a successful upload is followed
/// by "Add another file", or by an explicit, confirmed "Clear form".
///
/// Honest limit: browsers do not let a page keep a chosen file across a reload, and this draft lives in memory; a
/// page reload starts an empty form (the form says so next to the file).
library;

/// A file chosen for upload (bytes + name). Tests inject a picker through IngestionScreen.debugPicker.
class PickedUpload {
  const PickedUpload(this.name, this.bytes);
  final String name;
  final List<int> bytes;
}

class EvidenceDraft {
  String kind = 'TARGET';
  String preset = 'naukri';
  final Map<String, String> values = {};
  PickedUpload? file;

  /// The last upload's result, kept so returning to the page shows it until the person moves on.
  Map<String, dynamic>? result;

  /// Metadata suggestions read from [file]'s first pages ({field: suggestion}); see the inspect endpoint.
  Map<String, dynamic> suggestions = {};

  /// Fields whose current value was filled from a suggestion and not edited since.
  final Set<String> suggested = {};

  /// Optional parts of a curriculum's analysis (both are used when their evidence exists).
  bool includePeers = true;
  bool includeIndustry = true;

  /// The peers chosen for comparison (doc ids), or null when no choice was offered (the list of comparison targets
  /// could not be read): then the server uses the supplied peers of the same discipline. An empty choice means no
  /// peer comparison. A chosen peer is never replaced by another.
  Set<String>? peerIds;

  /// Nothing worth warning about before it is discarded.
  bool get isEmpty =>
      file == null && result == null && values.values.every((v) => v.trim().isEmpty) && includePeers && includeIndustry;

  Map<String, dynamic> get options {
    final chosen = peerIds;
    final peers = includePeers && (chosen == null || chosen.isNotEmpty);
    return {
      'peers': peers,
      'industry': includeIndustry,
      if (peers && chosen != null) 'peer_ids': chosen.toList()..sort(),
    };
  }

  void clear() {
    kind = 'TARGET';
    preset = 'naukri';
    values.clear();
    file = null;
    result = null;
    suggestions = {};
    suggested.clear();
    includePeers = true;
    includeIndustry = true;
    peerIds = null;
  }
}
