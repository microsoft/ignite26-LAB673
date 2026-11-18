const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const app = readFileSync(path.join(root, "src", "explorer", "static", "app.js"), "utf8");

function explorer(catalog) {
  const status = { textContent: "" };
  const groups = catalog.types.map((type) => ({ dataset: { type: type.name }, open: false }));
  const element = { addEventListener() {} };
  const context = vm.createContext({
    catalog,
    document: {
      getElementById: (id) => id === "status" ? status : element,
      querySelectorAll: (selector) => selector === "#type-list details" ? groups : [],
    },
    window: element,
    location: { hash: "" },
    cytoscape: { use() {} },
    cytoscapeDagre: {},
    fetch: () => new Promise(() => {}),
  });
  vm.runInContext(app, context);
  vm.runInContext(`
    activeTab = "graph";
    graphState.catalog = catalog;
    renderGraph = () => setStatus(graphState.nodes.size + " entities, " + graphState.edges.size + " facts shown");
    showGraphIntro = async () => {};
  `, context);
  return {
    run: (code) => vm.runInContext(code, context),
    ids: (kind) => Array.from(vm.runInContext(`[...graphState.${kind}.keys()]`, context)).sort(),
    status,
    groups,
  };
}

test("type navigation adds incoming and outgoing neighbors without expanding beyond one hop", async () => {
  const catalog = {
    types: [
      { name: "BeanLot", entities: [{ id: "lot", name: "Lot", type: "BeanLot" }, { id: "isolated", name: "Isolated", type: "BeanLot" }] },
      { name: "Batch", entities: [{ id: "batch", name: "Batch", type: "Batch" }] },
      { name: "Supplier", entities: [{ id: "supplier", name: "Supplier", type: "Supplier" }] },
      { name: "Case", entities: [{ id: "case", name: "Case", type: "Case" }] },
    ],
    edges: [
      { id: "incoming", source: "batch", target: "lot" },
      { id: "outgoing", source: "lot", target: "supplier" },
      { id: "second-hop", source: "case", target: "batch" },
    ],
  };
  const app = explorer(catalog);
  await app.run('showTypeInGraph("BeanLot")');
  assert.deepEqual(app.ids("nodes"), ["batch", "lot", "supplier"]);
  assert.deepEqual(app.ids("edges"), ["incoming", "outgoing"]);
  assert.match(app.status.textContent, /1 BeanLot entities with no relationships/);
  assert.equal(app.groups.find((group) => group.dataset.type === "BeanLot").open, true);

  await app.run('showTypeInGraph("BeanLot")');
  assert.deepEqual(app.ids("nodes"), ["batch", "lot", "supplier"]);
  app.run('graphState.nodes.set("case", { id: "case" })');
  await app.run('showTypeInGraph("BeanLot")');
  assert.deepEqual(app.ids("nodes"), ["batch", "case", "lot", "supplier"]);
  assert.deepEqual(app.ids("edges"), ["incoming", "outgoing", "second-hop"]);
});

test("BeanLot navigation shows every relationship in the lab snapshot without adding property-only lots", async () => {
  const rows = readFileSync(path.join(root, "data", "graph-data", "cocoarynth-graph-exported.jsonl"), "utf8")
    .trim().split(/\r?\n/).map((line) => JSON.parse(line));
  const nodes = new Map(), edges = new Map();
  for (const row of rows) {
    nodes.set(row.subject_id, { id: row.subject_id, name: row.subject, type: row.subject_type });
    if (row.object_id) {
      nodes.set(row.object_id, { id: row.object_id, name: row.object, type: row.object_type });
      edges.set(row.fact_id, { id: row.fact_id, source: row.subject_id, target: row.object_id });
    }
  }
  const types = new Map();
  for (const node of nodes.values()) {
    if (!types.has(node.type)) types.set(node.type, []);
    types.get(node.type).push(node);
  }
  const catalog = { types: [...types].map(([name, entities]) => ({ name, entities })), edges: [...edges.values()] };
  const lots = new Set(types.get("BeanLot").map((node) => node.id));
  const related = catalog.edges.filter((edge) => lots.has(edge.source) || lots.has(edge.target));
  const expectedNodes = new Set(related.flatMap((edge) => [edge.source, edge.target]));
  const app = explorer(catalog);
  await app.run('showTypeInGraph("BeanLot")');
  assert.deepEqual(app.ids("nodes"), [...expectedNodes].sort());
  for (const edge of related) assert.ok(app.ids("edges").includes(edge.id));
  assert.match(app.status.textContent, /3 BeanLot entities with no relationships/);
});

test("property-only types remain browsable and tab changes do not modify the graph", async () => {
  const catalog = { types: [{ name: "BeanLot", entities: [{ id: "isolated", type: "BeanLot" }] }], edges: [] };
  const app = explorer(catalog);
  await app.run('showTypeInGraph("BeanLot")');
  assert.deepEqual(app.ids("nodes"), []);
  assert.match(app.status.textContent, /no relationships are listed under Browse by type/);
  app.run('activeTab = "ontology"');
  await app.run('showTypeInGraph("BeanLot")');
  assert.deepEqual(app.ids("nodes"), []);
});
