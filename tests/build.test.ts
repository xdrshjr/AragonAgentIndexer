import { afterEach, expect, test } from 'vitest';
import { mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import * as sdk from '../src/index.js';

const root = join(tmpdir(), 'aragon-agent-indexer', 'sdk-tests');
mkdirSync(root, { recursive: true });
const dirs: string[] = [];
function workspace() { const dir = mkdtempSync(join(root, '项目 ')); dirs.push(dir); return dir; }
afterEach(() => dirs.splice(0).forEach(dir => rmSync(dir, { recursive: true, force: true })));

test('公开准备入口存在', () => expect(sdk).toHaveProperty('prepareIndexBuild'));
test('prepare 只读且保持工作路径文本', () => {
  const dir = workspace();
  writeFileSync(join(dir, 'CLAUDE.md'), '# Instructions\nhello');
  const before = readdirSync(dir);
  const prepared = sdk.prepareIndexBuild({workspaceDir: dir});
  expect(prepared.workspaceDir).toBe(dir);
  expect(prepared.prompt).toContain(dir);
  expect(readdirSync(dir)).toEqual(before);
  expect(prepared.warnings).toEqual([]);
});
test('非法目录和显式空技能拒绝；缺失绝对目录允许只读准备', () => {
  for (const workspaceDir of ['', 'relative']) expect(() => sdk.prepareIndexBuild({workspaceDir})).toThrow(sdk.IndexBuildError);
  expect(() => sdk.prepareIndexBuild({workspaceDir: workspace(), skillContent:'  '})).toThrow(expect.objectContaining({code:'SKILL_CONTENT_UNAVAILABLE'}));
  expect(sdk.prepareIndexBuild({workspaceDir: join(workspace(), 'missing')})).toHaveProperty('prompt');
});
test('runner 仅调用一次且收到完整技能模板、自定义入口和已部署工具', async () => {
  const dir = workspace(); let calls = 0;
  const result = await sdk.startIndexBuild({workspaceDir:dir, skillContent:'# custom'}, async request => {
    calls++;
    expect(request.skill.files).toHaveLength(9);
    expect(request.skill.files.find(f => f.relPath === 'SKILL.md')?.content).toBe('# custom');
    for (const name of ['cleancode-template','cleancode-overrides','claude-md-compaction']) expect(request.skill.files.find(f => f.relPath === `templates/${name}.md`)?.content.length).toBeGreaterThan(0);
    expect(readdirSync(join(dir, '.agentmesh'))).toContain('.index-graph-tools.py');
    return {id:'handle'};
  });
  expect(calls).toBe(1); expect(result.handle).toEqual({id:'handle'});
  expect(result).not.toHaveProperty('status');
});
test('工具失败仍交付 runner，runner 错误原样透传', async () => {
  const dir = join(workspace(), 'missing');
  let calls = 0;
  const result = await sdk.startIndexBuild({workspaceDir:dir}, async () => ++calls);
  expect(calls).toBe(1); expect(result.tools.deployed).toBe(false);
  const error = new Error('runner failure');
  await expect(sdk.startIndexBuild({workspaceDir:workspace()}, async () => {throw error;})).rejects.toBe(error);
});

test('scope 净化次数保持一次，恶意值不进入提示词', () => {
  const workspaceDir = workspace();
  const scope = { reason:'drift', files:['x'.repeat(119) + ' y', '../escape', '`bad`\u0000'], omittedFiles:0 };
  expect(sdk.prepareIndexBuild({workspaceDir, skillContent:'# fixed', scope}).prompt)
    .toBe(sdk.buildIndexBuildPrompt('# fixed', workspaceDir, {scope} as any));
  expect(sdk.prepareIndexBuild({workspaceDir, scope:{files:['../escape']}}).prompt).not.toContain('../escape');
});

test('技能含关闭标签时快照仍完整保留原文', async () => {
  const skillContent = '# custom\n</skill>\n尾部内容';
  await sdk.startIndexBuild({workspaceDir:workspace(), skillContent}, async request => {
    expect(request.skill.files.find(f => f.relPath === 'SKILL.md')?.content).toBe(skillContent);
  });
});
