import { expect, test } from 'vitest';
import * as sdk from '../src/index.js';
import * as graph from '../src/graph-types.js';
import { readFileSync, readdirSync } from 'node:fs';
test('公共 API 保持显式入口，图谱模块无 Node 运行依赖', () => {
  for (const name of ['prepareIndexBuild','startIndexBuild','getProjectIndexerSkill','readProjectIndexerAsset','resolveProjectIndexerAssetDir','deployIndexGraphTools','buildIndexBuildPrompt','buildGraphAuthoringBlock','buildRescanScopeBlock','buildClaudeMdBudgetBlock','sanitizeRescanScope','measureClaudeMdForBuild','readIndexFileInfo','readIndexMtime','prepareWorkspaceTools','IndexBuildError']) expect(typeof sdk[name as keyof typeof sdk]).toBe('function');
  expect(graph.PROJECT_GRAPH_SCHEMA_VERSION).toBe(2);
  expect(readFileSync(new URL('../src/graph-types.ts',import.meta.url),'utf8')).not.toMatch(/from ['"]node:/);
  for (const file of readdirSync(new URL('../src',import.meta.url)).filter(p=>p.endsWith('.ts'))) expect(readFileSync(new URL(`../src/${file}`,import.meta.url),'utf8')).not.toMatch(/from ['"](?:.*\/server\/|.*\/shared\/|@aragon-agent\/core)/);
});
