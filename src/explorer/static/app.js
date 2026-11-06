const SVG_NS = "http://www.w3.org/2000/svg";
const svg = document.getElementById("canvas");
const panel = document.getElementById("panel");
const toolbar = document.getElementById("toolbar");
const statusText = document.getElementById("status");

const PALETTE = ["#805124", "#146c94", "#166454", "#8a3a6b", "#b0522c", "#4b5d9b", "#6b7a1f", "#9b4040", "#2f7a7a", "#7a4fa3", "#a07a10", "#3d6b3d"];

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const typeColors = new Map();
function typeColor(type) {
  if (!typeColors.has(type)) typeColors.set(type, PALETTE[typeColors.size % PALETTE.length]);
  return typeColors.get(type);
}

function typeBadge(type) {
  return `<span class="type" style="background:${typeColor(type)}">${escapeHtml(type)}</span>`;
}

// Where each tab's data comes from, loaded from the server before the first tab opens
let sources = {};

const SOURCE_KINDS = { index: "Index", file: "File" };

// One row per resource: "From" or "Chunks", a pill colored by resource kind, and optional extras
function sourceRow(label, kind, name, extra = "") {
  return `<div class="source-row"><span class="source-label">${escapeHtml(label)}</span>
    <span class="source-pill ${kind}"><span class="source-kind">${SOURCE_KINDS[kind]}</span>${escapeHtml(name)}</span>${extra}</div>`;
}

function sourceBlock(...rows) {
  return `<div class="sources">${rows.join("")}</div>`;
}

// Long IDs are hashes, so offer a copy button (for pasting into the portal's search explorer) instead of showing them
function copyButton(label, value) {
  return `<button class="link" data-copy="${escapeHtml(value)}" title="${escapeHtml(value)}">${escapeHtml(label)}</button>`;
}

function chunkSource(chunkId) {
  return sourceBlock(sourceRow("From", "index", sources.chunks_index, copyButton("Copy ID", chunkId)));
}

panel.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  event.preventDefault();
  await navigator.clipboard.writeText(button.dataset.copy);
  const label = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => { button.textContent = label; }, 1500);
});

// Link to an original PDF, served by the explorer from data/cocoarynth/documents
function documentLink(blobPath, title) {
  return `<a href="/documents${escapeHtml(blobPath)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>`;
}

function shorten(text, length) {
  text = String(text ?? "");
  return text.length > length ? text.slice(0, length - 1) + "…" : text;
}

function svgEl(tag, attrs = {}, parent = null) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  if (parent) parent.appendChild(element);
  return element;
}

async function api(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function setStatus(text) {
  statusText.textContent = text;
}

function showError(error) {
  setStatus("");
  panel.innerHTML = `<h2>Something went wrong</h2><p class="error">${escapeHtml(error.message)}</p>
    <p class="muted">Check that the graph and topic indexes exist on your Foundry IQ service and that your <code>.env</code> file is correct.</p>`;
}

// ---------------------------------------------------------------------------
// Pan and zoom
// ---------------------------------------------------------------------------

const view = { x: 0, y: 0, k: 1 };
let viewport;

function resetCanvas() {
  svg.innerHTML = "";
  const defs = svgEl("defs", {}, svg);
  const marker = svgEl("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 10, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs);
  svgEl("path", { d: "M0,0 L10,5 L0,10 Z", fill: "#9c8574" }, marker);
  viewport = svgEl("g", {}, svg);
  Object.assign(view, { x: 0, y: 0, k: 1 });
  applyView();
}

function applyView() {
  viewport.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
}

function fitToView(points, padding = 60) {
  if (!points.length) return;
  const rect = svg.getBoundingClientRect();
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const minX = Math.min(...xs) - padding, maxX = Math.max(...xs) + padding;
  const minY = Math.min(...ys) - padding, maxY = Math.max(...ys) + padding;
  const k = Math.min(1.2, rect.width / (maxX - minX), rect.height / (maxY - minY));
  view.k = k;
  view.x = (rect.width - (minX + maxX) * k) / 2;
  view.y = (rect.height - (minY + maxY) * k) / 2;
  applyView();
}

svg.addEventListener("wheel", (event) => {
  event.preventDefault();
  const rect = svg.getBoundingClientRect();
  const mouseX = event.clientX - rect.left;
  const mouseY = event.clientY - rect.top;
  const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1;
  const k = Math.min(4, Math.max(0.2, view.k * factor));
  view.x = mouseX - ((mouseX - view.x) * k) / view.k;
  view.y = mouseY - ((mouseY - view.y) * k) / view.k;
  view.k = k;
  applyView();
}, { passive: false });

let pan = null;
svg.addEventListener("pointerdown", (event) => {
  if (event.target !== svg) return;
  pan = { x: event.clientX - view.x, y: event.clientY - view.y };
  svg.classList.add("dragging");
});
window.addEventListener("pointermove", (event) => {
  if (!pan) return;
  view.x = event.clientX - pan.x;
  view.y = event.clientY - pan.y;
  applyView();
});
window.addEventListener("pointerup", () => {
  pan = null;
  svg.classList.remove("dragging");
});

// ---------------------------------------------------------------------------
// Graph ontology tab
// ---------------------------------------------------------------------------

const ontology = { data: null, cy: null };
const cyContainer = document.getElementById("cy");
cytoscape.use(cytoscapeDagre);

// Node and edge styles follow the Microsoft Ontology Playground (https://microsoft.github.io/Ontology-Playground/)
const ONTOLOGY_STYLE = [
  {
    selector: "node",
    style: {
      label: "data(label)", "text-valign": "bottom", "text-halign": "center", "text-margin-y": 8,
      "font-size": "16px", "font-family": "Segoe UI, sans-serif", "font-weight": 600, color: "#2b1d15",
      width: 46, height: 46, "background-color": "data(color)",
      "border-width": 3, "border-color": "data(color)", "border-opacity": 0.5,
    },
  },
  { selector: "node.selected", style: { "border-width": 5, "border-color": "#0078D4", "border-opacity": 1, width: 58, height: 58 } },
  { selector: "node.highlighted", style: { "border-width": 4, "border-color": "#FFB900", "border-opacity": 1 } },
  { selector: ".dimmed", style: { opacity: 0.2 } },
  {
    selector: "edge",
    style: {
      label: "data(label)", "font-size": "13px", "font-family": "Segoe UI, sans-serif", color: "#6b5a4e",
      "text-background-color": "#fbf8f2", "text-background-opacity": 1, "text-background-padding": "2px",
      "text-background-shape": "roundrectangle",
      width: 2.5, "line-color": "#b8a593", "target-arrow-color": "#b8a593", "target-arrow-shape": "triangle",
      "curve-style": "bezier", "control-point-step-size": 40, "loop-direction": "-45deg", "loop-sweep": "-60deg",
    },
  },
  { selector: "edge.highlighted", style: { width: 4, "line-color": "#FFB900", "target-arrow-color": "#FFB900", color: "#8a6500" } },
  { selector: "edge.selected", style: { width: 5, "line-color": "#0078D4", "target-arrow-color": "#0078D4", color: "#0078D4" } },
  { selector: "edge.hovered", style: { width: 4, "line-color": "#0078D4", "target-arrow-color": "#0078D4", color: "#0078D4" } },
];

async function showOntology() {
  svg.style.display = "none";
  cyContainer.hidden = false;
  toolbar.innerHTML = "";
  showOntologyIntro();
  setStatus("Loading ontology…");
  try {
    ontology.data ??= await api("/api/ontology");
  } catch (error) {
    return showError(error);
  }
  if (activeTab !== "ontology") return;  // The user switched tabs while this loaded
  const { types, relationships } = ontology.data;
  setStatus(`${types.length} entity types, ${relationships.length} relationships`);
  ontology.cy?.destroy();
  ontology.cy = cytoscape({
    container: cyContainer,
    elements: [
      ...types.map((type) => ({ data: { id: type.name, label: type.name, color: typeColor(type.name) } })),
      ...relationships.map((r) => ({ data: { id: `rel:${r.name}`, name: r.name, label: r.name, source: r.domain, target: r.range } })),
    ],
    style: ONTOLOGY_STYLE,
  });
  // A layered layout gives the same left-to-right picture on every load
  ontology.cy.layout({ name: "dagre", rankDir: "LR", nodeSep: 45, rankSep: 150, edgeSep: 10, padding: 30 }).run();
  ontology.cy.on("tap", "node", (event) => showOntologyType(event.target.id()));
  ontology.cy.on("tap", "edge", (event) => showOntologyRelationship(event.target.data("name")));
  ontology.cy.on("mouseover", "edge", (event) => event.target.addClass("hovered"));
  ontology.cy.on("mouseout", "edge", (event) => event.target.removeClass("hovered"));
  ontology.cy.on("tap", (event) => {
    if (event.target === ontology.cy) {
      highlightOntology(null);
      showOntologyIntro();
    }
  });
}

function showOntologyIntro() {
  panel.innerHTML = `<h2>Graph ontology</h2>
    ${sourceBlock(sourceRow("From", "file", sources.ontology_file))}
    <p class="muted">The ontology is the schema of the graph: the kinds of entities it can contain and how they can relate.</p>
    <p class="muted">Each circle is an entity type. Each arrow is a relationship from its domain (subject type) to its range (object type).</p>
    <p class="muted">Select a type or arrow to see details. Scroll to zoom, and drag to move.</p>`;
}

function highlightOntology(selected) {
  highlightElement(ontology.cy, selected);
}

function showOntologyType(name) {
  const { types, relationships } = ontology.data;
  const type = types.find((t) => t.name === name);
  const outgoing = relationships.filter((r) => r.domain === name);
  const incoming = relationships.filter((r) => r.range === name);
  const list = (items, direction) => items.length
    ? `<ul>${items.map((r) => `<li><button class="link" data-relationship="${escapeHtml(r.name)}">${escapeHtml(direction === "out" ? `${r.name} → ${r.range}` : `${r.domain} → ${r.name}`)}</button></li>`).join("")}</ul>`
    : `<p class="muted">None</p>`;
  panel.innerHTML = `
    <h2>${escapeHtml(name)}</h2>${typeBadge("Entity type")}
    <p>${escapeHtml(type?.comment)}</p>
    <p><button class="link" id="show-type-in-graph">Show ${escapeHtml(name)} in Graph entities →</button></p>
    <h3>Relationships from ${escapeHtml(name)}</h3>${list(outgoing, "out")}
    <h3>Relationships to ${escapeHtml(name)}</h3>${list(incoming, "in")}`;
  panel.querySelectorAll("[data-relationship]").forEach((button) =>
    button.addEventListener("click", () => showOntologyRelationship(button.dataset.relationship)));
  document.getElementById("show-type-in-graph").addEventListener("click", () => {
    graphState.pendingType = name;
    document.querySelector('nav button[data-tab="graph"]').click();
  });
  highlightOntology(ontology.cy.getElementById(name));
}

function showOntologyRelationship(name) {
  const relationship = ontology.data.relationships.find((r) => r.name === name);
  panel.innerHTML = `
    <h2>${escapeHtml(name)}</h2>${typeBadge("Relationship")}
    <p class="triple">${escapeHtml(relationship.domain)} → ${escapeHtml(name)} → ${escapeHtml(relationship.range)}</p>
    <p>${escapeHtml(relationship.comment)}</p>
    <table>
      <tr><td>Domain (subject type)</td><td><button class="link" data-type="${escapeHtml(relationship.domain)}">${escapeHtml(relationship.domain)}</button></td></tr>
      <tr><td>Range (object type)</td><td><button class="link" data-type="${escapeHtml(relationship.range)}">${escapeHtml(relationship.range)}</button></td></tr>
    </table>`;
  panel.querySelectorAll("[data-type]").forEach((button) =>
    button.addEventListener("click", () => showOntologyType(button.dataset.type)));
  highlightOntology(ontology.cy.getElementById(`rel:${name}`));
}

// ---------------------------------------------------------------------------
// Graph entities tab
// ---------------------------------------------------------------------------

const graphState = {
  nodes: new Map(), edges: new Map(), properties: new Map(), expanded: new Set(),
  selected: null, pendingType: null, restored: false, catalog: null, cy: null,
};
const graphContainer = document.getElementById("graph-cy");
const GRAPH_STORAGE_KEY = "cocoarynth-explorer-graph";

// Positions aren't saved: the layered layout always draws the same graph the same way
function saveGraphState() {
  try {
    localStorage.setItem(GRAPH_STORAGE_KEY, JSON.stringify({
      nodes: [...graphState.nodes.values()],
      edges: [...graphState.edges.values()],
      properties: [...graphState.properties.entries()],
      expanded: [...graphState.expanded],
      selected: graphState.selected,
    }));
  } catch {
    // Storage can be full or unavailable (for example, in private browsing); the explorer still works without it
  }
}

// Returns true when a saved graph was found, even an empty one
function restoreGraphState() {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(GRAPH_STORAGE_KEY));
  } catch {
    return false;
  }
  if (!saved) return false;
  graphState.nodes = new Map(saved.nodes.map((node) => [node.id, node]));
  graphState.edges = new Map(saved.edges.map((edge) => [edge.id, edge]));
  graphState.properties = new Map(saved.properties);
  graphState.expanded = new Set(saved.expanded);
  graphState.selected = saved.selected;
  return true;
}

async function showGraph() {
  svg.style.display = "none";
  graphContainer.hidden = false;
  toolbar.innerHTML = `
    <form id="entity-search">
      <label for="entity-query">Find an entity</label>
      <input type="search" id="entity-query" placeholder="Name, for example Las Brisas">
      <button type="submit">Search</button>
    </form>
    <button id="show-all">Show everything</button>
    <button id="clear-graph">Clear</button>`;
  document.getElementById("entity-search").addEventListener("submit", (event) => {
    event.preventDefault();
    searchEntities(document.getElementById("entity-query").value);
  });
  document.getElementById("show-all").addEventListener("click", showAllEntities);
  document.getElementById("clear-graph").addEventListener("click", () => {
    graphState.nodes.clear();
    graphState.edges.clear();
    graphState.properties.clear();
    graphState.expanded.clear();
    graphState.selected = null;
    renderGraph();
    showGraphIntro();
  });
  graphState.cy?.destroy();
  graphState.cy = cytoscape({ container: graphContainer, style: ONTOLOGY_STYLE });
  graphState.cy.on("tap", "node", (event) => selectEntity(event.target.id()));
  graphState.cy.on("tap", "edge", (event) => showFact(event.target.id()));
  graphState.cy.on("mouseover", "edge", (event) => event.target.addClass("hovered"));
  graphState.cy.on("mouseout", "edge", (event) => event.target.removeClass("hovered"));
  graphState.cy.on("tap", (event) => {
    if (event.target === graphState.cy) {
      highlightElement(graphState.cy, null);
      graphState.selected = null;
      saveGraphState();
      showGraphIntro();
    }
  });
  const hasSavedGraph = graphState.restored || restoreGraphState();
  graphState.restored = true;
  if (graphState.pendingType) {
    const type = graphState.pendingType;
    graphState.pendingType = null;
    renderGraph();
    showTypeInGraph(type);
  } else if (hasSavedGraph) {
    renderGraph();
    if (graphState.selected && graphState.nodes.has(graphState.selected)) showEntity(graphState.selected);
    else showGraphIntro();
  } else {
    showGraphIntro();
    selectEntity("urn:cocoarynth:Batch:EC26-0811");
  }
}

async function showTypeInGraph(typeName) {
  setStatus(`Loading ${typeName} entities…`);
  let catalog;
  try {
    catalog = graphState.catalog ??= await api("/api/catalog");
  } catch (error) {
    return showError(error);
  }
  if (activeTab !== "graph") return;  // The user switched tabs while this loaded
  const type = catalog.types.find((t) => t.name === typeName);
  for (const entity of type?.entities || []) if (!graphState.nodes.has(entity.id)) graphState.nodes.set(entity.id, entity);
  // Connect the new entities to anything already shown
  for (const edge of catalog.edges) {
    if (graphState.nodes.has(edge.source) && graphState.nodes.has(edge.target)) graphState.edges.set(edge.id, edge);
  }
  renderGraph();
  await showGraphIntro();
  document.querySelectorAll("#type-list details").forEach((details) => {
    details.open = details.dataset.type === typeName;
  });
}

async function showGraphIntro() {
  panel.innerHTML = `<h2>Graph entities</h2>
    ${sourceBlock(sourceRow("From", "index", sources.graph_index), sourceRow("Chunks", "index", sources.chunks_index))}
    <p class="muted">Each circle is an entity, colored by its type. Each arrow is a fact: subject → predicate → object.</p>
    <p class="muted">Select an entity to see its properties and add its neighbors. Select an arrow to see the chunks that support it. Scroll to zoom, and drag to move.</p>
    <div id="search-results"></div>
    <h3>Browse by type</h3>
    <div id="type-list"><p class="muted">Loading…</p></div>`;
  let catalog;
  try {
    catalog = graphState.catalog ??= await api("/api/catalog");
  } catch (error) {
    return showError(error);
  }
  const list = document.getElementById("type-list");
  if (activeTab !== "graph" || !list) return;  // The user moved on while the catalog loaded
  list.innerHTML = catalog.types.map((type) => `
    <details class="type-group" data-type="${escapeHtml(type.name)}"><summary>${typeBadge(type.name)} <span class="muted">${type.entities.length}</span></summary>
      <ul>${type.entities.map((e) => `<li><button class="link" data-id="${escapeHtml(e.id)}">${escapeHtml(e.name)}</button></li>`).join("")}</ul>
    </details>`).join("");
  list.querySelectorAll("[data-id]").forEach((button) =>
    button.addEventListener("click", () => selectEntity(button.dataset.id)));
}

async function searchEntities(query) {
  setStatus("Searching…");
  let results;
  try {
    results = await api(`/api/entities?q=${encodeURIComponent(query)}`);
  } catch (error) {
    return showError(error);
  }
  if (activeTab !== "graph") return;  // The user switched tabs while this loaded
  setStatus("");
  await showGraphIntro();
  const container = document.getElementById("search-results");
  container.innerHTML = results.length
    ? `<h3>Matching entities</h3><ul>${results.map((r) => `<li><button class="link" data-id="${escapeHtml(r.id)}">${escapeHtml(r.name)}</button> ${typeBadge(r.type)}</li>`).join("")}</ul>`
    : `<p>No entities match “${escapeHtml(query)}”.</p>`;
  container.querySelectorAll("[data-id]").forEach((button) =>
    button.addEventListener("click", () => selectEntity(button.dataset.id)));
}

async function showAllEntities() {
  setStatus("Loading all entities…");
  let catalog;
  try {
    catalog = graphState.catalog ??= await api("/api/catalog");
  } catch (error) {
    return showError(error);
  }
  if (activeTab !== "graph") return;  // The user switched tabs while this loaded
  // Entities with only literal properties would appear as loose dots, so show just the connected ones
  const connected = new Set(catalog.edges.flatMap((edge) => [edge.source, edge.target]));
  for (const type of catalog.types) {
    for (const entity of type.entities) {
      if (connected.has(entity.id) && !graphState.nodes.has(entity.id)) graphState.nodes.set(entity.id, entity);
    }
  }
  for (const edge of catalog.edges) graphState.edges.set(edge.id, edge);
  renderGraph();
  const hidden = catalog.types.reduce((count, type) => count + type.entities.length, 0) - connected.size;
  setStatus(`${statusText.textContent}. ${hidden} entities with no relationships are listed under Browse by type.`);
}

async function selectEntity(id) {
  if (!graphState.expanded.has(id)) {
    setStatus("Loading neighbors…");
    let data;
    try {
      data = await api(`/api/neighbors?id=${encodeURIComponent(id)}`);
    } catch (error) {
      return showError(error);
    }
    if (activeTab !== "graph") return;  // The user switched tabs while this loaded
    for (const node of data.nodes) if (!graphState.nodes.has(node.id)) graphState.nodes.set(node.id, node);
    for (const edge of data.edges) graphState.edges.set(edge.id, edge);
    graphState.properties.set(id, data.properties);
    graphState.expanded.add(id);
    renderGraph();
  }
  showEntity(id);
}

function renderGraph() {
  const cy = graphState.cy;
  const nodes = [...graphState.nodes.values()];
  const edges = [...graphState.edges.values()].filter((e) => graphState.nodes.has(e.source) && graphState.nodes.has(e.target));
  const added = cy.add([
    ...nodes.filter((n) => cy.getElementById(n.id).empty())
      .map((n) => ({ data: { id: n.id, label: n.name, color: typeColor(n.type) } })),
    ...edges.filter((e) => cy.getElementById(e.id).empty())
      .map((e) => ({ data: { id: e.id, label: e.predicate, source: e.source, target: e.target } })),
  ]);
  cy.elements().not(cy.collection(nodes.map((n) => cy.getElementById(n.id))).union(cy.collection(edges.map((e) => cy.getElementById(e.id))))).remove();
  if (added.nonempty() || !nodes.length) {
    const previous = new Map(cy.nodes().not(added).map((node) => [node.id(), { ...node.position() }]));
    cy.layout({ name: "dagre", rankDir: "LR", nodeSep: 45, rankSep: 150, edgeSep: 10, fit: false }).run();
    packComponents(cy);
    // Animate the nodes that were already shown to their new places, so the change is easy to follow
    const targets = new Map(cy.nodes().map((node) => [node.id(), { ...node.position() }]));
    for (const [id, position] of previous) cy.getElementById(id).position(position);
    for (const [id] of previous) cy.getElementById(id).animate({ position: targets.get(id) }, { duration: 400 });
    cy.animate({ fit: { eles: cy.elements(), padding: 30 } }, { duration: previous.size ? 400 : 0 });
  }
  setStatus(nodes.length ? `${nodes.length} entities, ${edges.length} facts shown` : "");
  saveGraphState();
}

// dagre stacks unconnected groups of entities in one tall column; arrange them in rows that suit the canvas instead
function packComponents(cy, gap = 60) {
  const components = cy.elements().components().sort((a, b) => b.nodes().length - a.nodes().length);
  if (components.length < 2) return;
  const boxes = components.map((component) => component.boundingBox({ includeLabels: true }));
  const area = boxes.reduce((sum, box) => sum + (box.w + gap) * (box.h + gap), 0);
  const rowWidth = Math.max(...boxes.map((box) => box.w), Math.sqrt(area * (cy.width() / cy.height())));
  let x = 0, y = 0, rowHeight = 0;
  components.forEach((component, i) => {
    const box = boxes[i];
    if (x > 0 && x + box.w > rowWidth) {
      x = 0;
      y += rowHeight + gap;
      rowHeight = 0;
    }
    const dx = x - box.x1, dy = y - box.y1;
    component.nodes().positions((node) => ({ x: node.position("x") + dx, y: node.position("y") + dy }));
    x += box.w + gap;
    rowHeight = Math.max(rowHeight, box.h);
  });
}

function highlightElement(cy, selected) {
  cy.elements().removeClass("selected highlighted dimmed");
  if (!selected || selected.empty()) return;
  const focus = selected.isNode() ? selected.closedNeighborhood() : selected.union(selected.connectedNodes());
  selected.addClass("selected");
  focus.not(selected).addClass("highlighted");
  cy.elements().not(focus).addClass("dimmed");
}

function showEntity(id) {
  graphState.selected = id;
  saveGraphState();
  const node = graphState.nodes.get(id);
  const properties = graphState.properties.get(id) || [];
  const related = [...graphState.edges.values()].filter((e) => (e.source === id || e.target === id) && graphState.nodes.has(e.source) && graphState.nodes.has(e.target));
  const name = (nodeId) => graphState.nodes.get(nodeId)?.name ?? nodeId;
  panel.innerHTML = `
    <h2>${escapeHtml(node.name)}</h2>${typeBadge(node.type)}
    ${sourceBlock(sourceRow("From", "index", sources.graph_index, copyButton("Copy ID", id)))}
    <h3>Properties</h3>
    ${properties.length
      ? `<table>${properties.map((p) => `<tr><td>${escapeHtml(p.predicate)}</td><td><button class="link" data-fact="${escapeHtml(p.fact)}">${escapeHtml(shorten(p.value, 120))}</button></td></tr>`).join("")}</table>`
      : `<p class="muted">No literal properties.</p>`}
    <h3>Relationships</h3>
    ${related.length
      ? `<ul>${related.map((e) => `<li><button class="link" data-fact="${escapeHtml(e.id)}">${escapeHtml(name(e.source))} → ${escapeHtml(e.predicate)} → ${escapeHtml(name(e.target))}</button></li>`).join("")}</ul>`
      : `<p class="muted">None</p>`}`;
  panel.querySelectorAll("[data-fact]").forEach((button) =>
    button.addEventListener("click", () => showFact(button.dataset.fact)));
  highlightElement(graphState.cy, graphState.cy.getElementById(id));
}

async function showFact(factId) {
  setStatus("Loading evidence…");
  let data;
  try {
    data = await api(`/api/evidence?id=${encodeURIComponent(factId)}`);
  } catch (error) {
    return showError(error);
  }
  if (activeTab !== "graph") return;  // The user switched tabs while this loaded
  setStatus("");
  const { fact, supports } = data;
  panel.innerHTML = `
    <h2>Fact</h2>
    ${sourceBlock(sourceRow("From", "index", sources.graph_index, copyButton("Copy ID", fact.fact_id)))}
    <p class="triple">${escapeHtml(fact.subject)} → ${escapeHtml(fact.predicate)} → ${escapeHtml(fact.object)}</p>
    <table>
      <tr><td>Subject</td><td>${escapeHtml(fact.subject)} ${typeBadge(fact.subject_type)}<br><code>${escapeHtml(fact.subject_id)}</code></td></tr>
      <tr><td>Predicate</td><td>${escapeHtml(fact.predicate)}</td></tr>
      <tr><td>Object</td><td>${escapeHtml(fact.object)} ${fact.object_id ? typeBadge(fact.object_type) + `<br><code>${escapeHtml(fact.object_id)}</code>` : `<span class="muted">(literal value)</span>`}</td></tr>
    </table>
    <h3>Evidence from ${supports.length} chunk${supports.length === 1 ? "" : "s"}</h3>
    ${supports.map(({ evidence_quotes, source }) => `
      <p><strong>${source ? documentLink(source.blob_path, source.title) : "Unknown source"}</strong>${source ? `, pages ${escapeHtml(source.page_number_from)}–${escapeHtml(source.page_number_to)}` : ""}</p>
      ${evidence_quotes.length ? `<p class="muted">Exact excerpts:</p><div class="chunk-text">${evidence_quotes.map(escapeHtml).join("\n\n")}</div>` : ""}
      ${source ? `<details><summary>Full chunk text</summary>${chunkSource(source.chunk_id)}<div class="chunk-text">${escapeHtml(source.chunk)}</div></details>` : ""}`).join("")}`;
  highlightElement(graphState.cy, graphState.cy.getElementById(factId));
}

// ---------------------------------------------------------------------------
// Topics tab
// ---------------------------------------------------------------------------

const topicState = { data: null, selected: null };

async function showTopics() {
  toolbar.innerHTML = `<span class="hint">Broad topics are on the left and their narrower child topics are on the right. Select a topic to read its member chunks.</span>`;
  resetCanvas();
  setStatus("Loading topics…");
  try {
    topicState.data ??= await api("/api/topics");
  } catch (error) {
    return showError(error);
  }
  if (activeTab !== "topics") return;  // The user switched tabs while this loaded
  const { topics, coverage } = topicState.data;
  setStatus(`${topics.length} topics`);
  panel.innerHTML = `<h2>Topics</h2>
    ${sourceBlock(sourceRow("From", "index", sources.topics_index), sourceRow("Chunks", "index", sources.chunks_index))}
    <p class="muted">Topics group chunks with similar embeddings. Labels and descriptions were added from each topic's unchanged member chunks. Some broad topics have no narrower children.</p>
    <table>
      <tr><td>Source chunks</td><td>${escapeHtml(coverage.source_document_count)}</td></tr>
      <tr><td>Assigned to a topic</td><td>${escapeHtml(coverage.assigned_node_count)}</td></tr>
      <tr><td>Not assigned</td><td>${escapeHtml(coverage.unassigned_source_document_count)}</td></tr>
    </table>
    <h3>Sitemap</h3>
    <p class="muted">The topic hierarchy is also stored as a navigation graph, called the sitemap, so a knowledge base can traverse it with graph search. Its schema has three relationships:</p>
    <table>
      <tr><td>${typeBadge("Topic")} → <strong>hasSubtopic</strong> → ${typeBadge("Topic")}</td></tr>
      <tr><td>${typeBadge("Topic")} → <strong>hasMember</strong> → ${typeBadge("TextChunk")}</td></tr>
      <tr><td>${typeBadge("Document")} → <strong>hasTextChunk</strong> → ${typeBadge("TextChunk")}</td></tr>
    </table>
    <p class="muted">The arrows in the diagram are <strong>hasSubtopic</strong>. Select a topic to see its <strong>hasMember</strong> chunks, grouped by their document.</p>`;
  drawTopicTree(topics);
}

function drawTopicTree(topics) {
  const parents = topics.filter((t) => !t.parent_id).sort((a, b) => a.community_id.localeCompare(b.community_id));
  const width = 330, height = 74, rowGap = 92;
  let row = 0;
  const positions = new Map();
  for (const parent of parents) {
    const children = topics.filter((t) => t.parent_id === parent.community_id).sort((a, b) => a.community_id.localeCompare(b.community_id));
    const firstRow = row;
    for (const child of children) positions.set(child.community_id, { x: 440, y: 40 + rowGap * row++ });
    if (!children.length) row++;
    positions.set(parent.community_id, { x: 40, y: 40 + rowGap * (firstRow + Math.max(children.length - 1, 0) / 2) });
    row += 0.4;
  }
  const edgeLayer = svgEl("g", {}, viewport);
  const nodeLayer = svgEl("g", {}, viewport);
  for (const topic of topics) {
    const position = positions.get(topic.community_id);
    if (!position) continue;
    const parentPosition = topic.parent_id && positions.get(topic.parent_id);
    if (parentPosition) {
      const startX = parentPosition.x + width, startY = parentPosition.y + height / 2;
      const endX = position.x, endY = position.y + height / 2;
      svgEl("path", { d: `M${startX},${startY} C${startX + 40},${startY} ${endX - 40},${endY} ${endX - 4},${endY}`, stroke: "#9c8574", "stroke-width": 1.5, fill: "none", "marker-end": "url(#arrow)" }, edgeLayer);
    }
    const group = svgEl("g", { class: "topic", transform: `translate(${position.x},${position.y})`, tabindex: 0, role: "button" }, nodeLayer);
    svgEl("rect", { width, height, rx: 8, stroke: topic.parent_id ? "#146c94" : "#805124" }, group);
    const name = topic.label || `Topic ${topic.community_id.slice(0, 8)}`;
    const title = svgEl("text", { x: 12, y: 22, style: "font-size: 15px; font-weight: 600" }, group);
    title.textContent = shorten(name, 34);
    const count = svgEl("text", { x: 12, y: 44, style: "font-size: 13px" }, group);
    count.textContent = `${topic.member_count} chunks · ${topic.is_terminal ? "terminal topic" : "parent topic"}`;
    const sample = svgEl("text", { x: 12, y: 62, style: "font-size: 13px" }, group);
    sample.textContent = shorten((topic.sample_titles[0] || "").replace(/\.pdf$/, ""), 40);
    svgEl("title", {}, group).textContent = `${name}\n${topic.description}`;
    group.setAttribute("aria-label", `${name}, level ${topic.level}, ${topic.member_count} chunks`);
    topic.group = group;
    group.addEventListener("click", () => showTopic(topic));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") showTopic(topic);
    });
  }
  const corners = [...positions.values()].flatMap((p) => [p, { x: p.x + width, y: p.y + height }]);
  fitToView(corners, 20);
}

async function showTopic(topic) {
  for (const t of topicState.data.topics) t.group?.classList.toggle("selected", t === topic);
  const name = topic.label || `Topic ${topic.community_id.slice(0, 8)}`;
  const header = `<h2>${escapeHtml(name)}</h2>${typeBadge(topic.parent_id ? "Child topic" : "Parent topic")}
    ${sourceBlock(sourceRow("From", "index", sources.topics_index), sourceRow("Chunks", "index", sources.chunks_index))}
    <p>${escapeHtml(topic.description)}</p>`;
  panel.innerHTML = `${header}<p class="muted">Loading member chunks…</p>`;
  let members;
  try {
    members = await api(`/api/topic-members?id=${encodeURIComponent(topic.community_id)}&generation=${encodeURIComponent(topicState.data.generation_id)}`);
  } catch (error) {
    return showError(error);
  }
  if (activeTab !== "topics") return;  // The user switched tabs while this loaded
  const documents = new Map();
  for (const member of members) documents.set(member.blob_path, [...(documents.get(member.blob_path) || []), member]);
  const sorted = [...documents.entries()].sort(([, a], [, b]) => a[0].title.localeCompare(b[0].title));
  panel.innerHTML = `${header}
    <h3>${members.length} member chunks, from ${documents.size} documents</h3>
    <p><button class="link" id="toggle-chunks">Expand all chunks</button></p>
    ${sorted.map(([path, chunks]) => `
      <p class="document">${documentLink(path, chunks[0].title)}
        <span class="muted">${chunks.length} chunk${chunks.length === 1 ? "" : "s"}</span></p>
      ${chunks.map((member, i) => `<details class="member"><summary>Chunk ${i + 1}</summary>${chunkSource(member.chunk_id)}<div class="chunk-text">${escapeHtml(member.chunk)}</div></details>`).join("")}`).join("")}`;
  const toggle = document.getElementById("toggle-chunks");
  toggle.addEventListener("click", () => {
    const chunks = panel.querySelectorAll("details.member");
    const expand = [...chunks].some((details) => !details.open);
    chunks.forEach((details) => { details.open = expand; });
    toggle.textContent = expand ? "Collapse all chunks" : "Expand all chunks";
  });
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

let activeTab = null;
const tabs = { ontology: showOntology, graph: showGraph, topics: showTopics };
document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((b) => b.setAttribute("aria-selected", String(b === button)));
    svg.style.display = "";
    cyContainer.hidden = true;
    graphContainer.hidden = true;
    panel.innerHTML = "";
    activeTab = button.dataset.tab;
    history.replaceState(null, "", `#${button.dataset.tab}`);
    tabs[button.dataset.tab]();
  });
});

const initialTab = location.hash.slice(1) in tabs ? location.hash.slice(1) : "ontology";
api("/api/sources").then((data) => {
  sources = data;
  document.querySelector(`nav button[data-tab="${initialTab}"]`).click();
}, showError);
