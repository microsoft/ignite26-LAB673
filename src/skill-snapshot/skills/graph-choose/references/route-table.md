# Route table

## Quick starts

- "I have contract documents and need to know which vendors an outage affects. Which route fits?"
- "My data is already in Kusto and I need graph paths. Where do I start?"

## Pick the smallest route that fits

| What you have | What you want | Route today |
|---|---|---|
| Documents | One passage or a few passages with citations | `foundry-iq-skills` |
| Data already in Kusto or Azure Data Explorer | Graph traversal or path queries in that data | `azure-kusto-graph-skills` |
| Documents and an OWL file | Multi-hop answers across entities | `ekg-skills` with the supplied OWL file |
| Documents and no OWL file | Multi-hop answers across common business entities | `ekg-skills` with the built-in Schema.org option |
| A Search index with chunk vectors | Topic communities or corpus coverage | `grz-skills` |
| A published community summary | A proposed OWL ontology | `ontology-skills`, then use the exported OWL file with `ekg-skills` |
| A domain vocabulary in CSV, JSONL or Wikidata | Domain grounding for an EKG build | `grounding-skills` to create or load an edgeList grounding index |
| Automated entity linking or extraction | Entities resolved from text | `entity-skills` is planned; explain that no route exists yet |

## Rules of thumb

- If one document can answer the question, stay with `foundry-iq-skills`.
- If the answer needs two or more relationship hops and no single passage states it, use `ekg-skills`.
- If the source of truth is already Kusto data, use `azure-kusto-graph-skills` instead of moving the task to Azure AI Search.
- If the user needs domain-specific entity types, use `grz-skills` then `ontology-skills`, and add `grounding-skills` when a vocabulary should ground the EKG build.
- Only `entity-skills` is planned. Describe it as future work and keep the actionable route on an available plugin.

## Approval-first handoff

1. Run only the read-only checks in [Install and checks](install-and-checks.md) for the published route you chose.
2. Use the local snapshot installation guidance only when a required runtime is missing.
3. Wait for the user to confirm they are ready.
4. Hand off in plain language to the first owning skill.
