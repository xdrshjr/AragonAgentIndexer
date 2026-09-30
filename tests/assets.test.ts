import { expect, test } from 'vitest';
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, cpSync, rmSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { EMBEDDED_ASSETS } from '../src/generated/assets.js';
import { getProjectIndexerSkill, readProjectIndexerAsset } from '../src/index.js';
const fixture = JSON.parse(readFileSync(new URL('./fixtures/prompts.json', import.meta.url), 'utf8'));
test('迁移资产保留原始字节，fallback 与规范化原始内容一致', () => {
  for (const [path, value] of Object.entries(EMBEDDED_ASSETS)) {
    const raw = readFileSync(new URL(`../assets/${path}`, import.meta.url));
    const normalized = raw.toString('utf8').replace(/\r\n/g, '\n');
    // 原始迁移哈希在实施环境核验；git 的 LF/CRLF 检出不能令跨平台包测试假红。
    expect([fixture.hashes[path].raw, fixture.hashes[path].normalized]).toContain(createHash('sha256').update(raw).digest('hex'));
    expect(value.sha256).toBe(fixture.hashes[path].normalized);
    expect(Buffer.from(value.base64, 'base64').toString('utf8')).toBe(normalized);
  }
  expect(getProjectIndexerSkill().version).toBe('1.2.0');
  expect(getProjectIndexerSkill().files).toHaveLength(9);
});

test('生成器跨 LF/CRLF 稳定，真实内容漂移和版本不一致使检查失败', () => {
  const testRoot = join(tmpdir(), 'aragon-agent-indexer', 'generator-tests');
  mkdirSync(testRoot, {recursive:true});
  const dir = mkdtempSync(join(testRoot, 'fixture-'));
  try {
    cpSync(resolve('assets'), join(dir,'assets'), {recursive:true});
    mkdirSync(join(dir,'scripts')); cpSync(resolve('scripts/generate-assets.mjs'),join(dir,'scripts/generate-assets.mjs'));
    const run = (...args: string[]) => spawnSync(process.execPath,[join(dir,'scripts/generate-assets.mjs'),...args],{encoding:'utf8'});
    expect(run().status).toBe(0);
    const generated = readFileSync(join(dir,'src/generated/assets.ts'),'utf8');
    for (const path of Object.keys(EMBEDDED_ASSETS)) {
      const target = join(dir,'assets',path);
      writeFileSync(target,readFileSync(target,'utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'));
    }
    expect(run('--check').status).toBe(0);
    expect(run().status).toBe(0);
    expect(readFileSync(join(dir,'src/generated/assets.ts'),'utf8')).toBe(generated);
    const skill = join(dir,'assets/system-skills/project-indexer/SKILL.md');
    writeFileSync(skill, readFileSync(skill,'utf8') + '\n内容漂移\n');
    expect(run('--check').status).not.toBe(0);
    expect(run().status).toBe(0);
    writeFileSync(skill,readFileSync(skill,'utf8').replace('"version": "1.2.0"','"version": "9.9.9"'));
    expect(run().status).not.toBe(0);
  } finally { rmSync(dir,{recursive:true,force:true}); }
});
test.each(['../SKILL.md','/SKILL.md','C:/SKILL.md','templates/../SKILL.md','unknown','toString'])('资源只允许固定清单：%s', path => {
  expect(() => readProjectIndexerAsset(path)).toThrow(expect.objectContaining({code:'ASSET_NOT_FOUND'}));
});
