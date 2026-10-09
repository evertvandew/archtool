# Architecting Tool — Architecture

## Purpose of this document

This document describes the architecture that realises the vision in [vision.md](vision.md).
Where the vision states *what* the tool should do, this document describes *how* it is built: its components, the files it works on, the interfaces between components, and the decisions that were deferred by the vision.

## Terminology

The vision distinguishes three levels of abstraction. This document uses them strictly:

| Level | Defined by | Contains | Example | Identified by |
|---|---|---|---|---|
| Core model | The tools (hard-coded) | Kinds of meta-model elements | `Entity`, `Port`, `Relationship`, `SequenceDiagram` | Class name |
| Meta model | The user (configurable) | Types, rules and diagram definitions for a method | Entity type `function`, relationship type `functional_exchange` | Name |
| Concrete model | The user (modelling) | Instances of meta-model types | `function_42` "Compute position" | Identifier |

In this document, a *type* always means a meta-model element, and an *element* always means an element of the concrete model.

## Architectural principles

1. **Files are the source of truth.** All tools read and write the files in the model repository. There is no hidden database. Anything a tool knows about the model, it can derive from the files.
2. **One shared model library.** Parsing, writing, validating and navigating the three levels is implemented once, in a library that all tools use. Tools are thin.
3. **Generic over the meta model.** No tool contains knowledge of a specific method such as Arcadia. Tools only know the core model; everything else comes from the meta model.
4. **CLI first.** Every operation is available as a CLI command. Web interfaces are clients of a CLI tool running as a service; they never edit files themselves.
5. **Deterministic output.** Writing the same model always produces byte-identical files, so that git diffs only show real changes.

## Technology

* **CLI tools, model library and collaboration server:** Python for the MVP. When the design crystallises and stable binary distributions are wanted, they are ported to Rust.
* **Web clients:** free choice; TypeScript is a likely candidate, but C#, Brython, Rust or plain JavaScript are equally acceptable. The web clients talk to the server through a language-neutral protocol (JSON over WebSocket), so their technology does not affect the rest of the system.

All tools are subcommands of a single executable, `archtool`, e.g. `archtool check`, `archtool edit`, `archtool render` and `archtool serve`.
There is one thing to install, while each subcommand still performs a single task.

To keep the later port to Rust straightforward:

* The Python code uses static type annotations throughout, checked with a type checker in strict mode, and avoids dynamic features that have no Rust equivalent (monkey-patching, runtime attribute injection, heavy metaprogramming).
* The behaviour of the tools is pinned down by a language-independent conformance test suite: model repositories as input, expected files, diagrams and command results as output. The Rust port must pass the same suite.
* Each component has a narrow, explicit interface, so components can be ported one at a time.

## Component overview

@startuml components

package "Model library" {
  [File formats] as formats
  [Model store] as store
  [Meta-model loader] as mmloader
  [Selection language] as selection
}

[Meta-model checker] as mmcheck
[Model checker] as check
[Editing engine] as engine
[Diagram generator] as diagen
[Duplicate merger] as merger
[Collaboration server] as server
[Web clients] as web

store --> formats
mmloader --> formats
store --> mmloader
selection --> store

mmcheck --> mmloader
check --> store
check --> selection
engine --> store
engine --> check
diagen --> store
diagen --> selection
merger --> engine
server --> engine
server --> diagen
web --> server : WebSocket

@enduml

### Model library

The model library is the heart of the system.

* **File formats.** Reads and writes the CSV-like tables and the PlantUML-like diagram files, including escaping, type annotations and deterministic ordering.
* **Meta-model loader.** Loads a meta model into memory as instances of the core-model classes, and resolves inheritance between types.
* **Model store.** Holds a concrete model in memory, indexed by identifier, with reverse indexes for references (which elements refer to `function_42`?). It loads and saves the files of a model repository.
* **Selection language.** Evaluates declarative selections over the model store. See [Selection language](#selection-language).

### Tools

| Vision task | Component | Interface |
|---|---|---|
| Checking the validity of the model | Model checker | CLI |
| Checking traceability and coverage | Model checker (verification rules) | CLI |
| Generating diagrams | Diagram generator | CLI |
| Analysing and propagating changes | Editing engine | CLI, service |
| Checking the meta model | Meta-model checker | CLI |
| Adding elements to the model | Editing engine | CLI, service |
| Merging accidental duplicates | Duplicate merger | CLI |
| Viewing and editing the hierarchy | Web client (hierarchy view) on the editing engine | Web |
| Drawing diagrams | Web client (diagram editor) on the editing engine | Web |
| Generating identifiers centrally | Collaboration server | Web API |

**Model checker.** Checks the concrete model against the meta model (allowed types, containment, ports, connections, references that resolve, duplicate identifiers) and evaluates the verification rules, such as coverage rules. It reports findings in a machine-readable and a human-readable form, and returns a non-zero exit code on errors, so it can be used in CI.

**Editing engine.** Executes edit commands (see [Command interface](#command-interface)). After every command it propagates changes where it can, runs the model checker on the affected elements, and reports inconsistencies. It runs either as a one-shot CLI tool or as a long-running service.

**Diagram generator.** Evaluates a diagram's generation rule, or reads a drawn diagram, computes the layout, and renders the result to SVG (and optionally PNG). Used from CI to export diagrams, and by the collaboration server to show diagrams in the browser.

**Duplicate merger.** Merges two elements into one: the surviving element keeps its identifier, all references to the other element are rewritten, and the other element is deleted. It is built on the editing engine.

**Collaboration server.** See [Collaboration server](#collaboration-server).

## Model repository layout

A model lives in a directory, normally a git repository:

```
my-model/
├── archtool.toml              # Settings, including the path to the meta model
├── metamodel.csv              # The meta model, in a single file
├── model/                     # The concrete model: one file per meta-model type
│   ├── function.csv
│   ├── component.csv
│   ├── functional_exchange.csv
│   ├── function_contains_function.csv
│   └── ...
└── diagrams/                  # One file per diagram, plus an index table per diagram type
    ├── functional_sequence.csv
    ├── functional_sequence_12.diag
    └── ...
```

The meta model is kept in a single file (see [Meta-model file](#meta-model-file)).
`archtool.toml` refers to it by path, so a model can also use a meta model kept elsewhere, such as one of the shipped examples.
Abstraction levels are only used by the user interface, and have no files in `model/`.

## File formats

This section gives an overview; the complete specification is in [file_formats.md](file_formats.md).

### CSV-like tables

An example table, `model/functional_exchange.csv`:

```
@last_number 2
id:id;start:ref(function_port);end:ref(function_port);name:str;description:text
functional_exchange_1;function_port_3;function_port_8;Position;Current position estimate.\nUpdated at 10 Hz.
functional_exchange_2;function_port_9;function_port_4;Alarm;
```

* The first line records the highest identifier number ever used for this type (see [Identifiers](#identifiers)).
* The second line is the header. Each column is `name:type`.
* Column types: `id`, `str` (single line), `text` (multi-line), `int`, `float`, `bool`, `enum(a|b|c)`, `ref(type|type…)` and `list(…)` of any of these.
* Separator: `;`. Escapes: `\n`, `\t`, `\\`, `\s` for the separator, and `\[` and `\]` for square brackets.
* Lists are written in square brackets, with elements separated by commas: `[function_3,function_7]`. Because square brackets inside strings are always escaped, lists can be parsed simply. A comma inside a list element is escaped as `\,`.
* Rows are sorted by identifier, in natural order (`function_9` before `function_10`).
* Columns appear in a fixed order: first the core attributes, then the attributes defined by the meta-model type, in the order the meta model defines them.

### Diagram files

A drawn sequence diagram, `diagrams/functional_sequence_12.diag`:

```
@diagram functional_sequence_12 : functional_sequence
participant function_3
participant function_7
participant function_9
message functional_exchange_1
message functional_exchange_2
@end
```

A generated diagram only stores the call of its generation rule, and optional layout hints:

```
@diagram physical_architecture_4 : physical_architecture
generate component_internals(root=component_1, depth=2)
layout component_5 at 120,40 size 200x120
@end
```

* Diagrams refer to elements by identifier only. Names are looked up when rendering.
* Each diagram type has an index table in `diagrams/`, e.g. `diagrams/functional_sequence.csv`, listing the identifier and attributes (such as the name) of each diagram of that type. It records the highest identifier number used for the diagram type, like any other table, and lets tools list diagrams without opening every diagram file.
* In a drawn diagram, the order of lines is significant. For example, it is the order of messages in a sequence diagram. Inserting a message is inserting a line.
* Layout hints are optional. Without them, the layout is computed automatically.

The complete syntax is specified in [file_formats.md](file_formats.md#diagram-files).

### Meta-model file

The meta model is a single file, containing several tables in the CSV-like format.
Each table starts with a line `@table <kind>`, followed by its own header line.
Rules, which are not tabular, are written in the selection language in `@rules` sections; the stylesheet and SVG definitions for diagrams in `@style` and `@defs` sections.

```
@table entity_types
name:ident;extends:ref(entity_types);description:text
component;;A part of the system.
function;;A function performed by the system.
system_function;function;A function at system level.

@table attributes
type:ref(any_type);name:ident;datatype:datatype;required:bool;default:str;description:text
Entity;name;str;false;;The name of the element.
requirement;priority;enum(high|medium|low);true;;

@table hierarchy_types
name:ident;parent:ref(entity_types);child:ref(entity_types);description:text
function_contains_function;function;function;

@rules
diagram component_internals(root: component, depth: int = 1):
    ...
@end
```

The complete list of tables is specified in [file_formats.md](file_formats.md#meta-model-file).

## Identifiers

Numbers are counted per type.
Numbers are never reused, not even the number of a deleted element, so the highest number ever used must be stored permanently.

There is no separate counter file, as it would become stale in some use cases.
Instead, each type's table (for diagrams: the diagram type's index table) records the highest number ever used for that type, in its first line (`@last_number 2`).

* When a tool that can add elements starts, it determines, per type, the larger of the recorded number and the highest number actually present in the table. That way, rows added by hand without updating the recorded number cannot cause reuse.
* New elements get numbers above it, and the recorded number is updated whenever the table is written.
* Deleting an element leaves the recorded number unchanged, so its number is never handed out again.
* The collaboration server determines the numbers when it starts, and then allocates identifiers in memory, through its web API.
* When two branches both add elements of the same type, both change the `@last_number` line, and git reports a merge conflict. The conflict is resolved by keeping the higher number, and warns the user of a possible identifier collision. The model checker detects any actual collision.

## Selection language

The vision requires declarative rules in three places: diagram generation rules, verification rules, and (in future) the query tool.
One small selection language serves all three, implemented once in the model library.

The language is designed in [selection_language.md](selection_language.md). An example of each kind of rule:

```
diagram component_internals(root: component, depth: int = 1):
    let blocks = root.descendants(depth)
    show root
    show blocks
    show component_exchange between blocks

check requirement_covered (error):
    for each r in requirement:
        require r.sources(covers) is not empty
        otherwise "Requirement {r} is not covered by any test."

query unallocated_functions:
    select logical_function where targets(allocated_to) is empty
```

The key decision is that it is declarative, side-effect free, and shared.

This language is likely to be the most difficult part of learning to use the tools.
Using one language for all three purposes keeps the learning curve as short as possible, and its design should put learnability first.

## Command interface

CLI tools read commands, one per line, from a file or stdin, and write results to stdout as JSON lines.
An option for human-readable output will be added later.

```
add function name="Compute position" parent=function_3
set function_42 name="Estimate position"
connect functional_exchange start=function_42 end=function_7 name="Position"
delete function_9
```

A result:

```
{"ok": true, "created": ["function_42", "function_contains_function_17"], "changed": [], "issues": []}
```

Edits made through commands are written to the files immediately, so that the files always reflect the current state and can be committed at any time.

## Collaboration server

One server per model. It:

* runs the editing engine as a service, holding the model in memory;
* accepts commands from web clients over WebSocket, executes them one at a time, and writes the affected files;
* broadcasts every change to all connected clients, so all users see each other's edits in real time;
* serves the web clients (hierarchy view, diagram editor) and rendered diagrams;
* provides the identifier-generation web API.

Commands are executed in order of arrival; when two users edit the same element at the same moment, the last write wins.
There are no user accounts or access control.

## Layout and rendering

* **Block diagrams** (and state and class-like diagrams, which are rendered as block diagrams) need hierarchical layout with ports. This is the hardest layout problem in the tool.
* **Breakdown diagrams** are trees, laid out with a tree layout.
* **Sequence diagrams** and **use-case diagrams** have simple, mostly fixed layouts and are laid out by the tool itself.
* Output is SVG; PNG is produced from the SVG for contexts that need it.

Layout is computed by the diagram generator, not by the web clients, so that a diagram exported in CI looks the same as in the browser.

The texts shown for each element, and where they are placed, are defined by labels in the meta model. The shapes of blocks and the endings of lines are also defined in the meta model, from a large set of built-in shapes and line endings, or as SVG symbols and markers of its own. Diagrams are styled with CSS: each SVG element carries its type, the types it extends and its stereotype as CSS classes, and the meta model supplies the stylesheet and SVG definitions such as gradients (see [file_formats.md](file_formats.md#styles)).

### Layout engine

Block and breakdown diagrams are laid out with the Eclipse Layout Kernel (ELK), which is well suited to nested blocks with ports on their borders.
ELK is used through [elk-cli](https://github.com/kieler/elk-cli) (`@kieler/elk-cli` on npm), a command-line wrapper around elkjs:

1. The diagram generator converts the diagram into an ELK JSON graph: blocks become nodes (nested for hierarchy), ports become ELK ports, and relationships become edges. Layout hints and layout options are passed along.
2. It runs `elk`, passing the graph on stdin, and reads the laid-out graph, with coordinates, from stdout.
3. It renders the SVG itself from the laid-out graph, applying the styling from the diagram file. The basic SVG output of elk-cli is not used.

Consequences:

* Node.js is a runtime dependency of the diagram generator. The model library and the other tools do not need it.
* Starting `elk` costs some time per call. This is acceptable for CI and for the MVP collaboration server. If it becomes a bottleneck, the server can keep a long-running elkjs process instead.
* How manual layout hints are fed to ELK (e.g. fixed positions, or ELK's interactive layout options) is to be worked out in the detailed design.
* For the Rust port, Rust reimplementations of ELK exist (e.g. [elkrs](https://crates.io/crates/elkrs)). If one proves mature enough, the Node.js dependency can be dropped.

## Core-model stereotypes

Every type in a meta model is an instance of a core-model element, which acts as its **stereotype**.
The stereotype determines two things:

* **In the meta model:** which properties the user sets to define a type, e.g. which entity types a relationship type may start and end at.
* **In the concrete model:** which attributes and references every element of such a type has, in addition to the attributes the meta model defines for the type. These are the *core attributes*: the tools rely on them to implement their features.

### Stereotypes

The diagram defines each stereotype. The *meta model* compartment lists the properties set in the meta model; the *concrete model* compartment lists the core attributes of the elements.

@startuml stereotypes
hide empty members
skinparam classAttributeIconSize 0

package "Core model: stereotypes" as core {

  class Entity <<stereotype>> {
    .. meta model ..
    name: str
    extends: Entity type [0..1]
    {field} attributes: list(attribute definition)
    .. concrete model ..
    id: id
  }

  class Port <<stereotype>> {
    .. meta model ..
    {field} owner: list(Entity type)
    .. concrete model ..
    {field} owner: ref(Entity)
  }

  class Relationship <<stereotype>> {
    .. meta model ..
    {field} start: list(Entity or Port type)
    {field} end: list(Entity or Port type)
    .. concrete model ..
    {field} start: ref(Entity or Port)
    {field} end: ref(Entity or Port)
  }

  class Refinement <<stereotype>>

  class HierarchyRelationship <<stereotype>> {
    .. meta model ..
    parent: Entity type
    child: Entity type
    .. concrete model ..
    {field} parent: ref(Entity)
    {field} child: ref(Entity)
  }

  class Relationship_breakdown <<stereotype>> {
    .. meta model ..
    aggregate: Relationship type
    constituent: Relationship type
    .. concrete model ..
    {field} aggregate: ref(Relationship)
    {field} constituent: ref(Relationship)
  }

  class TemplateEntity <<stereotype>> {
    .. meta model ..
    instantiation: InstantiationEntity type
    .. concrete model ..
    {field} parameters: list(attribute definition)
  }

  class InstantiationEntity <<stereotype>> {
    .. meta model ..
    template: TemplateEntity type
    .. concrete model ..
    {field} template: ref(TemplateEntity)
    {field} arguments: list(attribute value)
  }

  class Diagram <<stereotype>> {
    .. meta model ..
    {field} entities: list(Entity type)
    {field} relationships: list(Relationship type)
    {field} rules: list(diagram rule) [0..*]
    {field} labels: list(label definition)
    {field} shapes: list(shape definition)
    .. concrete model ..
    rule: diagram rule [0..1]
    arguments: list [0..1]
    {field} elements: list(ref(Entity)) [0..1]
    layout hints
  }

  class BlockDiagram <<stereotype>> {
    .. meta model ..
    {field} chains: list(Chain type)
    .. concrete model ..
    {field} highlights: list(ref(Chain))
  }
  class BreakDownDiagram <<stereotype>>
  class UseCaseDiagram <<stereotype>>

  class SequenceDiagram <<stereotype>> {
    .. meta model ..
    chain: Chain type [0..1]
    .. concrete model ..
    {field} messages: ordered list(ref(Relationship))
  }

  class Chain <<stereotype>> {
    .. meta model ..
    relationship: Relationship type
    .. concrete model ..
    {field} relationships: ordered list(ref(Relationship))
  }

  class Abstraction_level <<stereotype>> {
    .. meta model ..
    name: str
    {field} diagrams: list(Diagram type)
  }

  Port -up-|> Entity
  Relationship -up-|> Entity
  Refinement -up-|> Relationship
  Chain -up-|> Entity
  HierarchyRelationship -up-|> Entity
  Relationship_breakdown -up-|> Entity
  TemplateEntity -up-|> Entity
  InstantiationEntity -up-|> Entity
  Diagram -up-|> Entity
  BlockDiagram -up-|> Diagram
  BreakDownDiagram -up-|> Diagram
  UseCaseDiagram -up-|> Diagram
  SequenceDiagram -up-|> Diagram
}
@enduml


* Every stereotype specialises `Entity`, so every element has an `id`.
* There is no core `name` attribute: names, like all other descriptive attributes, are defined in the meta model. A meta model can define an attribute for a stereotype, e.g. a `name` for `Entity`, which then applies to all types with that stereotype. How elements are shown, in diagrams and elsewhere, is defined by the `labels` of the diagram types in the meta model (see [file_formats.md](file_formats.md#labels)).
* `Abstraction_level` exists only in the meta model; it has no elements in the concrete model.
* A `Chain` type in the meta model defines the type of relationship its chains pass along. A chain in the concrete model holds the relationships it consists of, in order, so that e.g. a block diagram can highlight it.
* A `Refinement` connects an element to the element it refines. Refinements connect the different levels of a model with distinct hierarchy levels. Declaring them as a separate stereotype lets the selection language's `.refines` and `.refined_by` know which relationships to follow.
* The concrete attributes of a `Diagram` are stored in the diagram file rather than in a table: either a generation `rule` with its `arguments`, or the `elements` of a drawn diagram, plus optional layout hints. For a sequence diagram, the order of the `messages` is the order of lines in the file.
* A sequence diagram stores its own messages, independently of chains. In the meta model, a sequence diagram type shows at most one chain type. In the concrete model, a sequence diagram can show several chains of that type, e.g. two functional chains following each other, and additional messages that are not part of any chain.
* To map a chain to a sequence, as Capella allows, the editing engine provides a command that adds the relationships of a chain to a sequence diagram as messages, in the chain's order, e.g. `add_chain functional_sequence_12 functional_chain_3`. The chain must be of the chain type of the diagram's type; if that type has no chain type, the command is not available. After that, the messages are ordinary messages of the diagram, which the user can reorder or extend. This keeps the core model simple: there is no lasting link between the diagram and the chain to keep consistent.
* The `attributes` of an `Entity` type in the meta model define which attributes the elements of that type must have in the concrete model. Each attribute definition has a name, a data type and whether it is required, as in the `attributes` table of the [meta-model file](#meta-model-file).
* Templates work the same way, one level down: the `parameters` of a template element in the concrete model define which attributes each instantiation of that template must have. An instantiation supplies them as its `arguments`. Because different templates have different parameters, these are stored as lists in a single column rather than as separate columns. Parameters are written like the column headers of a table, and arguments as name-value pairs:

  ```
  # Template table
  id:id;parameters:list(parameter);name:str
  filter_template_1;Low-pass filter;[cutoff:float,order:int]

  # Instantiation table
  id:id;template:ref(filter_template);arguments:list(argument);name:str
  filter_1;Input filter;filter_template_1;[cutoff=50.0,order=2]
  ```

  The model checker verifies that every instantiation supplies its template's required parameters, with values of the right data type.

### Example: simplified Arcadia

The example meta model of [selection_language.md](selection_language.md#running-example), with each type's stereotype.
Each type lists the attributes the meta model adds, and under *restricts* how it narrows the properties of its stereotype.
Types can also extend other types of the same stereotype, as `system_function` and `logical_function` extend `function`.

@startuml simplified_arcadia
hide empty members
skinparam classAttributeIconSize 0

package "Example meta model: simplified Arcadia" {

  class requirement <<Entity>> {
    {field} priority: enum(high|medium|low)
    text: text
    {field} verification_method: enum(test|inspection|analysis|demonstration)
  }

  class test <<Entity>> {
    procedure: text
  }

  class function <<Entity>>
  class system_function <<Entity>>
  class logical_function <<Entity>>
  class component <<Entity>>

  system_function -up-|> function
  logical_function -up-|> function

  class function_port <<Port>> {
    {field} direction: enum(in|out)
    .. restricts ..
    owner: function
  }

  class component_port <<Port>> {
    .. restricts ..
    owner: component
  }

  class functional_exchange <<Relationship>> {
    description: text
    .. restricts ..
    start: function_port
    end: function_port
  }

  class component_exchange <<Relationship>> {
    protocol: str
    .. restricts ..
    start: component_port
    end: component_port
  }

  class allocated_to <<Relationship>> {
    .. restricts ..
    start: function
    end: component
  }

  class covers <<Relationship>> {
    .. restricts ..
    start: test
    end: requirement
  }

  class realises <<Refinement>> {
    .. restricts ..
    start: logical_function
    end: system_function
  }

  class function_contains_function <<HierarchyRelationship>> {
    .. restricts ..
    parent: function
    child: function
  }

  class component_contains_component <<HierarchyRelationship>> {
    .. restricts ..
    parent: component
    child: component
  }

  class exchange_allocation <<Relationship_breakdown>> {
    .. restricts ..
    aggregate: component_exchange
    constituent: functional_exchange
  }

  class functional_chain <<Chain>> {
    .. restricts ..
    relationship: functional_exchange
  }

  class functional_sequence <<SequenceDiagram>> {
    .. restricts ..
    entities: function
    chain: functional_chain
  }

  class physical_architecture <<BlockDiagram>> {
    .. restricts ..
    entities: component, component_port
    relationships: component_exchange
    rules: component_internals
  }

  class function_breakdown <<BreakDownDiagram>> {
    .. restricts ..
    entities: function
    relationships: function_contains_function
    rules: function_breakdown
  }
}
@enduml


An element of the concrete model has the core attributes of its stereotype, followed by the attributes its type defines (including those inherited from types it extends).
These are the columns of the type's table, in this order. The example meta model defines a `name` attribute for the `Entity` stereotype, so every type has it:

| Type | Stereotype | Core attributes | Meta-model attributes | Table header |
|---|---|---|---|---|
| `requirement` | `Entity` | `id` | `name`, `priority`, `text`, `verification_method` | `id:id;name:str;priority:enum(high\|medium\|low);text:text;verification_method:enum(test\|inspection\|analysis\|demonstration)` |
| `function_port` | `Port` | `id`, `owner` | `name`, `direction` | `id:id;owner:ref(function);name:str;direction:enum(in\|out)` |
| `functional_exchange` | `Relationship` | `id`, `start`, `end` | `name`, `description` | `id:id;start:ref(function_port);end:ref(function_port);name:str;description:text` |
| `realises` | `Refinement` | `id`, `start`, `end` | `name` | `id:id;start:ref(logical_function);end:ref(system_function);name:str` |
| `function_contains_function` | `HierarchyRelationship` | `id`, `parent`, `child` | `name` | `id:id;parent:ref(function);child:ref(function);name:str` |
| `functional_chain` | `Chain` | `id`, `relationships` | `name` | `id:id;relationships:list(ref(functional_exchange));name:str` |
| `exchange_allocation` | `Relationship_breakdown` | `id`, `aggregate`, `constituent` | `name` | `id:id;aggregate:ref(component_exchange);constituent:ref(functional_exchange);name:str` |

Note how the *restricts* properties in the meta model become the types of the reference columns: `start:ref(function_port)`.

## MVP scope

* Model library, including file formats and the selection language (generation and verification rules).
* Meta-model checker and model checker.
* Editing engine, as CLI and as service.
* Diagram generator for block and breakdown diagrams, with SVG output for CI.
* Collaboration server with the hierarchy view and the diagram editor.
* One example meta model, a simplified Arcadia, in [`examples/simplified_arcadia`](../examples/simplified_arcadia).

Later: sequence and use-case diagrams, duplicate merger, changing an element's type, templates and instantiations, the query tool, further example meta models.
