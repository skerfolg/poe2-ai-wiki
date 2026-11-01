"""Stable code-object identity independent of marshal's object-reference flags."""

from __future__ import annotations

import hashlib
import json
from types import CodeType
from typing import Any


def _constant(value: Any) -> Any:
    if isinstance(value, CodeType):
        return ["code", _code(value)]
    if value is None or isinstance(value, bool | str):
        return [type(value).__name__, value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        return ["float", value.hex()]
    if isinstance(value, complex):
        return ["complex", value.real.hex(), value.imag.hex()]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, tuple):
        return ["tuple", [_constant(part) for part in value]]
    if isinstance(value, frozenset):
        parts = [_constant(part) for part in value]
        return ["frozenset", sorted(parts, key=lambda part: json.dumps(part, sort_keys=True))]
    if value is Ellipsis:
        return ["ellipsis"]
    raise ValueError(f"Unsupported code constant type: {type(value).__name__}")


def _code(code: CodeType) -> dict[str, Any]:
    return {
        "bytecode": code.co_code.hex(),
        "constants": [_constant(value) for value in code.co_consts],
        "names": code.co_names,
        "varnames": code.co_varnames,
        "freevars": code.co_freevars,
        "cellvars": code.co_cellvars,
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
        "exceptiontable": code.co_exceptiontable.hex(),
        "filename": code.co_filename,
        "qualname": code.co_qualname,
        "firstlineno": code.co_firstlineno,
    }


def code_sha256(code: CodeType) -> str:
    """Fingerprint compiled semantics/location; defaults/globals are separate state."""
    raw = json.dumps(_code(code), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
