# Measured results

Historical single runs from before the CLI-first migration. They do not requalify current adapters or
product hosts. Each is one baseline for one corpus, not a benchmark.

## EKG: synthetic Contoso corpus

- 84 documents, 7 scripted multi-hop questions, an OWL ontology.
- The graph gave all 7 answers: 17 of 17 expected, with a path and a source file per hop. Graph
  queries took 2.5 to 5.3 s.
- Vector retrieval named none of the expected answers for 3 of 7 questions, because no chunk holds
  the whole chain.
- Extraction: 84 of 84 items, 0 failed, about 20 minutes.
- The built-in `schema_org` ontology is not measured.

## GRZ: Simple English Wikipedia

- 17 top-level topics over 7,296 public chunks; each opens into finer topics and the passages behind
  them. Built on a Basic-tier Search service.

## Ontology: enterprise-software Wikipedia

- 1,000 articles gave 21 classes and 54 properties for $1.35. A reviewer model refined it from v1 to
  v5 for $0.33, raising the rubric score from 16 to 18 of 25. Every class and property cites passages.

## Chain run: all three on the same articles

GRZ built 70 communities over 3,096 chunks. The ontology reached v5 (24 of 30; 21 classes, 42
properties). A 50-document EKG trial was a go: 21 of 21 classes and 32 of 33 relationship types. The
full build finished 1,000 of 1,000 in 9 h 45 min unattended (about $8) and scored 16 of 19 on seven
questions, correcting the wrong-premise one.

## Claims

| Claim | Status |
|---|---|
| A knowledge graph answers multi-hop questions with a cited source per hop | Measured: 17 of 17 Contoso; 16 of 19 Wikipedia |
| GraphRAG summarizes themes with no ontology | Measured on two corpora |
| A candidate ontology can be generated, reviewed and trialled | Measured in the chain run |
| Recovery from a wrong premise | One question, one corpus only |

## Not measured

- The seven Wikipedia questions in a full graph-mode agent run (the 16 of 19 came from chunk retrieval).
- Wrong-premise recovery beyond one question.
- GRZ recall against plain vector search.
- The built-in `schema_org` ontology.
