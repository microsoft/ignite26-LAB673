# Wrap an existing Azure AI Search index as a knowledge source

Expose a populated index that was built by another pipeline through agentic
retrieval without rebuilding ingestion.

## When to use / do not use

Use when a customer already has a populated Azure AI Search index and wants it
reachable through a Knowledge Base: "Use our existing index in a KB, don't
rebuild it." Do not use to create a new index, indexer, skillset or data
source — use [classic Search](../simple-search/simple-search.md) or the
[vector](../integrated-vector-search/integrated-vector-search.md) hero for
that. **Never modify, rebuild or re-ingest the existing index**; this scenario is
strictly read-only against it and only creates/cleans up the wrapper
knowledge source and KB. An empty or unsuitable index is a reported limitation,
not a reason to silently reshape it.

## Inputs and discovery

Reuse a compatible existing Search service unless isolation is requested.
Follow [service provisioning](../../references/service-provisioning.md) before
version resolution. Read the index definition
([Indexes_Get](../../operations/data-plane/indexes/get.md) if cataloged, or the
[Search index source contract](../../references/knowledge-sources/search-index.md)'s
linked documentation) and inspect: index name, semantic configuration,
searchable fields, retrievable key/content/citation fields, vector fields and
profile if present, and any document-level permission filter already on the
index. Resolve placeholders from this actual schema, never guessed field
names. Check for an existing knowledge source over the same index and for the
target application/agent, representative questions, citation and freshness
requirements. An empty index is not successful content validation; report it
rather than proceeding.

List/get permitted [sources](../../operations/data-plane/knowledge-sources/list.md)
and [KBs](../../operations/data-plane/knowledge-bases/list.md) read-only.
Use the [shared RBAC check](../../references/authentication-rbac.md): Search
Service Contributor for the definition, plus Search Index Data Reader or
Contributor for query verification. Ask before granting missing permissions or provide administrator instructions. Show the desired-state diff and obtain
approval for production or access-boundary changes before creating the wrapper;
preserving document-level access controls is part of this approval — selecting
fields is not an authorization filter.

## API version preflight

Follow [API version policy](../../references/api-version-policy.md) to resolve
`dataApiVersion` (and `managementApiVersion` only if service discovery is
needed) before the first request. Pass the resolved values unchanged to every
operation. Verify the selected version, the index's agentic-retrieval support
and this skill's index criteria in the
[Search index source contract](../../references/knowledge-sources/search-index.md)
before execution; never silently change the version.

## Execute

1. Inspect [service get](../../operations/search-management/services/get.md)
   (`Services_Get`) only if service identity/readiness is in question.
2. GET the knowledge source by name first ([get](../../operations/data-plane/knowledge-sources/get.md));
   a 404 confirms absence. For a brand-new wrapper, run
   [KS create/update](../../operations/data-plane/knowledge-sources/create-or-update.md)
   (`KnowledgeSources_CreateOrUpdate`) with `If-None-Match: *` so a concurrent
   creator's source is never silently overwritten; a 412 means it already
   exists — re-GET and reconcile rather than retrying the create. For a
   reused existing wrapper, send `If-Match` with the just-read ETag so the
   update fails (412) instead of clobbering a concurrent change; on 412,
   re-GET, diff, and only retry after confirming the new ETag reflects a
   change this approval still covers. Use the
   [Search index contract](../../references/knowledge-sources/search-index.md)
   with `kind: searchIndex`, the real `searchIndexName`,
   `semanticConfigurationName`, `searchFields` and `sourceDataFields` resolved
   from the schema read in discovery. Do not add ingestion parameters to this
   source kind; there is no generated pipeline.
3. Read back the source with [get](../../operations/data-plane/knowledge-sources/get.md);
   compare kind, index name and field mappings, and record created/reused
   ownership plus the resulting ETag. There is no synchronization to poll.
4. Use [KB composition and cited retrieval](../../references/knowledge-base-retrieval.md)
   (`KnowledgeBases_CreateOrUpdate`, `KnowledgeRetrieval_Retrieve`) with
   `kind: searchIndex`, reusing the same resolved `dataApiVersion`.

## Verify and clean up

Verify requested retrieval through the KB with a known answer and the actual
source/citation fields selected in `sourceDataFields`; confirm a no-answer
query returns no unsupported answer; confirm freshness by querying content
already present in the index (there is no ingestion lag to wait out, since the
index is pre-existing). Where the index already enforces document-level
security filters, verify those filters are preserved through retrieval — do
not assume selecting fields is itself an authorization boundary. Report any
suitability gap (missing semantic configuration, unsupported field types, an
unreachable index) as an explicit limitation rather than forcing the wrapper
to fit.

On a teardown request, follow
[scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup):
delete the owned [KB](../../operations/data-plane/knowledge-bases/delete.md)
before its [KS](../../operations/data-plane/knowledge-sources/delete.md).
Verify GET/404 for the KS and confirm the reused index remains intact and
unchanged; never delete or recreate the reused index or its ingestion
pipeline.

**Official source:** [Search index knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-search-index).
