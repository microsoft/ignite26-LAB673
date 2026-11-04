# From passages to graphs and topics

This is the initial three-notebook draft for the graph-enabled lab. Use it in a
guided session with these instructions in the sidebar, or work through the same
checkpoints at your own pace. The earlier notebooks remain available.

All three notebooks use **one Search service**, one connection, the Cocoarynth
documents, and the existing content and graph loading scripts. They do not use
the earnings-call demo's separate graph endpoint or its private connection files.

## Before you begin

Use the prepared lab Python kernel with the
[notebook requirements](../src/notebooks/lab/requirements.txt).

The session owner must prepare the existing service before attendees start:

1. Load the four ordinary Cocoarynth indexes with the
   [existing content setup](../infra/README.md#rebuild-the-index-snapshots).
   That maintainer operation replaces their records; do not rerun it against
   shared attendee indexes during the lab.
2. Use the [graph loading instructions](../infra/README.md#restore-graph-snapshots-private-preview)
   on **that same service**, with `--graph-ks`. This restores the seven graph and
   topic indexes and creates the inline-ontology Graph knowledge source. Existing
   resources are not replaced; use `--verify-only --graph-ks` to check a completed
   restoration. A new restore requires absent destination names.
3. Configure the root `.env` or exported environment variables below. Exported
   values take precedence. Keep keys local and do not display the full configuration.

| Variable | Purpose |
| --- | --- |
| `AZURE_SEARCH_SERVICE_ENDPOINT` | The single approved, graph-enabled Search HTTPS root, including Raouf's dev stamp when using that environment |
| `AZURE_SEARCH_ADMIN_KEY` | Its credential, shared only through the approved lab setup |
| `AZURE_SEARCH_LAB_RESOURCE_PREFIX` | Your unique `lab673-...` namespace for the notebooks' knowledge sources and bases |
| `AZURE_SEARCH_CONTENT_INDEX_PREFIX` | Optional; `cocoarynth` by default, or the prefix of the four prepared content indexes |
| `AZURE_SEARCH_GRAPH_INDEX_PREFIX` | Optional; exactly the graph loader's `--prefix`, or empty for an unprefixed restoration |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY` | An existing model resource that this Search service can call |
| `AZURE_OPENAI_CHATGPT_DEPLOYMENT`, `AZURE_OPENAI_CHATGPT_MODEL_NAME` | Its existing reasoning/answer model deployment and actual model name |

These are not the incremental SDK samples' separate `AZURE_SEARCH_PREVIEW_*`
connection variables. Do not mix endpoints or keys between the two paths.
No notebook provisions services, changes permissions or billing, generates
embeddings, runs an indexer, or starts a new graph extraction.

The service needs the November preview, native GQL, MR1, and the private
inline-ontology Graph KS capability. Source availability alone does not establish
that a particular stamp enables them. HTTP 402 is a service-owner prerequisite,
not an instruction to change the billing tier. Other service errors and partial
HTTP 206 responses stop the affected exercise rather than becoming sample answers.

## Notebook 1: Ask first, then compare retrieval strategies

Open [Knowledge base and MR1](../src/notebooks/lab/01-knowledge-base-and-mr1.ipynb).
Keep this introduction short so most of the lab remains available for entities.

### Sidebar: Start in the portal and original documents

Use the portal entry point and service supplied by the session owner. Inspect
the four prepared indexes and their populated document counts. Dev-stamp portal
access may require the owner's preview portal; do not substitute a different
public service if its controls are unavailable. The notebook's SDK checks provide
the same connection and index checks, but are not a claim that the public portal
supports the private preview.

Open the label claims policy PDF linked in the notebook. Find the conditions
for an organic seal before asking the knowledge base. The notebook creates
attendee-owned indexed sources and a standard agentic knowledge base; review
those objects in the portal when available. It never replaces existing objects.

### Sidebar: Inspect a grounded answer

Run the standard retrieval. Locate the returned policy passage and citation.
Check the original PDF, then inspect planning, search, and synthesis activity.
An answer is not evidence merely because it sounds plausible.

### Sidebar: Decide whether speed is worth the narrower scope

Run the optional MR1 section. The comparison fixes the policy source, question,
extractive output, and output bounds. Standard retrieval uses Low effort and a
chat message; pure MR1 uses Minimal effort and a semantic intent. These are
different retrieval strategies, not an isolated model benchmark.

MR1 prioritizes speed and faster query planning. It does not choose sources:
the application supplies the narrow policy scope. It is not a replacement for
the graph reasoning in the next notebook. Read the measured times and actual
evidence; do not assume MR1 wins every request or that a faster result is better.

## Notebook 2: Make the relationships visible

Open [Entities and graph exploration](../src/notebooks/lab/02-entities-and-graphs.ipynb).
This is the core and longest part of the lab.

### Sidebar: Separate the ontology, facts, and evidence

Inspect the restored ontology's entity types, relationship domains, and ranges.
An ontology describes which kinds of things and relationships the graph models;
it is not the graph's individual entities.

Compare the original batch record with a stored assertion and its source chunk.
The restored graph includes authored world-record assertions and document
mentions. The notebook explains schema-guided extraction but does not claim that
these cells run an extractor or that every assertion was extracted from a PDF.
Stored confidence values are not an independent accuracy measurement.

### Sidebar: Read a triple, then follow a joined path

Identify subject, predicate, object, stable entity IDs, and the source chunk.
Move from one batch-to-lot relationship to the farms that point to that same lot.
Read arrow direction carefully: `Batch -> BeanLot <- Farm`.

Build the GQL in the notebook, inspect a plan-only result, and then execute it.
The diagram and table use the service's actual returned IDs and rows, not a
pre-drawn answer. Plan-only returns no result rows by design.

### Sidebar: Check how the answer was obtained

Follow graph provenance IDs back to assertion rows and source chunks. Inspect
warnings, bounded evidence counts, the physical plan, and service statistics.
Evidence IDs do not by themselves prove the truth or completeness of a fact.

Ask the same relationship question through the inline-ontology Graph KS and
through ordinary document retrieval. A graph-backed result must contain
successful, nonempty `graphSearch` activity and a graph reference. The source can
also expose text search; read the actual activity instead of calling every
answer a graph traversal.

Handwritten GQL is not the model's generated GQL. If the private Graph KS does
not return generated query text, the notebook says so rather than drawing an
invented query. Natural-language graph retrieval can add model reasoning and
latency; a fast handwritten traversal does not measure that whole pipeline.

## Notebook 3: Explore topics without confusing them with entities

Open [Topics exploration](../src/notebooks/lab/03-topics.ipynb). Keep this
follow-on shorter than the entity section.

### Sidebar: Browse the captured hierarchy

Inspect the restored topic manifest, representatives, parent-child links, and
membership evidence. Unnamed communities remain unnamed. The manifest records
partial coverage and distinguishes native vectors from derived parent centroids;
those limits remain visible.

### Sidebar: Compare two ways to find related passages

Select an actual source passage and reuse its stored embedding. Compare direct
nearest-passage retrieval with nearest-native-topic lookup followed by its
captured members. Both use the SDK and the same restored corpus.

This is a passage-seeded exploration, not a fresh natural-language embedding or
a full query-latency benchmark. It is also not the earnings demo's native
`topicGraph` diversification modifier: the graph loader restores topic
representatives and memberships, but does not link that modifier to a vector
field. Different returned passages do not automatically mean better relevance.

### Sidebar: Choose a retrieval approach

Use the policy question, farm-traceability question, and broad topic browse to
explain a practical choice: passages for direct grounding, MR1 when narrow-scope
speed matters, entities for explicit relationship questions, and topics for
exploring related groups of passages. No approach is universally best.

## Finish

The notebooks read the prepared indexes and create only knowledge sources and
bases under your own namespace. They do not delete resources. Ask the session
owner to retire attendee-owned objects after the session; leave the shared
indexes and Graph KS in place.

Clear notebook outputs before saving or proposing changes. Never commit `.env`,
keys, private demo profiles, or executed outputs containing live configuration.
