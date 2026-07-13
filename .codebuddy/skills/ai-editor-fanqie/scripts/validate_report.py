#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate a generated Fanqie diagnostic report against scoring.md.

The validator checks structural integrity without owning scoring rules. Component
maxima, dimension names, and weights are read from the sibling references file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ComponentRule:
    name: str
    maximum: int
    dimension: str


@dataclass(frozen=True)
class DimensionRule:
    name: str
    maximum: int
    weight: Decimal


@dataclass(frozen=True)
class RatingRule:
    minimum: int
    maximum: int
    label: str


@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]
    metrics: dict[str, object]

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize_text(value: str) -> str:
    value = value.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", value).strip()


def parse_scoring(path: Path) -> tuple[list[DimensionRule], list[ComponentRule], list[RatingRule]]:
    text = path.read_text(encoding="utf-8")
    dimensions: list[DimensionRule] = []
    components: list[ComponentRule] = []
    ratings: list[RatingRule] = []
    current_dimension = ""

    dimension_re = re.compile(r"^##\s+[^、]+、(.+?)，满分\s*(\d+)\s*分")
    component_heading_re = re.compile(r"^###\s+\d+\.\s*(.+?)，满分\s*(\d+)\s*分")
    component_bullet_re = re.compile(r"^-\s+\*\*(.+?)，\s*(\d+)\s*分\*\*")
    weight_re = re.compile(r"^-\s*(.+?)：\s*(\d+(?:\.\d+)?)%")
    rating_less_re = re.compile(r"^-\s*最终总分\s*<\s*(\d+)\s*分：\*\*(.+?)\*\*")
    rating_range_re = re.compile(r"^-\s*最终总分\s*(\d+)\s*至\s*(\d+)\s*分：\*\*(.+?)\*\*")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        dimension_match = dimension_re.match(line)
        if dimension_match:
            current_dimension = dimension_match.group(1).strip()
            dimensions.append(
                DimensionRule(
                    name=current_dimension,
                    maximum=int(dimension_match.group(2)),
                    weight=Decimal("0"),
                )
            )
            continue

        heading_match = component_heading_re.match(line)
        if heading_match and current_dimension == "平台匹配度":
            components.append(
                ComponentRule(
                    name=heading_match.group(1).strip(),
                    maximum=int(heading_match.group(2)),
                    dimension=current_dimension,
                )
            )
            continue

        bullet_match = component_bullet_re.match(line)
        if bullet_match and current_dimension:
            components.append(
                ComponentRule(
                    name=bullet_match.group(1).strip(),
                    maximum=int(bullet_match.group(2)),
                    dimension=current_dimension,
                )
            )

        weight_match = weight_re.match(line)
        if weight_match:
            weight_name = weight_match.group(1).strip()
            for index, dimension in enumerate(dimensions):
                if dimension.name == weight_name:
                    dimensions[index] = DimensionRule(
                        name=dimension.name,
                        maximum=dimension.maximum,
                        weight=Decimal(weight_match.group(2)),
                    )

        rating_less_match = rating_less_re.match(line)
        if rating_less_match:
            ratings.append(
                RatingRule(
                    minimum=0,
                    maximum=int(rating_less_match.group(1)) - 1,
                    label=rating_less_match.group(2).strip(),
                )
            )
            continue
        rating_range_match = rating_range_re.match(line)
        if rating_range_match:
            ratings.append(
                RatingRule(
                    minimum=int(rating_range_match.group(1)),
                    maximum=int(rating_range_match.group(2)),
                    label=rating_range_match.group(3).strip(),
                )
            )

    if not dimensions:
        raise ValueError(f"No dimensions found in scoring file: {path}")
    if not components:
        raise ValueError(f"No components found in scoring file: {path}")
    missing_weights = [d.name for d in dimensions if d.weight == 0]
    if missing_weights:
        raise ValueError(f"Missing dimension weights: {', '.join(missing_weights)}")
    if not ratings:
        raise ValueError(f"No rating mappings found in scoring file: {path}")
    return dimensions, components, ratings


def split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or stripped.count("|") < 4:
        return None
    cells = [normalize_text(cell) for cell in stripped.strip("|").split("|")]
    if len(cells) < 4 or all(set(cell) <= {"-", ":"} for cell in cells):
        return None
    return cells


def table_rows(text: str) -> Iterable[list[str]]:
    for line in text.splitlines():
        row = split_table_row(line)
        if row is not None:
            yield row


def parse_score(value: str) -> int | None:
    value = normalize_text(value)
    if re.fullmatch(r"\d+", value):
        return int(value)
    return None


def parse_decimal(value: str) -> Decimal | None:
    value = normalize_text(value).rstrip("%")
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return Decimal(value)
    return None


def extract_evidence_ids(text: str) -> list[int]:
    section_match = re.search(
        r"## 【核心证据索引】(.*?)(?=\n---|\n## 【|\Z)",
        text,
        flags=re.S,
    )
    if not section_match:
        return []
    return [int(value) for value in re.findall(r"\|\s*E(\d+)\s*\|", section_match.group(1))]


def extract_referenced_evidence(text: str) -> set[int]:
    text_without_index = re.sub(
        r"## 【核心证据索引】.*?(?=\n---|\n## 【|\Z)",
        "",
        text,
        flags=re.S,
    )
    return {int(value) for value in re.findall(r"\bE(\d+)\b", text_without_index)}


def unresolved_placeholders(text: str) -> list[str]:
    patterns = [
        r"\bFORMULA\b",
        r"\bRATING\b",
        r"\bE#\b",
        r"\b[MW]\b",
        r"\[从 scoring\.md[^\]]*\]",
        r"\[按 scoring\.md[^\]]*\]",
        r"\[(?:位置|用途|章节或段落|引文或事实|事实概述|章节或段落)[^\]]*\]",
        r"\[[^\]\n]{1,80}\](?!\()",
        r"(?<![A-Za-z])X(?![A-Za-z])",
        r"\bX/M\b",
    ]
    found: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            found.append(match.group(0))
    return list(dict.fromkeys(found))


def validate_report(
    report_path: Path,
    scoring_path: Path,
    min_chars: int,
    max_chars: int,
) -> ValidationResult:
    text = report_path.read_text(encoding="utf-8")
    dimensions, components, ratings = parse_scoring(scoring_path)
    errors: list[str] = []
    warnings: list[str] = []
    rows = list(table_rows(text))
    row_by_name = {row[0]: row for row in rows if row}

    placeholders = unresolved_placeholders(text)
    if placeholders:
        errors.append("Unresolved template placeholders: " + ", ".join(placeholders))

    evidence_id_list = extract_evidence_ids(text)
    evidence_ids = set(evidence_id_list)
    referenced_ids = extract_referenced_evidence(text)
    if len(evidence_ids) < 6:
        errors.append(f"Evidence index has {len(evidence_ids)} entries; at least 6 are required")
    if len(evidence_ids) > 10:
        warnings.append(f"Evidence index has {len(evidence_ids)} entries; standard target is 6-10")
    duplicate_ids = sorted({value for value in evidence_id_list if evidence_id_list.count(value) > 1})
    if duplicate_ids:
        errors.append("Duplicate evidence IDs: " + ", ".join(f"E{value}" for value in duplicate_ids))
    if evidence_ids:
        expected_ids = set(range(1, max(evidence_ids) + 1))
        skipped_ids = sorted(expected_ids - evidence_ids)
        if skipped_ids:
            errors.append("Evidence IDs are not contiguous; missing: " + ", ".join(f"E{value}" for value in skipped_ids))
    missing_ids = sorted(referenced_ids - evidence_ids)
    if missing_ids:
        errors.append("Referenced evidence IDs are missing from the index: " + ", ".join(f"E{value}" for value in missing_ids))
    unused_ids = sorted(evidence_ids - referenced_ids)
    if unused_ids:
        warnings.append("Evidence entries are not referenced: " + ", ".join(f"E{value}" for value in unused_ids))

    component_scores: dict[str, int] = {}
    component_na: set[str] = set()
    component_rows_found = 0
    for rule in components:
        row = row_by_name.get(rule.name)
        if row is None:
            errors.append(f"Missing component row: {rule.name}")
            continue
        score = parse_score(row[1].replace("/ N/A", ""))
        maximum = parse_score(row[2])
        if maximum != rule.maximum:
            errors.append(f"{rule.name}: maximum is {row[2]!r}, expected {rule.maximum}")
        if score is None:
            if rule.name != "分类榜单热度" or "N/A" not in row[1]:
                errors.append(f"{rule.name}: score is not a numeric value")
            else:
                component_na.add(rule.name)
        else:
            if score < 0 or score > rule.maximum:
                errors.append(f"{rule.name}: score {score} is outside 0-{rule.maximum}")
            component_scores[rule.name] = score
        if not re.search(r"\bE\d+\b", row[3]) and not re.search(r"缺失|未提供|没有|未能核验|不适用", row[3]):
            errors.append(f"{rule.name}: evidence reference or missing reason is absent")
        component_rows_found += 1

    dimension_scores: dict[str, int] = {}
    for rule in dimensions:
        row = row_by_name.get(rule.name)
        if row is None:
            errors.append(f"Missing dimension total row: {rule.name}")
            continue
        score = parse_score(row[1])
        weight = parse_decimal(row[2])
        weighted_value = parse_decimal(row[3])
        if score is None:
            errors.append(f"{rule.name}: dimension total is not numeric")
        elif score < 0 or score > rule.maximum:
            errors.append(f"{rule.name}: dimension total {score} is outside 0-{rule.maximum}")
        else:
            dimension_scores[rule.name] = score
        if weight != rule.weight:
            errors.append(f"{rule.name}: weight is {row[2]!r}, expected {rule.weight}%")
        if score is not None and weight is not None:
            expected_weighted = Decimal(score) * weight / Decimal("100")
            if weighted_value is None:
                errors.append(f"{rule.name}: weighted result is not numeric")
            elif weighted_value != expected_weighted:
                errors.append(
                    f"{rule.name}: weighted result {weighted_value} does not match {expected_weighted}"
                )

    for dimension in dimensions:
        rules = [rule for rule in components if rule.dimension == dimension.name]
        if not rules or dimension.name not in dimension_scores:
            continue
        missing_component_scores = [
            rule.name for rule in rules if rule.name not in component_scores and rule.name not in component_na
        ]
        if missing_component_scores:
            continue
        numeric_sum = sum(component_scores.get(rule.name, 0) for rule in rules)
        if dimension.name == "平台匹配度" and "分类榜单热度" in component_na:
            heat_rule = next(rule for rule in rules if rule.name == "分类榜单热度")
            available_maximum = dimension.maximum - heat_rule.maximum
            expected_dimension = int(
                (Decimal(numeric_sum) / Decimal(available_maximum) * Decimal(dimension.maximum)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        else:
            expected_dimension = numeric_sum
        if dimension_scores[dimension.name] != expected_dimension:
            errors.append(
                f"{dimension.name}: dimension total {dimension_scores[dimension.name]} "
                f"does not match component result {expected_dimension}"
            )

    final_match = re.search(r"最终总分.*?[：:]\s*\*\*(\d+)\s*/\s*(\d+)\*\*", text)
    final_score = int(final_match.group(1)) if final_match else None
    final_maximum = int(final_match.group(2)) if final_match else None
    expected_maximum = max((dimension.maximum for dimension in dimensions), default=100)
    if final_score is None:
        errors.append("Missing numeric final score")
    elif final_score < 0 or final_score > expected_maximum:
        errors.append(f"Final score {final_score} is outside 0-{expected_maximum}")
    if final_maximum is not None and final_maximum != expected_maximum:
        errors.append(f"Final score maximum is {final_maximum}, expected {expected_maximum}")
    if not re.search(r"最终总分\s*=\s*round", text):
        errors.append("Missing final score formula")

    rating_match = re.search(r"终审评级.*?[：:]\s*(.+)", text)
    report_rating = normalize_text(rating_match.group(1)) if rating_match else ""
    if not report_rating:
        errors.append("Missing final rating")
    elif final_score is not None:
        expected_rating = next(
            (rule.label for rule in ratings if rule.minimum <= final_score <= rule.maximum),
            None,
        )
        if expected_rating is None:
            errors.append(f"No rating mapping covers final score {final_score}")
        elif report_rating != expected_rating:
            errors.append(f"Final rating {report_rating!r} does not match {expected_rating!r}")

    expected_total: Decimal | None = None
    if all(rule.name in dimension_scores for rule in dimensions):
        expected_total = sum(
            (Decimal(dimension_scores[rule.name]) * rule.weight / Decimal("100") for rule in dimensions),
            Decimal("0"),
        )
        rounded_total = int(expected_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if final_score is not None and final_score != rounded_total:
            errors.append(f"Final score {final_score} does not match weighted total {rounded_total}")

    content_chars = sum(1 for char in text if not char.isspace())
    if content_chars < min_chars:
        warnings.append(f"Report has {content_chars} non-whitespace characters; target starts at {min_chars}")
    if content_chars > max_chars:
        warnings.append(f"Report has {content_chars} non-whitespace characters; target ends at {max_chars}")

    metrics = {
        "content_chars": content_chars,
        "evidence_count": len(evidence_ids),
        "component_rows": component_rows_found,
        "component_scores": component_scores,
        "dimension_scores": dimension_scores,
        "weighted_total": str(expected_total) if expected_total is not None else None,
        "final_score": final_score,
        "final_rating": report_rating or None,
    }
    return ValidationResult(errors=errors, warnings=warnings, metrics=metrics)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a generated Fanqie diagnostic report")
    parser.add_argument("report", type=Path, help="Generated Markdown report")
    parser.add_argument(
        "--scoring",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "references" / "scoring.md",
        help="Scoring reference; defaults to this skill's references/scoring.md",
    )
    parser.add_argument("--min-chars", type=int, default=3000, help="Warning threshold for report length")
    parser.add_argument("--max-chars", type=int, default=5000, help="Warning threshold for report length")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    try:
        result = validate_report(args.report, args.scoring, args.min_chars, args.max_chars)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = {"ok": result.ok, "errors": result.errors, "warnings": result.warnings, "metrics": result.metrics}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for error in result.errors:
            print(f"ERROR: {error}")
        for warning in result.warnings:
            print(f"WARNING: {warning}")
        if result.ok:
            print(
                "OK: report structure, evidence references, score ranges, and weighted total are valid "
                f"({result.metrics['content_chars']} non-whitespace characters)"
            )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
