import { afterEach, expect, test } from 'vitest';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync, statSync, readFileSync, symlinkSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { deployIndexGraphTools, measureClaudeMdForBuild, prepareWorkspaceTools, readIndexFileInfo, readIndexMtime } from '../src/index.js';
const root = join(tmpdir(), 'aragon-agent-indexer', 'workspace-tests');
mkdirSync(root, {recursive:true});
const dirs: string[] = [];
function workspace() { const dir = mkdtempSync(join(root, 'fixture-')); dirs.push(dir); return dir; }
afterEach(() => dirs.splice(0).forEach(dir => rmSync(dir, {recursive:true, force:true})));
test('部署不会补齐不存在工程根或把文件当目录', () => {
  const dir = workspace(); const missing = join(dir, 'missing'); const file = join(dir, 'file'); writeFileSync(file, 'x');
  for (const path of ['', 'relative', missing, file]) {
    const result = prepareWorkspaceTools(path);
    expect(result.deployed).toBe(false); expect(result.warnings[0].code).toBe('TOOL_DEPLOY_FAILED');
  }
  expect(prepareWorkspaceTools('').toolPath).toBe(null);
  expect(existsSync(missing)).toBe(false);
});
test('部署覆盖伪造工具，.agentmesh 为文件时返回 warning', () => {
  const dir = workspace(); const tool = prepareWorkspaceTools(dir).toolPath!;
  writeFileSync(tool, 'counterfeit'); expect(prepareWorkspaceTools(dir).deployed).toBe(true);
  expect(readFileSync(tool, 'utf8')).toContain('def cmd_finalize');
  const bad = workspace(); writeFileSync(join(bad, '.agentmesh'), 'x'); expect(prepareWorkspaceTools(bad).deployed).toBe(false);
});
test('缺失、不可读、超限度量降级；三档分类保持', () => {
  const dir = workspace(); expect(measureClaudeMdForBuild(dir)).toEqual({measurement:null,warnings:[]});
  mkdirSync(join(dir, 'CLAUDE.md')); expect(measureClaudeMdForBuild(dir).warnings[0].code).toBe('CLAUDE_MD_UNAVAILABLE');
  rmSync(join(dir, 'CLAUDE.md'), {recursive:true});
  for (const [n,tier] of [[100,'lean'],[45000,'watch'],[65000,'over']] as const) {
    writeFileSync(join(dir, 'CLAUDE.md'), 'x'.repeat(n)); expect(measureClaudeMdForBuild(dir).measurement?.tier).toBe(tier);
  }
  writeFileSync(join(dir, 'CLAUDE.md'), 'x'.repeat(4*1024*1024+1)); expect(measureClaudeMdForBuild(dir).warnings[0].code).toBe('CLAUDE_MD_TOO_LARGE');
});
test('文件探测保留缺失形状与毫秒取整', () => {
  expect(readIndexFileInfo(null)).toEqual({exists:false, relPath:'.claude-index/index.md', absPath:null, mtime:null});
  const dir = workspace(); expect(readIndexMtime(dir)).toBe(0);
  mkdirSync(join(dir, '.claude-index')); const file = join(dir,'.claude-index/index.md'); writeFileSync(file, '# Index');
  expect(readIndexMtime(dir)).toBe(Math.floor(statSync(file).mtimeMs)); expect(readIndexFileInfo(dir).exists).toBe(true);
});

test('拒绝 .agentmesh 目录链接，避免向工程外写入', () => {
  const dir = workspace(); const external = workspace();
  const link = join(dir,'.agentmesh');
  symlinkSync(external,link,process.platform === 'win32' ? 'junction' : 'dir');
  try {
    expect(prepareWorkspaceTools(dir).deployed).toBe(false);
    expect(existsSync(join(external,'.index-graph-tools.py'))).toBe(false);
  } finally { unlinkSync(link); }
});

test('低层部署拒绝工具目标链接，同时允许工程根自身为目录链接', () => {
  const dir = workspace(); const external = workspace();
  const link = join(dir,'.index-graph-tools.py');
  symlinkSync(external,link,process.platform === 'win32' ? 'junction' : 'dir');
  try { expect(() => deployIndexGraphTools(dir)).toThrow('工具目标不能是链接'); }
  finally { unlinkSync(link); }
  const rootLink = join(dir,'workspace-link');
  symlinkSync(external,rootLink,process.platform === 'win32' ? 'junction' : 'dir');
  try { expect(prepareWorkspaceTools(rootLink).deployed).toBe(true); }
  finally { unlinkSync(rootLink); }
});
