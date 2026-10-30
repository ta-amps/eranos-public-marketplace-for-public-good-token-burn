# Eranos Tracks

Each subfolder `tracks/<track_id>/track.json` defines one public-good build track validated by
[`TrackPack`](../eranos/schemas/tracks.py). Engine code in `eranos/` is domain-neutral and names zero
track IDs; adding a new track is pure data.

## Current tracks

| Track ID | Domain | Focus |
|---|---|---|
| `job-recruitment-triage` | `anti_exploitation` | Cross-border contract & agency fee arithmetic checks paired with human caseworker review |
| `coerced-work-hotline-routing` | `anti_exploitation` | Verified public helpline & consular lookup directories with strict human-only crisis planning |
| `housing-and-charity-verification` | `anti_exploitation` | Rental deposit & disaster-relief charity registry verification checklists |
| `intake-and-referral-triage` | `nonprofit_ops` | Open Referral HSDS community service matching and warm-referral prep |
| `grant-and-compliance-ops` | `nonprofit_ops` | Restricted grant ledger reconciliation & audit-readiness prep for small nonprofits |
| `volunteer-shift-and-sop-builder` | `nonprofit_ops` | Volunteer shift checklists, multilingual role cards, and human escalation SOPs |
| `program-impact-reporting` | `nonprofit_ops` | Monthly program impact reports and funding impact summaries with every figure traced and every gap visible |
| `statement-transcription` | `nonprofit_ops` | Handwritten statements, cards and forms typed exactly as written, with uncertain readings flagged for a person |
