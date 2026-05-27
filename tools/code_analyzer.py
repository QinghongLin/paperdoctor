"""
Code Analyzer Tool

Indexes codebases using tree-sitter AST parsing + config file flattening.
Produces a rich index with:
  - symbols (functions, classes, imports) with tags, parent, init_params
  - config_entries (flattened key-value pairs from json/yaml/toml)
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tree-sitter setup
# ---------------------------------------------------------------------------

_LANG_MODULES = {
    ".py": ("tree_sitter_python", "python"),
    ".js": ("tree_sitter_javascript", "javascript"),
    ".jsx": ("tree_sitter_javascript", "javascript"),
    # Note: .ts/.tsx require tree_sitter_typescript (not installed by default)
    ".java": ("tree_sitter_java", "java"),
    ".go": ("tree_sitter_go", "go"),
    ".c": ("tree_sitter_c", "c"),
    ".h": ("tree_sitter_c", "c"),
    ".cpp": ("tree_sitter_cpp", "cpp"),
    ".hpp": ("tree_sitter_cpp", "cpp"),
    ".rs": ("tree_sitter_rust", "rust"),
}

_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml"}
_METADATA_ONLY_EXTS = {".sh", ".cfg", ".ini", ".md"}

try:
    import tree_sitter as _ts
    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False
    logger.warning("tree-sitter not available")

_parser_cache: Dict[str, Any] = {}


def _get_parser(ext: str):
    if not _TS_AVAILABLE or ext not in _LANG_MODULES:
        return None
    if ext in _parser_cache:
        return _parser_cache[ext]
    mod_name, lang_name = _LANG_MODULES[ext]
    try:
        mod = __import__(mod_name)
        lang = _ts.Language(mod.language())
        parser = _ts.Parser(lang)
        _parser_cache[ext] = (parser, lang_name)
        return (parser, lang_name)
    except Exception as e:
        logger.debug(f"Cannot load tree-sitter for {ext}: {e}")
        _parser_cache[ext] = None
        return None


# ---------------------------------------------------------------------------
# AST extraction rules per language
# ---------------------------------------------------------------------------

_EXTRACT_RULES: Dict[str, List[tuple]] = {
    "python": [
        ("function_definition", "function"),
        ("class_definition", "class"),
        ("import_statement", "import"),
        ("import_from_statement", "import"),
    ],
    "javascript": [
        ("function_declaration", "function"),
        ("class_declaration", "class"),
        ("arrow_function", "function"),
        ("import_statement", "import"),
    ],
    "java": [
        ("method_declaration", "function"),
        ("class_declaration", "class"),
        ("import_declaration", "import"),
    ],
    "go": [
        ("function_declaration", "function"),
        ("method_declaration", "function"),
        ("type_declaration", "class"),
        ("import_declaration", "import"),
    ],
    "c": [
        ("function_definition", "function"),
        ("struct_specifier", "class"),
        ("preproc_include", "import"),
    ],
    "cpp": [
        ("function_definition", "function"),
        ("class_specifier", "class"),
        ("struct_specifier", "class"),
        ("preproc_include", "import"),
    ],
    "rust": [
        ("function_item", "function"),
        ("struct_item", "class"),
        ("impl_item", "class"),
        ("use_declaration", "import"),
    ],
}


def _extract_name(node, source_bytes: bytes) -> str:
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "property_identifier"):
            return source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
    text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    return text.split("\n")[0][:120]


def _collect_nodes(node, node_types: Set[str]) -> list:
    """Walk tree and collect nodes of given types (yields tuples of (node, parent_node))."""
    results = []
    stack = [(node, None)]
    while stack:
        current, parent = stack.pop()
        if current.type in node_types:
            results.append((current, parent))
        # Push children with current as parent (only for class/function scopes)
        child_parent = current if current.type in (
            "class_definition", "class_declaration", "class_specifier",
            "struct_specifier", "impl_item",
        ) else parent
        for child in reversed(current.children):
            stack.append((child, child_parent))
    return results


# ---------------------------------------------------------------------------
# Python-specific: extract __init__ default params from AST
# ---------------------------------------------------------------------------

def _extract_init_params_py(node, source_bytes: bytes) -> Dict[str, str]:
    """For a Python function_definition node, extract default parameter values."""
    params = {}
    for child in node.children:
        if child.type == "parameters":
            for param in child.children:
                # Handle both untyped (default_parameter) and typed (typed_default_parameter)
                if param.type in ("default_parameter", "typed_default_parameter"):
                    name_node = param.children[0] if param.children else None
                    value_node = param.children[-1] if len(param.children) >= 2 else None
                    if name_node and value_node and name_node is not value_node:
                        pname = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                        pval = source_bytes[value_node.start_byte:value_node.end_byte].decode("utf-8", errors="replace")
                        if pname != "self":
                            params[pname] = pval
    return params


# ---------------------------------------------------------------------------
# Semantic tag assignment
# ---------------------------------------------------------------------------

_TRAINING_NAMES = {"train", "train_epoch", "_train_epoch", "training_step", "train_step", "fit"}
_FORWARD_NAMES = {"forward", "call", "__call__"}


def _assign_tags(name: str, kind: str, parent_name: Optional[str], init_params: Dict[str, str],
                 file_path: str) -> List[str]:
    """Assign semantic tags to a symbol based on heuristics."""
    tags: List[str] = []
    name_lower = name.lower()
    path_lower = file_path.lower()

    if kind == "class":
        tags.append("class")
    if kind == "function":
        # For qualified names like "ClassName.forward", check the method part
        method_name = name_lower.rsplit(".", 1)[-1]
        if method_name in _FORWARD_NAMES:
            tags.append("forward")
        if method_name in _TRAINING_NAMES:
            tags.append("training_loop")
        if method_name == "__init__":
            tags.append("constructor")
            # Check if init has numeric-like default params
            for v in init_params.values():
                try:
                    float(v)
                    tags.append("hyperparameter_site")
                    break
                except (ValueError, TypeError):
                    pass
    # Path-based tags — match on path segments to avoid false positives
    # (e.g. "data" matching "documentation", "run" matching "runtime")
    path_parts = set(re.split(r"[/\\._-]", path_lower))
    if path_parts & {"config", "configs", "cfg", "hparam", "hyperparam"}:
        tags.append("config_related")
    if path_parts & {"loss", "criterion", "objective"}:
        tags.append("loss")
    if path_parts & {"model", "network", "arch", "backbone"}:
        tags.append("model")
    if path_parts & {"train", "trainer", "run"}:
        tags.append("training")
    if path_parts & {"data", "dataset", "loader", "transform", "augment"}:
        tags.append("data")

    return tags


# ---------------------------------------------------------------------------
# Config file parsing — flatten to key-value entries
# ---------------------------------------------------------------------------

@dataclass
class ConfigEntry:
    key_path: str
    value: Any  # scalar: str, int, float, bool
    line: Optional[int] = None


def _flatten_config(obj: Any, prefix: str = "", results: Optional[List] = None) -> List[Dict[str, Any]]:
    """Recursively flatten a dict/list into dot-path key-value pairs."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_config(v, f"{prefix}{k}.", results)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _flatten_config(v, f"{prefix}{i}.", results)
    else:
        key_path = prefix.rstrip(".")
        if key_path:
            results.append({"key_path": key_path, "value": obj})
    return results


def _approx_line(raw_text: str, key: str, value: Any) -> Optional[int]:
    """Approximate line number for a key-value pair by searching raw text."""
    # Search for the last segment of the key path near the value
    last_key = key.split(".")[-1]
    val_str = json.dumps(value) if isinstance(value, str) else str(value)
    # Try to find a line containing both key and value
    for i, line in enumerate(raw_text.splitlines(), 1):
        if last_key in line and (val_str in line or repr(value) in line):
            return i
    # Fallback: find line with just the key
    for i, line in enumerate(raw_text.splitlines(), 1):
        if last_key in line:
            return i
    return None


def _parse_config_file(file_path: Path) -> List[ConfigEntry]:
    """Parse a config file and return flattened entries."""
    ext = file_path.suffix.lower()
    try:
        raw = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    data = None
    if ext == ".json":
        try:
            data = json.loads(raw)
        except Exception:
            return []
    elif ext in (".yaml", ".yml"):
        try:
            import yaml
            data = yaml.safe_load(raw)
        except ImportError:
            logger.debug("PyYAML not installed, skipping YAML config")
            return []
        except Exception:
            return []
    elif ext == ".toml":
        try:
            import tomllib
            data = tomllib.loads(raw)
        except ImportError:
            try:
                import tomli
                data = tomli.loads(raw)
            except ImportError:
                logger.debug("No TOML parser available, skipping")
                return []
        except Exception:
            return []

    if not isinstance(data, dict):
        return []

    flat = _flatten_config(data)
    entries = []
    for item in flat:
        line = _approx_line(raw, item["key_path"], item["value"])
        entries.append(ConfigEntry(
            key_path=item["key_path"],
            value=item["value"],
            line=line,
        ))
    return entries


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Symbol:
    name: str
    kind: str  # "function", "class", "import"
    line: int
    end_line: int
    tags: List[str] = field(default_factory=list)
    parent: Optional[str] = None
    init_params: Optional[Dict[str, str]] = None


@dataclass
class CodeFile:
    file_path: str
    file_type: str
    lines_of_code: int
    size_bytes: int
    symbols: List[Symbol] = field(default_factory=list)
    config_entries: List[ConfigEntry] = field(default_factory=list)


@dataclass
class CodebaseIndex:
    root_path: str
    total_files: int
    files: List[CodeFile]
    metadata: Dict[str, Any]


# ---------------------------------------------------------------------------
# Main analyzer
# ---------------------------------------------------------------------------

class CodeAnalyzer:
    """Analyzes codebase using tree-sitter AST + config file parsing."""

    def __init__(
        self,
        codebase_path: str,
        output_dir: str = None,
        supported_extensions: Optional[Set[str]] = None,
        skip_directories: Optional[Set[str]] = None,
        max_file_size: int = 1048576,
    ):
        self.codebase_path = Path(codebase_path)
        if output_dir is None:
            output_dir = str(self.codebase_path.parent / "paperdoctor" / "codebase")
        output_path = Path(output_dir)
        # Accept either an output directory or a full .json file path.
        if output_path.suffix.lower() == ".json":
            self.output_dir = output_path.parent
            self.output_file = output_path
        else:
            self.output_dir = output_path
            self.output_file = self.output_dir / "index.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.supported_extensions = supported_extensions or (
            set(_LANG_MODULES.keys()) | _CONFIG_EXTS | _METADATA_ONLY_EXTS
        )
        self.skip_directories = skip_directories or {
            "__pycache__", "node_modules", ".git",
            "venv", "env", ".venv",
            "build", "dist", "target",
            ".pytest_cache", ".mypy_cache",
        }
        self.max_file_size = max_file_size

    def _parse_file(self, file_path: Path, relative_path: str) -> List[Symbol]:
        """Parse a source file and return symbols with tags, parent, init_params."""
        ext = file_path.suffix
        parser_info = _get_parser(ext)
        if parser_info is None:
            return []
        parser, lang_name = parser_info
        rules = _EXTRACT_RULES.get(lang_name, [])
        if not rules:
            return []

        try:
            source = file_path.read_bytes()
        except Exception:
            return []

        tree = parser.parse(source)
        node_types = {r[0] for r in rules}
        type_to_kind = {r[0]: r[1] for r in rules}

        collected = _collect_nodes(tree.root_node, node_types)

        symbols: List[Symbol] = []
        for node, parent_node in collected:
            kind = type_to_kind[node.type]
            name = _extract_name(node, source)

            # Parent name
            parent_name = None
            if parent_node is not None:
                parent_name = _extract_name(parent_node, source)

            # Qualified name for methods
            qualified = f"{parent_name}.{name}" if parent_name and kind == "function" else name

            # Extract __init__ params (Python only)
            init_params = None
            if lang_name == "python" and name == "__init__" and node.type == "function_definition":
                init_params = _extract_init_params_py(node, source)
            # Also propagate init_params to the parent class symbol
            # (handled in post-processing below)

            tags = _assign_tags(qualified, kind, parent_name, init_params or {}, relative_path)

            symbols.append(Symbol(
                name=qualified,
                kind=kind,
                line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
                tags=tags,
                parent=parent_name,
                init_params=init_params,
            ))

        # Post-process: propagate init_params to class symbols
        init_params_by_class: Dict[str, Dict[str, str]] = {}
        for s in symbols:
            if s.init_params and s.parent:
                init_params_by_class[s.parent] = s.init_params
        for s in symbols:
            if s.kind == "class" and s.name in init_params_by_class:
                s.init_params = init_params_by_class[s.name]

        return symbols

    def scan_codebase(self) -> CodebaseIndex:
        if not self.codebase_path.exists():
            raise ValueError(f"Codebase path does not exist: {self.codebase_path}")

        files: List[CodeFile] = []
        total_size = 0
        total_config_entries = 0

        for root, dirs, filenames in os.walk(self.codebase_path):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if d not in self.skip_directories]

            for filename in filenames:
                file_path = root_path / filename
                if file_path.suffix not in self.supported_extensions:
                    continue
                try:
                    size = file_path.stat().st_size
                except Exception:
                    continue
                if size > self.max_file_size:
                    continue

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = sum(1 for _ in f)
                except Exception:
                    continue

                relative_path = str(file_path.relative_to(self.codebase_path))

                # AST symbols
                symbols = self._parse_file(file_path, relative_path)

                # Config entries
                config_entries = []
                if file_path.suffix in _CONFIG_EXTS:
                    config_entries = _parse_config_file(file_path)
                    total_config_entries += len(config_entries)

                files.append(CodeFile(
                    file_path=relative_path,
                    file_type=file_path.suffix,
                    lines_of_code=lines,
                    size_bytes=size,
                    symbols=symbols,
                    config_entries=config_entries,
                ))
                total_size += size

        total_symbols = sum(len(f.symbols) for f in files)
        logger.info(f"Indexed {len(files)} files, {total_symbols} symbols, {total_config_entries} config entries")

        return CodebaseIndex(
            root_path=str(self.codebase_path),
            total_files=len(files),
            files=files,
            metadata={
                "total_size_bytes": total_size,
                "total_symbols": total_symbols,
                "total_config_entries": total_config_entries,
                "extensions": sorted(self.supported_extensions),
                "timestamp": datetime.now().isoformat(),
                "indexer": "tree-sitter+config",
            },
        )

    def save_index(self, index: CodebaseIndex, filename: str = "index.json") -> str:
        output_file = self.output_file if filename == "index.json" else self.output_dir / filename

        def _sym_dict(s: Symbol) -> dict:
            d = {"name": s.name, "kind": s.kind, "line": s.line, "end_line": s.end_line}
            if s.tags:
                d["tags"] = s.tags
            if s.parent:
                d["parent"] = s.parent
            if s.init_params:
                d["init_params"] = s.init_params
            return d

        def _ce_dict(ce: ConfigEntry) -> dict:
            d = {"key_path": ce.key_path, "value": ce.value}
            if ce.line is not None:
                d["line"] = ce.line
            return d

        index_dict = {
            "root_path": index.root_path,
            "total_files": index.total_files,
            "files": [
                {
                    "file_path": f.file_path,
                    "file_type": f.file_type,
                    "lines_of_code": f.lines_of_code,
                    "size_bytes": f.size_bytes,
                    **({"symbols": [_sym_dict(s) for s in f.symbols]} if f.symbols else {}),
                    **({"config_entries": [_ce_dict(ce) for ce in f.config_entries]} if f.config_entries else {}),
                }
                for f in index.files
            ],
            "metadata": index.metadata,
        }
        with open(output_file, "w", encoding="utf-8") as fh:
            json.dump(index_dict, fh, indent=2, default=str)
        logger.info(f"Saved codebase index to: {output_file}")
        return str(output_file)

    def read_file_content(self, relative_path: str) -> Optional[str]:
        full_path = self.codebase_path / relative_path
        if not full_path.is_file():
            return None
        try:
            return full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

    def read_symbol_body(self, relative_path: str, line: int, end_line: int) -> Optional[str]:
        """Read specific line range from a file (for symbol body retrieval)."""
        content = self.read_file_content(relative_path)
        if content is None:
            return None
        lines = content.splitlines()
        start = max(0, line - 1)
        end = min(len(lines), end_line)
        return "\n".join(lines[start:end])

    def search_files_by_pattern(self, index: CodebaseIndex, pattern: str) -> List[CodeFile]:
        pattern_lower = pattern.lower()
        return [f for f in index.files if pattern_lower in f.file_path.lower()]

    def search_symbols(self, index: CodebaseIndex, name: str, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        name_lower = name.lower()
        results = []
        for f in index.files:
            for s in f.symbols:
                if name_lower in s.name.lower():
                    if kind and s.kind != kind:
                        continue
                    results.append({
                        "file": f.file_path,
                        "name": s.name,
                        "kind": s.kind,
                        "line": s.line,
                        "end_line": s.end_line,
                        "tags": s.tags,
                        "parent": s.parent,
                    })
        return results

    def search_config(self, index: CodebaseIndex, key_pattern: str) -> List[Dict[str, Any]]:
        """Search config entries by key_path substring match."""
        pat = key_pattern.lower()
        results = []
        for f in index.files:
            for ce in f.config_entries:
                if pat in ce.key_path.lower():
                    results.append({
                        "file": f.file_path,
                        "key_path": ce.key_path,
                        "value": ce.value,
                        "line": ce.line,
                    })
        return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Index a codebase using tree-sitter AST + config parsing",
    )
    parser.add_argument("codebase_path", help="Path to the codebase directory")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory or full .json file path for the index",
    )
    parser.add_argument("--search", "-s", help="Search for files matching pattern")
    parser.add_argument("--symbol", help="Search for symbol by name")
    parser.add_argument("--config-key", help="Search config entries by key pattern")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    output_dir = args.output or str(Path(args.codebase_path).parent / "paperdoctor" / "codebase")
    analyzer = CodeAnalyzer(codebase_path=args.codebase_path, output_dir=output_dir)

    print(f"Indexing codebase: {args.codebase_path}")
    index = analyzer.scan_codebase()

    output_file = analyzer.save_index(index)
    m = index.metadata
    print(f"Index saved to: {output_file}")
    print(f"Files: {index.total_files}, symbols: {m['total_symbols']}, config entries: {m['total_config_entries']}")

    if args.search:
        matches = analyzer.search_files_by_pattern(index, args.search)
        print(f"\nFiles matching '{args.search}': {len(matches)}")
        for f in matches:
            print(f"  {f.file_path} ({f.lines_of_code} lines, {len(f.symbols)} sym, {len(f.config_entries)} cfg)")

    if args.symbol:
        results = analyzer.search_symbols(index, args.symbol)
        print(f"\nSymbols matching '{args.symbol}': {len(results)}")
        for r in results:
            tags = f" [{', '.join(r['tags'])}]" if r['tags'] else ""
            print(f"  {r['kind']} {r['name']} @ {r['file']}:{r['line']}{tags}")

    if args.config_key:
        results = analyzer.search_config(index, args.config_key)
        print(f"\nConfig entries matching '{args.config_key}': {len(results)}")
        for r in results:
            print(f"  {r['key_path']} = {r['value']}  ({r['file']}:{r['line']})")

    if args.json:
        print(json.dumps({
            "codebase_path": str(analyzer.codebase_path),
            "total_files": index.total_files,
            "total_symbols": m["total_symbols"],
            "total_config_entries": m["total_config_entries"],
            "output_file": output_file,
        }, indent=2))
