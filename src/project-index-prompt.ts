/**
 * project-index-prompt — builds the English initial prompt handed to the
 * agent launched by the「构建索引」action (project-build-index, spec §2.5).
 *
 * Agent-facing prompts are English (CLAUDE.md §Localization). The full
 * project-indexer SKILL.md (~33 KB) is injected verbatim, wrapped in a
 * <skill> tag — this is the agent's ONLY task, so we deliberately do NOT
 * apply the 30 K truncation budget that buildEnhancedTask uses for the
 * multi-skill dispatch case.
 */

import { buildGraphAuthoringBlock } from './project-graph-prompt.js';
import { buildRescanScopeBlock } from './project-graph-rescan-prompt.js';
import { buildClaudeMdBudgetBlock } from './claude-md-budget-prompt.js';
import type { GraphRescanScope } from './graph-types.js';
import type { ClaudeMdMeasurement } from './claude-md-budget.js';

export interface IndexBuildPromptOptions {
  /**
   * 局部重扫范围在 buildRescanScopeBlock 内净化；此层不增加净化轮次。
   * 缺省时保留原有完整构建提示词。
   */
  scope?: GraphRescanScope | null;

  /**
   * index-build-claude-md-compaction W2. The project's CLAUDE.md as measured by
   * the CALLER, at the moment it built this prompt.
   *
   * `null` / absent => `buildClaudeMdBudgetBlock` returns `''` and the returned
   * prompt is byte-for-byte what it was before this round. That is the feature's
   * rollback switch (spec invariant 10).
   */
  claudeMd?: ClaudeMdMeasurement | null;
}

export function buildIndexBuildPrompt(
  skillContent: string,
  workspaceDir: string,
  opts?: IndexBuildPromptOptions,
): string {
  const budgetBlock = buildClaudeMdBudgetBlock(opts?.claudeMd ?? null);
  return [
    '# Reference Skill: project-indexer',
    '',
    'The following skill document defines exactly how to build and maintain a project index. Follow it precisely.',
    '',
    `<skill name="project-indexer">\n${skillContent}\n</skill>`,
    '',
    '# Task',
    '',
    `Apply the project-indexer skill to the project in the current working directory (\`${workspaceDir}\`).`,
    '',
    '1. Treat the current working directory as the project root.',
    "2. If `.claude-index/index.md` already exists, follow the skill's \"Regeneration\" workflow to update it incrementally; otherwise follow \"First-Time Generation\".",
    '3. Generate / refresh `.claude-index/index.md` and apply the Clean Code Guidelines section to CLAUDE.md exactly as the skill specifies.',
    '4. When the index file is fully written, continue with step 5 below.',
    // project-architecture-graph §3.4: the ONE place the graph block is spliced in,
    // so both entry points (right-click single project via `startBuild`, and the
    // 「所有项目」batch via `buildIndexPrompt`) get it for free. Deploying the tool
    // script is a *separate* concern anchored at agent launch, not here — see
    // ProjectIndexService.prepareWorkspaceTools and spec §8 invariant 3.
    '5. Build the machine-readable code graph described below, then stop. Do not wait for',
    '   further instructions.',
    '',
    buildGraphAuthoringBlock(),
    // index-build-claude-md-compaction §2.6: spliced AFTER the graph block and
    // BEFORE the rescan block — and CONDITIONALLY (review P1-1). This array is
    // `.join('\n')`-ed, so an empty string in a MIDDLE position adds a newline out
    // of thin air and the byte-equivalence guard (T7 / T7b) goes red on the spot.
    // `buildRescanScopeBlock` gets away with an unconditional `''` only because it
    // sits LAST, where the cost is the one trailing newline it shipped with.
    //
    // Do NOT "tidy" the numbered list above into a 6th step either: that text is
    // part of the「empty measurement => byte-identical」property, and a new step
    // would change the prompt of every project, including the ones that have no
    // CLAUDE.md at all. The budget block introduces itself as part of step 3.
    ...(budgetBlock ? [budgetBlock] : []),
    // Appended AFTER the authoring block, and only when a scope is present, so
    // the resident block's 5000 / 5000 character budget is untouched.
    buildRescanScopeBlock(opts?.scope),
  ].join('\n');
}
