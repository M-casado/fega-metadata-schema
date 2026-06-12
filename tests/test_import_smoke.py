from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_fega_tools_modules_import() -> None:
    """Check that the main helper modules can be imported."""
    modules = [
        "fega_tools.biovalidator",
        "fega_tools.io",
        "fega_tools.json_pointer",
        "fega_tools.jsonld_coverage",
        "fega_tools.jsonld_utils",
        "fega_tools.logging_utils",
        "fega_tools.rdf_utils",
        "fega_tools.validation_common",
    ]

    for module in modules:
        importlib.import_module(module)


def test_validation_scripts_show_help() -> None:
    """Check that each validation script can start and show its help text."""
    scripts = [
        "scripts/py/schema_diff.py",
        "scripts/py/validate_examples.py",
        "scripts/py/validate_jsonld_contexts.py",
        "scripts/py/validate_jsonld_coverage.py",
        "scripts/py/validate_jsonld_frames.py",
        "scripts/py/validate_metadata.py",
        "scripts/py/validate_rdf_shacl.py",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")

    for script in scripts:
        result = subprocess.run(
            [sys.executable, script, "--help"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout.lower()
