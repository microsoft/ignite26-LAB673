"""Prepare and verify Cocoarynth snapshot re-ingestion without regenerating vectors."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data" / "graph-data"
FORMAT = "cocoarynth-ekg-check-v1"
GRAPH_API = "2026-08-01-preview"
KS_API = "2026-11-01-preview"
SOURCE_MAPPING = {
    "chunk_id": "uid",
    "chunk": "snippet",
    "parent_id": "snippet_parent_id",
    "blob_path": "blob_url",
}


class CheckError(RuntimeError):
    pass


class ServiceError(CheckError):
    def __init__(self, status, message, api):
        super().__init__(message)
        self.status = status
        self.api = api


def require(condition, message):
    if not condition:
        raise CheckError(message)


def encoded(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_rows(path):
    return [json.loads(line) for line in path.read_text("utf-8-sig").splitlines() if line]


def write_artifact(directory, name, data):
    path = directory / name
    require(not path.exists() or path.read_bytes() == data,
            f"Refusing to overwrite a different prepared artifact: {name}")
    path.write_bytes(data)


def safe_message(message):
    return re.sub(
        r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b",
        "<id>", str(message),
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise CheckError("Authenticated Search redirects are not accepted.")


class Search:
    def __init__(self, endpoint):
        parsed = urllib.parse.urlsplit(endpoint)
        require(parsed.scheme == "https" and parsed.hostname
                and re.fullmatch(r"[a-z0-9-]+\.search\.windows\.net", parsed.hostname)
                and parsed.netloc == parsed.hostname and parsed.path in {"", "/"}
                and not parsed.query and not parsed.fragment,
                "Supply an explicit canonical HTTPS Azure AI Search endpoint.")
        config = os.environ.get("AZURE_CONFIG_DIR")
        tenant = os.environ.get("AZURE_TENANT_ID")
        require(config and tenant, "Run through an isolated Azure CLI profile with an explicit tenant.")
        require(not Path(config).resolve().is_relative_to((Path.home() / ".azure").resolve()),
                "The shared default Azure CLI profile is not allowed.")
        self.tenant = tenant
        self.endpoint = endpoint.rstrip("/")
        self.az = shutil.which("az.cmd") or shutil.which("az.exe") or shutil.which("az")
        require(self.az, "Azure CLI is required; no API-key or implicit credential fallback is used.")
        self.http = urllib.request.build_opener(NoRedirect())
        self.access_token = None
        self.token_expiry = 0

    def token(self):
        if self.token_expiry <= time.time() + 120:
            result = subprocess.run(
                [self.az, "account", "get-access-token", "--resource", "https://search.azure.com/",
                 "--tenant", self.tenant, "--output", "json", "--only-show-errors"],
                capture_output=True, text=True, check=False,
            )
            require(result.returncode == 0,
                    "Isolated Search authentication failed: " + safe_message(result.stderr))
            token = json.loads(result.stdout)["accessToken"]
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            require(claims.get("tid", "").casefold() == self.tenant.casefold(),
                    "The Search token belongs to a different tenant.")
            self.access_token = token
            self.token_expiry = claims["exp"]
        return self.access_token

    def request(self, method, path, body=None, *, api=GRAPH_API, absent=False, headers=None):
        require(not path.startswith(("/", "\\")) and "://" not in path and "?" not in path,
                "Only local Search resource paths are accepted.")
        require(api in {GRAPH_API, KS_API}, "An unverified API version was requested.")
        token = self.token()
        request = urllib.request.Request(
            self.endpoint + "/" + path + "?api-version=" + api,
            data=encoded(body) if body is not None else None, method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                     **(headers or {})},
        )
        try:
            with self.http.open(request, timeout=120) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as error:
            if absent and method == "GET" and error.code == 404:
                return None
            message = error.read().decode("utf-8", errors="replace").replace(token, "<redacted>")
            raise ServiceError(error.code, safe_message(message), api) from error


def load_plan(directory):
    plan = read_json(directory / "plan.json")
    require(plan["format"] == FORMAT, "Unknown prepared snapshot format.")
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,60}[a-z0-9]", plan["prefix"]),
            "The prepared resource prefix is invalid.")
    identity = sha256(encoded({"format": FORMAT, "inputs": plan["inputs"]}))
    require(plan["owner"] == f"{FORMAT}; input-sha256={identity}",
            "The prepared ownership marker does not match the source inventory.")
    for role in ("source", "ontology", "graph"):
        suffix = "sources" if role == "source" else role
        require(plan[role]["index"] == plan["prefix"] + "-" + suffix,
                "A prepared index is outside the declared resource prefix.")
        definition = read_json(directory / (suffix + "-index.json"))
        require(definition["name"] == plan[role]["index"]
                and definition["description"] == plan["owner"],
                "A prepared index definition is outside the declared ownership scope.")
    for name in (
        "sources-index.json", "sources-exported.jsonl", "ontology-index.json",
        "ontology-exported.jsonl", "graph-index.json", "graph-exported.jsonl",
        "ontology-relationships.jsonld", "graph-ks.json",
    ):
        require(sha256((directory / name).read_bytes()) == plan["artifacts"][name],
                "A prepared artifact changed: " + name)
    for name, digest in plan["inputs"].items():
        require(Path(name).name == name, "A bundle input path is invalid.")
        require(sha256((BUNDLE / name).read_bytes().replace(b"\r\n", b"\n")) == digest,
                "The source bundle changed after preparation: " + name)
    source = read_json(directory / "graph-ks.json")
    require(source["name"] == plan["prefix"] + "-ks"
            and source["searchIndexParameters"]["searchIndexName"] == plan["graph"]["index"],
            "The prepared Graph KS targets a different resource.")
    return plan


def check_definition(expected, observed):
    require(observed and observed.get("description") == expected["description"],
            "Refusing to adopt or overwrite an index not owned by this exact snapshot.")
    fields = {field["name"]: field for field in observed["fields"]}
    require(set(fields) == {field["name"] for field in expected["fields"]},
            "The restored field inventory differs.")
    for field in expected["fields"]:
        actual = fields[field["name"]]
        for flag in ("key", "filterable", "sortable", "facetable", "searchable", "retrievable"):
            if flag in field:
                require(actual.get(flag) is field[flag],
                        f"The restored field flag differs: {field['name']}/{flag}")
        for key in ("type", "dimensions", "vectorSearchProfile", "stored"):
            if key in field:
                require(actual.get(key) == field[key],
                        f"The restored field property differs: {field['name']}/{key}")
    if "graphProfile" in expected:
        profile = observed.get("graphProfile") or {}
        for key, value in expected["graphProfile"].items():
            require(profile.get(key) == value, "The restored graph profile differs: " + key)
    if "vectorSearch" in expected:
        for kind in ("algorithms", "profiles"):
            require(without_nulls(observed.get("vectorSearch", {}).get(kind))
                    == without_nulls(expected["vectorSearch"][kind]),
                    "The captured vector search configuration differs: " + kind)


def without_nulls(value):
    if isinstance(value, dict):
        return {key: without_nulls(child) for key, child in value.items() if child is not None}
    if isinstance(value, list):
        return [without_nulls(child) for child in value]
    return value


def read_all(client, index, key, limit):
    rows = []
    cursor = None
    for _ in range(16):
        body = {"search": "*", "top": 1000, "orderby": key + " asc"}
        if cursor is not None:
            body["filter"] = key + " gt '" + cursor.replace("'", "''") + "'"
        result = client.request("POST", f"indexes/{index}/docs/search", body)
        page = [
            {name: value for name, value in row.items() if not name.startswith("@")}
            for row in result["value"]
        ]
        if not page:
            return rows
        require(cursor is None or page[-1][key] > cursor, "Readback pagination did not advance.")
        rows.extend(page)
        require(len(rows) <= limit, "The task-owned index contains unexpected extra records.")
        cursor = page[-1][key]
        if len(page) < 1000 and not result.get("@odata.nextLink"):
            return rows
    raise CheckError("Readback exceeded its bounded page count.")


def parity(expected, actual, key):
    wanted = {row[key]: row for row in expected}
    seen = set()
    for row in actual:
        identity = row[key]
        require(identity in wanted and identity not in seen,
                "A duplicate or foreign document is present in the task-owned index.")
        original = wanted[identity]
        clean = {name: value for name, value in row.items()
                 if name != "snippet_vector" and value is not None}
        baseline = {name: value for name, value in original.items()
                    if name != "snippet_vector" and value is not None}
        for fields in (clean, baseline):
            if "object_datetime" in fields:
                instant = datetime.fromisoformat(fields["object_datetime"].replace("Z", "+00:00"))
                require(instant.tzinfo is not None, "A typed graph timestamp lost its time zone.")
                fields["object_datetime"] = instant.astimezone(timezone.utc)
        require(clean == baseline, "Text, identifiers, metadata or assertions changed: " + identity)
        if "snippet_vector" in original:
            before, after = original["snippet_vector"], row.get("snippet_vector")
            if before:
                require(isinstance(after, list) and len(after) == 3072,
                        "A captured source vector is missing or has the wrong dimensions.")
                require(struct.pack("<3072f", *before) == struct.pack("<3072f", *after),
                        "A captured source vector changed at float32 precision.")
            else:
                require(after in (None, []), "An embedding was introduced for unembedded evidence.")
        seen.add(identity)
    return seen


def verify_indexes(client, directory, plan):
    verified = []
    for role in ("sources", "ontology", "graph"):
        definition = read_json(directory / (role + "-index.json"))
        expected = read_rows(directory / (role + "-exported.jsonl"))
        key = "uid" if role == "sources" else "id"
        check_definition(definition, client.request("GET", "indexes/" + definition["name"]))
        actual = read_all(client, definition["name"], key, len(expected))
        require(len(parity(expected, actual, key)) == len(expected),
                "A restored index has an incomplete document count: " + definition["name"])
        verified.append({"role": role, "index": definition["name"], "records": len(actual)})
    source = next(row for row in read_rows(directory / "sources-exported.jsonl")
                  if row["snippet_vector"])
    result = client.request("POST", f"indexes/{plan['source']['index']}/docs/search", {
        "vectorQueries": [{"kind": "vector", "vector": source["snippet_vector"],
                           "fields": "snippet_vector", "k": 1}],
        "select": "uid", "top": 1,
    })
    hits = result["value"]
    require(len(hits) == 1 and hits[0]["uid"] == source["uid"]
            and hits[0]["@search.score"] >= 0.99999,
            "The restored source vector did not retrieve itself at the required score.")
    return {
        "status": "passed", "indexes": verified, "source_vectors": 106,
        "float32_bit_identical": True, "unembedded_records": 503,
        "typed_datetime_comparison": "same UTC instant; original object text remains exact",
        "embedding_calls": 0, "vector_self_query_score": hits[0]["@search.score"],
    }


def restore_index(client, directory, role):
    definition = read_json(directory / (role + "-index.json"))
    expected = read_rows(directory / (role + "-exported.jsonl"))
    name = definition["name"]
    key = "uid" if role == "sources" else "id"
    observed = client.request("GET", "indexes/" + name, absent=True)
    created = observed is None
    if created:
        client.request("PUT", "indexes/" + name, definition, headers={"If-None-Match": "*"})
        observed = client.request("GET", "indexes/" + name)
    check_definition(definition, observed)
    actual = read_all(client, name, key, len(expected))
    present = parity(expected, actual, key)
    missing = [row for row in expected if row[key] not in present]
    for offset in range(0, len(missing), 100):
        batch = missing[offset:offset + 100]
        body = {"value": [dict(row, **{"@search.action": "upload"}) for row in batch]}
        require(len(encoded(body)) < 15 * 1024 * 1024, "An upload batch exceeds the request budget.")
        result = client.request("POST", f"indexes/{name}/docs/index", body)
        statuses = result["value"]
        require(len(statuses) == len(batch)
                and {item["key"] for item in statuses} == {row[key] for row in batch}
                and all(item.get("status") is True for item in statuses),
                "Not every document upload succeeded: " + name)
    for _ in range(12):
        actual = read_all(client, name, key, len(expected))
        if len(parity(expected, actual, key)) == len(expected):
            return {"index": name, "created": created, "uploaded_documents": len(missing),
                    "verified_documents": len(actual)}
        time.sleep(2)
    raise CheckError("Restored records did not become fully readable: " + name)


def ensure_metadata(client, collection, definition):
    name = definition["name"]
    observed = client.request("GET", collection + "/" + name, api=KS_API, absent=True)
    if observed is None:
        client.request("PUT", collection + "/" + name, definition, api=KS_API,
                       headers={"If-None-Match": "*"})
        observed = client.request("GET", collection + "/" + name, api=KS_API)
    check_metadata(definition, observed)


def check_metadata(definition, observed):
    require(isinstance(observed, dict) and observed.get("description") == definition["description"],
            "Refusing to overwrite an unrelated knowledge source or knowledge base.")
    for key, value in definition.items():
        if key in {"name", "description"}:
            continue
        if key == "searchIndexParameters":
            require(all(observed.get(key, {}).get(field) == expected
                        for field, expected in value.items()),
                    "The stored Graph KS binding differs from the prepared definition.")
        elif key == "models":
            actual_models = observed.get("models") or []
            require(len(actual_models) == len(value), "The stored KB model inventory differs.")
            for expected, actual in zip(value, actual_models):
                require(expected["kind"] == actual.get("kind"), "The stored KB model kind differs.")
                parameters = actual.get("azureOpenAIParameters") or {}
                require(all(parameters.get(field) == setting
                            for field, setting in expected["azureOpenAIParameters"].items()),
                        "The stored KB model binding differs.")
        else:
            require(observed.get(key) == value, "The stored KB property differs: " + key)


def restore_live(client, directory, plan, report, model_source):
    definitions = [read_json(directory / (role + "-index.json"))
                   for role in ("sources", "ontology", "graph")]
    needed = sum(client.request("GET", "indexes/" + item["name"], absent=True) is None
                 for item in definitions)
    capacity = client.request("GET", "servicestats")["counters"]["indexesCount"]
    require(capacity["quota"] - capacity["usage"] >= needed,
            "Insufficient index slots. This script never deletes or scales resources.")
    report["restore"] = {"status": "in_progress", "indexes": []}
    for role in ("sources", "ontology", "graph"):
        report["restore"]["indexes"].append(restore_index(client, directory, role))
    report["restore"]["status"] = "passed"
    if not preview_available(client, report):
        return
    require(model_source and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,125}[a-z0-9]", model_source),
            "Supply --model-source-kb naming an existing Entra-authenticated model binding.")
    base = client.request("GET", "knowledgebases/" + model_source)
    models = base.get("models") or []
    require(len(models) == 1 and models[0].get("kind") == "azureOpenAI",
            "The named source KB must have one explicit Azure OpenAI model.")
    original = models[0]["azureOpenAIParameters"]
    require(not original.get("apiKey"), "API-key model bindings are not copied.")
    parameters = {name: original[name] for name in ("resourceUri", "deploymentId", "modelName")}
    require(all(parameters.values()), "The existing model binding is incomplete.")
    if original.get("authIdentity") is not None:
        parameters["authIdentity"] = original["authIdentity"]
    source = read_json(directory / "graph-ks.json")
    ensure_metadata(client, "knowledgesources", source)
    definition = {
        "name": plan["prefix"] + "-kb", "description": plan["owner"],
        "knowledgeSources": [{"name": source["name"]}],
        "models": [{"kind": "azureOpenAI", "azureOpenAIParameters": parameters}],
        "retrievalReasoningEffort": {"kind": "medium"}, "outputMode": "extractiveData",
        "retrievalInstructions": (
            "Use graph_search for Cocoarynth relationship questions. Follow the complete "
            "relationship path. Do not substitute lexical search for graph traversal."
        ),
    }
    ensure_metadata(client, "knowledgebases", definition)
    report["graph_ks"] = {
        "status": "prepared_not_verified", "knowledge_source": source["name"],
        "knowledge_base": definition["name"], "server_nl2gql_verified": False,
        "client_fallback_allowed": False,
    }


def query_cases():
    questions = {
        "M4: September batch still uses the earlier bean lot":
            "Which bean lot was used in production batch PE26-0902?",
        "M1: complaint to overflow bay":
            "Which site stored the shipment involved in case CASE-2607-18, "
            "via that shipment's depot stop?",
        "M2: wrapper batch to exactly its contributing farms":
            "Which farms contributed beans to the wrapper batch mentioned in case CASE-2609-14?",
    }
    fixtures = {item["name"]: item for item in read_json(
        BUNDLE / "cocoarynth-query-checks.json"
    )["routes"]}
    schema = {item["name"]: item for item in read_json(
        BUNDLE / "cocoarynth-ontology.json"
    )["properties"]}
    cases = []
    for name, question in questions.items():
        fixture = fixtures[name]
        pattern = "(n0:`" + fixture["start"].split(":")[2] + "`)"
        for number, step in enumerate(fixture["steps"]):
            relation = schema[step["predicate"]]
            target = relation["range"] if step["direction"] == "out" else relation["domain"]
            edge = f"[r{number}:`{step['predicate']}`]"
            node = f"(n{number + 1}:`{target}`)"
            pattern += ("-" + edge + "->" + node if step["direction"] == "out"
                        else "<-" + edge + "-" + node)
        gql = (f"MATCH {pattern} WHERE n0.id = '{fixture['start']}' "
               f"RETURN n{len(fixture['steps'])}.id AS answer LIMIT 20")
        cases.append({"name": name, "question": question, "gql": gql,
                      "expected": fixture["expected"]})
    return cases


def graph_query(client, index, gql, *, hydrate=False):
    require(isinstance(gql, str) and re.match(r"\s*MATCH\b", gql, re.IGNORECASE)
            and ";" not in gql and len(gql) < 16384,
            "Only a bounded read-only MATCH query may be replayed.")
    provenance = {"kind": "ids"}
    if hydrate:
        provenance = {
            "kind": "hydrate",
            "hydrateDocuments": {"select": "uid,snippet,snippet_parent_id,blob_url,source_pointer"},
        }
    result = client.request("POST", f"indexes('{index}')/docs/search.graph", {
        "gql": gql, "includeDiagnostics": True, "includeStatistics": True,
        "provenance": provenance,
    })
    errors = [item for item in result.get("@search.graphDiagnostics", [])
              if item.get("severity", "").casefold() == "error"]
    require(not errors, "Native graph execution returned error diagnostics: "
            + safe_message(json.dumps(errors)))
    require(isinstance(result.get("value"), list) and result["value"],
            "Native graph execution returned no result rows.")
    return result


def evidence_ids(result):
    return {
        item["chunkId"]
        for row in result["value"]
        for item in (row.get("@search.graphProvenance") or {}).get("evidence", [])
        if item.get("chunkId")
    }


def lookup_evidence(client, result, plan):
    documents = {}
    for identity in sorted(evidence_ids(result)):
        require(len(documents) < 40, "Graph provenance exceeded the source-lookup budget.")
        key = urllib.parse.quote(identity, safe="")
        documents[identity] = client.request(
            "GET", f"indexes('{plan['source']['index']}')/docs('{key}')"
        )
    return documents


def check_bindings(result, case, directory, *, answer_column=False, documents=None):
    rows = result["value"]
    expected = set(case["expected"])
    names = {}
    assertions = read_rows(directory / "graph-exported.jsonl")
    by_id = {row["id"]: row for row in assertions}
    for row in assertions:
        for side in ("subject", "object"):
            identity, label = row[side + "_id"], row[side + "_id_display_name"]
            if identity and label:
                names.setdefault(label, set()).add(identity)
    types = {value.rsplit(":", 1)[0] + ":" for value in expected}
    answers = set()
    evidence = set()
    for row in rows:
        values = [row.get("answer")] if answer_column else [
            value for name, value in row.items() if not name.startswith("@")
        ]
        for value in values:
            if isinstance(value, dict):
                value = value.get("id")
            if not isinstance(value, str):
                continue
            identities = {value} if value.startswith("urn:cocoarynth:") else names.get(value, set())
            candidates = {identity for identity in identities
                          if any(identity.startswith(prefix) for prefix in types)}
            require(len(candidates) <= 1, "A returned entity label is ambiguous.")
            answers.update(candidates)
        provenance = row.get("@search.graphProvenance") or {}
        for item in provenance.get("evidence", []):
            if item.get("chunkId"):
                require(item.get("edgeId") in by_id, "A graph evidence assertion is not in the snapshot.")
                original = by_id[item["edgeId"]]
                require(item["chunkId"] == original["chunk_id"]
                        and item.get("parentId") == original["parent_id"],
                        "A graph assertion lost its original chunk or parent identifier.")
                evidence.add(item["chunkId"])
    require(answers == expected, "Native graph result bindings differ from the independent fixture.")
    require(evidence, "Graph rows contain no source-chunk provenance.")
    hydration = "client-key-lookup" if documents is not None else "server"
    if documents is None:
        documents = result.get("@search.graphProvenanceDocuments")
    if isinstance(documents, list):
        documents = {row["uid"]: row for row in documents}
    require(isinstance(documents, dict), "No resolved graph source documents were provided.")
    sources = {row["uid"]: row for row in read_rows(directory / "sources-exported.jsonl")}
    for identity in evidence:
        require(identity in sources and identity in documents,
                "A graph evidence identifier has no resolved original source.")
        actual, original = documents[identity], sources[identity]
        for key in ("uid", "snippet", "snippet_parent_id", "blob_url", "source_pointer"):
            require(actual.get(key) == original.get(key), "Hydrated graph evidence changed: " + key)
    return {"name": case["name"], "answers": sorted(answers),
            "source_chunks": sorted(evidence), "hydration": hydration, "status": "passed"}


def preview_available(client, report):
    try:
        client.request("GET", "knowledgesources", api=KS_API)
    except ServiceError as error:
        if error.status == 400 and (
            "The version indicated by the api-version query string parameter does not exist."
            in str(error)
        ):
            report["graph_ks"] = {
                "status": "blocked", "required_api_version": KS_API,
                "http_status": error.status, "message": str(error),
                "server_nl2gql_verified": False, "client_fallback_allowed": False,
            }
            return False
        raise
    return True


def verify_live(client, directory, plan, report):
    report["knowledge_base_request_attempts"] = 0
    report["reingestion"] = verify_indexes(client, directory, plan)
    report["direct_gql"] = {"status": "in_progress", "cases": []}
    for number, case in enumerate(query_cases()):
        result = graph_query(client, plan["graph"]["index"], case["gql"])
        data = encoded(result) + b"\n"
        (directory / f"direct-gql-{number + 1}.json").write_bytes(data)
        documents = lookup_evidence(client, result, plan)
        checked = check_bindings(result, case, directory, answer_column=True, documents=documents)
        checked.update({"gql": case["gql"], "raw_response_sha256": sha256(data)})
        report["direct_gql"]["cases"].append(checked)
    report["direct_gql"]["status"] = "passed"
    case = query_cases()[0]
    try:
        result = graph_query(client, plan["graph"]["index"], case["gql"], hydrate=True)
        check_bindings(result, case, directory, answer_column=True)
        report["server_provenance_hydration"] = {"status": "passed"}
    except ServiceError as error:
        if error.status != 400 or "Provenance document hydration is not supported" not in str(error):
            raise
        report["server_provenance_hydration"] = {
            "status": "blocked", "http_status": error.status, "message": str(error),
            "alternative_verified": "explicit client lookup by unchanged source uid",
            "graph_execution_fallback": False,
        }
    if not preview_available(client, report):
        return
    source = read_json(directory / "graph-ks.json")
    stored = client.request("GET", "knowledgesources/" + source["name"], api=KS_API)
    check_metadata(source, stored)
    kb_name = plan["prefix"] + "-kb"
    check_metadata({
        "name": kb_name, "description": plan["owner"],
        "knowledgeSources": [{"name": source["name"]}],
        "retrievalReasoningEffort": {"kind": "medium"}, "outputMode": "extractiveData",
    }, client.request("GET", "knowledgebases/" + kb_name, api=KS_API))
    report["graph_ks"] = {"status": "in_progress", "cases": [],
                          "server_nl2gql_verified": False, "client_fallback_allowed": False}
    for number, case in enumerate(query_cases()):
        report["knowledge_base_request_attempts"] += 1
        result = client.request("POST", f"knowledgebases/{plan['prefix']}-kb/retrieve", {
            "messages": [{"role": "user", "content": [{"type": "text", "text": case["question"]}]}],
            "includeActivity": True,
            "knowledgeSourceParams": [{
                "kind": "searchIndex", "knowledgeSourceName": source["name"],
                "includeReferences": True, "includeReferenceSourceData": True,
                "alwaysQuerySource": True,
                "graphParameters": {"includeQuery": True, "provenance": {
                    "kind": ("hydrate" if report["server_provenance_hydration"]["status"] == "passed"
                             else "none")
                }},
            }],
        }, api=KS_API)
        data = encoded(result) + b"\n"
        (directory / f"graph-ks-{number + 1}.json").write_bytes(data)
        queries = check_graph_activity(result, source["name"], plan["graph"]["index"])
        require(len(queries) <= 4, "Graph KS exceeded the bounded graph-query replay budget.")
        replays = [graph_query(client, plan["graph"]["index"], query) for query in queries]
        combined = {"value": []}
        for replay in replays:
            combined["value"].extend(replay["value"])
        documents = lookup_evidence(client, combined, plan)
        checked = check_bindings(combined, case, directory, documents=documents)
        checked.update({"question": case["question"], "server_generated_gql": queries,
                        "raw_kb_response_sha256": sha256(data)})
        report["graph_ks"]["cases"].append(checked)
    report["graph_ks"].update({"status": "passed", "server_nl2gql_verified": True})


def check_graph_activity(response, source_name, graph_index):
    """Require actual server Graph KS execution, not a consumer's enriched answer."""
    require(not response.get("error"), "Knowledge-base retrieval returned an error.")
    activity = response.get("activity")
    require(isinstance(activity, list), "Raw KB retrieval has no activity trace.")
    queries = []
    for record in activity:
        require(isinstance(record, dict), "A KB activity record is malformed.")
        require(not record.get("error"), "A KB activity record reports an execution error.")
        arguments = record.get("graphSearchArguments")
        if record.get("knowledgeSourceName") != source_name or not isinstance(arguments, dict):
            continue
        require(arguments.get("graphIndexName") == graph_index,
                "Graph KS executed against a different graph index.")
        require(str(arguments.get("outcome", "")).casefold() in {"success", "succeeded"},
                "Graph KS did not report successful graph execution.")
        require(type(record.get("count")) is int and record["count"] > 0,
                "Graph KS returned no graph rows.")
        query = arguments.get("gql")
        require(isinstance(query, str) and query.strip(),
                "Graph KS did not expose generated GQL; includeQuery must be true.")
        require(isinstance(arguments.get("naturalLanguageQuery"), str)
                and arguments["naturalLanguageQuery"].strip(),
                "Graph KS did not record its natural-language query.")
        queries.append(query)
    require(queries, "No server Graph KS activity was returned; lexical/client fallback is not proof.")
    return queries


def prepare(directory, prefix):
    manifest = read_json(BUNDLE / "manifest.json")
    inventory = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
    inputs = {}
    names = (
        "cocoarynth-graph-sources-index.json",
        "cocoarynth-graph-sources-exported.jsonl",
        "cocoarynth-topic-sources-index.json",
        "cocoarynth-topic-sources-exported.jsonl",
        "cocoarynth-graph-index.json",
        "cocoarynth-graph-exported.jsonl",
        "cocoarynth-ontology-index.json",
        "cocoarynth-ontology-exported.jsonl",
        "cocoarynth-ontology.json",
        "cocoarynth-ontology.owl",
        "cocoarynth-query-checks.json",
    )
    for name in names:
        data = (BUNDLE / name).read_bytes().replace(b"\r\n", b"\n")
        require(sha256(data) == inventory[name], f"Bundle checksum differs: {name}")
        inputs[name] = sha256(data)
    identity = sha256(encoded({"format": FORMAT, "inputs": inputs}))
    prefix = prefix or f"cocoarynth-ekg-{identity[:12]}"
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,60}[a-z0-9]", prefix),
            "The resource prefix must be 3-62 lowercase letters, digits or hyphens.")
    owner = f"{FORMAT}; input-sha256={identity}"
    originals = read_rows(BUNDLE / "cocoarynth-graph-sources-exported.jsonl")
    captured = read_rows(BUNDLE / "cocoarynth-topic-sources-exported.jsonl")
    vectors = {row["chunk_id"]: row for row in captured}
    require(len(vectors) == len(captured) == 106, "Expected 106 unique captured vectors.")
    require(len(originals) == 609 and len({row["chunk_id"] for row in originals}) == 609,
            "Expected 609 unique original evidence records.")
    projected = []
    seen_vectors = set()
    for original in originals:
        row = {SOURCE_MAPPING.get(key, key): value for key, value in original.items()}
        row["snippet_vector"] = []
        if original["chunk_id"] in vectors:
            snapshot = vectors[original["chunk_id"]]
            for key, value in snapshot.items():
                if key != "text_vector":
                    require(original[key] == value,
                            f"Evidence/vector capture differs for {original['chunk_id']}: {key}")
            vector = snapshot["text_vector"]
            require(len(vector) == 3072 and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) for value in vector
            ) and any(vector), "A captured source vector is invalid.")
            struct.pack("<3072f", *vector)
            row["snippet_vector"] = vector
            seen_vectors.add(original["chunk_id"])
        projected.append(row)
    require(seen_vectors == set(vectors), "A captured vector has no original evidence record.")
    definition = read_json(BUNDLE / "cocoarynth-graph-sources-index.json")
    definition["name"] = prefix + "-sources"
    definition["description"] = owner
    for field in definition["fields"]:
        field["name"] = SOURCE_MAPPING.get(field["name"], field["name"])
    definition["fields"].append({
        "name": "snippet_vector", "type": "Collection(Edm.Single)",
        "searchable": True, "retrievable": True, "stored": True,
        "dimensions": 3072, "vectorSearchProfile": "captured-cosine",
    })
    definition["vectorSearch"] = read_json(
        BUNDLE / "cocoarynth-topic-sources-index.json"
    )["vectorSearch"]
    directory.mkdir(parents=True, exist_ok=True)
    write_artifact(directory, "sources-index.json", encoded(definition) + b"\n")
    write_artifact(directory, "sources-exported.jsonl",
                   b"".join(encoded(row) + b"\n" for row in projected))
    sources = {row["uid"] for row in projected}
    native = {}
    for role, expected_count in (("ontology", 288), ("graph", 3938)):
        index = read_json(BUNDLE / f"cocoarynth-{role}-index.json")
        rows = read_rows(BUNDLE / f"cocoarynth-{role}-exported.jsonl")
        require(len(rows) == len({row["id"] for row in rows}) == expected_count,
                f"The original {role} row inventory differs.")
        index["name"] = prefix + "-" + role
        index["description"] = owner
        if role == "graph":
            require(all(row["chunk_id"] in sources for row in rows),
                    "A business assertion has no preserved evidence record.")
            index["graphProfile"]["provenanceIndexName"] = definition["name"]
            index["semantic"] = {
                "defaultConfiguration": "graph-semantic",
                "configurations": [{
                    "name": "graph-semantic",
                    "prioritizedFields": {
                        "titleField": {"fieldName": "subject_id_display_name"},
                        "prioritizedContentFields": [
                            {"fieldName": name} for name in ("subject", "predicate", "object")
                        ],
                    },
                }],
            }
        write_artifact(directory, role + "-index.json", encoded(index) + b"\n")
        write_artifact(directory, role + "-exported.jsonl",
                       b"".join(encoded(row) + b"\n" for row in rows))
        native[role] = {"index": index["name"], "records": len(rows)}
    schema = read_json(BUNDLE / "cocoarynth-ontology.json")
    relations = [item for item in schema["properties"] if item["kind"] == "object"]
    ontology = {
        "@context": {
            "coco": manifest["ontology_iri"],
            "owl": "http://www.w3.org/2002/07/owl#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        },
        "@graph": [
            {"@id": "coco:" + item["name"], "@type": "owl:Class",
             "rdfs:label": item["name"], "rdfs:comment": item["description"]}
            for item in schema["classes"]
        ] + [
            {"@id": "coco:" + item["name"], "@type": "owl:ObjectProperty",
             "rdfs:label": item["name"], "rdfs:comment": item["description"],
             "rdfs:domain": {"@id": "coco:" + item["domain"]},
             "rdfs:range": {"@id": "coco:" + item["range"]}}
            for item in relations
        ],
    }
    ontology_text = (encoded(ontology) + b"\n").decode("utf-8")
    write_artifact(directory, "ontology-relationships.jsonld", ontology_text.encode("utf-8"))
    try:
        import ekg_core.ontology as ontology_runtime
        from ekg_core.models import OntologyMode
    except ImportError as error:
        raise CheckError(
            "Run prepare with the Python interpreter from the verified EKG skills runtime; "
            "the official inline JSON-LD validator is required."
        ) from error
    validated = ontology_runtime.load_ontology(
        OntologyMode.INLINE_JSONLD, path=str(directory / "ontology-relationships.jsonld")
    )
    require(len(validated.node_types) == 39 and len(validated.properties) == 70,
            "The official EKG validator did not preserve the relationship projection.")
    source = {
        "name": prefix + "-ks", "kind": "searchIndex",
        "description": owner + "; Cocoarynth business relationships; not datatype planning.",
        "searchIndexParameters": {
            "searchIndexName": native["graph"]["index"],
            "semanticConfigurationName": "graph-semantic",
            "sourceDataFields": [
                {"name": name} for name in
                ("id", "subject", "predicate", "object", "chunk_id", "parent_id")
            ],
            "graphOntology": {
                "kind": "inline", "name": "cocoarynth-business-relationships",
                "value": ontology_text,
            },
        },
    }
    write_artifact(directory, "graph-ks.json", encoded(source) + b"\n")
    plan = {
        "format": FORMAT, "owner": owner, "prefix": prefix, "inputs": inputs,
        "source": {
            "index": definition["name"], "records": len(projected),
            "vectors": len(seen_vectors), "dimensions": 3072,
            "records_without_precomputed_vectors": len(projected) - len(seen_vectors),
            "unembedded_vector_representation": "empty collection, not a null or zero vector",
            "field_mapping": {**SOURCE_MAPPING, "text_vector": "snippet_vector"},
            "embedding_calls": 0,
        },
        **native,
        "approved_owl_sha256": inputs["cocoarynth-ontology.owl"],
        "graph_ks": {
            "name": source["name"], "api_version": KS_API,
            "classes": 39, "object_properties": 70,
            "omitted_datatype_properties": len(schema["properties"]) - len(relations),
            "inheritance_reasoning_supported": False, "full_owl_planning_supported": False,
            "scope": "Flat relationship-only smoke-test projection, not a replacement ontology.",
            "runtime_validated": True, "projection_schema_id": validated.schema_id,
            "validator_module_sha256": sha256(Path(ontology_runtime.__file__).read_bytes()),
        },
    }
    plan["artifacts"] = {
        name: sha256((directory / name).read_bytes())
        for name in (
            "sources-index.json", "sources-exported.jsonl", "ontology-index.json",
            "ontology-exported.jsonl", "graph-index.json", "graph-exported.jsonl",
            "ontology-relationships.jsonld", "graph-ks.json",
        )
    }
    write_artifact(directory, "plan.json", encoded(plan) + b"\n")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare", help="Create a lossless, offline EKG source projection.")
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--prefix")
    command = commands.add_parser("verify", help="Read back snapshots and test native GQL and Graph KS.")
    command.add_argument("--prepared", type=Path, required=True)
    command.add_argument("--endpoint", required=True)
    command = commands.add_parser("restore", help="Restore only new or matching task-owned resources.")
    command.add_argument("--prepared", type=Path, required=True)
    command.add_argument("--endpoint", required=True)
    command.add_argument("--model-source-kb")
    args = parser.parse_args()
    report = None
    try:
        if args.command == "prepare":
            result = prepare(args.output, args.prefix)
        else:
            plan = load_plan(args.prepared)
            report = {
                "format": FORMAT, "command": args.command, "target": args.endpoint,
                "prefix": plan["prefix"], "started_at": datetime.now(timezone.utc).isoformat(),
                "plan_sha256": sha256((args.prepared / "plan.json").read_bytes()),
                "graph_api_version": GRAPH_API, "graph_ks_api_version": KS_API,
                "projection": plan["graph_ks"], "status": "in_progress",
                "script_sha256": sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")),
            }
            client = Search(args.endpoint)
            if args.command == "restore":
                restore_live(client, args.prepared, plan, report, args.model_source_kb)
            else:
                verify_live(client, args.prepared, plan, report)
            report["status"] = (
                "blocked" if report["graph_ks"]["status"] == "blocked" else
                "prepared_not_verified" if args.command == "restore" else "passed"
            )
            result = report
    except (CheckError, OSError, ValueError, KeyError, struct.error) as error:
        if report is not None:
            report["status"] = "failed"
            report["error"] = safe_message(error)
            if isinstance(error, ServiceError):
                report["http_status"], report["error_api_version"] = error.status, error.api
        print(json.dumps({"status": "failed", "error": safe_message(error)}), file=sys.stderr)
        return 1
    finally:
        if report is not None:
            report["completed_at"] = datetime.now(timezone.utc).isoformat()
            (args.prepared / (args.command + "-report.json")).write_bytes(encoded(report) + b"\n")
    print(json.dumps(result, indent=2))
    return 2 if report and report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
