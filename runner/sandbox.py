from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunResult:
    returncode: int | None
    output: str
    timed_out: bool = False
    output_limited: bool = False
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.output_limited and self.error is None


def build_docker_command(
    submission_dir: Path,
    cid_file: Path,
    image: str = "python:3.12-slim",
) -> list[str]:
    """Build a shell-free Docker command with restrictive runtime defaults."""
    mount = f"type=bind,source={submission_dir.resolve()},target=/submission,readonly"
    return [
        "docker", "run", "--rm", f"--cidfile={cid_file}",
        "--network=none", "--read-only", "--cpus=0.5",
        "--memory=128m", "--memory-swap=128m", "--pids-limit=32",
        "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
        "--user=65534:65534",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--mount", mount, "--workdir", "/tmp", image,
        "python", "-I", "/submission/main.py",
    ]


class DockerRunner:
    """Run one Python file inside a restricted Docker container.

    The runner never executes submission code directly on the host. Docker must
    be installed and available to the current user. Container isolation is a
    useful boundary, not a proof against kernel or runtime vulnerabilities.
    """

    def __init__(
        self,
        timeout_seconds: float = 5.0,
        max_output_bytes: int = 65_536,
        image: str = "python:3.12-slim",
        docker_executable: str = "docker",
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.image = image
        self.docker_executable = docker_executable

    def run(self, source: str) -> RunResult:
        docker = shutil.which(self.docker_executable)
        if docker is None:
            return RunResult(None, "", error="Docker executable was not found on PATH")

        with tempfile.TemporaryDirectory(prefix="ast-eval-") as folder:
            workdir = Path(folder)
            (workdir / "main.py").write_text(source, encoding="utf-8")
            cid_file = workdir / "container-id.txt"
            command = build_docker_command(workdir, cid_file, self.image)
            command[0] = docker
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    shell=False,
                )
            except OSError as exc:
                return RunResult(None, "", error=f"could not start Docker: {exc}")

            output = bytearray()
            exceeded = threading.Event()

            def drain_output() -> None:
                assert process.stdout is not None
                while True:
                    chunk = process.stdout.read(4096)
                    if not chunk:
                        return
                    remaining = self.max_output_bytes - len(output)
                    if remaining > 0:
                        output.extend(chunk[:remaining])
                    if len(chunk) > max(remaining, 0):
                        exceeded.set()

            reader = threading.Thread(target=drain_output, daemon=True)
            reader.start()
            deadline = time.monotonic() + self.timeout_seconds
            timed_out = False
            output_limited = False

            while process.poll() is None:
                if exceeded.is_set():
                    output_limited = True
                    self._kill_container(cid_file)
                    process.terminate()
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    self._kill_container(cid_file)
                    process.terminate()
                    break
                time.sleep(0.02)

            try:
                returncode = process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait(timeout=1.0)
            reader.join(timeout=1.0)
            decoded = bytes(output).decode("utf-8", errors="replace")
            return RunResult(returncode, decoded, timed_out, output_limited)

    @staticmethod
    def _kill_container(cid_file: Path) -> None:
        # The CID file can appear just after Docker starts the container.
        deadline = time.monotonic() + 0.75
        while time.monotonic() < deadline:
            try:
                container_id = cid_file.read_text(encoding="utf-8").strip()
            except OSError:
                container_id = ""
            if container_id:
                try:
                    subprocess.run(
                        ["docker", "kill", container_id],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.0,
                        check=False,
                        shell=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
                return
            time.sleep(0.025)
