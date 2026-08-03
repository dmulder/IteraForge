from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

from .migrations import validate_migrations
from .tabs import load_manifest, source_dir, validate_source_tree

ALLOWED_SUFFIXES = {".html", ".css", ".js", ".json", ".md", ".txt"}
MAX_FILE_SIZE = 512 * 1024
IGNORED_DIRS = {
    ".git",
    ".cache",
    ".config",
    ".local",
    ".npm",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "tmp",
    "temp",
}
WARNING_PATTERNS = [
    re.compile(r"/api/(tasks|settings|activity|tabs)", re.I),
]
TOP_LEVEL_LEXICAL_PATTERN = re.compile(r"^(?:const|let|class)\s+[A-Za-z_$]", re.M)
PERSISTENT_BROWSER_RESOURCE_PATTERN = re.compile(
    r"\b(?:document|window)\.addEventListener\b|\bnew\s+MutationObserver\b|\bsetInterval\s*\(",
    re.M,
)


class _Parser(HTMLParser):
    pass


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ignored_paths: list[str] = field(default_factory=list)

    def limited_warnings(self, limit: int = 50) -> list[str]:
        if len(self.warnings) <= limit:
            return self.warnings
        omitted = len(self.warnings) - limit
        return [*self.warnings[:limit], f"... {omitted} more warnings omitted"]

    def model_dump(self) -> dict[str, object]:
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "ignored_paths": self.ignored_paths,
        }


def validate_tab(tab_id: str) -> ValidationReport:
    report = ValidationReport()
    try:
        validate_source_tree(tab_id)
        manifest = load_manifest(tab_id)
        src = source_dir(tab_id)
        for path in iter_source_files(src, report):
            rel = path.relative_to(src)
            if path.suffix not in ALLOWED_SUFFIXES:
                report.warnings.append(f"{rel}: unsupported file type")
            if path.stat().st_size > MAX_FILE_SIZE:
                report.warnings.append(f"{rel}: file too large")
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in WARNING_PATTERNS:
                if pattern.search(text):
                    report.warnings.append(f"{rel}: suspicious pattern {pattern.pattern}")
            if path.suffix == ".html":
                try:
                    _Parser().feed(text)
                except Exception as exc:
                    report.warnings.append(f"{rel}: invalid HTML: {exc}")
            if path.suffix == ".js":
                if text.count("{") != text.count("}"):
                    report.warnings.append(f"{rel}: unbalanced braces")
                reload_warnings = reload_safety_warnings(text)
                report.warnings.extend(f"{rel}: {warning}" for warning in reload_warnings)
            if path.suffix == ".json":
                try:
                    json.loads(text)
                except Exception as exc:
                    report.warnings.append(f"{rel}: invalid JSON: {exc}")
        entry_text = (src / manifest.entrypoint).read_text(encoding="utf-8")
        if "data-render-list" not in entry_text and "data-action" not in entry_text:
            report.warnings.append("entrypoint does not use declarative IteraForge data bindings")
        try:
            validate_migrations(tab_id)
        except Exception as exc:
            report.warnings.append(f"migration validation warning: {exc}")
    except Exception as exc:
        report.errors.append(str(exc))
    return report


def iter_source_files(src: Path, report: ValidationReport):
    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        kept_dirs = []
        for dirname in dirs:
            rel = (root_path / dirname).relative_to(src)
            if dirname in IGNORED_DIRS or any(part in IGNORED_DIRS for part in rel.parts):
                report.ignored_paths.append(str(rel))
            else:
                kept_dirs.append(dirname)
        dirs[:] = kept_dirs
        for filename in files:
            path = root_path / filename
            if any(part in IGNORED_DIRS for part in path.relative_to(src).parts):
                report.ignored_paths.append(str(path.relative_to(src)))
                continue
            yield path


def reload_safety_warnings(text: str) -> list[str]:
    has_cleanup = "window.IteraForgeTabCleanup" in text
    warnings: list[str] = []
    if TOP_LEVEL_LEXICAL_PATTERN.search(text):
        warnings.append(
            "top-level let/const/class declarations can break same-page tab reloads; "
            "wrap app.js in a scoped initializer"
        )
    if PERSISTENT_BROWSER_RESOURCE_PATTERN.search(text) and not has_cleanup:
        warnings.append(
            "persistent listeners, observers, or timers should register window.IteraForgeTabCleanup"
        )
    return warnings
