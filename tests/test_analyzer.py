from __future__ import annotations

import unittest
from pathlib import Path

from analyzer.ast_parser import analyze_source
from runner.sandbox import DockerRunner, build_docker_command


class AnalyzerTests(unittest.TestCase):
    def test_clean_source_passes(self) -> None:
        report = analyze_source("def add(a, b):\n    return a + b\n")
        self.assertTrue(report.passed)
        self.assertEqual(report.findings, ())

    def test_restricted_import_is_reported_with_location(self) -> None:
        report = analyze_source("import subprocess\n")
        self.assertEqual(report.findings[0].code, "E001")
        self.assertEqual(report.findings[0].line, 1)

    def test_dynamic_execution_is_reported(self) -> None:
        report = analyze_source("result = eval(user_input)\n")
        self.assertEqual(report.findings[0].code, "E002")

    def test_syntax_error_is_returned(self) -> None:
        report = analyze_source("def broken(:\n    pass\n")
        self.assertIsNotNone(report.syntax_error)
        self.assertFalse(report.passed)

    def test_source_size_limit(self) -> None:
        with self.assertRaises(ValueError):
            analyze_source("x = 1", max_source_bytes=2)


class SandboxCommandTests(unittest.TestCase):
    def test_command_has_container_restrictions_and_no_shell(self) -> None:
        command = build_docker_command(Path("C:/tmp/submission with spaces"), Path("C:/tmp/cid"))
        self.assertIn("--network=none", command)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertIn("--pids-limit=32", command)
        self.assertEqual(command[-3:], ["python", "-I", "/submission/main.py"])

    def test_runner_rejects_invalid_limits(self) -> None:
        with self.assertRaises(ValueError):
            DockerRunner(timeout_seconds=0)
        with self.assertRaises(ValueError):
            DockerRunner(max_output_bytes=0)


if __name__ == "__main__":
    unittest.main()
