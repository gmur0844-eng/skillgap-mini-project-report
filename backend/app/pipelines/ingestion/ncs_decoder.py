"""
NCS response decoder -- INTENTIONALLY NOT IMPLEMENTED.

STATUS: blocked at the acquisition/decoding step. See docs/ncs_data_source.md
for the full investigation. Summary:

- This sandbox cannot make the required POST request to
  https://api.ncs.gov.in/api/v1/job-posts/search (bash network egress is
  restricted by an allowlist that does not include api.ncs.gov.in; direct
  curl attempt confirmed this).
- No browser/DevTools/JavaScript-execution capability is available to
  inspect NCS's first-party client-side decoding logic.
- web_fetch only returns a client-rendered page's stripped-down markdown
  (no job data, no script source) and cannot send a POST body.
- The only characterization of the response envelope found anywhere
  ("AES-256-CBC") comes from a third-party commercial scraper's marketing
  page (Apify "NCS Jobs Scraper"), NOT from official NCS client code. Per
  this project's explicit rule, a third-party "NCS API decryptor" claim is
  never treated as authoritative, so it is NOT implemented here.

This module exists only as the documented landing point for a future,
properly-verified implementation -- e.g. once a human with real browser
access captures the official frontend's actual transform function (HAR
export + the relevant JS source, or a confirmed reproduction of the
official client's decode step). When that evidence exists, implement
decode_ncs_response() here, matching the shape ingest_core_knowledge.py's
loaders use elsewhere in this project (a small, isolated, format-in/
record-out function), and cite the exact evidence (file, version/date
inspected) in its docstring -- do not guess.
"""


def decode_ncs_response(raw_response_bytes: bytes) -> list:
    """
    NOT IMPLEMENTED. Raises deliberately rather than guessing a decoding
    method. See this module's docstring and docs/ncs_data_source.md for why.
    """
    raise NotImplementedError(
        "NCS response decoding is blocked: no verified, first-party evidence of the "
        "official client's decoding logic is available in this environment. "
        "See docs/ncs_data_source.md for the full investigation and what would unblock this."
    )
