# AragonAgentIndexer

English | [简体中文](README.zh-CN.md)

A reusable project indexing SDK, published under the package name `@aragonmesh/project-indexer` and extracted from AragonMesh as a standalone open-source component. It includes the complete project-indexer 1.2.0 skill, six templates, and a Python code graph tool, with zero runtime npm dependencies. The package and skill are versioned independently.

## Installation and integration

The runtime requires Node.js 18 or later and uses ESM. CommonJS consumers can use dynamic `import()`. The full graph CLI requires Python 3; prompt-only APIs do not require Python. Use Node.js 22.12 or later to build and test the source.

Source code is available on GitHub. The package has not been published to the npm registry. Clone the repository and create an installation tarball:

```sh
git clone https://github.com/xdrshjr/AragonAgentIndexer.git
cd AragonAgentIndexer
npm ci --include=dev
npm pack
```

Then install the generated tarball in your application, replacing the path with its actual location:

```sh
npm install ./aragonmesh-project-indexer-0.1.1.tgz
```

```javascript
import { startIndexBuild, readIndexFileInfo } from '@aragonmesh/project-indexer';

const result = await startIndexBuild({ workspaceDir: '/absolute/project' }, async request => {
  // Register all files in the skill with your runner adapter before starting the agent.
  return launchAgent({ cwd: request.workspaceDir, initialPrompt: request.prompt, skills: [request.skill] });
});
console.log(result.handle, readIndexFileInfo('/absolute/project'));
```

You provide `launchAgent`. The `skills` property is part of the adapter contract, not a native argument supported by every agent CLI. See the importable [custom-runner.mjs](examples/custom-runner.mjs) example. Your adapter should write the skill files to a directory or register a virtual file reader so that both `project-indexer/templates/*` and skill-relative paths such as `templates/*` are accessible. For example:

```javascript
const files = new Map(request.skill.files.map(file => [`project-indexer/${file.relPath}`, file.content]));
function readSkillFile(path) {
  const key = path.startsWith('project-indexer/') ? path : `project-indexer/${path}`;
  if (!files.has(key)) throw new Error('Skill asset is unavailable');
  return files.get(key);
}
readSkillFile('templates/cleancode-template.md');
readSkillFile('project-indexer/templates/cleancode-overrides.md');
readSkillFile('templates/claude-md-compaction.md');
```

Refuse to start if templates are inaccessible. Passing only the prompt and discarding the skill assets is insufficient. The SDK does not modify the user's global skill directory. A custom `skillContent` replaces the skill content in both the prompt and the `SKILL.md` snapshot. Your adapter must supply any additional assets required by a custom skill.

## API and lifecycle

- `prepareIndexBuild({workspaceDir, skillContent?, scope?})`: Produces the complete prompt, relative output paths, and warnings without writing files. Requires an absolute path on the local system. Does not create directories, deploy tools, or start an agent. An explicitly blank skill is rejected.
- `prepareWorkspaceTools(workspaceDir)`: Creates `.agentmesh/` only inside an existing workspace, overwrites and verifies `.index-graph-tools.py`, and returns warnings on failure. Does not create a missing project root.
- `startIndexBuild(options, runner)`: Prepares the request, deploys tools, and calls the runner once. Returns `{handle, prepared, tools}`. Tool deployment failures allow the agent to use a fallback; runner errors propagate unchanged.
- `readIndexFileInfo` / `readIndexMtime`: Inspect the existence and modification time in milliseconds of `.claude-index/index.md`.
- `getProjectIndexerSkill` / `readProjectIndexerAsset` / `resolveProjectIndexerAssetDir`: Access the bundled skill and assets. Asset reads fall back to complete embedded copies when files are missing from disk.
- `measureClaudeMdForBuild`: Measures the root `CLAUDE.md`, up to 4 MiB, and degrades gracefully on failure. Does not modify its contents.

The root entry point also exports the underlying prompt APIs, scope sanitization, deployment functions, and their types. `/graph-types` provides browser-safe graph types and constants. `/budget` and the root entry point are Node.js-only. Frontend code must use `import type` for budget types.

The host application must serialize indexing jobs for the same workspace. The SDK does not coordinate concurrent jobs or provide cross-process locks. Tool deployment rejects links at `.agentmesh` or the target script to avoid following them outside the project.

A successful `startIndexBuild` call means the runner accepted the request. A real agent still needs to complete the semantic index. The caller manages processes, cancellation, timeouts, and status. The SDK does not hold account credentials, write to a database, or start timers. Python scanning and graph authoring are separate from agent-driven semantic indexing. A changed modification time only indicates that the index file was updated; it does not prove that the index, graph, and history files were completed as a single transaction. File watching, batch jobs, and UI entry points belong to the host application.

## Development and verification

Run these commands from this repository's root directory:

```sh
npm ci --include=dev
npm run check:assets
npm run build
npm test
npm pack
```

`npm run build` checks the assets, clears this package's `dist` directory, and compiles the source. `npm run generate:assets` updates the normalized embedded copies; `npm run check:assets` verifies them. `npm pack` builds automatically and produces `aragonmesh-project-indexer-0.1.1.tgz`. Installing the tarball does not require TypeScript or compile the source. Rebuild after source changes, then restart or reload your host application as needed.

## Repository structure

- `src/`: TypeScript SDK, prompts, graph types, and embedded assets.
- `assets/`: Python graph tool, original skill files, and templates.
- `examples/`: Integration example for a custom agent runner.
- `tests/`: Tests for the public API, asset consistency, prompts, and workspace boundaries.
- `scripts/generate-assets.mjs`: Asset generation, validation, and build entry point.

## Contributing

Report problems through [Issues](https://github.com/xdrshjr/AragonAgentIndexer/issues) or submit a pull request. Run the development and verification commands above before submitting changes. When changing skills or templates, regenerate the embedded assets and review the affected test baselines.

Automated tests verify the SDK contract and package contents. Integrators should evaluate actual indexing quality with their own models and agent runners.

## License

[MIT](LICENSE). The original skill metadata attributes the skill to AragonAgent-Skills. All skill files retain their original content from the extraction.
