// Workflow Governance Kit — Live-Doc Schema validator library.
//
// This module is the single source of truth for the structural schema of
// `docs/CURRENT-PLAN.md` and `docs/HISTORY-MAP.md`, as defined in §12
// (Live-Doc Schema) and §13 (Canonical Next Step Discipline) of
// `docs/WORKFLOW-GOVERNANCE.md`. Phase 3 will wire the guard checks
// (`checkLiveDocSchema()` + `checkCanonicalNextStep()`) purely through
// this module's public API.
//
// **Behavioral delta vs `scripts/workflow-guard.mjs:100-113`**:
// The existing helpers `extractActiveLane()` and `extractIntegrationBranch()`
// in the guard are legacy parsers that ALSO accept the deprecated
// `Version/lane:` form (per §12.1 deprecation). This library rejects
// `Version/lane:` — only `Lane:` and `Active lane:` are recognised. The
// reconciliation will land in Phase 3 when the guard switches over.
//
// Conformance: the contract this module implements is documented in
// `docs/WORKFLOW-GOVERNANCE.md` §12 + §13. If the two ever disagree, the
// policy doc wins and this module must be brought back into compliance.

// =============================================================================
// 1. Constants — exported (single source of truth for §12 tables)
// =============================================================================

export const PLAN_STATES = Object.freeze({
  ACTIVE: 'active',
  BETWEEN_LANES: 'between-lanes',
  MALFORMED: 'malformed',
});

// Sentinel regex matches the two forms specified in §12.3:
//   `(none — <reason>)`   — em-dash (U+2014)
//   `(none --- <reason>)` — exactly three ASCII hyphens
// En-dash, single hyphen, double hyphen do NOT match. Whitespace around the
// dash is permissive.
export const SENTINEL_REGEX = /^\(none\s*(?:—|---)\s*.+\)$/;

// CURRENT-PLAN.md header block fields per §12.1.
// Each entry: { label, pattern, required }. The pattern is matched against
// raw lines of the header block (text before the first `## ` H2).
export const CURRENT_PLAN_HEADER_FIELDS = Object.freeze([
  { label: 'h1-title', pattern: /^# Current Plan\s*$/, required: true },
  { label: 'status', pattern: /^\*\*Status\*\*:\s*.+$/, required: true },
  { label: 'policy', pattern: /^\*\*Policy\*\*:\s*\[Workflow Governance\]\(WORKFLOW-GOVERNANCE\.md\)\s*$/, required: true },
  { label: 'history-index', pattern: /^\*\*History index\*\*:\s*\[HISTORY-MAP\.md\]\(HISTORY-MAP\.md\)\s*$/, required: true },
  { label: 'integration-branch', pattern: /^(?:\*\*Integration branch\*\*|Integration branch):\s*`[^`]+`/, required: true },
]);

// CURRENT-PLAN.md required H2 sections per §12.1 (9 rows, in order).
// presence values: 'REQUIRED', 'OPTIONAL', 'RECOMMENDED'
export const CURRENT_PLAN_CORE_SECTIONS = Object.freeze([
  { index: 1, canonicalPrefix: 'Active Lane', purpose: 'Identifies current lane or sentinel', requiredWhenActive: 'REQUIRED', requiredWhenBetween: 'REQUIRED' },
  { index: 2, canonicalPrefix: 'Status Graph', purpose: 'Mermaid diagram of current workflow', requiredWhenActive: 'REQUIRED', requiredWhenBetween: 'REQUIRED' },
  { index: 3, canonicalPrefix: 'Baseline Structure', purpose: 'Sub-task/phase table for the active lane', requiredWhenActive: 'REQUIRED', requiredWhenBetween: 'OPTIONAL' },
  { index: 4, canonicalPrefix: 'Canonical Next Step', purpose: 'Single next executable action (see §13)', requiredWhenActive: 'REQUIRED', requiredWhenBetween: 'OPTIONAL' },
  { index: 5, canonicalPrefix: 'Deferred Candidates', purpose: 'Future work not yet promoted', requiredWhenActive: 'OPTIONAL', requiredWhenBetween: 'RECOMMENDED' },
  { index: 6, canonicalPrefix: 'Alternate Governance Actions', purpose: 'Named alternative paths', requiredWhenActive: 'OPTIONAL', requiredWhenBetween: 'OPTIONAL' },
  { index: 7, canonicalPrefix: 'Cleanup / Worktree Disposition', purpose: 'Worktree/branch cleanup state', requiredWhenActive: 'OPTIONAL', requiredWhenBetween: 'OPTIONAL' },
  { index: 8, canonicalPrefix: 'Open Decisions', purpose: 'Decision log table', requiredWhenActive: 'REQUIRED', requiredWhenBetween: 'REQUIRED' },
  { index: 9, canonicalPrefix: 'Explicit Non-Actions', purpose: 'Things explicitly ruled out', requiredWhenActive: 'OPTIONAL', requiredWhenBetween: 'OPTIONAL' },
]);

// HISTORY-MAP.md header block fields per §12.2.
export const HISTORY_MAP_HEADER_FIELDS = Object.freeze([
  { label: 'h1-title', pattern: /^# Project History Map\s*$/, required: true },
  { label: 'status', pattern: /^\*\*Status\*\*:\s*.+$/, required: true },
  { label: 'policy', pattern: /^\*\*Policy\*\*:\s*\[Workflow Governance\]\(WORKFLOW-GOVERNANCE\.md\)\s*$/, required: true },
]);

// HISTORY-MAP.md required H2 sections per §12.2 (6 rows, in order).
export const HISTORY_MAP_CORE_SECTIONS = Object.freeze([
  { index: 1, canonicalPrefix: 'Canonical References', purpose: 'Links to governance doc + current plan', presence: 'REQUIRED' },
  { index: 2, canonicalPrefix: 'Timeline', purpose: 'Mermaid timeline graph', presence: 'REQUIRED' },
  { index: 3, canonicalPrefix: 'Unreleased Workflow Evidence', purpose: 'Pointers to completed-but-unreleased work', presence: 'REQUIRED' },
  { index: 4, canonicalPrefix: 'Backlog Pointer', purpose: 'Link to WORK-BACKLOG.md or its absence', presence: 'REQUIRED' },
  { index: 5, canonicalPrefix: 'Deferred / Candidate Lanes', purpose: 'Table of known future candidates', presence: 'OPTIONAL' },
  { index: 6, canonicalPrefix: 'Cleanup Notes', purpose: 'Historical cleanup context', presence: 'OPTIONAL' },
]);

// =============================================================================
// 2. Diagnostic factory
// =============================================================================

function createDiagnostic(level, code, message, section) {
  const d = { level, code, message };
  if (section !== undefined) d.section = section;
  return d;
}

// =============================================================================
// 3. Internal parsing helpers
// =============================================================================
//
// Known limitations (convention-constrained Markdown only): parsers handle
// the Markdown conventions used by the kit's governance documents. Out of
// scope: pipe characters escaped inside table cells, HTML comments
// containing heading-like text, deeply nested list structures, lists or
// code blocks within table cells. These are not present in kit documents.

// normalizeInput — strips UTF-8 BOM. Idempotent.
function normalizeInput(text) {
  if (typeof text !== 'string') return '';
  return text.replace(/^﻿/, '');
}

// stripFencedCodeBlocks — removes fenced ``` ... ``` blocks. Same regex as
// scripts/workflow-guard.mjs:117.
function stripFencedCodeBlocks(text) {
  return text.replace(/```[\s\S]*?```/g, '');
}

// matchCanonicalPrefix — returns true if heading text starts with the
// canonical prefix and any trailing content is parenthetical/bracketed
// qualifier or whitespace. Per §12.1 rule: "parenthetical or bracketed
// qualifiers appearing AFTER the canonical heading text are permitted and
// ignored by the validator."
function matchCanonicalPrefix(heading, canonicalPrefix) {
  const h = heading.trim();
  if (h === canonicalPrefix) return true;
  if (!h.startsWith(canonicalPrefix)) return false;
  const rest = h.slice(canonicalPrefix.length);
  // Allowed trailing: whitespace, then optional (...) or [...] or em-dash separator
  return /^[\s]*(?:[(\[].*|[——].*)?$/.test(rest);
}

// parseH2Sections — two-pass approach.
//   Pass 1 (heading detection): strip fenced code blocks, then find H2
//     heading positions in the sanitized copy via /^## .+$/m.
//   Pass 2 (body extraction): use each heading's exact text as a unique
//     key to locate the same heading in the original (un-stripped) text via
//     indexOf. Body runs from the line after the heading to the start of
//     the next heading (or EOF). This preserves Mermaid blocks and other
//     fenced content within section bodies.
// Returns an ordered array of { heading, canonicalText, body, startOffset, endOffset }.
function parseH2Sections(text) {
  const sanitized = stripFencedCodeBlocks(text);
  const headingMatches = [...sanitized.matchAll(/^## (.+)$/gm)];
  if (headingMatches.length === 0) return [];

  // Map each sanitized-text heading to its position in the original text.
  // Use a moving offset to handle (the unlikely case of) duplicate heading
  // texts: each subsequent search starts after the previous match.
  const sections = [];
  let searchFrom = 0;
  for (let i = 0; i < headingMatches.length; i++) {
    const m = headingMatches[i];
    const headingLine = `## ${m[1]}`;
    const idx = text.indexOf(headingLine, searchFrom);
    if (idx === -1) {
      // Heading was inside a code block in the original. Skip.
      // (Should not happen since Pass 1 stripped code blocks, but be defensive.)
      continue;
    }
    sections.push({
      heading: m[1].trim(),
      headingLine,
      startOffset: idx,
      bodyStart: idx + headingLine.length,
      endOffset: -1, // filled below
    });
    searchFrom = idx + headingLine.length;
  }

  // Fill endOffset for each section as the start of the next, or text.length
  // for the final.
  for (let i = 0; i < sections.length; i++) {
    sections[i].endOffset = i + 1 < sections.length ? sections[i + 1].startOffset : text.length;
    sections[i].body = text.slice(sections[i].bodyStart, sections[i].endOffset);
  }

  return sections;
}

// parseHeaderBlock — extracts content before the first H2 (in sanitized
// view) and validates against headerFields. Returns { raw, fields, errors }.
function parseHeaderBlock(text, headerFields) {
  const sanitized = stripFencedCodeBlocks(text);
  const firstH2 = sanitized.search(/^## /m);
  const headerText = firstH2 === -1 ? sanitized : sanitized.slice(0, firstH2);
  const lines = headerText.split(/\r?\n/);

  const errors = [];
  const fields = new Map();

  for (const field of headerFields) {
    const matched = lines.find((line) => field.pattern.test(line));
    if (matched) {
      fields.set(field.label, matched.trim());
    } else if (field.required) {
      errors.push(createDiagnostic(
        'error',
        'header-field-missing',
        `Required header field '${field.label}' not found (pattern: ${field.pattern})`,
        'header',
      ));
    }
  }

  return { raw: headerText, fields, errors };
}

// parseMarkdownTable — finds the first pipe-delimited table in a text block.
// Returns { headers, rows, raw, startLine } or null if no table found.
// Separator regex matches §13.2(b): /^\|[\s:|-]+\|$/
function parseMarkdownTable(text) {
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length - 1; i++) {
    const headerLine = lines[i].trim();
    const sepLine = lines[i + 1].trim();
    if (!/^\|.+\|$/.test(headerLine)) continue;
    if (!/^\|[\s:|-]+\|$/.test(sepLine)) continue;
    // Found a table. Parse headers and rows.
    const headers = headerLine.slice(1, -1).split('|').map((c) => c.trim());
    const rows = [];
    for (let j = i + 2; j < lines.length; j++) {
      const rowLine = lines[j].trim();
      if (!/^\|.+\|$/.test(rowLine)) break;
      const cells = rowLine.slice(1, -1).split('|').map((c) => c.trim());
      rows.push(cells);
    }
    return { headers, rows, raw: lines.slice(i, i + 2 + rows.length).join('\n'), startLine: i };
  }
  return null;
}

// =============================================================================
// 4. Public API — detectState
// =============================================================================
//
// Per §12.3:
//   `active`         — Active Lane field's backtick value is a real lane
//                      identifier (NOT matching the sentinel pattern).
//   `between-lanes`  — Active Lane field's backtick value matches the
//                      sentinel pattern `(none — <reason>)` or
//                      `(none --- <reason>)`.
//   `malformed`      — No Active Lane field, or only `Version/lane:`
//                      (deprecated form rejected per §12.1).

export function detectState(text) {
  const normalized = normalizeInput(text);
  const sanitized = stripFencedCodeBlocks(normalized);
  // Match Lane: or Active lane: at start of a line, followed by a
  // backtick-wrapped value. Trailing content on the same line (e.g.,
  // `(active; produces ...)`) is permitted and ignored, matching the
  // existing `extractActiveLane()` behavior in scripts/workflow-guard.mjs.
  // Explicitly does NOT accept `Version/lane:` (§12.1 deprecation).
  const lineMatch = sanitized.match(/^(?:Lane|Active lane):\s*`([^`]+)`/m);
  if (!lineMatch) return PLAN_STATES.MALFORMED;
  const value = lineMatch[1].trim();
  if (SENTINEL_REGEX.test(value)) return PLAN_STATES.BETWEEN_LANES;
  return PLAN_STATES.ACTIVE;
}

// =============================================================================
// 5. Public API — validateCurrentPlan
// =============================================================================
//
// Returns { state, sections, errors[], warnings[], info[] }
//   state    — result of detectState
//   sections — ordered list of parsed H2 sections with match info
//   errors[] — ERROR-severity diagnostics
//   warnings[] — WARNING-severity diagnostics
//   info[]   — INFO-severity diagnostics
//
// Per §12.1 + §12.3 + §13.

export function validateCurrentPlan(text) {
  const normalized = normalizeInput(text);
  const errors = [];
  const warnings = [];
  const info = [];

  const state = detectState(normalized);

  // Malformed → short-circuit with single ERROR.
  if (state === PLAN_STATES.MALFORMED) {
    errors.push(createDiagnostic(
      'error',
      'state-malformed',
      'CURRENT-PLAN.md has no `Lane:` or `Active lane:` field (or only the deprecated `Version/lane:` form). Cannot determine plan state.',
    ));
    return { state, sections: [], errors, warnings, info };
  }

  // Header validation.
  const header = parseHeaderBlock(normalized, CURRENT_PLAN_HEADER_FIELDS);
  errors.push(...header.errors);

  // H2 section parsing.
  const parsedSections = parseH2Sections(normalized);

  // Match each parsed section to a CORE row (or mark as unknown).
  const matchedSections = parsedSections.map((s) => {
    let matched = null;
    for (const core of CURRENT_PLAN_CORE_SECTIONS) {
      if (matchCanonicalPrefix(s.heading, core.canonicalPrefix)) {
        matched = core;
        break;
      }
    }
    return { ...s, matched };
  });

  // Track which CORE indices are present and at what document position.
  const coreFound = new Map(); // coreIndex → position-in-parsedSections
  let lastCoreIndex = -1;
  let lastCorePosition = -1;
  for (let i = 0; i < matchedSections.length; i++) {
    const ms = matchedSections[i];
    if (!ms.matched) continue;
    if (coreFound.has(ms.matched.index)) {
      errors.push(createDiagnostic(
        'error',
        'section-duplicate',
        `Section '${ms.matched.canonicalPrefix}' appears more than once`,
        ms.heading,
      ));
      continue;
    }
    if (ms.matched.index < lastCoreIndex) {
      errors.push(createDiagnostic(
        'error',
        'section-order-violation',
        `Section '${ms.matched.canonicalPrefix}' (CORE row ${ms.matched.index}) appears after '${CURRENT_PLAN_CORE_SECTIONS[lastCoreIndex - 1].canonicalPrefix}' (CORE row ${lastCoreIndex}); CORE sections must be in order`,
        ms.heading,
      ));
    }
    coreFound.set(ms.matched.index, i);
    lastCoreIndex = ms.matched.index;
    lastCorePosition = i;
  }

  // Check REQUIRED / RECOMMENDED presence per state.
  for (const core of CURRENT_PLAN_CORE_SECTIONS) {
    if (coreFound.has(core.index)) continue;
    const presence = state === PLAN_STATES.ACTIVE ? core.requiredWhenActive : core.requiredWhenBetween;
    if (presence === 'REQUIRED') {
      errors.push(createDiagnostic(
        'error',
        'section-missing-required',
        `Required section '## ${core.canonicalPrefix}' missing (state=${state})`,
        core.canonicalPrefix,
      ));
    } else if (presence === 'RECOMMENDED') {
      info.push(createDiagnostic(
        'info',
        'section-recommended-absent',
        `Recommended section '## ${core.canonicalPrefix}' absent (state=${state})`,
        core.canonicalPrefix,
      ));
    }
  }

  // Unknown H2 handling (extensibility model per §12.1).
  for (let i = 0; i < matchedSections.length; i++) {
    const ms = matchedSections[i];
    if (ms.matched) continue;
    if (i > lastCorePosition && lastCorePosition !== -1) {
      info.push(createDiagnostic(
        'info',
        'section-unknown-trailing',
        `Unknown H2 section '## ${ms.heading}' appears after last CORE section (allowed as consumer extension)`,
        ms.heading,
      ));
    } else {
      errors.push(createDiagnostic(
        'error',
        'section-unknown-interleaved',
        `Unknown H2 section '## ${ms.heading}' appears before or between CORE sections (structural violation per §12.1)`,
        ms.heading,
      ));
    }
  }

  // §13 — Canonical Next Step validation (active state) or between-lanes
  // advisory (between-lanes state).
  validateCanonicalNextStep({
    state,
    matchedSections,
    coreFound,
    errors,
    warnings,
    info,
  });

  return { state, sections: matchedSections, errors, warnings, info };
}

// =============================================================================
// 6. §13 Canonical Next Step sub-routine
// =============================================================================
//
// Invoked by validateCurrentPlan. Pushes diagnostics into the shared
// errors[]/warnings[]/info[] arrays.

function validateCanonicalNextStep({ state, matchedSections, coreFound, errors, warnings, info }) {
  // Find the Canonical Next Step section.
  const cnsCore = CURRENT_PLAN_CORE_SECTIONS.find((c) => c.canonicalPrefix === 'Canonical Next Step');
  const cnsPosition = coreFound.get(cnsCore.index);
  const cnsSection = cnsPosition !== undefined ? matchedSections[cnsPosition] : null;

  // Between-lanes: minimal checks.
  if (state === PLAN_STATES.BETWEEN_LANES) {
    if (cnsSection) {
      // Section present in between-lanes — that's fine; check for sentinel
      // text (informational only). No diagnostic if section is absent.
    }
    // Optional INFO: deferred candidates without promotion decision.
    const dcCore = CURRENT_PLAN_CORE_SECTIONS.find((c) => c.canonicalPrefix === 'Deferred Candidates');
    const dcPosition = coreFound.get(dcCore.index);
    const dcSection = dcPosition !== undefined ? matchedSections[dcPosition] : null;
    if (dcSection) {
      const body = dcSection.body.trim();
      // Heuristic: if Deferred Candidates has content (any bullet items)
      // and there is no Open Decisions row mentioning "promote" or
      // "promotion", emit INFO.
      const hasContent = /^[\s\n]*[-*]\s/m.test(body);
      const odCore = CURRENT_PLAN_CORE_SECTIONS.find((c) => c.canonicalPrefix === 'Open Decisions');
      const odPosition = coreFound.get(odCore.index);
      const odSection = odPosition !== undefined ? matchedSections[odPosition] : null;
      const hasPromotionDecision = odSection ? /promot/i.test(odSection.body) : false;
      if (hasContent && !hasPromotionDecision) {
        info.push(createDiagnostic(
          'info',
          'deferred-candidates-no-promotion',
          'Deferred Candidates listed without an Open Decisions row mentioning promotion (user-decision-pending; advisory)',
          'Canonical Next Step',
        ));
      }
    }
    return;
  }

  // Active state.
  if (!cnsSection) {
    errors.push(createDiagnostic(
      'error',
      'canonical-next-step-missing',
      'Plan state is `active` but `## Canonical Next Step` section is missing (§13.1)',
      'Canonical Next Step',
    ));
    return;
  }

  // Item counting heuristic per Step 6 point 2.
  const body = cnsSection.body;
  const boldListItems = body.match(/^[ \t]*[-*][ \t]+\*\*[^*]+?\*\*/gm) || [];
  const inlineBolds = body.match(/\*\*[^*]+?\*\*/g) || [];

  if (boldListItems.length >= 2) {
    errors.push(createDiagnostic(
      'error',
      'canonical-next-step-multiple',
      `Canonical Next Step contains ${boldListItems.length} bolded list items; §13.1 requires exactly 1 actionable item`,
      'Canonical Next Step',
    ));
  } else if (boldListItems.length === 0 && inlineBolds.length === 0) {
    errors.push(createDiagnostic(
      'error',
      'canonical-next-step-empty',
      'Canonical Next Step section contains no bolded directive (zero actionable items per §13.1 heuristic)',
      'Canonical Next Step',
    ));
  }
  // else: 1 bolded list item OR 0 list + 1+ inline bold = PASS (one actionable item)

  // Baseline-matching algorithm (§13.2). Only meaningful when item count is OK.
  if (boldListItems.length <= 1) {
    runBaselineMatching({ matchedSections, coreFound, cnsSection, errors, warnings, info });
  }
}

function runBaselineMatching({ matchedSections, coreFound, cnsSection, errors, warnings, info }) {
  const bsCore = CURRENT_PLAN_CORE_SECTIONS.find((c) => c.canonicalPrefix === 'Baseline Structure');
  const bsPosition = coreFound.get(bsCore.index);
  const bsSection = bsPosition !== undefined ? matchedSections[bsPosition] : null;

  // §13.2 step (a): if Baseline Structure absent, INFO and skip.
  if (!bsSection) {
    info.push(createDiagnostic(
      'info',
      'baseline-structure-absent',
      'Baseline Structure section absent; baseline-mismatch check skipped (§13.2 step (a))',
      'Baseline Structure',
    ));
    return;
  }

  // §13.2 step (b): find first Markdown table in the section body.
  const table = parseMarkdownTable(bsSection.body);
  if (!table) {
    info.push(createDiagnostic(
      'info',
      'baseline-no-table',
      'Baseline Structure contains no Markdown table; baseline-mismatch check skipped (§13.2 step (f))',
      'Baseline Structure',
    ));
    return;
  }

  // §13.2 step (c): find Status column (case-insensitive).
  const statusIdx = table.headers.findIndex((h) => /^status$/i.test(h));
  if (statusIdx === -1) {
    info.push(createDiagnostic(
      'info',
      'baseline-no-status-column',
      'Baseline Structure table has no Status column; baseline-mismatch check skipped (§13.2 step (f))',
      'Baseline Structure',
    ));
    return;
  }

  // §13.2 step (d) + (e): scan rows top-to-bottom; first row whose Status
  // does NOT match /^(done|PASS)$/i (whitespace-trimmed) is the first
  // unclosed item.
  const closedPattern = /^(done|PASS)$/i;
  let firstUnclosed = null;
  for (let r = 0; r < table.rows.length; r++) {
    const cell = table.rows[r][statusIdx] || '';
    // Strip backticks and whitespace before testing.
    const statusValue = cell.replace(/^`|`$/g, '').trim();
    if (!closedPattern.test(statusValue)) {
      firstUnclosed = { rowIndex: r, row: table.rows[r] };
      break;
    }
  }

  if (!firstUnclosed) {
    info.push(createDiagnostic(
      'info',
      'baseline-all-closed',
      'All Baseline Structure rows are done/PASS; baseline-mismatch check skipped (§13.2 step (f))',
      'Baseline Structure',
    ));
    return;
  }

  // §13.2 step (e): identity resolution order.
  const identity = resolveIdentity(table.headers, firstUnclosed.row, firstUnclosed.rowIndex, statusIdx);

  // Compare identity against Canonical Next Step body (case-insensitive
  // substring).
  const cnsBody = cnsSection.body;
  const found = cnsBody.toLowerCase().includes(identity.toLowerCase());

  if (found) return; // Match; no diagnostic.

  // Mismatch — check Open Decisions for override.
  const override = findOpenDecisionsOverride({ matchedSections, coreFound, identity });
  if (override) {
    warnings.push(createDiagnostic(
      'warning',
      'canonical-next-step-baseline-mismatch-acknowledged',
      `Canonical Next Step does not match Baseline first-unclosed item '${identity}', but an Open Decisions override row is present (acknowledged; §13.1 WARNING override)`,
      'Canonical Next Step',
    ));
  } else {
    warnings.push(createDiagnostic(
      'warning',
      'canonical-next-step-baseline-mismatch',
      `Canonical Next Step does not match Baseline first-unclosed item '${identity}'; record the reason in Open Decisions to convert this WARNING into an acknowledged override (§13.1)`,
      'Canonical Next Step',
    ));
  }
}

function resolveIdentity(headers, row, rowIndex, statusIdx) {
  // §13.2 step (e): Sub > Subject > first non-Status non-index column with text content > row index.
  const subIdx = headers.findIndex((h) => /^sub$/i.test(h));
  if (subIdx !== -1 && row[subIdx] && row[subIdx].trim()) return row[subIdx].trim();
  const subjectIdx = headers.findIndex((h) => /^subject$/i.test(h));
  if (subjectIdx !== -1 && row[subjectIdx] && row[subjectIdx].trim()) return row[subjectIdx].trim();
  for (let c = 0; c < headers.length; c++) {
    if (c === statusIdx) continue;
    if (c === subIdx || c === subjectIdx) continue;
    if (/^(index|#|no\.?)$/i.test(headers[c])) continue;
    if (row[c] && row[c].trim()) return row[c].trim();
  }
  return String(rowIndex + 1);
}

function findOpenDecisionsOverride({ matchedSections, coreFound, identity }) {
  const odCore = CURRENT_PLAN_CORE_SECTIONS.find((c) => c.canonicalPrefix === 'Open Decisions');
  const odPosition = coreFound.get(odCore.index);
  const odSection = odPosition !== undefined ? matchedSections[odPosition] : null;
  if (!odSection) return false;
  // Heuristic: any Open Decisions row that mentions the unclosed identity
  // (case-insensitive substring) counts as an override entry. This is
  // permissive but matches the §13.1 intent: "the Current Plan MUST record
  // the reason in Open Decisions". If the author bothered to write
  // something referencing the unclosed identity, that is the override.
  const odLower = odSection.body.toLowerCase();
  return odLower.includes(identity.toLowerCase());
}

// =============================================================================
// 7. Public API — validateHistoryMap
// =============================================================================
//
// Returns { sections, releases[], unreleasedBullets[], errors[], warnings[], info[] }
//
// Per §12.2 + §3 (Composed Milestones Convention).

export function validateHistoryMap(text) {
  const normalized = normalizeInput(text);
  const errors = [];
  const warnings = [];
  const info = [];

  // Header validation.
  const header = parseHeaderBlock(normalized, HISTORY_MAP_HEADER_FIELDS);
  errors.push(...header.errors);

  // H2 sections.
  const parsedSections = parseH2Sections(normalized);

  // Match to CORE rows.
  const matchedSections = parsedSections.map((s) => {
    let matched = null;
    for (const core of HISTORY_MAP_CORE_SECTIONS) {
      if (matchCanonicalPrefix(s.heading, core.canonicalPrefix)) {
        matched = core;
        break;
      }
    }
    return { ...s, matched };
  });

  // Section ordering + presence.
  const coreFound = new Map();
  let lastCoreIndex = -1;
  let lastCorePosition = -1;
  for (let i = 0; i < matchedSections.length; i++) {
    const ms = matchedSections[i];
    if (!ms.matched) continue;
    if (coreFound.has(ms.matched.index)) {
      errors.push(createDiagnostic(
        'error',
        'section-duplicate',
        `Section '${ms.matched.canonicalPrefix}' appears more than once`,
        ms.heading,
      ));
      continue;
    }
    if (ms.matched.index < lastCoreIndex) {
      errors.push(createDiagnostic(
        'error',
        'section-order-violation',
        `Section '${ms.matched.canonicalPrefix}' (CORE row ${ms.matched.index}) appears out of order`,
        ms.heading,
      ));
    }
    coreFound.set(ms.matched.index, i);
    lastCoreIndex = ms.matched.index;
    lastCorePosition = i;
  }

  for (const core of HISTORY_MAP_CORE_SECTIONS) {
    if (coreFound.has(core.index)) continue;
    if (core.presence === 'REQUIRED') {
      errors.push(createDiagnostic(
        'error',
        'section-missing-required',
        `Required section '## ${core.canonicalPrefix}' missing`,
        core.canonicalPrefix,
      ));
    }
  }

  // Unknown H2 extensibility.
  for (let i = 0; i < matchedSections.length; i++) {
    const ms = matchedSections[i];
    if (ms.matched) continue;
    if (i > lastCorePosition && lastCorePosition !== -1) {
      info.push(createDiagnostic(
        'info',
        'section-unknown-trailing',
        `Unknown H2 section '## ${ms.heading}' appears after last CORE section (allowed as consumer extension)`,
        ms.heading,
      ));
    } else {
      errors.push(createDiagnostic(
        'error',
        'section-unknown-interleaved',
        `Unknown H2 section '## ${ms.heading}' appears before or between CORE sections (structural violation per §12.2)`,
        ms.heading,
      ));
    }
  }

  // Version entries — positional H3 children between Timeline body and
  // Unreleased Workflow Evidence. Per §12.2: scan H3 ### vX.Y.Z within
  // Timeline section's body (which extends to next H2 = Unreleased).
  const timelineCore = HISTORY_MAP_CORE_SECTIONS.find((c) => c.canonicalPrefix === 'Timeline');
  const timelinePos = coreFound.get(timelineCore.index);
  const timelineSection = timelinePos !== undefined ? matchedSections[timelinePos] : null;

  const releases = timelineSection ? parseVersionEntries(timelineSection.body) : [];

  // Validate reverse chronological order.
  for (let i = 1; i < releases.length; i++) {
    if (compareSemver(releases[i].version, releases[i - 1].version) > 0) {
      warnings.push(createDiagnostic(
        'warning',
        'version-order-violation',
        `Version ${releases[i].version} appears after ${releases[i - 1].version} but is newer (entries must be reverse-chronological)`,
        'Timeline',
      ));
    }
  }

  // Each entry needs Status: and Composed milestones: lines per §3.
  for (const r of releases) {
    if (!r.statusLine) {
      warnings.push(createDiagnostic(
        'warning',
        'version-entry-missing-status',
        `Version entry ${r.version} missing Status: line (§3 Composed Milestones Convention)`,
        r.version,
      ));
    }
    if (!r.composedMilestones || r.composedMilestones.length === 0) {
      warnings.push(createDiagnostic(
        'warning',
        'version-entry-missing-composed',
        `Version entry ${r.version} missing 'Composed milestones:' line (§3 Composed Milestones Convention)`,
        r.version,
      ));
    }
  }

  // Unreleased Workflow Evidence bullets.
  const unrelCore = HISTORY_MAP_CORE_SECTIONS.find((c) => c.canonicalPrefix === 'Unreleased Workflow Evidence');
  const unrelPos = coreFound.get(unrelCore.index);
  const unrelSection = unrelPos !== undefined ? matchedSections[unrelPos] : null;
  const unreleasedBullets = unrelSection ? parseBulletList(unrelSection.body) : [];

  return { sections: matchedSections, releases, unreleasedBullets, errors, warnings, info };
}

function parseVersionEntries(timelineBody) {
  // Pre-strip fenced code blocks so a `### v1.0.0` inside a Mermaid block
  // would not be miscounted. (In practice, Mermaid syntax doesn't use ###
  // for version-like tokens, but be defensive.)
  const sanitized = stripFencedCodeBlocks(timelineBody);
  const lines = sanitized.split(/\r?\n/);
  const versionLineRegex = /^### (v\d+\.\d+\.\d+).*$/;

  // First locate each version-entry line index in sanitized text.
  const entryStarts = [];
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(versionLineRegex);
    if (m) entryStarts.push({ lineIdx: i, version: m[1] });
  }

  // Slice each entry's body.
  const entries = [];
  for (let e = 0; e < entryStarts.length; e++) {
    const start = entryStarts[e].lineIdx;
    const end = e + 1 < entryStarts.length ? entryStarts[e + 1].lineIdx : lines.length;
    const body = lines.slice(start, end).join('\n');
    const statusMatch = body.match(/^Status:\s*(.+)$/m);
    const composedMatch = body.match(/^Composed milestones:\s*(.+)$/m);
    entries.push({
      version: entryStarts[e].version,
      statusLine: statusMatch ? statusMatch[1].trim() : null,
      composedMilestones: composedMatch
        ? composedMatch[1].trim().split(/,\s*/).map((m) => m.trim()).filter(Boolean)
        : [],
      raw: body,
    });
  }
  return entries;
}

function parseBulletList(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.match(/^[ \t]*[-*][ \t]+(.+)$/))
    .filter(Boolean)
    .map((m) => m[1].trim());
}

function compareSemver(a, b) {
  // Strip leading v, split, compare numerically.
  const pa = a.replace(/^v/, '').split('.').map((n) => parseInt(n, 10));
  const pb = b.replace(/^v/, '').split('.').map((n) => parseInt(n, 10));
  for (let i = 0; i < 3; i++) {
    if (pa[i] !== pb[i]) return pa[i] - pb[i];
  }
  return 0;
}

// =============================================================================
// 8. Internal helpers exported for self-test use only (not part of the
//    Phase 3 guard's public API).
// =============================================================================

export const __internals = Object.freeze({
  normalizeInput,
  stripFencedCodeBlocks,
  matchCanonicalPrefix,
  parseH2Sections,
  parseHeaderBlock,
  parseMarkdownTable,
  parseVersionEntries,
  parseBulletList,
  compareSemver,
});
