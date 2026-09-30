/**
 * project-graph-prompt — the English prompt block that teaches the index-build
 * agent to produce `.claude-index/graph.json` (project-architecture-graph §3.4).
 *
 * Agent-facing prompts are English (CLAUDE.md §Localization); this module is on
 * the `agent-facing-prompt-english.test.ts` module list.
 *
 * Two constraints in here are load-bearing and easy to "simplify" away:
 *
 * 1. **The degradation clause has TWO triggers** (§3.4 step 4 / D17): `python`
 *    unavailable **or** the tool script missing from the stated path. The batch
 *    entry point creates the plan card and launches it later — possibly hours
 *    later, possibly on a different machine after cloud sync, possibly after
 *    「清理缓存」 swept the directory. No server-side action can guarantee the
 *    script is there at launch. Drop the second trigger and the model hits
 *    `No such file`, abandons the graph, and the index build still records
 *    `completed` with no log anywhere.
 *
 * 2. **Every example must run under cmd.exe, PowerShell 5.1 and bash**
 *    (R2-P0-2). The primary platform is Windows and which sub-shell the agent
 *    CLI forwards to is not predictable. So: no `>` redirection, no heredocs,
 *    no `&&` chaining, no backslash continuations, no `/tmp`. Discovery
 *    commands write their own files via `--out`.
 */

/** Bump when the block's wording changes, so a live prompt can be dated. */
export const GRAPH_BLOCK_VERSION = 'v2-202608';

/** Hard cap asserted by `project-graph-prompt.test.ts` (R8: +5 KB budget). */
export const GRAPH_BLOCK_MAX_CHARS = 5000;

/** Where the deployer puts the CLI, relative to the workspace root. */
export const GRAPH_TOOL_REL_PATH = '.agentmesh/.index-graph-tools.py';

/** Where the published artifact goes, relative to the workspace root. */
export const GRAPH_OUT_REL_PATH = '.claude-index/graph.json';

/** Scratch directory for discovery output and the NDJSON batch. */
const WORK_REL_DIR = '.agentmesh/index-graph';

export function buildGraphAuthoringBlock(
  toolRelPath: string = GRAPH_TOOL_REL_PATH,
  outRelPath: string = GRAPH_OUT_REL_PATH,
): string {
  const tool = `python ${toolRelPath}`;
  return [
    `## Code Graph (${GRAPH_BLOCK_VERSION})`,
    '',
    `Also produce \`${outRelPath}\`: a machine-readable graph of this repository (modules,`,
    'their components, and the relations between them), rendered by the desktop app as an',
    `interactive architecture / UML view. The CLI at \`${toolRelPath}\` only touches files`,
    `in this working directory: no network, no env vars, no third-party packages.`,
    '',
    'Classes and members are EXTRACTED by the tool, not written by you. Your job is what a',
    'scanner cannot do: grouping, summaries, and semantic relations.',
    '',
    '### Workflow',
    '',
    '1. Discover the module layout. Each command writes its own file via `--out`; never redirect.',
    '',
    `   ${tool} scan-modules --max-depth 3 --min-files 3 --out ${WORK_REL_DIR}/mods.json`,
    `   ${tool} scan-imports --path src --lang ts --out ${WORK_REL_DIR}/imports.json`,
    '',
    '2. Open the draft. Idempotent: re-running keeps what you wrote, so an interrupted run',
    '   resumes instead of starting over.',
    '',
    `   ${tool} init --project-name "Your Project"`,
    '',
    '3. Declare 8-40 modules. This part is yours: grouping and summaries are judgement,',
    '   and no scanner can do them.',
    '',
    `   ${tool} add-module --id mod.srv --name "Services" --path server/services --layer backend --kind package --summary "Orchestration and sync."`,
    '',
    '4. Extract classes and members. `scan-uml` reads real class bodies off disk, so its',
    '   output IS the batch. Run it once per module and apply it directly.',
    '',
    `   ${tool} scan-uml --path server/services --module mod.srv --exported-only --max-containers 25 --emit-ops --out ${WORK_REL_DIR}/ops-srv.ndjson`,
    `   ${tool} apply --file ${WORK_REL_DIR}/ops-srv.ndjson`,
    '',
    '   Do NOT re-type scan results by hand. What `scan-uml` emits is marked',
    '   `"provenance":"extracted"` and shown to the user as verified; a copy you typed is not.',
    '',
    '5. Add the semantic relations the scanner cannot see (composition, emits, reads, calls).',
    `   Write one JSON object per line into \`${WORK_REL_DIR}/ops-semantic.ndjson\` with your own`,
    '   file-writing tool (no shell heredoc), then apply the batch:',
    '',
    '   {"op":"add-component","id":"cmp.srv.Cache","module":"mod.srv","name":"Cache","kind":"class","file":"server/services/cache.ts","line":12,"summary":"LRU.","provenance":"asserted"}',
    '   {"op":"add-relation","from":"cmp.srv.IndexSvc","to":"cmp.srv.Cache","kind":"composition","evidence":["server/services/index.ts:131"],"provenance":"asserted"}',
    '',
    `   ${tool} apply --file ${WORK_REL_DIR}/ops-semantic.ndjson`,
    '',
    '   An op key is the long option name without `--`, in lowerCamel (`--member-kind` is',
    '   `memberKind`). Every op is an upsert, so a batch can be re-applied safely. Use',
    '   `"provenance":"asserted"` for anything you wrote yourself.',
    '',
    '6. Verify, validate, then publish:',
    '',
    `   ${tool} verify --fix-lines`,
    `   ${tool} validate`,
    `   ${tool} finalize`,
    '',
    '   `verify` re-opens every cited file and line and repairs drifted line numbers; it',
    '   always exits 0 and reports what it found. `finalize` runs it again and refuses to',
    '   publish when a record marked `extracted` fails, then writes a temp file and',
    `   atomically replaces the artifact. Print \`GRAPH: ${outRelPath}\` as your first output line.`,
    '',
    '### Quality bar (checked, not aspirational)',
    '',
    '- Every module has a `summary`; every component has `file` and `line`.',
    '- Every `extends` / `implements` / `composition` relation carries `evidence`',
    '  (`path/to/file.ts:412`). Those three are the easiest to hallucinate, and the UI puts',
    '  the cited line in front of the user.',
    '- 8-40 modules (fewer for a small repo); at least as many relations as modules.',
    '- Prefer a complete module layer with its key components over an exhaustive class dump;',
    `  \`${tool} stats\` reports the remaining budget.`,
    '',
    'Relation kinds: extends, implements, composition, aggregation, association, depends,',
    'uses, calls, emits, reads, writes, contains. Layers: frontend, backend, shared, desktop,',
    'mobile, infra, test, docs, other.',
    '',
    '### If the tool is unavailable',
    '',
    `If \`python\` is not available, or \`${toolRelPath}\` is not at that path, do not skip the`,
    `graph. Hand-write \`${outRelPath}\` in this shape and report \`GRAPH: fallback-handwritten\`.`,
    '',
    '   {"schemaVersion":2,"generatedAt":0,"project":{"name":"Your Project","root":".","languages":["TypeScript"]},',
    '    "modules":[{"id":"mod.x","name":"X","path":"src/x","layer":"frontend","kind":"package","summary":"..."}],',
    '    "components":[{"id":"cmp.x.Y","moduleId":"mod.x","name":"Y","kind":"class","file":"src/x/y.ts","line":10,"provenance":"asserted",',
    '     "attributes":[{"name":"a","type":"string"}],"methods":[{"name":"run","signature":"(): void"}]}],',
    '    "relations":[{"from":"mod.x","to":"cmp.x.Y","kind":"contains"}]}',
  ].join('\n');
}
