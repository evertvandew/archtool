# Architecting Tool — Selection Language

## Purpose of this document

This document designs the selection language introduced in [architecture.md](architecture.md#selection-language).
One language serves three purposes:

* **Generation rules**, which select what a generated diagram shows.
* **Verification rules**, which check the model, e.g. for traceability and coverage.
* **Queries**, which extract data from the model, from the command line, the web clients or external tools.

The overall style, English keywords, Python-like indentation and dot navigation, is agreed. The details of the syntax may still change during implementation.

## Design goals

1. **Learnability first.** This language is likely to be the hardest part of learning the tools. It reads as close to English as is practical, has a small set of keywords, and the same expressions work in all three uses.
2. **Declarative and side-effect free.** Rules describe *what* to select or require, never *how*. Evaluating a rule never changes the model.
3. **Always terminates.** There are no loops, no recursion and no user-defined functions that call themselves. Evaluating a rule on a finite model always finishes.
4. **Statically checked against the meta model.** Every type, attribute and relationship name in a rule is checked by the meta-model checker before the rule is ever run, with clear error messages.
5. **Generic.** The language knows only the core model. All type, attribute and relationship names come from the meta model.
6. **Deterministic.** Results are always ordered by identifier (in natural order), unless a query says otherwise, so output is stable and diffable.

## Running example

The examples use a simplified Arcadia-like meta model with these types:

| Kind | Types |
|---|---|
| Entity types | `requirement`, `test`, `function`, `system_function` and `logical_function` (both extend `function`), `component` |
| Port types | `function_port`, `component_port` |
| Relationship types | `functional_exchange` (between function ports), `component_exchange` (between component ports), `allocated_to` (function → component), `realises` (logical function → system function), `covers` (test → requirement) |
| Hierarchy types | `function_contains_function`, `component_contains_component` |

Attributes: every element has an `id`, and the meta model gives every element a `name` (defined for the `Entity` stereotype); `requirement` also has `priority` (`high`, `medium`, `low`), `text`, and `verification_method` (`test`, `inspection`, `analysis`, `demonstration`).

## The language in five minutes

### Sets of elements

Almost every expression produces a **set of elements**.

```
requirement                          # all requirements
function                             # all functions, including system and logical functions
root                                 # a rule parameter, e.g. one component
```

A type name means all elements of that type, including elements of types that extend it.

### Navigation

A dot navigates from elements to related elements. Applied to a set, it navigates from every element in the set, and combines the results.

```
root.children                        # direct children in the hierarchy
root.descendants                     # children, their children, and so on
root.descendants(2)                  # down to two levels deep
f.parent                             # the hierarchy parent
c.ports                              # the ports of a component
p.owner                              # the entity a port belongs to
f.targets(allocated_to)              # the components function f is allocated to
r.sources(covers)                    # the tests that cover requirement r
```

### Filtering

`where` keeps only the elements that meet a condition.
Inside a `where`, names refer to the element being tested, so `priority` means "the priority of this requirement".

```
requirement where priority = high
logical_function where children is empty
logical_function where targets(allocated_to) is empty
```

### Relationships between sets

Selecting the relationships between a set of elements is so common that it has its own keywords.

```
functional_exchange between blocks          # both ends in blocks
functional_exchange from a to b             # starting in a, ending in b
covers to (requirement where priority = high)
```

The ends of a relationship may be ports; `between`, `from` and `to` then look at the ports' owners.

### Rules

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
    columns id, name, parent
```

## Expressions

### Values

| Kind | Examples |
|---|---|
| Set of elements | `requirement`, `root.children`, `blocks` |
| Text | `"Position"` |
| Number | `42`, `0.5` |
| Boolean | `true`, `false` |
| Enumeration value | `high` (checked against the attribute's `enum(…)` type) |
| List | `[high, medium]` |

A single element is a set with one element; there is no separate "element" type to learn.

### Navigation

Navigation is defined by the core model, so it is the same for every meta model.

| Navigation | Applies to | Result |
|---|---|---|
| `.parent` | entities | the hierarchy parent |
| `.children`, `.children(H)` | entities | direct hierarchy children (optionally only through hierarchy type `H`) |
| `.descendants`, `.descendants(n)` | entities | all hierarchy descendants, or down to `n` levels |
| `.ancestors` | entities | all hierarchy ancestors |
| `.ports`, `.ports(P)` | entities | ports (optionally only of port type `P`) |
| `.owner` | ports | the entity the port belongs to; for an entity, the entity itself |
| `.start`, `.end` | relationships | the start or end element |
| `.outgoing(R)`, `.incoming(R)` | entities, ports | relationships of type `R` starting or ending here (for an entity, also at its ports) |
| `.targets(R)`, `.sources(R)` | entities, ports | shorthand for `.outgoing(R).end.owner` and `.incoming(R).start.owner` |
| `.reachable(R)` | entities, ports | everything reachable by following relationships of type `R` any number of times |
| `.refines`, `.refined_by` | entities | elements related by a refinement type |
| `.template`, `.instances` | instantiations, templates | the template of an instantiation, or the instantiations of a template |
| `.constituents`, `.aggregate` | relationships | the relationship breakdown |
| `.relationships` | chains | the relationships a chain consists of, in order |
| `.chains`, `.chains(C)` | relationships | the chains (of chain type `C`) a relationship is part of |
| `.type` | any element | the name of the element's type, as text |
| `.<attribute>` | any element | the value of an attribute, e.g. `r.priority` |

Wherever a type name is expected, any type that extends it is included.

### Navigation per stereotype

The diagrams below show, for each stereotype, where each navigation leads.
They use the stereotypes of the [core model](architecture.md#core-model-stereotypes); a navigation applies to every element whose type has that stereotype.

* A navigation **without** `/` follows a core attribute that is stored in the concrete model, such as the `start` of a relationship.
* A navigation **with** `/` is derived: it is computed from the stored core attributes, as described in the note on the diagram. For example, an entity does not store its children; `.children` finds the hierarchy relationships whose `parent` is the entity.
* Where a navigation leads to the same stereotype, the target is drawn as a second box, for readability.
* Relationships, ports and the other stereotypes specialise `Entity`, so the navigations of `Entity` apply to them too. On an entity, `.owner` returns the entity itself; this is not drawn.

#### Entity: hierarchy

@startuml nav_entity_hierarchy
hide empty members
left to right direction
class "Entity" as E <<stereotype>>
class "HierarchyRelationship" as H <<stereotype>>
class "Entity" as T <<stereotype>>
E --> "0..1" T : /parent
E --> "*" T : /children(H)
E --> "*" T : /descendants(n)
E --> "*" T : /ancestors
H --> "1" T : parent
H --> "1" T : child
note as N
  <b>parent</b>: the parent of the hierarchy relationship
  whose child is this entity
  <b>children(H)</b>: the children of the hierarchy relationships
  (of type H) whose parent is this entity
  <b>descendants(n)</b>: children, repeated down to n levels
  <b>ancestors</b>: parent, repeated up to the top
end note
@enduml

#### Entity: ports and relationships

@startuml nav_entity_relationships
hide empty members
left to right direction
class "Entity" as E <<stereotype>>
class "Port" as P <<stereotype>>
class "Relationship" as R <<stereotype>>
class "Entity" as T <<stereotype>>
E --> "*" P : /ports(P)
E --> "*" R : /outgoing(R)
E --> "*" R : /incoming(R)
E --> "*" T : /targets(R)
E --> "*" T : /sources(R)
E --> "*" T : /reachable(R)
note as N
  <b>ports(P)</b>: the ports (of type P) whose owner is this entity
  <b>outgoing(R)</b>: the relationships (of type R) whose start
  is this entity or one of its ports
  <b>incoming(R)</b>: the same, for the end
  <b>targets(R)</b> = outgoing(R).end.owner
  <b>sources(R)</b> = incoming(R).start.owner
  <b>reachable(R)</b>: targets(R), repeated any number of times
end note
@enduml

#### Port

@startuml nav_port
hide empty members
left to right direction
class "Port" as P <<stereotype>>
class "Entity" as E <<stereotype>>
class "Relationship" as R <<stereotype>>
P --> "1" E : owner
P --> "*" R : /outgoing(R)
P --> "*" R : /incoming(R)
P --> "*" E : /targets(R)
P --> "*" E : /sources(R)
P --> "*" E : /reachable(R)
note as N
  <b>owner</b>: the core attribute of the port
  <b>outgoing(R)</b>, <b>incoming(R)</b>: the relationships
  (of type R) that start or end at this port
  <b>targets(R)</b>, <b>sources(R)</b>, <b>reachable(R)</b>:
  as for an entity
end note
@enduml

#### Relationship

@startuml nav_relationship
hide empty members
left to right direction
class "Relationship" as R <<stereotype>>
class "Entity or Port" as E <<stereotype>>
class "Relationship" as R2 <<stereotype>>
R --> "1" E : start
R --> "1" E : end
R --> "*" R2 : /constituents
R --> "*" R2 : /aggregate
note as N
  <b>start</b>, <b>end</b>: the core attributes of the relationship
  <b>constituents</b>: the constituents of the relationship
  breakdowns whose aggregate is this relationship
  <b>aggregate</b>: the aggregates of the relationship
  breakdowns whose constituent is this relationship
end note
@enduml

#### Relationship_breakdown

@startuml nav_relationship_breakdown
hide empty members
left to right direction
class "Relationship_breakdown" as B <<stereotype>>
class "Relationship" as R <<stereotype>>
B --> "1" R : aggregate
B --> "1" R : constituent
note as N
  <b>aggregate</b>, <b>constituent</b>:
  the core attributes of the breakdown
end note
@enduml

#### Chain

@startuml nav_chain
hide empty members
left to right direction
class "Chain" as C <<stereotype>>
class "Relationship" as R <<stereotype>>
class "Chain" as C2 <<stereotype>>
C --> "*" R : relationships
R --> "*" C2 : /chains(C)
note as N
  <b>relationships</b>: the core attribute of the chain,
  in order
  <b>chains(C)</b>: the chains (of type C) whose
  relationships include this relationship
end note
@enduml

#### Refinement

@startuml nav_refinement
hide empty members
left to right direction
class "Entity" as E <<stereotype>>
class "Refinement" as F <<stereotype>>
class "Entity" as T <<stereotype>>
F --> "1" T : start
F --> "1" T : end
E --> "*" T : /refines
E --> "*" T : /refined_by
note as N
  A refinement starts at the refining element,
  and ends at the element it refines.
  <b>refines</b>: the end of the refinements
  that start at this entity
  <b>refined_by</b>: the start of the refinements
  that end at this entity
end note
@enduml

#### TemplateEntity and InstantiationEntity

@startuml nav_template
hide empty members
left to right direction
class "InstantiationEntity" as I <<stereotype>>
class "TemplateEntity" as T <<stereotype>>
I --> "1" T : template
T --> "*" I : /instances
note as N
  <b>template</b>: the core attribute of the instantiation
  <b>instances</b>: the instantiations whose
  template is this template
end note
@enduml

### Set operations

```
a union b
a intersect b
a except b
```

Combining set operations, `between`, `from` or `to` with `where` requires parentheses, so there is never a question of what a `where` applies to:

```
(requirement where priority = high) union (requirement where text is empty)
```

### Conditions

| Condition | Meaning |
|---|---|
| `x = y`, `x != y`, `<`, `<=`, `>`, `>=` | comparison of values |
| `x in s` | every element of `x` is in set `s` |
| `x is empty`, `x is not empty` | the set is empty; for an attribute: no value is set |
| `x contains "text"` | the text contains the given text (case-insensitive) |
| `x matches "regex"` | the text matches a regular expression |
| `count(s) >= 2` | the number of elements in a set |
| `every y in s: cond`, `some y in s: cond`, `no y in s: cond` | quantifiers |
| `cond and cond`, `cond or cond`, `not cond` | combinations |

Comparing with an attribute that has no value is always false, except for `is empty`.

### Names inside `where`

Inside `where`, a bare name first refers to an attribute or navigation of the element being tested.
If a rule parameter or `let` has the same name, the meta-model checker reports the ambiguity as an error, and the user writes `this.name` to mean the element's attribute.

## Rules

Rules are written in the `@rules` sections of the meta-model file.
They use indentation, like Python, and every rule starts with a keyword: `define`, `diagram`, `check` or `query`.

### Parameters

Rules can take parameters, each with a type and an optional default:

```
diagram function_breakdown(root: function, depth: int = 3):
```

A parameter's type is a meta-model type (the argument is an element of that type), or `int`, `float`, `bool` or `text`.
Generated diagrams supply the arguments in their diagram file: `generate rule=function_breakdown parameters(root=function_3, depth=2)`.

### `define`: named expressions

`define` gives a name to an expression or condition, so it can be reused in other rules.
Definitions may use other definitions, but not themselves, directly or indirectly; this keeps evaluation terminating.

```
define leaf_functions = function where children is empty
define is_covered(r: requirement) = r.sources(covers) is not empty
```

### `diagram`: generation rules

A generation rule consists of `let` and `show` statements.
The diagram shows everything selected by any `show` statement; the order of the statements does not matter.

```
diagram function_breakdown(root: function, depth: int = 3):
    show root
    show root.descendants(depth)

diagram allocation(root: component):
    let blocks = root union root.descendants
    let functions = blocks.sources(allocated_to)
    show blocks
    show functions
    show allocated_to between (blocks union functions)
```

What is drawn follows from the diagram type:

* Shown entities become blocks. When an entity and its hierarchy parent are both shown, the entity is drawn inside its parent (block diagram) or below it (breakdown diagram).
* Shown relationships become lines.
* The ports of a shown entity are drawn when a shown relationship uses them, or when they are shown explicitly.

Sequence diagrams need an order of messages, which a set does not have, so they are drawn rather than generated. A sequence diagram can be filled from a chain, in the chain's order (see [architecture.md](architecture.md#stereotypes)).

### `check`: verification rules

A verification rule has a severity (`error`, `warning` or `info`), a `for each` over the elements to check, and one or more `require` statements.
Each element for which a `require` fails produces one finding, with the message after `otherwise`.

```
check requirement_covered (error):
    for each r in requirement:
        require r.sources(covers) is not empty
        otherwise "Requirement {r} is not covered by any test."

check logical_function_allocated (warning):
    for each f in logical_function where children is empty:
        require count(f.targets(allocated_to)) = 1
        otherwise "Leaf function {f} must be allocated to exactly one component."

check system_function_realised (warning):
    for each f in system_function:
        require f.sources(realises) is not empty
        otherwise "System function {f} is not realised by any logical function."
```

In messages, `{…}` inserts the value of an expression. An element is written as its default label, as defined in the meta model (see [file_formats.md](file_formats.md#labels)), or as its identifier if it has none.

The model checker reports findings in JSON by default, and returns a non-zero exit code if any finding has severity `error`.

#### Accepted deviations

The tools have no built-in mechanism to waive a finding for a specific element.
Accepted deviations are expressed in the meta model instead, and the verification rules take them into account.
For example, a `verification_method` attribute on requirements records how each requirement is verified. Requirements that are design constraints are verified by inspection, and are not expected to be covered by a test:

```
check requirement_covered (error):
    for each r in requirement where verification_method = test:
        require r.sources(covers) is not empty
        otherwise "Requirement {r} is verified by test, but is not covered by any test."
```

Another meta model might split requirements into functional and non-functional requirements, with design constraints as a kind of non-functional requirement, and only check coverage of functional requirements.

### `query`: queries

A query selects a set of elements, and optionally the columns to output and their order.

```
query unallocated_functions:
    select logical_function where targets(allocated_to) is empty
    columns id, name, parent
    order by name

query untested_high_priority_requirements:
    select requirement where priority = high and sources(covers) is empty
```

Without `columns`, a query outputs the identifier and the default label of each element.

### Ad-hoc expressions

Any expression can also be used directly, without writing a rule:

```
archtool query "requirement where priority = high"
archtool query "function_3.descendants(2)"
archtool query unallocated_functions
```

The same expressions are used in the search box of the web clients.
Because the CLI reads commands from stdin, `archtool query` also works interactively, which makes it a convenient way to explore a model and to try out expressions before putting them in a rule.

## Static checking

The meta-model checker checks every rule before it is used:

* Every type, attribute, relationship type and hierarchy type exists in the meta model, with suggestions for misspellings ("unknown type `requirment`; did you mean `requirement`?").
* Navigation is valid for the types involved, e.g. `.start` is only used on relationships, and `r.priority` only on types that have a `priority` attribute.
* Comparisons compare compatible values, and enumeration values exist in the attribute's enumeration.
* Rule parameters and `define`s are used with the right number and types of arguments, and `define`s do not refer to themselves.
* Names inside `where` are not ambiguous.

To make this possible, each expression has a static type: either a set of elements of known types (e.g. "set of `function`"), or a value type.

## Grammar

```
rules       = { define | diagram | check | query } ;

define      = "define" NAME [ params ] "=" ( expr | cond ) ;
diagram     = "diagram" NAME [ params ] ":" BLOCK( { let | show } ) ;
check       = "check" NAME [ params ] "(" severity ")" ":" BLOCK( { let } foreach ) ;
foreach     = "for" "each" NAME "in" expr ":" BLOCK( { let | require } ) ;
require     = "require" cond "otherwise" STRING ;
query       = "query" NAME [ params ] ":" BLOCK( { let } select ) ;
select      = "select" expr [ "columns" path { "," path } ] [ "order" "by" path [ "descending" ] ] ;

let         = "let" NAME "=" expr ;
show        = "show" expr ;
params      = "(" param { "," param } ")" ;
param       = NAME ":" NAME [ "=" literal ] ;
severity    = "error" | "warning" | "info" ;

expr        = setexpr [ "where" cond ] ;
setexpr     = relexpr { ( "union" | "intersect" | "except" ) relexpr } ;
relexpr     = path [ "between" path | [ "from" path ] [ "to" path ] ] ;
path        = primary { "." NAME [ "(" args ")" ] } ;
primary     = NAME [ "(" args ")" ] | "this" | literal | list | "(" expr ")" ;
args        = arg { "," arg } ;
arg         = expr ;

cond        = conj { "or" conj } ;
conj        = neg { "and" neg } ;
neg         = [ "not" ] atom ;
atom        = expr compare expr
            | expr "in" expr
            | expr "is" [ "not" ] "empty"
            | expr ( "contains" | "matches" ) STRING
            | quantifier NAME "in" expr ":" cond
            | NAME "(" args ")"
            | "(" cond ")" ;
quantifier  = "every" | "some" | "no" ;
compare     = "=" | "!=" | "<" | "<=" | ">" | ">=" ;

literal     = STRING | NUMBER | "true" | "false" ;
list        = "[" [ expr { "," expr } ] "]" ;
```

`BLOCK(x)` is an indented block of `x`. Comments start with `#`. Keywords are lowercase; names from the meta model are case-sensitive.

### Keywords

The complete list of keywords is: `define`, `diagram`, `check`, `query`, `let`, `show`, `for`, `each`, `in`, `require`, `otherwise`, `select`, `columns`, `order`, `by`, `descending`, `where`, `between`, `from`, `to`, `union`, `intersect`, `except`, `and`, `or`, `not`, `is`, `empty`, `contains`, `matches`, `every`, `some`, `no`, `this`, `true`, `false`, `error`, `warning`, `info`.

These names can therefore not be used as type, attribute or relationship names in a meta model; the meta-model checker reports it if they are.

## Implementation notes

* The parser is generated with [TatSu](https://github.com/neogeny/TatSu), a PEG parser generator for Python, from a grammar file derived from the grammar above. The grammar file is the authoritative definition of the syntax. For the Rust port, it can be translated to a Rust PEG parser generator such as pest.
* Python-like indentation needs attention: PEG grammars do not handle indentation-based blocks naturally. A small preprocessing step can turn changes in indentation into explicit block markers before parsing.
* Error messages must give the line and column, and be phrased in terms of the language rather than the grammar.
* Rules are processed in three steps: parsing into a syntax tree, type checking against the meta model, and evaluation against the model store.
* Evaluation uses the indexes of the model store (by type, by identifier, and reverse references), so that navigation such as `.sources(covers)` does not scan the whole model.
* The conformance test suite contains rules, models and their expected results, so the Rust port is tested against the same cases.
