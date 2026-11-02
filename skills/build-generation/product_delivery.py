"""Read-only final trial submission audit; no repair or build-quality decisions."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pok.pob import codec


def audit_submission(answer: dict[str, Any], artifacts_root: Path) -> dict[str, Any]:
    """Resolve only declared files inside this trial and compare all supplied XMLs."""
    root = artifacts_root.resolve()
    files: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    xmls: list[tuple[str, str]] = []
    for index, entry in enumerate(answer.get("artifacts", [])):
        try:
            reference = entry["reference"]
            if not isinstance(reference, str) or not reference:
                raise ValueError("Expected an exact local file path")
            path = Path(reference)
            path = (path if path.is_absolute() else root / path).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Submitted file escapes this trial artifacts")
            raw = path.read_bytes()
            files.append(
                {
                    "index": index,
                    "format": entry["format"],
                    "path": str(path),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }
            )
            if entry["format"] == "pob_xml":
                xml = raw.decode("utf-8")
            elif entry["format"] == "pob_code":
                xml = codec.decode(raw.decode("utf-8"))
            else:
                continue
            if ElementTree.fromstring(xml).tag not in {"PathOfBuilding", "PathOfBuilding2"}:
                raise ValueError("Expected a PoB XML root")
            xmls.append((f"artifact:{index}", xml))
        except (KeyError, TypeError, ValueError, OSError, ElementTree.ParseError) as exc:
            diagnostics.append({"source": f"artifact:{index}", "error": str(exc)})
    code = answer.get("pob_code")
    if code is not None:
        try:
            xml = codec.decode(code)
            if ElementTree.fromstring(xml).tag not in {"PathOfBuilding", "PathOfBuilding2"}:
                raise ValueError("Expected a PoB XML root")
            xmls.append(("answer:pob_code", xml))
        except (TypeError, ValueError, ElementTree.ParseError) as exc:
            diagnostics.append({"source": "answer:pob_code", "error": str(exc)})
    if not xmls:
        diagnostics.append({"source": "submission", "error": "No readable submitted PoB XML"})
    elif any(xml != xmls[0][1] for _, xml in xmls[1:]):
        diagnostics.append({"source": "submission", "error": "Submitted PoB sources disagree"})
    return {
        "format": "pok.trial-delivery-audit.v1",
        "declared_status": answer.get("status"),
        "files": files,
        "xml_sources": [
            {"source": source, "sha256": hashlib.sha256(xml.encode("utf-8")).hexdigest()}
            for source, xml in xmls
        ],
        "diagnostics": diagnostics,
        "transport_verified": bool(xmls) and not diagnostics,
        "build_quality_verified": False,
        "game_feasibility_certified": False,
        "claim": "submitted_bytes_only_no_repair_or_implicit_artifact_selection",
    }
