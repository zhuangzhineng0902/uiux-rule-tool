from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, fields
from pathlib import Path
import sys

from .config import DEFAULT_CONFIG_PATH, load_app_config
from .extractors import dedupe_rules, generate_rules
from .ingest import load_documents
from .llm_extractor import (
    LLMExtractorError,
    can_use_openai_llm,
    extract_dropped_rules_with_llm,
    extract_rules_with_llm,
    resolve_llm_model,
)
from .models import RuleRow, SourceDocument
from .writer import CSV_FILE_ENCODING, assign_rule_ids, write_csvs

RESUME_STATE_VERSION = 1


class ChineseArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        help_text = super().format_help()
        help_text = help_text.replace("usage:", "用法：", 1)
        help_text = help_text.replace("\noptions:\n", "\n参数说明：\n", 1)
        help_text = help_text.replace("show this help message and exit", "显示帮助信息并退出")
        return help_text


def run(
    input_value: str | list[str] | None = None,
    output_dir: str | None = None,
    extractor: str | None = None,
    llm_model: str | None = None,
    config_path: str | None = None,
    rerun_dropped: bool | None = None,
) -> dict[str, int]:
    app_config = load_app_config(config_path)
    selected_output_dir = (output_dir or "").strip() or app_config.output.directory
    should_rerun_dropped = rerun_dropped if rerun_dropped is not None else app_config.run.mode == "rerun_dropped"

    if should_rerun_dropped:
        return _rerun_dropped_rules(
            output_dir=selected_output_dir,
            app_config=app_config,
            llm_model=llm_model,
        )

    selected_inputs = _resolve_input_values(input_value, app_config)
    selected_extractor = extractor or app_config.extraction.strategy
    resume_signature = _build_resume_signature(selected_inputs, selected_extractor, llm_model)
    resume_path = _resume_checkpoint_path(selected_output_dir)
    completed_locations, rules = _load_resume_checkpoint(resume_path, resume_signature)

    documents = []
    seen_document_locations: set[str] = set(completed_locations)

    for source in selected_inputs:
        for document in load_documents(source, skip_locations=completed_locations):
            normalized_location = str(Path(document.location).resolve())
            if normalized_location in seen_document_locations:
                continue
            seen_document_locations.add(normalized_location)
            documents.append(document)

    use_document_debug_dirs = len(completed_locations) + len(documents) > 1
    for document in documents:
        debug_dir = _document_debug_dir(selected_output_dir, document.location) if use_document_debug_dirs else None
        document_rules = _generate_non_official_rules(
            [document],
            extractor=selected_extractor,
            llm_model=llm_model,
            app_config=app_config,
            output_dir=selected_output_dir,
            debug_dir=debug_dir,
        )
        rules.extend(document_rules)
        normalized_location = str(Path(document.location).resolve())
        completed_locations.add(normalized_location)
        _write_resume_checkpoint(resume_path, resume_signature, completed_locations, rules)

    rules = dedupe_rules(rules)
    assign_rule_ids(rules)
    write_csvs(rules, selected_output_dir)
    _clear_resume_checkpoint(resume_path)

    counter = Counter(row.prefix for row in rules)
    return {
        "documents": len(documents),
        "foundation_rules": counter.get("FDN", 0),
        "component_rules": counter.get("CMP", 0),
        "global_rules": sum(count for prefix, count in counter.items() if prefix not in {"FDN", "CMP"}),
        "output_dir": selected_output_dir,
    }


def _rerun_dropped_rules(output_dir: str, app_config, llm_model: str | None) -> dict[str, int]:
    debug_root = Path(output_dir) / "debug"
    dropped_docs = _load_dropped_rule_documents(debug_root)
    if not dropped_docs:
        print(f"[uiux-rule-tool] 未找到可重跑的 dropped-rules：{debug_root}", file=sys.stderr)

    recovered_rules: list[RuleRow] = []
    if dropped_docs:
        recovered_rules = extract_dropped_rules_with_llm(
            dropped_docs,
            config=app_config,
            model=resolve_llm_model(app_config, llm_model),
            debug_dir=str(debug_root / "rerun-dropped"),
        )

    rules = _read_existing_csv_rules(output_dir)
    rules.extend(recovered_rules)
    rules = dedupe_rules(rules)
    assign_rule_ids(rules)
    write_csvs(rules, output_dir)

    counter = Counter(row.prefix for row in rules)
    return {
        "documents": len(dropped_docs),
        "foundation_rules": counter.get("FDN", 0),
        "component_rules": counter.get("CMP", 0),
        "global_rules": sum(count for prefix, count in counter.items() if prefix not in {"FDN", "CMP"}),
        "rerun_dropped_rules": len(recovered_rules),
        "output_dir": output_dir,
    }


def _resolve_input_values(input_value: str | list[str] | None, app_config) -> list[str]:
    if isinstance(input_value, list):
        selected_inputs = [item.strip() for item in input_value if item and item.strip()]
    elif isinstance(input_value, str):
        selected_inputs = [input_value.strip()] if input_value.strip() else []
    else:
        selected_inputs = list(app_config.input.sources)

    if not selected_inputs:
        raise ValueError(
            "缺少输入源。请通过 --input 传入，或在配置文件中设置 [input].sources。"
        )

    remote_sources = [source for source in selected_inputs if _is_remote_source(source)]
    if remote_sources:
        raise ValueError("当前版本仅支持本地 Markdown 文件或目录，不支持网站 URL。")

    return selected_inputs


def _is_remote_source(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _load_dropped_rule_documents(debug_root: Path) -> list[SourceDocument]:
    if not debug_root.exists():
        return []

    documents: list[SourceDocument] = []
    for dropped_path in sorted(debug_root.rglob("dropped-rules.json")):
        if "rerun-dropped" in dropped_path.parts:
            continue
        try:
            entries = _load_dropped_rule_entries(dropped_path)
        except Exception as exc:
            raise RuntimeError(f"解析 dropped-rules 文件失败：{dropped_path}：{exc}") from exc
        if not entries:
            continue

        meta = _load_json_file(dropped_path.parent / "meta.json")
        location = str(meta.get("location", dropped_path.parent))
        title = str(meta.get("title", dropped_path.parent.name))
        source_bucket = str(meta.get("source_bucket", ""))
        text = json.dumps(
            {
                "source_debug_dir": str(dropped_path.parent),
                "source_location": location,
                "dropped_rules": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        documents.append(
            SourceDocument(
                source_type="dropped-rules",
                location=location,
                title=f"{title} dropped-rules 重跑",
                text=text,
                source_bucket=source_bucket,
            )
        )

    return documents


def _load_dropped_rule_entries(dropped_path: Path) -> list[dict[str, object]]:
    payload = _load_json_file(dropped_path)
    detailed_items = payload.get("dropped_rule_items")
    if isinstance(detailed_items, list) and detailed_items:
        return [item for item in detailed_items if isinstance(item, dict)]

    adjacent_payload = _load_json_file(dropped_path.parent / "payload.json")
    meta = _load_json_file(dropped_path.parent / "meta.json")
    doc = SourceDocument(
        source_type=str(meta.get("source_type", "markdown")),
        location=str(meta.get("location", dropped_path.parent)),
        title=str(meta.get("title", dropped_path.parent.name)),
        text="",
        source_bucket=str(meta.get("source_bucket", "")),
    )
    return _derive_dropped_rule_entries(adjacent_payload, doc)


def _derive_dropped_rule_entries(payload: dict[str, object], doc: SourceDocument) -> list[dict[str, object]]:
    from .llm_extractor import _dropped_rule_details

    return _dropped_rule_details(payload, doc)


def _load_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_existing_csv_rules(output_dir: str) -> list[RuleRow]:
    target = Path(output_dir)
    specs = [
        ("foundation-rules.csv", "FDN", "foundation", "foundation"),
        ("component-rules.csv", "CMP", "component", "component"),
        ("global-layout-rules.csv", "", "global", "layout"),
    ]
    rows: list[RuleRow] = []

    for filename, default_prefix, layer, page_type in specs:
        path = target / filename
        if not path.exists():
            continue
        with path.open(encoding=CSV_FILE_ENCODING) as handle:
            for item in csv.DictReader(handle):
                rule_id = str(item.get("rule_id", ""))
                prefix = default_prefix
                if not prefix and "-" in rule_id:
                    prefix = rule_id.split("-", 1)[0]
                rows.append(
                    RuleRow(
                        prefix=prefix or "LAY",
                        layer=layer,
                        page_type=page_type,
                        subject=str(item.get("subject", "")),
                        component=str(item.get("component", "")),
                        state=str(item.get("state", "")) or "default",
                        property_name=str(item.get("property_name", "")),
                        condition_if=str(item.get("condition_if", "")),
                        then_clause=str(item.get("then_clause", "")),
                        else_clause=str(item.get("else_clause", "")),
                        default_value=str(item.get("default_value", "")),
                        preferred_pattern=str(item.get("preferred_pattern", "")),
                        anti_pattern=str(item.get("anti_pattern", "")),
                        evidence=str(item.get("evidence", "")),
                        source_ref=str(item.get("source_ref", "")),
                        rule_id=rule_id,
                    )
                )

    return rows


def _resume_checkpoint_path(output_dir: str) -> Path:
    return Path(output_dir) / "debug" / "resume-state.json"


def _build_resume_signature(selected_inputs: list[str], extractor: str, llm_model: str | None) -> dict[str, object]:
    return {
        "inputs": [str(Path(source).resolve()) for source in selected_inputs],
        "extractor": extractor,
        "llm_model": llm_model or "",
    }


def _load_resume_checkpoint(path: Path, signature: dict[str, object]) -> tuple[set[str], list[RuleRow]]:
    if not path.exists():
        return set(), []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[uiux-rule-tool] 断点文件读取失败，将重新开始：{path}：{exc}", file=sys.stderr)
        return set(), []

    if payload.get("version") != RESUME_STATE_VERSION or payload.get("signature") != signature:
        print(f"[uiux-rule-tool] 断点文件与当前输入不匹配，将重新开始：{path}", file=sys.stderr)
        return set(), []

    completed_locations = {str(item) for item in payload.get("completed_documents", []) if item}
    rows = [_rule_from_checkpoint(item) for item in payload.get("rules", []) if isinstance(item, dict)]
    if completed_locations:
        print(
            f"[uiux-rule-tool] 已加载断点：{path}，已完成文件数：{len(completed_locations)}",
            file=sys.stderr,
        )
    return completed_locations, rows


def _write_resume_checkpoint(
    path: Path,
    signature: dict[str, object],
    completed_locations: set[str],
    rules: list[RuleRow],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": RESUME_STATE_VERSION,
        "signature": signature,
        "completed_documents": sorted(completed_locations),
        "rules": [_rule_to_checkpoint(row) for row in rules],
    }
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    print(f"[uiux-rule-tool] 已写入断点：{path}", file=sys.stderr)


def _clear_resume_checkpoint(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _rule_to_checkpoint(row: RuleRow) -> dict[str, str]:
    return {key: "" if value is None else str(value) for key, value in asdict(row).items()}


def _rule_from_checkpoint(payload: dict) -> RuleRow:
    field_names = {field.name for field in fields(RuleRow)}
    values = {name: "" if payload.get(name) is None else str(payload.get(name, "")) for name in field_names}
    return RuleRow(**values)


def _document_debug_dir(output_dir: str, location: str) -> str:
    name = Path(location).name or "document"
    safe_name = "".join(char if char.isalnum() or char in ".-_" else "_" for char in name)
    digest = hashlib.sha1(location.encode("utf-8")).hexdigest()[:10]
    return str(Path(output_dir) / "debug" / "documents" / f"{safe_name}-{digest}")


def _generate_non_official_rules(
    documents: list,
    extractor: str,
    llm_model: str | None,
    app_config,
    output_dir: str,
    debug_dir: str | None = None,
):
    if extractor not in {"auto", "heuristic", "llm"}:
        raise ValueError(f"不支持的抽取器类型：{extractor}")

    if extractor == "heuristic":
        return generate_rules(documents)

    if extractor == "llm":
        return extract_rules_with_llm(
            documents,
            config=app_config,
            model=resolve_llm_model(app_config, llm_model),
            debug_dir=debug_dir or str(Path(output_dir) / "debug"),
        )

    if can_use_openai_llm(app_config):
        try:
            return extract_rules_with_llm(
                documents,
                config=app_config,
                model=resolve_llm_model(app_config, llm_model),
                debug_dir=debug_dir or str(Path(output_dir) / "debug"),
            )
        except LLMExtractorError:
            return generate_rules(documents)

    return generate_rules(documents)


def build_parser() -> argparse.ArgumentParser:
    parser = ChineseArgumentParser(description="从本地 Markdown 文件或目录中生成原子化 UI/UX 规范规则。")
    parser.add_argument(
        "--input",
        action="append",
        default=None,
        help="可选输入源。仅支持本地 Markdown 文件或目录；可重复传入多个本地路径。默认读取配置文件中的 [input].sources。",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="可选输出目录覆盖项。默认读取配置文件中的 [output].directory。",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="应用配置 TOML 文件路径。",
    )
    parser.add_argument(
        "--extractor",
        choices=["auto", "heuristic", "llm"],
        default=None,
        help="可选抽取器覆盖项。默认读取配置文件中的抽取策略。",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="可选 OpenAI 模型覆盖项。默认读取配置文件中的模型配置。",
    )
    parser.add_argument(
        "--rerun-dropped",
        action="store_true",
        default=None,
        help="只重跑输出目录 debug 中的 dropped-rules，并把恢复出的规则合并回 CSV。",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    result = run(
        args.input,
        args.output_dir,
        extractor=args.extractor,
        llm_model=args.llm_model,
        config_path=args.config,
        rerun_dropped=args.rerun_dropped,
    )
    print(f"documents={result['documents']}")
    print(f"foundation_rules={result['foundation_rules']}")
    print(f"component_rules={result['component_rules']}")
    print(f"global_rules={result['global_rules']}")
    if "rerun_dropped_rules" in result:
        print(f"rerun_dropped_rules={result['rerun_dropped_rules']}")
    print(f"output_dir={result['output_dir']}")
    return 0
