# Architecting Tool

## Vision

I want a tool to help teams get a grip on their architecture.
It allows a team to construct a single model of their architecture.
Such a model allows the break-down of structures and functionality.
The model defines entities, and the relationships between those entities.
Some of the relationships can be shown in diagrams.

The result of this work should allow users to:

* Break down a project,
* Capture and define requirements,
* Define communication protocols between entities,
* Trace the breakdown to ensure functionality is fully covered,
* Link tests to functionality, and thus guarantee coverage,
* Connect functionality to a planning,
* Keep the model up-to-date with implementation,
* Baseline the model to reconstruct its state in the past.


The inspiration of the model structure is the Capella tool & the Arcadia MBSE method.

## Problem and differentiator

There are currently no modelling environments for system or software architects that fit well in a modern workflow.

Capella, the closest match, is not suitable for use in a team:

* It doesn't support merging changes made by different team members.
* It doesn't support exporting diagrams in an automated continuous integration workflow.
* Its internal XML format is not readable for humans.

This tool addresses these shortcomings: the model is stored as human-readable text that can be merged and versioned with git, all functionality is available through CLI tools that fit in a CI pipeline, and web interfaces allow real-time collaborative editing.

## Goals and non-goals

Goals:

* Real-time collaborative editing of the model, using appropriate web interfaces. This is part of the MVP release.
* A meta model that is expressive enough to describe Arcadia-like models, full UML/SysML, Simulink-like models and LabVIEW-like models.
* A documented model structure, so that external tools can extract data from the model.
* Several example meta models shipped with the tool.

Non-goals:

* Code generation. However, it should be possible for users of the tool to create their own code-generation tools, using the documented model structure.
* Executing or simulating models. The tool only describes e.g. Simulink-like or LabVIEW-like models. To execute them, a user would use the data from the model to create an executable instantiation of it.
* Synchronising the model with an implementation. The tool does not assume there is an implementation to keep in sync; a model may be purely abstract. How a team keeps model and implementation in sync depends on their situation, and teams are free to build their own round-trip engineering tools.
* Full UML/SysML support. The meta model should make it possible to define it, and it may be added as an example, but delivering it is not a goal of this project.
* User accounts and access control, at least for the MVP release.

## Tooling

This work will construct a set of tools.
Each tool will perform a specific task.

These tasks include:

* Checking the validity of the model and reporting what is wrong.
* Checking traceability and coverage in the model.
* Generating diagrams.
* Analysing changes and propagating changes to dependent elements in the model. Where changes can be propagated automatically, they are. Only when a change leaves the model in an inconsistent state is this reported to the user.
* Tools to check the meta model.
* Adding elements to the model.
* Merging elements when duplicates were created by accident.
* Viewing and editing the hierarchical structure of the model.
* Drawing diagrams that cannot be generated.
* Generating identifiers centrally, through a web API (see Identifiers).

In future, a query tool may be added, which external tools can use to extract the data they need from the model.

Tools will have CLI interfaces.
A CLI tool reads its commands from a file or from stdin, so that it can be run interactively, from a script, or as a long-running service.

Where an HMI is essential, as in the diagram editor, it is implemented as a web interface that communicates with a CLI tool running as a service, which does the actual editing.
If model files are edited by hand while such a service is running, the result is undefined; users should not do that.

### Collaborative editing

For real-time collaborative editing, a server holds the model and serves the web interfaces.
There is one server per model.
The same server provides the identifier-generation web API.

Users commit the model to git manually, to create baselines.
Bringing in changes from other branches while the server is running also requires manual action from the users.
Conflicts between git branches are detected by the merge tool, which offers methods to resolve them; resolving them is not the responsibility of this tooling.
When two users edit the same element on the collaboration server at the same moment, the last write wins, for now.

## Diagram types

Only a limited set of diagram types is needed.

The core model supports the following diagram types:

* A breakdown of one entity into smaller entities of the same type.
* A block diagram, which shows how entities contain other entities, and how they are interconnected. Entities connect to each other using connection points called "ports".
* A sequence diagram, which shows entities that communicate, what is communicated, and the processing that is done in response to a communication.
* A diagram similar to the UML Use Case diagram for high-level overview of main functions.

The following diagram types are not part of the core model, but can be defined using the meta model. Both are rendered as block diagrams:

* A state diagram that shows the various states a specific entity can be in, and the conditions for transitions between states.
* A diagram that shows similarities and shared functionality, with similar semantics as the UML class diagram.

### Generated and drawn diagrams

Diagrams are either generated from the model, or drawn by hand.

Generated diagrams are defined by generation rules in the meta model.
These rules are declarative: they select what to show rather than program how to show it.
For example: "a breakdown diagram of entity X shows all children of type `function` down to depth 2, plus the `functional_exchange` relationships between them".
Declarative rules stay readable, can be checked by the meta-model checker, and are safe to execute.

A generated diagram is still an entity in the model, so that other entities can refer to it (e.g. for refinement).
What is stored for a generated diagram is its identifier, the generation rule it uses, the rule's parameters (e.g. the root entity and depth), and optional layout hints.
The diagram content itself is not stored; it is computed from the model on demand, so it can never become stale.

Layout is computed automatically.
Manual adjustments to the layout are stored as layout hints in the diagram file, in the same way PlantUML includes styling.
Diagram files are separate from the entity tables, so layout changes never show up as changes to entities.

Some diagram content cannot be derived from the attributes defined in the meta model, such as the order of messages in a sequence diagram.
Such data is stored in attributes defined by the core model (see Core attributes).

Drawn diagrams can diverge from the model.
The validity checker verifies that every element in a drawn diagram exists in the model and is allowed by the definition of that diagram type.

## Model meta-model

The exact structure of model for e.g. the Arcadia method is quite complex.
It shouldn't be hard-coded, I believe the modelling tool will be much simpler if the underlying meta model is defined in a separate document.

Three levels of abstraction are distinguished:

* The **core model**, which is fixed and hard-coded in the tools. It defines the kinds of elements a meta model can be built from: entities, ports, relationships, hierarchy, diagrams, abstraction levels, templates and instantiations. It is formally defined below.
* The **meta model**, which is configurable. It describes a specific method, such as Arcadia, as instances of the core-model elements. For example, it defines an entity type `function`: its name and the attributes expected for it. Meta-model elements are identified by their names; they have no identifiers.
* The **concrete model**, which is the model a team builds. Its elements are instances of the types defined in the meta model. Each has an identifier, and the user supplies the values of the attributes that its type defines.

The meta model should define:

* The different types of entities used in the model.
* Entities can have "inheritance" relations, so that a specific entity can inherit its role from another entity. Meta-model rules that apply to an entity also apply to entities that inherit from it.
* The allowed hierarchical connections between entity types: what entities can a specific entity contain?
* The allowed ports types for each type of entity.
* The allowed connection types between ports and / or entities.
* The refinement relations between entities.
* The abstraction levels in the model.
* The diagram definitions. For each diagram, specifies the type of diagram (e.g. sequence, breakdown etc, as defined in the section Diagram Types), which entity types can be in it, and what relationships can be represented between them.
* The generation rules for diagrams that can be generated (see Generated and drawn diagrams).
* Verification rules, used e.g. by the coverage checker. For example: "every requirement must have at least one `covers` relationship".

Diagrams are entities in their own right, so that e.g. a function at a high level can be refined into a sequence diagram at a lower level.

### Domain elements

Requirements, tests and planning items have no dedicated support in the core model.
They are ordinary entity types, defined in the meta model.

For example, the tests mentioned in the vision are part of the IVVQ model that accompanies the requirements model a user creates.
What that IVVQ model looks like, including e.g. a `covers` relationship between a test and a function, is defined in the meta model.
The rules to verify coverage are also part of the meta model.
(These tests are unrelated to the tests of the tool itself.)

Likewise, planning is modelled within the tool for now, using entity types defined in the meta model, rather than by linking to an external planning system.

### Core model concepts

**Core attributes.**
The concrete model stores more data than the attributes defined in the meta model.
Besides the attributes its meta-model type defines, each element of the concrete model has the attributes the core model requires to implement the tool's features.
For example, in a sequence diagram the order in which messages are sent, and the order in which blocks are drawn, must be stored.
This may be implicit in the order in which messages are defined, but it must be possible to change the order and e.g. insert messages between existing ones.
The exact attributes each core element needs will be determined at a later stage.

**Chains.**
A chain is similar to a Capella functional chain.
In Capella, a functional chain is defined by the sequence of messages that are exchanged between functions.
In the meta model, a chain type therefore stores the type of relationship these messages pass along.
In the concrete model, a chain is an element in its own right, holding the relationships it consists of, so that e.g. a block diagram can highlight a functional chain in an architecture.

**Refinement.**
A refinement is a relationship that connects an element to the element it refines, e.g. a logical function to the system function it realises.
Refinements are vital in a model with distinct hierarchy levels: they connect the different levels.

**Hierarchy and relationship breakdown.**
`HierarchyRelationship` and `Relationship_breakdown` do not specialise `Relationship`.
They are part of the core model, and are rendered differently in block diagrams:

* A `HierarchyRelationship` is rendered by drawing child blocks within their parent block.
* A `Relationship_breakdown` is rendered as a dashed line from a port used in one relationship to the port this exchange is mapped on.

**Templates and instantiations.**
To support executable models, the core model has two additional specialisations of `Entity`: `TemplateEntity` and `InstantiationEntity`.
A template is e.g. a Simulink library block or a LabVIEW subVI; an instantiation is one use of a template, placed somewhere in a model.
An instantiation takes its ports and internal structure from its template, and can supply its own attribute values.

In the meta model, there is exactly one instantiation type for a particular template type, so there is one and only one way to instantiate that template.
In a concrete model, a template can of course be instantiated many times.
Templates will define the parameters users can or must supply when instantiating them; the details are part of the architecture.

**Abstraction levels.**
Abstraction levels are optional, and are only used in the user interface, to guide users in what they can do within a particular abstraction level.
In a typical meta model, the user takes care to make coherent sets of entities and diagrams for each abstraction level.
The diagrams are the entries into those levels, as they link all other entities together.
Most models will not use explicit abstraction levels; they are only needed for models of extraordinary complexity, as in Capella.

A more formal definition of the core model is below, in two diagrams: the elements, and the diagrams.

@startuml meta_model
skinparam nodesep 60
skinparam ranksep 70

class Entity {
    name: str
    attributes 
}

class Port
class HierarchyRelationship
class Relationship
class TemplateEntity
class InstantiationEntity

Port -up-|> Entity
Port -up-> "1" Entity : owner

HierarchyRelationship -up-|> Entity
HierarchyRelationship -up-> "1" Entity : parent
HierarchyRelationship -up-> "1" Entity : child

Relationship -up-|> Entity
Relationship -up-> "1" Entity : start
Relationship -up-> "1" Entity : end

' A refinement connects elements at different levels of the hierarchy
Refinement -up-|> Relationship

TemplateEntity -up-|> Entity
InstantiationEntity -up-|> Entity
InstantiationEntity *-left-> "1" TemplateEntity

' Capella can map e.g. several functional exchanges on a single component exchange.
' That mapping is the "Relationship_breakdown"
Relationship_breakdown -up-|> Entity
Relationship_breakdown -up-> "1" Relationship : aggregate
Relationship_breakdown -up-> "1" Relationship : constituent

Chain -up-|> Entity
Chain -up-> "1" Relationship : type
Chain -up-> "*" Relationship : relationships

@enduml

The diagrams in the core model, and what they show:

@startuml meta_model_diagrams
skinparam nodesep 40
skinparam ranksep 80

class Entity {
    name: str
    attributes 
}

class Diagram {
    rendering_details: entity, styling
}

class Abstraction_level { 
    name 
}

' The second Entity box is the same class as the first, drawn twice for readability
class "Entity" as Entity2

Diagram -up-|> Entity

' Abstraction levels are optional
Abstraction_level *-right-> "*" Diagram : diagrams

BlockDiagram -up-|> Diagram
SequenceDiagram -up-|> Diagram
BreakDownDiagram -up-|> Diagram
UseCaseDiagram -up-|> Diagram

BlockDiagram -down-> "1..*" Entity2 : block
BlockDiagram -down-> "1..*" HierarchyRelationship : hierarchy
BlockDiagram -down-> "*" Relationship : exchange
BlockDiagram -down-> "*" Chain : chain

SequenceDiagram -down-> "1..*" Entity2 : block
SequenceDiagram -down-> "1..*" Entity2 : message
SequenceDiagram -down-> "*" Entity2 : processing
SequenceDiagram -down-> "0..1" Chain : chain

BreakDownDiagram -down-> "1..*" Entity2 : block
BreakDownDiagram -down-> "*" Relationship : link

UseCaseDiagram -down-> "1..*" Entity2 : actor
UseCaseDiagram -down-> "1..*" Entity2 : function
UseCaseDiagram -down-> "1..*" Relationship : role


@enduml


## Data storage

The data in the model is stored in a format intended for human reading and editing, as well as merging changes made by others.
It must be suitable for version management using git.
Baselines of the model are git tags or commits.

### File formats

Custom DSLs are used for both the model and the meta model:

* **Diagrams** are expressed in a language similar to PlantUML, including styling and layout hints.
* **Other elements** of the concrete model are defined in CSV-like tables. Each element type defined in the meta model, except abstraction levels, has its own file, containing all instances of that type.
* **The meta model** is also expressed in the CSV-like format.

The CSV-like format is self-descriptive:

* Column headers contain annotations for the data type of the column.
* The column separator is the semicolon, because it is used less frequently in user-supplied texts than the comma.
* Escape sequences allow multi-line strings containing any character. The usual C-style escape sequences are used, such as `\n` and `\t`, plus `\s` to escape the column separator.
* Each element is stored on a single line, and lines are sorted by identifier. This keeps diffs small and merges simple.

### Identifiers

Every element of the concrete model has a stable identifier.
Elements of the meta model have no identifiers; they are identified by their names.
All references between elements of the concrete model use identifiers, never names.
Names of elements are expected to change, so diagrams and other elements never store an element's name, only its identifier.

Identifiers have the form `<type>_<number>`, where `<type>` is the name of the element's type in the meta model.
Whether the number is counted per type or globally is left to the implementation; whichever is easiest.
Identifiers are never reused after an element is deleted, so that baselines and old references remain unambiguous.

The type prefix must never become outdated:

* **Renaming a type in the meta model** renames all identifiers of that type, preserving the number. For example, renaming `function` to `system_function` turns `function_42` into `system_function_42`. This is rare, but a valid use case that is easy to implement. While the meta model is being changed, no-one edits the concrete model.
* **Changing the type of an element** in the concrete model is an advanced feature, not part of the MVP release. When it is implemented, it gives the element a new identifier and updates all references to it in the model.

Because team members create elements in parallel on separate branches, identifier allocation must not collide when branches are merged.
During collaborative work, the collaboration server generates identifiers centrally.
For offline work, users make their own arrangements to avoid collisions.
The tooling detects collisions, but does not resolve them.

## Deferred decisions

The vision remains a vision. The following are deliberately left for the architecture and later stages:

* The scope of the MVP release.
* The exact attributes each core-model element needs (see Core attributes).
* How generation rules, diagram definitions and verification rules are expressed in the meta model.
* A query tool for extracting data from the model.
* Changing the type of an element in the concrete model.
* How templates define the parameters supplied when instantiating them.

