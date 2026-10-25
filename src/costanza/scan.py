"""Detect stack, run, test and layout from common project files."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from costanza.config import Config, load_config
from costanza.constants import DEFAULT_SCAN_EXCLUDE
from costanza.format import Document, Header
from costanza.io import read_text
from costanza.paths import ProjectPaths, discover_root
from costanza.scrub import redact
from costanza.store import mutate_file, read_file

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found,unused-ignore]

_PY_FRAMEWORKS = (
    ("fastapi", "FastAPI"),
    ("flask", "Flask"),
    ("django", "Django"),
    ("typer", "Typer"),
    ("click", "Click"),
    ("aiogram", "aiogram"),
    ("sqlalchemy", "SQLAlchemy"),
    ("pydantic", "Pydantic"),
    ("httpx", "httpx"),
    ("pytest", "pytest"),
)
_JS_FRAMEWORKS = (
    ("react", "React"),
    ("next", "Next.js"),
    ("vue", "Vue"),
    ("svelte", "Svelte"),
    ("express", "Express"),
    ("vite", "Vite"),
    ("jest", "Jest"),
    ("vitest", "Vitest"),
)
_DIR_PURPOSE = {
    "src": "lib",
    "lib": "lib",
    "pkg": "lib",
    "app": "app",
    "apps": "apps",
    "tests": "tests",
    "test": "tests",
    "docs": "docs",
    "doc": "docs",
    "scripts": "scripts",
    "bin": "scripts",
    "cmd": "cli",
    "internal": "internal",
    "web": "frontend",
    "frontend": "frontend",
    "backend": "api",
    "api": "api",
    "deploy": "deploy",
    "data": "data",
    "migrations": "db",
}
_EXT_PURPOSE = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
}
_REQUIRES_RE = re.compile(r"(\d+\.\d+)")
_MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:", re.MULTILINE)
_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)")
_GO_VER_RE = re.compile(r"^go\s+(\d+\.\d+)", re.MULTILINE)


@dataclass
class Detected:
    stack: str | None = None
    run: str | None = None
    test: str | None = None
    layout: str | None = None


@dataclass
class HeaderChange:
    key: str
    old: str
    new: str


@dataclass
class ScanResult:
    detected: Detected
    changes: list[HeaderChange] = field(default_factory=list)
    wrote: bool = False
    redacted: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "detected": {
                "stack": self.detected.stack,
                "run": self.detected.run,
                "test": self.detected.test,
                "layout": self.detected.layout,
            },
            "changes": [{"key": item.key, "old": item.old, "new": item.new} for item in self.changes],
        }


def _read(path: Path) -> str:
    try:
        return read_text(path)
    except OSError:
        return ""


def _parse_toml(path: Path) -> dict[str, object]:
    text = _read(path)
    if not text:
        return {}
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_json(path: Path) -> dict[str, object]:
    text = _read(path)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _dep_names(*groups: object) -> list[str]:
    names: list[str] = []
    for group in groups:
        if isinstance(group, list):
            for item in group:
                if isinstance(item, str):
                    match = _REQ_NAME_RE.match(item.strip())
                    if match:
                        names.append(match.group(1).split("[")[0].lower())
        elif isinstance(group, dict):
            names.extend(str(key).split("[")[0].lower() for key in group)
    return names


def _frameworks(names: list[str], table: tuple[tuple[str, str], ...]) -> list[str]:
    found: list[str] = []
    lower = set(names)
    for key, label in table:
        if key in lower and label not in found:
            found.append(label)
    return found


def _python_version(spec: str) -> str | None:
    match = _REQUIRES_RE.search(spec)
    if match is None:
        return None
    return f"python{match.group(1)}"


def _walk_files(root: Path, exclude: tuple[str, ...]) -> list[str]:
    blocked = set(exclude) | set(DEFAULT_SCAN_EXCLUDE)
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in blocked and not name.startswith(".")
        ]
        current = Path(dirpath)
        for name in filenames:
            rel = (current / name).relative_to(root).as_posix()
            if any(part in blocked or part.startswith(".") for part in rel.split("/")):
                continue
            out.append(rel)
    return sorted(out)


def listed_files(root: Path, exclude: tuple[str, ...]) -> list[str]:
    from costanza.git import ls_files

    tracked = ls_files(root)
    if tracked is not None:
        blocked = set(exclude)
        cleaned: list[str] = []
        for rel in tracked:
            parts = rel.replace("\\", "/").split("/")
            if any(part in blocked for part in parts):
                continue
            cleaned.append("/".join(parts))
        return cleaned
    return _walk_files(root, exclude)


def _layout(files: list[str]) -> str | None:
    counts: dict[str, dict[str, int]] = {}
    for rel in files:
        parts = rel.split("/")
        if len(parts) < 2:
            continue
        top = parts[0]
        if top.startswith(".") or top in DEFAULT_SCAN_EXCLUDE:
            continue
        bucket = counts.setdefault(top, {})
        suffix = Path(rel).suffix.lower()
        if suffix:
            bucket[suffix] = bucket.get(suffix, 0) + 1
        bucket[""] = bucket.get("", 0) + 1
    if not counts:
        return None
    items: list[str] = []
    for name in sorted(counts)[:8]:
        purpose = _DIR_PURPOSE.get(name)
        if purpose is None:
            extensions = [(ext, n) for ext, n in counts[name].items() if ext]
            extensions.sort(key=lambda item: item[1], reverse=True)
            if extensions:
                purpose = _EXT_PURPOSE.get(extensions[0][0])
        if purpose:
            items.append(f"{name}/ ({purpose})")
        else:
            items.append(f"{name}/")
    return ", ".join(items) if items else None


def detect(root: Path, *, exclude: tuple[str, ...] = DEFAULT_SCAN_EXCLUDE) -> Detected:
    files = listed_files(root, exclude)
    present = set(files)
    stack: list[str] = []
    run: str | None = None
    test: str | None = None

    pyproject = root / "pyproject.toml"
    if "pyproject.toml" in present or pyproject.is_file():
        data = _parse_toml(pyproject)
        project = data.get("project")
        project_table = project if isinstance(project, dict) else {}
        requires = project_table.get("requires-python")
        if isinstance(requires, str):
            version = _python_version(requires)
            if version:
                stack.append(version)
        elif not stack:
            stack.append("python")
        extra_deps = project_table.get("optional-dependencies")
        extra_groups = list(extra_deps.values()) if isinstance(extra_deps, dict) else []
        deps = _dep_names(project_table.get("dependencies"), *extra_groups)
        tool = data.get("tool")
        tool_table = tool if isinstance(tool, dict) else {}
        if "pytest" in tool_table or "pytest" in deps:
            deps.append("pytest")
        stack.extend(_frameworks(deps, _PY_FRAMEWORKS))
        scripts = project_table.get("scripts")
        if run is None and isinstance(scripts, dict) and scripts:
            first = next(iter(scripts))
            if isinstance(first, str) and first:
                run = first
        if test is None and ("pytest" in deps or "pytest" in tool_table):
            test = "pytest -q"

    req = root / "requirements.txt"
    if "requirements.txt" in present or req.is_file():
        names = []
        for line in _read(req).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                continue
            match = _REQ_NAME_RE.match(stripped)
            if match:
                names.append(match.group(1).split("[")[0].lower())
        if not any(item.startswith("python") for item in stack):
            stack.insert(0, "python")
        stack.extend(_frameworks(names, _PY_FRAMEWORKS))
        if test is None and "pytest" in names:
            test = "pytest -q"

    package = root / "package.json"
    if "package.json" in present or package.is_file():
        data = _parse_json(package)
        names = _dep_names(data.get("dependencies"), data.get("devDependencies"))
        lang = ["node"]
        if "typescript" in names:
            lang.append("typescript")
        stack = lang + [item for item in stack if item not in lang]
        stack.extend(_frameworks(names, _JS_FRAMEWORKS))
        scripts = data.get("scripts")
        script_table = scripts if isinstance(scripts, dict) else {}
        if run is None and "dev" in script_table:
            run = "npm run dev"
        elif run is None and "start" in script_table:
            run = "npm start"
        if test is None and "test" in script_table:
            test = "npm test"

    if "Cargo.toml" in present or (root / "Cargo.toml").is_file():
        if "rust" not in stack:
            stack.append("rust")
        if run is None:
            run = "cargo run"
        if test is None:
            test = "cargo test"

    if "go.mod" in present or (root / "go.mod").is_file():
        match = _GO_VER_RE.search(_read(root / "go.mod"))
        label = f"go {match.group(1)}" if match else "go"
        if not any(item.startswith("go") for item in stack):
            stack.append(label)
        if run is None:
            run = "go run ."
        if test is None:
            test = "go test ./..."

    makefile = root / "Makefile"
    if "Makefile" in present or makefile.is_file():
        targets = set(_MAKE_TARGET_RE.findall(_read(makefile)))
        if run is None and "run" in targets:
            run = "make run"
        if test is None and "test" in targets:
            test = "make test"

    if "pom.xml" in present or (root / "pom.xml").is_file():
        if "java" not in stack:
            stack.append("java")

    gradle = root / "build.gradle"
    gradle_kts = root / "build.gradle.kts"
    if "build.gradle" in present or "build.gradle.kts" in present or gradle.is_file() or gradle_kts.is_file():
        text = _read(gradle) + _read(gradle_kts)
        if "kotlin" in text.lower() and "kotlin" not in stack:
            stack.append("kotlin")
        elif "java" not in stack:
            stack.append("java")

    if "Gemfile" in present or (root / "Gemfile").is_file():
        text = _read(root / "Gemfile").lower()
        if "ruby" not in stack:
            stack.append("ruby")
        if "rails" in text and "Rails" not in stack:
            stack.append("Rails")

    if "composer.json" in present or (root / "composer.json").is_file():
        if "php" not in stack:
            stack.append("php")

    # First match wins for language: keep order, unique, cap at 6.
    unique: list[str] = []
    for item in stack:
        if item not in unique:
            unique.append(item)
    stack = unique[:6]
    layout = _layout(files)
    return Detected(
        stack=", ".join(stack) if stack else None,
        run=run,
        test=test,
        layout=layout,
    )


def _is_empty(key: str, value: str) -> bool:
    if key == "synced":
        return False
    return value in {"", "?"}


def plan_changes(header: Header, detected: Detected, *, overwrite: bool) -> list[HeaderChange]:
    current = {
        "stack": header.stack,
        "run": header.run,
        "test": header.test,
        "layout": header.layout,
    }
    proposed = {
        "stack": detected.stack,
        "run": detected.run,
        "test": detected.test,
        "layout": detected.layout,
    }
    changes: list[HeaderChange] = []
    for key in ("stack", "run", "test", "layout"):
        new = proposed[key]
        if new is None:
            continue
        old = current[key]
        if old == new:
            continue
        if overwrite or _is_empty(key, old):
            changes.append(HeaderChange(key=key, old=old, new=new))
    return changes


def apply_header(header: Header, changes: list[HeaderChange]) -> Header:
    values = {
        "stack": header.stack,
        "run": header.run,
        "test": header.test,
        "layout": header.layout,
        "synced": header.synced,
    }
    for item in changes:
        values[item.key] = item.new
    return Header(
        project=header.project,
        stack=values["stack"],
        run=values["run"],
        test=values["test"],
        layout=values["layout"],
        synced=values["synced"],
        extras=header.extras,
        line=header.line,
    )


def scan_project(
    *,
    write: bool = False,
    overwrite: bool = False,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> tuple[ScanResult, Config]:
    root = discover_root(cwd, explicit, allow_cwd=False)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    detected = detect(root, exclude=config.scan_exclude)
    previous, document = read_file(paths)
    changes = plan_changes(document.header, detected, overwrite=overwrite)
    names: list[str] = []
    if write and changes:
        cleaned: list[HeaderChange] = []
        for item in changes:
            red = redact(item.new, list(config.secret_allow))
            names.extend(red.names)
            cleaned.append(HeaderChange(key=item.key, old=item.old, new=red.text))

        def mutator(current: Document) -> Document:
            return replace(current, header=apply_header(current.header, cleaned))

        mutate_file(paths, previous, mutator, "scan header")
        changes = cleaned
    return (
        ScanResult(
            detected=detected,
            changes=changes,
            wrote=bool(write and changes),
            redacted=tuple(dict.fromkeys(names)),
        ),
        config,
    )
