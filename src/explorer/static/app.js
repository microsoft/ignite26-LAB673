const SVG_NS = "http://www.w3.org/2000/svg";
const svg = document.getElementById("canvas");
const panel = document.getElementById("panel");
const toolbar = document.getElementById("toolbar");
const statusText = document.getElementById("status");

const PALETTE = ["#805124", "#146c94", "#166454", "#8a3a6b", "#b0522c", "#4b5d9b", "#6b7a1f", "#9b4040", "#2f7a7a", "#7a4fa3", "#a07a10", "#3d6b3d"];
const NODE_RADIUS = 16;

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

function toGraphCoords(event) {
  const rect = svg.getBoundingClientRect();
  return { x: (event.clientX - rect.left - view.x) / view.k, y: (event.clientY - rect.top - view.y) / view.k };
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
// Force-directed graph
// ---------------------------------------------------------------------------

class ForceGraph {
  constructor({ onNodeClick, onEdgeClick, alwaysShowEdgeLabels, repulsion = 4000 }) {
    this.repulsion = repulsion;
    this.onNodeClick = onNodeClick;
    this.onEdgeClick = onEdgeClick;
    this.alwaysShowEdgeLabels = alwaysShowEdgeLabels;
    this.nodes = new Map();
    this.edges = [];
    this.selected = null;
    this.frame = null;
  }

  setData(nodes, edges) {
    const rect = svg.getBoundingClientRect();
    const center = { x: (rect.width / 2 - view.x) / view.k, y: (rect.height / 2 - view.y) / view.k };
    const previous = this.nodes;
    this.nodes = new Map();
    for (const node of nodes) {
      const old = previous.get(node.id);
      const anchor = node.near && this.nodes.get(node.near) || previous.get(node.near) || center;
      this.nodes.set(node.id, old ? Object.assign(old, node) : {
        ...node,
        x: anchor.x + (Math.random() - 0.5) * 120,
        y: anchor.y + (Math.random() - 0.5) * 120,
        vx: 0,
        vy: 0,
      });
    }
    this.edges = edges.filter((edge) => this.nodes.has(edge.source) && this.nodes.has(edge.target));
    const pairCounts = new Map();
    for (const edge of this.edges) {
      const key = [edge.source, edge.target].sort().join("|");
      edge.pairIndex = pairCounts.get(key) || 0;
      pairCounts.set(key, edge.pairIndex + 1);
    }
    for (const edge of this.edges) {
      const key = [edge.source, edge.target].sort().join("|");
      edge.pairCount = pairCounts.get(key);
    }
    this.center = center;
    this.render();
    if (previous.size) {
      this.fitPending = true;
      this.start(0.6);
    } else {
      // Lay out a brand new diagram before showing it
      for (this.alpha = 1; this.alpha > 0.01; this.alpha *= 0.98) this.tick();
      this.draw();
      fitToView([...this.nodes.values()]);
    }
  }

  render() {
    resetViewportContents();
    this.edgeLayer = svgEl("g", {}, viewport);
    this.nodeLayer = svgEl("g", {}, viewport);
    for (const edge of this.edges) {
      const group = svgEl("g", { class: "edge" + (this.alwaysShowEdgeLabels ? "" : " hidden-label") }, this.edgeLayer);
      edge.path = svgEl("path", { "marker-end": "url(#arrow)" }, group);
      edge.hit = svgEl("path", { class: "hit" }, group);
      edge.label = svgEl("text", { "text-anchor": "middle" }, group);
      edge.label.textContent = edge.predicate;
      edge.group = group;
      const title = svgEl("title", {}, group);
      title.textContent = edge.predicate;
      group.addEventListener("click", () => this.onEdgeClick?.(edge));
    }
    for (const node of this.nodes.values()) {
      const group = svgEl("g", { class: "node", tabindex: 0, role: "button", "aria-label": `${node.type} ${node.name}` }, this.nodeLayer);
      svgEl("circle", { r: NODE_RADIUS, fill: typeColor(node.type) }, group);
      const label = svgEl("text", { y: NODE_RADIUS + 14, "text-anchor": "middle" }, group);
      label.textContent = shorten(node.name, 28);
      const title = svgEl("title", {}, group);
      title.textContent = `${node.type}: ${node.name}`;
      node.group = group;
      this.attachDrag(node);
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") this.onNodeClick?.(node);
      });
    }
    this.highlight(this.selected);
    this.draw();
  }

  attachDrag(node) {
    node.group.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      const start = { x: event.clientX, y: event.clientY };
      let moved = false;
      const move = (moveEvent) => {
        if (Math.hypot(moveEvent.clientX - start.x, moveEvent.clientY - start.y) > 4) moved = true;
        if (!moved) return;
        const point = toGraphCoords(moveEvent);
        node.fixed = true;
        node.x = point.x;
        node.y = point.y;
        this.start(0.2);
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        if (!moved) this.onNodeClick?.(node);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
  }

  start(alpha) {
    this.alpha = Math.max(this.alpha || 0, alpha);
    if (this.frame) return;
    const step = () => {
      for (let i = 0; i < 3; i++) this.tick();
      this.draw();
      this.alpha *= 0.97;
      this.frame = this.alpha > 0.01 ? requestAnimationFrame(step) : null;
      if (!this.frame && this.fitPending) {
        this.fitPending = false;
        fitToView([...this.nodes.values()]);
      }
    };
    this.frame = requestAnimationFrame(step);
  }

  stop() {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = null;
  }

  tick() {
    const nodes = [...this.nodes.values()];
    const alpha = this.alpha;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        const distanceSquared = Math.max(dx * dx + dy * dy, 100);
        const force = (this.repulsion * alpha) / distanceSquared;
        const distance = Math.sqrt(distanceSquared);
        dx /= distance;
        dy /= distance;
        a.vx -= dx * force; a.vy -= dy * force;
        b.vx += dx * force; b.vy += dy * force;
      }
    }
    for (const edge of this.edges) {
      const a = this.nodes.get(edge.source), b = this.nodes.get(edge.target);
      if (a === b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const distance = Math.max(Math.hypot(dx, dy), 1);
      const force = (distance - 130) * 0.04 * alpha;
      a.vx += (dx / distance) * force; a.vy += (dy / distance) * force;
      b.vx -= (dx / distance) * force; b.vy -= (dy / distance) * force;
    }
    for (const node of nodes) {
      node.vx += (this.center.x - node.x) * 0.005 * alpha;
      node.vy += (this.center.y - node.y) * 0.005 * alpha;
      node.vx *= 0.6;
      node.vy *= 0.6;
      if (!node.fixed) {
        node.x += node.vx;
        node.y += node.vy;
      }
    }
  }

  draw() {
    for (const node of this.nodes.values()) {
      node.group.setAttribute("transform", `translate(${node.x},${node.y})`);
    }
    for (const edge of this.edges) {
      const a = this.nodes.get(edge.source), b = this.nodes.get(edge.target);
      let d, labelX, labelY;
      if (a === b) {
        const r = NODE_RADIUS;
        d = `M${a.x - r * 0.6},${a.y - r * 0.8} C${a.x - 40},${a.y - 70} ${a.x + 40},${a.y - 70} ${a.x + r * 0.6},${a.y - r * 0.8}`;
        labelX = a.x;
        labelY = a.y - 62;
      } else {
        const dx = b.x - a.x, dy = b.y - a.y;
        const distance = Math.max(Math.hypot(dx, dy), 1);
        const bend = (edge.pairIndex - (edge.pairCount - 1) / 2) * 36 * (edge.source < edge.target ? 1 : -1);
        const controlX = (a.x + b.x) / 2 - (dy / distance) * bend;
        const controlY = (a.y + b.y) / 2 + (dx / distance) * bend;
        const endDx = b.x - controlX, endDy = b.y - controlY;
        const endDistance = Math.max(Math.hypot(endDx, endDy), 1);
        const endX = b.x - (endDx / endDistance) * (NODE_RADIUS + 3);
        const endY = b.y - (endDy / endDistance) * (NODE_RADIUS + 3);
        d = `M${a.x},${a.y} Q${controlX},${controlY} ${endX},${endY}`;
        labelX = (a.x + 2 * controlX + b.x) / 4;
        labelY = (a.y + 2 * controlY + b.y) / 4 - 4;
      }
      edge.path.setAttribute("d", d);
      edge.hit.setAttribute("d", d);
      edge.label.setAttribute("x", labelX);
      edge.label.setAttribute("y", labelY);
    }
  }

  highlight(selection) {
    this.selected = selection;
    const connected = new Set();
    for (const edge of this.edges) {
      const touches = selection?.kind === "node" && (edge.source === selection.id || edge.target === selection.id);
      const isSelected = selection?.kind === "edge" && edge.id === selection.id;
      edge.group.classList.toggle("highlight", touches);
      edge.group.classList.toggle("selected", isSelected);
      edge.group.classList.toggle("hidden-label", !this.alwaysShowEdgeLabels && !touches && !isSelected);
      if (touches || isSelected) {
        connected.add(edge.source);
        connected.add(edge.target);
      }
      edge.group.classList.toggle("faded", Boolean(selection) && !this.alwaysShowEdgeLabels && !touches && !isSelected);
    }
    for (const node of this.nodes.values()) {
      const isSelected = selection?.kind === "node" && node.id === selection.id;
      node.group.classList.toggle("selected", isSelected);
      node.group.classList.toggle("faded", Boolean(selection) && !this.alwaysShowEdgeLabels && !isSelected && !connected.has(node.id));
    }
  }
}

function resetViewportContents() {
  viewport.innerHTML = "";
}

// ---------------------------------------------------------------------------
// Ontology tab
// ---------------------------------------------------------------------------

const ontology = { data: null, graph: null };

async function showOntology() {
  toolbar.innerHTML = `<span class="hint">Each circle is an entity type. Each arrow is a relationship from its domain (subject type) to its range (object type). Select a type or arrow to see details. Scroll to zoom, and drag to move.</span>`;
  panel.innerHTML = `<h2>Ontology</h2><p class="muted">The ontology is the schema of the graph: the kinds of entities it can contain and how they can relate. Select a type or relationship to learn more.</p>`;
  resetCanvas();
  setStatus("Loading ontology…");
  try {
    ontology.data ??= await api("/api/ontology");
  } catch (error) {
    return showError(error);
  }
  const { types, relationships } = ontology.data;
  setStatus(`${types.length} entity types, ${relationships.length} relationships`);
  ontology.graph = new ForceGraph({
    alwaysShowEdgeLabels: false,
    repulsion: 9000,
    onNodeClick: (node) => showOntologyType(node.id),
    onEdgeClick: (edge) => showOntologyRelationship(edge.id),
  });
  ontology.graph.setData(
    types.map((type) => ({ id: type.name, name: type.name, type: type.name })),
    relationships.map((relationship) => ({ id: relationship.name, source: relationship.domain, target: relationship.range, predicate: relationship.name })),
  );
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
    <h3>Relationships from ${escapeHtml(name)}</h3>${list(outgoing, "out")}
    <h3>Relationships to ${escapeHtml(name)}</h3>${list(incoming, "in")}`;
  panel.querySelectorAll("[data-relationship]").forEach((button) =>
    button.addEventListener("click", () => showOntologyRelationship(button.dataset.relationship)));
  ontology.graph.highlight({ kind: "node", id: name });
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
  ontology.graph.highlight({ kind: "edge", id: name });
}

// ---------------------------------------------------------------------------
// Graph tab
// ---------------------------------------------------------------------------

const graphState = { nodes: new Map(), edges: new Map(), properties: new Map(), expanded: new Set(), graph: null };

async function showGraph() {
  toolbar.innerHTML = `
    <form id="entity-search">
      <label for="entity-query">Find an entity</label>
      <input type="search" id="entity-query" value="EC26-0811" placeholder="For example, EC26-0811">
      <button type="submit">Search</button>
    </form>
    <button id="clear-graph">Clear</button>`;
  document.getElementById("entity-search").addEventListener("submit", (event) => {
    event.preventDefault();
    searchEntities(document.getElementById("entity-query").value);
  });
  document.getElementById("clear-graph").addEventListener("click", () => {
    graphState.nodes.clear();
    graphState.edges.clear();
    graphState.expanded.clear();
    renderGraph();
    showGraphIntro();
  });
  resetCanvas();
  graphState.graph = new ForceGraph({
    alwaysShowEdgeLabels: true,
    repulsion: 7000,
    onNodeClick: (node) => selectEntity(node.id),
    onEdgeClick: (edge) => showAssertion(edge.id),
  });
  if (graphState.nodes.size) {
    renderGraph();
    showGraphIntro();
  } else {
    showGraphIntro();
    searchEntities("EC26-0811", true);
  }
}

function showGraphIntro() {
  panel.innerHTML = `<h2>Graph</h2>
    <p class="muted">Each circle is an entity, colored by its type. Each arrow is an assertion: subject → predicate → object.</p>
    <ul>
      <li>Select an entity to see its properties and add its neighbors to the diagram.</li>
      <li>Select an arrow to see the evidence behind that assertion.</li>
    </ul>
    <div id="search-results"></div>`;
}

async function searchEntities(query, selectFirst = false) {
  setStatus("Searching…");
  let results;
  try {
    results = await api(`/api/entities?q=${encodeURIComponent(query)}`);
  } catch (error) {
    return showError(error);
  }
  setStatus("");
  if (selectFirst && results.length) return selectEntity(results[0].id);
  showGraphIntro();
  const container = document.getElementById("search-results");
  container.innerHTML = results.length
    ? `<h3>Matching entities</h3><ul>${results.map((r) => `<li><button class="link" data-id="${escapeHtml(r.id)}">${escapeHtml(r.name)}</button> ${typeBadge(r.type)}</li>`).join("")}</ul>`
    : `<p>No entities match “${escapeHtml(query)}”.</p>`;
  container.querySelectorAll("[data-id]").forEach((button) =>
    button.addEventListener("click", () => selectEntity(button.dataset.id)));
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
    for (const node of data.nodes) {
      if (!graphState.nodes.has(node.id)) graphState.nodes.set(node.id, { ...node, near: id });
    }
    for (const edge of data.edges) graphState.edges.set(edge.id, edge);
    graphState.properties.set(id, data.properties);
    graphState.expanded.add(id);
    setStatus("");
    renderGraph();
  }
  showEntity(id);
}

function visibleGraph() {
  const nodes = [...graphState.nodes.values()];
  const ids = new Set(nodes.map((node) => node.id));
  const edges = [...graphState.edges.values()].filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  return { nodes, edges };
}

function renderGraph() {
  const { nodes, edges } = visibleGraph();
  graphState.graph.setData(nodes, edges);
  setStatus(nodes.length ? `${nodes.length} entities, ${edges.length} assertions shown` : "");
}

function showEntity(id) {
  const node = graphState.nodes.get(id);
  const properties = graphState.properties.get(id) || [];
  const { edges } = visibleGraph();
  const related = edges.filter((edge) => edge.source === id || edge.target === id);
  const name = (nodeId) => graphState.nodes.get(nodeId)?.name ?? nodeId;
  panel.innerHTML = `
    <h2>${escapeHtml(node.name)}</h2>${typeBadge(node.type)}
    <p><code>${escapeHtml(id)}</code></p>
    <h3>Properties</h3>
    ${properties.length
      ? `<table>${properties.map((p) => `<tr><td>${escapeHtml(p.predicate)}</td><td><button class="link" data-assertion="${escapeHtml(p.assertion)}">${escapeHtml(shorten(p.value, 120))}</button></td></tr>`).join("")}</table>`
      : `<p class="muted">No literal properties.</p>`}
    <h3>Relationships shown</h3>
    ${related.length
      ? `<ul>${related.map((e) => `<li><button class="link" data-assertion="${escapeHtml(e.id)}">${escapeHtml(name(e.source))} → ${escapeHtml(e.predicate)} → ${escapeHtml(name(e.target))}</button></li>`).join("")}</ul>`
      : `<p class="muted">None</p>`}`;
  panel.querySelectorAll("[data-assertion]").forEach((button) =>
    button.addEventListener("click", () => showAssertion(button.dataset.assertion)));
  graphState.graph.highlight({ kind: "node", id });
}

async function showAssertion(assertionId) {
  setStatus("Loading evidence…");
  let data;
  try {
    data = await api(`/api/evidence?id=${encodeURIComponent(assertionId)}`);
  } catch (error) {
    return showError(error);
  }
  setStatus("");
  const { assertion, source } = data;
  panel.innerHTML = `
    <h2>Assertion</h2>
    <p class="triple">${escapeHtml(assertion.subject)} → ${escapeHtml(assertion.predicate)} → ${escapeHtml(assertion.object)}</p>
    <table>
      <tr><td>Subject</td><td>${escapeHtml(assertion.subject)} ${typeBadge(assertion.subject_type)}<br><code>${escapeHtml(assertion.subject_id)}</code></td></tr>
      <tr><td>Predicate</td><td>${escapeHtml(assertion.predicate)}</td></tr>
      <tr><td>Object</td><td>${escapeHtml(assertion.object)} ${assertion.object_id ? typeBadge(assertion.object_type) + `<br><code>${escapeHtml(assertion.object_id)}</code>` : `<span class="muted">(literal value)</span>`}</td></tr>
    </table>
    <h3>Evidence</h3>
    ${assertion.evidence_quotes?.length
      ? `<p class="muted">Exact excerpts from the PDF-extracted passage:</p><div class="passage">${assertion.evidence_quotes.map(escapeHtml).join("\n\n")}</div>`
      : ""}
    ${source
      ? `<table>
          <tr><td>Source</td><td>${escapeHtml(source.title)}</td></tr>
          <tr><td>Path</td><td><code>${escapeHtml(source.blob_path)}</code></td></tr>
          <tr><td>Pages</td><td>${escapeHtml(source.page_number_from)}–${escapeHtml(source.page_number_to)}</td></tr>
        </table>
        <div class="passage">${escapeHtml(source.chunk)}</div>`
      : `<p class="muted">This assertion has no linked source.</p>`}`;
  graphState.graph.highlight({ kind: "edge", id: assertionId });
}

// ---------------------------------------------------------------------------
// Topics tab
// ---------------------------------------------------------------------------

const topicState = { data: null, selected: null };

async function showTopics() {
  toolbar.innerHTML = `<span class="hint">Broad topics are on the left and their narrower child topics are on the right. Select a topic to read its member passages.</span>`;
  resetCanvas();
  stopActiveGraph();
  setStatus("Loading topics…");
  try {
    topicState.data ??= await api("/api/topics");
  } catch (error) {
    return showError(error);
  }
  const { topics, coverage } = topicState.data;
  setStatus(`${topics.length} topics`);
  panel.innerHTML = `<h2>Topics</h2>
    <p class="muted">Topics group passages with similar embeddings. Labels and descriptions were added from each topic's unchanged member passages. Some broad topics have no narrower children.</p>
    <table>
      <tr><td>Source passages</td><td>${escapeHtml(coverage.source_document_count)}</td></tr>
      <tr><td>Assigned to a topic</td><td>${escapeHtml(coverage.assigned_node_count)}</td></tr>
      <tr><td>Not assigned</td><td>${escapeHtml(coverage.unassigned_source_document_count)}</td></tr>
    </table>`;
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
    count.textContent = `${topic.member_count} passages · ${topic.is_terminal ? "terminal topic" : "parent topic"}`;
    const sample = svgEl("text", { x: 12, y: 62, style: "font-size: 13px" }, group);
    sample.textContent = shorten((topic.sample_titles[0] || "").replace(/\.pdf$/, ""), 40);
    svgEl("title", {}, group).textContent = `${name}\n${topic.description}`;
    group.setAttribute("aria-label", `${name}, level ${topic.level}, ${topic.member_count} passages`);
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
  panel.innerHTML = `<h2>${escapeHtml(name)}</h2>${typeBadge(topic.parent_id ? "Child topic" : "Parent topic")}
    <p><code>${escapeHtml(topic.community_id)}</code></p><p class="muted">Loading member passages…</p>`;
  let members;
  try {
    members = await api(`/api/topic-members?id=${encodeURIComponent(topic.community_id)}&generation=${encodeURIComponent(topicState.data.generation_id)}`);
  } catch (error) {
    return showError(error);
  }
  members.sort((a, b) => a.title.localeCompare(b.title));
  panel.innerHTML = `<h2>${escapeHtml(name)}</h2>${typeBadge(topic.parent_id ? "Child topic" : "Parent topic")}
    <p>${escapeHtml(topic.description)}</p>
    <p><code>${escapeHtml(topic.community_id)}</code></p>
    <h3>${members.length} member passages</h3>
    ${members.map((m) => `<p><strong>${escapeHtml(m.title)}</strong><br><code>${escapeHtml(m.blob_path)}</code></p><div class="passage">${escapeHtml(shorten(m.chunk, 600))}</div>`).join("")}`;
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function stopActiveGraph() {
  ontology.graph?.stop();
  graphState.graph?.stop();
}

const tabs = { ontology: showOntology, graph: showGraph, topics: showTopics };
document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((b) => b.setAttribute("aria-selected", String(b === button)));
    stopActiveGraph();
    history.replaceState(null, "", `#${button.dataset.tab}`);
    tabs[button.dataset.tab]();
  });
});

const initialTab = location.hash.slice(1) in tabs ? location.hash.slice(1) : "ontology";
document.querySelector(`nav button[data-tab="${initialTab}"]`).click();
