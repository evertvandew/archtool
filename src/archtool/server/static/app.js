// The web client of the collaboration server: a hierarchy view with forms to edit the model, interactive
// diagrams, the findings of the model checker, and a console for commands.
//
// Every change is made by sending a command of the editing engine (see doc/architecture.md, "Command interface")
// over a WebSocket. When the model changes, by this client or another one, the server says so, and the client
// fetches the model again.

// Where the browser keeps what is collapsed in the tree. Declared before `state`, which reads it.
const COLLAPSED_KEY = "archtool.collapsed";

const state = {
  model: null,          // The snapshot from /api/model.
  view: null,           // {kind: "element" | "diagram", id}
  selected: null,       // The selected element: in the tree, or in a diagram.
  dirty: false,         // Whether the element form has unsaved edits.
  search: "",
  collapsed: loadCollapsed(),  // The elements, and type groups (`type:<name>`), collapsed in the tree.
};

// --- Talking to the server ---------------------------------------------------------------------------------

let socket = null;
let nextRequest = 1;
const pending = new Map();

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/api/socket`);
  socket.addEventListener("open", () => setStatus("connected", "connected"));
  socket.addEventListener("close", () => {
    setStatus("disconnected — reconnecting…", "disconnected");
    for (const [, reject] of pending.values()) reject(new Error("disconnected"));
    pending.clear();
    setTimeout(connect, 2000);
  });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "result" && pending.has(message.request)) {
      const [resolve] = pending.get(message.request);
      pending.delete(message.request);
      resolve(message);
    } else if (message.type === "changed" || message.type === "hello") {
      if (!state.model || message.version !== state.model.version) refresh();
    }
  });
}

function setStatus(text, kind) {
  const status = document.getElementById("status");
  status.textContent = state.model ? `${text} · version ${state.model.version}` : text;
  status.className = `status ${kind}`;
}

// Send a command, and log its result. Resolves with the result.
function send(command) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    log(command, {ok: false, error: "not connected"});
    return Promise.resolve({ok: false});
  }
  const request = nextRequest++;
  return new Promise((resolve, reject) => {
    pending.set(request, [resolve, reject]);
    socket.send(JSON.stringify({request, command}));
  }).then((result) => {
    log(command, result);
    return result;
  });
}

async function refresh() {
  const response = await fetch("/api/model");
  state.model = await response.json();
  setStatus(socket && socket.readyState === WebSocket.OPEN ? "connected" : "connecting…",
            socket && socket.readyState === WebSocket.OPEN ? "connected" : "");
  if (state.selected && !state.model.elements[state.selected]) state.selected = null;
  if (state.view && state.view.kind === "element" && !state.model.elements[state.view.id]) state.view = null;
  if (state.view && state.view.kind === "diagram" && !state.model.diagrams.some((d) => d.id === state.view.id)) {
    state.view = null;
  }
  renderSidebar();
  renderFindings();
  renderContent({keepForm: state.dirty});
}

// --- Helpers -----------------------------------------------------------------------------------------------

// Create a DOM element. Text is always set with textContent, so that names in the model cannot inject markup.
function el(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else if (key === "className") element.className = value;
    else if (key === "value") element.value = value;
    else element.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

const types = () => state.model.types;
const elements = () => state.model.elements;
const element = (id) => state.model.elements[id];
const label = (id) => (element(id) ? element(id).label : id);

// Whether a type is, or extends, a type or stereotype.
function isA(type, name) {
  const definition = types()[type];
  return !!definition && (definition.ancestors.includes(name) || definition.stereotypes.includes(name));
}

const isAny = (type, names) => (names || []).some((name) => isA(type, name));
const property = (type, key) => (types()[type] && types()[type].properties[key]) || [];
const hasStereotype = (type, stereotype) => types()[type].stereotypes.includes(stereotype);
const isEntity = (type) => ["Entity", "TemplateEntity", "InstantiationEntity"].includes(types()[type].stereotype);
const isDiagramType = (type) => hasStereotype(type, "Diagram");

function elementsOf(names) {
  return Object.entries(elements()).filter(([, e]) => isAny(e.type, names)).map(([id]) => id);
}

function quote(text) {
  return `"${text.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n")}"`;
}

// The text of a value in a command, for a column of a type.
function commandValue(column, text) {
  if (text === "") return "";
  if (column.list) return `[${text.split(",").map((s) => s.trim()).filter((s) => s).join(",")}]`;
  if (column.kind === "str" || column.kind === "text") return quote(text);
  return text;
}

function nameArgument(type, name) {
  const hasName = types()[type].columns.some((c) => c.name === "name");
  return hasName && name.trim() ? ` name=${quote(name.trim())}` : "";
}

function link(id, text) {
  return el("a", {onclick: () => select(id)}, text || label(id));
}

function option(value, text, selected) {
  return el("option", {value, selected: selected ? true : undefined}, text);
}

function select(id) {
  state.selected = id;
  state.dirty = false;
  const e = element(id);
  if (e && isDiagramType(e.type)) state.view = {kind: "diagram", id};
  else state.view = {kind: "element", id};
  // The view is kept in the URL, so that links to elements and diagrams can be shared.
  if (location.hash !== `#${id}`) history.replaceState(null, "", `#${id}`);
  if (e && isEntity(e.type)) reveal(id);
  renderSidebar();
  renderContent({});
}

// --- Sidebar: element tree and diagrams --------------------------------------------------------------------

function renderSidebar() {
  const typeSelect = document.getElementById("new-element-type");
  const previous = typeSelect.value;
  typeSelect.replaceChildren(...Object.keys(types()).filter(isEntity).map((t) => option(t, t, t === previous)));
  const diagramTypeSelect = document.getElementById("new-diagram-type");
  const previousDiagramType = diagramTypeSelect.value;
  diagramTypeSelect.replaceChildren(
    ...Object.keys(types()).filter(isDiagramType).map((t) => option(t, t, t === previousDiagramType)));
  renderTree();
  const list = document.getElementById("diagrams");
  list.replaceChildren(...state.model.diagrams.map((d) => el("li", {},
    el("button", {className: `item${state.selected === d.id ? " selected" : ""}`, onclick: () => select(d.id)},
       d.label, el("span", {className: "type"}, d.type)))));
}

function renderTree() {
  const tree = document.getElementById("tree");
  const query = state.search.trim().toLowerCase();
  if (query) {
    const matches = Object.entries(elements())
      .filter(([id, e]) => id.toLowerCase().includes(query) || e.label.toLowerCase().includes(query))
      .map(([id]) => id);
    tree.replaceChildren(matches.length ? el("ul", {}, matches.map(treeItem)) : el("p", {className: "muted"}, "No matches."));
    return;
  }
  const children = new Map();
  for (const [id, e] of Object.entries(elements())) {
    if (!isEntity(e.type)) continue;
    const parent = e.parent && element(e.parent) ? e.parent : null;
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(id);
  }
  const descendants = (id) => (children.get(id) || []).reduce((count, kid) => count + 1 + descendants(kid), 0);
  const branch = (id) => {
    const kids = children.get(id) || [];
    const collapsed = kids.length > 0 && state.collapsed.has(id);
    const toggle = kids.length
      ? el("button", {className: "toggle", "aria-expanded": String(!collapsed),
                      "aria-label": `${collapsed ? "Expand" : "Collapse"} ${label(id)}`,
                      onclick: () => setCollapsed([id], !collapsed)}, collapsed ? "▸" : "▾")
      : el("span", {className: "toggle"});
    const hidden = collapsed ? el("span", {className: "hidden-count", title: "collapsed parts"}, `+${descendants(id)}`) : null;
    return el("li", {}, el("div", {className: "row"}, toggle, treeItem(id), hidden),
              kids.length && !collapsed ? el("ul", {}, kids.map(branch)) : null);
  };
  const roots = children.get(null) || [];
  const groups = Object.keys(types()).filter(isEntity).map((type) => {
    const ofType = roots.filter((id) => element(id).type === type);
    if (!ofType.length) return null;
    const key = `type:${type}`;
    const group = el("details", {open: !state.collapsed.has(key)},
                     el("summary", {}, `${type} (${ofType.length})`), el("ul", {}, ofType.map(branch)));
    group.addEventListener("toggle", () => {
      if (group.open === state.collapsed.has(key)) setCollapsed([key], !group.open, {render: false});
    });
    return group;
  });
  tree.replaceChildren(...groups.filter(Boolean));
}

// Collapsing parts of the tree. What is collapsed is kept in the browser, for this viewer only.
function loadCollapsed() {
  try {
    const stored = JSON.parse(localStorage.getItem(COLLAPSED_KEY) || "[]");
    return new Set(Array.isArray(stored) ? stored : []);
  } catch {
    return new Set();
  }
}

function setCollapsed(keys, collapsed, {render = true} = {}) {
  for (const key of keys) {
    if (collapsed) state.collapsed.add(key);
    else state.collapsed.delete(key);
  }
  try {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...state.collapsed]));
  } catch {
    // Without storage, the tree still works; it is just not remembered.
  }
  if (render) renderTree();
}

// The elements that have parts in the tree.
function parentKeys() {
  return [...new Set(Object.values(elements()).filter((e) => isEntity(e.type) && e.parent).map((e) => e.parent))];
}

// The groups of top-level elements, by type.
function groupKeys() {
  return Object.keys(types()).filter(isEntity).map((type) => `type:${type}`);
}

// Expand the ancestors of an element, so that it is visible in the tree.
function reveal(id) {
  const keys = [];
  let current = element(id);
  while (current && current.parent && element(current.parent)) {
    keys.push(current.parent);
    current = element(current.parent);
  }
  if (current) keys.push(`type:${current.type}`);
  if (keys.some((key) => state.collapsed.has(key))) setCollapsed(keys, false, {render: false});
}

function treeItem(id) {
  return el("button", {className: `item${state.selected === id ? " selected" : ""}`, onclick: () => select(id)},
            label(id), el("span", {className: "type"}, element(id).type));
}

// --- Findings ----------------------------------------------------------------------------------------------

function renderFindings() {
  const findings = state.model.findings;
  document.getElementById("findings-count").textContent = findings.length ? `(${findings.length})` : "";
  document.getElementById("findings").replaceChildren(...findings.map((f) => el("li", {
      title: [f.check, f.path, f.line ? `line ${f.line}` : null].filter(Boolean).join(" · "),
      onclick: () => f.element && element(f.element) && select(f.element),
    }, el("span", {className: `severity ${f.severity}`}, f.severity), f.message)));
}

// --- Content: an element or a diagram ----------------------------------------------------------------------

function renderContent({keepForm}) {
  const content = document.getElementById("content");
  if (!state.view) {
    content.replaceChildren(el("p", {className: "hint"}, "Select an element or a diagram."));
    return;
  }
  if (state.view.kind === "diagram") {
    renderDiagram(content, state.view.id);
  } else if (keepForm) {
    // Keep the unsaved edits, but tell the user that the model changed.
    if (!content.querySelector(".notice")) {
      content.prepend(el("p", {className: "notice"}, "The model was changed. Save your edits, or ",
        el("a", {onclick: () => { state.dirty = false; renderContent({}); }, href: "#"}, "discard them"), "."));
    }
  } else {
    renderElement(content, state.view.id);
  }
}

function renderElement(content, id) {
  const e = element(id);
  const type = types()[e.type];
  const parts = [
    el("div", {className: "title"}, el("h2", {}, e.label), el("span", {className: "id"}, id),
       el("span", {className: "muted"}, `${e.type} · ${type.stereotype}`)),
  ];
  if (type.description) parts.push(el("p", {className: "muted"}, type.description));
  parts.push(attributeForm(id));
  if (isEntity(e.type)) parts.push(...hierarchySection(id), ...portsSection(id));
  if (isEntity(e.type) || hasStereotype(e.type, "Port")) parts.push(...relationshipsSection(id));
  parts.push(...referencesSection(id), ...diagramsSection(id), ...viewsSection(id));
  content.replaceChildren(...parts);
  showDefaultView(id);
}

function attributeForm(id) {
  const e = element(id);
  const inputs = new Map();
  const rows = [];
  for (const column of types()[e.type].columns) {
    const value = e.values[column.name];
    const text = value === undefined ? "" : Array.isArray(value) ? value.join(", ") : String(value);
    let input;
    if (column.kind === "enum" && !column.list) {
      input = el("select", {}, option("", "—", text === ""), column.values.map((v) => option(v, v, v === text)));
    } else if (column.kind === "bool") {
      input = el("select", {}, option("", "—", text === ""), option("true", "true", text === "true"),
                 option("false", "false", text === "false"));
    } else if (column.kind === "ref" && !column.list) {
      input = el("select", {}, option("", "—", text === ""),
                 elementsOf(column.targets).map((target) => option(target, `${label(target)} (${target})`, target === text)));
    } else if (column.kind === "text") {
      input = el("textarea", {}, text);
    } else {
      input = el("input", {value: text, placeholder: column.list ? "comma-separated" : ""});
    }
    input.id = `field-${column.name}`;
    input.dataset.original = text;
    input.addEventListener("input", () => update());
    inputs.set(column.name, [column, input]);
    rows.push(el("label", {for: input.id, className: column.required ? "required" : ""}, column.name), input);
  }
  const changes = () => [...inputs].filter(([, [, input]]) => input.value !== input.dataset.original)
    .map(([name, [column, input]]) => `${name}=${commandValue(column, input.value)}`);
  const saveButton = el("button", {type: "submit", disabled: true, title: "No changes to save"}, "Save");
  // The Save button is only active while a field differs from the model; undoing an edit greys it out again.
  function update() {
    state.dirty = changes().length > 0;
    saveButton.disabled = !state.dirty;
    saveButton.title = state.dirty ? "" : "No changes to save";
  }
  const save = async (event) => {
    event.preventDefault();
    if (!changes().length) return;
    const result = await send(`set ${id} ${changes().join(" ")}`);
    if (result.ok) state.dirty = false;
  };
  const remove = async () => {
    if (!confirm(`Delete ${label(id)} (${id}), and everything that cannot exist without it?`)) return;
    const result = await send(`delete ${id}`);
    if (result.ok) { state.view = null; state.selected = null; state.dirty = false; }
  };
  return el("form", {onsubmit: save}, el("div", {className: "fields"}, rows),
    el("div", {className: "actions"}, saveButton,
       el("button", {type: "button", className: "danger", onclick: remove}, "Delete")));
}

// The hierarchy types in which an element of `childType` can be part of an element of `parentType`.
function hierarchies(parentType, childType) {
  return Object.keys(types()).filter((h) => types()[h].stereotype === "HierarchyRelationship"
    && isA(parentType, property(h, "parent")[0]) && isA(childType, property(h, "child")[0]));
}

function hierarchySection(id) {
  const e = element(id);
  const parentCandidates = Object.keys(elements()).filter((p) => p !== id && isEntity(element(p).type)
    && hierarchies(element(p).type, e.type).length);
  const childTypes = Object.keys(types()).filter((t) => isEntity(t) && hierarchies(e.type, t).length);
  const children = Object.keys(elements()).filter((c) => element(c).parent === id);
  const parentSelect = el("select", {"aria-label": "Parent"}, option("", "(top level)", !e.parent),
    parentCandidates.map((p) => option(p, `${label(p)} (${p})`, p === e.parent)));
  const parts = [el("h3", {}, "Hierarchy")];
  if (parentCandidates.length || e.parent) {
    parts.push(el("form", {className: "actions", onsubmit: (event) => {
        event.preventDefault();
        send(`move ${id} parent=${parentSelect.value}`);
      }}, "Part of", parentSelect, el("button", {type: "submit"}, "Move")));
  }
  if (children.length) parts.push(el("ul", {className: "links"}, children.map((c) => el("li", {}, link(c)))));
  if (childTypes.length) {
    const typeSelect = el("select", {"aria-label": "Type of the new part"}, childTypes.map((t) => option(t, t)));
    const name = el("input", {placeholder: "Name", "aria-label": "Name of the new part"});
    parts.push(el("form", {className: "actions", onsubmit: (event) => {
        event.preventDefault();
        send(`add ${typeSelect.value}${nameArgument(typeSelect.value, name.value)} parent=${id}`);
      }}, "Add part", typeSelect, name, el("button", {type: "submit"}, "Add")));
  }
  return parts.length > 1 ? parts : [];
}

function portsSection(id) {
  const e = element(id);
  const portTypes = Object.keys(types()).filter((t) => types()[t].stereotype === "Port" && isAny(e.type, property(t, "owner")));
  const ports = Object.keys(elements()).filter((p) => element(p).values.owner === id);
  if (!portTypes.length && !ports.length) return [];
  const parts = [el("h3", {}, "Ports")];
  if (ports.length) parts.push(el("ul", {className: "links"}, ports.map((p) => el("li", {}, link(p), " ",
    el("span", {className: "muted"}, element(p).type)))));
  if (portTypes.length) {
    const typeSelect = el("select", {"aria-label": "Type of the new port"}, portTypes.map((t) => option(t, t)));
    const name = el("input", {placeholder: "Name", "aria-label": "Name of the new port"});
    parts.push(el("form", {className: "actions", onsubmit: (event) => {
        event.preventDefault();
        send(`add ${typeSelect.value} owner=${id}${nameArgument(typeSelect.value, name.value)}`);
      }}, "Add port", typeSelect, name, el("button", {type: "submit"}, "Add")));
  }
  return parts;
}

function relationshipsSection(id) {
  const own = [id, ...Object.keys(elements()).filter((p) => element(p).values.owner === id)];
  const relationships = Object.entries(elements()).filter(([, r]) => hasStereotype(r.type, "Relationship")
    && (own.includes(r.values.start) || own.includes(r.values.end)));
  const parts = [el("h3", {}, "Relationships")];
  const owner = (end) => (element(end) && element(end).values.owner) || end;
  if (relationships.length) {
    parts.push(el("ul", {className: "links"}, relationships.map(([rid, r]) => {
      const outgoing = own.includes(r.values.start);
      const other = owner(outgoing ? r.values.end : r.values.start);
      return el("li", {}, outgoing ? "→ " : "← ", link(other), " ", el("span", {className: "muted"}, "by "),
                link(rid, r.label === rid ? r.type : `${r.label} (${r.type})`));
    })));
  }
  // Connecting: the relationship types that can start at this element or one of its ports.
  const options = Object.keys(types()).filter((t) => hasStereotype(t, "Relationship")).map((t) => ({
    type: t,
    starts: own.filter((o) => isAny(element(o).type, property(t, "start"))),
    ends: elementsOf(property(t, "end")),
  })).filter((o) => o.starts.length && o.ends.length);
  if (options.length) {
    const typeSelect = el("select", {"aria-label": "Relationship type"}, options.map((o) => option(o.type, o.type)));
    const startSelect = el("select", {"aria-label": "From"});
    const endSelect = el("select", {"aria-label": "To"});
    const update = () => {
      const chosen = options.find((o) => o.type === typeSelect.value);
      startSelect.replaceChildren(...chosen.starts.map((s) => option(s, s === id ? "this element" : `port ${label(s)}`)));
      endSelect.replaceChildren(...chosen.ends.map((target) => option(target, `${label(target)} (${target})`)));
    };
    typeSelect.addEventListener("change", update);
    update();
    const name = el("input", {placeholder: "Name", "aria-label": "Name of the relationship"});
    parts.push(el("form", {className: "actions", onsubmit: (event) => {
        event.preventDefault();
        send(`connect ${typeSelect.value} start=${startSelect.value} end=${endSelect.value}${nameArgument(typeSelect.value, name.value)}`);
      }}, "Connect", typeSelect, startSelect, "to", endSelect, name, el("button", {type: "submit"}, "Connect")));
  }
  return parts.length > 1 ? parts : [];
}

function referencesSection(id) {
  // The elements this element refers to (e.g. the ends of a relationship), and those that refer to it.
  const e = element(id);
  const out = [];
  for (const column of types()[e.type].columns) {
    if (column.kind !== "ref") continue;
    const value = e.values[column.name];
    for (const target of Array.isArray(value) ? value : value ? [value] : []) {
      if (element(target)) out.push(el("li", {}, `${column.name}: `, link(target)));
    }
  }
  return out.length ? [el("h3", {}, "Refers to"), el("ul", {className: "links"}, out)] : [];
}

function diagramsSection(id) {
  // The diagrams in which the element appears. Opening one selects the element in it.
  const diagrams = state.model.diagrams.filter((d) => d.elements.includes(id));
  if (!diagrams.length) return [];
  return [el("h3", {}, "Appears in"), el("ul", {className: "links"}, diagrams.map((d) => el("li", {},
    el("a", {onclick: () => openDiagram(d.id, id)}, d.label), " ", el("span", {className: "muted"}, d.type))))];
}

// The generated diagrams that can be made for an element without storing them: those of diagram types whose
// generation rule has exactly one required parameter, of the element's type. E.g. the breakdown of a requirement.
function viewOptions(id) {
  const type = element(id).type;
  const options = [];
  for (const diagramType of Object.keys(types()).filter(isDiagramType)) {
    for (const rule of property(diagramType, "rules")) {
      const parameters = (state.model.rules[rule] || {parameters: []}).parameters;
      const required = parameters.filter((p) => p.default === null);
      if (required.length === 1 && isA(type, required[0].type)) {
        options.push({diagramType, rule, parameter: required[0].name, kind: types()[diagramType].stereotype});
      }
    }
  }
  return options;
}

function viewsSection(id) {
  const options = viewOptions(id);
  if (!options.length) return [];
  const viewSelect = el("select", {id: "view-select", "aria-label": "Generated view"},
    options.map((o, index) => option(String(index), o.diagramType === o.rule ? o.diagramType : `${o.diagramType} (${o.rule})`)));
  return [
    el("h3", {}, "Generated views"),
    el("form", {className: "actions", onsubmit: (event) => {
        event.preventDefault();
        showView(id, options[Number(viewSelect.value)]);
      }}, viewSelect, el("button", {type: "submit"}, "Show")),
    el("div", {id: "view", className: "diagram-view", hidden: true}),
  ];
}

// Elements that are broken down show their breakdown straight away.
function showDefaultView(id) {
  const hasParts = Object.values(elements()).some((e) => e.parent === id);
  const options = viewOptions(id);
  const breakdown = options.findIndex((o) => o.kind === "BreakDownDiagram");
  if (hasParts && breakdown >= 0) {
    document.getElementById("view-select").value = String(breakdown);
    showView(id, options[breakdown]);
  }
}

async function showView(id, view) {
  const container = document.getElementById("view");
  if (!container) return;
  container.hidden = false;
  container.replaceChildren(el("p", {className: "muted"}, "Rendering…"));
  const query = new URLSearchParams({type: view.diagramType, rule: view.rule, [view.parameter]: id,
                                     version: String(state.model.version)});
  const response = await fetch(`/api/preview.svg?${query}`);
  if (!state.view || state.view.id !== id || !document.getElementById("view")) return;  // Another view was chosen.
  if (!response.ok) {
    const body = await response.json().catch(() => ({error: response.statusText}));
    container.replaceChildren(el("p", {className: "notice"}, `The view cannot be rendered: ${body.error}`));
    return;
  }
  // The SVG comes from the server's renderer, which escapes all text in it.
  container.innerHTML = await response.text();
  for (const group of container.querySelectorAll("[data-id]")) {
    group.classList.toggle("selected", group.dataset.id === id);
    group.addEventListener("click", (event) => {
      event.stopPropagation();
      if (element(group.dataset.id)) select(group.dataset.id);
    });
  }
}

// Open a diagram, with an element selected in it.
function openDiagram(diagramId, elementId) {
  select(diagramId);
  state.selected = elementId;
  renderTree();
}

// --- Diagrams ----------------------------------------------------------------------------------------------

async function renderDiagram(content, id) {
  const diagram = state.model.diagrams.find((d) => d.id === id);
  const kind = diagram.kind;
  const container = el("div", {className: "diagram-view"}, el("p", {className: "muted"}, "Rendering…"));
  const parts = [
    el("div", {className: "title"}, el("h2", {}, diagram.label), el("span", {className: "id"}, id),
       el("span", {className: "muted"}, `${diagram.type} · ${diagram.generated ? "generated" : "drawn"}`)),
    container,
    el("div", {id: "diagram-selection", className: "actions"}),
  ];
  if (!diagram.generated && kind === "SequenceDiagram") {
    const chains = elementsOf(property(diagram.type, "chains"));
    if (chains.length) {
      const chainSelect = el("select", {"aria-label": "Chain"}, chains.map((c) => option(c, `${label(c)} (${c})`)));
      parts.push(el("form", {className: "actions", onsubmit: (event) => {
          event.preventDefault();
          send(`add_chain ${id} ${chainSelect.value}`);
        }}, "Add chain", chainSelect, el("button", {type: "submit"}, "Add")));
    }
  } else if (!diagram.generated) {
    const allowed = [...property(diagram.type, "entities"), ...property(diagram.type, "relationships")];
    const candidates = elementsOf(allowed).filter((c) => !diagram.shown.includes(c));
    if (candidates.length) {
      const elementSelect = el("select", {"aria-label": "Element to show"},
        candidates.map((c) => option(c, `${label(c)} (${element(c).type})`)));
      parts.push(el("form", {className: "actions", onsubmit: (event) => {
          event.preventDefault();
          send(`show ${id} ${elementSelect.value}`);
        }}, "Show", elementSelect, el("button", {type: "submit"}, "Show")));
    }
  }
  parts.push(el("div", {className: "actions"},
    el("button", {className: "danger", onclick: async () => {
      if (!confirm(`Delete the diagram ${diagram.label} (${id})?`)) return;
      const result = await send(`delete ${id}`);
      if (result.ok) { state.view = null; state.selected = null; }
    }}, "Delete diagram")));
  content.replaceChildren(...parts);

  const version = state.model.version;
  const response = await fetch(`/api/diagrams/${encodeURIComponent(id)}.svg?version=${version}`);
  if (!state.view || state.view.id !== id) return;  // Another view was chosen meanwhile.
  if (!response.ok) {
    const body = await response.json().catch(() => ({error: response.statusText}));
    container.replaceChildren(el("p", {className: "notice"}, `The diagram cannot be rendered: ${body.error}`));
    return;
  }
  // The SVG comes from the server's renderer, which escapes all text in it.
  container.innerHTML = await response.text();
  for (const group of container.querySelectorAll("[data-id]")) {
    group.addEventListener("click", (event) => {
      event.stopPropagation();
      selectInDiagram(diagram, group.dataset.id);
    });
  }
  if (state.selected && state.selected !== id) selectInDiagram(diagram, state.selected);
}

function selectInDiagram(diagram, id) {
  state.selected = id;
  for (const group of document.querySelectorAll(".diagram-view [data-id]")) {
    group.classList.toggle("selected", group.dataset.id === id);
  }
  const panel = document.getElementById("diagram-selection");
  if (!panel || !element(id)) return;
  const actions = [el("span", {}, "Selected: ", el("strong", {}, label(id)), " ", el("span", {className: "id"}, id)),
                   el("button", {onclick: () => select(id)}, "Open")];
  if (!diagram.generated && diagram.shown.includes(id)) {
    actions.push(el("button", {onclick: () => send(`hide ${diagram.id} ${id}`)}, "Hide from diagram"));
  }
  panel.replaceChildren(...actions);
  if (isEntity(element(id).type)) reveal(id);
  renderTree();
}

// --- Console -----------------------------------------------------------------------------------------------

function log(command, result) {
  const lines = [`> ${command}`];
  if (result.ok) {
    for (const key of ["created", "changed", "deleted"]) {
      if (result[key] && result[key].length) lines.push(`${key}: ${result[key].join(", ")}`);
    }
    for (const issue of result.issues || []) lines.push(`${issue.severity}: ${issue.message}`);
    for (const finding of result.resolved || []) lines.push(`resolved: ${finding.message}`);
  } else {
    lines.push(`error: ${result.error}`);
  }
  const entry = el("div", {className: result.ok ? "ok" : "failed"}, lines.join("\n"));
  const logElement = document.getElementById("log");
  logElement.append(entry);
  logElement.scrollTop = logElement.scrollHeight;
}

// --- Start -------------------------------------------------------------------------------------------------

// Expanding all opens everything; collapsing all leaves the groups open, showing the top-level elements.
document.getElementById("expand-all").addEventListener("click", () => setCollapsed([...parentKeys(), ...groupKeys()], false));
document.getElementById("collapse-all").addEventListener("click", () => setCollapsed(parentKeys(), true));

document.getElementById("search").addEventListener("input", (event) => {
  state.search = event.target.value;
  renderTree();
});

document.getElementById("console").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("command");
  if (input.value.trim()) send(input.value.trim());
  input.value = "";
});

document.getElementById("new-element").addEventListener("submit", async (event) => {
  event.preventDefault();
  const type = document.getElementById("new-element-type").value;
  const name = document.getElementById("new-element-name");
  const result = await send(`add ${type}${nameArgument(type, name.value)}`);
  if (result.ok) {
    name.value = "";
    const created = result.created.find((id) => id.startsWith(`${type}_`));
    if (created) { await refresh(); select(created); }
  }
});

document.getElementById("new-diagram").addEventListener("submit", async (event) => {
  event.preventDefault();
  const type = document.getElementById("new-diagram-type").value;
  const name = document.getElementById("new-diagram-name");
  const generate = document.getElementById("new-diagram-generate");
  const rule = generate.value.trim() ? ` generate=${quote(generate.value.trim())}` : "";
  const result = await send(`add ${type}${nameArgument(type, name.value)}${rule}`);
  if (result.ok) {
    name.value = "";
    generate.value = "";
    await refresh();
    select(result.created[0]);
  }
});

refresh().then(() => {
  const id = decodeURIComponent(location.hash.slice(1));
  if (id && element(id)) select(id);
  connect();
});
