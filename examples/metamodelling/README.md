# Metamodelling

An example for defining your own meta model with the tools themselves, instead of writing the meta-model file by hand.

Its [meta model](metamodel.csv) describes meta models: a model made with it says which types a modelling method has, with their attributes, labels and shapes, and which diagram types, abstraction levels and rules. The script [`generate_metamodel.py`](generate_metamodel.py) turns such a model into a meta-model file, with which you can start a model repository.

One model can define several meta models, which can share types, stereotypes and rules. The script generates the meta-model file of one of them.

This gives a meta model the same support as any other model: the web client to build and browse it, diagrams of its types, verification rules that find mistakes while you model, and reviewable diffs in git.

## The meta model

| What | Types | Linked by |
|---|---|---|
| A meta model as a whole: its name, description, stylesheet and SVG definitions | `metamodel` | |
| What belongs to which meta model: types, stereotypes, rules and abstraction levels | | `belongs_to` |
| The types of the meta model, all of them `model_type`s | `entity_type`, `port_type`, `relationship_type`, `refinement_type`, `hierarchy_type`, `breakdown_type`, `chain_type`, `template_type`, `instantiation_type`, `diagram_type` | `extends` |
| Stereotypes of the core model, for what applies to all types with a stereotype, e.g. a `name` for every `Entity` | `stereotype` | |
| What ports belong to, and what relationships connect | | `owned_by`, `starts_at`, `ends_at` |
| The types in a hierarchy type, relationship breakdown, chain type and instantiation type | | `has_parent`, `has_child`, `has_aggregate`, `has_constituent`, `chain_of`, `instantiates` |
| Attributes, labels and shapes: parts of the type or stereotype they belong to | `attribute`, `type_label`, `type_shape` | `classifier_has_attribute`, `classifier_has_label`, `classifier_has_shape` |
| Rules in the selection language | `rule` | |
| What diagram types show, and the rules that generate them | | `shows`, `highlights`, `uses_rule` |
| Abstraction levels, and their diagram types | `abstraction_level` | `includes` |

Everything that belongs to a meta model is linked to it with `belongs_to`; attributes, labels and shapes belong to the meta models of their type or stereotype. An element that belongs to several meta models is shared between them, such as a stereotype `Entity` that gives every entity a `name` in each of them.

Types and stereotypes are named by their `name`, which becomes their name in the meta-model file. A rule's text is the whole rule, starting with `define`, `diagram`, `check` or `query` and its name; the element's own name is only shown in the tools.

Diagrams of a meta model:

* `type_overview`: the types of a meta model and how they are related, e.g. which types a relationship type connects;
* `type_details`: a type or stereotype with its attributes, labels and shapes;
* `diagram_contents`: what a diagram type shows, and the rules that generate its diagrams.

Verification rules check what the meta-model file needs, such as names that can be used as type names, relationship types with a start and an end, and diagram types that only use generation rules. A warning points out entity types that no relationship or hierarchy type connects, directly, through their port types, or through the types they extend. The rules also check that everything belongs to a meta model, and that links stay within meta models: if a relationship type of a meta model starts at a type, that type must belong to the same meta model.

## The example model

The model in [`model/`](model) and [`diagrams/`](diagrams) defines two small meta models:

* "Blocks and requirements" (`metamodel_1`): blocks with flow ports, connected by flows, broken down into parts, and requirements that blocks satisfy. It has three diagram types with generation rules, a verification rule, labels, shapes and a stylesheet.
* "State machines" (`metamodel_2`): states, broken down into substates, with transitions between them, a diagram type and a verification rule.

They share the stereotypes `Entity`, `Relationship` and `HierarchyRelationship`, with the `name` attribute, the default label and the shapes defined for them.

## Making a meta model

1. Start a repository for your meta model with this example's meta model, and open it in the web client:

   ```
   archtool init examples/metamodelling/metamodel.csv my-metamodel
   archtool serve my-metamodel
   ```

   Or copy this example, and change its model.
2. Add a `metamodel`, and the types, their attributes, labels and shapes, the rules and the diagram types, each linked to the meta model with `belongs_to`. In the web client, the "Add new" field of a meta model adds a type, rule or abstraction level that belongs to it in one step, and "Add part" of a type adds its attributes, labels and shapes. `archtool check my-metamodel` reports what is still missing.
3. Generate the meta-model file:

   ```
   uv run python examples/metamodelling/generate_metamodel.py my-metamodel -m "My method" -o my-method.csv
   ```

   `-m` chooses the meta model, by its name or identifier; it can be left out if the model defines only one. For this example: `-m "Blocks and requirements"` or `-m "State machines"`.

   The file is only written if it is valid, as the tools would read it. Otherwise the script reports the errors, with the line of the generated file they are on.

   In the web client, the "Meta-model file" button of a meta model downloads the same file. This example's [`archtool.toml`](archtool.toml) declares the script as an export of meta models. A repository started with `archtool init`, as in step 1, needs the same `[[exports]]` table, with the path to the script, e.g. `command = ["{python}", "/path/to/examples/metamodelling/generate_metamodel.py", "{repository}", "--metamodel", "{element}"]`.
4. Start a model with it:

   ```
   archtool init my-method.csv my-model
   ```

   To change the meta model later, change the model in `my-metamodel`, and generate the file again. With `archtool init --link`, the model refers to the generated file where it is, so it uses the new version straight away.

The generated file is a build product: change the model it is generated from, not the file.
