from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    line: int
    column: int
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    findings: tuple[Finding, ...]
    syntax_error: str | None = None

    @property
    def passed(self) -> bool:
        return self.syntax_error is None and not self.findings


BLOCKED_IMPORTS = frozenset(
    {"ctypes", "multiprocessing", "os", "pty", "resource", "socket", "subprocess"}
)
BLOCKED_CALLS = frozenset({"__import__", "compile", "eval", "exec"})
BLOCKED_ATTRIBUTES = frozenset(
    {"fork", "popen", "spawn", "system", "startfile", "execv", "execve"}
)


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def _add(self, node: ast.AST, code: str, message: str) -> None:
        self.findings.append(
            Finding(
                line=getattr(node, "lineno", 1),
                column=getattr(node, "col_offset", 0) + 1,
                code=code,
                message=message,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root in BLOCKED_IMPORTS:
                self._add(node, "E001", f"restricted import: {root}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if root in BLOCKED_IMPORTS:
            self._add(node, "E001", f"restricted import: {root}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            self._add(node, "E002", f"restricted dynamic call: {node.func.id}")
        if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_ATTRIBUTES:
            self._add(node, "E003", f"restricted process or system call: {node.func.attr}")
        self.generic_visit(node)


def analyze_source(source: str, max_source_bytes: int = 1_000_000) -> AnalysisReport:
    """Parse source and report a small set of risky constructs.

    Findings are review signals, not proof that code is safe or unsafe. Execution
    isolation is handled separately by the Docker runner.
    """
    if max_source_bytes < 1:
        raise ValueError("max_source_bytes must be positive")
    if len(source.encode("utf-8")) > max_source_bytes:
        raise ValueError("source exceeds max_source_bytes")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return AnalysisReport((), f"line {exc.lineno}: {exc.msg}")

    visitor = _Visitor()
    visitor.visit(tree)
    findings = tuple(sorted(visitor.findings, key=lambda item: (item.line, item.column, item.code)))
    return AnalysisReport(findings)
