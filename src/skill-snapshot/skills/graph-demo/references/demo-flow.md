# Demo flow

## Quick starts

- "Walk me through the graph workflow using the companion plugins."
- "Show where grounding, communities and an ontology fit before the EKG build."

## Stage order

Each stage belongs to its owning skill in this unified snapshot; this skill only sequences them. Use a public
or synthetic corpus for the demo. Only `entity-skills` is planned.

| Step | Owner | Outcome | Status |
|---|---|---|---|
| Prepare Azure resources | `ekg-provision` | Ready Azure AI Search, storage, and model prerequisites | Available |
| Create a grounding index (optional) | `grounding-provision`, `grounding-build` | An edgeList grounding index from CSV, JSONL or Wikidata | Available |
| Build topic communities | `grz-build` | Corpus-wide community structure | Available |
| Propose or refine an ontology | `ontology-build` | Reviewed OWL ontology for the corpus | Available |
| Build the graph | `ekg-build` | An EKG build using the OWL file or the built-in Schema.org option, with grounding when present | Available |
| Ask multi-hop questions | `ekg-consume` | Read-only answers with cited paths | Available |
| Browse communities, ontology or grounding | `grz-consume`, `ontology-consume`, `grounding-consume` | Read-only inspection of each artifact | Available |

## Safe sequence

1. Check only the prerequisites for the stages the user chose in [Install and checks](install-and-checks.md).
2. Hand off to each owning skill only after the user approves that step; never pass its approval flags.
3. Skip optional stages the user does not need: with an OWL file, skip `ontology-build`; without a vocabulary, skip grounding.
4. If the user already has an OWL file, use it for the custom-ontology trial path in `ekg-build`.
5. Use `ekg-consume` only after an EKG build is ready.
6. If the user asks for automated entity linking or extraction, explain that `entity-skills` is planned and cannot be run today.

## Fallback

When a required runtime or native asset is missing, report its prerequisite from [Install and checks](install-and-checks.md), wait for the user, then continue. The minimal path is:

- bring an OWL file the user already has, or
- use the built-in Schema.org option in `ekg-skills`.

Never skip a leaf-skill approval to speed up the demo.
