from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_IMPORTS = {"django", "rest_framework", "celery", "psycopg", "redis", "adapters", "config"}


def test_core_has_no_framework_or_adapter_imports() -> None:
    core_dir = Path(__file__).resolve().parents[2] / "core"
    python_files = sorted(core_dir.rglob("*.py"))
    assert python_files, "backend/core deve conter módulos de domínio."

    violations: list[str] = []
    for file_path in python_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    if root_pkg in FORBIDDEN_IMPORTS:
                        violations.append(f"{file_path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_pkg = node.module.split(".")[0]
                if root_pkg in FORBIDDEN_IMPORTS:
                    violations.append(f"{file_path.name}: from {node.module}")

    assert not violations, f"Violação hexagonal encontrada em core/: {violations}"
