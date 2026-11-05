#!/usr/bin/env python3
"""PreToolUse hook shared by Claude Code and Codex: block any tool call that touches a .env file.

Reads the hook payload (JSON) from stdin and scans every string in `tool_input`
(file paths, glob patterns, shell commands, ...). If one refers to `.env` or a
variant such as `.env.local` / `backend/.env`, the call is blocked with exit code 2
(both Claude Code and Codex treat exit code 2 + stderr as "deny").
`.env.example` stays allowed because it holds no secrets.

This is a best-effort text match, not a sandbox: a deliberately obfuscated command
(e.g. `cat .e""nv`) can get past it. It guards against accidental reads.
"""

import json
import re
import sys
from collections.abc import Iterator
from typing import cast

# `.env` or `.env.<suffix>` not preceded by a name character (so `foo.env` and
# `os.environ` do not match) and not followed by one (so `.envrc` does not match).
ENV_FILE = re.compile(r"(?<![\w.-])\.env(?P<suffix>\.[\w.-]+)?(?![\w-])")
# Wildcards that can expand to .env (e.g. `.e*`, `.en?`, `.env*`).
ENV_GLOB = re.compile(r"(?<![\w.-])\.e(?:nv?)?[*?\[]")
ALLOWED_SUFFIXES = {".example"}


def strings(value: object) -> Iterator[str]:
    """Yield every string nested anywhere in a JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in cast("dict[str, object]", value).values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in cast("list[object]", value):
            yield from strings(item)


def touches_env(text: str) -> bool:
    for match in ENV_FILE.finditer(text):
        if match.group("suffix") not in ALLOWED_SUFFIXES:
            return True
    return bool(ENV_GLOB.search(text))


def main() -> int:
    try:
        payload: object = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = cast("dict[str, object]", payload).get("tool_input")
    if any(touches_env(s) for s in strings(tool_input)):
        print(
            "Blocked by project guardrail: .env files contain secrets and must not be "
            "read by AI agents. Use .env.example to learn which variables exist, or ask "
            "the user for a specific non-secret value.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
