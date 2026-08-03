from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from .models import TabManifest
from .tabs import git_head, load_manifest, source_dir

BLOCKED_TAGS = {"script", "iframe", "object", "embed", "base", "link", "meta"}
VOID_TAGS = {"area", "br", "col", "hr", "img", "input", "source", "track", "wbr"}
URI_ATTRS = {"href", "src", "action", "formaction", "poster"}
ALLOWED_URI_PREFIXES = ("#", "/", "./", "../")


class TabSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.errors: list[str] = []
        self._skip_stack: list[str] = []
        self._in_body = False
        self._in_head = False
        self._saw_body = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "body":
            self._in_body = True
            self._saw_body = True
            return
        if tag == "head":
            self._in_head = True
            return
        if tag in {"html", "title"}:
            return
        if self._in_head and tag in {"meta", "link"}:
            return
        if tag in BLOCKED_TAGS:
            self.errors.append(f"blocked tag <{tag}>")
            self._skip_stack.append(tag)
            return
        if self._skip_stack:
            return
        if self._saw_body and not self._in_body:
            return
        clean_attrs = self._clean_attrs(tag, attrs)
        attr_text = "".join(f' {name}="{escape_attr(value)}"' for name, value in clean_attrs)
        self.output.append(f"<{tag}{attr_text}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "head":
            self._in_head = False
            return
        if tag == "body":
            self._in_body = False
            return
        if self._skip_stack:
            if self._skip_stack[-1] == tag:
                self._skip_stack.pop()
            return
        if tag in {"html", "head", "title"} or tag in BLOCKED_TAGS or tag in VOID_TAGS:
            return
        if self._saw_body and not self._in_body:
            return
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip_stack:
            return
        if self._saw_body and not self._in_body:
            return
        self.output.append(escape_text(data))

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")

    def _clean_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
        clean: list[tuple[str, str]] = []
        for name, value in attrs:
            attr = name.lower()
            raw = value or ""
            if attr.startswith("on"):
                self.errors.append(f"blocked inline event handler {attr}")
                continue
            if attr in {"srcdoc", "sandbox"}:
                self.errors.append(f"blocked attribute {attr}")
                continue
            if attr in URI_ATTRS and not safe_uri(raw):
                self.errors.append(f"blocked unsafe URL in {attr}")
                continue
            if tag == "form" and attr in {"action", "method", "target"}:
                continue
            clean.append((attr, raw))
        return clean


def sanitize_html(html: str) -> tuple[str, list[str]]:
    parser = TabSanitizer()
    parser.feed(html)
    parser.close()
    return "".join(parser.output).strip(), parser.errors


def safe_uri(value: str) -> bool:
    stripped = value.strip().lower()
    if not stripped:
        return True
    if stripped.startswith(("javascript:", "data:", "vbscript:", "http://", "https://", "//")):
        return False
    return stripped.startswith(ALLOWED_URI_PREFIXES) or ":" not in stripped


def render_payload(tab_id: str, runtime_token: str) -> dict[str, Any]:
    manifest: TabManifest = load_manifest(tab_id)
    src = source_dir(tab_id)
    html = (src / manifest.entrypoint).read_text(encoding="utf-8")
    html_body = extract_body(html)
    css_path = src / "style.css"
    css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    js_path = src / "app.js"
    js = js_path.read_text(encoding="utf-8") if js_path.exists() else ""
    return {
        "manifest": manifest.model_dump(),
        "html_body": html_body,
        "css": css,
        "js": js,
        "runtime_token": runtime_token,
        "schema_version": manifest.schema_version,
        "asset_version": git_head(tab_id) or str(manifest.version),
    }


def extract_body(html: str) -> str:
    match = re.search(r"<body\b[^>]*>(?P<body>.*?)</body\s*>", html, re.I | re.S)
    if match:
        return match.group("body").strip()
    return html.strip()


def escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_attr(value: str) -> str:
    return escape_text(value).replace('"', "&quot;")
