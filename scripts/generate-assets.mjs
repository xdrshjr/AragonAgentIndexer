import { readFileSync, writeFileSync, mkdirSync, rmSync, lstatSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const skillFiles = ['SKILL.md', 'README.md', '_meta.json', 'templates/claude-md-compaction.md', 'templates/cleancode-overrides.md', 'templates/cleancode-template.md', 'templates/config-template.md', 'templates/environments-template.md', 'templates/index-template.md'];
const paths = ['index-graph-tools.py', ...skillFiles.map(p => `system-skills/project-indexer/${p}`)];
const assets = Object.fromEntries(paths.map(path => {
  const text = readFileSync(resolve(root, 'assets', path), 'utf8').replace(/\r\n/g, '\n');
  return [path, { base64: Buffer.from(text).toString('base64'), sha256: createHash('sha256').update(text).digest('hex') }];
}));
const meta = JSON.parse(Buffer.from(assets['system-skills/project-indexer/_meta.json'].base64, 'base64').toString('utf8'));
const skill = Buffer.from(assets['system-skills/project-indexer/SKILL.md'].base64, 'base64').toString('utf8');
const metadata = JSON.parse((skill.split('---')[1] ?? '').match(/^metadata:\s*(\{.*\})$/m)?.[1] ?? '{}');
if (meta.version !== meta.latest.version || meta.version !== metadata.version) throw new Error('技能版本标记不一致');
const generated = '// 此文件由 scripts/generate-assets.mjs 生成，请勿手工编辑。\n' +
  `export const SKILL_VERSION = ${JSON.stringify(meta.version)};\n` +
  `export const SKILL_FILES = ${JSON.stringify(skillFiles)} as const;\n` +
  `export const EMBEDDED_ASSETS = ${JSON.stringify(assets, null, 2)} as const;\n`;
const target = resolve(root, 'src/generated/assets.ts');
if (process.argv.includes('--check') || process.argv.includes('--build')) {
  if (readFileSync(target, 'utf8').replace(/\r\n/g, '\n') !== generated) throw new Error('嵌入资产过期，请运行 npm run generate:assets');
} else {
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, generated);
}
if (process.argv.includes('--build')) {
  const dist = resolve(root, 'dist');
  try { if (lstatSync(dist).isSymbolicLink()) throw new Error('拒绝清理链接形式的 dist'); rmSync(dist, { recursive: true }); }
  catch (err) { if (err.code !== 'ENOENT') throw err; }
  const result = spawnSync(process.execPath, [resolve(root, 'node_modules/typescript/bin/tsc'), '-p', resolve(root, 'tsconfig.json')], { stdio: 'inherit' });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
}
