export interface IndexBuildOptions {
  workspaceDir: string;
  skillContent?: string;
  scope?: unknown;
}

export type IndexBuildErrorCode = 'INVALID_WORKSPACE' | 'SKILL_CONTENT_UNAVAILABLE' | 'ASSET_NOT_FOUND';

export class IndexBuildError extends Error {
  readonly code: IndexBuildErrorCode;

  constructor(code: IndexBuildErrorCode, message: string) {
    super(message);
    this.name = 'IndexBuildError';
    this.code = code;
  }
}

export interface IndexWarning {
  code: 'CLAUDE_MD_UNAVAILABLE' | 'CLAUDE_MD_TOO_LARGE' | 'TOOL_DEPLOY_FAILED';
  message: string;
}

export interface PreparedIndexBuild {
  workspaceDir: string;
  prompt: string;
  indexRelPath: '.claude-index/index.md';
  graphRelPath: '.claude-index/graph.json';
  warnings: IndexWarning[];
}

export interface WorkspaceToolsResult {
  deployed: boolean;
  toolPath: string | null;
  warnings: IndexWarning[];
}

export interface IndexFileInfo {
  exists: boolean;
  relPath: '.claude-index/index.md';
  absPath: string | null;
  mtime: number | null;
}

export interface IndexSkillAsset {
  relPath: string;
  content: string;
}

export interface IndexRunnerRequest {
  workspaceDir: string;
  prompt: string;
  skill: Readonly<{
    name: 'project-indexer';
    entryFile: 'SKILL.md';
    files: ReadonlyArray<Readonly<IndexSkillAsset>>;
  }>;
}

export interface IndexBuildRunner<T> {
  (request: Readonly<IndexRunnerRequest>): Promise<T>;
}

export interface ProjectIndexerSkillDefinition {
  key: 'project-indexer';
  version: string;
  name: 'project-indexer';
  description: string;
  summary: string;
  entryFile: 'SKILL.md';
  files: Array<{ relPath: string }>;
  fallbackEntryB64: string;
}
