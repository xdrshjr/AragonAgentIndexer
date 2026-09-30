/**
 * claude-md-budget-prompt — the English prompt block that hands the index-build
 * agent this project's measured CLAUDE.md budget
 * (index-build-claude-md-compaction §2.6).
 *
 * Agent-facing prompts are English (CLAUDE.md §Localization); this module is on
 * the `agent-facing-prompt-english.test.ts` module list.
 *
 * Four constraints in here are load-bearing and easy to "simplify" away:
 *
 * 1. **A null / non-existent measurement returns `''`** — and the caller splices
 *    it with `...(block ? [block] : [])`, never `block,`. `buildIndexBuildPrompt`
 *    is a `[...].join('\n')`: an empty string in the MIDDLE of that array adds a
 *    newline out of thin air, and the byte-equivalence guard goes red on the
 *    spot. This pair is the feature's rollback switch: make the measurement
 *    `null` and every project behaves exactly as it did before this round.
 *
 * 2. **The numbers are a HINT, never a promise** (§2.1 / review P1-3). The batch
 *    「all projects」entry point builds this prompt at CARD-CREATION time, writes
 *    it into `task_tracker_plans.prompt`, and syncs it to the cloud — the card
 *    may launch hours later on a different machine whose CLAUDE.md is not the
 *    file measured here. So the block says so, verbatim, and tells the agent to
 *    re-read the file itself. Same lesson as `prepareWorkspaceTools`'s D17
 *    anchor and `project-graph-rescan-prompt.ts`'s header.
 *
 * 3. **Every example must run under cmd.exe, PowerShell 5.1 and bash**: no `>`
 *    redirection, no heredocs, no `&&` chaining, no backslash continuations, no
 *    `/tmp`. Which sub-shell the agent CLI forwards to is not predictable.
 *
 * 4. **The tiering anchors match the HEADING LINE ONLY, never body text**
 *    (review P0-1). Running a body-text anchor over this repo's real CLAUDE.md
 *    immunises 59.6% of it (19 of 33 sections, 122,467 chars) — long narrative
 *    sections are long precisely BECAUSE they are full of 禁止 / MUST clauses.
 *    A body anchor makes the whole pass a no-op that still reports success.
 */

import {
  CLAUDE_MD_HARD_CHARS,
  CLAUDE_MD_MAX_SECTIONS_PER_RUN,
  CLAUDE_MD_SECTION_SOFT_CHARS,
  CLAUDE_MD_TARGET_CHARS,
  type ClaudeMdMeasurement,
  type ClaudeMdUnit,
} from './claude-md-budget.js';

/** Bump when the block's wording changes, so a live prompt can be dated. */
export const CLAUDE_MD_BLOCK_VERSION = 'v1-202608';

/**
 * Hard cap asserted by `claude-md-budget-prompt.test.ts`.
 *
 * It is the block's STRUCTURAL maximum, not a hopeful round number: the block is
 * a fixed 2,775-char body plus at most `LISTED_UNITS` lines, each bounded by
 * `HEADING_MAX_CHARS` and by the widest line/char numbers a 4 MB file can carry
 * (`CLAUDE_MD_MEASURE_MAX_BYTES`) — 3,480 chars in total. Anything smaller is a
 * cap the block can exceed in production while the test stays green, because a
 * synthetic fixture's short headings and 3-digit line numbers never reach the
 * worst case. This repo's own CLAUDE.md already renders at 3,206.
 *
 * So: bound it by construction (lower `LISTED_UNITS` / `HEADING_MAX_CHARS`) and
 * recompute this number — do not just raise it to whatever today's file needs.
 */
export const CLAUDE_MD_BLOCK_MAX_CHARS = 3500;

/** How many of the largest units are listed. More is noise; fewer hides the work. */
const LISTED_UNITS = 8;

/** Longest heading rendered in the unit list; longer ones are elided. */
const HEADING_MAX_CHARS = 64;

/** Control characters plus the backtick: the first can truncate the prompt, the
 *  second can open a fence inside it. Headings are arbitrary user text. */
const CONTROL_CHARS = /[\x00-\x1f\x7f`]/g;

function sanitizeHeading(raw: string): string {
  const value = raw.replace(CONTROL_CHARS, '').trim();
  return value.length > HEADING_MAX_CHARS ? `${value.slice(0, HEADING_MAX_CHARS - 3)}...` : value;
}

/**
 * Units worth listing: biggest first, skipping the ones the agent must not touch
 * anyway (already-managed content and the navigation preamble of each chapter).
 * Listing an immune unit as "largest" invites the agent to go after it.
 */
function rankUnits(units: ClaudeMdUnit[]): ClaudeMdUnit[] {
  return units
    .filter((u) => !u.isPreamble && u.managed === null && u.chars >= CLAUDE_MD_SECTION_SOFT_CHARS)
    .slice()
    .sort((a, b) => b.chars - a.chars)
    .slice(0, LISTED_UNITS);
}

/**
 * Build the budget block, or `''` when there is nothing to say.
 *
 * `''` is returned for a missing measurement, a missing CLAUDE.md, and a
 * truncated read — in all three cases the honest answer is "we do not know", and
 * a block full of `unknown` would only spend context to say so.
 */
export function buildClaudeMdBudgetBlock(m: ClaudeMdMeasurement | null): string {
  if (!m || !m.exists || m.truncated) return '';

  const ranked = rankUnits(m.units);
  const unitLines = ranked.length > 0
    ? ranked.map((u, i) => `  ${i + 1}. L${u.startLine}-${u.endLine}  ${u.chars}  ${sanitizeHeading(u.heading)}`)
    : ['  (none — every unit is already short, managed, or a chapter preamble)'];

  return [
    `# CLAUDE.md Budget (${CLAUDE_MD_BLOCK_VERSION}, part of step 3 above)`,
    '',
    'CLAUDE.md is injected into every agent session in this project, so its total length',
    'is a cost everyone pays. Apply Step 6b of the project-indexer skill.',
    '',
    'The numbers below were measured when this prompt was built, which may have been on a',
    'different machine at a different time. Re-read CLAUDE.md yourself in Step 6b and act on',
    'your own measurement.',
    '',
    `- Measured: ${m.chars} chars / ${m.bytes} bytes / ${m.lines} lines / ${m.units.length} units`,
    `- Tier: ${m.tier}  (lean <= ${CLAUDE_MD_TARGET_CHARS} < watch <= ${CLAUDE_MD_HARD_CHARS} < over)`,
    '- Largest compactable units (line range / chars / heading):',
    ...unitLines,
    '',
    'What each tier means:',
    '- lean: do nothing beyond the two managed sections. Leave CLAUDE.md otherwise untouched.',
    '- watch: change nothing; report the total and the largest units in your Step 7 summary.',
    '- over: run the compaction pass below, in this order.',
    '',
    '0. Gate. Run: git check-ignore -q .claude-index/notes/.keep',
    '   Exit code 0 means that directory is git-ignored: ABANDON the whole pass and say so',
    '   in the summary. Moving prose into an unversioned directory is deletion, not',
    '   compaction. Not a repo / git unavailable / any other outcome: abandon too (fail closed).',
    `1. Rank compactable units by size, descending. Stop as soon as the file is <= ${CLAUDE_MD_TARGET_CHARS}`,
    `   chars, or ${CLAUDE_MD_MAX_SECTIONS_PER_RUN} units have been compacted. The rest waits for the next index build.`,
    `2. Never touch: units under ${CLAUDE_MD_SECTION_SOFT_CHARS} chars; the preamble between a "## " heading and its`,
    '   first "### "; anything inside project-indexer markers or the "## Project Index"',
    '   section; units carrying a non-project-indexer HTML comment marker; and units whose',
    '   HEADING LINE names Commands, Workflow Rules, Path Aliases, Environment Variables,',
    '   Build Output or Patches. Match the heading line only — never body text. Prohibitions',
    '   in the body tell you which sentences to KEEP, not whether to compact.',
    '3. Write .claude-index/notes/<slug>.md FIRST with the verbatim original, read it back to',
    '   confirm it landed, and only then rewrite CLAUDE.md. If that notes file already exists',
    '   with a different heading in its front matter, skip that unit — never overwrite it.',
    '4. Replace the body with a 600-900 char stub: the heading line verbatim, one summary',
    '   sentence, the must-hold invariants, and pointers to the notes file and',
    '   .claude-index/index.md. Wrap the stub in:',
    '   <!-- project-indexer:compact:begin v1.2.0 slug=<slug> chars=<original> -->',
    '   <!-- project-indexer:compact:end -->',
    '5. A unit that already carries a compact marker is never compacted again; only verify',
    '   that the notes file its pointer names still exists.',
    '',
    'This run is unattended: never ask a question anywhere in the skill. Take the documented',
    'default and report the choices you made in the Step 7 summary.',
  ].join('\n');
}
