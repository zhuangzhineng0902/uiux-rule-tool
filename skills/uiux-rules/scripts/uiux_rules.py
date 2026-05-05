#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RULE_FILES = {
    "foundation": "foundation-rules.csv",
    "component": "component-rules.csv",
    "global": "global-layout-rules.csv",
}

SCAN_EXTENSIONS = {
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".pcss",
    ".html",
    ".vue",
    ".svelte",
    ".jsx",
    ".tsx",
    ".js",
    ".ts",
}

IGNORED_DIRS = {
    ".git",
    ".next",
    ".nuxt",
    ".svelte-kit",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "target",
    "vendor",
}

STATE_MARKERS = {
    "hover": (":hover", "hover", "is-hover"),
    "focus": (":focus", ":focus-visible", "focus", "focused", "is-focus"),
    "active": (":active", ".active", "is-active", "aria-selected", "selected"),
    "disabled": (":disabled", "[disabled]", "disabled", "aria-disabled"),
    "open": (".open", "is-open", "[open]", "aria-expanded"),
    "error": (".error", "is-error", ":invalid", "invalid", "aria-invalid"),
    "loading": ("loading", "is-loading", "spinner"),
    "selected": (".selected", "is-selected", "aria-current", "selected"),
}

SPACING_PROPS = {
    "gap",
    "row-gap",
    "column-gap",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    "margin-top",
    "margin-right",
    "margin-bottom",
    "margin-left",
    "top",
    "right",
    "bottom",
    "left",
}

BORDER_PROPS = {
    "border-width",
    "border-style",
    "border-color",
    "border-top-width",
    "border-right-width",
    "border-bottom-width",
    "border-left-width",
    "border-top-color",
    "border-right-color",
    "border-bottom-color",
    "border-left-color",
}

FOUNDATION_TOKEN_PROP_ALIASES = {
    "color": {"color"},
    "background-color": {"background-color"},
    "primary-color": {"color", "background-color", "border-color"},
    "font-size": {"font-size"},
    "line-height": {"line-height"},
    "font-weight": {"font-weight"},
    "font-family": {"font-family"},
    "font-variant-numeric": {"font-variant-numeric"},
    "spacing": SPACING_PROPS,
    "space": SPACING_PROPS,
    "gap": {"gap", "row-gap", "column-gap"},
    "padding": {"padding-top", "padding-right", "padding-bottom", "padding-left"},
    "margin": {"margin-top", "margin-right", "margin-bottom", "margin-left"},
    "radius": {"border-radius"},
    "border-radius": {"border-radius"},
    "shadow": {"box-shadow"},
    "box-shadow": {"box-shadow"},
    "opacity": {"opacity"},
    "border": BORDER_PROPS,
    "border-width": {
        "border-width",
        "border-top-width",
        "border-right-width",
        "border-bottom-width",
        "border-left-width",
    },
    "border-style": {"border-style"},
    "border-color": {
        "border-color",
        "border-top-color",
        "border-right-color",
        "border-bottom-color",
        "border-left-color",
    },
}

GLOBAL_LAYOUT_PROPS = {
    "width",
    "max-width",
    "min-width",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    "margin-top",
    "margin-right",
    "margin-bottom",
    "margin-left",
    "gap",
    "row-gap",
    "column-gap",
    "grid-template-columns",
    "top",
    "right",
    "bottom",
    "left",
    "z-index",
}

SHORTHAND_EXPANSIONS = {
    "padding": ("padding-top", "padding-right", "padding-bottom", "padding-left"),
    "margin": ("margin-top", "margin-right", "margin-bottom", "margin-left"),
}


@dataclass(frozen=True)
class Rule:
    row: dict[str, str]

    @property
    def rule_id(self) -> str:
        return self.row.get("rule_id", "")

    @property
    def layer(self) -> str:
        return self.row.get("layer", "")

    @property
    def component(self) -> str:
        return self.row.get("component", "").strip().lower()

    @property
    def state(self) -> str:
        return self.row.get("state", "").strip().lower() or "default"

    @property
    def property_name(self) -> str:
        return self.row.get("property_name", "").strip().lower()

    @property
    def default_value(self) -> str:
        return self.row.get("default_value", "").strip()

    @property
    def subject(self) -> str:
        return self.row.get("subject", "").strip()


@dataclass(frozen=True)
class Declaration:
    path: Path
    line: int
    prop: str
    value: str
    context: str
    source_prop: str = ""


def resolve_rules_dir(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()

    candidates = [
        Path.cwd() / "data",
        Path(__file__).resolve().parents[3] / "data",
        Path(__file__).resolve().parents[2] / "data",
    ]
    for candidate in candidates:
        if all((candidate / filename).exists() for filename in RULE_FILES.values()):
            return candidate.resolve()
    raise SystemExit("找不到规则 CSV 文件。请显式传入 --rules-dir。")


def load_rules(rules_dir: Path) -> dict[str, list[Rule]]:
    result: dict[str, list[Rule]] = {}
    for bucket, filename in RULE_FILES.items():
        path = rules_dir / filename
        if not path.exists():
            raise SystemExit(f"缺少规则文件：{path}")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            result[bucket] = [Rule(row) for row in csv.DictReader(handle)]
    return result


def parse_components(raw_values: Iterable[str]) -> list[str]:
    components: list[str] = []
    for raw in raw_values:
        for item in re.split(r"[,，\s]+", raw):
            normalized = item.strip().lower()
            if normalized and normalized not in components:
                components.append(normalized)
    return components


def select_rules(rules: dict[str, list[Rule]], components: list[str]) -> list[Rule]:
    selected = list(rules["foundation"]) + list(rules["global"])
    if components:
        component_set = set(components)
        selected.extend(
            rule
            for rule in rules["component"]
            if rule.component in component_set or rule.subject.lower() in component_set
        )
    return selected


def format_rule(rule: Rule) -> dict[str, str]:
    fields = [
        "rule_id",
        "layer",
        "subject",
        "component",
        "state",
        "property_name",
        "condition_if",
        "then_clause",
        "else_clause",
        "default_value",
        "preferred_pattern",
        "anti_pattern",
        "evidence",
    ]
    return {field: rule.row.get(field, "") for field in fields}


def print_rules_markdown(rules: list[Rule]) -> None:
    buckets = [
        ("基础规范规则", [rule for rule in rules if rule.layer == "foundation"]),
        ("全局布局规则", [rule for rule in rules if rule.layer == "global"]),
        ("组件规范规则", [rule for rule in rules if rule.layer == "component"]),
    ]
    for title, bucket_rules in buckets:
        print(f"## {title}")
        if not bucket_rules:
            print("\n未选择任何规则。\n")
            continue
        for rule in bucket_rules:
            values = format_rule(rule)
            property_label = values["property_name"] or "无属性字段"
            print(
                f"- {values['rule_id']} "
                f"[{values['component'] or values['subject']} / {values['state']} / {property_label}]\n"
                f"  - 条件：{values['condition_if']}\n"
                f"  - 要求：{values['then_clause']}\n"
                f"  - 默认值：{values['default_value']}\n"
                f"  - 推荐做法：{values['preferred_pattern']}\n"
                f"  - 禁止/避免：{values['anti_pattern']}\n"
            )


def iter_frontend_files(project: Path) -> Iterable[Path]:
    for path in project.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix.lower() not in SCAN_EXTENSIONS:
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        yield path


def extract_declarations(path: Path) -> list[Declaration]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []

    declarations: list[Declaration] = []
    selector_stack: list[str] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if "{" in stripped:
            before = stripped.split("{", 1)[0].strip()
            if before.startswith("@media"):
                selector_stack.append(before)
            elif before and not before.startswith(("@", "if ", "for ", "function ")):
                selector_stack.append(before)
        context = " ".join(selector_stack[-3:]) + " " + stripped

        for match in re.finditer(r"(?P<prop>[-a-zA-Z]+)\s*:\s*(?P<value>[^;,{}`]+)", stripped):
            prop = to_kebab_case(match.group("prop"))
            value = clean_value(match.group("value"))
            if prop and value:
                declarations.extend(expand_declaration(path, index, prop, value, context.strip()))

        closing_count = stripped.count("}")
        for _ in range(min(closing_count, len(selector_stack))):
            selector_stack.pop()
    return declarations


def expand_declaration(path: Path, line: int, prop: str, value: str, context: str) -> list[Declaration]:
    if prop in SHORTHAND_EXPANSIONS:
        values = split_box_values(value)
        expanded = dict(zip(SHORTHAND_EXPANSIONS[prop], values, strict=True))
        return [
            Declaration(path, line, expanded_prop, expanded_value, context, source_prop=prop)
            for expanded_prop, expanded_value in expanded.items()
        ]
    if prop == "border":
        return expand_border(path, line, value, context)
    return [Declaration(path, line, prop, value, context, source_prop=prop)]


def split_box_values(value: str) -> tuple[str, str, str, str]:
    parts = [part for part in re.split(r"\s+", clean_value(value)) if part]
    if len(parts) == 1:
        top = right = bottom = left = parts[0]
    elif len(parts) == 2:
        top = bottom = parts[0]
        right = left = parts[1]
    elif len(parts) == 3:
        top = parts[0]
        right = left = parts[1]
        bottom = parts[2]
    else:
        top, right, bottom, left = parts[:4]
    return top, right, bottom, left


def expand_border(path: Path, line: int, value: str, context: str) -> list[Declaration]:
    width = ""
    style = ""
    color = ""
    for part in re.split(r"\s+", clean_value(value)):
        if re.match(r"^\d+(\.\d+)?(px|rem|em)$", part):
            width = part
        elif part in {"none", "solid", "dashed", "dotted", "double"}:
            style = part
        elif looks_like_css_color(part):
            color = part
    declarations = []
    if width:
        declarations.append(Declaration(path, line, "border-width", width, context, source_prop="border"))
    if style:
        declarations.append(Declaration(path, line, "border-style", style, context, source_prop="border"))
    if color:
        declarations.append(Declaration(path, line, "border-color", color, context, source_prop="border"))
    return declarations or [Declaration(path, line, "border", value, context, source_prop="border")]


def clean_value(value: str) -> str:
    value = value.strip().strip("'\"")
    value = re.sub(r"\s*!important$", "", value, flags=re.IGNORECASE)
    return value.strip()


def to_kebab_case(value: str) -> str:
    value = value.strip()
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    return value.replace("_", "-").lower()


def normalize_css_value(value: str) -> str:
    value = clean_value(value).lower()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*,\s*", ",", value)
    return value


def expected_values(rule: Rule) -> list[str]:
    raw = rule.default_value
    if not raw:
        return []
    if not looks_like_css_value(raw):
        return []
    parts = [part.strip() for part in re.split(r"[、|/，]", raw) if part.strip()]
    return parts or [raw]


def looks_like_css_value(value: str) -> bool:
    value = value.strip()
    return bool(
        looks_like_css_color(value)
        or re.search(r"\b\d+(\.\d+)?(px|rem|em|%|vh|vw|s|ms)\b", value)
        or value in {"0", "none", "auto", "transparent", "inherit", "initial", "unset", "100%"}
    )


def looks_like_css_color(value: str) -> bool:
    return bool(re.search(r"^(#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\()", value.strip()))


def rule_css_properties(rule: Rule) -> set[str]:
    if rule.layer == "foundation":
        subject = rule.subject.lower()
        if rule.property_name == "color":
            if "边框" in subject:
                return {"border-color", "border-top-color", "border-right-color", "border-bottom-color", "border-left-color"}
            if "分割线" in subject:
                return {"border-color", "background-color"}
            if "背景" in subject:
                return {"background-color"}
            if "文本" in subject:
                return {"color"}
        return set(FOUNDATION_TOKEN_PROP_ALIASES.get(rule.property_name, {rule.property_name}))
    return {rule.property_name}


def context_matches_component(rule: Rule, context: str) -> bool:
    if rule.layer != "component":
        return True
    if not rule.component:
        return True
    lowered = context.lower()
    component = re.escape(rule.component)
    return bool(re.search(rf"(\.{component}\b|\b{component}\b|-{component}\b|{component}-)", lowered))


def context_matches_state(rule: Rule, context: str) -> bool:
    if rule.layer != "component":
        return True
    if rule.state in {"", "default"}:
        lowered = context.lower()
        return not any(
            marker in lowered
            for state, markers in STATE_MARKERS.items()
            for marker in markers
        )
    lowered = context.lower()
    return any(marker in lowered for marker in STATE_MARKERS.get(rule.state, (rule.state,)))


def scan_project(project: Path, rules: dict[str, list[Rule]]) -> list[dict[str, object]]:
    declarations: list[Declaration] = []
    for path in iter_frontend_files(project):
        declarations.extend(extract_declarations(path))

    comparable_rules = [
        rule
        for bucket in ("foundation", "global", "component")
        for rule in rules[bucket]
        if is_comparable_rule(rule)
    ]

    violations: list[dict[str, object]] = []
    for declaration in declarations:
        for rule in comparable_rules:
            if declaration.prop not in rule_css_properties(rule):
                continue
            if not context_matches_component(rule, declaration.context):
                continue
            if not context_matches_state(rule, declaration.context):
                continue
            expected = [normalize_css_value(value) for value in expected_values(rule)]
            actual = normalize_css_value(declaration.value)
            if actual in expected:
                continue
            if rule.layer == "foundation" and not foundation_context_matches(rule, declaration):
                continue
            if rule.layer == "global" and not global_context_matches(rule, declaration.context):
                continue
            violations.append(
                {
                    "rule_id": rule.rule_id,
                    "layer": rule.layer,
                    "component": rule.component,
                    "state": rule.state,
                    "property_name": rule.property_name,
                    "expected": rule.default_value,
                    "actual": declaration.value,
                    "path": str(declaration.path),
                    "line": declaration.line,
                    "reason": f"{rule.property_name} 应符合 {rule.rule_id}",
                    "condition_if": rule.row.get("condition_if", ""),
                    "preferred_pattern": rule.row.get("preferred_pattern", ""),
                    "anti_pattern": rule.row.get("anti_pattern", ""),
                }
            )

    violations.extend(find_missing_component_states(declarations, rules["component"]))
    return dedupe_violations(violations)


def is_comparable_rule(rule: Rule) -> bool:
    if not rule.property_name or not expected_values(rule):
        return False
    if rule.layer == "global" and rule.property_name not in GLOBAL_LAYOUT_PROPS:
        return False
    if rule.layer == "foundation" and not rule_css_properties(rule):
        return False
    return True


def global_context_matches(rule: Rule, context: str) -> bool:
    subject = rule.subject.lower()
    condition = rule.row.get("condition_if", "").lower()
    if "屏幕宽度" in condition and "@media" not in context.lower():
        return False
    if "屏幕宽度" not in condition and "@media" in context.lower():
        return False
    if not subject or subject in {"explicit-if-then-else"}:
        return True
    normalized_subject = re.sub(r"\s+", "-", subject)
    lowered = context.lower()
    return subject in lowered or normalized_subject in lowered


def foundation_context_matches(rule: Rule, declaration: Declaration) -> bool:
    subject = rule.subject.lower()
    if not subject:
        return False
    context = declaration.context
    lowered = context.lower()
    aliases = {
        "标题文本": ("title", "heading", "h1", "h2", "h3"),
        "一级文本": ("primary-text", "body", "content"),
        "二级文本": ("secondary-text", "muted", "caption", "subtext"),
        "禁用文本": ("disabled", "is-disabled", "[disabled]"),
        "一级边框": ("primary-border",),
        "分割线": ("divider", "separator"),
        "布局背景": ("layout-background", "page-shell", "layout"),
        "主字体": ("body", "root", "html"),
        "regular": ("regular", "body"),
        "medium": ("medium", "emphasis"),
        "英文加粗": ("semibold", "bold"),
        "间距": ("spacing", "space", "gap", "padding", "margin"),
        "圆角": ("radius", "rounded", "border-radius"),
        "阴影": ("shadow", "elevation", "box-shadow"),
        "透明度": ("opacity", "alpha"),
        "边框": ("border", "stroke"),
    }
    if subject in lowered or re.sub(r"\s+", "-", subject) in lowered:
        return True
    if "边框" in subject and declaration.prop not in BORDER_PROPS:
        return False
    if "圆角" in subject and declaration.prop != "border-radius":
        return False
    if "阴影" in subject and declaration.prop != "box-shadow":
        return False
    if "透明度" in subject and declaration.prop != "opacity":
        return False
    if any(any(alias in lowered for alias in values) for key, values in aliases.items() if key in subject):
        return True
    return is_foundation_token_set_rule(rule)


def is_foundation_token_set_rule(rule: Rule) -> bool:
    if rule.property_name not in FOUNDATION_TOKEN_PROP_ALIASES:
        return False
    if not expected_values(rule):
        return False
    subject_and_condition = f"{rule.subject} {rule.row.get('condition_if', '')}".lower()
    token_markers = (
        "token",
        "令牌",
        "基础",
        "色板",
        "字阶",
        "间距",
        "圆角",
        "阴影",
        "透明度",
        "边框",
    )
    return any(marker in subject_and_condition for marker in token_markers)


def find_missing_component_states(declarations: list[Declaration], component_rules: list[Rule]) -> list[dict[str, object]]:
    required: dict[str, set[str]] = {}
    properties: dict[tuple[str, str], set[str]] = {}
    for rule in component_rules:
        if rule.component and rule.state and rule.state != "default":
            required.setdefault(rule.component, set()).add(rule.state)
            properties.setdefault((rule.component, rule.state), set()).add(rule.property_name)

    seen: dict[str, dict[str, Declaration]] = {}
    for declaration in declarations:
        lowered = declaration.context.lower()
        for component, states in required.items():
            if not re.search(rf"(\.{re.escape(component)}\b|\b{re.escape(component)}\b)", lowered):
                continue
            bucket = seen.setdefault(component, {})
            bucket.setdefault("default", declaration)
            for state in states:
                if any(marker in lowered for marker in STATE_MARKERS.get(state, (state,))):
                    bucket[state] = declaration

    violations: list[dict[str, object]] = []
    for component, states in required.items():
        component_seen = seen.get(component, {})
        if "default" not in component_seen:
            continue
        anchor = component_seen["default"]
        for state in sorted(states):
            if state in component_seen:
                continue
            violations.append(
                {
                    "rule_id": "CMP-state-coverage",
                    "layer": "component",
                    "component": component,
                    "state": state,
                    "property_name": ",".join(sorted(properties.get((component, state), set()))),
                    "expected": f"{component} 应定义 {state} 状态",
                    "actual": "未找到状态选择器",
                    "path": str(anchor.path),
                    "line": anchor.line,
                    "reason": "组件规范要求的交互状态在已扫描样式中缺失",
                    "condition_if": "",
                    "preferred_pattern": "为已使用组件声明必需的交互状态。",
                    "anti_pattern": "不要在缺少必要视觉状态的情况下交付组件。",
                }
            )
    return violations


def dedupe_violations(violations: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for item in violations:
        key = (item["rule_id"], item["path"], item["line"], item["property_name"], item["state"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def print_violations_markdown(violations: list[dict[str, object]], project: Path) -> None:
    print(f"# UIUX 扫描报告\n\n工程：`{project}`\n\n违规数量：{len(violations)}\n")
    if not violations:
        print("未发现高置信度静态违规。")
        return
    for item in violations:
        print(
            f"- {item['rule_id']} `{item['path']}:{item['line']}`\n"
            f"  - {item['reason']}\n"
            f"  - 属性：`{item['property_name']}`；实际值：`{item['actual']}`；期望值：`{item['expected']}`\n"
            f"  - 禁止/避免：{item['anti_pattern']}\n"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检索 UIUX 规则，或扫描前端工程。")
    parser.add_argument("--rules-dir", default=None, help="包含三个 UIUX 规则 CSV 文件的目录。")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    subparsers = parser.add_subparsers(dest="command", required=True)

    rules_parser = subparsers.add_parser("rules-for-components", help="加载基础/全局规则，并按组件名加载对应组件规则。")
    rules_parser.add_argument("--components", action="append", default=[], help="用英文逗号或空格分隔的组件名称。")

    scan_parser = subparsers.add_parser("scan-project", help="扫描前端工程中的高置信度 UIUX 违规。")
    scan_parser.add_argument("--project", required=True, help="前端工程路径。")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rules_dir = resolve_rules_dir(args.rules_dir)
    rules = load_rules(rules_dir)

    if args.command == "rules-for-components":
        selected = select_rules(rules, parse_components(args.components))
        payload = [format_rule(rule) for rule in selected]
        if args.format == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_rules_markdown(selected)
        return 0

    if args.command == "scan-project":
        project = Path(args.project).expanduser().resolve()
        violations = scan_project(project, rules)
        if args.format == "json":
            print(json.dumps(violations, ensure_ascii=False, indent=2))
        else:
            print_violations_markdown(violations, project)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
