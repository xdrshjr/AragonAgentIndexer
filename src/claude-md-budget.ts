/**
 * index-build-claude-md-compaction · W1 —— `CLAUDE.md` 预算模型的**前后端唯一真相源**
 * （spec §2.2 / §2.3 / §4.2）。
 *
 * 零 IO、纯函数。服务端（构建路径的提示词块、overview 竖栏）与渲染端（体量 chip）
 * 共用同一把尺 —— 两份实现必然漂移，而漂移之后「面板说没超标、提示词说超标」两句话
 * 同时存在，且都不报错。
 *
 * ⚠️ **值导出是服务端面的**：`claudeMdUnitSlug()` 依赖 `node:crypto`。渲染端只
 * `import type` 本模块的类型（`shared/types.ts` 用 `export type { … } from` 转出，
 * 编译期被完全擦除），**不要**在 `src/` 里引用本模块的任何**值**，否则 Next 的浏览器
 * 打包会尝试解析 `node:crypto`。`shared/project-graph-source-hash.ts` 是同型先例。
 *
 * ---
 *
 * ## 三件互相独立的事（spec §2.3，v1 曾把它们压成一句「fence-aware 就够了」）
 *
 * 1. **围栏识别**防的是围栏内的 `## ` 行被当成段落边界。这是真实需求，但它**只**解决
 *    这一件事。
 * 2. **受管范围由标记决定，不由标题名决定**（§2.3.2）。实测：一个完全 fence-aware 的
 *    切分器量 `## Clean Code Guidelines` 段落仍然得到 8,675 字符，因为一个 6,273 字符的
 *    孤儿 `### …` 挂在它下面；而 2,375 是 `<!-- project-indexer:cleancode:… -->`
 *    **标记块**的长度。两者从来就不是同一个量。按标题名整段免疫 ⇒ 那份手写文档永远动
 *    不了；按段落长度判超标 ⇒ 压缩 pass 会**重写掉它**。两条路上都没有一步会报错。
 * 3. **超大段落必须能按 `###` 再切**（§2.3.3）。`## Architecture` 一段 55,746 字符、
 *    占全文 27%、内含 23 个 `###`。只有 `##` 一种单位时要么放过它（目标不可达），要么
 *    把 23 条独立的踩坑记录压成一个存根（信息毁灭，比不压更糟）。
 *
 * ## 计量约定
 *
 * **单位是 `string.length`（UTF-16 code unit），不是字节，也不是中文字符数**（§2.2）。
 * 字节会把中文密集的文件夸大 3 倍；中文字符数对英文段落、代码围栏、路径清单一律记 0。
 * 两种错法都会让阈值形同虚设，而**没有任何测试会因此变红**。
 *
 * 行的字符数**含它自己的行尾**（CRLF 记 2，LF 记 1，文件末尾无行尾的那一行记 0 个行尾
 * 字符）。这条约定让「段落 = 若干整行」与「unit 的 chars 之和 === 段落 chars」在**任何**
 * 行尾风格下都逐字成立 —— 换成 `slice().length` 之后 unit 之间的连接换行会被漏计，
 * T2b 当场变红，而最省事的「修法」是把那条断言改松。
 */

import { createHash } from 'node:crypto';

// --- 阈值（spec §2.2 / §4.2）-------------------------------------------------

/** 目标线；**同时是压缩 pass 的停止条件**（§2.5.2 第 2 步）。 */
export const CLAUDE_MD_TARGET_CHARS = 40_000;

/**
 * 触发压缩的硬线。target 到 hard 之间是「观察带」，只报数不动手。
 *
 * ⚠️ 它是**触发线**，不是**达标承诺**（§6.3）。本仓 Tier A 自己就有约 49 K 字符，
 * 压到 `≤ 60,000` 在不动 Tier A 的前提下不可达 —— 而「为了达标去削 Tier A」正是
 * §2.5.2 第 8 步明令禁止的事。
 */
export const CLAUDE_MD_HARD_CHARS = 60_000;

/** 单个 unit 压缩后的硬上限；同时是「短到不值得压」的免疫线（Tier A 第 1 条）。 */
export const CLAUDE_MD_SECTION_SOFT_CHARS = 2_500;

/** `##` 段落超过它即按 `###` 切成子单元（§2.3.3）。 */
export const CLAUDE_MD_SECTION_SPLIT_CHARS = 12_000;

/**
 * 单轮最多压缩的 unit 数（§2.5.2 第 2 步）。
 *
 * 压缩是有损的语义操作，单轮 12 个已经是人工复核 diff 的上限；收敛靠多轮 —— 这依赖
 * 「已带 compact 标记的 unit 绝不二次压缩」才成立，两条是一对。
 */
export const CLAUDE_MD_MAX_SECTIONS_PER_RUN = 12;

/** **构建路径**（每次构建一次）的读取上限。超过即 `truncated` + `tier: 'unknown'`。 */
export const CLAUDE_MD_MEASURE_MAX_BYTES = 4 * 1024 * 1024;

/**
 * **overview 路径**的读取上限，比构建路径小一个数量级（§2.7）。
 *
 * 那条路径是 memo TTL 3 秒 / 最多 300 个项目，与「每次构建一次」不是同一种预算：
 * 照抄 4 MB 的最坏情形是每 3 秒读 1.2 GB。
 */
export const CLAUDE_MD_OVERVIEW_MAX_BYTES = 512 * 1024;

/**
 * slug 白名单。落空一律回退 `section-<sha256(heading) 前 8 位>`。
 *
 * 标题是文件里的**任意文本**，而 slug 会成为**文件名**。不做白名单 ⇒ `## src/foo`
 * 之类的标题写出一个跨目录的路径。与 `shared/run-log-slug.ts` 同源的纪律。
 */
export const CLAUDE_MD_SLUG_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

// --- 形状（spec §4.2）--------------------------------------------------------

export type ClaudeMdTier = 'lean' | 'watch' | 'over' | 'unknown';

/** `null` = 不受管（普通叙事）。`'compacted'` 对应 `project-indexer:compact` 标记。 */
export type ClaudeMdManagedKind = 'project-index' | 'cleancode' | 'compacted' | null;

/** 落在某个段落内的一段受管标记范围（行号闭区间，1-based）。 */
export interface ClaudeMdManagedRange {
  kind: Exclude<ClaudeMdManagedKind, null>;
  start: number;
  end: number;
}

/** 一个 `## ` 段落（含其下全部 `###`）。 */
export interface ClaudeMdSection {
  /** 逐字原文，含 `'## '`。 */
  heading: string;
  /** 1-based，指向 `'## '` 行本身。 */
  startLine: number;
  /** 1-based，闭区间。 */
  endLine: number;
  chars: number;
  /**
   * 本段内的受管标记范围。**受管 = 标记，不是标题名**（§2.3.2 / 评审 P0-3）。
   * Tier A 的免疫对象是这里的范围，不是恰好同名的那个段落。
   */
  managedRanges: ClaudeMdManagedRange[];
  /** `chars` 减去 `managedRanges` 覆盖的部分。 */
  unmanagedChars: number;
}

/**
 * 分层与压缩的**实际操作对象**（§2.3.3 / 评审 P0-2）。
 *
 * 段落 ≤ `CLAUDE_MD_SECTION_SPLIT_CHARS` ⇒ 一段一个 unit；
 * 超过 ⇒ 前言 unit + 每个 `###` 一个 unit。
 */
export interface ClaudeMdUnit {
  /** 逐字原文，含 `'## '` 或 `'### '`。 */
  heading: string;
  level: 2 | 3;
  /** notes 文件名；恒满足 `CLAUDE_MD_SLUG_RE`。 */
  slug: string;
  startLine: number;
  endLine: number;
  chars: number;
  /**
   * true = `##` 标题行到第一个 `###` 之间的导航前言，**恒 Tier A**。
   * 那是这一章的导航句，删了读者进不去。
   */
  isPreamble: boolean;
  managed: ClaudeMdManagedKind;
}

export interface ClaudeMdMeasurement {
  exists: boolean;
  chars: number;
  bytes: number;
  lines: number;
  tier: ClaudeMdTier;
  sections: ClaudeMdSection[];
  units: ClaudeMdUnit[];
  /** true = 文件超过读取上限，`sections` / `units` 为空且 `tier` 为 `'unknown'`。 */
  truncated: boolean;
}

/**
 * overview / 渲染端消费的窄形状（spec §4.1）。
 *
 * **具名类型而非内联匿名对象**（评审 P2-2）：同一个形状会被 overview 与将来的详情面板
 * 共用，内联两份迟早漂移。
 */
export interface ClaudeMdFileInfo {
  chars: number;
  bytes: number;
  tier: ClaudeMdTier;
  /** true = 超过读取上限，`tier` 恒为 `'unknown'`。UI 出「无法读取」而非「未超标」。 */
  truncated: boolean;
}

// --- 单趟扫描（围栏 / front matter / 标题 / 标记）------------------------------

const FENCE_RE = /^ {0,3}(`{3,}|~{3,})/;
const FENCE_CLOSE_RE = /^ {0,3}(`{3,}|~{3,})[ \t]*$/;
/** 标题正则锚定行首（不允许前导空白），因此 4 空格缩进的代码块天然不会被误判。 */
const H2_RE = /^## (.*)$/;
const H3_RE = /^### (.*)$/;
const PROJECT_INDEX_H2_RE = /^##\s+Project Index\s*$/;
const MARKER_BEGIN_RE = /^<!--\s*project-indexer:(cleancode|compact):begin\b[^>]*-->\s*$/;
const MARKER_END_RE = /^<!--\s*project-indexer:(cleancode|compact):end\s*-->\s*$/;

interface ScannedDoc {
  /** 逐行原文，**不含**行尾。 */
  lines: string[];
  /** 每行的字符数，**含它自己的行尾**（见文件头「计量约定」）。 */
  lineChars: number[];
  /** true = 该行处于围栏内或 YAML front matter 内，一律不是标题、不是标记。 */
  inert: boolean[];
  /** 常规行数（末尾换行不额外计一行）。 */
  lineCount: number;
}

/**
 * 单趟扫描的一格缓存。
 *
 * `splitClaudeMdSections` / `expandClaudeMdUnits` / `measureClaudeMd` 三个入口共用
 * **同一趟**扫描（§2.3.3：「子单元的围栏状态继承自同一趟扫描，不重新扫」）。重扫一次
 * 就多一处会漂移的判据 —— 而两处判据迟早会对同一个围栏说不一致的话。
 */
let scanCache: { text: string; doc: ScannedDoc } | null = null;

function scanDocument(text: string): ScannedDoc {
  if (scanCache && scanCache.text === text) return scanCache.doc;

  const lines: string[] = [];
  const lineChars: number[] = [];
  let i = 0;
  for (;;) {
    const nl = text.indexOf('\n', i);
    if (nl < 0) {
      // 末行无换行符：字符数就是剩余长度（可能为 0，即文件以 '\n' 结尾）。
      lines.push(stripCr(text.slice(i)));
      lineChars.push(text.length - i);
      break;
    }
    lines.push(stripCr(text.slice(i, nl)));
    lineChars.push(nl - i + 1); // 含 '\n'；CRLF 时 '\r' 也在这段里，故恒守恒
    i = nl + 1;
  }

  // 末尾换行制造的空行不计入行数（与 `wc -l` 的直觉一致）。
  const lineCount = lines.length > 1 && lines[lines.length - 1] === '' && lineChars[lineChars.length - 1] === 0
    ? lines.length - 1
    : text.length === 0
      ? 0
      : lines.length;

  const inert = new Array<boolean>(lines.length).fill(false);

  // 1. YAML front matter：文件以 '---' 开头时跳到下一个 '---'（含两端）。
  let cursor = 0;
  if (lines.length > 0 && lines[0].trim() === '---') {
    inert[0] = true;
    cursor = 1;
    while (cursor < lines.length) {
      inert[cursor] = true;
      if (lines[cursor].trim() === '---') { cursor += 1; break; }
      cursor += 1;
    }
  }

  // 2. 围栏。开围栏记录 marker 字符与连续长度；只有**同字符、长度 ≥ 开围栏**且该行
  //    只有 marker（无 info string）的行才闭合它。围栏内的行一律 inert。
  let fence: { char: string; len: number } | null = null;
  for (let n = cursor; n < lines.length; n += 1) {
    const line = lines[n];
    if (fence) {
      inert[n] = true;
      const close = FENCE_CLOSE_RE.exec(line);
      if (close && close[1][0] === fence.char && close[1].length >= fence.len) fence = null;
      continue;
    }
    const open = FENCE_RE.exec(line);
    if (open) {
      fence = { char: open[1][0], len: open[1].length };
      inert[n] = true;
    }
  }

  const doc: ScannedDoc = { lines, lineChars, inert, lineCount };
  scanCache = { text, doc };
  return doc;
}

function stripCr(line: string): string {
  return line.endsWith('\r') ? line.slice(0, -1) : line;
}

/** 行号闭区间 [start, end]（1-based）的字符数，含每行自己的行尾。 */
function rangeChars(doc: ScannedDoc, start: number, end: number): number {
  let total = 0;
  for (let n = start; n <= end; n += 1) total += doc.lineChars[n - 1] ?? 0;
  return total;
}

// --- 切段 --------------------------------------------------------------------

/**
 * 把 `CLAUDE.md` 切成 `##` 段落（fence-aware，§2.3.1）。
 *
 * 段落 = 从一个 `## ` 行到下一个 `## ` 行（或 EOF）之间的全部文本，**包含其下的所有
 * `###` 子段落**。第一个 `## ` 之前的内容（front matter、`# 标题`、导言）不属于任何
 * 段落 —— 这是刻意的：那部分从来不是压缩的对象。
 */
export function splitClaudeMdSections(text: string): ClaudeMdSection[] {
  const doc = scanDocument(text);
  const starts: number[] = [];
  for (let n = 0; n < doc.lines.length; n += 1) {
    if (doc.inert[n]) continue;
    if (H2_RE.test(doc.lines[n])) starts.push(n + 1); // 1-based
  }

  const sections: ClaudeMdSection[] = [];
  for (let k = 0; k < starts.length; k += 1) {
    const startLine = starts[k];
    const endLine = k + 1 < starts.length ? starts[k + 1] - 1 : doc.lines.length;
    const heading = doc.lines[startLine - 1];
    const chars = rangeChars(doc, startLine, endLine);
    const managedRanges = collectManagedRanges(doc, startLine, endLine, heading);
    let managedChars = 0;
    for (const r of managedRanges) managedChars += rangeChars(doc, r.start, r.end);
    sections.push({
      heading,
      startLine,
      endLine,
      chars,
      managedRanges,
      unmanagedChars: Math.max(0, chars - managedChars),
    });
  }
  return sections;
}

/**
 * 本段内的受管标记范围（§2.3.2）。
 *
 * 三个来源：`## Project Index` 段落体（整段）、`project-indexer:cleancode` 标记块、
 * `project-indexer:compact` 标记块。围栏内的标记不算 —— SKILL.md 一类的文档会在代码块
 * 里展示这些标记，把它们当成真标记会让一段文档凭空获得免疫。
 *
 * 只有 begin、没有 end 的块延伸到段末（保守方向）：一个写了一半的 compact 块若被判为
 * 不受管，下一轮就会被**二次压缩**。
 */
function collectManagedRanges(
  doc: ScannedDoc,
  startLine: number,
  endLine: number,
  heading: string,
): ClaudeMdManagedRange[] {
  if (PROJECT_INDEX_H2_RE.test(heading)) {
    return [{ kind: 'project-index', start: startLine, end: endLine }];
  }
  const ranges: ClaudeMdManagedRange[] = [];
  let open: { kind: Exclude<ClaudeMdManagedKind, null>; start: number } | null = null;
  for (let n = startLine; n <= endLine; n += 1) {
    if (doc.inert[n - 1]) continue;
    const line = doc.lines[n - 1];
    if (!open) {
      const begin = MARKER_BEGIN_RE.exec(line);
      if (begin) open = { kind: begin[1] === 'cleancode' ? 'cleancode' : 'compacted', start: n };
      continue;
    }
    if (MARKER_END_RE.test(line)) {
      ranges.push({ kind: open.kind, start: open.start, end: n });
      open = null;
    }
  }
  if (open) ranges.push({ kind: open.kind, start: open.start, end: endLine });
  return ranges;
}

// --- unit 展开 ---------------------------------------------------------------

/**
 * 把段落展开成**压缩单元**（§2.3.3 / 评审 P0-2）。
 *
 * - `chars ≤ CLAUDE_MD_SECTION_SPLIT_CHARS` ⇒ 整段一个 unit。
 * - 超过且含 `###` ⇒ 前言 unit（`isPreamble: true`，恒 Tier A）+ 每个 `###` 一个 unit。
 * - 超过但**不含** `###` ⇒ 仍然一个 unit（切不动，但作为整体是可压的）。
 *
 * `####` 及更深的层级被吸收进它所属的 `###` unit：再切下去就开始切碎句子了。
 *
 * **不变量**：unit 恰好划分段落的行区间 ⇒ `Σ unit.chars === section.chars`。
 */
export function expandClaudeMdUnits(text: string, sections: ClaudeMdSection[]): ClaudeMdUnit[] {
  const doc = scanDocument(text);
  const units: ClaudeMdUnit[] = [];

  for (const section of sections) {
    if (section.chars <= CLAUDE_MD_SECTION_SPLIT_CHARS) {
      units.push(makeUnit(doc, section, section.heading, 2, section.startLine, section.endLine, false));
      continue;
    }

    const subStarts: number[] = [];
    for (let n = section.startLine + 1; n <= section.endLine; n += 1) {
      if (doc.inert[n - 1]) continue;
      if (H3_RE.test(doc.lines[n - 1])) subStarts.push(n);
    }
    if (subStarts.length === 0) {
      units.push(makeUnit(doc, section, section.heading, 2, section.startLine, section.endLine, false));
      continue;
    }

    // 前言 unit：`## ` 标题行到第一个 `### ` 之前。恒 Tier A（§2.5.1 第 2 条）。
    units.push(makeUnit(doc, section, section.heading, 2, section.startLine, subStarts[0] - 1, true));
    for (let k = 0; k < subStarts.length; k += 1) {
      const s = subStarts[k];
      const e = k + 1 < subStarts.length ? subStarts[k + 1] - 1 : section.endLine;
      units.push(makeUnit(doc, section, doc.lines[s - 1], 3, s, e, false));
    }
  }
  return units;
}

function makeUnit(
  doc: ScannedDoc,
  section: ClaudeMdSection,
  heading: string,
  level: 2 | 3,
  startLine: number,
  endLine: number,
  isPreamble: boolean,
): ClaudeMdUnit {
  return {
    heading,
    level,
    slug: claudeMdUnitSlug(heading),
    startLine,
    endLine,
    chars: rangeChars(doc, startLine, endLine),
    isPreamble,
    managed: managedKindFor(section, startLine, endLine),
  };
}

/**
 * unit 的受管归属：只要它与任一受管范围**有交集**即视为受管。
 *
 * 判据是交集而非包含：一个 unit 里混着受管标记块与手写正文时，压缩它就会连标记一起
 * 重写掉，而下一轮 upsert 找不到标记会再插一份 —— 静默的重复块。
 */
function managedKindFor(section: ClaudeMdSection, startLine: number, endLine: number): ClaudeMdManagedKind {
  for (const r of section.managedRanges) {
    if (r.start <= endLine && r.end >= startLine) return r.kind;
  }
  return null;
}

// --- 测量与分档 --------------------------------------------------------------

/** 三档阶梯（§2.4）。`unknown` 只由读取失败 / 超限的调用方产出。 */
export function classifyClaudeMd(chars: number): ClaudeMdTier {
  if (chars <= CLAUDE_MD_TARGET_CHARS) return 'lean';
  if (chars <= CLAUDE_MD_HARD_CHARS) return 'watch';
  return 'over';
}

/**
 * 构建路径的完整测量（切段 + unit 展开）。
 *
 * 调用方保证 `text` 是**完整**内容 —— 超过读取上限时不要读，直接构造
 * `truncated: true` / `tier: 'unknown'` 的结果。
 */
export function measureClaudeMd(text: string, bytes: number): ClaudeMdMeasurement {
  const doc = scanDocument(text);
  const sections = splitClaudeMdSections(text);
  return {
    exists: true,
    chars: text.length,
    bytes,
    lines: doc.lineCount,
    tier: classifyClaudeMd(text.length),
    sections,
    units: expandClaudeMdUnits(text, sections),
    truncated: false,
  };
}

/**
 * overview 专用：只算 `chars` / `bytes` / `tier`，**不切段**（§2.7 / 评审 P1-2）。
 *
 * 那条路径 memo TTL 3 秒、最多 300 个项目，而面板要显示的只是一枚 chip。
 */
export function measureClaudeMdShallow(text: string, bytes: number): ClaudeMdFileInfo {
  return { chars: text.length, bytes, tier: classifyClaudeMd(text.length), truncated: false };
}

// --- slug --------------------------------------------------------------------

/** 只在标题「本身就长得像 slug」时才尝试 kebab 化 —— 见 `claudeMdUnitSlug` 的注释。 */
const KEBAB_SAFE_TITLE_RE = /^[A-Za-z0-9][A-Za-z0-9 _.-]*$/;
/** 末尾成对括号（半角或全角）内的内容。 */
const TRAILING_PARENS_RE = /[（(]\s*([^（()）]+?)\s*[)）]\s*$/;

/**
 * unit → notes 文件名（§4.2）。
 *
 * 1. 末尾成对括号内的内容 —— 本仓惯例是 `## 通知中心（notification-center）`，
 *    括号里就是现成的 kebab slug。
 * 2. 否则，标题**本身就长得像 slug** 时 kebab 化（`## Architecture` → `architecture`）。
 * 3. 再落空则 `section-<sha256(标题) 的前 8 位十六进制>`。
 *
 * ⚠️ **第 2 步的门槛必须收在 `KEBAB_SAFE_TITLE_RE` 上，不能「kebab 完再验白名单」。**
 * 朴素的 kebab 会把 `## a/../b` 折成 `a-b` —— 它满足 `CLAUDE_MD_SLUG_RE`，于是一个
 * 明显是路径的标题被静默接受成 slug。收在门槛上则它落到第 3 步，得到一个与内容绑定
 * 的哈希名。同理 `## 项目架构图 · 模块与 UML 可视化` 只剩 `uml`，与任何别的含 UML 的
 * 标题相撞 —— 非 ASCII 标题一律走哈希。
 *
 * ⚠️ **回退值绝不能是段落序号**（评审 P1-4）。序号会随「上面增删一个段落」整体位移，
 * 下一轮 `section-07` 对应**另一个** unit ⇒ `.claude-index/notes/section-07.md` 被
 * **静默覆盖**、原文永久消失，而写入本身是「成功」的（「先写 notes 再改 CLAUDE.md」
 * 的顺序拦不住它）。内容派生的哈希与位置无关：重命名标题只会让旧 notes 变成孤儿 ——
 * 可发现、可清理，比静默覆盖好得多。
 */
export function claudeMdUnitSlug(heading: string): string {
  const raw = heading.trim();
  const title = raw.replace(/^#{1,6}\s*/, '').trim();

  const paren = TRAILING_PARENS_RE.exec(title);
  if (paren) {
    const candidate = paren[1].trim().toLowerCase();
    if (CLAUDE_MD_SLUG_RE.test(candidate)) return candidate;
  }

  if (KEBAB_SAFE_TITLE_RE.test(title)) {
    const kebab = title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 64)
      .replace(/-+$/g, '');
    if (CLAUDE_MD_SLUG_RE.test(kebab)) return kebab;
  }

  return `section-${createHash('sha256').update(raw, 'utf8').digest('hex').slice(0, 8)}`;
}
