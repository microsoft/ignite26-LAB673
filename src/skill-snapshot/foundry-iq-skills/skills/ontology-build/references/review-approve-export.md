# Review, approve, export

## Quick starts

- "Review the latest ontology version and show what changed from the previous one."
- "Approve version 3 and export it as `wiki.owl`."
- "Which ontology is my current approved one?"

## Use this path

Use this path to review a version, pin it by its schema ID, write the flat-owl `.owl` file or opt-in JSON-LD, import an existing ontology, or hand the approved ontology to a consumer.

## Review and approve

1. `ontology-build review --details` shows class and property counts, the change from the previous version, hygiene notes, and after refine the rounds, fixes, remaining findings, and stop reason.
2. Show the review `approval` card exactly. Its Plan ID is the version's schema ID. Stop.
3. After `approved <schema-id>`, run the `ontology-build approve` command that `review` printed with that exact `--schema-id`. Never construct or reuse a schema ID. Approving also records the version as the current approved ontology.

## Export and hand off

- `ontology-build export --output <path>.owl` writes flat-owl RDF/XML, refuses any unapproved version, and never overwrites a file unless the user asked for `--force`. It also updates the current pointer.
- `ontology-build export --format jsonld --output <path>.jsonld` is an explicit, separate inline-compatible artifact. It never changes `current`; offer it only for a compatible inline JSON-LD graph-extraction input.
- `ontology-build current --json` (or `ontology-consume current --json`) returns the current approved ontology's path, SHA-256, IRI, counts, source generation, and approval time. Blocks with `NO_CURRENT` until a version is approved and `CURRENT_INVALID` when the file changed.
- Offer `ontology-consume check <path>.owl` to validate the exported file against the flat-owl profile.

## Import

`ontology-build import <file>` saves an OWL, Turtle, or JSON ontology as a new version to review, approve, and export. Offline, import, review, approve, and export need no Azure.

## Return

Report the exported path or current pointer, the SHA-256, and one safe next action. If blocked, relay `error` in plain words and do exactly `next_step`; use `ontology-build reconcile` only for a stale lock or changed state files.
