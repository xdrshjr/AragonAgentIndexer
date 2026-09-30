import { lstatSync, readFileSync, writeFileSync } from 'node:fs';
import { isAbsolute, join } from 'node:path';
import { readGraphToolSource } from './assets.js';
export const INDEX_GRAPH_TOOLS_FILENAME = '.index-graph-tools.py';
export const INDEX_GRAPH_TOOLS_SOURCE_FILENAME = 'index-graph-tools.py';
export function deployIndexGraphTools(agentMeshDir: string): void {
  if (!agentMeshDir || !isAbsolute(agentMeshDir)) throw new Error('工具目录必须为现有绝对路径');
  const directory = lstatSync(agentMeshDir);
  if (directory.isSymbolicLink() || !directory.isDirectory()) throw new Error('工具目录不能是链接');
  const target = join(agentMeshDir, INDEX_GRAPH_TOOLS_FILENAME);
  if (lstatSync(target, { throwIfNoEntry: false })?.isSymbolicLink()) throw new Error('工具目标不能是链接');
  const content = Buffer.from(readGraphToolSource(), 'utf8');
  writeFileSync(target, content);
  if (!readFileSync(target).equals(content)) throw new Error('图谱工具写入后校验失败');
}
