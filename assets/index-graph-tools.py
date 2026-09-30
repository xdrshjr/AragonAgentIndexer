#!/usr/bin/env python3
"""
Index Graph Tools - local CLI for authoring `.claude-index/graph.json`.

Standard library only. ZERO network calls, ZERO environment variables, ZERO
third-party imports. Every command prints exactly one line of JSON on stdout.

Exit codes: 0 = success, 1 = business failure, 2 = usage error.

==================================================================
Command quick reference
==================================================================

-- Discovery (deterministic, read-only; feed facts to the model) --

  python .agentmesh/.index-graph-tools.py scan-modules --max-depth 3 --min-files 3 --out .agentmesh/index-graph/mods.json
  python .agentmesh/.index-graph-tools.py scan-imports --path src --lang ts --out .agentmesh/index-graph/imports.json
  python .agentmesh/.index-graph-tools.py scan-symbols --path server/services --kinds class,interface --out .agentmesh/index-graph/symbols.json
  python .agentmesh/.index-graph-tools.py scan-uml --path server/services --module mod.srv --emit-ops --out .agentmesh/index-graph/ops-srv.ndjson

  `scan-uml` is the structural extractor: it masks strings/comments/regexes,
  matches braces, and reads real class bodies, members and heritage clauses off
  disk (`ast` for Python). With `--emit-ops` its output IS the NDJSON batch, so
  nothing has to be transcribed by hand. Every record it writes carries
  `"provenance":"extracted"`.

  Every discovery command accepts `--out <path>` and writes its own file.
  NEVER use shell redirection: the host may forward commands to cmd.exe,
  PowerShell 5.1 or bash, and `>` / heredocs / `&&` are not portable across
  all three. Omit `--out` only when you want the JSON on stdout for debugging.

-- Authoring (idempotent upserts against a DRAFT file) --

  python .agentmesh/.index-graph-tools.py init --project-name "MyProject"
  python .agentmesh/.index-graph-tools.py add-module --id mod.server --name "Server" --path server --layer backend
  python .agentmesh/.index-graph-tools.py add-component --id cmp.Foo --module mod.server --name Foo --kind class --file server/foo.ts --line 12
  python .agentmesh/.index-graph-tools.py add-member --component cmp.Foo --member-kind method --name run --signature "(): void"
  python .agentmesh/.index-graph-tools.py add-relation --from cmp.Foo --to cmp.Bar --kind composition --evidence server/foo.ts:31
  python .agentmesh/.index-graph-tools.py apply --file .agentmesh/index-graph/ops.ndjson
  python .agentmesh/.index-graph-tools.py remove --id cmp.Foo --kind component
  python .agentmesh/.index-graph-tools.py list --kind modules --limit 50
  python .agentmesh/.index-graph-tools.py stats

-- Sealing --

  python .agentmesh/.index-graph-tools.py verify --fix-lines
  python .agentmesh/.index-graph-tools.py validate
  python .agentmesh/.index-graph-tools.py finalize

`verify` re-opens every `file:line` and every `evidence` entry in the draft and
checks it against the bytes on disk. It is a REPORT: it always exits 0. The
gate lives in `finalize`, which runs a verification pass of its own and refuses
to publish when a record that claims `"provenance":"extracted"` fails it -
that combination means the extractor itself lied, which is a tool bug. A failing
`"asserted"` record is published and labelled instead: a partly correct graph
that says which parts are uncertain beats no graph at all.

`apply` is the main authoring path. Write one JSON object per line into an
NDJSON file with your own file-writing tool, then run `apply --file <path>`.
The op key equals the long option name without `--`, converted to lowerCamel
(`--member-kind` -> `memberKind`, `--from-card` -> `fromCard`).

  {"op":"add-module","id":"mod.server","name":"Server","path":"server","layer":"backend","kind":"package","summary":"...","files":96,"loc":41230}
  {"op":"add-component","id":"cmp.Foo","module":"mod.server","name":"Foo","kind":"class","stereotype":"service","file":"server/foo.ts","line":12,"summary":"..."}
  {"op":"add-member","component":"cmp.Foo","memberKind":"method","name":"run","signature":"(): Promise<void>","visibility":"public","async":true}
  {"op":"add-relation","from":"cmp.Foo","to":"cmp.Bar","kind":"composition","label":"owns","evidence":["server/foo.ts:31"]}
  {"op":"remove","id":"cmp.Foo","kind":"component"}

Authoring writes a DRAFT at `.agentmesh/index-graph/draft.json`. Only
`finalize` publishes `.claude-index/graph.json`, and it does so atomically
(write temp file, then os.replace). A reader therefore never sees half a
graph: it sees the previous complete graph, or nothing at all.

`init` without `--force` keeps whatever is already in the draft, so an
interrupted run can simply resume instead of starting over.
"""

import argparse
import ast
import bisect
import hashlib
import json
import os
import re
import sys
import tempfile

TOOL_VERSION = "2.1.0"
# Must stay in lock-step with shared/project-graph-types.ts::
# PROJECT_GRAPH_SCHEMA_VERSION. `cmd_finalize` stamps every artifact with this
# number, so a mismatch publishes a v2 graph wearing a v1 label.
SCHEMA_VERSION = 2

DRAFT_DIR = os.path.join(".agentmesh", "index-graph")
DRAFT_PATH = os.path.join(DRAFT_DIR, "draft.json")
DEFAULT_OUT = os.path.join(".claude-index", "graph.json")
CONFIG_PATH = os.path.join(".claude-index", "config.md")

# Caps mirror shared/project-graph-types.ts::GRAPH_LIMITS. The server re-applies
# them on read, so exceeding one here is never fatal - it is just work thrown away.
MAX_MODULES = 400
MAX_COMPONENTS = 6000
MAX_RELATIONS = 20000
MAX_MEMBERS = 80
MAX_TAGS = 8
MAX_EVIDENCE = 5
MAX_NAME = 200
MAX_SUMMARY = 400
MAX_SIGNATURE = 300
MAX_LABEL = 120
MAX_TYPE = 200

# Structural extraction / verification budgets. These mirror GRAPH_LIMITS too;
# `index-graph-tools-uml.test.ts` asserts the numbers on both sides match.
UML_MAX_CONTAINERS = 40
UML_MAX_MEMBERS = 80            # == GRAPH_LIMITS.maxMembersPerComponent
SCAN_MAX_FILE_BYTES = 1536 * 1024
VERIFY_MAX_FILES = 1500
VERIFY_MAX_FILE_BYTES = 2 * 1024 * 1024
VERIFY_CACHE_FILES = 64
MAX_FINDINGS = 50               # == GRAPH_LIMITS.maxVerificationFindings
MAX_FINDING_DETAIL = 200        # == GRAPH_LIMITS.maxFindingDetailChars

# --- Round 3 (liveness): source manifest, history rotation, member lines ---
#
# These mirror GRAPH_LIMITS too. They MUST be changed as a group with
# shared/project-graph-types.ts (invariant 15): a mismatch makes `truncated`
# report 0 while the manifest really is short, so the server's `notChecked`
# bucket stays empty forever and the user reads a partial check as a full one.

# Identifies the content-hash normalisation. Changing the ALGORITHM must change
# this STRING; never redefine the semantics in place. The server stops comparing
# when it does not recognise the id (`unsupported`), whereas a silent semantic
# change reports the whole repository as changed with nothing anywhere naming
# the real reason.
SOURCE_HASH_ALGO = "sha256-lf16"

# NOT an independently choosable number. The manifest is a by-product of
# `run_verify`, whose read budget is VERIFY_MAX_FILES and which `break`s out of
# the component loop once that budget is spent - so the manifest can never hold
# more than VERIFY_MAX_FILES entries. Writing a LARGER number here means the
# rejection branch never fires, `truncated` stays 0, and the graph claims a full
# check it never performed.
MANIFEST_MAX_ENTRIES = VERIFY_MAX_FILES

# `_find_declaration_line` scans EVERY line of a file with a regex. On components
# it only runs on the (rare) failure path; extended to members that becomes
# "every unmatched member x file length", and the worst case is 6000 components x
# 80 members. `finalize` is the publish gate: when it stalls, the Agent goes
# silent on the terminal and the scheduler kills the node as hung.
MEMBER_LOOKUP_BUDGET = 2000

HISTORY_DIR_NAME = "graph-history"
HISTORY_KEEP = 5
HISTORY_MAX_BYTES = 24 * 1024 * 1024
HISTORY_COPY_CHUNK = 512 * 1024

PROVENANCES = ("extracted", "asserted")

ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")

LAYERS = ("frontend", "backend", "shared", "desktop", "mobile", "infra", "test", "docs", "other")
MODULE_KINDS = ("package", "feature", "layer", "service", "library", "app")
COMPONENT_KINDS = (
    "class", "interface", "enum", "struct", "function", "react_component",
    "hook", "store", "service", "table", "endpoint", "type_alias", "module",
)
RELATION_KINDS = (
    "extends", "implements", "composition", "aggregation", "association",
    "depends", "uses", "calls", "emits", "reads", "writes", "contains",
)
EVIDENCE_REQUIRED = ("extends", "implements", "composition")
VISIBILITIES = ("public", "protected", "private", "internal")

DEFAULT_EXCLUDES = {
    "node_modules", ".git", "dist", ".next", "build", "target", "venv",
    "__pycache__", "release", ".venv", ".cache", "coverage", ".agentmesh",
    ".claude-index", "out", "vendor", ".idea", ".vscode", ".gradle",
}

SOURCE_EXTENSIONS = {
    ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript",
    ".mjs": "JavaScript", ".cjs": "JavaScript", ".py": "Python", ".java": "Java",
    ".kt": "Kotlin", ".kts": "Kotlin", ".go": "Go", ".cs": "C#", ".rb": "Ruby",
    ".rs": "Rust", ".php": "PHP", ".swift": "Swift", ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".sql": "SQL", ".vue": "Vue",
    ".svelte": "Svelte", ".scala": "Scala", ".sh": "Shell", ".ps1": "PowerShell",
}

LAYER_HINTS = (
    ("test", ("__tests__", "test", "tests", "spec", "e2e")),
    ("docs", ("docs", "doc", "documentation")),
    ("infra", ("scripts", "ops", ".github", "infra", "deploy", "ci")),
    ("frontend", ("src", "client", "web", "renderer", "components", "pages", "app")),
    ("backend", ("server", "api", "backend", "services", "routes")),
    ("shared", ("shared", "common", "types", "protocol")),
    ("desktop", ("desktop", "electron")),
    ("mobile", ("android", "ios", "mobile")),
)


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

def emit(payload, code=0):
    """Print exactly one JSON line and exit with the given code."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    sys.exit(code)


def fail(message, **extra):
    payload = {"success": False, "error": message}
    payload.update(extra)
    emit(payload, 1)


def usage_error(message):
    emit({"success": False, "error": message, "kind": "usage"}, 2)


def write_out(path, payload):
    """Write a discovery result to `path` (creating parent dirs)."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)


def deliver(args, payload):
    """`--out` writes the payload to disk and prints a short receipt."""
    out = getattr(args, "out", None)
    if out:
        write_out(out, payload)
        summary = {"success": True, "out": out}
        for key in ("count", "total", "truncated"):
            if key in payload:
                summary[key] = payload[key]
        emit(summary)
    emit(payload)


# --------------------------------------------------------------------------
# Draft persistence
# --------------------------------------------------------------------------

def empty_draft(project_name="", root="."):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": 0,
        "generator": {"name": "index-graph-tools", "toolVersion": TOOL_VERSION, "agentType": ""},
        "project": {"name": project_name, "root": root, "languages": [], "indexVersion": None},
        "modules": [],
        "components": [],
        "relations": [],
        "truncation": {
            "modules": 0, "components": 0, "relations": 0, "members": 0,
            "droppedRelations": 0, "note": None,
        },
    }


def load_draft(required=True):
    if not os.path.isfile(DRAFT_PATH):
        if required:
            fail("draft not found; run `init` first", path=DRAFT_PATH)
        return empty_draft()
    try:
        with open(DRAFT_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as err:  # noqa: BLE001 - any unreadable draft is a business failure
        fail("draft is not readable JSON: %s" % err, path=DRAFT_PATH)
        return empty_draft()
    for key, default in (("modules", []), ("components", []), ("relations", [])):
        if not isinstance(data.get(key), list):
            data[key] = default
    if not isinstance(data.get("truncation"), dict):
        data["truncation"] = empty_draft()["truncation"]
    # A round-1 draft has no `verification` key at all, and `init` is designed to
    # be resumable, so finding one in the working directory is normal rather than
    # exceptional. Fill the default instead of raising.
    if "verification" in data and not isinstance(data.get("verification"), dict):
        data.pop("verification", None)
    return data


def save_draft(draft):
    os.makedirs(DRAFT_DIR, exist_ok=True)
    write_atomic(DRAFT_PATH, json.dumps(draft, ensure_ascii=False, indent=1))


def write_atomic(path, text):
    """Write via a temp file in the same directory, then os.replace.

    os.replace is atomic on NTFS and on POSIX, which is what lets the reader
    skip any "parse failed, retry" logic entirely.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    handle, tmp = tempfile.mkstemp(prefix=".tmp-", dir=parent or ".")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def counts(draft):
    members = 0
    for comp in draft.get("components", []):
        members += len(comp.get("attributes") or []) + len(comp.get("methods") or [])
    return {
        "modules": len(draft.get("modules", [])),
        "components": len(draft.get("components", [])),
        "relations": len(draft.get("relations", [])),
        "members": members,
    }


# --------------------------------------------------------------------------
# Field coercion
# --------------------------------------------------------------------------

def clip(value, limit):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def split_list(value, limit, item_limit):
    if value is None:
        return None
    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(",")
    out = []
    for item in items:
        text = clip(item, item_limit)
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out or None


def to_posix(value):
    if value is None:
        return None
    return str(value).strip().replace("\\", "/").rstrip("/") or "."


def enum_or(value, allowed, default):
    if value is None:
        return default
    text = str(value).strip()
    return text if text in allowed else default


def as_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return None


def as_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def prune(record):
    return {k: v for k, v in record.items() if v is not None}


# --------------------------------------------------------------------------
# Discovery: excluded directories
# --------------------------------------------------------------------------

def load_excludes(root):
    """Read `## Excluded Directories` from .claude-index/config.md, else defaults."""
    excludes = set(DEFAULT_EXCLUDES)
    path = os.path.join(root, CONFIG_PATH)
    if not os.path.isfile(path):
        return excludes
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return excludes
    inside = False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip().lower() == "## excluded directories"
            continue
        if not inside:
            continue
        item = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
        if item:
            excludes.add(item.group(1).strip().strip("`").rstrip("/"))
    return excludes


def is_excluded(rel_path, excludes):
    """Excluded when any single segment matches, any path prefix matches, or the
    segment is a dot-directory (`.github` is the one deliberate exception)."""
    if not rel_path or rel_path == ".":
        return False
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    for index, part in enumerate(parts):
        if part in excludes:
            return True
        if part.startswith(".") and part != ".github":
            return True
        if "/".join(parts[: index + 1]) in excludes:
            return True
    return False


def guess_layer(rel_path):
    lowered = rel_path.lower()
    segments = [s for s in lowered.split("/") if s]
    for layer, hints in LAYER_HINTS:
        for hint in hints:
            if hint in segments:
                return layer
    return "other"


# --------------------------------------------------------------------------
# Discovery: scan-modules
# --------------------------------------------------------------------------

def cmd_scan_modules(args):
    root = os.path.abspath(args.root)
    excludes = load_excludes(args.root)
    buckets = {}

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        dirnames[:] = [d for d in dirnames if not is_excluded((rel_dir + "/" + d).lstrip("/"), excludes)]
        if rel_dir and is_excluded(rel_dir, excludes):
            continue

        depth = 0 if not rel_dir else len(rel_dir.split("/"))
        # Files below --max-depth are folded into their ancestor at max-depth.
        bucket_key = rel_dir if depth <= args.max_depth else "/".join(rel_dir.split("/")[: args.max_depth])
        if not bucket_key:
            bucket_key = "."

        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue
            bucket = buckets.setdefault(bucket_key, {"files": 0, "loc": 0, "languages": {}})
            bucket["files"] += 1
            bucket["languages"][ext] = bucket["languages"].get(ext, 0) + 1
            try:
                with open(os.path.join(dirpath, name), "rb") as handle:
                    bucket["loc"] += handle.read().count(b"\n") + 1
            except OSError:
                pass

    candidates = []
    for path, bucket in buckets.items():
        if bucket["files"] < args.min_files:
            continue
        candidates.append({
            "path": path,
            "files": bucket["files"],
            "loc": bucket["loc"],
            "languages": bucket["languages"],
            "guessedLayer": guess_layer(path),
        })
    candidates.sort(key=lambda c: (-c["files"], c["path"]))
    truncated = len(candidates) > args.limit
    candidates = candidates[: args.limit]

    deliver(args, {
        "success": True,
        "command": "scan-modules",
        "root": to_posix(args.root),
        "count": len(candidates),
        "truncated": truncated,
        "excluded": sorted(excludes),
        "modules": candidates,
    })


# --------------------------------------------------------------------------
# Discovery: scan-imports
# --------------------------------------------------------------------------

TS_IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*(?:import\s[^'"\n]*from\s*|import\s*|export\s[^'"\n]*from\s*)['"]([^'"]+)['"]"""
    r"""|require\(\s*['"]([^'"]+)['"]\s*\)"""
)
PY_IMPORT_RE = re.compile(r"""(?:^|\n)\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))""")
JVM_IMPORT_RE = re.compile(r"""(?:^|\n)\s*import\s+([\w.]+)""")
CS_IMPORT_RE = re.compile(r"""(?:^|\n)\s*using\s+([\w.]+)\s*;""")
GO_IMPORT_RE = re.compile(r"""["']([\w./-]+)["']""")

# Repo-internal aliases resolved to a directory; anything else is a package.
ALIAS_PREFIXES = (("@/", "src/"), ("@server/", "server/"), ("@shared/", "shared/"))

LANG_BY_EXT = {
    ".ts": "ts", ".tsx": "ts", ".js": "ts", ".jsx": "ts", ".mjs": "ts", ".cjs": "ts",
    ".py": "py", ".java": "java", ".kt": "kt", ".kts": "kt", ".go": "go", ".cs": "cs",
}


def to_directory(root, joined):
    """Reduce a resolved specifier to a DIRECTORY.

    TS/JS imports normally omit the extension (`../bar`), so a plain "strip the
    extension" rule leaves a file masquerading as a directory and the edge lands
    on `server/bar` instead of `server`. Ask the filesystem instead: keep the
    path when it really is a directory, otherwise take its parent.
    """
    if not joined or joined == ".":
        return "."
    if os.path.isdir(os.path.join(root, joined)):
        return joined
    parent = os.path.dirname(joined)
    return parent or "."


def resolve_import(root, spec, source_rel):
    """Return (target_dir, is_external). Only relative + aliased specs resolve."""
    if spec.startswith("."):
        base = os.path.dirname(source_rel)
        joined = os.path.normpath(os.path.join(base, spec)).replace("\\", "/")
        if joined.startswith(".."):
            return None, True
        return to_directory(root, joined), False
    for prefix, replacement in ALIAS_PREFIXES:
        if spec.startswith(prefix):
            joined = replacement + spec[len(prefix):]
            return to_directory(root, joined), False
    head = spec.split("/")[0]
    return "external:" + head, True


def cmd_scan_imports(args):
    root = os.path.abspath(args.root)
    target = os.path.abspath(os.path.join(root, args.path))
    if not os.path.isdir(target) and not os.path.isfile(target):
        fail("path not found: %s" % to_posix(args.path))
    excludes = load_excludes(args.root)
    edges = {}
    scanned = 0

    for file_path, rel in iter_source_files(root, target, excludes):
        ext = os.path.splitext(file_path)[1].lower()
        lang = args.lang if args.lang != "auto" else LANG_BY_EXT.get(ext)
        if not lang:
            continue
        text = read_text(file_path)
        if text is None:
            continue
        scanned += 1
        source_dir = os.path.dirname(rel) or "."
        for spec in extract_import_specs(text, lang):
            resolved, external = resolve_import(root, spec, rel)
            if resolved is None:
                continue
            if external and not args.include_external:
                continue
            if resolved == source_dir:
                continue
            key = source_dir + "|" + resolved
            edge = edges.setdefault(key, {"from": source_dir, "to": resolved, "count": 0, "samples": []})
            edge["count"] += 1
            if len(edge["samples"]) < 3:
                edge["samples"].append(rel)
        if len(edges) > args.limit * 4:
            break

    ordered = sorted(edges.values(), key=lambda e: (-e["count"], e["from"], e["to"]))
    truncated = len(ordered) > args.limit
    ordered = ordered[: args.limit]

    deliver(args, {
        "success": True,
        "command": "scan-imports",
        "path": to_posix(args.path),
        "extraction": "regex",
        "filesScanned": scanned,
        "count": len(ordered),
        "truncated": truncated,
        "edges": ordered,
    })


def extract_import_specs(text, lang):
    out = []
    if lang == "ts":
        for match in TS_IMPORT_RE.finditer(text):
            out.append(match.group(1) or match.group(2))
    elif lang == "py":
        for match in PY_IMPORT_RE.finditer(text):
            out.append(match.group(1) or match.group(2))
    elif lang in ("java", "kt"):
        for match in JVM_IMPORT_RE.finditer(text):
            out.append(match.group(1))
    elif lang == "cs":
        for match in CS_IMPORT_RE.finditer(text):
            out.append(match.group(1))
    elif lang == "go":
        for match in GO_IMPORT_RE.finditer(text):
            out.append(match.group(1))
    return [s for s in out if s]


# --------------------------------------------------------------------------
# Discovery: scan-symbols
# --------------------------------------------------------------------------

SYMBOL_PATTERNS = (
    ("class", re.compile(r"^\s*(export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")),
    ("interface", re.compile(r"^\s*(export\s+)?interface\s+([A-Za-z_$][\w$]*)")),
    ("enum", re.compile(r"^\s*(export\s+)?(?:const\s+)?enum\s+([A-Za-z_$][\w$]*)")),
    ("type_alias", re.compile(r"^\s*(export\s+)?type\s+([A-Za-z_$][\w$]*)\s*[=<]")),
    ("function", re.compile(r"^\s*(export\s+)?(?:async\s+)?function\s+\*?\s*([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s*)?\(")),
    ("class", re.compile(r"^\s*(?:public\s+|private\s+|internal\s+)?(?:abstract\s+|final\s+|data\s+|sealed\s+)*class\s+([A-Za-z_][\w]*)")),
    ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)")),
)


def cmd_scan_symbols(args):
    root = os.path.abspath(args.root)
    target = os.path.abspath(os.path.join(root, args.path))
    if not os.path.exists(target):
        fail("path not found: %s" % to_posix(args.path))
    wanted = {k.strip() for k in (args.kinds or "").split(",") if k.strip()} or None
    excludes = load_excludes(args.root)
    symbols = []
    truncated = False

    for file_path, rel in iter_source_files(root, target, excludes):
        text = read_text(file_path)
        if text is None:
            continue
        # `split("\n")`, not `splitlines()`: every other line number in this
        # tool (build_line_starts, _read_lines_cached) counts "\n" only, and
        # `splitlines()` additionally breaks on VT(0x0b), FF(0x0c), FS/GS/RS,
        # NEL(0x85), LS(U+2028) and PS(U+2029). A file containing any of those
        # would make this command hand back line numbers that `verify` then
        # reports as wrong - blaming the wrong side.
        for index, line in enumerate(text.split("\n"), start=1):
            if len(line) > 400:
                continue
            for kind, pattern in SYMBOL_PATTERNS:
                match = pattern.match(line)
                if not match:
                    continue
                groups = [g for g in match.groups() if g is not None]
                name = groups[-1]
                if not name or (wanted and kind not in wanted):
                    continue
                symbols.append({
                    "file": rel,
                    "line": index,
                    "kind": kind,
                    "name": name,
                    "exported": "export" in line or "public" in line,
                })
                break
            if len(symbols) >= args.limit:
                truncated = True
                break
        if truncated:
            break

    deliver(args, {
        "success": True,
        "command": "scan-symbols",
        "path": to_posix(args.path),
        "count": len(symbols),
        "truncated": truncated,
        # Regex-level extraction: cross-check against the source before writing
        # any of this into the graph. `heuristic` is kept for backward
        # compatibility and equals `extraction == "regex"`; prefer `extraction`.
        "extraction": "regex",
        "heuristic": True,
        "symbols": symbols,
    })


def iter_source_files(root, target, excludes):
    if os.path.isfile(target):
        yield target, os.path.relpath(target, root).replace("\\", "/")
        return
    for dirpath, dirnames, filenames in os.walk(target):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        prefix = "" if rel_dir == "." else rel_dir
        dirnames[:] = [d for d in dirnames if not is_excluded((prefix + "/" + d).lstrip("/"), excludes)]
        if rel_dir != "." and is_excluded(rel_dir, excludes):
            continue
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() not in SOURCE_EXTENSIONS:
                continue
            full = os.path.join(dirpath, name)
            yield full, os.path.relpath(full, root).replace("\\", "/")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def read_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def decode_source(data):
    """Bytes -> text for LINE LOOKUP only.

    Never on the hash path: `errors="replace"` is exactly what makes the text
    route impossible to keep in sync across two languages (see
    `normalize_source_bytes`).
    """
    return data.decode("utf-8", errors="replace")


def normalize_source_bytes(data):
    """Strip ONE UTF-8 BOM, then fold CRLF and lone CR to LF - on BYTES.

    Mirror of shared/project-graph-source-hash.ts::normalizeSourceBytes. The two
    implementations MUST agree byte for byte, so neither side is allowed to
    decode or to split lines (invariant 1):

    - Decoding cannot agree and, on this read path, cannot even fail:
      `read_text` uses errors="replace", so "skip the file if it does not
      decode" is an instruction that never executes - and Python's replacement
      GRANULARITY for illegal sequences is not guaranteed to match Node's
      Buffer.toString('utf8'), so the two sides would hash the same file
      differently.
    - Splitting cannot agree either: `str.splitlines()` also breaks on VT(0x0b),
      FF(0x0c), FS/GS/RS, NEL(0x85), LS(U+2028) and PS(U+2029); the JS
      three-way regex does not.

    On bytes, neither failure mode can exist. For valid UTF-8 the result is
    identical to the text route (U+2028 / U+2029 / NEL are all multi-byte, and
    the folding below only ever looks at the single bytes 0x0d / 0x0a).

    The two `replace` calls are equivalent to a single left-to-right pass; the
    order is NOT interchangeable.
    """
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def hash_source_bytes(data):
    """sha256 of the normalised bytes, first 16 hex characters.

    Deliberately takes BYTES only. A `str` overload is exactly the entry point
    this design removes: the moment one exists, "who decodes, and with which
    error policy" becomes a question that can be answered wrongly - and the
    symptom of answering it wrongly is silent (that file shows as drifted
    forever, rebuilding does not clear it, and the logs say nothing).
    """
    return hashlib.sha256(normalize_source_bytes(data)).hexdigest()[:16]


def now_ms():
    """Wall clock in milliseconds WITHOUT importing `time`.

    The import list is asserted by the asset-shape test and kept at the stdlib
    minimum on purpose. `tempfile` is already here for atomic writes, and a
    file created a moment ago carries the current clock in its mtime. Returns 0
    rather than raising: a missing timestamp costs one label in the UI, an
    exception would abort a publish.
    """
    try:
        handle, tmp = tempfile.mkstemp(prefix=".igt-clock-")
        try:
            os.close(handle)
            return int(os.path.getmtime(tmp) * 1000)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except OSError:
        return 0


# --------------------------------------------------------------------------
# Structural extraction: masking pre-pass
# --------------------------------------------------------------------------
#
# Counting braces on raw text is wrong, and it is wrong SILENTLY: one `{`
# inside a string literal is enough to send a class-body range off the rails,
# and the members harvested from the wrong range look perfectly plausible.
# So every TS/JS scan runs on a mask first: same length, same newlines, with
# string literals, template literal segments, comments and regex literals
# replaced by spaces. Offsets computed on the mask index straight back into
# the original text.

# Tokens after which a `/` starts a regex literal rather than a division.
# This is the ONLY heuristic left in the TS path; see `strip_noise`.
_REGEX_PREV_PUNCT = frozenset("(,=:[!&|?{};+-*%~^")
_REGEX_PREV_WORDS = frozenset((
    "return", "typeof", "case", "in", "of", "new", "delete", "void",
    "instanceof", "do", "else", "yield", "await",
))
_IDENT_START = re.compile(r"[A-Za-z_$]")
_TEMPLATE_MAX_DEPTH = 24


def _blank(chars, start, end):
    """Replace chars[start:end] with spaces, preserving newlines verbatim."""
    for index in range(start, min(end, len(chars))):
        if chars[index] != "\n":
            chars[index] = " "


def _regex_allowed(prev):
    if not prev:
        return True
    if prev in _REGEX_PREV_WORDS:
        return True
    return len(prev) == 1 and prev in _REGEX_PREV_PUNCT


def _scan_quoted(text, start, quote):
    """Index just past the closing quote (or the newline that ends an
    unterminated single-line string)."""
    length = len(text)
    index = start + 1
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if char == "\n":
            return index
        index += 1
    return length


def _scan_regex(text, start):
    """Index just past a regex literal's flags, or None when `start` is more
    plausibly a division operator (unterminated, or spanning a newline)."""
    length = len(text)
    index = start + 1
    in_class = False
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "\n":
            return None
        if in_class:
            if char == "]":
                in_class = False
        elif char == "[":
            in_class = True
        elif char == "/":
            index += 1
            while index < length and text[index].isalpha():
                index += 1
            return index
        index += 1
    return None


def _scan_template(text, chars, start, warnings, depth):
    """Consume a template literal; blank its literal segments but treat every
    `${ ... }` as code.

    Leaving the interpolation braces in place is deliberate: they are balanced,
    so outer brace matching still adds up, while the expression inside gets the
    same masking treatment (a `}` hiding in a string there would otherwise close
    a class body early).
    """
    length = len(text)
    chars[start] = " "
    index = start + 1
    segment = index
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "`":
            _blank(chars, segment, index)
            chars[index] = " "
            return index + 1
        if char == "$" and index + 1 < length and text[index + 1] == "{":
            _blank(chars, segment, index)
            if depth >= _TEMPLATE_MAX_DEPTH:
                # Pathological nesting: stop recursing rather than blow the
                # stack. The rest of this literal stays unmasked, which can only
                # cost us a container (fail by omission, never by invention).
                index += 2
                segment = index
                continue
            index = _mask_code(text, chars, index + 2, warnings, True, depth + 1)
            segment = index
            continue
        index += 1
    _blank(chars, segment, length)
    return length


def _mask_code(text, chars, start, warnings, stop_on_close_brace, depth):
    """Mask from `start`. When `stop_on_close_brace`, return just past the `}`
    that closes the block we were called inside; otherwise run to the end."""
    length = len(text)
    index = start
    brace = 0
    prev = ""
    while index < length:
        char = text[index]
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            end = text.find("\n", index)
            end = length if end < 0 else end
            _blank(chars, index, end)
            index = end
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            end = length if end < 0 else end + 2
            _blank(chars, index, end)
            index = end
            continue
        if char == "/" and text[index + 1:index + 2] != ">" and _regex_allowed(prev):
            # `/>` is a JSX self-closing tag, not a regex. A regex CAN begin with
            # `>`, but in .tsx the tag is overwhelmingly more likely, and the cost
            # of the two mistakes is not symmetric: declining only means we do not
            # mask (safe), while accepting `/><Bar /` as one literal blanks real
            # code between two tags on the same line.
            end = _scan_regex(text, index)
            if end is None:
                # Not a regex after all: treated as division, nothing was masked,
                # so nothing can have been swallowed. No warning - a warning here
                # fires on every `/>` in a .tsx file and drowns the real ones.
                prev = "/"
                index += 1
                continue
            if "{" in text[index:end] or "}" in text[index:end]:
                # Accepted a literal that contains a brace. If this was actually a
                # division, the mask just moved a class-body boundary and a
                # container will be quietly missing - which is precisely the case
                # worth surfacing.
                warnings.append({"code": "AMBIGUOUS_SLASH", "offset": index})
            _blank(chars, index, end)
            prev = "x"
            index = end
            continue
        if char == "'" or char == '"':
            end = _scan_quoted(text, index, char)
            _blank(chars, index, end)
            prev = "x"
            index = end
            continue
        if char == "`":
            index = _scan_template(text, chars, index, warnings, depth)
            prev = "x"
            continue
        if char == "{":
            brace += 1
            prev = "{"
            index += 1
            continue
        if char == "}":
            if stop_on_close_brace and brace == 0:
                return index + 1
            brace = max(0, brace - 1)
            prev = "}"
            index += 1
            continue
        if _IDENT_START.match(char):
            end = index + 1
            while end < length and (text[end].isalnum() or text[end] in "_$"):
                end += 1
            prev = text[index:end]
            index = end
            continue
        if char.isdigit():
            prev = "0"
            index += 1
            continue
        if not char.isspace():
            prev = char
        index += 1
    return length


def strip_noise(text, lang, warnings=None):
    """Return a string of EXACTLY the same length as `text` in which every
    string literal, template literal segment, line comment, block comment and
    regex literal has been replaced by spaces. Newlines are preserved verbatim
    so byte offsets and line numbers stay valid in both strings.

    Length and newline conservation is load-bearing: everything downstream
    locates on the mask and slices the original, and being off by one character
    misplaces every `file:line` the graph will later assert.
    """
    if lang != "ts":
        return text
    chars = list(text)
    _mask_code(text, chars, 0, warnings if warnings is not None else [], False, 0)
    return "".join(chars)


# --------------------------------------------------------------------------
# Structural extraction: TypeScript / JavaScript
# --------------------------------------------------------------------------

CONTAINER_RE = re.compile(
    r"(?:^|[\n;}])[ \t]*"
    r"(?P<mods>(?:export\s+(?:default\s+)?|declare\s+|abstract\s+)*)"
    r"(?P<kw>class|interface|enum)\s+(?P<name>[A-Za-z_$][\w$]*)",
    re.M,
)

_MEMBER_MODS = r"(?:(?:public|private|protected|readonly|static|abstract|override|declare|async)\s+)*"
METHOD_RE = re.compile(
    r"(?P<mods>" + _MEMBER_MODS + r")"
    r"(?P<accessor>(?:get|set)\s+)?"
    r"(?P<name>#?[A-Za-z_$][\w$]*)\s*(?P<opt>\?)?\s*(?:<[^<>()]*>)?\s*\("
)
FIELD_TYPED_RE = re.compile(
    r"(?P<mods>" + _MEMBER_MODS + r")"
    r"(?P<name>#?[A-Za-z_$][\w$]*)\s*(?P<opt>[?!])?\s*:"
)
FIELD_ASSIGN_RE = re.compile(
    r"(?P<mods>" + _MEMBER_MODS + r")"
    r"(?P<name>#?[A-Za-z_$][\w$]*)\s*="
)
PARAM_PROPERTY_RE = re.compile(
    r"^\s*(?:(?P<vis>public|private|protected)\s+)?(?P<ro>readonly\s+)?"
    r"(?:(?P<vis2>public|private|protected)\s+)?"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\??\s*(?::\s*(?P<type>.+))?$",
    re.S,
)
SIMPLE_NAME_RE = re.compile(r"^[A-Za-z_$][\w$]*$")

TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def compress_ws(value):
    """Collapse internal whitespace so a multi-line signature renders as one
    line inside a UML box."""
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value)).strip() or None


def compress_signature(value):
    """`compress_ws` plus the tidying a flattened parameter list needs.

    A multi-line signature collapses to `( input: string, )`: the newline after
    the paren becomes a space and the trailing comma is still there. Both are
    noise in a UML box, and the box is the only place this string is ever read.
    """
    text = compress_ws(value)
    if text is None:
        return None
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r",?\s+\)", ")", text)
    return text or None


def build_line_starts(text):
    """Offsets of every line start. Built ONCE per file: doing
    `text.count("\\n", 0, offset)` per lookup is quadratic and visibly stalls on
    a 5000-line file."""
    starts = [0]
    index = text.find("\n")
    while index >= 0:
        starts.append(index + 1)
        index = text.find("\n", index + 1)
    return starts


def line_of(line_starts, offset):
    return bisect.bisect_right(line_starts, offset)


def _match_brace(masked, open_index):
    depth = 0
    index = open_index
    length = len(masked)
    while index < length:
        char = masked[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _match_paren(masked, open_index):
    depth = 0
    index = open_index
    length = len(masked)
    while index < length:
        char = masked[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _find_container_body(masked, start):
    """From just after the container name, find the `{ ... }` body.

    Returns (open_index, close_index) or None. Bails out on `;` (a `declare
    class X;` style forward declaration) and on an unbalanced brace: a
    truncated file or a mask misfire must skip the container, never guess a
    range.
    """
    length = len(masked)
    index = start
    angle = 0
    paren = 0
    while index < length:
        char = masked[index]
        if char == "<":
            angle += 1
        elif char == ">":
            angle = max(0, angle - 1)
        elif char == "(":
            paren += 1
        elif char == ")":
            paren = max(0, paren - 1)
        elif char == ";" and angle == 0 and paren == 0:
            return None
        elif char == "{" and angle == 0 and paren == 0:
            close = _match_brace(masked, index)
            return None if close is None else (index, close)
        index += 1
    return None


def _split_type_names(chunk):
    """Split a heritage clause into bare type names: drop generic arguments and
    namespace prefixes, keep at most 8."""
    parts = []
    current = []
    depth = 0
    for char in chunk:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))

    names = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        text = re.sub(r"<.*$", "", text, flags=re.S).strip()
        text = text.split("(")[0].strip()
        if "." in text:
            text = text.split(".")[-1].strip()
        if SIMPLE_NAME_RE.match(text):
            names.append(text)
        if len(names) >= 8:
            break
    return names


def parse_heritage(raw):
    """`extends A, B implements C` -> (["A", "B"], ["C"]).

    TS allows `interface A extends B, C` (multi) and
    `class A extends B implements C, D` (single + multi); no arity is enforced
    here, the lists are recorded as written.
    """
    extends_at = re.search(r"\bextends\b", raw)
    implements_at = re.search(r"\bimplements\b", raw)
    extends = []
    implements = []
    if extends_at:
        stop = implements_at.start() if implements_at and implements_at.start() > extends_at.start() else len(raw)
        extends = _split_type_names(raw[extends_at.end():stop])
    if implements_at:
        stop = extends_at.start() if extends_at and extends_at.start() > implements_at.start() else len(raw)
        implements = _split_type_names(raw[implements_at.end():stop])
    return extends, implements


def _leading_doc(text, start):
    """First line of the JSDoc block immediately above a declaration.

    Read off the ORIGINAL text (the mask blanked the comment body). Feeds the
    component `summary`, so the model does not have to re-read the file just to
    describe something that already documents itself.
    """
    cursor = start
    while cursor > 0 and text[cursor - 1] in " \t\r\n":
        cursor -= 1
    if cursor < 2 or text[cursor - 2:cursor] != "*/":
        return None
    open_at = text.rfind("/**", 0, cursor)
    if open_at < 0:
        return None
    for line in text[open_at + 3:cursor - 2].split("\n"):
        stripped = line.strip().lstrip("*").strip()
        if stripped:
            return clip(compress_ws(stripped), 200)
    return None


def _visibility_of(mods, name):
    if "private" in mods:
        return "private"
    if "protected" in mods:
        return "protected"
    if "public" in mods:
        return "public"
    if name.startswith("#"):
        return "private"
    if name.startswith("_"):
        return "protected"
    return "public"


def _member_flags(mods):
    return {
        "static": "static" in mods,
        "abstract": "abstract" in mods,
        "async": "async" in mods,
        "readonly": "readonly" in mods,
    }


def _skip_statement(masked, index, end):
    """Advance past whatever we could not classify, stopping at the next `;` or
    newline that sits outside brackets."""
    depth = 0
    while index < end:
        char = masked[index]
        if char in "{([":
            depth += 1
        elif char in "})]":
            if depth == 0:
                return index
            depth -= 1
        elif depth == 0 and (char == ";" or char == "\n"):
            return index + 1
        index += 1
    return end


def _param_properties(raw_params, line):
    """Constructor parameter properties: `constructor(private svc: Service)`
    declares a field. Widely used in this repository, and invisible to anything
    that only looks at the class body."""
    inner = raw_params.strip()
    if inner.startswith("("):
        inner = inner[1:]
    if inner.endswith(")"):
        inner = inner[:-1]
    fields = []
    depth = 0
    current = []
    parts = []
    for char in inner:
        if char in "<([{":
            depth += 1
        elif char in ">)]}":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))

    for part in parts:
        text = part.strip()
        if not text:
            continue
        if not re.search(r"\b(public|private|protected|readonly)\b", text.split("=")[0]):
            continue
        text = text.split("=")[0]
        match = PARAM_PROPERTY_RE.match(text)
        if not match:
            continue
        name = match.group("name")
        visibility = match.group("vis") or match.group("vis2") or ("public" if match.group("ro") else None)
        fields.append({
            "name": name,
            "type": clip(compress_ws(match.group("type")), MAX_TYPE),
            "visibility": visibility or _visibility_of("", name),
            "static": False,
            "abstract": False,
            "async": False,
            "readonly": bool(match.group("ro")),
            "line": line,
        })
    return fields


def _extract_enum_members(text, masked, body_open, body_close, line_starts):
    members = []
    index = body_open + 1
    depth = 0
    current_start = index
    chunks = []
    while index < body_close:
        char = masked[index]
        if char in "<([{":
            depth += 1
        elif char in ">)]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            chunks.append((current_start, index))
            current_start = index + 1
        index += 1
    chunks.append((current_start, body_close))

    for start, stop in chunks:
        raw = text[start:stop]
        stripped = raw.strip()
        if not stripped:
            continue
        name_match = re.match(r"^\s*(?P<name>[A-Za-z_$][\w$]*)\s*(?:=\s*(?P<value>.+))?$", raw, re.S)
        if not name_match:
            continue
        offset = start + (len(raw) - len(raw.lstrip()))
        members.append({
            "name": name_match.group("name"),
            "type": clip(compress_ws(name_match.group("value")), MAX_TYPE),
            "visibility": "public",
            "static": False,
            "abstract": False,
            "async": False,
            "readonly": False,
            "line": line_of(line_starts, offset),
        })
    return members


def _keep_member(visibility, public_only):
    """Default is "keep everything" - a UML box without private fields is a
    much weaker artifact, and the renderer already draws the `-` sigil for
    them. `--public-only` is the opt-in narrowing."""
    return not public_only or visibility == "public"


def _extract_ts_members(text, masked, body_open, body_close, line_starts, public_only):
    attributes = []
    methods = []
    index = body_open + 1
    end = body_close

    while index < end:
        char = masked[index]
        if char in " \t\r\n;,":
            index += 1
            continue
        if char == "@":
            index = _skip_statement(masked, index, end)
            continue
        if char in "})]":
            index += 1
            continue

        method = METHOD_RE.match(masked, index, end)
        if method:
            paren_open = method.end() - 1
            paren_close = _match_paren(masked, paren_open)
            if paren_close is None or paren_close >= end:
                index = _skip_statement(masked, index, end)
                continue
            mods = method.group("mods") or ""
            name = method.group("name")
            raw_params = text[paren_open:paren_close + 1]
            cursor = paren_close + 1
            return_type = None
            while cursor < end and masked[cursor] in " \t\r\n":
                cursor += 1
            if cursor < end and masked[cursor] == ":":
                type_start = cursor + 1
                type_end = type_start
                depth = 0
                while type_end < end:
                    ch = masked[type_end]
                    if ch in "<([{":
                        if ch == "{" and depth == 0:
                            break
                        depth += 1
                    elif ch in ">)]}":
                        if ch == "}" and depth == 0:
                            break
                        depth = max(0, depth - 1)
                    elif depth == 0 and (ch == ";" or ch == "\n"):
                        break
                    type_end += 1
                return_type = compress_ws(text[type_start:type_end])
                cursor = type_end
            while cursor < end and masked[cursor] in " \t\r\n":
                cursor += 1
            member_line = line_of(line_starts, index)
            flags = _member_flags(mods)
            signature = compress_signature(raw_params) or "()"
            if return_type:
                signature = signature + ": " + return_type
            visibility = _visibility_of(mods, name)
            if name == "constructor":
                for field in _param_properties(raw_params, member_line):
                    if _keep_member(field["visibility"], public_only):
                        attributes.append(field)
            if _keep_member(visibility, public_only):
                methods.append({
                    "name": name,
                    "signature": clip(signature, MAX_SIGNATURE),
                    "visibility": visibility,
                    "static": flags["static"],
                    "abstract": flags["abstract"],
                    "async": flags["async"],
                    "readonly": False,
                    "line": member_line,
                })
            if cursor < end and masked[cursor] == "{":
                close = _match_brace(masked, cursor)
                index = end if close is None else close + 1
            else:
                index = _skip_statement(masked, cursor, end)
            continue

        field = FIELD_TYPED_RE.match(masked, index, end)
        kind = "typed"
        if not field:
            field = FIELD_ASSIGN_RE.match(masked, index, end)
            kind = "assign"
        if field:
            mods = field.group("mods") or ""
            name = field.group("name")
            member_line = line_of(line_starts, index)
            flags = _member_flags(mods)
            visibility = _visibility_of(mods, name)
            type_text = None
            if kind == "typed":
                type_start = field.end()
                type_end = type_start
                depth = 0
                while type_end < end:
                    ch = masked[type_end]
                    if ch in "<([{":
                        depth += 1
                    elif ch in ">)]}":
                        if depth == 0:
                            break
                        depth -= 1
                    elif depth == 0 and (ch == ";" or ch == "\n" or ch == "="):
                        break
                    type_end += 1
                type_text = compress_ws(text[type_start:type_end])
                index = _skip_statement(masked, type_end, end)
            else:
                index = _skip_statement(masked, field.end(), end)
            if _keep_member(visibility, public_only):
                attributes.append({
                    "name": name,
                    "type": clip(type_text, MAX_TYPE),
                    "visibility": visibility,
                    "static": flags["static"],
                    "abstract": flags["abstract"],
                    "async": False,
                    "readonly": flags["readonly"],
                    "line": member_line,
                })
            continue

        index = _skip_statement(masked, index, end)

    return attributes, methods


def extract_ts(text, rel_path, opts):
    """Structural extraction for TS/JS. Returns (containers, warnings)."""
    warnings = []
    masked = strip_noise(text, "ts", warnings)
    line_starts = build_line_starts(text)
    for warning in warnings:
        offset = warning.pop("offset", 0)
        warning["file"] = rel_path
        warning["line"] = line_of(line_starts, offset)

    containers = []
    for match in CONTAINER_RE.finditer(masked):
        name = match.group("name")
        keyword = match.group("kw")
        mods = match.group("mods") or ""
        body = _find_container_body(masked, match.end())
        if body is None:
            warnings.append({
                "code": "BODY_UNMATCHED", "file": rel_path,
                "line": line_of(line_starts, match.start("name")), "name": name,
            })
            continue
        body_open, body_close = body
        heritage_raw = text[match.end():body_open]
        extends, implements = parse_heritage(heritage_raw)

        if keyword == "enum":
            attributes = _extract_enum_members(text, masked, body_open, body_close, line_starts)
            methods = []
        else:
            attributes, methods = _extract_ts_members(
                text, masked, body_open, body_close, line_starts, opts.get("public_only", False),
            )

        exported = "export" in mods
        if opts.get("exported_only") and not exported:
            continue
        container = {
            "name": name,
            "kind": keyword,
            "extraction": "structural",
            "file": rel_path,
            "line": line_of(line_starts, match.start("name")),
            "exported": exported,
            "abstract": "abstract" in mods,
            "extends": extends,
            "implements": implements,
            "attributes": attributes,
            "methods": methods,
        }
        doc = _leading_doc(text, match.start("mods") if mods else match.start("kw"))
        if doc:
            container["docFirstLine"] = doc
        containers.append(container)
    return containers, warnings


# --------------------------------------------------------------------------
# Structural extraction: Python (stdlib ast, so this one is exact)
# --------------------------------------------------------------------------

def _expr_name(node):
    """Best-effort name of an expression node.

    `Name` / `Attribute` / `Subscript` are handled directly because they cover
    every base class and annotation that matters; `ast.unparse` is only a
    fallback because it does not exist before 3.9. Calling it unguarded turns
    the whole Python path into an AttributeError that surfaces as "this project
    has no classes" - which sounds entirely plausible.
    """
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _expr_name(node.value)
    unparse = getattr(ast, "unparse", None)
    if unparse is not None:
        try:
            return compress_ws(unparse(node))
        except Exception:  # noqa: BLE001 - any unparse failure degrades to "unknown"
            return None
    return None


def _py_visibility(name):
    if name.startswith("__") and not name.endswith("__"):
        return "private"
    if name.startswith("_"):
        return "protected"
    return "public"


def _py_decorators(node):
    names = set()
    for decorator in getattr(node, "decorator_list", []) or []:
        name = _expr_name(decorator if not isinstance(decorator, ast.Call) else decorator.func)
        if name:
            names.add(name)
    return names


def _py_annotation(arg):
    return _expr_name(getattr(arg, "annotation", None))


def _py_signature(fn):
    args = fn.args
    pieces = []
    posonly = list(getattr(args, "posonlyargs", []) or [])
    positional = posonly + list(args.args or [])
    defaults = list(args.defaults or [])
    first_default = len(positional) - len(defaults)
    for index, arg in enumerate(positional):
        piece = arg.arg
        annotation = _py_annotation(arg)
        if annotation:
            piece += ": " + annotation
        if index >= first_default:
            piece += "=..."
        pieces.append(piece)
        if posonly and index == len(posonly) - 1:
            pieces.append("/")
    if args.vararg is not None:
        piece = "*" + args.vararg.arg
        annotation = _py_annotation(args.vararg)
        if annotation:
            piece += ": " + annotation
        pieces.append(piece)
    elif args.kwonlyargs:
        pieces.append("*")
    kw_defaults = list(args.kw_defaults or [])
    for index, arg in enumerate(args.kwonlyargs or []):
        piece = arg.arg
        annotation = _py_annotation(arg)
        if annotation:
            piece += ": " + annotation
        if index < len(kw_defaults) and kw_defaults[index] is not None:
            piece += "=..."
        pieces.append(piece)
    if args.kwarg is not None:
        piece = "**" + args.kwarg.arg
        annotation = _py_annotation(args.kwarg)
        if annotation:
            piece += ": " + annotation
        pieces.append(piece)
    signature = "(" + ", ".join(pieces) + ")"
    returns = _expr_name(getattr(fn, "returns", None))
    if returns:
        signature += " -> " + returns
    return signature


def _py_self_attributes(class_node):
    """`self.x = ...` inside `__init__`. Without this a typical Python class
    reports zero attributes, which reads as a fact rather than a gap."""
    found = []
    seen = set()
    for child in class_node.body:
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) or child.name != "__init__":
            continue
        for node in ast.walk(child):
            targets = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for target in targets:
                if not isinstance(target, ast.Attribute):
                    continue
                if not isinstance(target.value, ast.Name) or target.value.id != "self":
                    continue
                if target.attr in seen:
                    continue
                seen.add(target.attr)
                annotation = _expr_name(getattr(node, "annotation", None)) if isinstance(node, ast.AnnAssign) else None
                found.append({
                    "name": target.attr,
                    "type": clip(annotation, MAX_TYPE),
                    "visibility": _py_visibility(target.attr),
                    "static": False,
                    "abstract": False,
                    "async": False,
                    "readonly": False,
                    "line": getattr(target, "lineno", 0) or 0,
                })
    return found


def _py_container(class_node, qualified_name, rel_path, public_only):
    attributes = []
    methods = []
    seen_attrs = set()

    for child in class_node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = _py_decorators(child)
            visibility = _py_visibility(child.name)
            if not _keep_member(visibility, public_only):
                continue
            if "property" in decorators or "cached_property" in decorators:
                if child.name not in seen_attrs:
                    seen_attrs.add(child.name)
                    attributes.append({
                        "name": child.name,
                        "type": clip(_expr_name(getattr(child, "returns", None)), MAX_TYPE),
                        "visibility": visibility,
                        "static": False,
                        "abstract": False,
                        "async": False,
                        "readonly": True,
                        "line": child.lineno,
                    })
                continue
            methods.append({
                "name": child.name,
                "signature": clip(_py_signature(child), MAX_SIGNATURE),
                "visibility": visibility,
                "static": "staticmethod" in decorators or "classmethod" in decorators,
                "abstract": "abstractmethod" in decorators,
                "async": isinstance(child, ast.AsyncFunctionDef),
                "readonly": False,
                "line": child.lineno,
            })
            continue
        targets = []
        annotation = None
        if isinstance(child, ast.AnnAssign):
            targets = [child.target]
            annotation = _expr_name(child.annotation)
        elif isinstance(child, ast.Assign):
            targets = list(child.targets)
        for target in targets:
            if not isinstance(target, ast.Name) or target.id in seen_attrs:
                continue
            visibility = _py_visibility(target.id)
            if not _keep_member(visibility, public_only):
                continue
            seen_attrs.add(target.id)
            attributes.append({
                "name": target.id,
                "type": clip(annotation, MAX_TYPE),
                "visibility": visibility,
                "static": True,
                "abstract": False,
                "async": False,
                "readonly": False,
                "line": getattr(target, "lineno", child.lineno),
            })

    for attribute in _py_self_attributes(class_node):
        if attribute["name"] in seen_attrs:
            continue
        if not _keep_member(attribute["visibility"], public_only):
            continue
        seen_attrs.add(attribute["name"])
        attributes.append(attribute)

    bases = []
    for base in class_node.bases:
        name = _expr_name(base)
        if name:
            bases.append(name.split(".")[-1])

    doc = ast.get_docstring(class_node)
    return {
        "name": qualified_name,
        "kind": "class",
        "extraction": "ast",
        "file": rel_path,
        "line": class_node.lineno,
        # Python has no export keyword; the leading-underscore convention is the
        # closest thing, so `--exported-only` uses it rather than dropping every
        # Python class on the floor.
        "exported": not qualified_name.split(".")[-1].startswith("_"),
        "abstract": any(name in ("ABC", "ABCMeta") for name in bases),
        "extends": bases[:8],
        "implements": [],
        "docFirstLine": clip((doc or "").strip().split("\n")[0], 200),
        "attributes": attributes,
        "methods": methods,
    }


def extract_py(text, rel_path, opts):
    """Exact extraction via the stdlib parser. Returns (containers, warnings)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError) as err:
        return [], [{
            "code": "PY_PARSE_FAILED", "file": rel_path,
            "line": getattr(err, "lineno", 0) or 0,
        }]

    public_only = opts.get("public_only", False)
    containers = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, ast.ClassDef):
                continue
            qualified = (prefix + "." + child.name) if prefix else child.name
            container = _py_container(child, qualified, rel_path, public_only)
            if opts.get("exported_only") and not container["exported"]:
                continue
            containers.append(container)
            walk(child, qualified)

    walk(tree, "")
    return containers, []


# --------------------------------------------------------------------------
# Discovery: scan-uml
# --------------------------------------------------------------------------

def _short_hash(text):
    """FNV-1a, 24 bits. Deterministic and dependency-free: adding `hashlib`
    would widen the pinned import list for six characters of suffix."""
    value = 2166136261
    for char in text:
        value ^= ord(char) & 0xFF
        value = (value * 16777619) & 0xFFFFFFFF
    return "%06x" % (value & 0xFFFFFF)


def sanitize_id_part(value):
    part = re.sub(r"[^A-Za-z0-9._-]", "_", str(value or "")).strip("._-")
    return part or "x"


def build_component_id(module_id, name):
    """`cmp.<module suffix>.<Name>`.

    Scoping by module is not cosmetic: `--emit-ops` is designed to be run once
    per module, and `apply` upserts components BY ID. A bare `cmp.<Name>` makes
    `server/services`' `Config` and `src/lib`' `Config` the same record, so the
    second scan replaces the first wholesale - members included - and reports
    `updated` instead of `created`. Nothing anywhere errors.
    """
    suffix = str(module_id or "")
    if suffix.startswith("mod."):
        suffix = suffix[4:]
    candidate = "cmp." + sanitize_id_part(suffix) + "." + sanitize_id_part(name)
    if len(candidate) > 120:
        candidate = candidate[:113] + "." + _short_hash(candidate)
    return candidate


def _component_kind(container):
    if container["kind"] == "interface":
        return "interface"
    if container["kind"] == "enum":
        return "enum"
    return "class"


def _language_of(rel_path):
    return SOURCE_EXTENSIONS.get(os.path.splitext(rel_path)[1].lower())


def _uml_lang_for(rel_path, requested):
    extension = os.path.splitext(rel_path)[1].lower()
    if extension == ".py":
        return None if requested == "ts" else "py"
    if extension in TS_EXTENSIONS:
        return None if requested == "py" else "ts"
    return None


def write_ndjson(path, records):
    """`--emit-ops` cannot go through `deliver()` / `write_out()`: those only
    know how to `json.dump` a single object."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def cmd_scan_uml(args):
    root = os.path.abspath(args.root)
    target = os.path.abspath(os.path.join(root, args.path))
    if not os.path.exists(target):
        fail("path not found: %s" % to_posix(args.path))
    if args.emit_ops and not args.module:
        usage_error("scan-uml --emit-ops requires --module <moduleId>")
    if args.emit_ops and not args.out:
        usage_error("scan-uml --emit-ops requires --out <file.ndjson>")

    excludes = load_excludes(args.root)
    opts = {"exported_only": bool(args.exported_only), "public_only": bool(args.public_only)}
    containers = []
    warnings = []
    languages = set()
    files_scanned = 0
    truncated = False

    for file_path, rel in iter_source_files(root, target, excludes):
        lang = _uml_lang_for(rel, args.lang)
        if lang is None:
            continue
        try:
            size = os.path.getsize(file_path)
        except OSError:
            continue
        if size > SCAN_MAX_FILE_BYTES:
            # A skip that nobody can see is indistinguishable from "this file
            # has no classes" (No silent caps).
            warnings.append({"code": "FILE_TOO_LARGE", "file": rel, "bytes": size})
            continue
        text = read_text(file_path)
        if text is None:
            continue
        files_scanned += 1
        found, file_warnings = extract_ts(text, rel, opts) if lang == "ts" else extract_py(text, rel, opts)
        language = _language_of(rel)
        if language:
            languages.add(language)
        warnings.extend(file_warnings)
        for container in found:
            if len(container["attributes"]) + len(container["methods"]) < args.min_members:
                continue
            containers.append(container)
        if len(containers) >= args.limit:
            truncated = True
            break

    total_containers = len(containers)
    containers.sort(key=lambda c: (
        0 if c["exported"] else 1,
        -(len(c["attributes"]) + len(c["methods"])),
        c["name"],
    ))
    cap = max(1, args.max_containers)
    kept = containers[:cap]
    omitted = total_containers - len(kept)

    truncated_members = 0
    for container in kept:
        budget = UML_MAX_MEMBERS - len(container["attributes"])
        if budget < 0:
            truncated_members += -budget
            del container["attributes"][UML_MAX_MEMBERS:]
            budget = 0
        if len(container["methods"]) > budget:
            truncated_members += len(container["methods"]) - budget
            del container["methods"][budget:]

    members = sum(len(c["attributes"]) + len(c["methods"]) for c in kept)
    extraction = "ast" if languages == {"Python"} else "structural"
    language_label = ", ".join(sorted(languages)) if languages else "unknown"

    if not args.emit_ops:
        deliver(args, {
            "success": True,
            "command": "scan-uml",
            "path": to_posix(args.path),
            "extraction": extraction,
            "language": language_label,
            "counts": {"files": files_scanned, "containers": len(kept), "members": members},
            "omittedContainers": omitted,
            "truncatedMembers": truncated_members,
            "truncated": truncated,
            "containers": kept,
            "unresolvedHeritage": [],
            "warnings": warnings[:50],
        })

    by_name = {}
    for container in kept:
        by_name.setdefault(container["name"], build_component_id(args.module, container["name"]))

    ops = []
    unresolved = []
    for container in kept:
        component_id = by_name[container["name"]]
        ops.append(prune({
            "op": "add-component",
            "id": component_id,
            "module": args.module,
            "name": container["name"],
            "kind": _component_kind(container),
            "file": container["file"],
            "line": container["line"],
            "abstract": True if container["abstract"] else None,
            "summary": container.get("docFirstLine"),
            "provenance": "extracted",
        }))
        for attribute in container["attributes"]:
            ops.append(prune({
                "op": "add-member",
                "component": component_id,
                "memberKind": "field",
                "name": attribute["name"],
                # `or None` so a 0 (unknown) is pruned rather than published as
                # a line number that would send every click to the file header.
                "line": attribute.get("line") or None,
                "type": attribute.get("type"),
                "visibility": attribute.get("visibility"),
                "static": True if attribute.get("static") else None,
                "readonly": True if attribute.get("readonly") else None,
                "provenance": "extracted",
            }))
        for method in container["methods"]:
            ops.append(prune({
                "op": "add-member",
                "component": component_id,
                "memberKind": "method",
                "name": method["name"],
                "line": method.get("line") or None,
                "signature": method.get("signature"),
                "visibility": method.get("visibility"),
                "static": True if method.get("static") else None,
                "abstract": True if method.get("abstract") else None,
                "async": True if method.get("async") else None,
                "provenance": "extracted",
            }))
        for kind, bases in (("extends", container["extends"]), ("implements", container["implements"])):
            for base in bases:
                target_id = by_name.get(base)
                if target_id is None:
                    if len(unresolved) < 50:
                        unresolved.append({
                            "from": container["name"], "to": base,
                            "file": container["file"], "line": container["line"],
                        })
                    # Never emit a dangling relation: normalization drops it and
                    # bumps `droppedRelations`, turning a real health metric into
                    # noise.
                    continue
                ops.append({
                    "op": "add-relation",
                    "from": component_id,
                    "to": target_id,
                    "kind": kind,
                    "evidence": ["%s:%d" % (container["file"], container["line"])],
                    "provenance": "extracted",
                })

    write_ndjson(args.out, ops)
    emit({
        "success": True,
        "command": "scan-uml",
        "out": to_posix(args.out),
        "emitOps": True,
        "extraction": extraction,
        "language": language_label,
        "counts": {"files": files_scanned, "containers": len(kept), "members": members, "ops": len(ops)},
        "omittedContainers": omitted,
        "truncatedMembers": truncated_members,
        "truncated": truncated,
        "unresolvedHeritage": unresolved,
        "warnings": warnings[:50],
    })


# --------------------------------------------------------------------------
# Authoring
# --------------------------------------------------------------------------

HISTORY_NAME_RE = re.compile(r"^graph-(\d{10,16})\.json$")


def _history_dir(out_path):
    return os.path.join(os.path.dirname(os.path.abspath(out_path)), HISTORY_DIR_NAME)


def _history_stamp(out_path):
    """(stamp_ms, source) for the artifact currently on disk.

    Prefer what the ARTIFACT says about ITSELF. Using the file's mtime instead
    is wrong twice over: `cmd_finalize` derives `generatedAt` from the DRAFT's
    mtime, so the two numbers are never equal (the artifact is written later);
    and `graph.json` is committed, so one `git checkout` rewrites its mtime and
    the same artifact gets a brand-new snapshot name - which also defeats the
    idempotent skip and stores it twice.

    Falling back to mtime is an acceptable degradation, but it MUST leave a
    trace in the output (`historyStampSource`), otherwise nobody can tell what
    the number in the filename means.
    """
    try:
        with open(out_path, "r", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
        stamp = data.get("generatedAt")
        if isinstance(stamp, int) and not isinstance(stamp, bool) \
                and 10 ** 9 <= stamp <= 9999999999999999:
            return stamp, "generatedAt"
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return int(os.path.getmtime(out_path) * 1000), "mtime"
    except OSError:
        return None, None


def _copy_file(src, dst):
    """Chunked copy via a temp file + os.replace.

    Deliberately NOT `shutil`: the asset-shape test pins a hardcoded import
    whitelist, and growing the stdlib surface of a file that ships inside the
    installer is not worth saving four lines.
    """
    handle, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(dst) or ".")
    try:
        with os.fdopen(handle, "wb") as out:
            with open(src, "rb") as source:
                while True:
                    chunk = source.read(HISTORY_COPY_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
        os.replace(tmp, dst)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _prune_history(directory):
    """Newest HISTORY_KEEP files AND at most HISTORY_MAX_BYTES, in that order."""
    items = []
    for name in os.listdir(directory):
        match = HISTORY_NAME_RE.match(name)
        if not match:
            continue
        full = os.path.join(directory, name)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        items.append((int(match.group(1)), full, size))
    items.sort(key=lambda row: row[0], reverse=True)
    for _stamp, full, _size in items[HISTORY_KEEP:]:
        try:
            os.unlink(full)
        except OSError:
            pass
    keep = items[:HISTORY_KEEP]
    total = 0
    for row in keep:
        total += row[2]
    for _stamp, full, size in reversed(keep):
        if total <= HISTORY_MAX_BYTES:
            break
        try:
            os.unlink(full)
        except OSError:
            break
        total -= size


def rotate_history(out_path):
    """Copy the artifact that is about to be replaced into `graph-history/`.

    Returns `(rotated, stamp_source)`.

    ⚠️ Rotation NEVER blocks a publish. A read-only `.claude-index/`, a full
    disk, an antivirus holding a lock, a corrupt previous artifact - none of
    those should cost the user an index run that has already completed AND
    passed verification. Every failure degrades to `(False, None)` and is
    reported as `historyRotated: false`.
    """
    try:
        if not os.path.isfile(out_path):
            return False, None
        stamp, source = _history_stamp(out_path)
        if stamp is None:
            return False, None
        directory = _history_dir(out_path)
        os.makedirs(directory, exist_ok=True)
        # Self-ignoring, exactly like `write_agentmesh_gitignore`. The working
        # directory is the USER's repository and `.claude-index/` is committed:
        # snapshots are a local by-product and have to keep themselves out of
        # git without ever touching the repository-root .gitignore.
        gitignore = os.path.join(directory, ".gitignore")
        if not os.path.isfile(gitignore):
            # `newline=""` disables universal-newline translation, so the file is
            # byte-identical on Windows and POSIX. Without it Python writes CRLF
            # here, and a byte-level assertion on the content fails on one OS only.
            with open(gitignore, "w", encoding="utf-8", newline="") as handle:
                handle.write("*\n")
        target = os.path.join(directory, "graph-%d.json" % stamp)
        if not os.path.isfile(target):
            _copy_file(out_path, target)
        _prune_history(directory)
        return True, source
    except (OSError, ValueError):
        return False, None


def seed_from_published(path, project_name, root):
    """Build a draft from an already published graph (round 3, W3).

    ⚠️ `verification`, `sourceManifest`, `generatedAt` and `generator` are
    STRIPPED. They describe the PREVIOUS publish - the previous verification
    moment and the previous source fingerprints. Carrying them into a fresh
    draft means one `finalize --no-verify` re-stamps an OLD "verified" badge
    onto a NEW graph, when `skipped: true` is supposed to be the only honest
    marker for that case. This is the one path in the whole feature that could
    manufacture evidence out of nothing.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
    except OSError as err:
        fail("could not read --from-published: %s" % err, path=to_posix(path))
        return None
    except ValueError as err:
        fail("--from-published is not valid JSON: %s" % err, path=to_posix(path))
        return None
    if not isinstance(data, dict):
        fail("--from-published is not a graph document", path=to_posix(path))
        return None
    published_project = data.get("project") if isinstance(data.get("project"), dict) else {}
    draft = empty_draft(project_name or clip(published_project.get("name"), MAX_NAME) or "",
                        to_posix(root) or ".")
    draft["project"]["languages"] = published_project.get("languages") or []
    draft["project"]["indexVersion"] = published_project.get("indexVersion")
    for key in ("modules", "components", "relations"):
        value = data.get(key)
        draft[key] = value if isinstance(value, list) else []
    if isinstance(data.get("truncation"), dict):
        draft["truncation"] = data["truncation"]
    return draft


def cmd_init(args):
    existed = os.path.isfile(DRAFT_PATH)
    from_published = getattr(args, "from_published", None)
    if existed and not args.force:
        # A draft in hand always wins: `--from-published` is the rescue path for
        # "the draft is gone", not a way to silently discard work in progress.
        draft = load_draft()
        write_agentmesh_gitignore()
        emit({
            "success": True, "command": "init", "created": False, "resumed": True,
            "path": DRAFT_PATH, "counts": counts(draft),
        })
    seeded_from = None
    if from_published:
        draft = seed_from_published(from_published, args.project_name, args.root)
        seeded_from = to_posix(from_published)
    else:
        draft = empty_draft(args.project_name or "", to_posix(args.root) or ".")
    save_draft(draft)
    write_agentmesh_gitignore()
    payload = {
        "success": True, "command": "init", "created": True, "resumed": False,
        "path": DRAFT_PATH, "counts": counts(draft),
    }
    if seeded_from:
        payload["seededFrom"] = seeded_from
    emit(payload)


def write_agentmesh_gitignore():
    """The working directory is the USER's repository - nobody wrote `.agentmesh/`
    into their .gitignore for us. Drop a self-ignoring file instead of touching
    the repository root .gitignore. Idempotent, best effort."""
    try:
        os.makedirs(".agentmesh", exist_ok=True)
        path = os.path.join(".agentmesh", ".gitignore")
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("*\n")
    except OSError:
        pass


def upsert(collection, record, key="id"):
    for index, existing in enumerate(collection):
        if existing.get(key) == record.get(key):
            collection[index] = record
            return "updated"
    collection.append(record)
    return "created"


def build_module(data):
    module_id = clip(data.get("id"), 120)
    if not module_id or not ID_RE.match(module_id):
        fail("invalid or missing --id (allowed: A-Z a-z 0-9 . _ : -)", value=data.get("id"))
    path = to_posix(data.get("path"))
    if not path:
        fail("--path is required", id=module_id)
    metrics = prune({"files": as_int(data.get("files")), "loc": as_int(data.get("loc"))})
    return prune({
        "id": module_id,
        "name": clip(data.get("name"), MAX_NAME) or module_id,
        "path": path,
        "layer": enum_or(data.get("layer"), LAYERS, "other"),
        "kind": enum_or(data.get("kind"), MODULE_KINDS, "package"),
        "parentId": clip(data.get("parent") or data.get("parentId"), 120),
        "summary": clip(data.get("summary"), MAX_SUMMARY),
        "tags": split_list(data.get("tags"), MAX_TAGS, 32),
        "entryPoints": split_list(data.get("entry") or data.get("entryPoints"), MAX_TAGS, 400),
        "metrics": metrics or None,
    })


def build_component(data):
    component_id = clip(data.get("id"), 120)
    if not component_id or not ID_RE.match(component_id):
        fail("invalid or missing --id (allowed: A-Z a-z 0-9 . _ : -)", value=data.get("id"))
    module_id = clip(data.get("module") or data.get("moduleId"), 120)
    if not module_id:
        fail("--module is required", id=component_id)
    return prune({
        "id": component_id,
        "moduleId": module_id,
        "name": clip(data.get("name"), MAX_NAME) or component_id,
        "kind": enum_or(data.get("kind"), COMPONENT_KINDS, "class"),
        "stereotype": clip(data.get("stereotype"), 40),
        "file": to_posix(data.get("file")),
        "line": as_int(data.get("line")),
        "visibility": enum_or(data.get("visibility"), VISIBILITIES, None),
        "abstract": as_bool(data.get("abstract")),
        "summary": clip(data.get("summary"), MAX_SUMMARY),
        "tags": split_list(data.get("tags"), MAX_TAGS, 32),
        # Whitelist rebuild: a key that is not listed here is DROPPED. Missing
        # `provenance` is a silent chain - no badge, the "extracted only" filter
        # empties the graph, verification reports `extracted: 0`, and finalize's
        # hard gate (which keys off exactly this field) never fires.
        "provenance": enum_or(data.get("provenance"), PROVENANCES, None),
    })


def build_member(data):
    name = clip(data.get("name"), MAX_NAME)
    if not name:
        fail("--name is required for add-member")
    return prune({
        "name": name,
        # Whitelist rebuild: a key not listed here is DROPPED, silently. Omitting
        # "line" does not raise - it just makes every member's line number vanish
        # from the artifact, so clicking a method name in the graph always jumps
        # to the top of the file (same trap as `provenance` in round 2).
        "line": as_int(data.get("line")),
        "type": clip(data.get("type"), MAX_TYPE),
        "signature": clip(data.get("signature"), MAX_SIGNATURE),
        "visibility": enum_or(data.get("visibility"), VISIBILITIES, None),
        "static": as_bool(data.get("static")),
        "abstract": as_bool(data.get("abstract")),
        "async": as_bool(data.get("async")),
        "readonly": as_bool(data.get("readonly")),
        "provenance": enum_or(data.get("provenance"), PROVENANCES, None),
    })


def build_relation(data):
    source = clip(data.get("from"), 120)
    target = clip(data.get("to"), 120)
    if not source or not target:
        fail("--from and --to are required for add-relation")
    kind = clip(data.get("kind"), 40)
    if kind not in RELATION_KINDS:
        fail("invalid --kind for add-relation", value=kind, allowed=list(RELATION_KINDS))
    return prune({
        "from": source,
        "to": target,
        "kind": kind,
        "label": clip(data.get("label"), MAX_LABEL),
        "fromCardinality": clip(data.get("fromCard") or data.get("fromCardinality"), 12),
        "toCardinality": clip(data.get("toCard") or data.get("toCardinality"), 12),
        "weight": as_int(data.get("weight")),
        "evidence": split_list(data.get("evidence"), MAX_EVIDENCE, 400),
        "provenance": enum_or(data.get("provenance"), PROVENANCES, None),
    })


def apply_op(draft, op_name, data):
    """Apply one operation to the draft. Returns a short result dict."""
    if op_name == "add-module":
        record = build_module(data)
        action = upsert(draft["modules"], record)
        return {"op": op_name, "id": record["id"], "action": action}
    if op_name == "add-component":
        record = build_component(data)
        action = upsert(draft["components"], record)
        return {"op": op_name, "id": record["id"], "action": action}
    if op_name == "add-member":
        component_id = clip(data.get("component") or data.get("componentId"), 120)
        if not component_id:
            fail("--component is required for add-member")
        member_kind = clip(data.get("memberKind") or data.get("member_kind"), 20)
        if member_kind not in ("field", "method"):
            fail("--member-kind must be `field` or `method`", value=member_kind)
        target = next((c for c in draft["components"] if c.get("id") == component_id), None)
        if target is None:
            fail("component not found: %s" % component_id)
        bucket_key = "attributes" if member_kind == "field" else "methods"
        bucket = target.setdefault(bucket_key, [])
        member = build_member(data)
        action = upsert(bucket, member, key="name")
        if len(bucket) > MAX_MEMBERS:
            dropped = len(bucket) - MAX_MEMBERS
            del bucket[MAX_MEMBERS:]
            draft["truncation"]["members"] += dropped
        return {"op": op_name, "component": component_id, "member": member["name"], "action": action}
    if op_name == "add-relation":
        record = build_relation(data)
        for index, existing in enumerate(draft["relations"]):
            if (existing.get("from"), existing.get("to"), existing.get("kind")) == (
                record["from"], record["to"], record["kind"]
            ):
                draft["relations"][index] = record
                return {"op": op_name, "action": "updated"}
        draft["relations"].append(record)
        return {"op": op_name, "action": "created"}
    if op_name == "remove":
        return remove_entity(draft, clip(data.get("id"), 120), clip(data.get("kind"), 20))
    fail("unknown op: %s" % op_name)
    return {}


def remove_entity(draft, entity_id, kind):
    if not entity_id:
        fail("--id is required for remove")
    removed = {"modules": 0, "components": 0, "relations": 0}
    if kind in (None, "module"):
        before = len(draft["modules"])
        draft["modules"] = [m for m in draft["modules"] if m.get("id") != entity_id]
        removed["modules"] = before - len(draft["modules"])
        if removed["modules"]:
            # Cascade: components belonging to the module, then every relation
            # touching any of them.
            orphan_ids = {c["id"] for c in draft["components"] if c.get("moduleId") == entity_id}
            draft["components"] = [c for c in draft["components"] if c.get("moduleId") != entity_id]
            removed["components"] += len(orphan_ids)
            gone = orphan_ids | {entity_id}
            before_rel = len(draft["relations"])
            draft["relations"] = [
                r for r in draft["relations"] if r.get("from") not in gone and r.get("to") not in gone
            ]
            removed["relations"] += before_rel - len(draft["relations"])
    if kind in (None, "component"):
        before = len(draft["components"])
        draft["components"] = [c for c in draft["components"] if c.get("id") != entity_id]
        dropped = before - len(draft["components"])
        removed["components"] += dropped
        if dropped:
            before_rel = len(draft["relations"])
            draft["relations"] = [
                r for r in draft["relations"] if r.get("from") != entity_id and r.get("to") != entity_id
            ]
            removed["relations"] += before_rel - len(draft["relations"])
    if kind == "relation":
        before_rel = len(draft["relations"])
        draft["relations"] = [
            r for r in draft["relations"] if r.get("from") != entity_id and r.get("to") != entity_id
        ]
        removed["relations"] += before_rel - len(draft["relations"])
    return {"op": "remove", "id": entity_id, "removed": removed}


def cmd_add(op_name, args):
    draft = load_draft()
    result = apply_op(draft, op_name, vars(args))
    enforce_caps(draft)
    save_draft(draft)
    result["success"] = True
    result["counts"] = counts(draft)
    emit(result)


def cmd_remove(args):
    draft = load_draft()
    result = remove_entity(draft, clip(args.id, 120), args.kind)
    save_draft(draft)
    result["success"] = True
    result["counts"] = counts(draft)
    emit(result)


def cmd_apply(args):
    if not args.stdin and not args.file:
        usage_error("apply requires --file <path> or --stdin")
    if args.stdin:
        raw = sys.stdin.read()
    else:
        if not os.path.isfile(args.file):
            fail("ops file not found: %s" % to_posix(args.file))
        raw = read_text(args.file) or ""

    draft = load_draft()
    applied = 0
    errors = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#") or text.startswith("//"):
            continue
        try:
            data = json.loads(text)
        except ValueError as err:
            errors.append({"line": lineno, "error": "invalid JSON: %s" % err})
            continue
        if not isinstance(data, dict):
            errors.append({"line": lineno, "error": "each line must be a JSON object"})
            continue
        op_name = data.get("op")
        if not op_name:
            errors.append({"line": lineno, "error": "missing `op`"})
            continue
        try:
            apply_op(draft, op_name, data)
            applied += 1
        except SystemExit:
            # apply_op called fail() -> SystemExit. Record and keep going so one
            # bad line never throws away a whole batch.
            errors.append({"line": lineno, "error": "operation rejected", "op": op_name})
        except Exception as err:  # noqa: BLE001
            errors.append({"line": lineno, "error": str(err), "op": op_name})

    enforce_caps(draft)
    save_draft(draft)
    emit({
        "success": True, "command": "apply", "applied": applied,
        "errors": errors[:20], "errorCount": len(errors), "counts": counts(draft),
    })


def enforce_caps(draft):
    """Trim to the caps and record what was dropped. Never silent (No silent caps)."""
    trunc = draft["truncation"]
    for key, cap in (("modules", MAX_MODULES), ("components", MAX_COMPONENTS), ("relations", MAX_RELATIONS)):
        overflow = len(draft[key]) - cap
        if overflow > 0:
            del draft[key][cap:]
            trunc[key] += overflow


def cmd_list(args):
    draft = load_draft()
    if args.kind == "modules":
        items = draft["modules"]
    elif args.kind == "components":
        items = draft["components"]
        if args.module:
            items = [c for c in items if c.get("moduleId") == args.module]
    else:
        items = draft["relations"]
    emit({
        "success": True, "command": "list", "kind": args.kind,
        "total": len(items), "items": items[: args.limit],
    })


def cmd_stats(args):
    draft = load_draft()
    current = counts(draft)
    emit({
        "success": True, "command": "stats", "counts": current,
        "caps": {
            "modules": MAX_MODULES, "components": MAX_COMPONENTS,
            "relations": MAX_RELATIONS, "membersPerComponent": MAX_MEMBERS,
        },
        "remaining": {
            "modules": max(0, MAX_MODULES - current["modules"]),
            "components": max(0, MAX_COMPONENTS - current["components"]),
            "relations": max(0, MAX_RELATIONS - current["relations"]),
        },
        "truncation": draft["truncation"],
    })


# --------------------------------------------------------------------------
# Verification: check the draft against the bytes on disk
# --------------------------------------------------------------------------
#
# `validate` never opens a source file: it checks ids, caps and dangling
# references. That leaves the most damaging class of defect completely
# unguarded - a component can claim `server/services/foo.ts:96` for a file that
# does not exist, and the whole pipeline stays green. `verify` closes that gap.
#
# It checks POSITION EXISTENCE ONLY (D13): the file is there, the line is in
# range, the declaration carries the name. It deliberately does not try to
# confirm that line 412 really says `extends` - that is unreliable across
# languages, and a verification mechanism nobody trusts is worth less than none.

HARD_VERIFY_CODES = ("FILE_MISSING", "NAME_NOT_IN_FILE", "EVIDENCE_MISSING")


def empty_verification_counts():
    return {"total": 0, "extracted": 0, "asserted": 0,
            "checked": 0, "confirmed": 0, "repaired": 0, "mismatched": 0}


def _census(records, counts):
    for record in records:
        counts["total"] += 1
        provenance = record.get("provenance")
        if provenance == "extracted":
            counts["extracted"] += 1
        elif provenance == "asserted":
            counts["asserted"] += 1


def empty_manifest():
    """Accumulator for the source fingerprint manifest (round 3, W1).

    `entries` is a dict rather than a list because `_read_lines_cached`'s LRU
    evicts, so the manifest can NEVER be harvested from that cache afterwards -
    it has to be written at the moment the bytes are in hand (invariant: see
    the `manifest is not None` branch below).

    `seen` records every path this run actually processed, whatever the outcome.
    It is what lets `manifest_truncated()` tell "we looked and it was gone" apart
    from "we never got to it" - and only the latter is `truncated`.
    """
    return {"entries": {}, "seen": set(), "skipped": 0, "rejected": 0}


def _record_manifest(manifest, rel, info, raw):
    """Only `kind == "ok"` files get an entry.

    A "missing" (absent OR unreadable) or "too_large" file counts as `skipped`
    and MUST NOT be smuggled in with an empty hash: the server would read that
    as a genuine `changed`.
    """
    if manifest is None:
        return
    if len(manifest["entries"]) >= MANIFEST_MAX_ENTRIES:
        manifest["rejected"] += 1
        return
    manifest["entries"][rel] = {
        "path": rel,
        "size": int(info.st_size),
        "mtime": int(info.st_mtime * 1000),
        "hash": hash_source_bytes(raw),
    }


def _read_lines_cached(cache, order, root, rel, budget, manifest=None):
    """LRU-cached `(kind, lines)` for one repo-relative path.

    Returns None once the file-read budget is exhausted; the caller stops
    checking and reports `budgetExhausted`, because a truncated check reported
    as a complete one is exactly the kind of quiet lie this command exists to
    remove.

    Round 3: this is also where the source manifest is built. One `os.stat`
    yields both size and mtime (one syscall, not two), and the bytes we already
    have to read are hashed on the spot - so the manifest costs a sha256 and
    nothing else. Harvesting it from `cache` afterwards is impossible: the LRU
    above evicts.
    """
    if rel in cache:
        return cache[rel]
    if budget["read"] >= budget["max"]:
        budget["exhausted"] = True
        return None
    full = os.path.join(root, rel.replace("/", os.sep))
    try:
        info = os.stat(full)
    except OSError:
        entry = ("missing", [])
        if manifest is not None:
            manifest["skipped"] += 1
    else:
        if info.st_size > VERIFY_MAX_FILE_BYTES:
            entry = ("too_large", [])
            if manifest is not None:
                manifest["skipped"] += 1
        else:
            raw = read_bytes(full)
            if raw is None:
                entry = ("missing", [])
                if manifest is not None:
                    manifest["skipped"] += 1
            else:
                # `split("\n")`, NOT `splitlines()`. The extractor numbers lines
                # with `build_line_starts`, which only breaks on "\n";
                # `splitlines()` additionally breaks on VT(0x0b), FF(0x0c),
                # FS/GS/RS, NEL(0x85), LS(U+2028) and PS(U+2029). Any source file
                # containing a form feed - generated code, some lint configs,
                # plenty of legacy C - therefore made `lines[line-1]` read the
                # WRONG line, which reports NAME_NOT_AT_LINE on an
                # `extracted` record, which is a HARD_VERIFY_CODE, which makes
                # `finalize` refuse to publish and blame the extractor.
                # A trailing "\r" is harmless to `re.search(name)`.
                entry = ("ok", decode_source(raw).split("\n"))
                _record_manifest(manifest, rel, info, raw)
    budget["read"] += 1
    if manifest is not None:
        manifest["seen"].add(rel)
    cache[rel] = entry
    order.append(rel)
    if len(order) > VERIFY_CACHE_FILES:
        cache.pop(order.pop(0), None)
    return entry


def _referenced_paths(draft):
    """Every repo-relative path `run_verify` would try to open, in order.

    The filters MUST stay identical to the ones in the verification loops: this
    set is the denominator for `truncated`, and a denominator that counts files
    the loops never wanted would report phantom truncation.
    """
    out = []
    seen = set()
    for component in draft.get("components", []):
        rel = component.get("file")
        line = component.get("line")
        name = str(component.get("name") or "")
        if not rel or not isinstance(line, int) or line <= 0 or not name:
            continue
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    for relation in draft.get("relations", []):
        for item in relation.get("evidence") or []:
            text = str(item)
            head, sep, tail = text.rpartition(":")
            if not sep or not head or not tail.isdigit():
                continue
            rel = to_posix(head)
            if rel and rel not in seen:
                seen.add(rel)
                out.append(rel)
    return out


def finish_manifest(manifest, draft):
    """Freeze the accumulator into the shape that ships in `graph.json`.

    `truncated` absorbs BOTH sources (No silent caps):
      1. referenced files the read budget never reached, and
      2. entries rejected by MANIFEST_MAX_ENTRIES.
    The second term is 0 while the two constants are equal, but the code path
    must stay - it is the only place that will speak up if someone makes them
    differ.
    """
    if manifest is None:
        return None
    missed = 0
    for rel in _referenced_paths(draft):
        if rel not in manifest["seen"]:
            missed += 1
    entries = [manifest["entries"][key] for key in sorted(manifest["entries"])]
    return {
        "algo": SOURCE_HASH_ALGO,
        "builtAt": now_ms(),
        "entries": entries,
        "truncated": missed + manifest["rejected"],
        "skipped": manifest["skipped"],
    }


def _name_needle(name):
    """`\b`-anchored regex for `name`, but only where a boundary can exist.

    TypeScript private fields are named `#secret`, and `\b` between a space and
    `#` is never a word boundary, so the naive `r"\b" + escape(name) + r"\b"`
    NEVER matches them. Extended from components (whose names are always
    identifiers) to members (which are not), that turns every `#private` field
    into a phantom mismatch — and on an `extracted` record a phantom mismatch is
    a finding on the publish path.
    """
    prefix = r"\b" if (name[:1].isalnum() or name[:1] == "_") else ""
    suffix = r"\b" if (name[-1:].isalnum() or name[-1:] == "_") else ""
    return re.compile(prefix + re.escape(name) + suffix)


def _find_member_line(lines, name):
    """First line that mentions `name`, for MEMBERS.

    `_find_declaration_line` additionally requires the line to look like a
    top-level declaration (CONTAINER_RE / SYMBOL_PATTERNS), and a class member
    never does - `  run(): void {}` matches none of those patterns. Reusing it
    for members makes every member fallback return None, so `--fix-lines`
    silently repairs nothing while still reporting a finding.
    """
    needle = _name_needle(name)
    for index, line in enumerate(lines, start=1):
        if len(line) > 600:
            continue
        if needle.search(line):
            return index
    return None


def _find_declaration_line(lines, name):
    """First line that both mentions `name` and looks like a declaration."""
    needle = _name_needle(name)
    for index, line in enumerate(lines, start=1):
        if len(line) > 600 or not needle.search(line):
            continue
        if CONTAINER_RE.search(line):
            return index
        for _kind, pattern in SYMBOL_PATTERNS:
            if pattern.match(line):
                return index
    return None


def _add_finding(findings, overflow, record):
    if len(findings) >= MAX_FINDINGS:
        overflow[0] += 1
        return
    record["detail"] = clip(record.get("detail"), MAX_FINDING_DETAIL) or ""
    findings.append(record)


def _verify_member_lines(component, lines, rel, findings, overflow, counts,
                         member_budget, fix_lines):
    """Re-check every member's `line` against the file we already have open.

    Findings are folded into the COMPONENT counts on purpose: opening a third
    counter set would force every existing `GraphVerificationCounts` assertion
    to change for zero gain.

    Two things here are load-bearing:

    1. **The O(1) fast path runs first.** `_find_declaration_line` scans the
       whole file with a regex; on components it only ran on the rare failure
       path, but there can be 80 members per component and 6000 components.
       The fallback is therefore capped GLOBALLY by MEMBER_LOOKUP_BUDGET, and
       once that is spent the remaining members are SKIPPED rather than counted
       `confirmed` - counting them confirmed is the exact lie this command
       exists to remove.

    2. **Member findings carry a `member` key**, and `cmd_finalize`'s hard gate
       skips anything that has one. `NAME_NOT_IN_FILE` is a HARD_VERIFY_CODE,
       and members reach places components never do (constructor parameter
       properties, decorated Python properties, computed names). Letting a
       single odd member block publishing would turn "a graph with one stale
       line number" into "no graph at all" - the same trade `finalize` already
       resolved for `asserted` records. The key is dropped by the TypeScript
       whitelist rebuild, so it never reaches the wire.
    """
    for bucket in ("attributes", "methods"):
        for member in component.get(bucket) or []:
            if not isinstance(member, dict):
                continue
            line = member.get("line")
            name = str(member.get("name") or "")
            if not name or not isinstance(line, int) or line <= 0:
                continue
            if member_budget["skipped"]:
                continue
            cid = "%s#%s" % (component.get("id") or "", name)
            provenance = member.get("provenance")
            short = name.split(".")[-1]
            counts["checked"] += 1
            if line <= len(lines) and _name_needle(short).search(lines[line - 1]):
                counts["confirmed"] += 1
                continue
            if member_budget["used"] >= member_budget["max"]:
                # Budget just ran out on THIS member: it has not been checked,
                # so un-count it and stop looking at the rest.
                counts["checked"] -= 1
                member_budget["skipped"] = True
                member_budget["exhausted"] = True
                continue
            member_budget["used"] += 1
            suggested = _find_member_line(lines, short)
            if suggested is not None and fix_lines:
                member["line"] = suggested
                counts["repaired"] += 1
                member_budget["repaired"] += 1
            else:
                counts["mismatched"] += 1
            code = "LINE_OUT_OF_RANGE" if line > len(lines) else "NAME_NOT_AT_LINE"
            detail = ("%s has %d lines, %s claims line %d" % (rel, len(lines), name, line)
                      if code == "LINE_OUT_OF_RANGE"
                      else "%s is not declared at line %d of %s" % (name, line, rel))
            record = {
                "code": code, "entity": "component", "id": cid,
                "provenance": provenance, "detail": detail, "member": name,
            }
            if suggested is not None:
                record["suggestedLine"] = suggested
            _add_finding(findings, overflow, record)


def run_verify(draft, root=".", fix_lines=False, drop_mismatched=False,
               max_files=VERIFY_MAX_FILES, want_manifest=False,
               member_lookup_budget=MEMBER_LOOKUP_BUDGET):
    """Returns (verification, repaired, dropped, files_read, budget_exhausted, manifest)."""
    root = os.path.abspath(root)
    cache = {}
    order = []
    budget = {"read": 0, "max": max(1, int(max_files)), "exhausted": False}
    manifest = empty_manifest() if want_manifest else None
    member_budget = {"used": 0, "max": max(0, int(member_lookup_budget)),
                     "skipped": False, "exhausted": False, "repaired": 0}
    findings = []
    overflow = [0]

    component_counts = empty_verification_counts()
    relation_counts = empty_verification_counts()
    _census(draft.get("components", []), component_counts)
    _census(draft.get("relations", []), relation_counts)

    repaired = 0
    drop_component_ids = set()
    drop_relation_keys = set()

    for component in draft.get("components", []):
        rel = component.get("file")
        line = component.get("line")
        name = str(component.get("name") or "")
        cid = str(component.get("id") or "")
        provenance = component.get("provenance")
        if not rel or not isinstance(line, int) or line <= 0 or not name:
            continue
        entry = _read_lines_cached(cache, order, root, rel, budget, manifest)
        if entry is None:
            break
        kind, lines = entry
        if kind == "too_large":
            _add_finding(findings, overflow, {
                "code": "SKIPPED_TOO_LARGE", "entity": "component", "id": cid,
                "provenance": provenance, "detail": "%s is larger than the verification limit" % rel,
            })
            continue
        component_counts["checked"] += 1
        if kind == "missing":
            component_counts["mismatched"] += 1
            drop_component_ids.add(cid)
            _add_finding(findings, overflow, {
                "code": "FILE_MISSING", "entity": "component", "id": cid,
                "provenance": provenance, "detail": "%s does not exist" % rel,
            })
            continue
        _verify_member_lines(component, lines, rel, findings, overflow,
                             component_counts, member_budget, fix_lines)
        if line > len(lines):
            # Nested Python classes are recorded as `Outer.Inner`; only the last
            # segment ever appears on the declaration line.
            suggested = _find_declaration_line(lines, name.split(".")[-1])
            if suggested is not None and fix_lines:
                component["line"] = suggested
                component_counts["repaired"] += 1
                repaired += 1
            else:
                component_counts["mismatched"] += 1
            _add_finding(findings, overflow, {
                "code": "LINE_OUT_OF_RANGE", "entity": "component", "id": cid,
                "provenance": provenance,
                "detail": "%s has %d lines, %s claims line %d" % (rel, len(lines), name, line),
                "suggestedLine": suggested,
            })
            continue
        if _name_needle(name.split(".")[-1]).search(lines[line - 1]):
            component_counts["confirmed"] += 1
            continue
        suggested = _find_declaration_line(lines, name.split(".")[-1])
        if suggested is None:
            component_counts["mismatched"] += 1
            drop_component_ids.add(cid)
            _add_finding(findings, overflow, {
                "code": "NAME_NOT_IN_FILE", "entity": "component", "id": cid,
                "provenance": provenance,
                "detail": "%s has no declaration named %s" % (rel, name),
            })
            continue
        if fix_lines:
            component["line"] = suggested
            component_counts["repaired"] += 1
            repaired += 1
        else:
            component_counts["mismatched"] += 1
        _add_finding(findings, overflow, {
            "code": "NAME_NOT_AT_LINE", "entity": "component", "id": cid,
            "provenance": provenance,
            "detail": "%s is declared at line %d of %s, not %d" % (name, suggested, rel, line),
            "suggestedLine": suggested,
        })

    for relation in draft.get("relations", []):
        evidence = relation.get("evidence") or []
        if not evidence:
            continue
        key = (relation.get("from"), relation.get("to"), relation.get("kind"))
        rid = "%s->%s" % (relation.get("from"), relation.get("to"))
        provenance = relation.get("provenance")
        problems = 0
        bailed = False
        for item in evidence:
            text = str(item)
            head, sep, tail = text.rpartition(":")
            if not sep or not head or not tail.isdigit():
                problems += 1
                _add_finding(findings, overflow, {
                    "code": "EVIDENCE_MALFORMED", "entity": "relation", "id": rid,
                    "provenance": provenance, "detail": "%s is not `path:line`" % text,
                })
                continue
            entry = _read_lines_cached(cache, order, root, to_posix(head), budget, manifest)
            if entry is None:
                # Budget exhausted mid-relation. Counting it `confirmed` here
                # would report a check that never happened, which is the exact
                # class of quiet lie this command exists to remove.
                bailed = True
                break
            kind, lines = entry
            if kind == "too_large":
                continue
            if kind == "missing":
                problems += 1
                drop_relation_keys.add(key)
                _add_finding(findings, overflow, {
                    "code": "EVIDENCE_MISSING", "entity": "relation", "id": rid,
                    "provenance": provenance, "detail": "%s does not exist" % head,
                })
                continue
            if int(tail) > len(lines) or int(tail) <= 0:
                problems += 1
                _add_finding(findings, overflow, {
                    "code": "EVIDENCE_OUT_OF_RANGE", "entity": "relation", "id": rid,
                    "provenance": provenance,
                    "detail": "%s has %d lines, evidence cites %s" % (head, len(lines), tail),
                })
        if not bailed:
            relation_counts["checked"] += 1
            if problems:
                relation_counts["mismatched"] += 1
            else:
                relation_counts["confirmed"] += 1
        if budget["exhausted"]:
            break

    dropped = 0
    if drop_mismatched:
        for cid in sorted(drop_component_ids):
            remove_entity(draft, cid, "component")
            dropped += 1
        if drop_relation_keys:
            before = len(draft.get("relations", []))
            draft["relations"] = [
                r for r in draft.get("relations", [])
                if (r.get("from"), r.get("to"), r.get("kind")) not in drop_relation_keys
            ]
            dropped += before - len(draft["relations"])

    repaired += member_budget["repaired"]
    verification = {
        "verifiedAt": now_ms(),
        "skipped": False,
        "toolVersion": TOOL_VERSION,
        "components": component_counts,
        "relations": relation_counts,
        "findings": findings,
        "findingsTruncated": overflow[0],
    }
    if member_budget["exhausted"]:
        verification["memberLookupBudgetExhausted"] = True
    return (verification, repaired, dropped, budget["read"], budget["exhausted"],
            finish_manifest(manifest, draft))


def skipped_verification(draft):
    """The `--no-verify` receipt (invariant 9).

    A graph that skipped verification MUST look like one. Publishing it with a
    zeroed-but-normal-looking block would be indistinguishable from "verified
    and clean", which is the single strongest claim this feature makes.
    """
    component_counts = empty_verification_counts()
    relation_counts = empty_verification_counts()
    _census(draft.get("components", []), component_counts)
    _census(draft.get("relations", []), relation_counts)
    return {
        "verifiedAt": None,
        "skipped": True,
        "toolVersion": TOOL_VERSION,
        "components": component_counts,
        "relations": relation_counts,
        "findings": [],
        "findingsTruncated": 0,
    }


def cmd_verify(args):
    draft = load_draft()
    verification, repaired, dropped, files_read, exhausted, _manifest = run_verify(
        draft, args.root, bool(args.fix_lines), bool(args.drop_mismatched), args.max_files,
        False, args.member_budget,
    )
    draft["verification"] = verification
    save_draft(draft)
    hard = [f for f in verification["findings"] if f["code"] in HARD_VERIFY_CODES]
    payload = {
        "success": True,
        "command": "verify",
        "ok": not verification["findings"],
        "verification": {
            "verifiedAt": verification["verifiedAt"],
            "skipped": False,
            "toolVersion": TOOL_VERSION,
            "components": verification["components"],
            "relations": verification["relations"],
            "findings": verification["findings"][: args.limit],
            "findingsTruncated": verification["findingsTruncated"],
        },
        "hardFailures": len([f for f in hard if f.get("provenance") == "extracted"]),
        "repaired": repaired,
        "dropped": dropped,
        "filesRead": files_read,
        "budgetExhausted": exhausted,
        "memberLookupBudgetExhausted": bool(verification.get("memberLookupBudgetExhausted")),
    }
    if args.out:
        write_out(args.out, payload)
    # Always exit 0: `verify` reports, `finalize` gates. A gate that fails
    # unconditionally is a gate that gets bypassed on first use (D14, same
    # lesson as `validate --strict` and module cycles).
    emit(payload)


# --------------------------------------------------------------------------
# Sealing
# --------------------------------------------------------------------------

def run_validate(draft):
    errors = []
    quality = []
    info = []

    module_ids = set()
    for module in draft["modules"]:
        mid = module.get("id")
        if not mid or not ID_RE.match(str(mid)):
            errors.append({"code": "BAD_ID", "entity": "module", "id": mid})
            continue
        if mid in module_ids:
            errors.append({"code": "DUPLICATE_ID", "entity": "module", "id": mid})
            continue
        module_ids.add(mid)
        path = str(module.get("path") or "")
        if not path or path.startswith("/") or re.match(r"^[A-Za-z]:/", path) or ".." in path.split("/"):
            errors.append({"code": "PATH_ESCAPES_ROOT", "entity": "module", "id": mid, "path": path})
        if module.get("layer") not in LAYERS:
            errors.append({"code": "BAD_LAYER", "entity": "module", "id": mid})
        if not module.get("summary"):
            quality.append({"code": "MODULE_WITHOUT_SUMMARY", "id": mid})

    component_ids = set()
    per_module = {}
    for component in draft["components"]:
        cid = component.get("id")
        if not cid or not ID_RE.match(str(cid)):
            errors.append({"code": "BAD_ID", "entity": "component", "id": cid})
            continue
        if cid in component_ids or cid in module_ids:
            errors.append({"code": "DUPLICATE_ID", "entity": "component", "id": cid})
            continue
        component_ids.add(cid)
        module_id = component.get("moduleId")
        if module_id not in module_ids:
            errors.append({"code": "DANGLING_MODULE_REF", "entity": "component", "id": cid, "moduleId": module_id})
        else:
            per_module[module_id] = per_module.get(module_id, 0) + 1
        if component.get("kind") not in COMPONENT_KINDS:
            errors.append({"code": "BAD_COMPONENT_KIND", "id": cid})
        if not (component.get("attributes") or component.get("methods")):
            quality.append({"code": "COMPONENT_WITHOUT_MEMBERS", "id": cid})
        if not component.get("summary"):
            quality.append({"code": "COMPONENT_WITHOUT_SUMMARY", "id": cid})

    for module_id in module_ids:
        if per_module.get(module_id, 0) == 0:
            quality.append({"code": "EMPTY_MODULE", "id": module_id})

    known = module_ids | component_ids
    adjacency = {}
    isolated = set(known)
    for relation in draft["relations"]:
        source, target = relation.get("from"), relation.get("to")
        if relation.get("kind") not in RELATION_KINDS:
            errors.append({"code": "BAD_RELATION_KIND", "from": source, "to": target})
            continue
        if source not in known or target not in known:
            errors.append({"code": "DANGLING_RELATION_REF", "from": source, "to": target})
            continue
        isolated.discard(source)
        isolated.discard(target)
        if relation.get("kind") in EVIDENCE_REQUIRED and not relation.get("evidence"):
            quality.append({"code": "RELATION_WITHOUT_EVIDENCE", "from": source, "to": target, "kind": relation.get("kind")})
        source_module = module_of(draft, source)
        target_module = module_of(draft, target)
        if source_module and target_module and source_module != target_module:
            adjacency.setdefault(source_module, set()).add(target_module)

    if len(draft["modules"]) > MAX_MODULES:
        errors.append({"code": "OVER_CAP", "entity": "modules", "cap": MAX_MODULES})
    if len(draft["components"]) > MAX_COMPONENTS:
        errors.append({"code": "OVER_CAP", "entity": "components", "cap": MAX_COMPONENTS})
    if len(draft["relations"]) > MAX_RELATIONS:
        errors.append({"code": "OVER_CAP", "entity": "relations", "cap": MAX_RELATIONS})

    cycle = find_cycle(adjacency)
    if cycle:
        info.append({"code": "MODULE_CYCLE", "cycle": cycle})
    if known and len(isolated) * 100 > len(known) * 60:
        info.append({"code": "MANY_ISOLATED_NODES", "isolated": len(isolated), "total": len(known)})

    return errors, quality, info


def module_of(draft, entity_id):
    for module in draft["modules"]:
        if module.get("id") == entity_id:
            return entity_id
    for component in draft["components"]:
        if component.get("id") == entity_id:
            return component.get("moduleId")
    return None


def find_cycle(adjacency):
    """Return one module-level cycle as a list of ids, or None."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {}
    stack = []

    def visit(node):
        color[node] = GREY
        stack.append(node)
        for neighbour in sorted(adjacency.get(node, ())):
            state = color.get(neighbour, WHITE)
            if state == GREY:
                start = stack.index(neighbour)
                return stack[start:] + [neighbour]
            if state == WHITE:
                found = visit(neighbour)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(adjacency):
        if color.get(node, WHITE) == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def cmd_validate(args):
    draft = load_draft()
    errors, quality, info = run_validate(draft)
    # --strict promotes QUALITY warnings only. Module-level cycles and isolated
    # nodes describe what the CODE looks like, not what the GRAPH is worth: every
    # real repository has cycles, so promoting them would make this gate fail
    # unconditionally and therefore get bypassed on first use.
    effective_errors = list(errors) + (list(quality) if args.strict else [])
    ok = not effective_errors
    emit({
        "success": True, "command": "validate", "ok": ok, "strict": bool(args.strict),
        "errors": effective_errors[:50], "errorCount": len(effective_errors),
        "warnings": {"quality": quality[:50], "info": info[:20]},
        "warningCount": {"quality": len(quality), "info": len(info)},
        "counts": counts(draft),
    }, 0 if ok else 1)


def cmd_finalize(args):
    draft = load_draft()
    errors, quality, info = run_validate(draft)
    if errors:
        emit({
            "success": False, "command": "finalize", "error": "validation failed",
            "errors": errors[:50], "errorCount": len(errors),
        }, 1)

    # Verification gate (D5). Only `extracted` records fail the publish: such a
    # record failing means the EXTRACTOR lied, which is a tool bug and must be
    # loud. An `asserted` record failing means the model mis-remembered a line
    # number - a known, expected event, and the reason this labelling exists.
    # Refusing to publish for it would downgrade "a partly correct graph" to
    # "no graph", which is worse. Publish, but label it.
    verification = None
    verify_repaired = 0
    manifest = None
    if args.no_verify:
        verification = skipped_verification(draft)
    else:
        verification, verify_repaired, _dropped, _files, _exhausted, manifest = run_verify(
            draft, args.root, False, False, VERIFY_MAX_FILES,
            not args.no_manifest,
        )
        hard = [
            f for f in verification["findings"]
            # `not f.get("member")`: member findings never gate a publish. See
            # `_verify_member_lines` - members reach constructs components never
            # do, and one odd member turning "a graph with a stale line number"
            # into "no graph" is the trade this gate already refused to make for
            # `asserted` records.
            if f.get("provenance") == "extracted" and f["code"] in HARD_VERIFY_CODES
            and not f.get("member")
        ]
        if hard:
            # Note the artifact has NOT been touched yet: a rejected publish
            # leaves the previous graph intact.
            emit({
                "success": False, "command": "finalize",
                "error": "verification failed for records claiming provenance=extracted",
                "findings": hard[:20], "findingCount": len(hard),
                "hint": "run `verify --fix-lines` to repair drifted line numbers, "
                        "or `verify --drop-mismatched` to remove the records",
            }, 1)
    draft["verification"] = verification
    # Absence, NOT an empty manifest (invariant 18). An empty one would make the
    # drift report compute `total: 0` and `status: 'clean'` - a graph that was
    # never verified, wearing a green tick that reads "the 0 files it references
    # are unchanged". A stale manifest inherited from the draft would be worse
    # still, so this pops unconditionally on the no-manifest paths.
    if manifest is not None:
        draft["sourceManifest"] = manifest
    else:
        draft.pop("sourceManifest", None)
    draft["schemaVersion"] = SCHEMA_VERSION
    draft["generatedAt"] = int(os.path.getmtime(DRAFT_PATH) * 1000) if os.path.isfile(DRAFT_PATH) else 0
    draft["generator"] = {"name": "index-graph-tools", "toolVersion": TOOL_VERSION,
                          "agentType": draft.get("generator", {}).get("agentType", "")}
    out = args.out or DEFAULT_OUT
    # Rotation happens BEFORE the artifact is replaced - it is the artifact
    # currently on disk that gets archived - and it can never abort the publish.
    history_rotated = False
    history_stamp_source = None
    if not args.no_history:
        history_rotated, history_stamp_source = rotate_history(out)
    try:
        write_atomic(out, json.dumps(draft, ensure_ascii=False, indent=1))
    except OSError as err:
        fail("could not publish graph: %s" % err, path=to_posix(out))
    payload = {
        "success": True, "command": "finalize", "path": to_posix(out),
        "counts": counts(draft), "truncation": draft["truncation"],
        "warningCount": {"quality": len(quality), "info": len(info)},
        "verification": {
            "verifiedAt": verification["verifiedAt"],
            "skipped": verification["skipped"],
            "components": verification["components"],
            "relations": verification["relations"],
            "findingCount": len(verification["findings"]),
        },
        "repaired": verify_repaired,
        "historyRotated": history_rotated,
    }
    if history_stamp_source:
        payload["historyStampSource"] = history_stamp_source
    if manifest is not None:
        payload["sourceManifest"] = {
            "entries": len(manifest["entries"]),
            "truncated": manifest["truncated"],
            "skipped": manifest["skipped"],
        }
    emit(payload)


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog="index-graph-tools", description="Author .claude-index/graph.json")
    sub = parser.add_subparsers(dest="command")

    scan_modules = sub.add_parser("scan-modules", help="Aggregate directories into candidate modules")
    scan_modules.add_argument("--root", default=".")
    scan_modules.add_argument("--max-depth", type=int, default=3)
    scan_modules.add_argument("--min-files", type=int, default=2)
    scan_modules.add_argument("--limit", type=int, default=400)
    scan_modules.add_argument("--out")
    scan_modules.set_defaults(func=cmd_scan_modules)

    scan_imports = sub.add_parser("scan-imports", help="Extract directory-level import edges")
    scan_imports.add_argument("--root", default=".")
    scan_imports.add_argument("--path", required=True)
    scan_imports.add_argument("--lang", default="auto",
                              choices=["auto", "ts", "py", "java", "kt", "go", "cs"])
    scan_imports.add_argument("--limit", type=int, default=5000)
    scan_imports.add_argument("--include-external", action="store_true")
    scan_imports.add_argument("--out")
    scan_imports.set_defaults(func=cmd_scan_imports)

    scan_symbols = sub.add_parser("scan-symbols", help="Extract top-level declarations (heuristic)")
    scan_symbols.add_argument("--root", default=".")
    scan_symbols.add_argument("--path", required=True)
    scan_symbols.add_argument("--kinds", default="")
    scan_symbols.add_argument("--limit", type=int, default=2000)
    scan_symbols.add_argument("--out")
    scan_symbols.set_defaults(func=cmd_scan_symbols)

    scan_uml = sub.add_parser("scan-uml", help="Structural class/member extraction (brace-aware TS/JS, ast for Python)")
    scan_uml.add_argument("--root", default=".")
    scan_uml.add_argument("--path", required=True)
    scan_uml.add_argument("--lang", default="auto", choices=["auto", "ts", "py"])
    scan_uml.add_argument("--exported-only", dest="exported_only", action="store_true")
    scan_uml.add_argument("--max-containers", dest="max_containers", type=int, default=UML_MAX_CONTAINERS)
    scan_uml.add_argument("--min-members", dest="min_members", type=int, default=0)
    # Accepted and documented as the DEFAULT: every visibility is extracted, so
    # this flag is an explicit no-op kept so documented invocations keep working.
    scan_uml.add_argument("--include-private", dest="include_private", action="store_true",
                          help="No-op: private members are extracted by default")
    scan_uml.add_argument("--public-only", dest="public_only", action="store_true",
                          help="Narrow the output to public members only")
    scan_uml.add_argument("--limit", type=int, default=4000)
    scan_uml.add_argument("--module", help="Required with --emit-ops; scopes the component ids")
    scan_uml.add_argument("--emit-ops", dest="emit_ops", action="store_true",
                          help="Write ready-to-apply NDJSON instead of a descriptive report")
    scan_uml.add_argument("--out")
    scan_uml.set_defaults(func=cmd_scan_uml)

    init = sub.add_parser("init", help="Create (or resume) the draft")
    init.add_argument("--project-name", default="")
    init.add_argument("--root", default=".")
    init.add_argument("--force", action="store_true")
    init.add_argument("--from-published", dest="from_published", nargs="?",
                      const=DEFAULT_OUT, default=None,
                      help="Seed a new draft from an already published graph "
                           "(default .claude-index/graph.json). Ignored when a "
                           "draft already exists unless --force is given.")
    init.set_defaults(func=cmd_init)

    add_module = sub.add_parser("add-module", help="Upsert a module")
    add_module.add_argument("--id", required=True)
    add_module.add_argument("--name")
    add_module.add_argument("--path", required=True)
    add_module.add_argument("--layer")
    add_module.add_argument("--kind")
    add_module.add_argument("--parent")
    add_module.add_argument("--summary")
    add_module.add_argument("--tags")
    add_module.add_argument("--entry")
    add_module.add_argument("--files")
    add_module.add_argument("--loc")
    add_module.set_defaults(func=lambda a: cmd_add("add-module", a))

    add_component = sub.add_parser("add-component", help="Upsert a component")
    add_component.add_argument("--id", required=True)
    add_component.add_argument("--module", required=True)
    add_component.add_argument("--name")
    add_component.add_argument("--kind")
    add_component.add_argument("--stereotype")
    add_component.add_argument("--file")
    add_component.add_argument("--line")
    add_component.add_argument("--visibility")
    add_component.add_argument("--abstract")
    add_component.add_argument("--summary")
    add_component.add_argument("--tags")
    add_component.set_defaults(func=lambda a: cmd_add("add-component", a))

    add_member = sub.add_parser("add-member", help="Append an attribute or a method to a component")
    add_member.add_argument("--component", required=True)
    add_member.add_argument("--member-kind", dest="memberKind", required=True, choices=["field", "method"])
    add_member.add_argument("--name", required=True)
    # Both authoring paths must be able to carry a line number; without this the
    # `apply` path could and the subcommand path could not, which is the kind of
    # asymmetry nobody discovers until a hand-authored member refuses to jump.
    add_member.add_argument("--line")
    add_member.add_argument("--type")
    add_member.add_argument("--signature")
    add_member.add_argument("--visibility")
    add_member.add_argument("--static")
    add_member.add_argument("--abstract")
    add_member.add_argument("--async", dest="async_flag")
    add_member.add_argument("--readonly")
    add_member.set_defaults(func=lambda a: cmd_add("add-member", normalize_member_args(a)))

    add_relation = sub.add_parser("add-relation", help="Upsert a relation")
    add_relation.add_argument("--from", dest="from_id", required=True)
    add_relation.add_argument("--to", dest="to_id", required=True)
    add_relation.add_argument("--kind", required=True)
    add_relation.add_argument("--label")
    add_relation.add_argument("--from-card", dest="fromCard")
    add_relation.add_argument("--to-card", dest="toCard")
    add_relation.add_argument("--weight")
    add_relation.add_argument("--evidence")
    add_relation.set_defaults(func=lambda a: cmd_add("add-relation", normalize_relation_args(a)))

    apply_parser = sub.add_parser("apply", help="Apply a batch of operations from NDJSON")
    apply_parser.add_argument("--file")
    apply_parser.add_argument("--stdin", action="store_true")
    apply_parser.set_defaults(func=cmd_apply)

    remove = sub.add_parser("remove", help="Remove an entity (cascades)")
    remove.add_argument("--id", required=True)
    remove.add_argument("--kind", choices=["module", "component", "relation"])
    remove.set_defaults(func=cmd_remove)

    list_parser = sub.add_parser("list", help="List draft entities")
    list_parser.add_argument("--kind", required=True, choices=["modules", "components", "relations"])
    list_parser.add_argument("--module")
    list_parser.add_argument("--limit", type=int, default=100)
    list_parser.set_defaults(func=cmd_list)

    stats = sub.add_parser("stats", help="Draft counts, caps and remaining budget")
    stats.set_defaults(func=cmd_stats)

    validate = sub.add_parser("validate", help="Structural validation of the draft")
    validate.add_argument("--strict", action="store_true")
    validate.set_defaults(func=cmd_validate)

    verify = sub.add_parser("verify", help="Re-check every file:line and evidence entry against disk")
    verify.add_argument("--root", default=".")
    verify.add_argument("--fix-lines", dest="fix_lines", action="store_true",
                        help="Rewrite drifted line numbers in place")
    verify.add_argument("--drop-mismatched", dest="drop_mismatched", action="store_true",
                        help="Remove records whose file or declaration is gone (cascades)")
    verify.add_argument("--max-files", dest="max_files", type=int, default=VERIFY_MAX_FILES)
    verify.add_argument("--member-budget", dest="member_budget", type=int,
                        default=MEMBER_LOOKUP_BUDGET,
                        help="Cap on full-file declaration lookups for members")
    verify.add_argument("--limit", type=int, default=MAX_FINDINGS)
    verify.add_argument("--out")
    verify.set_defaults(func=cmd_verify)

    finalize = sub.add_parser("finalize", help="Verify, validate and atomically publish the graph")
    finalize.add_argument("--root", default=".")
    finalize.add_argument("--no-verify", dest="no_verify", action="store_true",
                          help="Escape hatch; the artifact records that it was skipped")
    finalize.add_argument("--no-manifest", dest="no_manifest", action="store_true",
                          help="Escape hatch; publish without the source fingerprint "
                               "manifest (the project then reports drift as unavailable)")
    finalize.add_argument("--no-history", dest="no_history", action="store_true",
                          help="Escape hatch; do not archive the previous artifact")
    finalize.add_argument("--out")
    finalize.set_defaults(func=cmd_finalize)

    return parser


class _Bag(object):
    """argparse Namespace shim so cmd_add can read attributes uniformly."""

    def __init__(self, mapping):
        self.__dict__.update(mapping)


def normalize_member_args(args):
    data = dict(vars(args))
    data["async"] = data.pop("async_flag", None)
    return _Bag(data)


def normalize_relation_args(args):
    data = dict(vars(args))
    data["from"] = data.pop("from_id", None)
    data["to"] = data.pop("to_id", None)
    return _Bag(data)


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        sys.exit(2)
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as err:  # noqa: BLE001
        emit({"success": False, "error": "unexpected error: %s" % err}, 1)


if __name__ == "__main__":
    main()
