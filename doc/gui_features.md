# Web client features

The features of the web client of the collaboration server (`archtool serve`), grouped by the part of the client they belong to. Each feature is described in one line, in enough detail to implement it.

Status: **I** = implemented. An empty status means the feature is wanted, but not implemented yet.

Every change the client makes is a command of the editing engine (see "Command interface" in [architecture.md](architecture.md)), sent over the WebSocket, so it is validated like `archtool edit`, and all clients see it.

## Page layout and connection

| Feature | Description | Status |
|---|---|---|
| Three-panel layout | A header, with the model explorer and the diagram list on the left, the selected element or diagram in the middle, and the findings and command console on the right. | I |
| Resizable columns | The lines between the three columns can be dragged to change the widths of the side columns, and the widgets in the columns (forms, tree, diagrams, console) follow their width; a side column is at least 160 pixels wide and the middle column at least 320, also when the window is made narrower; the arrow keys move a focused splitter by 16 pixels, double-clicking it restores the default width (300 pixels left, 340 right), and the chosen widths are kept in the browser's localStorage, per viewer. | I |
| Connection status | The header shows whether the client is connecting, connected or disconnected, with the version of the model it shows. | I |
| Reconnecting | When the WebSocket closes, pending commands fail, the status says "disconnected — reconnecting…", and the client reconnects every 2 seconds. | I |
| Live updates | When the server reports that the model changed (by this client or another one), the client fetches `/api/model` again and redraws the explorer, findings and content; a selection or view whose element was deleted is cleared. | I |
| Shareable links | The URL hash holds the id of the selected element or diagram (e.g. `/#component_2`), or a generated view that is not stored as `#view:<diagram type>:<rule>:<element>`; opening such a link selects it once the model is loaded. | I |

## Model explorer

| Feature | Description | Status |
|---|---|---|
| Hierarchy tree | The entities (Entity, TemplateEntity and InstantiationEntity stereotypes) as a tree following their `parent`, with top-level elements grouped by type in collapsible groups that show the number of elements, in meta-model order. | I |
| Element rows | Each row shows the element's label and its type; clicking it selects the element; the selected element is highlighted. | I |
| Collapsing elements | Every element with parts has a ▸/▾ toggle (with `aria-expanded` and an "Expand/Collapse <label>" label) that hides or shows its parts. | I |
| Hidden count | A collapsed element shows `+N`, the number of descendants it hides. | I |
| Expand all / Collapse all | "Expand all" opens all elements and type groups; "Collapse all" collapses all elements with parts but leaves the type groups open, so the top-level elements stay visible. | I |
| Remembered collapse state | What is collapsed (element ids and `type:<name>` group keys) is kept in the browser's localStorage, per viewer, and survives reloads; without storage the tree still works. | I |
| Reveal on select | Selecting an element, from a link, a finding or a diagram, expands its ancestors and its type group so that it is visible in the tree. | I |
| Search | A search box filters the explorer to a flat list of all elements (not only entities) whose id or label contains the text, case-insensitively; "No matches." when none do. | I |
| Add element | A form with a type (the entity types) and a name adds a top-level element (`add <type> name="…"`; the name only for types with a `name` column) and selects it. | I |

## Element view

| Feature             | Description | Status |
|---------------------|---|---|
| Title               | The element's label, its id, its type and its stereotype, followed by the type's description from the meta model. | I |
| Attribute form      | One field per column of the type: a select for enumerations and booleans, a select of candidate elements (of the column's target types) for single references, a text area for `text`, and a text input otherwise, with lists comma-separated; required columns are marked with `*`. | I |
| Save                | Saving sends one `set <id> …` command with only the attributes that changed, with values quoted or turned into lists as their column requires. | I |
| Unsaved edits       | When the model changes while the form has unsaved edits, the edits are kept and a notice says that the model changed, with a link to discard them. | I |
| Save button         | When the entry is unchanged, the save button is greyed-out. When the user makes any edit, the save button become active. | I |
| Delete element      | A Delete button asks for confirmation, then sends `delete <id>`, which also deletes everything that cannot exist without the element. | I |
| Hierarchy: move     | For entities: "Part of" shows the parent as a link that selects it, or "(top level)", with a Change button; Change opens a popup with a select of the possible parents (elements of types that a HierarchyRelationship type allows as parent of this type) and "(top level)", and Move and Cancel buttons; Move sends `move <id> parent=…` and closes the popup, or shows the error in it. | I |
| Hierarchy: parts    | The element's parts, as links that select them. | I |
| Hierarchy: add part | A form with the types that can be parts of this element and a name, which adds a part (`add <type> name="…" parent=<id>`). | I |
| Ports               | For entities: the element's ports as links with their types, and a form with the port types this element can own and a name, which adds a port (`add <type> owner=<id> name="…"`). | I |
| Relationships       | For entities and ports: the relationships that start or end at the element or one of its ports, as "→ other" (outgoing) or "← other" (incoming), with a link to the relationship itself. | I |
| Connect             | A form with the relationship types that can start at this element or one of its ports, the start (this element or a port), the end (all elements of the type's end types) and a name, which adds a relationship (`connect <type> start=… end=… name="…"`). | I |
| Refers to           | The elements this element refers to through its reference columns, as "column: link". | I |
| Appears in          | The diagrams the element appears in (shown or drawn in it, or, for generated diagrams, passing the diagram's generation rule), as links that open the diagram with the element selected. | I |
| Generated views     | A select of the diagram types whose generation rule has exactly one required parameter, of the element's type, and a Show button that renders that view of the element through `/api/preview.svg`, without storing it in the model. | I |
| Default breakdown   | An element with parts that has a breakdown view shows that view straight away. | I |
| Selecting in a view | In a generated view the element itself is highlighted, and clicking another element selects that element. | I |

## Diagrams

| Feature | Description | Status |
|---|---|---|
| Diagram list | All diagrams with their label and type; clicking one opens it; the open diagram is highlighted. | I |
| New diagram | A collapsible form with a diagram type, a name and an optional generation rule (e.g. `mission`), which adds the diagram (`add <type> name="…" generate="…"`) and opens it. | I |
| Diagram view | The diagram's label, id, type and whether it is generated or drawn (or, for a generated view that is not stored, the element and diagram type), and the SVG rendered by the server (`/api/diagrams/<id>.svg` or `/api/preview.svg`), scaled to the width of the view; rendering errors are shown as a notice. | I |
| Selecting in a diagram | Clicking an element in the diagram highlights it and shows a panel with its label and id and an Open button that selects the element; the element is also revealed in the explorer. | I |
| Show element | For drawn diagrams other than sequence diagrams: a select of the elements of the diagram type's entity and relationship types that are not shown yet, and a Show button (`show <diagram> <element>`). | I |
| Hide element | For drawn diagrams: the selection panel has a "Hide from diagram" button for elements shown in it (`hide <diagram> <element>`). | I |
| Open subsystem | Double-clicking a block whose element has parts (shown with a zoom-in cursor), or selecting it and clicking "Open subsystem" in the selection panel, opens a diagram of the same kind showing its parts: a stored diagram generated with the element as the parameter of a rule with one required parameter (preferring the current diagram type), or else such a generated view, which is not stored; the element whose parts are already shown has no subsystem. | I |
| Up to the parent | A diagram about an element (the value of the one required parameter of its generation rule, e.g. the root of a subsystem) whose element has a parent shows an "↑ Up to <parent>" button in its title, which opens the subsystem of that parent, as "Open subsystem" would. | I |
| Add chain | For drawn sequence diagrams: a select of the chains of the diagram type's chain types, and an Add button (`add_chain <diagram> <chain>`). | I |
| Delete diagram | A Delete diagram button asks for confirmation, then sends `delete <id>`. | I |

## Findings

| Feature | Description | Status |
|---|---|---|
| Findings list | The findings of the model checker, with their number in the heading, each with its severity (error, warning or info, coloured) and message. | I |
| Finding details | Hovering over a finding shows its check, file and line. | I |
| Go to finding | Clicking a finding selects the element it concerns. | I |

## Command console

| Feature | Description | Status |
|---|---|---|
| Command input | A text field to type any command of the editing engine (e.g. `add actor name="Barista"`), sent on Enter. | I |
| Command log | Every command the client sends, typed or made through a form, is logged with its result: created, changed and deleted elements, new issues and resolved findings, or the error, coloured by success. | I |
