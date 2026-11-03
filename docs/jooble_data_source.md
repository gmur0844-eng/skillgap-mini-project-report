# Jooble (India) Data Source

## Status: BLOCKED at Phase 3 (the real validation request). No real Jooble data has been acquired, and per this project's own gating rule (Phase 7: "only if Phase 1-6 succeed"), no adapter was built.

## 1. Source
Jooble (https://jooble.org), a job search aggregator. Would use the
**existing** `JobPosting` model and `DataSource` provenance system -- no new
model was created or needed, mirroring the Naukri source already in this
project.

## 2. Endpoint (from public documentation -- not independently confirmed by a live call)
```
POST https://in.jooble.org/api/{key}
Content-Type: application/json
Body: {"keywords": "software engineer", "location": "India", "page": 1}
```
The key is part of the URL **path**, not a header, and the call is a
**POST with a JSON body** -- not a GET with query parameters. Jooble issues
keys per country-subdomain (a `jooble.org` key and an `in.jooble.org` key
are reportedly distinct), which is why the India subdomain specifically was
used for `JOOBLE_API_BASE_URL`.

## 3. Why Phase 3 could not run

| Check | Result |
|---|---|
| `curl -D - https://jooble.org` from this sandbox | Blocked: `x-deny-reason: host_not_allowed`, "Host not in allowlist: jooble.org" |
| `curl -D - https://in.jooble.org` from this sandbox | Same block, confirmed separately |
| `web_fetch` as an alternative | Cannot send a POST body; it is a read-only page-content GET fetcher, structurally incapable of calling this API even if the host were reachable |

This is a **sandbox network restriction**, not a Jooble-side failure and not
a decoding/authentication problem (contrast with the NCS source, which is
blocked for a different reason -- see `docs/ncs_data_source.md`).

## 4. The API key

A key was provided in chat. It was **not used** (no request could be sent),
**not printed**, **not logged**, and **not written to any file in this
repository** -- confirmed by grep after this session's changes. The only
places Jooble configuration exists are `.env.example` (empty placeholder)
and `Settings.jooble_api_key` (empty string default, loaded from the
environment at runtime only).

## 5. What the public documentation (not a live call) suggests about suitability

Cited here only as documentation research, explicitly **not** verified
against a real response, and not to be confused with an actual Phase 6
determination:
- Free API keys have a **lifetime limit of 500 requests**.
- Independent third-party technical write-ups (analyzing the real API's
  behavior, not Jooble's own marketing) describe the response as containing
  **truncated description snippets, not full job descriptions**. If
  accurate, this would matter directly for Phase 6 (skill-extraction
  suitability) -- but this project's own rule is that an unverified
  third-party characterization is never treated as authoritative, so this
  is noted as something to check on the FIRST real call, not assumed.

## 6. Formal Phase 6 decision

**NOT MADE.** Phase 6 requires an observed real response; none exists.
Do not read anything above as SUITABLE / PARTIALLY SUITABLE / NOT SUITABLE.

## 7. What would unblock this

`in.jooble.org` (and `jooble.org`) added to this environment's network
egress allowlist, or this validation step run from an environment that has
outbound internet access, using the key already provided (which remains
valid and unused).

## 8. Reproducibility (once unblocked)

```bash
export JOOBLE_API_KEY="<the real key, never committed>"
curl -s -X POST "https://in.jooble.org/api/${JOOBLE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"keywords": "software engineer", "location": "India", "page": 1}'
```
Then follow this project's Phases 4-6 exactly: save the raw response under
`data/raw/jooble/<run_id>/`, inspect actual fields (not assumed ones), run
the existing skill extraction against real snippet/description text, and
only then make the SUITABLE/PARTIALLY SUITABLE/NOT SUITABLE call.

## 9. Provenance (for when acquisition is unblocked)
Reuses `DataSource`, no schema change: `source_name="Jooble (India)"`,
`source_type="labour_market"` (same convention as Naukri and the planned
NCS source), `source_url="https://in.jooble.org"`, `retrieval_date`.
`JobPosting.external_posting_id` = Jooble's job ID, with the existing
`UniqueConstraint(source_id, external_posting_id)` providing duplicate
protection exactly as it does for every other source.

## 10. Ethical / legal constraints observed
No request was sent. No key was printed, logged, or committed. No scraping
of Jooble's HTML was attempted (correctly avoided per instructions even
before the network block was discovered, since the official API was the
mandated path). No quota was consumed -- 0 of the 500 lifetime requests used.
