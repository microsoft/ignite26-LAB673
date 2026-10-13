"""Read-only GRZ sidecar client.

Written against GRZ's published `grz-descriptor-v1` and `grz-sidecar-v1`/`grz-sidecar-v2` contracts; no grz import.
v2 only adds fields (evidence `chunk_vector`/`community_ids`, manifest `member_ranking`) that this reader never selects.
The source index is never read. Tests inject a `SidecarSearch` fake (see tests/fixtures/grz/).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from ontology_core import http
from ontology_core.errors import Blocked
from ontology_core.hashing import sha256_json
from ontology_core.http import EgressPolicy

DESCRIPTOR_VERSION = "grz-descriptor-v1"
SIDECAR_SCHEMAS = ("grz-sidecar-v1", "grz-sidecar-v2")
DESCRIPTOR_FIELDS = (
    "version", "schema_version", "physical_index", "generation_id", "source_service", "source_index",
    "embedding_model_id", "dimension", "visibility",
)
OPTIONAL_DESCRIPTOR_FIELDS = ("visibility_basis",)
VISIBILITY_BASES = ("per-document", "public-attested")
PAGE_SIZE = 500
EVIDENCE_BATCH = 200
MAX_RETRIES = 3
SIDECAR_FIELDS = (
    "id", "sort_key", "kind", "generation_id", "community_id", "parent_id", "level", "chunk_id", "source_id",
    "text", "visibility", "member_count", "label", "label_status", "payload",
)
_CHECK_FIELDS = ["sort_key", "kind", "generation_id", "visibility"]
_SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
_DELIMITERS = (",", "|", ";", "~", "^")


@dataclass(frozen=True)
class Descriptor:
    version: str
    schema_version: str
    physical_index: str
    generation_id: str
    source_service: str
    source_index: str
    embedding_model_id: str
    dimension: int
    visibility: str
    visibility_basis: str | None = None
    """How GRZ established `visibility`; absent in descriptors written before GRZ recorded it."""

    @property
    def search_endpoint(self) -> str:
        return search_endpoint(self.source_service)

    def to_dict(self) -> dict[str, Any]:
        data = {name: getattr(self, name) for name in DESCRIPTOR_FIELDS}
        if self.visibility_basis is not None:
            data["visibility_basis"] = self.visibility_basis
        return data


@dataclass(frozen=True)
class Manifest:
    payload: dict[str, Any]
    digest: str
    """`sha256(canonical_json(payload))`, 64 hex chars, pinned in the plan as `grz.manifest_digest`."""

    @property
    def health(self) -> str:
        return str(self.payload.get("health"))

    @property
    def counts(self) -> dict[str, int]:
        return dict(self.payload.get("counts") or {})


@dataclass(frozen=True)
class Representative:
    community_id: str
    parent_id: str | None
    level: int
    member_count: int
    label: str | None
    label_status: str | None

    @property
    def label_hint(self) -> str | None:
        """`label` when `label_status == "named"`, else None."""
        return self.label if self.label_status == "named" else None


@dataclass(frozen=True)
class Membership:
    community_id: str
    chunk_id: str
    level: int


@dataclass(frozen=True)
class EvidenceText:
    chunk_id: str
    source_id: str
    text: str


class SidecarSearch(Protocol):
    """Minimal search surface. The real one wraps `SearchClient` built with `http.search_transport`."""

    def query(self, *, filter: str, select: list[str], order_by: list[str] | None, top: int) -> list[dict[str, Any]]:
        """One page of documents. Raises `Blocked` GRZ_SIDECAR_* codes mapped from HTTP status."""
        ...


# --------------------------------------------------------------------------- descriptor

def search_endpoint(source_service: str) -> str:
    """Normalize a service name or URL to `https://<name>.search.windows.net`.

    Accepts `name`, `name.search.windows.net` or `https://name.search.windows.net[/]`. Raises `ValueError`
    for anything else (another scheme, host suffix, port, path or an invalid service name).
    """
    value = source_service.strip().lower()
    if value.startswith("https://"):
        value = value[len("https://"):].rstrip("/")
    host = value.removesuffix(".search.windows.net")
    if not _SERVICE_NAME.match(host) or host.endswith("-"):
        raise ValueError(f"not an Azure AI Search service name or URL: {source_service!r}")
    return f"https://{host}.search.windows.net"


def _unreadable(reason: str) -> Blocked:
    return Blocked("GRZ_DESCRIPTOR_UNREADABLE", f"GRZ descriptor is not readable: {reason}")


def validate_descriptor(obj: Any) -> Descriptor:
    """Field set `DESCRIPTOR_FIELDS` plus optional `OPTIONAL_DESCRIPTOR_FIELDS`, `dimension >= 1`.

    `visibility_basis`, when present, must be one of `VISIBILITY_BASES`; either value still requires
    `visibility == "public"`.

    Raises:
        Blocked("GRZ_DESCRIPTOR_UNREADABLE"): not an object, missing/extra/mistyped fields.
        Blocked("GRZ_DESCRIPTOR_UNSUPPORTED"): `version` differs or `schema_version` is not in `SIDECAR_SCHEMAS`.
        Blocked("GRZ_NOT_PUBLIC"): `visibility != "public"`.
    """
    if not isinstance(obj, dict):
        raise _unreadable("expected a JSON object")
    missing = sorted(set(DESCRIPTOR_FIELDS) - set(obj))
    extra = sorted(set(obj) - set(DESCRIPTOR_FIELDS) - set(OPTIONAL_DESCRIPTOR_FIELDS))
    if missing or extra:
        raise Blocked("GRZ_DESCRIPTOR_UNREADABLE",
                      f"GRZ descriptor fields differ from {DESCRIPTOR_VERSION}",
                      details={"missing": missing, "extra": extra})
    for name in DESCRIPTOR_FIELDS:
        value = obj[name]
        if name == "dimension":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise _unreadable("`dimension` must be an integer >= 1")
        elif not isinstance(value, str) or not value.strip():
            raise _unreadable(f"`{name}` must be a non-empty string")
    basis = obj.get("visibility_basis")
    if "visibility_basis" in obj and basis not in VISIBILITY_BASES:
        raise _unreadable(f"`visibility_basis` must be one of {', '.join(VISIBILITY_BASES)}")
    if obj["version"] != DESCRIPTOR_VERSION or obj["schema_version"] not in SIDECAR_SCHEMAS:
        raise Blocked("GRZ_DESCRIPTOR_UNSUPPORTED",
                      f"descriptor is {obj['version']}/{obj['schema_version']}; "
                      f"this tool reads {DESCRIPTOR_VERSION}/{' or '.join(SIDECAR_SCHEMAS)}")
    if obj["visibility"] != "public":
        raise Blocked("GRZ_NOT_PUBLIC", f"GRZ generation visibility is {obj['visibility']!r}, not 'public'")
    try:
        search_endpoint(obj["source_service"])
    except ValueError as exc:
        raise _unreadable(str(exc)) from exc
    return Descriptor(**{name: obj[name] for name in DESCRIPTOR_FIELDS}, visibility_basis=basis)


def load_descriptor(path: Path) -> Descriptor:
    """Read and `validate_descriptor`. Unreadable file or invalid JSON: `GRZ_DESCRIPTOR_UNREADABLE`."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise _unreadable(f"{path}: {type(exc).__name__}") from exc
    return validate_descriptor(data)


# --------------------------------------------------------------------------- live search

def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


_sleep: Callable[[float], None] = time.sleep


def _status_error(status: int, descriptor: Descriptor) -> Blocked | None:
    scope = f"{descriptor.search_endpoint}/indexes/{descriptor.physical_index}"
    if status in (401, 403):
        return Blocked("GRZ_SIDECAR_ACCESS_DENIED",
                       f"HTTP {status} reading GRZ sidecar {descriptor.physical_index}",
                       index_scope=f"<search service resource id>/indexes/{descriptor.physical_index}",
                       details={"index": scope})
    if status == 404:
        return Blocked("GRZ_SIDECAR_NOT_FOUND",
                       f"GRZ sidecar {descriptor.physical_index} was not found on {descriptor.search_endpoint}")
    return None


class _LiveSidecarSearch:
    def __init__(self, descriptor: Descriptor, tenant_id: str, policy: EgressPolicy) -> None:
        self.descriptor = descriptor
        self.tenant_id = tenant_id
        self.policy = policy
        self._client: Any = None

    def _search_client(self) -> Any:
        if self._client is None:
            from azure.search.documents import SearchClient

            from ontology_core import azure_auth

            self._client = SearchClient(self.descriptor.search_endpoint, self.descriptor.physical_index,
                                        azure_auth.credential(self.tenant_id),
                                        transport=http.search_transport(self.policy), retry_total=0)
        return self._client

    def query(self, *, filter: str, select: list[str], order_by: list[str] | None, top: int) -> list[dict[str, Any]]:
        from azure.core.exceptions import HttpResponseError

        attempt = 0
        while True:
            try:
                results = self._search_client().search(search_text="*", filter=filter, select=select,
                                                       order_by=order_by, top=top)
                return [{k: v for k, v in dict(doc).items() if not k.startswith("@search.")} for doc in results]
            except HttpResponseError as exc:
                status = int(exc.status_code or 0)
                mapped = _status_error(status, self.descriptor)
                if mapped is not None:
                    raise mapped from exc
                if status not in (429, 503):
                    raise
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise Blocked("GRZ_SIDECAR_THROTTLED",
                                  f"GRZ sidecar still returned HTTP {status} after {MAX_RETRIES} retries") from exc
                headers = dict(exc.response.headers) if exc.response is not None else {}
                _sleep(http.retry_after_seconds(headers, default=2.0 ** attempt))
            except http.EgressNameNotResolved as exc:
                raise Blocked("GRZ_SIDECAR_NOT_FOUND",
                              f"GRZ search service {self.descriptor.search_endpoint} does not resolve in DNS; "
                              "it may have been deleted") from exc
            except (http.EgressNotSent, http.EgressUnknownOutcome) as exc:
                # Reads are idempotent, but an unknown outcome is still never retried automatically.
                raise Blocked("GRZ_SIDECAR_THROTTLED",
                              f"GRZ sidecar request did not complete: {exc}") from exc


def live_search(descriptor: Descriptor, tenant_id: str, policy: EgressPolicy) -> SidecarSearch:
    """Real `SidecarSearch` for `descriptor.physical_index` using an Entra token (scope `search`).
    Retries 429/503 up to `MAX_RETRIES` honoring `retry-after` (<= 30 s). The policy's search endpoint and
    index default to the descriptor's when unset. Network failures (not sent, or unknown outcome) are not
    retried and surface as GRZ_SIDECAR_THROTTLED, except a service name that does not resolve in DNS
    (GRZ_SIDECAR_NOT_FOUND).

    Raises (from `query`): GRZ_SIDECAR_ACCESS_DENIED (401/403), GRZ_SIDECAR_NOT_FOUND (404 or no DNS record),
    GRZ_SIDECAR_THROTTLED (retries exhausted).
    """
    policy = replace(policy, search_endpoint=policy.search_endpoint or descriptor.search_endpoint,
                     physical_index=policy.physical_index or descriptor.physical_index)
    return _LiveSidecarSearch(descriptor, tenant_id, policy)


# --------------------------------------------------------------------------- reader

def _malformed(kind: str, field: str) -> Blocked:
    return Blocked("GRZ_COUNTS_MISMATCH", f"GRZ sidecar {kind} row has a missing or invalid `{field}`")


def _str(doc: dict[str, Any], name: str, kind: str, *, optional: bool = False) -> str | None:
    value = doc.get(name)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        raise _malformed(kind, name)
    return value


def _int(doc: dict[str, Any], name: str, kind: str) -> int:
    value = doc.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _malformed(kind, name)
    return value


class GrzReader:
    """Keyset-paged reads (`sort_key gt '<last>'`, `orderby sort_key asc`, `PAGE_SIZE`). Every document is
    re-checked for `visibility == "public"` and the descriptor's `generation_id` (else
    `GRZ_GENERATION_CHANGED`)."""

    def __init__(self, descriptor: Descriptor, search: SidecarSearch) -> None:
        self.descriptor = descriptor
        self.search = search

    def _base_filter(self, kind: str) -> str:
        return f"kind eq {_quote(kind)} and generation_id eq {_quote(self.descriptor.generation_id)}"

    def _recheck(self, doc: dict[str, Any], kind: str) -> None:
        gen = self.descriptor.generation_id
        if doc.get("generation_id") != gen or doc.get("visibility") != "public" or doc.get("kind") != kind:
            raise Blocked("GRZ_GENERATION_CHANGED",
                          f"GRZ sidecar returned a {kind} row outside public generation {gen}",
                          details={"generation_id": doc.get("generation_id"), "visibility": doc.get("visibility"),
                                   "kind": doc.get("kind")})

    def _page(self, kind: str, extra: str, select: Iterable[str]) -> list[dict[str, Any]]:
        fields = list(dict.fromkeys([*select, *_CHECK_FIELDS]))
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        last: str | None = None
        while True:
            flt = self._base_filter(kind) + extra
            if last is not None:
                flt += f" and sort_key gt {_quote(last)}"
            page = self.search.query(filter=flt, select=fields, order_by=["sort_key asc"], top=PAGE_SIZE)
            for doc in page:
                self._recheck(doc, kind)
                key = doc.get("sort_key")
                if not isinstance(key, str) or key in seen:
                    raise Blocked("GRZ_COUNTS_MISMATCH", f"GRZ sidecar {kind} rows repeat or lack a sort_key")
                seen.add(key)
                last = key
                rows.append(doc)
            if len(page) < PAGE_SIZE:
                return rows

    def manifest(self) -> Manifest:
        """Raises: GRZ_SIDECAR_NOT_FOUND (no manifest doc), GRZ_GENERATION_CHANGED, GRZ_SIDECAR_* transport codes."""
        docs = self.search.query(filter=self._base_filter("manifest"),
                                 select=list(dict.fromkeys(["id", "payload", *_CHECK_FIELDS])), order_by=None, top=1)
        if not docs:
            raise Blocked("GRZ_SIDECAR_NOT_FOUND",
                          f"GRZ sidecar {self.descriptor.physical_index} has no manifest for generation "
                          f"{self.descriptor.generation_id}")
        doc = docs[0]
        self._recheck(doc, "manifest")
        payload = doc.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError as exc:
                raise Blocked("GRZ_MANIFEST_UNHEALTHY", "GRZ manifest payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise Blocked("GRZ_MANIFEST_UNHEALTHY", "GRZ manifest payload is not a JSON object")
        pinned = payload.get("generation_id")
        if pinned is not None and pinned != self.descriptor.generation_id:
            raise Blocked("GRZ_GENERATION_CHANGED",
                          f"GRZ manifest is for generation {pinned}, not {self.descriptor.generation_id}")
        return Manifest(payload=payload, digest=sha256_json(payload))

    def representatives(self) -> list[Representative]:
        """All `kind eq 'representative'` rows, sorted by (level, community_id)."""
        kind = "representative"
        rows = self._page(kind, "", ["community_id", "parent_id", "level", "member_count", "label", "label_status"])
        reps = [Representative(community_id=_str(d, "community_id", kind) or "",
                               parent_id=_str(d, "parent_id", kind, optional=True),
                               level=_int(d, "level", kind), member_count=_int(d, "member_count", kind),
                               label=d.get("label") if isinstance(d.get("label"), str) else None,
                               label_status=d.get("label_status") if isinstance(d.get("label_status"), str) else None)
                for d in rows]
        return sorted(reps, key=lambda r: (r.level, r.community_id))

    def members(self, level: int | None = None) -> list[Membership]:
        """Membership rows; `None` reads every level (needed for the exact `counts.membership` check),
        an int filters `level eq N`. Sorted by (level, community_id, chunk_id)."""
        kind = "membership"
        extra = "" if level is None else f" and level eq {int(level)}"
        rows = self._page(kind, extra, ["community_id", "chunk_id", "level"])
        out = [Membership(community_id=_str(d, "community_id", kind) or "", chunk_id=_str(d, "chunk_id", kind) or "",
                          level=_int(d, "level", kind)) for d in rows]
        if level is not None and any(m.level != level for m in out):
            raise Blocked("GRZ_COUNTS_MISMATCH", f"GRZ sidecar returned membership rows outside level {level}")
        return sorted(out, key=lambda m: (m.level, m.community_id, m.chunk_id))

    def evidence(self, chunk_ids: list[str]) -> dict[str, EvidenceText]:
        """Evidence text for `chunk_ids` in batches of `EVIDENCE_BATCH` via `search.in`.

        Raises:
            Blocked("GRZ_COUNTS_MISMATCH"): any requested chunk is missing.
        """
        kind = "evidence"
        wanted = list(dict.fromkeys(chunk_ids))
        found: dict[str, EvidenceText] = {}
        for start in range(0, len(wanted), EVIDENCE_BATCH):
            batch = wanted[start:start + EVIDENCE_BATCH]
            delim = next((d for d in _DELIMITERS if not any(d in c for c in batch)), None)
            if delim is None:
                raise Blocked("GRZ_COUNTS_MISMATCH", "GRZ chunk IDs contain every supported search.in delimiter")
            ids = _quote(delim.join(batch))
            rows = self._page(kind, f" and search.in(chunk_id, {ids}, {_quote(delim)})",
                              ["chunk_id", "source_id", "text"])
            for d in rows:
                chunk = _str(d, "chunk_id", kind) or ""
                text = d.get("text")
                if not isinstance(text, str):
                    raise _malformed(kind, "text")
                found[chunk] = EvidenceText(chunk_id=chunk, source_id=_str(d, "source_id", kind) or "", text=text)
        missing = [c for c in wanted if c not in found]
        if missing:
            raise Blocked("GRZ_COUNTS_MISMATCH",
                          f"{len(missing)} of {len(wanted)} sampled chunks have no evidence row in the GRZ sidecar",
                          details={"missing": missing[:20]})
        return {c: found[c] for c in wanted}


def check_manifest(manifest: Manifest, representatives: list[Representative], members: list[Membership]) -> None:
    """Raises:
        Blocked("GRZ_MANIFEST_UNHEALTHY"): `health != "verified"`.
        Blocked("GRZ_COUNTS_MISMATCH"): `counts.representative`/`counts.membership` differ from the rows
        (members must be all levels).
    """
    if manifest.health != "verified":
        raise Blocked("GRZ_MANIFEST_UNHEALTHY", f"GRZ manifest health is {manifest.health!r}, not 'verified'")
    counts = manifest.counts
    actual = {"representative": len(representatives), "membership": len(members)}
    diffs = {k: {"manifest": counts.get(k), "rows": v} for k, v in actual.items() if counts.get(k) != v}
    if diffs:
        raise Blocked("GRZ_COUNTS_MISMATCH",
                      "GRZ manifest counts differ from the sidecar rows: "
                      + ", ".join(f"{k} {d['manifest']} vs {d['rows']}" for k, d in sorted(diffs.items())),
                      details={"counts": diffs})
