# UI consistency remediation

This source update addresses the authenticated all-page Edge audit. It preserves
the existing Operate theme and the typography and Resource Health control fixes
already merged in PR #367. Source qualification does not establish acceptance of
the deployed release.

## Shared interaction rules

- Pagination controls use the shared control-height token: 40px on desktop and
  44px on narrower layouts, with 14px control text.
- Connection readiness selectors use the existing themed form-control pattern.
- Header signals wrap between meaningful segments rather than splitting words.
- Exposure detail Copilot buttons remain square icon controls on mobile; ordinary
  full-width actions retain their existing behavior.
- Arrow, Home, and End navigation reveal the selected tab inside scrollable tab
  strips while retaining the existing roving-focus behavior.

## Evidence and unavailable states

- FinOps waste-type bars count returned waste records. They do not convert
  unknown savings to zero or add monetary values across currencies.
- Installed Software does not show successful zero summaries or an empty-success
  panel when the provider is unavailable. Partial observations remain visible
  with their source qualification.
- Resource Health distinguishes returned health responses from resources with CPU
  samples. Its page insight is grounded in the submitted, scope-validated Health
  snapshot rather than a generic incident investigation. Browser observations are
  qualified evidence, not independent verification of Azure health.
- Digital Twin provides an explicit instructional detail state before selection;
  it does not silently select an entity.

## Progressive disclosure

Change observations keep resource and change type visible; identifiers and mapping
metadata remain available in a disclosure. Fabric ingestion history paginates all
returned attempts, preserves their order, and reports failure totals over the
returned set. Large patch-review lists collapse the duplicate selection form;
readiness, errors, and recorded review history remain outside the disclosure.
Expanding or selecting patches never creates or approves a review automatically.

## Release boundary

### Wide-screen follow-up

The operational page canvas grows to a bounded 1920px rather than stopping at
1440px. Inventory narrative sections share readable columns once the containing
panel reaches 960px; long narrative paragraphs retain the 75ch reading measure.
Shared card descriptions use their available header width, and partial/stale/error
notices place the symbol beside the message instead of reserving a tall, mostly
empty panel. Empty and loading states retain their existing centered treatment.
This changes layout only, not evidence, scope, actions, or factual copy. Regression
coverage includes 1912px and 2560px as well as the existing mobile widths.

Compliance score inversion and shared prose spacing were already corrected in
the baseline and are deliberately not reimplemented here. Their live outcome,
and the outcome of this update, require a separately authorized release and
authenticated Edge recheck against the exact deployed revision. No deployment,
cloud configuration change, or execution-policy change is part of this update.
