import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { buildIndexBuildPrompt } from '../src/index.js';
const fixture = JSON.parse(readFileSync(new URL('./fixtures/prompts.json', import.meta.url), 'utf8'));
test.each(fixture.cases)('迁移前提示词字节保持：$workspaceDir', ({skillContent, workspaceDir, opts, prompt}) => {
  expect(buildIndexBuildPrompt(skillContent, workspaceDir, opts)).toBe(prompt);
});
