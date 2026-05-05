from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "uiux-rules" / "scripts" / "uiux_rules.py"
RULES_DIR = ROOT / "data"
CSV_COLUMNS = [
    "rule_id",
    "prefix",
    "layer",
    "page_type",
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
    "source_ref",
]


class UIUXRulesSkillTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--rules-dir", str(RULES_DIR), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def run_script_with_rules_dir(self, rules_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--rules-dir", str(rules_dir), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def write_rules_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})

    def test_rules_for_components_loads_foundation_global_and_selected_component_rules(self) -> None:
        result = self.run_script(
            "--format",
            "json",
            "rules-for-components",
            "--components",
            "button",
        )

        rows = json.loads(result.stdout)
        layers = {row["layer"] for row in rows}
        components = {row["component"] for row in rows if row["component"]}

        self.assertIn("foundation", layers)
        self.assertIn("global", layers)
        self.assertIn("component", layers)
        self.assertIn("button", components)
        self.assertNotIn("input", components)

    def test_scan_project_reports_high_confidence_component_and_global_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            css_path = Path(temp_dir) / "app.css"
            css_path.write_text(
                ".button { height: 40px; border-radius: 4px; background-color: #123456; color: #FFFFFF; }\n"
                ".button:hover { background-color: #111111; }\n"
                ".page-shell { padding-top: 24px; }\n",
                encoding="utf-8",
            )

            result = self.run_script(
                "--format",
                "json",
                "scan-project",
                "--project",
                temp_dir,
            )

        violations = json.loads(result.stdout)
        ids = {item["rule_id"] for item in violations}

        self.assertIn("CMP-003", ids)
        self.assertIn("CMP-007", ids)
        self.assertIn("LST-002", ids)
        self.assertFalse(any(item["layer"] == "foundation" for item in violations))
        self.assertTrue(any(item["line"] == 1 for item in violations))

    def test_scan_project_expands_layout_shorthand_and_skips_interaction_assertions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            css_path = Path(temp_dir) / "app.css"
            css_path.write_text(
                ".page-shell { padding: 24px 32px; }\n"
                "@media (max-width: 600px) { .page-shell { padding: 24px 16px; } }\n"
                ".modal { display: block; }\n",
                encoding="utf-8",
            )

            result = self.run_script(
                "--format",
                "json",
                "scan-project",
                "--project",
                temp_dir,
            )

        violations = json.loads(result.stdout)
        ids = {item["rule_id"] for item in violations}

        self.assertIn("LST-002", ids)
        self.assertIn("LST-006", ids)
        self.assertFalse(any(item["property_name"] == "dismiss-on-overlay-click" for item in violations))

    def test_scan_project_checks_foundation_token_families(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rules_dir = root / "rules"
            project_dir = root / "project"
            rules_dir.mkdir()
            project_dir.mkdir()

            self.write_rules_csv(
                rules_dir / "foundation-rules.csv",
                [
                    {
                        "rule_id": "FDN-SPACE",
                        "prefix": "FDN",
                        "layer": "foundation",
                        "page_type": "foundation",
                        "subject": "间距令牌",
                        "state": "default",
                        "property_name": "spacing",
                        "condition_if": "If 使用间距令牌",
                        "then_clause": "Then spacing 必须从 8px|12px 中选择",
                        "default_value": "8px|12px",
                    }
                ],
            )
            self.write_rules_csv(rules_dir / "global-layout-rules.csv", [])
            self.write_rules_csv(rules_dir / "component-rules.csv", [])
            (project_dir / "app.css").write_text(".toolbar { gap: 10px; }\n", encoding="utf-8")

            result = self.run_script_with_rules_dir(
                rules_dir,
                "--format",
                "json",
                "scan-project",
                "--project",
                str(project_dir),
            )

        violations = json.loads(result.stdout)

        self.assertEqual(violations[0]["rule_id"], "FDN-SPACE")
        self.assertEqual(violations[0]["property_name"], "spacing")
        self.assertEqual(violations[0]["actual"], "10px")

    def test_empty_property_foundation_and_global_rules_are_retrieved_but_not_compared(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rules_dir = root / "rules"
            project_dir = root / "project"
            rules_dir.mkdir()
            project_dir.mkdir()

            self.write_rules_csv(
                rules_dir / "foundation-rules.csv",
                [
                    {
                        "rule_id": "FDN-EMPTY",
                        "prefix": "FDN",
                        "layer": "foundation",
                        "page_type": "foundation",
                        "subject": "色彩克制原则",
                        "state": "default",
                        "property_name": "",
                        "condition_if": "If 设计企业级产品配色",
                        "then_clause": "Then 色彩使用必须克制",
                    }
                ],
            )
            self.write_rules_csv(
                rules_dir / "global-layout-rules.csv",
                [
                    {
                        "rule_id": "LAY-EMPTY",
                        "prefix": "LAY",
                        "layer": "global",
                        "page_type": "list",
                        "subject": "破坏性操作确认",
                        "state": "default",
                        "property_name": "",
                        "condition_if": "If 用户触发破坏性操作",
                        "then_clause": "Then 必须先二次确认",
                    }
                ],
            )
            self.write_rules_csv(rules_dir / "component-rules.csv", [])
            (project_dir / "app.css").write_text(".page-shell { padding-top: 20px; }\n", encoding="utf-8")

            retrieved = self.run_script_with_rules_dir(
                rules_dir,
                "--format",
                "json",
                "rules-for-components",
            )
            scanned = self.run_script_with_rules_dir(
                rules_dir,
                "--format",
                "json",
                "scan-project",
                "--project",
                str(project_dir),
            )

        rows = json.loads(retrieved.stdout)
        violations = json.loads(scanned.stdout)

        self.assertEqual({row["rule_id"] for row in rows}, {"FDN-EMPTY", "LAY-EMPTY"})
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
