#!/usr/bin/env python3
"""Bug 数据校验脚本 — 确定性逻辑，不依赖 LLM。

Usage:
    python validate_bugs.py --input bugs.json [--max-records 5000] [--timeout 60]
    python validate_bugs.py --input bugs.csv  [--max-records 5000] [--timeout 60]

输出: validated_bugs.json（标准格式，含统计摘要）
"""

import argparse
import csv
import io
import json
import re
import signal
import sys
from datetime import datetime
from pathlib import Path

REQUIRED_FIELDS = {"bug_id", "title", "severity"}

VALID_SEVERITIES = {"critical", "major", "minor", "trivial"}

SEVERITY_ALIASES = {
    "blocker": "critical", "fatal": "critical", "p0": "critical",
    "紧急": "critical", "致命": "critical",
    "high": "major", "p1": "major", "严重": "major", "重要": "major",
    "medium": "minor", "normal": "minor", "p2": "minor",
    "一般": "minor", "中等": "minor",
    "low": "trivial", "suggestion": "trivial", "p3": "trivial",
    "提示": "trivial", "轻微": "trivial", "建议": "trivial",
}

CSV_COLUMN_ALIASES = {
    "bug_id": ["id", "bug_id", "issue_id", "issue_key", "key", "defect_id",
               "编号", "缺陷编号"],
    "title": ["title", "summary", "name", "bug_title", "issue_title",
              "标题", "摘要", "缺陷标题"],
    "severity": ["severity", "sev", "level", "bug_level",
                 "严重程度", "严重级别", "等级"],
    "status": ["status", "state", "bug_status", "状态"],
    "module": ["module", "component", "subsystem", "模块", "组件", "子系统"],
    "affected_files": ["affected_files", "files", "file_path",
                       "related_files", "涉及文件", "相关文件"],
    "language": ["language", "lang", "编程语言", "语言"],
    "root_cause": ["root_cause", "cause", "root_cause_analysis",
                   "根因", "根因分析", "原因"],
    "fix_description": ["fix_description", "fix", "solution", "resolution",
                        "修复方案", "解决方案", "修复"],
    "pattern_tags": ["pattern_tags", "tags", "labels", "categories",
                     "标签", "分类"],
    "reporter": ["reporter", "reported_by", "creator", "author",
                 "报告人", "创建人"],
    "assignee": ["assignee", "assigned_to", "owner", "handler",
                 "处理人", "负责人"],
    "project": ["project", "project_name", "project_key", "项目", "项目名"],
    "created_at": ["created_at", "created", "create_date", "create_time",
                   "创建时间", "创建日期"],
    "resolved_at": ["resolved_at", "resolved", "resolve_date",
                    "closed_at", "closed_date", "解决时间", "关闭时间"],
    "description": ["description", "desc", "detail", "details",
                    "描述", "详细描述", "详情"],
    "priority": ["priority", "pri", "优先级"],
    "url": ["url", "link", "issue_url", "链接"],
}

DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d",
    "%d/%m/%Y",
]

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_DESCRIPTION_LEN = 10_000
MAX_FILES_PER_BUG = 50
MAX_TAGS_PER_BUG = 20


def timeout_handler(signum, frame):
    print(json.dumps({"error": "Validation timed out"}, ensure_ascii=False))
    sys.exit(1)


def parse_date(val: str) -> str | None:
    if not val or not val.strip():
        return None
    val = val.strip()
    for fmt in DATE_FORMATS:
        try:
            datetime.strptime(val, fmt)
            return val
        except ValueError:
            continue
    return None


def normalize_severity(raw: str) -> str | None:
    s = raw.strip().lower()
    if s in VALID_SEVERITIES:
        return s
    return SEVERITY_ALIASES.get(s)


def strip_abs_path(p: str) -> str:
    p = p.strip()
    p = re.sub(r"^[A-Za-z]:\\", "", p)
    p = re.sub(r"^/(?:home|Users|opt|var|tmp|workspace)/\S+?/", "", p)
    return p.lstrip("/")


def split_list_field(val: str) -> list[str]:
    if not val or not val.strip():
        return []
    for sep in [";", "|"]:
        if sep in val:
            return [x.strip() for x in val.split(sep) if x.strip()]
    return [x.strip() for x in val.split(",") if x.strip()]


def normalize_tag(tag: str) -> str:
    tag = tag.strip().lower()
    tag = re.sub(r"([a-z])([A-Z])", r"\1_\2", tag).lower()
    tag = re.sub(r"[\s\-]+", "_", tag)
    tag = re.sub(r"[^a-z0-9_\u4e00-\u9fff]", "", tag)
    return tag


def build_csv_mapping(headers: list[str]) -> dict[str, str]:
    mapping = {}
    lower_headers = [h.strip().lower() for h in headers]
    for std_field, aliases in CSV_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lower_headers:
                idx = lower_headers.index(alias.lower())
                mapping[headers[idx]] = std_field
                break
    return mapping


def read_csv(path: Path) -> list[dict]:
    raw = path.read_bytes()
    for encoding in ["utf-8-sig", "utf-8", "gbk", "gb2312", "latin1"]:
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []

    col_map = build_csv_mapping(list(reader.fieldnames))
    rows = []
    for row in reader:
        mapped = {}
        for orig_col, value in row.items():
            std = col_map.get(orig_col, orig_col)
            if std in ("affected_files", "pattern_tags", "labels"):
                mapped[std] = split_list_field(value or "")
            else:
                mapped[std] = (value or "").strip()
        rows.append(mapped)
    return rows


def read_json(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("bugs", "records", "items", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]
    return []


def validate_record(rec: dict, seen_ids: set) -> tuple[dict | None, str | None]:
    bug_id = str(rec.get("bug_id", "")).strip()
    if not bug_id:
        return None, "missing_bug_id"

    if len(bug_id) > 128:
        bug_id = bug_id[:128]

    title = str(rec.get("title", "")).strip()
    if not title:
        return None, "missing_title"
    if len(title) > 512:
        title = title[:512]

    raw_sev = str(rec.get("severity", "")).strip()
    severity = normalize_severity(raw_sev)
    if not severity:
        return None, "invalid_severity"

    if bug_id in seen_ids:
        return None, "duplicate"
    seen_ids.add(bug_id)

    result = {
        "bug_id": bug_id,
        "title": title,
        "severity": severity,
    }

    for field in ["status", "module", "language", "root_cause",
                  "fix_description", "reporter", "assignee",
                  "project", "priority", "url", "environment"]:
        val = rec.get(field)
        if val and str(val).strip():
            result[field] = str(val).strip()

    desc = rec.get("description", "")
    if desc and str(desc).strip():
        d = str(desc).strip()
        if len(d) > MAX_DESCRIPTION_LEN:
            d = d[:MAX_DESCRIPTION_LEN] + "...[truncated]"
        result["description"] = d

    for date_field in ["created_at", "resolved_at"]:
        raw = rec.get(date_field, "")
        if raw:
            parsed = parse_date(str(raw))
            if parsed:
                result[date_field] = parsed

    af = rec.get("affected_files", [])
    if isinstance(af, str):
        af = split_list_field(af)
    af = [strip_abs_path(str(f)) for f in af if str(f).strip()]
    if af:
        result["affected_files"] = af[:MAX_FILES_PER_BUG]

    tags = rec.get("pattern_tags", [])
    if isinstance(tags, str):
        tags = split_list_field(tags)
    tags = [normalize_tag(str(t)) for t in tags if str(t).strip()]
    tags = [t for t in tags if t]
    if tags:
        result["pattern_tags"] = tags[:MAX_TAGS_PER_BUG]

    labels = rec.get("labels", [])
    if isinstance(labels, str):
        labels = split_list_field(labels)
    if labels:
        result["labels"] = [str(l).strip() for l in labels if str(l).strip()]

    return result, None


def main():
    parser = argparse.ArgumentParser(description="Validate bug import data")
    parser.add_argument("--input", required=True, help="Input file (JSON or CSV)")
    parser.add_argument("--max-records", type=int, default=5000)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", default="validated_bugs.json")
    args = parser.parse_args()

    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(args.timeout)

    path = Path(args.input)
    if not path.exists():
        print(json.dumps({"error": f"File not found: {args.input}"},
                         ensure_ascii=False))
        sys.exit(1)

    if path.stat().st_size > MAX_FILE_SIZE:
        print(json.dumps({"error": f"File too large (>{MAX_FILE_SIZE // 1024 // 1024}MB), please split"},
                         ensure_ascii=False))
        sys.exit(1)

    suffix = path.suffix.lower()
    if suffix == ".csv":
        records = read_csv(path)
    elif suffix in (".json", ".jsonl"):
        records = read_json(path)
    else:
        print(json.dumps({"error": f"Unsupported format: {suffix}"},
                         ensure_ascii=False))
        sys.exit(1)

    truncated = False
    if len(records) > args.max_records:
        records = records[:args.max_records]
        truncated = True

    valid = []
    skip_reasons: dict[str, int] = {}
    seen_ids: set[str] = set()

    for rec in records:
        result, reason = validate_record(rec, seen_ids)
        if result:
            valid.append(result)
        else:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    output = {
        "total_input": len(records),
        "valid": len(valid),
        "skipped": sum(skip_reasons.values()),
        "skipped_reasons": skip_reasons,
        "truncated": truncated,
        "records": valid,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    summary = {k: v for k, v in output.items() if k != "records"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
