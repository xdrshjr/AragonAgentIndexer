# Index Configuration

> Configuration for project-indexer. Edit this file to customize index generation.

## Excluded Directories

Directories to skip during indexing:

- node_modules
- .git
- dist
- build
- __pycache__
- .venv
- venv
- vendor
- coverage
- .next
- .nuxt
- .cache
- target
- bin
- obj
- .idea
- .vscode

## Priority Directories

Directories to index in detail (leave empty for auto-detection):

- src/
- lib/
- app/
- core/

## Tech Stack

Detected or specified technology stack:

- **Frontend:** {React | Vue | Angular | Svelte | Next.js | Nuxt | etc.}
- **Backend:** {Express | FastAPI | Django | Rails | Spring | etc.}
- **Language:** {TypeScript | JavaScript | Python | Go | etc.}
- **Database:** {PostgreSQL | MySQL | MongoDB | etc.}
- **Other:** {Docker, Redis, etc.}

## Index Settings

- **Generated:** {YYYY-MM-DD HH:MM:SS}
- **Project Root:** {/path/to/project}
- **Index Version:** 1.0
- **Total Files Indexed:** {N}
- **Total Symbols Extracted:** {N}
- **Environments Configured:** {Yes | No}

## CLAUDE.md Budget

Written by Step 6b on every run. `Compaction: Disabled` is the opt-out switch:
once it says `Disabled`, every later run skips the compaction pass and says so in
its summary.

- **Chars:** {N}
- **Tier:** {lean | watch | over}
- **Last Measured:** {YYYY-MM-DD}
- **Last Compacted:** {YYYY-MM-DD | never}
- **Compaction:** {Enabled | Disabled}
- **Sections Compacted:** {N}
- **Notes Bytes:** {N}

## Custom Rules

Add any project-specific rules here:

### Additional Exclusions
```
# Add patterns to exclude
*.test.ts
*.spec.ts
__tests__/
__mocks__/
```

### File Type Overrides
```
# Treat certain files specially
*.config.js -> skip symbol extraction
*.d.ts -> skip (type definitions)
```

## Regeneration Notes

Notes for future regeneration:

- {Any special considerations}
- {Files that need manual review}
- {Known limitations}
