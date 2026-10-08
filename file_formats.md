# Architecting Tool — File Format Specification

## Purpose of this document

This document specifies the files of a model repository, precisely enough to implement readers and writers, and to build the conformance test suite on.
It elaborates the file formats introduced in [architecture.md](architecture.md#file-formats).

## Principles

1. **Human-readable and mergeable.** Every file is plain text, line-based, and organised so that a typical change touches few lines.
2. **Canonical form.** For every file there is exactly one canonical way to write a given content. Tools always write the canonical form, so that writing an unchanged model produces byte-identical files.
3. **Lenient reading, strict writing.** Readers accept some variation (e.g. columns in a different order, blank lines); writers always produce the canonical form.
4. **Single source.** Every piece of information is stored in exactly one place. For example, the attributes of a diagram, such as its name, are stored in the diagram index table, not in the diagram file.

## General rules

These rules apply to all files:

* **Encoding:** UTF-8, without byte order mark.
* **Line endings:** LF. Readers also accept CRLF; writers always write LF.
* **Final newline:** every file ends with a single LF.
* **Trailing whitespace:** writers never write it. Readers do not strip it from cell values; it is part of the value.

## Repository layout

```
my-model/
├── archtool.toml                  # Settings
├── metamodel.csv                  # The meta model (or elsewhere; see archtool.toml)
├── model/                         # One table per type defined in the meta model
│   ├── <type>.csv
│   └── ...
└── diagrams/                      # One index table per diagram type, one file per diagram
    ├── <diagram_type>.csv
    ├── <diagram_id>.diag
    └── ...
```

* `model/<type>.csv` contains all elements of `<type>`. Elements of a type that extends `<type>` are stored in the table of their own type.
* A table is created when the first element of its type is created. It is never deleted while its type exists, even when it has no more rows, because it records the highest identifier number ever used (see [@last_number](#the-last_number-line)).
* `diagrams/<diagram_type>.csv` is the index table of a diagram type. Each diagram listed in it has a file `diagrams/<diagram_id>.diag`.
* Abstraction levels have no files in the concrete model.

Recommended `.gitattributes`, so that git never converts line endings:

```
*.csv  text eol=lf
*.diag text eol=lf
```

## `archtool.toml`

The settings file is in [TOML](https://toml.io) format. All keys are optional.

```toml
[model]
metamodel = "metamodel.csv"        # Path to the meta-model file, relative to this file

[render]
elk = "elk"                        # Command that runs elk-cli

[server]
host = "127.0.0.1"
port = 8080
```

| Key | Default | Meaning |
|---|---|---|
| `model.metamodel` | `"metamodel.csv"` | Path to the meta-model file, relative to `archtool.toml`. May point outside the repository, e.g. to a shipped example. |
| `render.elk` | `"elk"` | Command used to run elk-cli. |
| `server.host` | `"127.0.0.1"` | Address the collaboration server listens on. |
| `server.port` | `8080` | Port the collaboration server listens on. |

`archtool.toml` is the only file not written in a custom format: it is rarely edited, and TOML is well supported in both Python and Rust.

## Tables

All `.csv` files consist of tables in the same format. A model table contains one table; the meta-model file contains several.

### Structure

A model table looks like this:

```
@last_number 7
id:id;start:ref(function_port);end:ref(function_port);name:str;description:text
functional_exchange_1;function_port_3;function_port_8;Position;Current position estimate.\nUpdated at 10 Hz.
functional_exchange_2;function_port_9;function_port_4;Alarm;
functional_exchange_7;function_port_9;function_port_12;Mode;
```

1. Optional directive lines, starting with `@`.
2. The **header line**: the columns of the table, separated by `;`.
3. The **rows**: one per element, with one cell per column, separated by `;`.

### Header

Each column in the header is written as `<name>:<type>`.

* Column names match `[a-z][a-z0-9_]*`.
* A column name occurs at most once in a header.

Column types:

```
type       = simple | "list(" simple ")" ;
simple     = "id" | "ident" | "str" | "text" | "int" | "float" | "bool"
           | "enum(" word { "|" word } ")"
           | "ref(" ident { "|" ident } ")"
           | "parameter" | "argument" | "datatype" ;
word       = ident ;
ident      = [a-z][a-z0-9_]* ;
```

Lists of lists are not allowed.

### Cells

Within a row, cells are separated by `;`. A row has exactly as many cells as the header has columns.
An **empty cell** means that the attribute has no value. There is no distinction between an empty string and no value, nor between an empty list and no value.

| Type | Value | Examples |
|---|---|---|
| `id` | An identifier, see [Identifiers](#identifiers). | `function_42` |
| `ident` | A name matching `[a-z][a-z0-9_]*`. Used in the meta model. | `system_function` |
| `str` | Single-line text. | `Compute position` |
| `text` | Multi-line text. Newlines are written as `\n`. | `First line.\nSecond line.` |
| `int` | An optional `-`, followed by digits, without leading zeros. | `42`, `-3`, `0` |
| `float` | A decimal number, optionally with an exponent. | `0.5`, `-12.25`, `1e-07` |
| `bool` | `true` or `false`. | `true` |
| `enum(…)` | One of the listed words. | `high` |
| `ref(…)` | The identifier of an element of one of the listed types, or of a type that extends one of them. | `function_port_3` |
| `parameter` | A template parameter: see [Template parameters and arguments](#template-parameters-and-arguments). | `cutoff:float` |
| `argument` | A template argument: see [Template parameters and arguments](#template-parameters-and-arguments). | `cutoff=50.0` |
| `datatype` | A column type, as in a header. Used in the meta model. | `enum(high\|medium\|low)` |
| `list(…)` | Elements in square brackets, separated by commas. | `[function_3,function_7]` |

**Floats.** Readers keep the text of a float as it was written, and writers write it back unchanged, so that a float never changes merely by being read and written. When a tool computes a new float value, it writes the shortest decimal form that reads back as the same value, using an exponent only if the exponent is smaller than -4 or at least 16 (e.g. `0.1`, `1e-05`, `1e+16`).

### Escape sequences

The following escape sequences are used in cell values:

| Sequence | Character | Where |
|---|---|---|
| `\\` | `\` | everywhere |
| `\s` | `;` | everywhere |
| `\n` | line feed | `text` values only |
| `\t` | tab | `str` and `text` values |
| `\[` | `[` | everywhere |
| `\]` | `]` | everywhere |
| `\,` | `,` | inside list elements only |

* Any other backslash sequence is an error.
* `;`, `[` and `]` never occur unescaped in a value, and `,` never occurs unescaped in a list element. A reader can therefore split a row into cells at every `;`, and a list into elements at every `,`, before unescaping.
* Control characters other than tab and line feed are not allowed in values.
* Writers escape exactly the characters that must be escaped, and nothing else.

### Lists

A list is written as `[`, the elements separated by `,`, and `]`, without spaces.
Each element is written as a value of the list's element type, with `,` additionally escaped as `\,`.
An empty list is written as an empty cell.

```
[function_3,function_7]
[Alpha\, Beta,Gamma]
```

The second example is a `list(str)` with the elements `Alpha, Beta` and `Gamma`.

### Template parameters and arguments

A **parameter** defines an attribute that the instantiations of a template must or may supply:

```
<name>:<datatype>              # required parameter
<name>:<datatype>=<default>    # optional parameter, with a default value
```

An **argument** supplies the value of a parameter:

```
<name>=<value>
```

The value is written as a value of the parameter's data type. Within a list, a `,` inside a value is written as `\,`.

A template table, `model/filter_template.csv`:

```
@last_number 1
id:id;parameters:list(parameter);name:str
filter_template_1;[cutoff:float,order:int=2];Low-pass filter
```

An instantiation table, `model/filter.csv`:

```
@last_number 2
id:id;template:ref(filter_template);arguments:list(argument);name:str
filter_1;filter_template_1;[cutoff=50.0,order=4];Input filter
filter_2;filter_template_1;[cutoff=20.0];Output filter
```

Parameters of a list type, e.g. `gains:list(float)`, are not supported, because lists cannot be nested.

### Rows

* Each row describes one element; there is one row per element.
* Rows are sorted by identifier. All identifiers in a model table have the same type prefix, so this is the order of their numbers.
* Readers ignore blank lines. Writers write none in model tables.

### Column order

Readers accept the columns of a model table in any order.
Writers write them in canonical order:

1. The core attributes of the type's stereotype, in the order listed in [Core columns](#core-columns).
2. The attributes defined in the meta model: first those defined for the stereotype (see [Attributes](#attributes)), then those of the type at the root of its inheritance chain, down to those of the type itself. Within each, in the order of the `attributes` table.

A column for an attribute that is not defined for the type is an error. A column for an attribute that is not required may be absent; writers always write all columns.

### The `@last_number` line

The first line of every model table, and of every diagram index table, records the highest identifier number ever used for its type:

```
@last_number 7
```

* When adding an element, a tool uses the number above the larger of `@last_number` and the highest number present in the table, and updates `@last_number`.
* Deleting an element does not change `@last_number`.
* When git reports a merge conflict on this line, the higher number is kept.

## Identifiers

An identifier is the name of the element's type, an underscore, and a number:

```
identifier = type "_" number ;
number     = [1-9][0-9]* ;
```

* The type is everything before the last underscore.
* Numbers start at 1, have no leading zeros, and are never reused within a type.
* Because identifiers are split at the last underscore, type names must not end in an underscore followed by digits (`level_2` is not a valid type name).

## Core columns

The core columns of each stereotype, which every table of a type with that stereotype has:

| Stereotype | Core columns |
|---|---|
| `Entity` | `id:id` |
| `Port` | `id:id;owner:ref(…)` |
| `Relationship`, `Refinement` | `id:id;start:ref(…);end:ref(…)` |
| `HierarchyRelationship` | `id:id;parent:ref(…);child:ref(…)` |
| `Relationship_breakdown` | `id:id;aggregate:ref(…);constituent:ref(…)` |
| `Chain` | `id:id;relationships:list(ref(…))` |
| `TemplateEntity` | `id:id;parameters:list(parameter)` |
| `InstantiationEntity` | `id:id;template:ref(…);arguments:list(argument)` |
| Diagram types (index table) | `id:id` |

* `ref(…)` lists the types the meta model allows: e.g. for a `Port` type, the entity types listed as its `owner` in the meta model.
* All core columns are required.
* There is no core `name` column. Names, like all other descriptive attributes, are defined in the meta model. To give every element a name, a meta model defines a `name` attribute for the `Entity` stereotype (see [Attributes](#attributes)).
* How an element is shown, in diagrams and elsewhere, is defined by [labels](#labels) in the meta model.
* The order of `relationships` in a chain is significant: it is the order of the chain.

## Meta-model file

The meta-model file contains several tables, and sections with rules, styles and SVG definitions.
It is written by hand. Tools only change it when a type is renamed; they then change only the affected names, and leave everything else, including comments and layout, untouched.

### Structure

```
# Simplified Arcadia meta model

@table entity_types
name:ident;extends:ref(entity_types);description:text
component;;A part of the system.
function;;A function performed by the system.
logical_function;function;A function at logical level.
system_function;function;A function at system level.

@table attributes
type:ref(any_type);name:ident;datatype:datatype;required:bool;default:str;description:text
Entity;name;str;false;;The name of the element.
requirement;priority;enum(high|medium|low);true;;
requirement;text;text;false;;

@table labels
diagram_type:ref(diagram_types);type:ref(any_type);text:str;anchor:ident
;Entity;{name};
physical_architecture;component;{name};top
physical_architecture;component;«{type}»;top_left
physical_architecture;component_exchange;{name};middle

@rules
check requirement_covered (error):
    for each r in requirement where verification_method = test:
        require r.sources(covers) is not empty
        otherwise "Requirement {r} is verified by test, but is not covered by any test."
@end
```

* `@table <table name>` starts a table, followed by its header line and its rows. The table ends at the next line starting with `@`, or at the end of the file.
* `@rules` starts a section with rules in the [selection language](selection_language.md), which ends at a line `@end`. There may be several `@rules` sections.
* `@style` and `@defs` start sections with a stylesheet and SVG definitions, which end at a line `@end` (see [Styles](#styles)).
* Outside these sections, lines starting with `#` are comments, and blank lines are ignored.
* Each table may occur at most once. Tables that are not needed may be absent.
* Rows in the meta-model file are kept in the order they are written; they are not sorted.

### Names

* Type names are unique across all tables that define types (all tables below except `attributes`, `labels`, `shapes` and `abstraction_levels`), because they are used as identifier prefixes and in rules.
* Attribute names are unique within a type, including the attributes it inherits. `id`, `type` and the names of core columns cannot be used as attribute names.
* Names must not be keywords of the selection language, and type names must not end in an underscore followed by digits.
* In the meta-model file, `ref(<table>)` refers to a name defined in that table. `ref(entity_types)` also accepts the names in `template_types` and `instantiation_types`, because templates and instantiations are entities. `ref(any_type)` accepts the name of any type; in the `attributes`, `labels` and `shapes` tables, it also accepts the name of a stereotype.

### Tables

| Table | Stereotype | Columns |
|---|---|---|
| `entity_types` | `Entity` | `name:ident;extends:ref(entity_types);description:text` |
| `port_types` | `Port` | `name:ident;extends:ref(port_types);owner:list(ref(entity_types));description:text` |
| `relationship_types` | `Relationship` | `name:ident;extends:ref(relationship_types);start:list(ref(entity_types\|port_types));end:list(ref(entity_types\|port_types));description:text` |
| `refinement_types` | `Refinement` | `name:ident;extends:ref(refinement_types);start:list(ref(entity_types));end:list(ref(entity_types));description:text` |
| `hierarchy_types` | `HierarchyRelationship` | `name:ident;parent:ref(entity_types);child:ref(entity_types);description:text` |
| `relationship_breakdown_types` | `Relationship_breakdown` | `name:ident;aggregate:ref(relationship_types);constituent:ref(relationship_types);description:text` |
| `chain_types` | `Chain` | `name:ident;relationship:ref(relationship_types);description:text` |
| `template_types` | `TemplateEntity` | `name:ident;extends:ref(template_types);description:text` |
| `instantiation_types` | `InstantiationEntity` | `name:ident;template:ref(template_types);description:text` |
| `diagram_types` | `Diagram` | `name:ident;kind:enum(block\|sequence\|breakdown\|use_case);entities:list(ref(entity_types\|port_types));relationships:list(ref(any_type));chain:ref(chain_types);rules:list(ident);description:text` |
| `abstraction_levels` | `Abstraction_level` | `name:ident;diagrams:list(ref(diagram_types));description:text` |
| `attributes` | | `type:ref(any_type);name:ident;datatype:datatype;required:bool;default:str;description:text` |
| `labels` | | `diagram_type:ref(diagram_types);type:ref(any_type);text:str;anchor:ident` |
| `shapes` | | `diagram_type:ref(diagram_types);type:ref(any_type);shape:str;start:str;end:str` |

* `extends` is optional; a type extends at most one other type of the same table.
* Each template type has exactly one instantiation type: `instantiation_types.template` refers to it, and no two instantiation types refer to the same template type.
* In `diagram_types`, `kind` selects the core diagram stereotype. `chain` is only allowed for sequence diagrams, and is optional. `relationships` may list relationship, refinement, hierarchy and relationship breakdown types. `rules` lists the generation rules that diagrams of this type may use.

### Attributes

Each row of the `attributes` table defines an attribute that the elements of a type must (`required`) or may have.

* `type` is the name of a type, or the name of a stereotype (`Entity`, `Port`, `Relationship`, …). An attribute defined for a stereotype applies to all types with that stereotype, and with the stereotypes that specialise it. For example, `Entity;name;str;false;;` gives every element of every type an optional `name`. Stereotype names start with a capital letter, so they never clash with type names.
* `default` is written as a value of the attribute's data type. A required attribute has no default.

### Labels

The `labels` table defines the texts shown for an element, and where they are placed.

* `diagram_type` is the diagram type the label applies to. If it is empty, the label is the element's **default label**, which tools use outside diagrams: in the hierarchy view, in search results, and when a verification message inserts an element with `{…}`. Within a diagram type, an element that has no labels for that diagram type is shown with its default label.
* `type` is a type or a stereotype, as in `attributes`. A label for a type replaces the labels for the stereotype and for the types it extends.
* `text` is the text to show, with `{…}` inserting the value of an expression in the [selection language](selection_language.md), evaluated for the element. For example, `{name}` inserts the element's name, and `{type}` the name of its type.
* `anchor` is where the text is attached:
  * for blocks: `top_left`, `top`, `top_right`, `left`, `centre`, `right`, `bottom_left`, `bottom` and `bottom_right` (inside the block); the default is `centre`;
  * for lines: `start`, `middle` and `end`; the default is `middle`;
  * for ports: `outside` and `inside`; the default is `outside`.
* An element can have several labels in the same diagram type, one per row.
* If an element has no label at all, its identifier is shown.

### Styles

Diagrams are rendered as SVG, and styled with CSS.

* Each rendered element carries CSS classes: its type, the types it extends, and its stereotype, e.g. `class="system_function function Entity"`. The SVG of a diagram carries its diagram type as a class.
* The `@style` section contains a stylesheet, which applies to all diagrams. It is copied into the SVG unchanged, so any CSS that SVG supports can be used.
* The `@defs` section contains SVG definitions, such as gradients and markers, which the stylesheet can refer to. It is copied into the `<defs>` of the SVG unchanged.

```
@defs
<linearGradient id="component_fill" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#ffffff"/>
  <stop offset="1" stop-color="#a6d5ee"/>
</linearGradient>
@end

@style
.physical_architecture .component > rect { fill: url(#component_fill); stroke: #4a7ea4; }
.Relationship path { stroke: #333333; }
.functional_exchange path { stroke: #2e8b57; stroke-width: 2px; }
@end
```

Note that SVG does not support CSS gradients such as `linear-gradient(…)` in `fill`; gradients are defined in `@defs`, and referred to with `url(#…)`.

### Shapes and line endings

CSS can change colours, lines and fonts, but not the geometry of an element. The shape of blocks, and the endings of lines, are therefore defined in the `shapes` table:

```
@table shapes
diagram_type:ref(diagram_types);type:ref(any_type);shape:str;start:str;end:str
;Entity;rectangle;;
;Relationship;;none;arrow
physical_architecture;component;rounded_rectangle;;
function_breakdown;function;ellipse;;
;Relationship_breakdown;;none;none
;covers;;none;open_arrow
;function_contains_function;;filled_diamond;none
;state;#state_symbol;;
```

* `diagram_type` and `type` work as in `labels`: an empty diagram type applies to all diagram types, and a type replaces its stereotype and the types it extends.
* `shape` is the shape of a block. The tools provide a large set of built-in shapes:
  `rectangle`, `rounded_rectangle`, `ellipse`, `circle`, `diamond`, `hexagon`, `octagon`, `parallelogram`, `trapezoid`, `triangle`, `stadium`, `cylinder`, `document`, `note`, `folder`, `package`, `component`, `node`, `cloud`, `actor`, `use_case`, `state`, `initial_state`, `final_state`, `decision`, `fork_join`, `lifeline` and `activation`.
* `start` and `end` are the endings of a line, at its start and end. Built-in line endings:
  `none`, `arrow`, `open_arrow`, `filled_arrow`, `double_arrow`, `half_arrow`, `triangle`, `open_triangle`, `diamond`, `filled_diamond`, `circle`, `filled_circle`, `square`, `filled_square`, `bar`, `cross`, and the crow's-foot endings `one`, `many`, `zero_or_one`, `one_or_many` and `zero_or_many`.
* A value starting with `#` refers to an element in the `@defs` section instead: an SVG `<symbol>` for a shape, which is scaled to the size of the block, or an SVG `<marker>` for a line ending. This makes any shape or line ending possible that SVG can draw.
* The default shape is `rectangle`; the default line endings are `none` at the start and `arrow` at the end. Ports are drawn as small squares by default, and can be given a shape like any other type.
* Line style (solid, dashed, dotted), colours and widths are set with CSS in the `@style` section.

## Diagram files

A diagram consists of a row in the index table of its diagram type, which holds its identifier and attributes (such as its name), and a file `diagrams/<id>.diag`, which holds everything else.

### Structure

```
@diagram <id> : <diagram type>
<statements>
@end
```

The first line repeats the identifier and type, so that a diagram file can be understood on its own; the checker verifies that they match the file name and the index table.
Each statement is one line. Readers ignore blank lines. There are no comments: diagram files are written by tools.

### Generated diagrams

A generated diagram has a single `generate` statement, which calls a generation rule with its arguments, in the syntax of the selection language:

```
@diagram physical_architecture_4 : physical_architecture
generate component_internals(root=component_1, depth=2)
layout component_5 at 120,40 size 200x120
@end
```

### Drawn diagrams

A drawn block, breakdown or use-case diagram lists the elements it shows, and the chains it highlights:

```
@diagram physical_architecture_6 : physical_architecture
show component_1
show component_5
show component_exchange_3
highlight functional_chain_2
layout component_5 at 120,40 size 200x120
@end
```

* `show <id>` shows an entity, relationship, refinement, hierarchy relationship or relationship breakdown. The ports of a shown entity are drawn when a shown relationship uses them; a port can also be shown explicitly.
* `highlight <id>` highlights a chain, i.e. its relationships and the elements they connect.

A drawn sequence diagram lists its participants (lifelines) and its messages and processing, in order:

```
@diagram functional_sequence_12 : functional_sequence
participant function_3
participant function_7
participant function_9
message functional_exchange_1
process function_11 on function_7
message functional_exchange_2
@end
```

* `participant <id>` adds a lifeline. Lifelines are drawn in the order of these statements.
* `message <id>` adds a message. Its sender and receiver are not written: they are the owners of the relationship's `start` and `end`, and must be participants.
* `process <id> on <participant>` shows processing done by a participant in response to the preceding message.
* The order of `message` and `process` statements is the order in time.

### Layout and styling

```
layout <id> at <x>,<y> [size <width>x<height>]
style <id> <CSS declarations>
```

* Coordinates and sizes are integers, in pixels.
* `layout` fixes the position (and optionally size) of a block. All other blocks are laid out automatically.
* `style` overrides the style of one element in this diagram, with literal CSS declarations that are applied to the element's SVG, e.g. `style component_5 fill: url(#highlight_fill); stroke-dasharray: 4 2`. Styles that apply to all elements of a type belong in the `@style` section of the meta model instead.

### Canonical order

Writers write statements in this order:

1. `generate`.
2. For sequence diagrams: `participant` statements in lifeline order, followed by `message` and `process` statements in time order.
3. For other drawn diagrams: `show` statements, then `highlight` statements, each sorted by identifier.
4. `layout` statements, sorted by identifier.
5. `style` statements, sorted by identifier, with the declarations as written.

## Errors

Readers report errors with the file name, line and column. Errors include:

* malformed lines: a wrong number of cells, an unknown escape sequence, unbalanced square brackets;
* values that do not match their column type;
* duplicate identifiers, or identifiers whose type prefix does not match the table;
* a missing or malformed `@last_number` line in a model or index table.

Errors against the meta model, such as references to elements of the wrong type, or a missing required attribute, are reported by the model checker rather than the reader.
