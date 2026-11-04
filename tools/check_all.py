"""Run every design and registry check in one place.

This is the single command CI calls. Each check is a standalone script so it can
also be run alone during development; this runner only aggregates exit codes and
keeps one authoritative list.

Usage:
    python tools/check_all.py
    python tools/check_all.py --quiet     # only failures and the summary
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHECKS: list[tuple[str, list[str]]] = [
    ("状态机契约", ["design/check_state_machines.py", "--selftest"]),
    ("动作契约", ["design/check_actions.py", "--selftest"]),
    ("接口契约", ["design/check_api_surface.py", "--selftest"]),
    ("导航与门禁策略", ["design/check_navigation.py", "--selftest"]),
    ("黄金路径样例", ["design/check_golden_path.py", "--selftest"]),
    ("测试矩阵覆盖", ["design/check_test_plan.py", "--selftest"]),
    ("文档表格与围栏", ["design/check_docs.py"]),
    ("文档标点规范", ["design/normalize_text.py", "--check"]),
    ("目录与锚点", ["design/gen_toc.py"]),
    ("Registry 一致性", ["database/generator/validate_registry.py", "--selftest"]),
    ("DDL 与 Registry 同步", ["database/generator/generate_ddl.py", "--check"]),
    ("迁移 SQL 切分正确", ["database/tests/check_migration_splitter.py"]),
    ("迁移与 DDL 同步", ["database/tests/check_migration_sync.py"]),
]


def main() -> int:
    quiet = "--quiet" in sys.argv
    failures: list[str] = []

    for label, args in CHECKS:
        proc = subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        ok = proc.returncode == 0
        print(f"{'PASS' if ok else 'FAIL'}  {label:<22} {' '.join(args)}")
        if not ok:
            failures.append(label)
            if proc.stdout.strip():
                for line in proc.stdout.strip().splitlines()[-12:]:
                    print(f"      {line}")
            if proc.stderr.strip():
                for line in proc.stderr.strip().splitlines()[-6:]:
                    print(f"      {line}")
        elif not quiet:
            tail = proc.stdout.strip().splitlines()
            if tail:
                print(f"      {tail[-1]}")

    print()
    total = len(CHECKS)
    print(f"{total - len(failures)}/{total} checks passed")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
