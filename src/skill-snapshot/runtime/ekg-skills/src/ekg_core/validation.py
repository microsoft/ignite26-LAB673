from __future__ import annotations

from typing import Any
import hashlib
import json
import re
from urllib.parse import urlsplit


def validate_deployment_descriptor(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["descriptor must be an object"]
    unexpected = set(value) - {
        "deployment_id", "build_id", "ontology", "capabilities", "endpoints",
        "source_provenance",
    }
    if unexpected:
        errors.append("descriptor contains unsupported fields")
    for field in ("deployment_id", "build_id", "capabilities", "endpoints"):
        if field not in value:
            errors.append(f"missing required field: {field}")
    for field in ("deployment_id", "build_id"):
        if field in value and (not isinstance(value[field], str) or not value[field]):
            errors.append(f"{field} must be a nonempty string")
    if "ontology" in value and value["ontology"] is not None and not isinstance(
        value["ontology"], dict
    ):
        errors.append("ontology must be an object or null")
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, dict):
        errors.append("capabilities must be an object")
    else:
        allowed = {"document_retrieval", "graph_retrieval", "agentic_retrieval"}
        unknown = sorted(set(capabilities) - allowed)
        errors.extend(f"unknown capability: {name}" for name in unknown)
        errors.extend(
            f"capability {name} must be boolean"
            for name, enabled in capabilities.items()
            if name in allowed and not isinstance(enabled, bool)
        )
    endpoints = value.get("endpoints")
    if not isinstance(endpoints, dict):
        errors.append("endpoints must be an object")
    elif any(not isinstance(key, str) or not isinstance(item, str)
             for key, item in endpoints.items()):
        errors.append("endpoints must map names to strings")
    _validate_source_provenance(value, endpoints, errors)
    return errors


def _validate_source_provenance(value: dict[str, Any], endpoints: Any, errors: list[str]) -> None:
    provenance = value.get("source_provenance")
    if "source_provenance" in value and provenance is None:
        errors.append("source provenance must not be null")
    if isinstance(endpoints, dict):
        if (("source_manifest_digest" in endpoints) != (provenance is not None)
                or isinstance(provenance, dict) and
                endpoints.get("source_manifest_digest") != provenance.get("manifest_digest")):
            errors.append("source provenance differs from descriptor source manifest")
    if provenance is not None:
        if not isinstance(provenance, dict) or set(provenance) != {
            "manifest_digest", "mapping_digest", "staged",
        }:
            errors.append("source provenance needs manifest digest, mapping digest and staged map")
        else:
            digest, staged = provenance["manifest_digest"], provenance["staged"]
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                errors.append("source provenance requires an approved manifest digest")
            if isinstance(staged, dict):
                raw = json.dumps({"manifest_digest": digest, "staged": staged},
                                 sort_keys=True, separators=(",", ":")).encode("utf-8")
                if provenance["mapping_digest"] != f"sha256:{hashlib.sha256(raw).hexdigest()}":
                    errors.append("source provenance mapping digest differs")
            if not isinstance(staged, dict) or not 1 <= len(staged) <= 5000:
                errors.append("source provenance requires a bounded staged map")
            else:
                source_ids: set[str] = set()
                build_id = value.get("build_id")
                if not isinstance(build_id, str) or not re.fullmatch(
                    r"build-[a-f0-9]{16}", build_id
                ):
                    errors.append("source provenance requires an exact generation build ID")
                generation = build_id.removeprefix("build-") if isinstance(build_id, str) else ""
                for url, item in staged.items():
                    parsed = urlsplit(url) if isinstance(url, str) else None
                    if (parsed is None or parsed.scheme != "https" or not parsed.netloc
                            or parsed.query or parsed.fragment or not isinstance(item, dict)
                            or set(item) != {"source_id", "original_uri", "citation_uri", "version_or_hash"}
                            or any(not isinstance(v, str) or not v for v in item.values())
                            or not re.fullmatch(r"source-item-[a-f0-9]{16}|blob-[a-f0-9]{16}",
                                                item["source_id"])
                            or not re.fullmatch(
                                rf"/[a-z0-9-]+/{re.escape(generation)}/"
                                rf"{re.escape(item['source_id'])}\.(?:md|txt)",
                                parsed.path,
                            )
                            or url == item["original_uri"]
                            or (isinstance(endpoints, dict) and not url.startswith(
                                endpoints.get("storage", "") + "/"
                            ))):
                        errors.append("source provenance contains invalid staged identity")
                        break
                    if item["source_id"] in source_ids:
                        errors.append("source provenance has duplicate original source IDs")
                        break
                    source_ids.add(item["source_id"])
