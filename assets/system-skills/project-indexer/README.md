# Project Indexer

A Claude Code skill that generates structured project indexes for quick codebase understanding in new sessions.

## Problem

Every new Claude Code session starts fresh without knowledge of your project. You end up repeatedly explaining the project structure or waiting for Claude to explore the codebase.

## Solution

Project Indexer creates a `.claude-index/` directory containing a structured map of your codebase:
- **Project Overview** - Type, languages, frameworks, entry points
- **Feature Map** - Organized by domain/feature with key exports
- **File Index** - Every file with one-line descriptions
- **Module Dependencies** - How modules relate to each other

It also injects a **Clean Code Guidelines** section (~1,500 Chinese chars,
Google-style — file/method size caps, naming, errors, tests, review
checklist) into `CLAUDE.md`, with language-aware overrides, so every future
agent loading `CLAUDE.md` is bound to consistent code-quality thresholds.

## Usage

### Generate Index (First Time)

Say any of these to Claude Code:
- "explore the project" / "understand the codebase" / "generate index"
- "index this project" / "scan the project" / "map the codebase"
- "了解项目" / "扫描项目" / "分析项目" / "生成索引"
- `/project-indexer`

Claude will ask you about:
1. Directories to exclude (defaults provided)
2. Priority directories to focus on
3. Tech stack (auto-detected if not specified)
4. **Clean Code Guidelines preference** — choose one of:
   - `A) Google style, strict` (60-line methods, 1,000-line files) — recommended
   - `B) Google style, relaxed` (literal-brief 600-line methods)
   - `C) Custom` — four follow-up questions for each numeric limit
   - `D) Skip` — don't add the section to `CLAUDE.md`

Before scanning, you'll also be asked about server environment connections (optional — dev, staging, production). Then it scans the project and generates `.claude-index/index.md`, `.claude-index/config.md`, and updates `CLAUDE.md` with index information **and** (unless you picked D above) a Clean Code Guidelines section.

### Use Existing Index

In a new session, Claude automatically sees the index information in `CLAUDE.md` and knows to read the index when you ask about the project.

Say:
- "explore the project"
- "了解项目"

Claude reads the existing index and is immediately ready to help with full project context.

### Regenerate Index

After major changes, say:
- "regenerate index"
- "更新索引"

Claude preserves your configuration and regenerates the content. For server environments, you can choose to keep, update, or remove the configuration during regeneration. For the Clean Code Guidelines section, you can choose to **refresh** (re-compose with current language detection), **keep** (untouched), or **remove**. Say `disable cleancode` or `enable cleancode` to flip the section on or off without re-running a full scan.

## Generated Files

```
.claude-index/
├── index.md           # Main index (project map, features, files, symbols)
├── config.md          # Configuration (exclusions, priorities, tech stack)
└── environments.md    # Server environments (optional)
```

Additionally, `CLAUDE.md` in the project root is updated with two managed sections:

```markdown
## Project Index

This project has a pre-generated index for quick codebase understanding.

- **Location:** `.claude-index/index.md`
- **Last Updated:** 2026-02-03
- **Contents:** Project overview, feature map, file index, exported symbols, module dependencies

**Usage:** Read `.claude-index/index.md` to quickly understand the project structure...

## Clean Code Guidelines

<!-- project-indexer:cleancode:begin v1.1.0 -->
{{ ~1,500-char Google-style rules, with project-specific MAX_FILE_LINES /
   MAX_METHOD_LINES / MAX_FUNCTION_PARAMS / MAX_CYCLOMATIC /
   MAX_LINE_LENGTH / MAX_NESTING_DEPTH and language-specific hints }}
<!-- project-indexer:cleancode:end -->
```

This ensures future Claude Code sessions automatically know about the index **and** are bound to the project's clean-code thresholds. The `<!-- project-indexer:cleancode:* -->` markers are load-bearing — do not hand-edit the content between them; run `regenerate index` to refresh.

## Index Content

### Project Overview
```markdown
- **Type:** Fullstack web application
- **Languages:** TypeScript (85%), Python (15%)
- **Frameworks:** Next.js, FastAPI
- **Entry Points:** src/app/page.tsx, api/main.py
```

### Feature Map
```markdown
### Authentication (`src/auth/`)
Entry: `src/auth/index.ts`
- User authentication, session management, authorization
- **Key exports:**
  - `login(credentials): Promise<User>` - Authenticate user
  - `useAuth(): AuthContext` - React hook for auth state
```

### File Index
```markdown
| File | Description |
|------|-------------|
| login.ts | Login logic and credential validation |
| session.ts | Session storage and refresh tokens |
```

## Language Support

**Full Support:** JavaScript, TypeScript, Python

**Best-Effort:** Java, Kotlin, Go, Rust, C/C++, C#, Ruby, PHP

**Fallback:** Unknown types included in file list without symbol extraction

## Configuration

The `config.md` file stores your preferences:

```markdown
## Excluded Directories
- node_modules
- .git
- dist

## Priority Directories
- src/
- lib/

## Tech Stack
- Frontend: Next.js
- Backend: FastAPI
```

## Git Handling

After generation, you can:
- **Add to .gitignore** - Keep index local to each developer
- **Commit to repo** - Share index with team members

## Server Environments (Optional)

Before scanning, you can optionally configure server environments (dev, staging, production). This stores SSH connection details in `.claude-index/environments.md` for use with the `/ssh-remote` skill.

Collected per environment:
- Environment name, host, port, username
- Auth method (SSH key recommended, or password via secret manager)
- Working directory on server
- Optional notes

> **Security:** Passwords are never stored. Use SSH keys or reference a secret manager. Consider adding `environments.md` to `.gitignore` if your team prefers not to commit infrastructure details.

When loading an existing index, if no environments are configured, you'll be asked whether to add them. If already configured, no prompt is shown.

## Tips

1. **Regenerate after refactoring** - Keep index in sync with major changes
2. **CLAUDE.md auto-discovery** - New sessions automatically know about the index via CLAUDE.md
3. **Customize exclusions** - Add project-specific directories to exclude
4. **Set priorities** - Focus indexing on your most important code

## License

MIT
