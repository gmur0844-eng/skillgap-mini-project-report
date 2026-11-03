# NCS (National Career Service) Data Source

## Status: BLOCKED at acquisition/decoding. No real NCS data has been imported.

## 1. NCS's role in this project

NCS (https://ncs.gov.in) would be an additional `JobPosting` source
alongside Naukri, using the **existing** `DataSource` provenance model and
the **existing** `JobPosting` model (`UniqueConstraint(source_id,
external_posting_id)` already supports it) -- no new job model was created
or is needed.

## 2. Endpoint / workflow (as described, not independently verified end-to-end)

```
POST https://api.ncs.gov.in/api/v1/job-posts/search?page=0&size=20
GET  https://api.ncs.gov.in/api/jobs/detail?id={id}   (per a third-party listing; not independently confirmed)
```

## 3. Investigation performed and its outcome

| Avenue | Result |
|---|---|
| Repo search for existing NCS code/HAR/traces | None found -- this is a fresh source, nothing to build on |
| `curl https://api.ncs.gov.in` from this sandbox | **Blocked**: "Host not in allowlist" -- confirmed directly, not assumed |
| `web_fetch https://ncs.gov.in/job-listing` | Returns a stripped, client-rendered markdown view showing "0 Job Posts" -- the tool executes no JavaScript, exposes no `<script>` sources, and cannot send a POST body |
| `web_search` for the official decoding logic | Found only: (a) generic NCS marketing/press pages, (b) generic AES/Angular tutorials unrelated to NCS, and (c) one third-party commercial scraper's marketing page (Apify "NCS Jobs Scraper") that *claims* "the same AES-256-CBC JSON envelope used by the public NCS application" |

## 4. Why the AES-256-CBC claim is not used

The only source characterizing the response encoding is a **third-party
commercial scraper's product page**, not official NCS frontend JavaScript,
not a captured HAR of the real client, and not independently reproducible
from this environment. This project's explicit rule is that a third-party
"NCS API decryptor" claim is never treated as authoritative. No decoder was
written based on it.

## 5. Decoding approach

**None implemented.** `app/pipelines/ingestion/ncs_decoder.py` exists only
as a documented landing point (`decode_ncs_response()` raises
`NotImplementedError` with this same explanation) for a future, properly
evidenced implementation.

## 6. What would unblock this

Any of:
- A HAR capture of a real, logged-in-free NCS search performed by a human with actual browser access, alongside the exact frontend JS bundle that was served for that session.
- Direct inspection (by a human, in DevTools) of the function the official NCS frontend calls immediately after `job-posts/search` returns, with its source quoted or attached.
- Official NCS API documentation, if one is ever published.

None of these are obtainable from this sandboxed environment.

## 7. Provenance (for when acquisition is unblocked)

Reuses the existing `DataSource` model, no schema change needed:
`source_name="National Career Service (NCS)"`, `source_type="labour_market"`
(matching the existing convention already used for Naukri), `source_url`,
`retrieval_date`, `version` = the date/commit of whatever client evidence
was actually inspected.

## 8. Rate limiting, pagination, idempotency

Not applicable yet -- no request has been made. The existing
`UniqueConstraint(source_id, external_posting_id)` on `JobPosting` already
provides duplicate protection for whenever real ingestion begins, exactly
as it does for the existing Naukri path.

## 9. Fields intentionally not retained

Not applicable yet -- no fields have been extracted from any real response.

## 10. Ethical / legal constraints observed

No POST request was sent. No authentication, CAPTCHA, or rate limit was
bypassed or attempted. No brute-forcing occurred. No personal data was
scraped. No secrets, cookies, or session tokens exist in this repository.
