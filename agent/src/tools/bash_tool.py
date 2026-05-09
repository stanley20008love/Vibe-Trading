"""Bash tool: execute shell commands under run_dir.

⚠️  SECURITY WARNING: This tool executes arbitrary shell commands. A denylist
blocks network exfiltration, reverse-shell, and destructive patterns, but it
is NOT a complete sandbox. A determined attacker with LLM access may find
bypasses (e.g. encoding tricks, lesser-known utilities). Deploy this tool
only in environments where the LLM is trusted or where additional OS-level
containment (containers, seccomp, network namespaces) is in place.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from src.agent.tools import BaseTool

_OUTPUT_LIMIT = 50_000
_DEFAULT_TIMEOUT = 120

# ---------------------------------------------------------------------------
# Command denylist — blocks network exfiltration, reverse shells, and
# destructive commands.  Checked before execution; a match rejects the command.
# ---------------------------------------------------------------------------
_COMMAND_DENYLIST: list[re.Pattern[str]] = [
    re.compile(r"\bcurl\b", re.IGNORECASE),
    re.compile(r"\bwget\b", re.IGNORECASE),
    re.compile(r"\bnc\b"),
    re.compile(r"\bncat\b", re.IGNORECASE),
    re.compile(r"\bssh\b", re.IGNORECASE),
    re.compile(r"\bscp\b", re.IGNORECASE),
    re.compile(r"\brsync\b", re.IGNORECASE),
    re.compile(r"\bpython\s+-c\b"),
    re.compile(r"\bpython3\s+-c\b"),
    re.compile(r"\beval\b"),
    re.compile(r"\bexec\b"),
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bmkfifo\b", re.IGNORECASE),
    re.compile(r"/dev/tcp"),
    re.compile(r"\bbase64\s+-d\b"),
    re.compile(r"\bopenssl\b", re.IGNORECASE),
    # Pipe-based exfiltration: redirecting into /dev/tcp or known exfil helpers
    re.compile(r"\|\s*(?:nc|ncat|curl|wget|openssl|socat)\b", re.IGNORECASE),
]


def _is_command_allowed(command: str) -> tuple[bool, str]:
    """Return (allowed, reason) after checking the command against the denylist."""
    for pattern in _COMMAND_DENYLIST:
        if pattern.search(command):
            return False, f"Command denied: matches denied pattern '{pattern.pattern}'"
    return True, ""


class BashTool(BaseTool):
    """Execute shell commands in the working directory."""

    name = "bash"
    description = "Execute a shell command in the working directory. Use for installing packages, running scripts, or inspecting files."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
        },
        "required": ["command"],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        """Execute a shell command.

        Args:
            **kwargs: Must include command. Optional run_dir used as cwd.

        Returns:
            JSON string with stdout, stderr, and exit_code.
        """
        command = kwargs["command"]
        cwd = kwargs.get("run_dir")

        allowed, reason = _is_command_allowed(command)
        if not allowed:
            return json.dumps({"status": "error", "error": reason}, ensure_ascii=False)

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_DEFAULT_TIMEOUT,
                encoding="utf-8",
                errors="replace",
            )
            stdout = result.stdout[:_OUTPUT_LIMIT] if len(result.stdout) > _OUTPUT_LIMIT else result.stdout
            stderr = result.stderr[:_OUTPUT_LIMIT] if len(result.stderr) > _OUTPUT_LIMIT else result.stderr
            return json.dumps({
                "status": "ok" if result.returncode == 0 else "error",
                "exit_code": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({
                "status": "error",
                "error": f"Command timed out after {_DEFAULT_TIMEOUT}s",
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": str(exc),
            }, ensure_ascii=False)
