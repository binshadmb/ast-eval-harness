# ast-eval-harness

A compact Python evaluation harness with two separate stages: AST-based static checks and optional execution inside a restricted Docker container. The analyzer never executes source. The runner does not execute submission code on the host.

## Features

- Reports restricted imports and dynamic execution calls with line and column locations.
- Returns syntax errors as structured results.
- Runs one Python submission in Docker with no network, a read-only filesystem, no Linux capabilities, a non-root UID, process and memory limits, a wall-clock timeout, and bounded output capture.
- Uses only the Python standard library at runtime.

## Limits and threat model

AST findings are review hints, not a proof of safety. Docker adds process and filesystem isolation, but containers share a host kernel. Do not use this project as a multi-tenant service for highly adversarial submissions without an additional VM or micro-VM boundary and operational hardening. The Docker image must be available locally or pulled by Docker before execution.

## Setup and tests

Requires Python 3.11+ and Docker for execution. Tests do not require Docker because they verify the analyzer and command construction only.

```sh
python -m venv .venv
# Activate the environment, then:
python -m pip install -e ".[dev]"
pytest -q
```

## Example

```python
from analyzer.ast_parser import analyze_source
from runner.sandbox import DockerRunner

source = "print('hello')"
report = analyze_source(source)
if report.passed:
    result = DockerRunner(timeout_seconds=3).run(source)
    print(result.output)
```

The runner applies a bounded timeout and output limit. Review Docker's security guidance before deploying it to evaluate untrusted submissions.
