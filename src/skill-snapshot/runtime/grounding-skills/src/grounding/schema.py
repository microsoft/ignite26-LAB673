"""edgeList index schema: field list, graph profile, definition and document validation.

Pure functions only. The role/type/capability table below mirrors the service contract for
graphProfile kind "edgeList" on API 2026-08-01-preview; see references/edgelist-schema.md.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from . import API_VERSION, SCHEMA_VERSION

_S, _D, _B, _T = "Edm.String", "Edm.Double", "Edm.Boolean", "Edm.DateTimeOffset"

# role -> (index field, required Edm type, required capabilities)
PROFILE_ROLES: dict[str, tuple[str, str, frozenset[str]]] = {
    "assertionIdField": ("id", _S, frozenset({"key", "filterable", "sortable", "retrievable"})),
    "factIdField": ("id", _S, frozenset({"filterable", "retrievable"})),
    "subjectField": ("subject", _S, frozenset({"filterable", "facetable", "sortable", "retrievable"})),
    "predicateField": ("predicate", _S, frozenset({"filterable", "facetable", "retrievable"})),
    "objectField": ("object", _S, frozenset({"filterable", "facetable", "sortable", "retrievable"})),
    "objectStringField": ("object_string", _S, frozenset({"filterable", "facetable", "retrievable"})),
    "objectDoubleField": ("object_double", _D, frozenset({"filterable", "facetable", "sortable", "retrievable"})),
    "objectBoolField": ("object_bool", _B, frozenset({"filterable", "retrievable"})),
    "objectDateTimeField": ("object_datetime", _T, frozenset({"filterable", "retrievable"})),
    "subjectTypeField": ("subject_type", _S, frozenset({"filterable", "facetable", "retrievable"})),
    "subjectIdField": ("subject_id", _S, frozenset({"filterable", "facetable", "sortable", "retrievable"})),
    "objectTypeField": ("object_type", _S, frozenset({"filterable", "facetable", "retrievable"})),
    "objectIdField": ("object_id", _S, frozenset({"filterable", "facetable", "sortable", "retrievable"})),
    "graphNameField": ("graph_name", _S, frozenset({"filterable", "facetable", "sortable", "retrievable"})),
    "confidenceField": ("edge_confidence", _D, frozenset({"retrievable"})),
    "subjectConfidenceField": ("s_confidence", _D, frozenset({"retrievable"})),
    "predicateConfidenceField": ("p_confidence", _D, frozenset({"retrievable"})),
    "objectConfidenceField": ("o_confidence", _D, frozenset({"retrievable"})),
    "sourceChunkIdField": ("chunk_id", _S, frozenset({"retrievable"})),
    "sourceParentIdField": ("parent_id", _S, frozenset({"retrievable"})),
    "subjectIdDisplayNameField": ("subject_id_display_name", _S, frozenset({"retrievable"})),
    "objectIdDisplayNameField": ("object_id_display_name", _S, frozenset({"retrievable"})),
}
SHAREABLE_ROLES = frozenset({"assertionIdField", "factIdField"})

GRAPH_PROFILE_FIELDS = {role: spec[0] for role, spec in PROFILE_ROLES.items()}

# Fields outside the profile: content hash and per-edge origin (license/source label).
EXTRA_FIELDS: dict[str, tuple[str, frozenset[str]]] = {
    "edge_hash": (_S, frozenset({"retrievable", "filterable"})),
    "namespace": (_S, frozenset({"retrievable", "filterable"})),
}
SEARCHABLE = frozenset({"subject", "object", "object_string", "subject_id_display_name",
                        "object_id_display_name", "predicate"})


def _field_caps() -> dict[str, tuple[str, set[str]]]:
    out: dict[str, tuple[str, set[str]]] = {}
    for _, (fname, ftype, caps) in PROFILE_ROLES.items():
        prev = out.get(fname)
        out[fname] = (ftype, set(caps) | (prev[1] if prev else set()))
    for fname, (ftype, caps) in EXTRA_FIELDS.items():
        out[fname] = (ftype, set(caps))
    return out


FIELD_CAPS = _field_caps()
FIELD_NAMES = list(FIELD_CAPS)
FIELD_TYPES = {n: t for n, (t, _) in FIELD_CAPS.items()}
CONFIDENCE_FIELDS = ("edge_confidence", "s_confidence", "p_confidence", "o_confidence")
REQUIRED_DOC_FIELDS = ("id", "subject", "predicate", "object")


def build_index_definition(name: str) -> dict[str, Any]:
    fields = []
    for fname, (ftype, caps) in FIELD_CAPS.items():
        f: dict[str, Any] = {"name": fname, "type": ftype, "key": "key" in caps,
                             "retrievable": "retrievable" in caps, "filterable": "filterable" in caps,
                             "sortable": "sortable" in caps, "facetable": "facetable" in caps}
        if ftype == _S:
            f["searchable"] = fname in SEARCHABLE
        fields.append(f)
    return {"name": name, "fields": fields,
            "graphProfile": {"kind": "edgeList", "fields": dict(GRAPH_PROFILE_FIELDS)}}


def validate_definition(defn: dict[str, Any]) -> list[str]:
    """Check an index definition against the edgeList contract (empty list = valid). Runs before any POST."""
    problems: list[str] = []
    profile = defn.get("graphProfile")
    if not isinstance(profile, dict):
        return ["GROUNDING_PROFILE_MISSING: index has no graphProfile"]
    if profile.get("kind") != "edgeList":
        problems.append(f"GROUNDING_PROFILE_KIND: graphProfile.kind is {profile.get('kind')!r}, expected 'edgeList'")
    mapping = profile.get("fields") or {}
    existing = {f.get("name"): f for f in defn.get("fields", [])}
    for key in mapping:
        if key not in PROFILE_ROLES:
            problems.append(f"PROFILE_ROLE_UNKNOWN: graphProfile.fields.{key} is not a valid role")
    seen: dict[str, str] = {}
    for role, (_, rtype, rcaps) in PROFILE_ROLES.items():
        target = mapping.get(role)
        if not target:
            problems.append(f"PROFILE_FIELD_UNMAPPED: graphProfile.fields.{role} missing")
            continue
        f = existing.get(target)
        if f is None:
            problems.append(f"PROFILE_FIELD_UNKNOWN: graphProfile.fields.{role} -> {target!r} is not an index field")
            continue
        if f.get("type") != rtype:
            problems.append(f"PROFILE_FIELD_TYPE: {role} -> {target!r} must be {rtype}, is {f.get('type')}")
        for cap in sorted(rcaps):
            if not f.get(cap):
                problems.append(f"PROFILE_FIELD_CAPABILITY: {role} -> {target!r} must be {cap}")
        if rtype == _S and f.get("normalizer"):
            problems.append(f"PROFILE_FIELD_NORMALIZER: {role} -> {target!r} must not have a normalizer")
        other = seen.get(target)
        if other and not ({role, other} <= SHAREABLE_ROLES):
            problems.append(f"PROFILE_FIELD_SHARED: {role} and {other} both map to {target!r}")
        seen.setdefault(target, role)
    return problems


def definitions_equivalent(planned: dict[str, Any], existing: dict[str, Any]) -> bool:
    """True when every planned field/profile mapping is present with the same type/key on the remote definition."""
    ex_fields = {f.get("name"): f for f in existing.get("fields", [])}
    for f in planned["fields"]:
        r = ex_fields.get(f["name"])
        if not r or r.get("type") != f["type"] or bool(r.get("key")) != bool(f["key"]):
            return False
    p, r = planned["graphProfile"], existing.get("graphProfile") or {}
    return r.get("kind") == p["kind"] and (r.get("fields") or {}) == p["fields"]


def schema_fingerprint() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "api_version": API_VERSION,
            "fields": {n: [t, sorted(c)] for n, (t, c) in FIELD_CAPS.items()}, "profile": GRAPH_PROFILE_FIELDS}


def validate_document(doc: dict[str, Any]) -> list[str]:
    problems = []
    for k in REQUIRED_DOC_FIELDS:
        if not isinstance(doc.get(k), str) or not doc[k]:
            problems.append(f"{k} is required and must be a non-empty string")
    for k, v in doc.items():
        if k not in FIELD_TYPES:
            problems.append(f"unknown field {k}")
            continue
        if v is None:
            continue
        t = FIELD_TYPES[k]
        if t == _S and not isinstance(v, str):
            problems.append(f"{k} must be a string")
        elif t == _D and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
            problems.append(f"{k} must be a finite number")
        elif t == _B and not isinstance(v, bool):
            problems.append(f"{k} must be a boolean")
    for k in CONFIDENCE_FIELDS:
        v = doc.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and not 0.0 <= v <= 1.0:
            problems.append(f"{k} must be between 0 and 1")
    return problems


def copy_definition(defn: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(defn)
