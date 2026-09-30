---
name: project-indexer
description: Generate and use project index for quick codebase understanding in new Claude Code sessions. Scans project structure, extracts code symbols, creates a navigable feature map, and injects a Google-style Clean Code Guidelines section into CLAUDE.md.
metadata: {"version": "1.2.0", "tags": ["productivity", "codebase", "indexing", "navigation", "cleancode"]}
license: MIT
---

# Project Indexer

Generate a structured index of any codebase to help Claude Code quickly understand project structure in new sessions with minimal context usage.

## When to Use This Skill

Use this skill when:
- Starting work on a new or unfamiliar project
- Beginning a new Claude Code session and need project context
- User says: "explore the project", "understand the codebase", "project structure"
- User says: "了解项目", "探索项目", "项目结构", "索引项目"
- User says: "generate index", "create project map", "生成索引"
- User explicitly calls `/project-indexer`
- User wants to regenerate/update the index: "regenerate index", "更新索引"
- User wants to remove or restore the injected Clean Code Guidelines: "disable cleancode", "enable cleancode"

## Core Principle

The index serves as a **navigation map**, not a code copy. It provides just enough information for Claude to:
1. Understand the project globally (type, tech stack, architecture)
2. Navigate to specific areas on demand (feature map, file index)
3. Know what functions/classes exist without reading all files (symbol index)

## Unattended Runs

**Read this before any step that asks a question.**

This skill is also launched non-interactively — the「构建索引」action and the
「all projects」batch start an agent with a prompt ending in "then stop. Do not
wait for further instructions." **No human will answer.** In such a run every
`AskUserQuestion` below is skipped and its **deterministic default** is taken:

| Question | Deterministic default |
|---|---|
| First-Time Generation Step 1 (all four) | Defaults: standard exclusions, auto-detected priorities, auto-detected tech stack, cleancode preset A (Strict) |
| First-Time Generation Step 2 (environments) | Skip — do not create `environments.md` |
| Regeneration Step 2 (environments) | **A** (keep current configuration) |
| Regeneration Step 2b (cleancode) | **A** (refresh), unless `config.md` says `Enabled: No` |
| Regeneration Step 3 ("Proceed?") | Proceed |
| Step 6b (budget) | Never asks under any circumstance |

Announce the defaults you took in the Step 7 summary instead of asking.

**Why this matters.** Stopping on a question in an unattended run does not fail
loudly — the agent waits, the build is eventually recorded as stalled, and
everything after that question never happens. Step 6b is last in the flow, so a
question asked in Step 2 silently disables it entirely.

## Workflow

### Step 1: Check for Existing Index

First, check if `.claude-index/index.md` exists in the project root.

```
IF .claude-index/index.md exists:
    → Go to "Using Existing Index" section
ELSE:
    → Go to "First-Time Generation" section
```

---

## Using Existing Index

When `.claude-index/index.md` already exists:

1. **Read the index file**
   ```
   Read .claude-index/index.md

   IF the index is empty, malformed, or missing key sections (Project Overview, Feature Map, File Index):
       → Inform user: "The existing index appears incomplete or corrupted. I'll regenerate it."
       → Preserve config.md and environments.md if intact
       → Go to "First-Time Generation" section
   ```

2. **Read CLAUDE.md if exists** (independent file for project conventions)
   ```
   Read CLAUDE.md (if present)
   ```

3. **Check for environments configuration**
   ```
   IF .claude-index/environments.md exists:
       Read it silently (available for SSH/deployment context)
       → No prompt needed
   ELSE:
       AskUserQuestion:
       "I notice no server environments are configured for this project.
       Would you like to set up server/cloud environment connections?
       This enables SSH workflows (e.g., /ssh-remote) and helps identify deployment-related files.

       A) Yes, configure server environments
       B) No, skip"

       Candidate answers: ["A", "B"]

       IF A: Follow the environment configuration flow (same as First-Time Generation Step 2),
             then generate .claude-index/environments.md using the format from Step 5,
             update .claude-index/config.md to set "Environments Configured: Yes",
             and update CLAUDE.md with the Server Environments subsection
   ```

4. **Inform the user**
   ```
   "I've loaded the project index. I now have an overview of:
   - Project structure and tech stack
   - Feature areas and their locations
   - Key functions and classes

   Ready to help with development. What would you like to work on?"
   ```

5. **Use the index for navigation**
   - When user asks about a feature, use the Feature Map to locate relevant files
   - When user needs a specific function, use the File Index to find it
   - Read actual source files only when needed for detailed work

---

## First-Time Generation

When no index exists, guide the user through configuration and generate the index.

### Step 1: Gather Configuration

Ask the user these questions (provide defaults):

**Question 1: Directories to Exclude**
```
"Which directories should I exclude from indexing?

Default exclusions: node_modules, .git, dist, build, __pycache__, .venv, vendor, coverage, .next, .nuxt, .cache, target, bin, obj

Would you like to:
A) Use defaults
B) Add more exclusions
C) Customize the list"
```

**Question 2: Priority Directories**
```
"Which directories are most important to index in detail?

Options:
A) Let me auto-detect based on project structure (Recommended)
B) Specify priority directories (e.g., src/, lib/, core/)
C) Index everything equally"
```

**Question 3: Tech Stack (Optional)**
```
"I'll auto-detect the tech stack, but you can specify if needed:
- Press Enter to auto-detect
- Or tell me: e.g., 'Next.js + FastAPI' or 'Vue + Django'"
```

**Question 4: Clean Code Guidelines Preferences**

```
AskUserQuestion:
"I'll also inject a ~1,500-char Clean Code Guidelines section into CLAUDE.md
to guide future agents (Google-style: file/method size caps, naming, errors,
tests, review checklist). What style do you want?

A) Google style, strict (60-line methods, 1,000-line files) — recommended
B) Google style, relaxed (use the literal brief: 600-line methods)
C) Custom — I'll specify limits one by one
D) Skip — don't add this section"

Candidate answers: ["A", "B", "C", "D"]
```

Treat this as `CleanCodeConfig.preset`:

| Choice | `preset`  | `MAX_METHOD_LINES` | Other defaults                                  |
|--------|-----------|--------------------|-------------------------------------------------|
| A      | `strict`  | 60                 | file 1000, params 5, cyclomatic 10, nest 4      |
| B      | `relaxed` | 600                | file 1000, params 5, cyclomatic 10, nest 4      |
| C      | `custom`  | per-user           | see four follow-up questions below              |
| D      | `disabled`| —                  | Step 5b is skipped; `Enabled: No` is persisted  |

> **Note on choice B.** The user's original brief said "600 lines per method".
> Google's published style guides recommend ~40 lines. Choice A is the
> *recommended* default; choice B exists to honour the brief literally if the
> user really wants the looser cap.

**If the user picks C (Custom), ask four sequential `AskUserQuestion` calls — one per limit.**
Bundling all four into one free-form prompt is forbidden — silent parse
failures are the most common feedback on free-form numeric prompts. Each
question must show the default and the allowed range, and accept either a
numeric answer or `"use default"`.

| Field                  | Default | Allowed range | Out-of-range / unparseable behavior |
|------------------------|---------|---------------|--------------------------------------|
| `MAX_FILE_LINES`       | 1000    | 200 – 5000    | fall back to default, note in confirmation summary |
| `MAX_METHOD_LINES`     | 60      | 20 – 600      | fall back to default, note in confirmation summary |
| `MAX_FUNCTION_PARAMS`  | 5       | 2 – 10        | fall back to default, note in confirmation summary |
| `MAX_CYCLOMATIC`       | 10      | 5 – 25        | fall back to default, note in confirmation summary |

After all four answers are collected, show a single confirmation summary
listing the final values and any fallbacks, then proceed.

Persist the chosen preset and final limits into `.claude-index/config.md`
per the `## Clean Code Settings` block in Step 5.

If the user picks D: skip Step 5b entirely, do not add cleancode markers to
`CLAUDE.md`, and persist `Enabled: No` to `config.md`. Mention once that the
section can be re-added later by saying "enable cleancode".

`MAX_LINE_LENGTH` and `MAX_NESTING_DEPTH` are not asked here; they default to
`100` (Python override: `80`) and `4` respectively, with language-aware
overrides applied at Step 5b.

### Step 2: Project Environment Configuration (Optional)

Before scanning, ask the user about their project's deployment and server environment. This information helps contextualize the index (e.g., identifying deployment configs, CI/CD files) and enables SSH workflows later.

**Question: Deployment Context**
```
AskUserQuestion:
"Does this project deploy to any servers or cloud environments?

Understanding your deployment topology helps me:
- Identify relevant configuration and deployment files during scanning
- Set up SSH connection details for remote workflows (e.g., /ssh-remote)

A) Yes — I have server environments to configure (dev, staging, production, etc.)
B) Not yet — but I plan to deploy later (skip for now, can configure later via regeneration)
C) No — this is a local-only / library / CLI project (skip entirely)"

Candidate answers: ["A", "B", "C"]
```

**If user selects A:**

For each environment the user wants to add, collect via AskUserQuestion:

```
AskUserQuestion:
"Please provide the details for this server environment.

Format — fill in what applies, leave blank or say 'N/A' for the rest:

1. Environment name (e.g., dev, staging, production):
2. Host (IP address or hostname):
3. SSH Port (default: 22):
4. Username (SSH login user):
5. Auth method:
   A) SSH key (recommended) — provide key path
   B) Password — will NOT be stored; reference a secret manager instead
6. Working directory on server (e.g., /home/user/app):
7. Notes (optional — e.g., 'GPU server', 'behind VPN', 'Docker host'):

Please provide all details in your response."

Note: This is a free-form question — no candidate answers needed.
```

After collecting each environment, confirm and ask:

```
AskUserQuestion:
"Environment '{name}' configured:
- Host: {host}:{port}
- User: {username}
- Auth: {method}

Add another environment?

A) Yes, add another environment
B) No, done with environments"

Candidate answers: ["A", "B"]
```

Repeat until user selects B.

**If user selects B or C:** Continue to Step 3.

> **Security:** Never collect or store actual passwords. For password auth, only store "Password (via secret manager)" as the auth method. Store SSH key **paths**, not key contents.

> **Graceful handling:** If the user provides incomplete information (e.g., missing port or auth method), use sensible defaults (port 22, SSH key auth) and note the assumptions in the confirmation. Only re-ask if critical fields (host, username) are missing.

### Step 3: Scan and Analyze Project

Perform these analysis steps:

1. **Traverse file structure** with exclusion rules
2. **Detect project type**: frontend / backend / fullstack / library / CLI / monorepo
3. **Identify primary languages** and their percentages
4. **Detect frameworks** (React, Vue, Next.js, Express, FastAPI, Django, etc.)
5. **Find entry points**: main.ts, index.js, app.py, main.go, etc.
6. **Group files by feature/domain**: auth/, api/, components/, utils/, etc.
7. **Extract exported symbols**: public classes, functions, constants with signatures
8. **Generate descriptions**: one-line AI-generated description for each file/module
9. **Analyze dependencies**: module-level dependency relationships

### Step 4: Apply Adaptive Sizing

Adjust detail level based on project size:

| Project Size | Files | Strategy |
|--------------|-------|----------|
| Small | <50 | Detailed index - include all files with full symbol extraction |
| Medium | 50-200 | Standard index - full coverage with concise descriptions |
| Large | 200+ | Focused index - prioritize core code, summarize peripheral areas |

For large projects:
- Focus detailed indexing on priority directories
- Provide summary-level coverage for other areas
- Group similar utility files together

### Step 5: Generate Index Files

Create files in `.claude-index/`:

**1. config.md** - Stores configuration for future regeneration
```markdown
# Index Configuration

## Excluded Directories
- node_modules
- .git
- [other exclusions...]

## Priority Directories
- src/
- [other priorities...]

## Tech Stack
- Frontend: [detected/specified]
- Backend: [detected/specified]
- Language: [primary language]

## Index Settings
- Generated: [timestamp]
- Project Root: [path]
- Index Version: 1.0
- Environments Configured: [Yes | No]
```

**2. index.md** - Main index file (see format below)

**3. environments.md** (if user opted in at Step 2) - Server environment connections

Generate using the format from `templates/environments-template.md`. Include the security warning header, then create a `## {Environment Name}` section for each environment the user configured. Remove the example sections from the template — only include real environments.

Also append a `## Clean Code Settings` block to `config.md` so that future
regeneration knows which preset and limits to reuse:

```markdown
## Clean Code Settings
- Enabled: [Yes | No]
- Preset: [strict | relaxed | custom | disabled]
- MAX_FILE_LINES: 1000
- MAX_METHOD_LINES: 60
- MAX_FUNCTION_PARAMS: 5
- MAX_CYCLOMATIC: 10
- MAX_LINE_LENGTH: 100
- MAX_NESTING_DEPTH: 4
```

When the user picked D (Skip), write `Enabled: No`, `Preset: disabled`, and
fill the numeric fields with the strict defaults — they are kept so that a
later "enable cleancode" can switch `Enabled` back to `Yes` without losing
context.

### Step 5b: Compose Clean Code Guidelines

**Skip this step entirely if the user picked D (Skip) at Step 1 Question 4,
or if `config.md` already records `Enabled: No` (see Regeneration Step 2b).**

Otherwise, compose the Clean Code Guidelines block that will be injected into
`CLAUDE.md` at Step 6.

**Inputs.** The language and framework set that the agent has identified
during Step 3.

> **Important — Step 3 is procedural, not data-producing.** Step 3 is a list
> of analysis instructions; it does NOT emit a structured JSON file. Carry
> the language / framework set in working memory (formed from file
> extensions, dependency manifests such as `package.json`,
> `pyproject.toml`, `Cargo.toml`, `go.mod`, plus entry-point detection) and
> consume it directly here. **Do not add an intermediate JSON file.**
>
> *Primary language disambiguation:* include any language that accounts for
> **≥ 10% of source files** after applying exclusions. Languages below 10%
> are incidental and do not contribute to override merging. If uncertain,
> prefer the language(s) of the entry points.

**Algorithm.**

1. **Load the template.** `Read project-indexer/templates/cleancode-template.md`.
2. **Load the override table.** `Read project-indexer/templates/cleancode-overrides.md`.
3. **Compute language-aware overrides.** For each detected primary language,
   pick its row from the override table. When two or more rows apply, take
   the **minimum** across all detected languages for every numeric column
   (`MAX_FILE_LINES`, `MAX_METHOD_LINES`, `MAX_LINE_LENGTH`,
   `MAX_FUNCTION_PARAMS`). Rationale: a polyglot repo should default to the
   tightest rule so agents don't accidentally apply the loose rule to the
   wrong file.
4. **Apply user-chosen preset.** Preset values from Step 1 Question 4 take
   priority for the four fields the user can override
   (`MAX_FILE_LINES`, `MAX_METHOD_LINES`, `MAX_FUNCTION_PARAMS`,
   `MAX_CYCLOMATIC`). If the user picked `strict` or `relaxed`, also
   intersect with the language-aware minimum so the result is never looser
   than the language baseline. If the user picked `custom`, honour the
   user's numbers verbatim — do **not** silently auto-correct against the
   language table, but record any divergence in the confirmation summary.
5. **Substitute placeholders.**
   - `{{MAX_FILE_LINES}}`
   - `{{MAX_METHOD_LINES}}`
   - `{{MAX_FUNCTION_PARAMS}}`
   - `{{MAX_CYCLOMATIC}}`
   - `{{MAX_LINE_LENGTH}}` (default 100; Python override 80; polyglot uses min)
   - `{{MAX_NESTING_DEPTH}}` (default 4)
   - `{{PRIMARY_LANGUAGES}}` — comma-joined list, e.g. `TypeScript, Python`
   - `{{LANGUAGE_HINTS}}` — bulletized language-specific bullets built by
     concatenating each matching row's `Notes` cell, prefixed with the
     language name, deduped by exact string. Example:
     `- TypeScript: Prefer interface over type for public APIs.`
6. **Verify** that no `{{placeholder}}` strings remain in the rendered
   output. **Do NOT** count Chinese characters at runtime — the 1,400 – 1,700
   range is a template-author-time invariant (see §8.1 of the spec), not a
   per-run check.
7. **Hand the final string to Step 6.** Step 5b does not write a file
   directly. The section only lives inside `CLAUDE.md` so it travels with
   the project.

### Step 6: Update CLAUDE.md

After generating the index files, update the project's `CLAUDE.md` to inform future Claude Code sessions about the index:

**If `CLAUDE.md` exists:**
1. Read the existing content
2. Look for `## Project Index` section
3. If found: Replace that entire section (including any `### Server Environments` subsection) with updated content
4. If not found: Append the section at the end of the file

**If `CLAUDE.md` does not exist:**
1. Create a new `CLAUDE.md` file with the Project Index section
2. Inform user they can add more project-specific instructions to this file

**Content to add/update:**
```markdown
## Project Index

This project has a pre-generated index for quick codebase understanding.

- **Location:** `.claude-index/index.md`
- **Last Updated:** {YYYY-MM-DD}
- **Contents:** Project overview, feature map, file index, exported symbols, module dependencies

**Usage:** Read `.claude-index/index.md` to quickly understand the project structure before making changes. The index provides a navigation map of the codebase without needing to explore every file.

**Regenerate:** Say "regenerate index" or "更新索引" to update the index after major changes.
```

**If environments.md was generated, also append this subsection under `## Project Index`:**
```markdown
### Server Environments

Server environment configurations are stored in `.claude-index/environments.md`. This file contains connection details for development, staging, and production servers. Use with the `/ssh-remote` skill for remote operations.

> **Security Note:** Passwords and secrets are NOT stored in this file. Use SSH keys or reference your team's secret manager.
```

**Clean Code Guidelines upsert (new in v1.1.0).**

After the `## Project Index` section has been written, upsert a second
managed section, `## Clean Code Guidelines`, containing the string produced
by Step 5b. The block is wrapped in HTML-comment markers so future runs can
locate it even if the heading is reworded:

```markdown
## Clean Code Guidelines

<!-- project-indexer:cleancode:begin v1.1.0 -->
{{rendered template body from Step 5b}}
<!-- project-indexer:cleancode:end -->
```

**Upsert algorithm:**

1. Read the existing `CLAUDE.md` content (or empty string if the file does
   not exist).
2. Locate any existing block:
   - **First**, search for the begin marker with the *version-agnostic*
     regex `<!-- project-indexer:cleancode:begin v\d+\.\d+\.\d+ -->` and the
     literal end marker `<!-- project-indexer:cleancode:end -->`. **Never**
     match the begin marker as a literal string with a hard-coded version —
     doing so causes silent duplicate-block bugs after every version bump.
   - **Fallback**, if no markers are found, search for a `## Clean Code Guidelines`
     heading and treat the region from that heading up to the next `## `
     heading (or EOF) as the block.
3. If a block is found, replace it with the new content. If the version
   number found inside the existing begin marker differs from the running
   skill version, announce one line **before** writing:
   `"Upgrading cleancode block from vX.Y.Z to vA.B.C"`.
4. If no block is found, insert one:
   - If `## Project Index` is present, append the new section immediately
     after the Project Index section.
   - If `## Project Index` is also missing (brand-new `CLAUDE.md`), append
     both sections after any pre-existing content, separated by a single
     blank line, in the order Project Index → Clean Code Guidelines.
5. When writing a fresh block, embed the current `_meta.json` `version`
   literally into the begin marker (e.g. `v1.1.0`).

**Section ordering is "first-insert only".** The rule "Project Index first,
then Clean Code Guidelines" applies **only** when a section is being added
for the first time. If both sections already exist (in any order, with or
without other `## ` sections between them), the skill must preserve the
user's existing ordering and any intermediate sections; only the content
between the cleancode markers is replaced. Re-flowing or re-ordering is
forbidden — users edit CLAUDE.md by hand and that work must not be silently
undone.

If the file ends without a trailing newline, add one before appending.
Always write `CLAUDE.md` as UTF-8.

If the user picked D (Skip) at Step 1 Question 4, or if `config.md` records
`Enabled: No`, **do not** insert or update the Clean Code block.

### Step 6b: CLAUDE.md Budget (new in v1.2.0)

`CLAUDE.md` enters every agent session here, so its length is a cost everyone pays.
Steps 5b/6 own two managed sections; **this step owns the total.** Never ask a
question here.

1. **Count characters yourself** (`string.length`, not bytes, not Chinese
   characters). Any figure in the launch prompt was measured when that prompt was
   built — possibly hours earlier, on another machine. Yours wins.
2. **Pick the tier:**
   - `lean` (<= 40,000): do nothing beyond Step 6. Stop here.
   - `watch` (40,001 – 60,000): change nothing; report the total and three
     largest units in Step 7, and record them in `config.md`.
   - `over` (> 60,000): run the compaction pass below.
3. `Compaction: Disabled` in `config.md` skips the pass; say so in Step 7.

**Compaction pass — the order is load-bearing.**

0. **Gate.** Run `git check-ignore -q .claude-index/notes/.keep`. Exit 0 = that
   directory is git-ignored: **abandon the whole pass** and say so in Step 7.
   Moving prose into an unversioned directory is deletion, not compaction: clone
   the repo elsewhere and the pointers lead nowhere. Any other outcome (not a repo,
   no git) abandons too — fail closed.
1. **Split into units.** A unit is a `## ` section with everything under it. Over
   12,000 characters, split it into its preamble (`## ` heading up to the first
   `### `) plus one unit per `### `. `## ` / `### ` in fences are not headings.
2. **Tier each unit. Never touch Tier A:**
   - under 2,500 characters (all risk, no gain);
   - a `## ` preamble — the chapter's navigation sentence;
   - anything inside `<!-- project-indexer:... -->` markers, or `## Project Index`;
   - a unit carrying an HTML comment marker that is **not** `project-indexer:`;
   - a unit whose **heading line** names Commands, Workflow Rules, Path Aliases,
     Environment Variables, Build Output or Patches.

   Match the **heading line only — never body text.** Prohibitions in the body
   (`禁止`, `严禁`, `MUST`, `Do NOT`) say which sentences to **keep**, not whether
   to compact. Matching them immunises most of a mature `CLAUDE.md` — long sections
   are long *because* they are full of such clauses — and the pass becomes a no-op
   that still reports success.
3. **Order and stop.** Sort the rest by size, descending. Compact one at a time,
   re-measuring after each. Stop at <= 40,000 characters or after **12** units;
   the remainder waits for the next index build.
4. **Notes first, `CLAUDE.md` second.** Per unit: write the **verbatim original** to
   `.claude-index/notes/<slug>.md` with the front matter from
   `templates/claude-md-compaction.md`, read it back, then rewrite the section. If a
   read-back fails, **abandon the pass and leave `CLAUDE.md` untouched** — this is
   the one path here that can destroy text existing nowhere else.
   - If that file exists with a different front-matter `heading:`, **skip the
     unit**. Never overwrite: the write succeeds and someone else's original is gone.
   - `<slug>`: the kebab name in the heading's trailing parentheses when present
     (`## 通知中心（notification-center）` -> `notification-center`); else the kebab
     of a plain-ASCII heading; else `section-<first 8 hex of sha256(heading)>`.
     **Never number the slug** — indices shift when a section is added above, and
     the next run would overwrite a different unit's notes.
5. **Write the stub** (600–900 chars) exactly as that template specifies.
6. **Idempotence.** A unit already carrying a `project-indexer:compact` marker is
   **never** compacted again — only verify the notes file its pointer names still
   exists. Without it, every run re-summarises the summary until the meaning is
   gone, and each individual diff looks perfectly reasonable.
7. **Re-measure** and write `## CLAUDE.md Budget` into `config.md`. Still above
   60,000? **Report it and stop.** Never compact a Tier A unit to reach a number:
   60,000 decides whether to act, not where you can land.

### Step 7: Inform User

```
"Project index generated successfully!

Created:
- .claude-index/index.md (main index)
- .claude-index/config.md (configuration)
- .claude-index/environments.md (server environments)  ← only if configured
- Updated CLAUDE.md with index information
- Clean Code Guidelines (~1,500 chars, Google-style) added to CLAUDE.md  ← only if not skipped
- CLAUDE.md budget: [N] chars ([tier])  ← always
- Compacted [N] sections into .claude-index/notes/  ← only in the `over` tier

The index includes:
- Project overview and tech stack
- Feature map with [N] areas identified
- [N] files indexed with [N] exported symbols
- Module dependency graph

Future Claude Code sessions will automatically know about this index from CLAUDE.md.
Future agents will follow the clean-code rules automatically. Say
'regenerate index' to refresh; say 'disable cleancode' to drop the section.

I'm now ready to help with development. What would you like to work on?"
```

Omit the cleancode bullet and trailing sentence when the user picked D at
Step 1 Question 4 (i.e. when `Enabled: No` is persisted).

**Never omit the budget report (v1.2.0).** State the tier even when nothing was
compacted, and state the reason whenever the pass was skipped or abandoned:
`Compaction: Disabled`, the git-ignore gate, a failed read-back, a slug conflict.
In an unattended run this summary is the only place a human learns that compaction
did not happen — "the build succeeded" and "the file was compacted" are two facts,
not one.

---

## Regeneration Flow

When user requests index regeneration ("regenerate index", "更新索引", "refresh index"):

1. **Read existing config**
   ```
   Read .claude-index/config.md to preserve:
   - Exclusion rules
   - Priority directories
   - Tech stack settings
   ```

2. **Check for environments configuration**
   ```
   IF .claude-index/environments.md exists:
       Inform user: "Server environments configuration (.claude-index/environments.md) detected."
       AskUserQuestion:
       "How would you like to handle server environments during regeneration?

       A) Keep current configuration
       B) Update environments (re-configure)
       C) Remove environments configuration"

       Candidate answers: ["A", "B", "C"]

       IF A: Preserve environments.md as-is during regeneration
       IF B: Follow the environment configuration flow from First-Time Generation Step 2,
             overwrite existing environments.md, update config.md "Environments Configured: Yes"
       IF C: Delete environments.md, remove Server Environments subsection from CLAUDE.md,
             and update config.md to set "Environments Configured: No"
   ```

2b. **Clean Code Guidelines handling (new in v1.1.0)**

   ```
   IF CLAUDE.md contains the cleancode markers
       (regex `<!-- project-indexer:cleancode:begin v\d+\.\d+\.\d+ -->`)
       OR contains a "## Clean Code Guidelines" heading:

       AskUserQuestion:
       "Clean Code Guidelines section detected in CLAUDE.md.
        How would you like to handle it during regeneration?

        A) Refresh — re-compose with current language detection
        B) Keep — leave existing content untouched
        C) Remove — drop the section from CLAUDE.md"

       Candidate answers: ["A", "B", "C"]

       IF A: Run Step 5b, then Step 6 upsert. Persist any preset changes
             to config.md.
       IF B: Skip Step 5b. Step 6 must NOT touch the cleancode block.
       IF C: Step 6 deletes the cleancode block (markers + content) and
             does not re-insert it. Set config.md `Enabled: No`.

   ELSE (no markers, no heading):

       1. Read .claude-index/config.md. If a "## Clean Code Settings" block
          exists AND its `Enabled` field is `No`:
            → SKIP cleancode injection.
            → Inform the user once: "Clean Code Guidelines were previously
              disabled (config.md). Say 'enable cleancode' to re-add them."
            → Do NOT proceed to Step 5b.

       2. Otherwise (Enabled: Yes, or the Clean Code Settings block is
          absent — i.e. config.md was produced by v1.0.0 and this is the
          first cleancode-aware regeneration):
            → Default behavior = choice A (compose and inject).
            → Announce the action *before* writing so the user can
              interrupt: "I'll also add a Clean Code Guidelines section
              to CLAUDE.md."
            → Run Step 5b, then Step 6 upsert.
   ```

   > **Why the `Enabled: No` short-circuit?** A user who picked Skip once
   > and later hand-deleted the markers (or never had markers because we
   > skipped) would be re-injected on every regeneration if the default
   > were unconditional. The `config.md` flag is the single source of
   > truth for opt-out. Honour it.

   > **Special trigger phrases:**
   > - "disable cleancode" → run choice C (remove markers + content) without
   >   re-running the full regeneration; update `config.md` `Enabled: No`.
   > - "enable cleancode" → run choice A (compose and inject) without
   >   re-running the full scan; update `config.md` `Enabled: Yes`.

2c. **CLAUDE.md budget decision (new in v1.2.0)**

   Read `.claude-index/config.md`. If a `## CLAUDE.md Budget` block says
   `Compaction: Disabled`, note it and have Step 6b skip its pass; otherwise note
   "compaction enabled". Same opt-out semantics as `Clean Code Settings`'
   `Enabled: No`.

   > **Decide here, act in Step 6b.** Compact nothing at this point. Step 6b runs
   > inside Step 4's expansion — after `index.md` is regenerated and after Step 6
   > upserts the two managed sections. Compacting earlier points the new stubs at a
   > stale index, and Step 6 then rewrites part of what you just wrote.

3. **Confirm with user**
   ```
   "I'll regenerate the index using your existing configuration:
   - Excluded: [list]
   - Priority: [list]
   - Environments: [kept | updating | removing]
   - Clean Code Guidelines: [refresh | keep | remove | inject (first time) | skipped (Enabled: No)]
   - CLAUDE.md compaction: [enabled | disabled (config.md)]

   Proceed? (Or would you like to update the configuration?)"
   ```

4. **Re-scan and regenerate**
   - Follow Steps 3, 4, 5, 5b, 6, **6b**, 7 from First-Time Generation (skip Step 2 — environments already handled above in this flow's Step 2; skip Step 5b according to the Step 2b decision; Step 6b honours the Step 2c decision).
   - Preserve config.md, regenerate index.md
   - Preserve, update, or remove environments.md based on user choice above
   - Refresh, keep, or remove the Clean Code Guidelines block based on the Step 2b decision
   - Update the timestamp in CLAUDE.md's Project Index section
   - Measure CLAUDE.md and, in the `over` tier, run the Step 6b compaction pass

---

## Index File Format

The `index.md` should follow this structure:

```markdown
# Project Index: {project-name}

> Auto-generated by project-indexer | Last updated: {YYYY-MM-DD}

## Project Overview

- **Type:** {Frontend | Backend | Fullstack | Library | CLI | Monorepo}
- **Languages:** {TypeScript (70%), Python (30%)}
- **Frameworks:** {Next.js, FastAPI}
- **Entry Points:** `{src/app/page.tsx}`, `{api/main.py}`

## Feature Map

### {Feature Name} (`{path}/`)
Entry: `{entry-file}`
- {One-line description of this feature area}
- **Key exports:**
  - `{functionName}({params}): {returnType}` - {description}
  - `{ClassName}` - {description}

### Authentication (`src/auth/`)
Entry: `src/auth/index.ts`
- User authentication, session management, and authorization
- **Key exports:**
  - `login(credentials: LoginInput): Promise<User>` - Authenticate user
  - `logout(): void` - Clear session and tokens
  - `useAuth(): AuthContext` - React hook for auth state
  - `withAuth(Component)` - HOC for protected routes

### API Layer (`src/api/`)
Entry: `src/api/client.ts`
- REST API client with error handling and request interceptors
- **Key exports:**
  - `apiClient` - Configured axios instance
  - `useQuery<T>(endpoint): SWRResponse<T>` - Data fetching hook
  - `useMutation<T>(endpoint): MutationResult<T>` - Data mutation hook

[Continue for each feature area...]

## Module Dependencies

- `auth` → `api` (uses apiClient for authentication requests)
- `pages` → `auth`, `components` (imports hooks and UI components)
- `api` → (standalone, no internal dependencies)
- `components` → `utils` (uses helper functions)

## File Index

### src/auth/
| File | Description |
|------|-------------|
| index.ts | Auth module entry point, re-exports public API |
| login.ts | Login logic, credential validation, token handling |
| session.ts | Session storage, refresh token management |
| hooks.ts | React hooks: useAuth, useUser, usePermissions |
| types.ts | TypeScript types for auth entities |

### src/api/
| File | Description |
|------|-------------|
| client.ts | Axios instance with interceptors and base config |
| endpoints.ts | API endpoint path constants |
| types.ts | Request/response type definitions |
| errors.ts | Custom error classes and error handling |

### src/components/
| File | Description |
|------|-------------|
| Button.tsx | Reusable button with variants (primary, secondary, ghost) |
| Modal.tsx | Dialog component with portal and focus trap |
| Form/index.tsx | Form wrapper with validation context |
| Form/Input.tsx | Text input with label and error display |
| Form/Select.tsx | Dropdown select component |

[Continue for each directory...]
```

---

## Language Support

### Priority Support (Full Symbol Extraction)
- **JavaScript / TypeScript** (.js, .jsx, .ts, .tsx, .mjs)
- **Python** (.py)

### Best-Effort Support
- Java (.java)
- Kotlin (.kt)
- Go (.go)
- Rust (.rs)
- C/C++ (.c, .cpp, .h, .hpp)
- C# (.cs)
- Ruby (.rb)
- PHP (.php)

### Fallback Behavior
For unsupported or unknown file types:
- Include in file listing
- Provide basic file info (size, type)
- Skip detailed symbol extraction
- Generate description based on filename and location

---

## Best Practices

1. **Keep index focused** - Don't try to document everything; focus on navigation value
2. **Update when structure changes** - Regenerate after major refactoring
3. **Use with CLAUDE.md** - Index provides structure; CLAUDE.md provides conventions
4. **Trust the map** - Use index to navigate, read actual files for implementation details
5. **Honour the injected Clean Code Guidelines** - When a `## Clean Code Guidelines` section exists in CLAUDE.md, any agent (including this one) writing code in the project must respect its numeric thresholds (file size, method size, parameters, complexity, nesting) and the review checklist. The block is managed by this skill; do not hand-edit the content between the `<!-- project-indexer:cleancode:begin ... -->` and `<!-- project-indexer:cleancode:end -->` markers — use `regenerate index`, `disable cleancode`, or `enable cleancode` instead.
6. **Compaction moves prose, it never deletes it** (new in v1.2.0) - Step 6b writes the verbatim original to `.claude-index/notes/<slug>.md` **before** touching `CLAUDE.md`, and abandons the pass if it cannot be read back. Two rules make that promise real and both fail silently if dropped: the notes directory must not be git-ignored (gate 0), and a unit already carrying a `project-indexer:compact` marker is never compacted twice. When a compact stub is all you can see, the full text is one `Read` away at the path in its pointer line — follow it before concluding something is undocumented.

## Troubleshooting

**Index too large?**
- Add more directories to exclusions
- Reduce priority directories
- The adaptive sizing should handle this automatically

**Missing important files?**
- Check exclusion rules in config.md
- Ensure priority directories are set correctly
- Regenerate with updated configuration

**Outdated information?**
- Run regeneration: "regenerate index" or "更新索引"
- Index is a snapshot; regenerate after significant changes

## Error Handling and Edge Cases

**Partial or corrupted existing index:**
- If `.claude-index/index.md` exists but is empty, malformed, or missing key sections (Project Overview, Feature Map, File Index), treat it as a first-time generation and inform the user: "The existing index appears incomplete or corrupted. I'll regenerate it."
- Preserve `config.md` and `environments.md` if they are intact.

**User skips all configuration questions:**
- If user presses Enter or gives empty responses to all Step 1 questions, use all defaults: standard exclusions, auto-detect priorities, auto-detect tech stack.
- If user skips environment configuration (Step 2), proceed without any prompt repetition.

**Very large projects (1000+ files):**
- If traversal yields more than 1000 files after exclusions, warn the user and suggest adding more exclusions or narrowing priority directories before proceeding.
- Never attempt to read all files in a single pass; use Glob/Grep to sample representative files per directory.

**Permission or access errors:**
- If certain directories cannot be read (permission denied), log them in the index under a "Skipped Directories" note and continue with accessible files.
- Do not fail the entire indexing process due to a single inaccessible directory.

**Empty project or no source files:**
- If the project contains no recognizable source files after exclusions, inform the user and generate a minimal index with just the file listing and project overview.
