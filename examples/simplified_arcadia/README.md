# Simplified Arcadia

An example meta model, based on a small subset of the [Arcadia](https://mbse-capella.org/arcadia.html) method used in Capella, with an example model of a coffee machine.

It serves as:

* an example of a meta model, for users writing their own;
* the running example of the [selection language](../../doc/selection_language.md) and the [architecture](../../doc/architecture.md);
* a starting point for the conformance test suite, as it uses every part of the [file formats](../../doc/file_formats.md).

## The meta model

[`metamodel.csv`](metamodel.csv) defines three levels:

| Level | Types | Diagrams |
|---|---|---|
| `system_level` | `actor`, `requirement`, `test`, `system_function` | `mission` (use case), `function_breakdown` (breakdown), `requirement_traceability` (block) |
| `logical_level` | `logical_function`, `function_port`, `functional_exchange`, `functional_chain` | `logical_dataflow` (block), `functional_sequence` (sequence) |
| `physical_level` | `component`, `component_port`, `component_exchange` | `physical_architecture` (block), `allocation` (block) |

The levels are connected by relationships:

* `realises`: a logical function realises a system function (a refinement);
* `allocated_to`: a logical function is allocated to a component;
* `exchange_allocation`: a functional exchange is carried by a component exchange (a relationship breakdown);
* `satisfies` and `covers`: system functions satisfy requirements, and tests cover them.

The meta model also contains generation rules for all diagram types except the sequence diagram, verification rules for traceability and allocation, two example queries, labels, shapes, and a Capella-like stylesheet.

## The example model

A coffee machine, in [`model/`](model) and [`diagrams/`](diagrams):

* The user selects a drink (`system_function_2`), after which the machine heats water (`system_function_3`) and brews (`system_function_4`).
* Four logical functions realise these, and are allocated to three components: a controller, a boiler and a pump unit.
* Three requirements: two verified by tests, and one, a design constraint on materials, verified by inspection, so it is not expected to be covered by a test.
* The diagrams include generated diagrams, a drawn block diagram that highlights a functional chain, and a drawn sequence diagram.
