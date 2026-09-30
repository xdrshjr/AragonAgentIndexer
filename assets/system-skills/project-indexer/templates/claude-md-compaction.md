# CLAUDE.md Compaction Template (skill v1.2.0)

Output shapes for Step 6b's compaction pass. Two files per compacted unit: the
notes file that receives the original, and the stub that replaces it in
`CLAUDE.md`.

**Write the notes file first, read it back, and only then rewrite `CLAUDE.md`.**
Reversing that order means a crash between the two writes destroys text that
exists nowhere else. This is the only irreversible path in this skill.

---

## 1. Tier decision (per unit)

Decide before writing anything. A unit is a `## ` section, or — when that section
exceeds 12,000 characters — its preamble plus one unit per `### `.

**Tier A — never modify.** Any one of these is enough:

- [ ] under 2,500 characters
- [ ] it is the preamble between a `## ` heading and its first `### `
- [ ] it lies inside `<!-- project-indexer:... -->` markers, or is the
      `## Project Index` section
- [ ] it carries an HTML comment marker that is **not** `project-indexer:`
      (another tool or the user manages it)
- [ ] its **heading line** names Commands, Workflow Rules, Path Aliases,
      Environment Variables, Build Output or Patches

Match the **heading line only**. `禁止` / `严禁` / `MUST` / `Do NOT` in the body
select which sentences survive into the stub; they do **not** grant immunity. Body
matching immunises most of a mature `CLAUDE.md`, and the pass then does nothing
while still reporting success.

**Tier C — delete, replace with a pointer.** File lists, path enumerations,
exported-symbol tables, module-dependency lists. These already exist, structured,
in `.claude-index/index.md` (`## File Index`, `## Feature Map`,
`## Module Dependencies`) and in `graph.json`. In `CLAUDE.md` they are pure
duplication.

**Tier B — summarise, keep the rules.** Everything else that is long: feature
narratives, post-mortems, design records.

---

## 2. Notes file — `.claude-index/notes/<slug>.md`

```markdown
---
source: CLAUDE.md
heading: "## 通知中心（notification-center）"
compactedAt: 2026-08-31
skillVersion: 1.2.0
originalChars: 7181
---

<the original unit, verbatim, heading line included>
```

- `heading` is the heading line **exactly** as it appears in `CLAUDE.md`. The next
  run compares it before writing: a mismatch means two units resolved to the same
  slug, and the correct action is to **skip that unit**, never to overwrite.
- The body is a byte-for-byte copy. Do not reformat, retitle, or "tidy" it — this
  file is the only remaining copy.
- `<slug>`: the kebab name inside the heading's trailing parentheses when there is
  one; else the kebab of a plain-ASCII heading; else
  `section-<first 8 hex characters of sha256 of the heading line>`. Never derive a
  slug from a position — section numbers shift and the next run silently overwrites
  a different unit's notes.

---

## 3. Stub — what replaces the unit in `CLAUDE.md`

Target 600–900 characters; 2,500 is the hard ceiling.

```markdown
## 通知中心（notification-center）

<!-- project-indexer:compact:begin v1.2.0 slug=notification-center chars=7181 -->
顶栏铃铛的通知中心：把「已经发生但用户看不见的报错」按指纹合并成一行并累加 ×N。
零协议扩张（复用既有 `system.notification`）。

**必须遵守的不变量**：
- 分类器判定顺序即语义：`insufficient_quota` 必须排在 `429 rate_limit` 之前。
- `notification-store` 只导出返回 primitive 的 selector（zustand v5 派生对象 = 无限重渲染）。

→ 完整设计与踩坑记录：`.claude-index/notes/notification-center.md`
→ 文件清单与导出符号：`.claude-index/index.md`（`## File Index` / `## Feature Map`）
<!-- project-indexer:compact:end -->
```

Rules, in order of how badly they fail when dropped:

1. **The heading line is copied verbatim and stays outside the markers.** Other
   documents, links and the user's own memory reference it.
2. **The "必须遵守的不变量" list is mandatory when the original had such rules.**
   That is the one kind of content that is neither derivable from the code nor
   present in `index.md`. A stub without it is lossy in the way that matters:
   the next agent reads a summary, does not follow the pointer, and breaks the
   rule the section existed to state. Copy those sentences; do not paraphrase them.
3. **Both pointer lines are mandatory**, even when one of them adds little. A stub
   whose pointer is missing reads as a section someone truncated.
4. **`chars=` records the ORIGINAL length**, not the stub's. It is how a later run
   reports how much was moved.
5. **The version in `:begin` is the running skill version.** Match existing blocks
   with the version-agnostic regex
   `<!-- project-indexer:compact:begin v\d+\.\d+\.\d+ [^>]*-->`, never as a literal
   with a hard-coded version — that produces duplicate blocks after every bump.

Write the stub in the same language as the original section.

---

## 4. `config.md` block

Upsert into `.claude-index/config.md` on every run, `over` tier or not:

```markdown
## CLAUDE.md Budget

- **Chars:** 205573
- **Tier:** over
- **Last Measured:** 2026-08-31
- **Last Compacted:** 2026-08-31
- **Compaction:** Enabled
- **Sections Compacted:** 12
- **Notes Bytes:** 148230
```

`Compaction: Disabled` is the user's opt-out. Once written, every later run skips
the pass and says so in its Step 7 summary. `Notes Bytes` is the total size of
`.claude-index/notes/` — compaction moves weight into that directory, and someone
has to be able to see how much.
