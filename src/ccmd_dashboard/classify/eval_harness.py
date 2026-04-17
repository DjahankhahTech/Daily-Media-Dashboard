"""AOR tagger evaluation harness.

Reads a hand-labeled eval set (JSONL), runs the tagger on each record, and
computes per-CCMD precision / recall / F1 plus a macro average. Used at
startup (print) and in tests (assert thresholds).

JSONL schema (one object per line):

    {
      "id": "short-id",
      "title": "...",
      "body": "...",
      "gold_ccmds": ["INDOPACOM", "CENTCOM"]
    }

An empty "gold_ccmds" list means "should be unassigned".
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .aor_tagger import tag_article


@dataclass
class EvalRecord:
    id: str
    title: str
    body: str
    gold_ccmds: set[str]


@dataclass
class PerCCMDCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    def f1(self) -> float:
        p, r = self.precision(), self.recall()
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class EvalReport:
    per_ccmd: dict[str, PerCCMDCounts] = field(default_factory=dict)
    n_records: int = 0
    unassigned_correct: int = 0
    unassigned_wrong: int = 0

    def macro_f1(self) -> float:
        if not self.per_ccmd:
            return 0.0
        return sum(c.f1() for c in self.per_ccmd.values()) / len(self.per_ccmd)

    def as_table(self) -> str:
        lines = [
            f"AOR eval: {self.n_records} records, macro-F1={self.macro_f1():.3f}",
            f"{'CCMD':<12}{'P':>8}{'R':>8}{'F1':>8}{'TP':>6}{'FP':>6}{'FN':>6}",
        ]
        for code in sorted(self.per_ccmd):
            c = self.per_ccmd[code]
            lines.append(
                f"{code:<12}{c.precision():>8.3f}{c.recall():>8.3f}{c.f1():>8.3f}"
                f"{c.tp:>6}{c.fp:>6}{c.fn:>6}"
            )
        lines.append(
            f"unassigned: {self.unassigned_correct} correct / "
            f"{self.unassigned_wrong} wrong"
        )
        return "\n".join(lines)


def load_eval_set(path: Path) -> list[EvalRecord]:
    records: list[EvalRecord] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        obj: dict[str, Any] = json.loads(line)
        records.append(
            EvalRecord(
                id=obj["id"],
                title=obj["title"],
                body=obj.get("body", ""),
                gold_ccmds=set(obj.get("gold_ccmds", [])),
            )
        )
    return records


def evaluate(records: Iterable[EvalRecord]) -> EvalReport:
    report = EvalReport()
    for rec in records:
        report.n_records += 1
        predicted = {m.ccmd_code for m in tag_article(rec.title, rec.body)}
        gold = rec.gold_ccmds

        if not gold:
            if not predicted:
                report.unassigned_correct += 1
            else:
                report.unassigned_wrong += 1

        all_codes = predicted | gold
        for code in all_codes:
            c = report.per_ccmd.setdefault(code, PerCCMDCounts())
            if code in gold and code in predicted:
                c.tp += 1
            elif code in predicted:
                c.fp += 1
            else:
                c.fn += 1
    return report
