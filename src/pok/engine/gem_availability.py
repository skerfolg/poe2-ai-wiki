"""Report patch-scoped approved gem exclusions without blocking calculation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pok.kb.exclusions import fold_gem_name, gem_exclusion_ledger
from pok.pob.catalog import canonical_gem_id, gem_names


def audit_gem_availability(spec: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    try:
        ledger = gem_exclusion_ledger(root)
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "ledger_unavailable", "findings": [], "reason": str(exc)}
    try:
        native_names = {identity: name for name, identity in gem_names(root).items()}
        aliases = {
            str(gem.get("gem_id", "")): canonical_gem_id(str(gem.get("gem_id", "")), root)
            for group in spec.get("skills", [])
            for gem in group.get("gems", [])
            if gem.get("gem_id")
        }
    except (OSError, ValueError, RuntimeError) as exc:
        return {
            "status": "catalog_unavailable",
            "findings": [],
            "reason": str(exc),
            "ledger_sha256": ledger["sha256"],
            "patch": ledger["patch"],
        }
    findings = []
    unresolved = []
    for gi, group in enumerate(spec.get("skills", [])):
        for index, gem in enumerate(group.get("gems", [])):
            identity = str(gem.get("gem_id", ""))
            native = aliases.get(identity, identity)
            name = native_names.get(native)
            location = {
                "group_index": gi,
                "gem_index": index,
                "gem_id": identity,
                "group_enabled": group.get("enabled", True),
                "gem_enabled": gem.get("enabled", True),
            }
            if name is None:
                unresolved.append({**location, "reason": "native_identity_unresolved"})
                continue
            key = fold_gem_name(name)
            for entry in ledger["entries"]:
                if key not in {fold_gem_name(value) for value in entry["aliases"]}:
                    continue
                row = entry["entry"]
                findings.append(
                    {
                        **location,
                        "canonical_gem_id": native,
                        "catalog_name": name,
                        "declared_name": gem.get("name"),
                        "matched_by": "native_catalog_identity",
                        "category": entry["category"],
                        "ledger_entry_path": entry["source_path"],
                        "entry_patch": row.get("patch"),
                        "scope": "matches_kb_patch"
                        if row.get("patch") == ledger["patch"] and ledger["patch"]
                        else "different_or_unknown_patch",
                        "approval": row.get("approved"),
                        "classification": "approved_exclusion"
                        if isinstance(row.get("approved"), str) and row["approved"].strip()
                        else "unapproved_ledger_entry",
                        "evidence": row.get("evidence"),
                        "note": row.get("note"),
                        "merged_into": row.get("merged_into"),
                        "removed_ids": row.get("removed_ids", []),
                    }
                )
    return {
        "status": "inspected",
        "patch": ledger["patch"],
        "ledger_source": ledger["source"],
        "ledger_sha256": ledger["sha256"],
        "findings": findings,
        "unresolved": unresolved,
        "absence_is_not_exclusion": True,
        "calculation_blocked": False,
        "scope": "approved_catalog_history_not_gameplay_verification",
    }
