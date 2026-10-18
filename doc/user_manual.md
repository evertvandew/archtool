# Architecting Tool — User Manual

## Purpose of this document

This manual explains how to use the tools of the Architecting tool: the command-line tools that check, query, render and edit a model, and, briefly, the web client of the collaboration server.

It assumes you know what you want to model, but not how the tools work. For the details behind the tools, see:

* [vision.md](vision.md): what the tool is for;
* [architecture.md](architecture.md): how it is built, including the core-model stereotypes;
* [file_formats.md](file_formats.md): the exact format of every file;
* [selection_language.md](selection_language.md): the language of queries, generation rules and verification rules;
* [gui_features.md](gui_features.md): the features of the web client.

The examples use the coffee machine in [`examples/simplified_arcadia`](../examples/simplified_arcadia). The example in [`examples/metamodelling`](../examples/metamodelling) shows how to define your own meta model.

## Concepts

A model is a directory of text files, kept in git like source code. The tools read and write these files; there is no database.

A model is described at three levels:

| Level | What it contains | Where |
|---|---|---|
| Core model | The fixed building blocks of every meta model: stereotypes such as `Entity`, `Port`, `Relationship`, `HierarchyRelationship`, `Chain` and `Diagram`. | Built into the tools. |
| Meta model | The types of a modelling method, such as `requirement`, `component` or `functional_exchange`, each with a stereotype and attributes; the diagram types; and the rules that generate diagrams and check the model. Types are identified by name. | `metamodel.csv` |
| Concrete model | The elements: instances of the meta model's types, each with a stable identifier such as `component_2`. | `model/*.csv`, `diagrams/*` |

Identifiers have the form `<type>_<number>`. They are allocated by the tools, never reused, and never change, so they can be used in links, commit messages and other documents.

## Installation

The tools need Python 3.12 or later. From a checkout of the repository, run them with [uv](https://docs.astral.sh/uv/):

```
uv run archtool --help
```

`uv run` creates the environment with the dependencies the first time. Alternatively, install the package into a Python environment of your own with `pip install .`, which puts the `archtool` command on its path.

Rendering diagrams also needs [elk-cli](https://www.npmjs.com/package/@kieler/elk-cli), which runs the Eclipse Layout Kernel on Node.js:

* If the `elk` command is installed (`npm install -g @kieler/elk-cli`), it is used.
* Otherwise, if `npx` is available, the tools run elk-cli with `npx -y @kieler/elk-cli`, which downloads it the first time.
* A different command can be set with `render.elk` in `archtool.toml`.

The other tools do not need elk-cli.

## A model repository

```
my-model/
├── archtool.toml                  # Settings
├── metamodel.csv                  # The meta model
├── model/                         # One table per type: model/<type>.csv
└── diagrams/                      # One index table per diagram type, and one <id>.diag file per diagram
```

Create a new repository for a meta model with [`archtool init`](#archtool-init-starting-a-model), e.g. for the simplified Arcadia meta model:

```
archtool init examples/simplified_arcadia/metamodel.csv my-model
cd my-model
git init
```

To experiment with a model that already has content, copy the example instead: `cp -r examples/simplified_arcadia my-model`.

### Settings: `archtool.toml`

All settings are optional:

```toml
[model]
metamodel = "metamodel.csv"        # The meta-model file, relative to this file; it may be outside the repository

[render]
elk = "elk"                        # The command that runs elk-cli

[server]
host = "127.0.0.1"                 # The address the collaboration server listens on
port = 8080                        # The port it listens on

[[exports]]                        # A file made from an element, offered as a download in the web client
name = "Meta-model file"
type = "metamodel"                 # The type of the elements it is made from
command = ["{python}", "generate_metamodel.py", "{repository}", "--metamodel", "{element}"]
file = "{label}.csv"
```

An export's command runs in the repository's directory, and writes the file to stdout. `{element}`, `{label}`, `{repository}` and `{python}` are replaced by the element's identifier and label, the repository's path, and the Python that runs the tools. See [file_formats.md](file_formats.md#archtooltoml) for the details.

### Files

The files are meant to be read, reviewed and merged with ordinary git tools:

* `model/<type>.csv` holds all elements of one type, one per line, in a table with `;` as separator. Its first line, `@last_number N`, records the highest identifier number ever used for the type.
* `diagrams/<diagram type>.csv` lists the diagrams of a type, with their names; `diagrams/<id>.diag` holds the content of one diagram.
* The tools write the files in a canonical form: writing an unchanged model changes nothing, and an edit changes only the lines it concerns.

You can edit the files by hand, e.g. to fix a merge conflict, or to add layout hints to a diagram. Run `archtool check` afterwards. For everyday changes, `archtool edit` and the web client are safer: they validate every change, allocate identifiers, and keep related elements consistent.

Recommended `.gitattributes`, so that git never converts line endings:

```
*.csv  text eol=lf
*.diag text eol=lf
```

## Using the command-line tools

All tools are subcommands of one command, `archtool`:

| Command | Purpose |
|---|---|
| `archtool init` | Create a model repository for a meta model. |
| `archtool check` | Check a model against its meta model and its verification rules. |
| `archtool query` | Run a query, or evaluate an expression in the selection language. |
| `archtool render` | Render diagrams as SVG files. |
| `archtool edit` | Change a model with commands. |
| `archtool serve` | Share a model with web clients, for viewing and editing. |

`archtool <command> --help` describes the arguments of each command.

Conventions shared by the tools:

* **Repository:** the tools work on the model in the current directory, unless told otherwise: `archtool init`, `archtool check` and `archtool serve` take the repository as an argument, the others take `-r <repository>`.
* **Output:** results are written to stdout as [JSON lines](https://jsonlines.org): one JSON object per line, easy to process with `jq` or a script. A human-readable output format is planned.
* **Errors:** a file that cannot be read is reported on stderr as `<file>:<line>:<column>: <message>`, with the path relative to the repository.
* **Exit status:** 0 on success; 1 when something failed, as described for each tool.

### `archtool init`: starting a model

```
archtool init [--link] <metamodel> [repository]
```

Creates a model repository for a meta model, in the given directory (by default the current one), which is created if needed. It writes one line per file created:

```
$ archtool init examples/simplified_arcadia/metamodel.csv my-model
{"file": "my-model/metamodel.csv"}
{"file": "my-model/archtool.toml"}
{"file": "my-model/.gitattributes"}
{"file": "my-model/.gitignore"}
{"file": "my-model/model/actor.csv"}
…
{"file": "my-model/diagrams/allocation.csv"}
```

The repository contains:

| File | Content |
|---|---|
| `metamodel.csv` | A copy of the meta model. |
| `archtool.toml` | The settings, naming the meta model; the other settings are written as comments, with their default values. |
| `model/<type>.csv` | An empty table for every type of the meta model, with its columns, and `@last_number 0`. |
| `diagrams/<diagram type>.csv` | An empty index table for every diagram type. |
| `.gitattributes` | Keeps git from converting the line endings of the model files. Only created if there is none yet. |
| `.gitignore` | Ignores `rendered/`, where `archtool render` writes. Only created if there is none yet. |

The new repository has no findings, and can be edited, rendered and served straight away. The empty tables show the columns of every type, which helps when reading or editing the files by hand.

* **Sharing a meta model:** with `--link`, the meta model is not copied; `archtool.toml` refers to it where it is, with a relative path. Use this when several models share one meta model, e.g. in the same git repository. Changes to the shared meta model then affect all of its models, so check them all after changing it.
* **A meta model in place:** if the directory already contains the meta model as `metamodel.csv`, run `archtool init metamodel.csv` there; the file is used as it is.
* **Safety:** nothing is created if the meta model has errors, which are reported as with `archtool check`, or if the directory already contains `archtool.toml`, `model/`, `diagrams/`, or a different `metamodel.csv`. Fix the meta model, or choose another directory, and try again.

`archtool init` does not run `git init`: the model may become part of an existing git repository, so that is left to you.

### `archtool check`: checking a model

```
archtool check [repository]
```

Checks everything that can be wrong in a model, and writes one finding per line:

* the syntax of all files;
* the meta model itself, including its rules, with suggestions for misspellings;
* every element against its type: required attributes, value types, enumeration values, and references to existing elements of the right types;
* the diagrams: their files, the elements they show, and the arguments of generation rules;
* the verification rules (`check`) of the meta model.

```
$ archtool check
{"severity": "error", "check": "required", "element": "requirement_6", "path": "model/requirement.csv", "message": "'text' is required"}
{"severity": "error", "check": "requirement_covered", "element": "requirement_6", "path": "model/requirement.csv", "message": "Requirement Hot coffee is verified by test, but is not covered by any test."}
{"severity": "warning", "check": "requirement_satisfied", "element": "requirement_6", "path": "model/requirement.csv", "message": "Requirement Hot coffee is not satisfied by any system function."}
```

Each finding has:

| Field | Meaning |
|---|---|
| `severity` | `error`, `warning` or `info`. |
| `check` | What found it: a built-in check such as `required` or `syntax`, or the name of a verification rule. |
| `element` | The element concerned, if any. |
| `path`, `line`, `column` | Where, relative to the repository, as far as known. |
| `message` | What is wrong. |

A model without findings produces no output. The exit status is 1 if any finding is an error, so warnings do not fail a build.

**In continuous integration**, run `archtool check` on every commit or pull request, so that errors are caught before they are merged.

**Accepted deviations** are not waived per element. Instead, the meta model records why a deviation is acceptable, and the verification rules take it into account; for example, the example's `requirement_covered` rule only applies to requirements whose `verification_method` is `test`. See [selection_language.md](selection_language.md#accepted-deviations).

### `archtool query`: exploring a model

```
archtool query [-r repository] <query or expression> [name=value …]
```

Answers questions about a model, in the [selection language](selection_language.md). The argument is either the name of a query defined in the meta model, or any expression.

**Expressions** select elements and navigate between them:

```
$ archtool query "requirement where priority = high"
{"id": "requirement_1", "label": "Brew coffee"}

$ archtool query "requirement_1.children.name"
{"value": "Brew strength"}
{"value": "Cup size"}

$ archtool query "count(requirement)"
{"value": 5}
```

A few common forms (see [selection_language.md](selection_language.md#the-language-in-five-minutes) for the whole language):

| Expression | Meaning |
|---|---|
| `requirement` | All requirements, including elements of types that extend `requirement`. |
| `component_1.children`, `component_1.descendants(2)`, `component_2.parent` | Navigating the hierarchy. |
| `component_2.ports`, `component_port_1.owner` | Ports and their owners. |
| `logical_function_1.targets(allocated_to)`, `requirement_1.sources(covers)` | Following relationships of a type, forwards or backwards. |
| `logical_function where children is empty` | Filtering; inside `where`, attribute names refer to the element being tested. |
| `functional_exchange between (logical_function where children is empty)` | The relationships between elements. |
| `a union b`, `a intersect b`, `a except b` | Set operations. |

**Queries** are named expressions in the `@rules` section of the meta model, which can also choose the columns of the output:

```
query untested_high_priority_requirements:
    select requirement where priority = high and sources(covers) is empty
    columns id, name, verification_method
```

```
$ archtool query untested_high_priority_requirements
{"id": "requirement_6", "name": "Hot coffee", "verification_method": "test"}
```

A query with parameters, e.g. `query functions_of(root: component):`, takes its arguments as `name=value` after its name: `archtool query functions_of root=component_1`.

**Output:** a set of elements gives one line per element, with its `id` and `label`, or with the query's columns; other values give one line per value, as `{"value": …}`. No output means an empty result.

**Errors** in an expression are reported on stderr, with the position and a suggestion where possible, and exit status 1:

```
$ archtool query requirment
<expression>:1:1: unknown name 'requirment'; did you mean 'requirement'?
```

Trying out an expression with `archtool query` is the easiest way to develop the generation and verification rules of a meta model.

### `archtool render`: rendering diagrams

```
archtool render [-r repository] [-o output] [diagram …]
```

Renders diagrams as SVG files, one per diagram, named `<id>.svg`. Without arguments, all diagrams of the model are rendered; the output directory is `rendered/` in the repository, unless `-o` says otherwise.

```
$ archtool render mission_1 requirement_breakdown_1 -o out
{"diagram": "mission_1", "file": "out/mission_1.svg"}
{"diagram": "requirement_breakdown_1", "file": "out/requirement_breakdown_1.svg"}
```

A diagram that cannot be rendered is reported on stderr, the other diagrams are still rendered, and the exit status is 1.

How a diagram looks is determined by the model, not by the person rendering it:

* **Content:** a generated diagram shows what its generation rule selects, so it is always up to date with the model; a drawn diagram shows the elements listed in its file.
* **Layout:** computed automatically, by ELK for block, breakdown and use-case diagrams, and by the tool itself for sequence diagrams. The result is the same on every machine, so diagrams rendered in CI match those in the web client.
* **Position hints:** a `layout <id> at <x>,<y> [size <w>x<h>]` line in a `.diag` file fixes the position, and optionally the size, of a block, relative to its enclosing block. Add these by hand when the automatic layout needs help; everything else is still laid out automatically.
* **Appearance:** the labels, shapes, line endings and CSS styles of each type are defined in the meta model. A `style <id> <CSS>` line in a `.diag` file overrides the style of one element in one diagram.

Rendered files are build products: they can be regenerated at any time, so you will usually not commit them (add `rendered/` to `.gitignore`).

The SVG elements carry the identifier of the element they show (`data-id`) and its type, ancestors and stereotypes as classes, so they can be styled or scripted further.

### `archtool edit`: changing a model

```
archtool edit [-r repository] [file]
```

Executes commands, one per line, from a file or from stdin, and writes the changes to the model's files immediately. It writes one result per command.

```
$ archtool edit <<'EOF'
# Add a requirement under "Brew coffee", and a diagram of its breakdown.
add requirement name="Hot coffee" text="The coffee shall be served hot." priority=high verification_method=test parent=requirement_1
add requirement_breakdown name="Brewing" generate="requirement_breakdown(root=requirement_1, depth=1)"
set requirement_6 priority=urgent
EOF
{"ok": true, "line": 2, "command": "add", "created": ["requirement_6", "requirement_contains_requirement_3"], "changed": [], "deleted": [], "issues": [{"severity": "error", "check": "requirement_covered", "element": "requirement_6", "path": "model/requirement.csv", "message": "Requirement Hot coffee is verified by test, but is not covered by any test."}, {"severity": "warning", "check": "requirement_satisfied", "element": "requirement_6", "path": "model/requirement.csv", "message": "Requirement Hot coffee is not satisfied by any system function."}], "resolved": []}
{"ok": true, "line": 3, "command": "add", "created": ["requirement_breakdown_2"], "changed": [], "deleted": [], "issues": [], "resolved": []}
{"ok": false, "line": 4, "command": "set", "error": "'priority': 'urgent' is not one of high, medium, low"}
```

#### Command syntax

* A command is a name, followed by positional arguments (types and identifiers) and `key=value` arguments.
* Values are written as in a table cell: `high`, `42`, `true`, `[function_3, function_7]`. Strings with spaces or special characters are written in double quotes, with `\"`, `\\` and `\n` as escape sequences: `name="Brew coffee"`.
* `key=` without a value removes a value.
* Blank lines and lines starting with `#` are ignored.

#### Commands

| Command | Meaning | Example |
|---|---|---|
| `add <type> key=value …` | Add an element. `parent=<id>` also places it in the hierarchy; if several hierarchy types fit, `hierarchy=<type>` chooses one. | `add component name="Grinder" parent=component_1` |
| `add <diagram type> key=value …` | Add a diagram: a generated one with `generate="<rule>(<arguments>)"`, or else a drawn one. | `add mission name="Missions" generate="mission"` |
| `connect <relationship type> start=<id> end=<id> key=value …` | Add a relationship. The ends may be entities or ports, as the meta model allows. | `connect allocated_to start=logical_function_1 end=component_2` |
| `set <id> key=value …` | Set or remove attributes of an element. | `set requirement_2 priority=medium` |
| `move <id> parent=<id>` | Move an element in the hierarchy; `parent=` makes it a top-level element. | `move component_3 parent=` |
| `delete <id> …` | Delete elements, and everything that cannot exist without them. | `delete test_2` |
| `show <diagram> <id> …` | Show elements in a drawn diagram. The contents of generated diagrams follow from their rule, so they cannot be changed. | `show logical_dataflow_2 logical_function_1` |
| `hide <diagram> <id> …` | Hide elements from a drawn diagram. | `hide logical_dataflow_2 logical_function_1` |
| `add_chain <diagram> <chain>` | Add the relationships of a chain to a sequence diagram as messages, and the missing participants. | `add_chain functional_sequence_1 functional_chain_1` |

There are no commands for position hints and per-diagram styles yet; add the `layout` and `style` lines to the `.diag` file by hand.

#### What a command does

* **All or nothing:** a command is validated completely before anything changes. Values must match their types, and references must point to existing elements of the right types. A command that fails changes nothing, and the next commands are still executed.
* **Identifiers** of new elements are allocated by the tool, and reported in `created`. A hierarchy is stored as hierarchy relationships, so `add … parent=…` also creates one (e.g. `requirement_contains_requirement_3`), and `move` replaces it.
* **Deleting propagates:** deleting an element also deletes its ports, the relationships attached to it or its ports, and the hierarchy relationships and relationship breakdowns that refer to it. Its parts become top-level elements, and references to it are removed from chains and drawn diagrams. A template that is still instantiated cannot be deleted.
* **Checking:** after every command, the model is checked again. `issues` lists the findings that the command introduced, and `resolved` the findings that it made disappear. A command that introduces errors still succeeds: a model may be incomplete while you work on it, and `archtool check` tells you what remains to be done.
* **Writing:** the changes are written to the files at once, and only files whose content changes are written. Review them with `git diff`, and commit them when you like.

#### Result fields

| Field | Meaning |
|---|---|
| `ok` | Whether the command succeeded. |
| `line` | The line of the command in the input. |
| `command` | The command name. |
| `created`, `changed`, `deleted` | The identifiers of the elements and diagrams affected. |
| `issues`, `resolved` | Findings, as written by `archtool check`. |
| `error` | Why a command failed. |

The exit status is 1 if any command failed.

Because the results are written as soon as each command is executed, `archtool edit` can also be used interactively: run it without a file, and type commands.

### `archtool serve`: the collaboration server

```
archtool serve [repository] [--host HOST] [--port PORT]
```

Starts a web server for one model, which several people can use at the same time with a web browser:

```
$ archtool serve examples/simplified_arcadia --port 8765
Serving examples/simplified_arcadia on http://127.0.0.1:8765/
```

The host and port default to the `[server]` settings in `archtool.toml`. Stop the server with Ctrl+C.

* Every change made in a web client is a command of `archtool edit`, executed by the server one at a time, and written to the files at once. All connected clients then show the new state.
* When two people change the same element at the same moment, the last change wins.
* The server does not commit: commit the files with git, as with any other change. Do not edit the files by other means while the server runs, as it does not reread them.
* The server has no authentication. By default it only listens on the local machine; only make it listen on other addresses (`--host 0.0.0.0`) on a network you trust.

## The web client

Open the address the server prints in a browser. The page has three columns:

* **Left:** the model explorer, with the entities as a tree that can be searched, collapsed and expanded, a form to add elements, and the list of diagrams with a form to add one.
* **Middle:** the selected element or diagram.
  * For an element: a form to edit its attributes, its place in the hierarchy, its parts, ports and relationships with forms to add them, the elements it refers to, the diagrams it appears in, and generated views of it, such as its breakdown.
  * For a diagram: the rendered diagram, in which elements can be selected by clicking them, with controls to show, hide and open elements, or to add chains to a sequence diagram. Double-clicking a block that has parts opens its subsystem, a diagram of its parts, as in Simulink; an "Up" button returns to the subsystem of its parent.
* **Right:** the findings of the checker, which link to the elements they concern, and a console in which any `archtool edit` command can be typed, with a log of the results of all commands of the client.

The address in the browser's address bar includes the selected element or diagram (e.g. `/#component_2`), so it can be shared with others who use the same server.

All features of the web client are listed in [gui_features.md](gui_features.md).

## Defining your own meta model

A meta model can be written by hand, following [file_formats.md](file_formats.md#meta-model-file), or modelled with the tools themselves, with the example in [`examples/metamodelling`](../examples/metamodelling):

1. Start a repository with the metamodelling meta model: `archtool init examples/metamodelling/metamodel.csv my-metamodel`.
2. Model your meta model, with its types, their attributes, labels and shapes, its diagram types and its rules, e.g. in the web client (`archtool serve my-metamodel`). One model can define several meta models, which can share types and rules. `archtool check` reports what is missing or wrong.
3. Generate the meta-model file of one of them: `uv run python examples/metamodelling/generate_metamodel.py my-metamodel -m "My method" -o my-method.csv`. It is only written if the tools can read it. With an export in `archtool.toml`, as in the example, the web client offers the file as a download on the meta model's page.
4. Start a model with it: `archtool init my-method.csv my-model`.

See the example's [README](../examples/metamodelling/README.md) for the details.

## A typical workflow

1. Start from a meta model: the simplified Arcadia example, or your own. Create a repository for it with `archtool init`, which also checks the meta model.
2. Build the model with `archtool edit` scripts or in the web client (`archtool serve`). Fix the findings the tools report as you go.
3. Develop queries and rules with `archtool query`, and add them to the meta model.
4. Review changes with `git diff`, and commit them with a message that explains why.
5. In continuous integration, run `archtool check` to keep errors out of the main branch, and `archtool render` to publish the diagrams.

## Troubleshooting

| Problem | Solution |
|---|---|
| `archtool render` fails because elk-cli cannot be run. | Install elk-cli (`npm install -g @kieler/elk-cli`), install Node.js so that `npx` is available, or set `render.elk` in `archtool.toml`. |
| A file cannot be read, e.g. after a merge. | The error gives the file, line and column. Fix the line by hand, then run `archtool check`. |
| An expression reports an unknown name. | Check the spelling against the meta model; the message suggests the closest name. Names in a `where` refer to attributes of the element tested. |
| A command fails with an error about a value. | The value does not match the attribute's type. Strings with spaces need double quotes; lists are written as `[a, b]`. |
| The server's address is already in use. | Choose another port with `--port`, or stop the other server. |
| The web client shows an old state after files were changed by hand. | Restart the server: it reads the files only when it starts. |
