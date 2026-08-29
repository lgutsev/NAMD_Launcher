"""Trivial ``@TOKEN@`` templating.

Fortran namelists and Python driver files contain braces and ``$`` freely, so
``str.format`` / ``string.Template`` are more trouble than they are worth here.
Every placeholder is spelled ``@NAME@`` and every one must be supplied.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"@([A-Z0-9_]+)@")


def render(text: str, values: dict[str, object]) -> str:
    missing: set[str] = set()

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.add(key)
            return match.group(0)
        return str(values[key])

    out = _TOKEN.sub(_sub, text)
    if missing:
        raise KeyError(f"template placeholders not provided: {', '.join(sorted(missing))}")
    return out


def fortran_bool(value: bool) -> str:
    return ".TRUE." if value else ".FALSE."


def python_bool(value: bool) -> str:
    return "True" if value else "False"
