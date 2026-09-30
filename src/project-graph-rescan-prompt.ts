/**
 * project-graph-rescan-prompt — the English prompt block appended when the user
 * asks for a TARGETED rescan (project-architecture-graph-liveness §3.3).
 *
 * Agent-facing prompts are English (CLAUDE.md §Localization); this module is on
 * the `agent-facing-prompt-english.test.ts` module list.
 *
 * ⚠️ **This block is deliberately NOT part of `buildGraphAuthoringBlock()`.**
 * That block is already at 5000 / 5000 characters — its budget has zero
 * headroom, and adding a single sentence to it reddens
 * `project-graph-prompt.test.ts` on the spot. The two sentences this round
 * needs to say (`init --from-published` exists; `finalize` now records
 * fingerprints and archives the previous artifact) are only useful DURING a
 * rescan, so they live here, where they cost that budget nothing.
 *
 * ⚠️ **Every example must run under cmd.exe, PowerShell 5.1 and bash**
 * (round-2 R2-P0-2): no `>` redirection, no heredocs, no `&&` chaining, no
 * backslash continuations, no `/tmp`.
 *
 * ⚠️ **The wording is a HINT, never a promise** (§8 invariant 11). The agent may
 * ignore the scope entirely, or fall back to a full rebuild because
 * `--from-published` failed. Nothing downstream of this file is allowed to say
 * "fixed" or "updated" — the result is answered by the NEXT drift probe.
 */

import { GRAPH_LIMITS, type GraphRescanScope } from './graph-types.js';

/** Bump when the block's wording changes, so a live prompt can be dated. */
export const RESCAN_BLOCK_VERSION = 'v1-202608';

/** Hard cap asserted by `project-graph-rescan-prompt.test.ts`. */
export const RESCAN_BLOCK_MAX_CHARS = GRAPH_LIMITS.scopeBlockMaxChars;

/** Control characters plus the backtick: the first can truncate the prompt,
 *  the second can open a fence inside it. */
const CONTROL_CHARS = /[\x00-\x1f\x7f\u0060]/g;

/**
 * Narrow one client-supplied path-ish string down to something that is safe to
 * splice verbatim into an LLM prompt.
 *
 * ⚠️ **§8 invariant 27 · `scope` is untrusted input and sanitising it is the
 * SERVER's job.** It arrives as a client-controlled string array (the WS
 * handler `as`-asserts everything except `projectId` / `agentType`), and its
 * *normal* source is `graph.json` inside the user's repository — which was
 * never trusted input either. Every rule below has a silent failure mode if
 * dropped: an oversized block squeezes out the skill body, a fence-breaking
 * character truncates the instructions mid-sentence, and a crafted path can
 * rewrite the second half of the prompt. All of them surface only as "that
 * index run behaved oddly".
 */
function sanitizeEntry(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  let value = raw.replace(CONTROL_CHARS, '').trim();
  if (!value) return null;
  value = value.replace(/\\/g, '/');
  if (value.startsWith('/') || /^[A-Za-z]:\//.test(value)) return null;
  if (value.split('/').some((seg) => seg === '..')) return null;
  if (value.length > GRAPH_LIMITS.scopeMaxEntryChars) {
    value = value.slice(0, GRAPH_LIMITS.scopeMaxEntryChars);
  }
  return value || null;
}

function sanitizeList(raw: unknown, cap: number): { kept: string[]; dropped: number } {
  if (!Array.isArray(raw)) return { kept: [], dropped: 0 };
  const kept: string[] = [];
  const seen = new Set<string>();
  let dropped = 0;
  for (const item of raw) {
    const value = sanitizeEntry(item);
    if (!value || seen.has(value)) continue;
    if (kept.length >= cap) { dropped += 1; continue; }
    seen.add(value);
    kept.push(value);
  }
  return { kept, dropped };
}

/**
 * Returns `undefined` when nothing survives — the caller then degrades to a
 * FULL rebuild rather than rejecting the request (D10). The user clicked
 * "rescan"; a full rebuild still gives them a correct result, whereas a
 * rejection is a dead end they cannot fix themselves.
 */
export function sanitizeRescanScope(raw: unknown): GraphRescanScope | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const input = raw as Record<string, unknown>;
  const modules = sanitizeList(input.moduleIds, GRAPH_LIMITS.scopeMaxModules);
  const paths = sanitizeList(input.paths, GRAPH_LIMITS.scopeMaxPaths);
  const files = sanitizeList(input.files, GRAPH_LIMITS.scopeMaxFiles);
  if (!modules.kept.length && !paths.kept.length && !files.kept.length) return undefined;
  const declared = Number.isFinite(input.omittedFiles) ? Math.max(0, Math.floor(input.omittedFiles as number)) : 0;
  return {
    reason: 'drift',
    moduleIds: modules.kept,
    paths: paths.kept,
    files: files.kept,
    // Both sources are counted: what the client already knew it had left out,
    // plus what we just dropped here.
    omittedFiles: declared + files.dropped + modules.dropped + paths.dropped,
  };
}

/**
 * The prompt block. Empty string when there is no scope, so the no-scope path
 * stays byte-for-byte identical to what it was before this round.
 */
export function buildRescanScopeBlock(scope?: GraphRescanScope | null): string {
  if (!scope) return '';
  const normalized = sanitizeRescanScope(scope);
  if (!normalized) return '';

  let trimmed = { ...normalized };
  let omittedModules = 0;
  let omittedPaths = 0;
  let block = renderBlock(trimmed, omittedModules, omittedPaths);
  // Last-resort trim: keep dropping from the tail of the file list until the
  // block fits, and count every dropped entry. Silently blowing the budget is
  // what squeezes the skill body out of the prompt, and that failure is
  // invisible.
  //
  // ⚠️ The loop calls `renderBlock`, NOT `buildRescanScopeBlock`. Recursing into
  // the public entry point makes every level re-run its own trim loop, which is
  // exponential in the number of files — with a full 40-file scope it never
  // returns, and the symptom is the whole index build hanging with no output.
  //
  // 裁剪顺序：files -> paths -> moduleIds。文件是最长也最容易补回来的一档（模块列表
  // 本身就指得出该重扫哪里）；模块 id 最短、信息密度最高，最后才动。
  // ⚠️ 实测：12 个长模块 id + 12 条长路径 + 40 个长文件路径的满载 scope 是 1300+
  // 字符，只裁 files 到零仍然超标 —— 所以三档都必须可裁，否则这个上限形同虚设。
  while (block.length > RESCAN_BLOCK_MAX_CHARS && trimmed.files.length > 0) {
    trimmed = {
      ...trimmed,
      files: trimmed.files.slice(0, -1),
      omittedFiles: trimmed.omittedFiles + 1,
    };
    block = renderBlock(trimmed, omittedModules, omittedPaths);
  }
  while (block.length > RESCAN_BLOCK_MAX_CHARS && trimmed.paths.length > 0) {
    trimmed = { ...trimmed, paths: trimmed.paths.slice(0, -1) };
    omittedPaths += 1;
    block = renderBlock(trimmed, omittedModules, omittedPaths);
  }
  while (block.length > RESCAN_BLOCK_MAX_CHARS && trimmed.moduleIds.length > 1) {
    trimmed = { ...trimmed, moduleIds: trimmed.moduleIds.slice(0, -1) };
    omittedModules += 1;
    block = renderBlock(trimmed, omittedModules, omittedPaths);
  }
  return block;
}

/** 纯渲染，**不做任何裁剪**（裁剪由上面那三个循环负责）。 */
function renderBlock(
  normalized: GraphRescanScope,
  omittedModules: number,
  omittedPaths: number,
): string {
  const lines: string[] = [
    '',
    '## Targeted rescan',
    '',
    'The published graph is still there; only part of it has gone stale. Prefer updating',
    'that part over rebuilding everything.',
    '',
    '1. Seed the draft from the published artifact instead of starting empty:',
    '   `python .agentmesh/.index-graph-tools.py init --project-name "<name>" --from-published`',
    '   (ignored when a draft already exists, so it is safe to run first).',
    '2. Re-run `scan-uml --emit-ops` and `apply` for the paths below only.',
    '3. Finish with `verify` and `finalize` as usual. `finalize` now also records a source',
    '   fingerprint for every file the graph cites, and archives the previous artifact.',
    '',
    'Changed since the graph was built:',
  ];

  if (normalized.moduleIds.length) {
    lines.push(`- modules: ${normalized.moduleIds.join(', ')}`);
  }
  if (normalized.paths.length) {
    lines.push(`- module paths: ${normalized.paths.join(', ')}`);
  }
  if (normalized.files.length) {
    lines.push(`- files: ${normalized.files.join(', ')}`);
  }
  if (normalized.omittedFiles > 0) {
    lines.push(`- plus ${normalized.omittedFiles} more file(s) not listed here.`);
  }
  // No silent caps: what the length budget trimmed has to be said out loud too.
  if (omittedModules > 0 || omittedPaths > 0) {
    lines.push(`- plus ${omittedModules} more module(s) and ${omittedPaths} more path(s) not listed here.`);
  }
  lines.push(
    '',
    'If any of this does not apply, fall back to a full rebuild — a correct whole graph',
    'beats a partial one.',
  );

  return lines.join('\n');
}
