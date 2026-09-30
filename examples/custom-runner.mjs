import { startIndexBuild, readIndexFileInfo } from '@aragonmesh/project-indexer';

/** 接入方负责让 Agent 的读取工具使用此映射，或将这些文件物化到技能目录。 */
export function createSkillReader(skill) {
  const files = new Map(skill.files.map(file => [`${skill.name}/${file.relPath}`, file.content]));
  return path => {
    const key = path.startsWith(`${skill.name}/`) ? path : `${skill.name}/${path}`;
    if (!files.has(key)) throw new Error(`技能资源不可访问：${path}`);
    return files.get(key);
  };
}

export async function launchProjectIndex(workspaceDir, launchAgent) {
  const result = await startIndexBuild({ workspaceDir }, async request => {
    const readSkillFile = createSkillReader(request.skill);
    for (const name of ['cleancode-template', 'cleancode-overrides', 'claude-md-compaction']) {
      readSkillFile(`templates/${name}.md`);
    }
    // launchAgent 必须先注册 skills/readSkillFile，再启动 Agent。
    return launchAgent({ cwd: request.workspaceDir, initialPrompt: request.prompt, skills: [request.skill], readSkillFile });
  });
  return { handle: result.handle, currentIndex: readIndexFileInfo(workspaceDir) };
}
