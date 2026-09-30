import { readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { EMBEDDED_ASSETS, SKILL_FILES, SKILL_VERSION } from './generated/assets.js';
import { IndexBuildError, type ProjectIndexerSkillDefinition } from './types.js';

const assetRoot = new URL('../assets/', import.meta.url);
function readAsset(path: keyof typeof EMBEDDED_ASSETS): string {
  try { return readFileSync(new URL(path, assetRoot), 'utf8'); }
  catch { return Buffer.from(EMBEDDED_ASSETS[path].base64, 'base64').toString('utf8'); }
}
export function resolveProjectIndexerAssetDir(): string | null {
  const dir = fileURLToPath(new URL('system-skills/project-indexer/', assetRoot));
  try { return statSync(dir).isDirectory() ? dir : null; } catch { return null; }
}
export function readProjectIndexerAsset(relPath: string): string {
  if (!(SKILL_FILES as readonly string[]).includes(relPath)) throw new IndexBuildError('ASSET_NOT_FOUND', '未知的项目索引技能资源');
  return readAsset(`system-skills/project-indexer/${relPath}` as keyof typeof EMBEDDED_ASSETS);
}
export function readGraphToolSource(): string { return readAsset('index-graph-tools.py'); }
export function getProjectIndexerSkill(): ProjectIndexerSkillDefinition {
  return {
    key: 'project-indexer', name: 'project-indexer', version: SKILL_VERSION,
    description: 'Generate and use project index for quick codebase understanding in new Claude Code sessions. Scans project structure, extracts code symbols, creates a navigable feature map, and injects a Google-style Clean Code Guidelines section into CLAUDE.md.',
    summary: '为任意代码库生成结构化索引，帮助 Claude 在新会话中快速理解项目结构，并向 CLAUDE.md 注入 Clean Code 规范。',
    entryFile: 'SKILL.md', files: SKILL_FILES.map(relPath => ({relPath})),
    fallbackEntryB64: EMBEDDED_ASSETS['system-skills/project-indexer/SKILL.md'].base64,
  };
}
