# AragonAgentIndexer

可复用的项目索引构建 SDK，包名为 `@aragonmesh/project-indexer`，从 AragonMesh 提取为独立开源组件。内含完整 project-indexer 1.2.0 技能、六个模板及 Python 图谱工具；零运行时 npm 依赖。包版本与技能版本独立。

## 安装与接入

运行时需要 Node.js 18 及以上，ESM；CommonJS 使用动态 `import()`。完整图谱 CLI 需要 Python 3，纯提示词 API 不需要 Python。源码构建和测试请使用 Node.js 22.12 及以上。

本组件通过 GitHub 提供源码，尚未发布到 npm registry。先克隆仓库并生成安装包：

```sh
git clone https://github.com/xdrshjr/AragonAgentIndexer.git
cd AragonAgentIndexer
npm ci --include=dev
npm pack
```

然后在接入项目中安装生成的 tarball（替换为实际文件路径）：

```text
npm install ./aragonmesh-project-indexer-0.1.1.tgz
```

```javascript
import { startIndexBuild, readIndexFileInfo } from '@aragonmesh/project-indexer';

const result = await startIndexBuild({ workspaceDir: '/absolute/project' }, async request => {
  // 接入方的执行器适配层须先注册 skills 中的全部文件，再启动真实 Agent。
  return launchAgent({ cwd: request.workspaceDir, initialPrompt: request.prompt, skills: [request.skill] });
});
console.log(result.handle, readIndexFileInfo('/absolute/project'));
```

`launchAgent` 是接入方提供的函数，`skills` 是适配层合同，并非所有 Agent CLI 原生参数。参考可导入的 [custom-runner.mjs](examples/custom-runner.mjs)。适配层应物化技能目录或注册虚拟读取工具，确保 `project-indexer/templates/*` 和技能相对路径 `templates/*` 都能访问。例如：

```javascript
const files = new Map(request.skill.files.map(file => [`project-indexer/${file.relPath}`, file.content]));
function readSkillFile(path) {
  const key = path.startsWith('project-indexer/') ? path : `project-indexer/${path}`;
  if (!files.has(key)) throw new Error('技能资源不可访问');
  return files.get(key);
}
readSkillFile('templates/cleancode-template.md');
readSkillFile('project-indexer/templates/cleancode-overrides.md');
readSkillFile('templates/claude-md-compaction.md');
```

模板不能访问时应拒绝启动，不能仅传提示词丢弃技能资源。SDK 不修改用户全局技能目录。自定义 `skillContent` 会同时替换 prompt 和快照 SKILL.md；自定义技能需要额外资源时，由接入方提供。

## 接口与生命周期

- `prepareIndexBuild({workspaceDir, skillContent?, scope?})`：只读生成完整提示词、相对输出路径与 warning。要求本机绝对路径；不创建目录，不部署工具，不启动 Agent。显式空白技能报错。
- `prepareWorkspaceTools(workspaceDir)`：仅在现有工作目录内创建 `.agentmesh/`，覆盖并核验 `.index-graph-tools.py`；失败返回 warning，不隐式创建项目根。
- `startIndexBuild(options, runner)`：先准备、再部署、最后调用一次 runner，返回 `{handle, prepared, tools}`。工具失败仍可由 Agent 降级处理；执行器异常原样透传。
- `readIndexFileInfo` / `readIndexMtime`：读取 `.claude-index/index.md` 的存在性和毫秒时间戳。
- `getProjectIndexerSkill` / `readProjectIndexerAsset` / `resolveProjectIndexerAssetDir`：读取资源合同；缺磁盘资源时使用包内完整嵌入副本。
- `measureClaudeMdForBuild`：仅度量根 CLAUDE.md，最大 4 MiB，失败降级；不修改正文。

根入口还导出原提示词 API、scope 净化、部署函数和对应类型。`/graph-types` 是浏览器安全的图谱类型与常量入口；`/budget` 和根入口为 Node 专用。前端预算类型必须使用 `import type`。

外部宿主必须串行执行同一工作目录的索引任务，SDK 不提供同目录并发协调或跨进程锁。工具部署拒绝 `.agentmesh` 或目标脚本为链接的情况，避免跟随链接修改工程外文件。

`startIndexBuild` 成功仅表示执行器接受请求，完整语义索引仍由真实 Agent 完成。调用方负责进程、取消、超时和状态管理。SDK 不持有账号凭据、不写数据库、不启动定时器。Python 扫描/图谱编写 CLI 与 Agent 语义索引是不同步骤。mtime 变化只说明索引文件更新，不能证明索引、图谱和历史文件整体事务完成。文件监听、批量任务和界面入口由宿主应用管理。

## 开发与验证

在本仓库根目录依次执行：

```text
npm ci --include=dev
npm run check:assets
npm run build
npm test
npm pack
```

`npm run build` 检查资产并清理自身 dist 后编译，`npm run generate:assets` 更新规范化嵌入副本，`npm run check:assets` 校验。`npm pack` 自动构建，产出 `aragonmesh-project-indexer-0.1.1.tgz`。tarball 安装不需要 TypeScript，也不执行源码编译。修改源码后需重新构建；接入应用按自身方式重启或重新加载。

## 目录结构

- `src/`：TypeScript SDK、提示词、图谱类型与嵌入资产。
- `assets/`：Python 图谱工具、原始技能文件与模板。
- `examples/`：自定义 Agent 执行器的接入示例。
- `tests/`：公开 API、资源一致性、提示词和工作目录边界测试。
- `scripts/generate-assets.mjs`：资产生成、校验与构建入口。

## 贡献

欢迎通过 [Issues](https://github.com/xdrshjr/AragonAgentIndexer/issues) 报告问题，或提交 Pull Request。提交前请运行上面的开发与验证命令。修改技能或模板时，需重新生成嵌入资产并检查相关测试基线。

自动测试验证 SDK 协议与打包内容；真实 Agent 的索引质量需要由接入方结合自己的模型和执行器验证。

## 许可证

MIT 授权；原技能元数据归属 AragonAgent-Skills，迁移保留所有技能文件原文。
