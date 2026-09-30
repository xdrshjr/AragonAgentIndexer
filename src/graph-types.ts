/**
 * project-architecture-graph · schema v1 的**唯一真相源**（spec §6.1 / §6.2）。
 *
 * 这份文件同时被三方引用：
 *   1. Agent 产出的 `.claude-index/graph.json`（由 `index-graph-tools.py` 写出）；
 *   2. 服务端 `ProjectGraphService` 的归一化与 REST 响应构造；
 *   3. 渲染端 `graph-view-model.ts` 的视图推导。
 *
 * ⚠️ `GRAPH_LIMITS` 是服务端与渲染端**共用的一份**上限（D16）。双份魔数漂移在这类
 * 特性里是最常见的静默缺陷：服务端按 6000 截断、渲染端按 5000 渲染，用户看到
 * 「已省略 0 个」却真的少了 1000 个节点。一份常量，两端引用。
 */

/**
 * schema v2（project-architecture-graph-hardening §6.1）。归一化接受 `[1, 2]`：
 * 第一轮产出的 v1 图零改动照常渲染，只是不显示溯源徽章。
 *
 * ⚠️ `server/assets/index-graph-tools.py::SCHEMA_VERSION` 必须与这个数字**同步**
 * （§8 不变量 16）。`cmd_finalize` 里的 `draft["schemaVersion"] = SCHEMA_VERSION`
 * 会给每一张产物盖戳，两边不同步的表现是「v2 的图被盖上 v1 的戳」。
 */
export const PROJECT_GRAPH_SCHEMA_VERSION = 2;

export type GraphLayer =
  | 'frontend' | 'backend' | 'shared' | 'desktop' | 'mobile'
  | 'infra' | 'test' | 'docs' | 'other';

export const GRAPH_LAYERS: readonly GraphLayer[] = [
  'frontend', 'backend', 'shared', 'desktop', 'mobile',
  'infra', 'test', 'docs', 'other',
] as const;

export type ModuleKind = 'package' | 'feature' | 'layer' | 'service' | 'library' | 'app';

export const MODULE_KINDS: readonly ModuleKind[] = [
  'package', 'feature', 'layer', 'service', 'library', 'app',
] as const;

export type ComponentKind =
  | 'class' | 'interface' | 'enum' | 'struct' | 'function'
  | 'react_component' | 'hook' | 'store' | 'service'
  | 'table' | 'endpoint' | 'type_alias' | 'module';

export const COMPONENT_KINDS: readonly ComponentKind[] = [
  'class', 'interface', 'enum', 'struct', 'function',
  'react_component', 'hook', 'store', 'service',
  'table', 'endpoint', 'type_alias', 'module',
] as const;

export type RelationKind =
  | 'extends' | 'implements' | 'composition' | 'aggregation' | 'association'
  | 'depends' | 'uses' | 'calls' | 'emits' | 'reads' | 'writes' | 'contains';

export const RELATION_KINDS: readonly RelationKind[] = [
  'extends', 'implements', 'composition', 'aggregation', 'association',
  'depends', 'uses', 'calls', 'emits', 'reads', 'writes', 'contains',
] as const;

/**
 * 必须带 `evidence` 的关系类型（spec §3.3 validate 规则 / R1）。这三类最容易被模型
 * 幻觉出来（「A 继承 B」听起来永远合理），所以质量校验对它们要求行号证据。
 */
export const EVIDENCE_REQUIRED_RELATION_KINDS: readonly RelationKind[] = [
  'extends', 'implements', 'composition',
] as const;

export type Visibility = 'public' | 'protected' | 'private' | 'internal';

export const VISIBILITIES: readonly Visibility[] = [
  'public', 'protected', 'private', 'internal',
] as const;

/** id 字符集（spec §3.3 validate 规则）。 */
export const PROJECT_GRAPH_ID_PATTERN = /^[A-Za-z0-9._:-]{1,120}$/;

// --- 溯源与核验（W2, §6.1） ---------------------------------------------------

/**
 * 一条记录是**抽取**出来的还是**断言**出来的。
 *
 * - `'extracted'`：由 `scan-uml --emit-ops` 直接产出，未经模型转录。
 * - `'asserted'`：模型手写 / 手工转录。
 * - `undefined`：**未知**（第一轮的 v1 图 / Tier 2 派生图）。
 *
 * ⚠️ **归一化绝不推断**（§8 不变量 1 / D4）。「v1 图里的一切显然都是模型敲的，
 * 那就在读的时候统统标成 `asserted` 吧」是一个非常自然、且必须拒绝的想法：一旦
 * 读端开始推断，同一个文件在不同版本的应用里会渲染出不同的溯源结论，而基于推断
 * 算出来的 `verification` 统计是**编造的数字**。统计只能来自生产者。
 */
export type GraphProvenance = 'extracted' | 'asserted';

export const GRAPH_PROVENANCES: readonly GraphProvenance[] = ['extracted', 'asserted'] as const;

export type GraphVerificationCode =
  | 'FILE_MISSING' | 'LINE_OUT_OF_RANGE' | 'NAME_NOT_AT_LINE' | 'NAME_NOT_IN_FILE'
  | 'EVIDENCE_MISSING' | 'EVIDENCE_OUT_OF_RANGE' | 'EVIDENCE_MALFORMED' | 'SKIPPED_TOO_LARGE';

export const GRAPH_VERIFICATION_CODES: readonly GraphVerificationCode[] = [
  'FILE_MISSING', 'LINE_OUT_OF_RANGE', 'NAME_NOT_AT_LINE', 'NAME_NOT_IN_FILE',
  'EVIDENCE_MISSING', 'EVIDENCE_OUT_OF_RANGE', 'EVIDENCE_MALFORMED', 'SKIPPED_TOO_LARGE',
] as const;

export interface GraphVerificationFinding {
  code: GraphVerificationCode;
  entity: 'component' | 'relation';
  id: string;
  provenance?: GraphProvenance;
  /** 英文，<= 200 字符。渲染端原样显示、不做本地化（含路径与标识符）。 */
  detail: string;
  suggestedLine?: number;
}

export interface GraphVerificationCounts {
  total: number; extracted: number; asserted: number;
  checked: number; confirmed: number; repaired: number; mismatched: number;
}

export interface GraphVerification {
  /** null = 从未核验（含 `finalize --no-verify` 的产物，§8 不变量 9）。 */
  verifiedAt: number | null;
  skipped: boolean;
  toolVersion?: string;
  components: GraphVerificationCounts;
  relations: GraphVerificationCounts;
  findings: GraphVerificationFinding[];
  findingsTruncated: number;
}

// --- 架构规则（W3, §6.2） ------------------------------------------------------

export interface GraphLayerRule {
  from: GraphLayer;
  to: GraphLayer;
  effect: 'forbid' | 'allow';
  reason?: string;
}

export interface GraphRulesDocument {
  schemaVersion: number;
  layerRules: GraphLayerRule[];
  allowCycles: boolean;
  /** 模块 id 白名单：两端任一命中即跳过该边。 */
  ignore: string[];
}

export type GraphRulesStatus = 'none' | 'ok' | 'invalid';

/**
 * 上卷后的模块边。**刻意不含任何 React Flow 类型**（评审 P0-3），这样
 * `shared/project-graph-rules.ts` 才能被服务端与 node 单测直接引用 ——
 * `rollUpModuleEdges` 住在渲染端且顶部 `import type { Node, Edge } from
 * '@xyflow/react'`，把它拖进 `shared/` 要么编译期炸、要么逼出第二份上卷实现。
 */
export interface GraphModuleEdge { from: string; to: string; kind: RelationKind; }

/**
 * `edgeIds` 逐字为 `${from}|${to}|${kind}`，与画布 `toFlowEdge` 一致（评审 P1-1）。
 * 自造一个 key 不会报错：健康面板照样列得出环，`selectEdge(edgeId)` 却选不中任何
 * 东西，画布上一条边都不亮。
 */
export interface GraphCycle { moduleIds: string[]; edgeIds: string[]; }

export interface GraphRuleViolation {
  edgeId: string;
  fromModuleId: string;
  toModuleId: string;
  fromLayer: GraphLayer;
  toLayer: GraphLayer;
  reason?: string;
}

export interface ProjectGraphMember {
  name: string;
  /** 见 `GraphProvenance`。归一化**绝不推断**（§8 不变量 1）。 */
  provenance?: GraphProvenance;
  /**
   * 声明所在行（1-based）。第三轮 W4 新增，稀疏写（缺省不产生该键）。
   *
   * ⚠️ Python 侧 `build_member` 是**白名单重建**，必须显式列出 `"line"`
   * （§8 不变量 12）—— 漏一个键不会报错，只会让该字段在产物里静默消失，
   * 表现是「op 里明明带了行号，图上点方法名却总是跳到文件开头」。
   */
  line?: number;
  /** 属性类型。 */
  type?: string;
  /** 方法签名。 */
  signature?: string;
  visibility?: Visibility;
  static?: boolean;
  abstract?: boolean;
  async?: boolean;
  readonly?: boolean;
}

export interface ProjectGraphModule {
  id: string;
  name: string;
  /** 仓库相对、POSIX 分隔符、禁止 '..' 与绝对路径。 */
  path: string;
  layer: GraphLayer;
  kind: ModuleKind;
  /** 至多一层嵌套：指向的模块自身必须 `parentId == null`（§6.1）。 */
  parentId?: string | null;
  summary?: string;
  tags?: string[];
  entryPoints?: string[];
  metrics?: { files?: number; loc?: number; components?: number };
}

export interface ProjectGraphComponent {
  id: string;
  /** 见 `GraphProvenance`。归一化**绝不推断**（§8 不变量 1）。 */
  provenance?: GraphProvenance;
  /** 必须命中某个 module.id，否则归一化时整条剔除。 */
  moduleId: string;
  name: string;
  kind: ComponentKind;
  /** 渲染为 «stereotype»。 */
  stereotype?: string;
  file?: string;
  line?: number;
  visibility?: Visibility;
  abstract?: boolean;
  summary?: string;
  tags?: string[];
  attributes?: ProjectGraphMember[];
  methods?: ProjectGraphMember[];
}

export interface ProjectGraphRelation {
  /** 缺省由归一化生成 `rel.<n>`。 */
  id?: string;
  /** 见 `GraphProvenance`。归一化**绝不推断**（§8 不变量 1）。 */
  provenance?: GraphProvenance;
  from: string;
  to: string;
  kind: RelationKind;
  label?: string;
  fromCardinality?: string;
  toCardinality?: string;
  weight?: number;
  /** 形如 'path/to/file.ts:412'。 */
  evidence?: string[];
}

export interface ProjectGraphTruncation {
  modules: number;
  components: number;
  relations: number;
  members: number;
  /** 悬挂引用被剔除的条数（§8 不变量 7）。 */
  droppedRelations: number;
  note: string | null;
}

/** `graph.json` 的顶层形状（§3.2）。 */
export interface ProjectGraphDocument {
  schemaVersion: number;
  generatedAt?: number;
  generator?: { name?: string; toolVersion?: string; agentType?: string };
  project?: { name?: string; root?: string; languages?: string[]; indexVersion?: string | null };
  modules?: ProjectGraphModule[];
  components?: ProjectGraphComponent[];
  relations?: ProjectGraphRelation[];
  truncation?: Partial<ProjectGraphTruncation>;
  /** v2 起由 `verify` / `finalize` 盖进产物；v1 图缺席（§3.3.3）。 */
  verification?: GraphVerification;
  /**
   * 第三轮 W1：这张图**引用过的每一个源文件**的指纹清单。
   *
   * ⚠️ **`finalize --no-verify` 时本键缺席，不是空清单**（§8 不变量 18）。
   * 空清单会让漂移报告算出 `total: 0` 且 `status: 'clean'` —— 一张从未核验的图，
   * 顶着「引用的 0 个文件未改变」的绿✓。
   */
  sourceManifest?: GraphSourceManifest;
}

// --- W1 · 源码指纹清单（第三轮 §6.1） ------------------------------------------

/**
 * 规范化过程见 `shared/project-graph-source-hash.ts`（**字节级**：剥 BOM 字节 →
 * CRLF→LF → 孤立 CR→LF → sha256[:16]）。算法标识的真相源是那个文件里的
 * `GRAPH_SOURCE_HASH_ALGO`；这里只描述形状。
 */
export interface GraphSourceManifestEntry {
  /** 仓库相对、POSIX 分隔符、禁止 '..' 与绝对路径（归一化会剔除违规条目）。 */
  path: string;
  /** 抽取时刻磁盘上的字节数。 */
  size: number;
  /** 抽取时刻的 mtime（ms）。**只用作 stat 快路径**，不单独作为变更判据。 */
  mtime: number;
  /** LF 归一化后**字节**的 sha256 前 16 个十六进制字符（绝不经过解码）。 */
  hash: string;
}

export interface GraphSourceManifest {
  /**
   * 认不出就 `status: 'unsupported'`，**绝不当作全量漂移** —— 算不出来就说算不出来，
   * 而不是把整个仓库报成变了。
   */
  algo: string;
  builtAt: number;
  entries: GraphSourceManifestEntry[];
  /**
   * 被引用但未记入清单的文件数（No silent caps）。**两个来源都要算进来**：
   * `run_verify` 读预算耗尽 + `MANIFEST_MAX_ENTRIES` 拒绝。只算后者会让它恒为 0
   * （两个常量相等），从而让服务端 `notChecked` 恒 0 —— 一张**声称全量核对过**的
   * 部分核对报告（§8 不变量 15）。
   */
  truncated: number;
  /** 读取失败 / 超单文件上限。 */
  skipped: number;
}

// --- W1 · 漂移报告 -------------------------------------------------------------

export type GraphFileDriftState = 'unchanged' | 'changed' | 'missing' | 'uncertain';

export const GRAPH_FILE_DRIFT_STATES: readonly GraphFileDriftState[] = [
  'unchanged', 'changed', 'missing', 'uncertain',
] as const;

export type GraphDriftStatus =
  | 'clean' | 'drifted' | 'partial' | 'unavailable' | 'unsupported';

export interface GraphFileDrift { path: string; state: GraphFileDriftState; }

/**
 * ⚠️ 恒等式（G2 的可验证形式）：
 *   `total === unchanged + changed + missing + uncertain + notChecked`
 * 其中 **`total = manifest.entries.length + manifest.truncated`**、
 * **`notChecked = manifest.truncated`**。
 *
 * `manifest.skipped`（产出侧读不到 / 超单文件上限）是**产出侧的事实**，不是一种
 * 漂移状态，因此单列为信息项、**不进这五档**。
 */
export interface GraphDriftCounts {
  total: number;
  unchanged: number;
  changed: number;
  missing: number;
  /**
   * ⚠️ **预算耗尽归这一档，不归 `changed`**（§8 不变量 2）。把「没来得及看」说成
   * 「变了」，会在大仓库上把漂移横幅变成一个恒亮的、无法消除的警告，而用户对恒亮
   * 警告的唯一合理反应是从此忽略它 —— 那就把 W1 整个作废了。
   */
  uncertain: number;
  /** === `manifest.truncated`。 */
  notChecked: number;
  /** 信息项，不进恒等式：产出侧就没读到的文件数（=== `manifest.skipped`）。 */
  skippedAtBuild: number;
}

export interface GraphDriftReport {
  projectId: string;
  /**
   * ⚠️ 逐字是 `ProjectGraphResponse.fingerprint`，**不是**
   * `NormalizedProjectGraph.fingerprint`（§8 不变量 23）。仓里有两个同名字段且都是
   * `string`，类型系统帮不上忙；取错那个会让不变量 5 的校验恒失败 ⇒ 报告永远被丢弃。
   */
  graphFingerprint: string;
  status: GraphDriftStatus;
  checkedAt: number;
  /** 清单的 `builtAt`；无清单为 null。 */
  builtAt: number | null;
  counts: GraphDriftCounts;
  /** 只含非 unchanged 的条目，按 state → path 排序，封顶 `driftMaxReportedFiles`。 */
  files: GraphFileDrift[];
  filesTruncated: number;
  driftedComponentIds: string[];
  driftedModuleIds: string[];
  /** 三个哈希预算中的任意一个被打满。 */
  budgetExhausted: boolean;
}

// ⚠️ 这里**没有** `indexAgeMs`（§8 不变量 25）。「索引年龄」这第二个信号由渲染端
// 从 `ProjectGraphResponse.indexFile.mtime` + `computeIndexFreshness()` 自算 —— 否则
// 它会在 `unavailable` / `unsupported` / 请求失败这三种情形下一起消失，而那恰恰是
// 「这份索引已经 12 天没更新了」最该被看见的时候。

// --- W2 · 快照与 diff ----------------------------------------------------------

/** 快照 id 的白名单正则（§8 不变量 14）。服务端与渲染端共用一份。 */
export const GRAPH_SNAPSHOT_ID_PATTERN = /^graph-\d{10,16}$/;

export interface GraphSnapshotInfo {
  /** 文件名去扩展名，形如 `graph-1787770000000`；必须匹配 `GRAPH_SNAPSHOT_ID_PATTERN`。 */
  id: string;
  /**
   * === id 里的那个数字。产出侧优先取**产物自身的 `generatedAt`**，解析不到才退回
   * 文件 mtime（§8 不变量 26）。**这是本协议里「那一份产物生成于何时」的唯一真相源**
   * —— `GraphDiff` 刻意不再重复它。
   */
  generatedAt: number;
  bytes: number;
}

export type GraphDiffEntityKind = 'module' | 'component' | 'relation';

export interface GraphFieldChange {
  id: string;
  field: string;
  before: string | number | boolean | null;
  after: string | number | boolean | null;
}

export interface GraphMovedComponent {
  id: string;
  fromModuleId: string; toModuleId: string;
  fromFile: string | null; toFile: string | null;
}

/**
 * **提示，不是结论**（§8 不变量 8）。两端仍分别出现在 `added` / `removed` 里，
 * 且 UI 措辞必须是「可能由 X 改名而来」—— 把启发式判断呈现成事实，用户会据此
 * 下架构结论，而它错的时候没有任何提示。
 */
export interface GraphRenameHint {
  removedId: string; addedId: string;
  moduleId: string; file: string; kind: string;
}

/**
 * 渲染一个「已删除」幽灵节点所需的最小信息。
 *
 * ⚠️ **为什么 `removed: string[]` 不够**（实施期发现 IF-3）：幽灵节点按定义不在
 * 当前这张图里，渲染端手上只有一个 id。组件 id 形如 `cmp.<module>.<Name>`，从中
 * 「切最后一段当类名」是一个**会错**的启发式（模块名本身可能带点、类名可能重名），
 * 而更要命的是 `moduleId` 根本无从还原 —— 于是模块内 UML 视图无法判断某个幽灵
 * 属不属于当前模块，只能全都画上或全都不画。两种都是错的。
 *
 * 这份最小载荷由服务端（它手上有 base 快照）产出，上限 `ghostCap`。
 */
export interface GraphGhostNode {
  id: string;
  label: string;
  /** 组件才有。 */
  moduleId?: string;
  file?: string;
  kind?: string;
  /** 模块才有。 */
  layer?: GraphLayer;
}

export interface GraphDiff {
  baseId: string;
  // ⚠️ 刻意没有 baseGeneratedAt / headGeneratedAt：客户端手上已经有 `snapshots[]`
  // （含 generatedAt）与当前响应（含 generatedAt）。同一个时间概念有三个来源时，
  // 在 `historyStampSource === 'mtime'` 的降级路径上它们必然打架。
  modules:    { added: string[]; removed: string[]; changed: GraphFieldChange[] };
  components: { added: string[]; removed: string[]; changed: GraphFieldChange[];
                moved: GraphMovedComponent[] };
  relations:  { added: string[]; removed: string[] };
  members:    { added: number; removed: number; changedSignature: number };
  renameHints: GraphRenameHint[];
  truncated: Record<GraphDiffEntityKind, number>;
  /**
   * `removed` 两个数组的可渲染投影（见 `GraphGhostNode`）。`truncated` 是因
   * `ghostCap` 未下发的条数 —— **如实上报，绝不静默丢弃**。
   */
  ghosts: { modules: GraphGhostNode[]; components: GraphGhostNode[]; truncated: number };
}

/** `GET /api/projects/:id/graph/diff` 的响应体（§5.1）。 */
export interface ProjectGraphDiffResponse {
  snapshots: GraphSnapshotInfo[];
  diff: GraphDiff | null;
}

// --- W3 · 重扫 scope -----------------------------------------------------------

/**
 * ⚠️ 这个对象**逐字进提示词**，且来自客户端。服务端必须先过
 * `sanitizeRescanScope()`（§8 不变量 27）再往下传：POSIX 相对、拒 `..` / 绝对路径 /
 * 盘符、剥控制字符与反引号、单条 ≤ `scopeMaxEntryChars`、去重、两级截断。
 *
 * 它的**正常**来源是用户仓库里的 `graph.json` —— 那本来就不是可信输入。
 */
export interface GraphRescanScope {
  reason: 'drift';
  /** 已漂移的模块 id，≤ `scopeMaxModules`；超出部分只体现在 note 里。 */
  moduleIds: string[];
  /** 这些模块的仓库相对路径，≤ `scopeMaxPaths`。 */
  paths: string[];
  /** 已改变 / 已丢失的文件，≤ `scopeMaxFiles`。 */
  files: string[];
  /** 因上限未列出的文件数。 */
  omittedFiles: number;
}

// --- 上限（服务端与渲染端共用一份，D16 / §6.2） --------------------------------

export const GRAPH_LIMITS = {
  maxBytes:            12 * 1024 * 1024,
  maxIndexMdBytes:      8 * 1024 * 1024,
  maxModules:          400,
  maxComponents:      6000,
  maxRelations:      20000,
  maxMembersPerComponent: 80,
  maxTags:               8,
  maxEvidence:           5,
  maxNameChars:        200,
  maxSummaryChars:     400,
  maxSignatureChars:   300,
  maxLabelChars:       120,
  maxTypeChars:        200,
  maxTagChars:          32,
  maxEntryPoints:        8,
  maxStereotypeChars:   40,
  maxCardinalityChars:  12,
  maxPathChars:        400,
  // 渲染端
  renderCapModules:    400,
  renderCapModuleUml:  200,
  renderCapGlobalUml:  600,
  /** module_uml 视图里的跨模块「边界代理节点」上限（R2-P2-4）。 */
  renderCapProxyNodes:  40,
  /** 详情面板里列出上卷来源关系的条数上限。 */
  maxRolledUpSources:   20,
  // 第二轮（W2 / W3 / W4）——Python 侧的对应常量必须与这些数字逐个一致（§6.3）。
  maxVerificationFindings:   50,
  maxFindingDetailChars:    200,
  maxRulesBytes:      256 * 1024,
  maxLayerRules:             60,
  maxNeighborhoodDepth:       4,
  svgMaxNodes:             1200,
  // 服务端缓存
  cacheEntries:          2,
  cacheMaxNormalizedBytes: 4 * 1024 * 1024,
  cacheTtlMs:      5 * 60 * 1000,

  // --- 第三轮（W1..W4，§6.3）------------------------------------------------
  // ⚠️ **三份常量必须成组修改**（§8 不变量 15）：这里、`index-graph-tools.py` 的
  // 同名常量、以及渲染端的引用点。不一致的表现是 `truncated` 报 0 而清单里确实
  // 少了条目 —— 漂移报告的 `notChecked` 恒为 0，「未核对」这一档永远不出现，
  // 用户看到的是一张**声称全量核对过**的部分核对报告。

  /**
   * ⚠️ 必须**恒等于** Python 侧的 `VERIFY_MAX_FILES`（1500），这不是一个可以独立
   * 取值的数：清单是 `run_verify` 的副产品，而 `run_verify` 的读预算就是它，预算
   * 耗尽时组件循环直接 `break`。写一个更大的数 ⇒ 那条分支永远不触发、`truncated`
   * 恒 0，而清单里确实少了条目。
   */
  maxManifestEntries: 1500,
  /** Python 侧 `MEMBER_LOOKUP_BUDGET`（§8 不变量 28）。 */
  memberLookupBudget: 2000,
  /** Python 侧 `HISTORY_KEEP`。 */
  historyKeep: 5,
  /** Python 侧 `HISTORY_MAX_BYTES`。 */
  historyMaxBytes: 24 * 1024 * 1024,

  // 漂移探测（仅服务端）
  driftMaxHashFiles: 1200,
  driftMaxHashBytes: 48 * 1024 * 1024,
  driftMaxMs: 2500,
  /** 服务级 `(path,size,mtime)→hash` 有界 LRU 的容量（§8 不变量 22）。 */
  driftHashMemoEntries: 4000,
  /** 哈希并发度：机械硬盘 / 网络盘上把事件循环打满是真实风险。 */
  driftHashConcurrency: 8,
  /** 指纹失配的连续重发上限（§8 不变量 24）。 */
  driftMaxRetries: 2,
  driftMaxReportedFiles: 200,
  driftCacheTtlMs: 20 * 1000,

  // diff / 叠加层
  diffMaxEntries: 400,
  /** 叠加态注入的幽灵（已删除）节点上限。 */
  ghostCap: 100,

  // 重扫 scope 净化（§8 不变量 27）
  scopeMaxEntryChars: 120,
  scopeMaxModules: 12,
  scopeMaxPaths: 12,
  scopeMaxFiles: 40,
  /** `buildRescanScopeBlock` 的整块字符上限。 */
  scopeBlockMaxChars: 900,

  /** 「复制为上下文」的字符上限。 */
  contextCopyMaxChars: 4000,
} as const;

// --- 归一化后的内存形状（§6.3） ----------------------------------------------

/**
 * `relations` 的类型是**元素的交叉**（`(A & Required<Pick<A,…>>)[]`）而不是**数组的
 * 交叉**（`A[] & B[]`，R2-P2-3）—— 后者能编译但语义不是想要的，读起来也会误导。
 */
export type NormalizedRelation =
  ProjectGraphRelation & Required<Pick<ProjectGraphRelation, 'id' | 'weight'>>;

export interface NormalizedProjectGraph {
  fingerprint: string;
  /** 已排序：layer → path。 */
  modules: ProjectGraphModule[];
  /** 已排序：moduleId → name。 */
  components: ProjectGraphComponent[];
  relations: NormalizedRelation[];
  /** 渲染端建，**不过网**（Map 不可 JSON 序列化，R2-P2-3）。 */
  moduleIndex: Map<string, ProjectGraphModule>;
  componentIndex: Map<string, ProjectGraphComponent>;
  truncation: ProjectGraphTruncation;
}

// --- REST 契约（§5.1） --------------------------------------------------------

export type ProjectGraphSource = 'graph_json' | 'index_md' | 'none';

export type ProjectGraphNoticeCode =
  /** graph.json 存在但不是合法 JSON。 */
  | 'GRAPH_PARSE_FAILED'
  /** schemaVersion 大于本端认识的版本。 */
  | 'GRAPH_SCHEMA_UNSUPPORTED'
  /** graph.json 超过 12 MB —— **降级，不是错误**（R2-P1-3 / D18）。 */
  | 'GRAPH_TOO_LARGE'
  /** 没有 graph.json，走 index.md 派生。 */
  | 'GRAPH_MISSING'
  /** 连 index.md 都没有。 */
  | 'INDEX_MISSING'
  /** index.md 在，但超过派生上限，连派生视图都给不出（与 INDEX_MISSING 是两件事）。 */
  | 'INDEX_TOO_LARGE'
  /** 派生成功但 Module Dependencies 非规范格式（D12）。 */
  | 'DEPS_SECTION_UNPARSEABLE';

export interface ProjectGraphFileInfo {
  exists: boolean;
  relPath: string;
  mtime: number | null;
  bytes?: number | null;
}

export interface ProjectGraphResponse {
  projectId: string;
  source: ProjectGraphSource;
  /** `source !== 'graph_json'`。 */
  degraded: boolean;
  /** 降级原因的英文兜底文案；渲染端按 `noticeCode` 映射本地化文案。 */
  notice: string | null;
  noticeCode: ProjectGraphNoticeCode | null;
  /**
   * `${source}:${noticeCode ?? '-'}:${mtimeMs}-${size}-${m}.${c}.${r}`；布局 memo 与
   * ETag 都用它。`source` / `noticeCode` 进指纹不是装饰（IF-3）：删掉一个超大的
   * `graph.json` 之后，Tier 2 的 mtime / size / counts 与删除前**逐字相同**，只有
   * `noticeCode` 从 `GRAPH_TOO_LARGE` 变成 `GRAPH_MISSING` —— 不带它们客户端会拿到
   * 304，横幅永远停在「架构图过大」，而那个文件已经不在了。
   */
  fingerprint: string;
  /** 产物自报的生成时刻；派生路径取 index.md 的 mtime。 */
  generatedAt: number | null;
  indexFile: ProjectGraphFileInfo;
  graphFile: ProjectGraphFileInfo;
  project: { name: string; languages: string[]; indexVersion: string | null };
  modules: ProjectGraphModule[];
  components: ProjectGraphComponent[];
  relations: NormalizedRelation[];
  truncation: ProjectGraphTruncation;
  /** Tier 1 且产物里有才非空；v1 图与派生视图恒 null（§3.3.1）。 */
  verification: GraphVerification | null;
  rules: GraphRulesDocument | null;
  rulesStatus: GraphRulesStatus;
  /**
   * 评审 P0-4：`source === 'graph_json' && rulesStatus === 'ok'` 才为 true。
   * 派生视图下恒 false —— 渲染端据此隐藏分层违规段，**不自己推断**（推断 = 第二处
   * 判据 = 迟早与服务端说不一致，到那时健康面板会在一张猜出来的图上把边标红）。
   */
  rulesApplied: boolean;
  rulesFile: ProjectGraphFileInfo;
}

/** REST 的三个错误码（§5.1）—— 没有 413，也没有 422。 */
export type ProjectGraphErrorCode = 'PROJECT_NOT_FOUND' | 'WORKSPACE_NOT_BOUND' | 'INTERNAL';

/**
 * `/graph/diff` 额外的两个错误码（第三轮 §5.1）。服务端只下发**稳定机器 code +
 * 英文 fallback**，中文由渲染端 `resolveErrorMessage(code, fallback)` 提供。
 */
export type ProjectGraphDiffErrorCode =
  | ProjectGraphErrorCode | 'SNAPSHOT_ID_INVALID' | 'SNAPSHOT_NOT_FOUND';

/** 快照目录（本机产物，自忽略；§6.2 / D7）。 */
export const PROJECT_GRAPH_HISTORY_REL_DIR = '.claude-index/graph-history';

export const PROJECT_GRAPH_REL_PATH = '.claude-index/graph.json';
export const PROJECT_INDEX_REL_PATH = '.claude-index/index.md';
/** 可选的架构规则文件（W3 / §6.2）。不存在 ⇒ `rulesStatus: 'none'`，不是错误。 */
export const PROJECT_GRAPH_RULES_REL_PATH = '.claude-index/graph-rules.json';

/** 空的核验计数（渲染端做差量与兜底时共用一份字面量）。 */
export function emptyVerificationCounts(): GraphVerificationCounts {
  return { total: 0, extracted: 0, asserted: 0, checked: 0, confirmed: 0, repaired: 0, mismatched: 0 };
}

/** 空的 truncation（两端共用，避免各写各的字面量）。 */
export function emptyTruncation(): ProjectGraphTruncation {
  return { modules: 0, components: 0, relations: 0, members: 0, droppedRelations: 0, note: null };
}

/** 空的漂移计数（服务端与渲染端共用一份字面量，避免各写各的）。 */
export function emptyDriftCounts(): GraphDriftCounts {
  return {
    total: 0, unchanged: 0, changed: 0, missing: 0,
    uncertain: 0, notChecked: 0, skippedAtBuild: 0,
  };
}

/** 空的 diff（渲染端在 `diffStatus !== 'ready'` 时的兜底形状）。 */
export function emptyGraphDiff(baseId: string): GraphDiff {
  return {
    baseId,
    modules: { added: [], removed: [], changed: [] },
    components: { added: [], removed: [], changed: [], moved: [] },
    relations: { added: [], removed: [] },
    members: { added: 0, removed: 0, changedSignature: 0 },
    renameHints: [],
    truncated: { module: 0, component: 0, relation: 0 },
    ghosts: { modules: [], components: [], truncated: 0 },
  };
}
