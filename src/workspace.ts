import { lstatSync, mkdirSync, readFileSync, statSync } from 'node:fs';
import { isAbsolute, join } from 'node:path';
import { CLAUDE_MD_MEASURE_MAX_BYTES, measureClaudeMd, type ClaudeMdMeasurement } from './claude-md-budget.js';
import { deployIndexGraphTools, INDEX_GRAPH_TOOLS_FILENAME } from './deploy-index-graph-tools.js';
import type { IndexFileInfo, IndexWarning, WorkspaceToolsResult } from './types.js';
export function measureClaudeMdForBuild(workspaceDir: string | null): { measurement: ClaudeMdMeasurement | null; warnings: IndexWarning[] } {
  if (!workspaceDir) return {measurement:null, warnings:[]};
  try {
    const path = join(workspaceDir, 'CLAUDE.md');
    if (statSync(path).size > CLAUDE_MD_MEASURE_MAX_BYTES) return {measurement:null, warnings:[{code:'CLAUDE_MD_TOO_LARGE', message:'CLAUDE.md 超过 4 MiB 度量上限'}]};
    const buf = readFileSync(path);
    return {measurement:measureClaudeMd(buf.toString('utf8'), buf.byteLength), warnings:[]};
  } catch (err) {
    return {measurement:null, warnings:(err as NodeJS.ErrnoException).code === 'ENOENT' ? [] : [{code:'CLAUDE_MD_UNAVAILABLE', message:'无法读取 CLAUDE.md 度量'}]};
  }
}
export function prepareWorkspaceTools(workspaceDir: string): WorkspaceToolsResult {
  const valid = typeof workspaceDir === 'string' && !!workspaceDir.trim() && isAbsolute(workspaceDir);
  const toolPath = valid ? join(workspaceDir, '.agentmesh', INDEX_GRAPH_TOOLS_FILENAME) : null;
  try {
    if (!valid || !statSync(workspaceDir).isDirectory()) throw new Error('工作目录必须是现有绝对目录');
    const dir = join(workspaceDir, '.agentmesh');
    try { mkdirSync(dir); } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== 'EEXIST') throw err;
      const existing = lstatSync(dir);
      if (existing.isSymbolicLink() || !existing.isDirectory()) throw new Error('工具目录必须是工程内的实目录');
    }
    deployIndexGraphTools(dir);
    return {deployed:true, toolPath, warnings:[]};
  } catch {
    return {deployed:false, toolPath, warnings:[{code:'TOOL_DEPLOY_FAILED', message:'无法部署图谱工具，请检查工作目录及写入权限'}]};
  }
}
export function readIndexFileInfo(workspaceDir: string | null): IndexFileInfo {
  const relPath = '.claude-index/index.md';
  const absPath = workspaceDir ? join(workspaceDir, relPath) : null;
  if (absPath) try { return {exists:true, relPath, absPath, mtime:Math.floor(statSync(absPath).mtimeMs)}; } catch { /* 缺失或不可读沿用相同信号。 */ }
  return {exists:false, relPath, absPath, mtime:null};
}
export function readIndexMtime(workspaceDir: string | null): number { return readIndexFileInfo(workspaceDir).mtime ?? 0; }
