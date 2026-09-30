import { isAbsolute } from 'node:path';
import { getProjectIndexerSkill, readProjectIndexerAsset } from './assets.js';
import { buildIndexBuildPrompt, type IndexBuildPromptOptions } from './project-index-prompt.js';
import { measureClaudeMdForBuild, prepareWorkspaceTools } from './workspace.js';
import { IndexBuildError, type IndexBuildOptions, type IndexBuildRunner, type PreparedIndexBuild } from './types.js';

function effectiveSkill(options: IndexBuildOptions): string {
  const content = options.skillContent === undefined ? readProjectIndexerAsset('SKILL.md') : options.skillContent;
  if (typeof content !== 'string' || !content.trim()) {
    throw new IndexBuildError('SKILL_CONTENT_UNAVAILABLE', '项目索引技能内容不可用');
  }
  return content;
}

export function prepareIndexBuild(options: IndexBuildOptions): PreparedIndexBuild {
  return prepareWithSkill(options).prepared;
}

function prepareWithSkill(options: IndexBuildOptions): { prepared: PreparedIndexBuild; content: string } {
  if (!options || typeof options.workspaceDir !== 'string' || !options.workspaceDir.trim() || !isAbsolute(options.workspaceDir)) {
    throw new IndexBuildError('INVALID_WORKSPACE', '工作目录必须为非空绝对路径');
  }
  const content = effectiveSkill(options);
  const { measurement, warnings } = measureClaudeMdForBuild(options.workspaceDir);
  // 唯一净化边界仍在 buildRescanScopeBlock；这里不重复净化，避免截断尾空格发生二次变化。
  const scope = options.scope as IndexBuildPromptOptions['scope'];
  return {
    content,
    prepared: {
      workspaceDir: options.workspaceDir,
      prompt: buildIndexBuildPrompt(content, options.workspaceDir, { scope, claudeMd: measurement }),
      indexRelPath: '.claude-index/index.md',
      graphRelPath: '.claude-index/graph.json',
      warnings,
    },
  };
}

export async function startIndexBuild<T>(options: IndexBuildOptions, runner: IndexBuildRunner<T>) {
  const { prepared, content: skillContent } = prepareWithSkill(options);
  const tools = prepareWorkspaceTools(options.workspaceDir);
  const files = getProjectIndexerSkill().files.map(({ relPath }) => Object.freeze({
    relPath,
    content: relPath === 'SKILL.md' ? skillContent : readProjectIndexerAsset(relPath),
  }));
  const handle = await runner(Object.freeze({
    workspaceDir: prepared.workspaceDir,
    prompt: prepared.prompt,
    skill: Object.freeze({
      name: 'project-indexer' as const,
      entryFile: 'SKILL.md' as const,
      files: Object.freeze(files),
    }),
  }));
  return { handle, prepared, tools };
}
