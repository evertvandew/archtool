# Copyright (C) 2026 Evert van de Waal
#
# This file is part of archtool, the architecting tool.
#
# archtool is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# archtool is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with archtool. If not, see
# <https://www.gnu.org/licenses/>.

"""The syntax tree of the selection language.

The parser produces the nodes in the first part of this module. The resolver (archtool.language.resolver)
checks them against a meta model, and replaces names and calls by the resolved nodes in the second part, which
the evaluator works on.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Position:
    """A position in a file. Lines and columns are counted from 1."""

    path: str
    line: int
    column: int


# --- Expressions --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Name:
    """A bare name: a variable, a type, an attribute of `this`, a definition or an enumeration value."""

    ident: str
    pos: Position


@dataclass(frozen=True, slots=True)
class This:
    pos: Position


@dataclass(frozen=True, slots=True)
class Literal:
    """A string, number or boolean. Strings may contain `{…}` interpolations, which are only evaluated in
    messages and labels."""

    value: str | int | float | bool
    pos: Position


@dataclass(frozen=True, slots=True)
class ListLiteral:
    items: tuple["Expression", ...]
    pos: Position


@dataclass(frozen=True, slots=True)
class Call:
    """`name(arguments)`: a built-in function, a definition, or a navigation of `this` inside `where`."""

    ident: str
    arguments: tuple["Expression", ...]
    pos: Position


@dataclass(frozen=True, slots=True)
class Navigate:
    """`source.step` or `source.step(arguments)`: a navigation or an attribute."""

    source: "Expression"
    step: str
    arguments: tuple["Expression", ...] | None
    pos: Position


@dataclass(frozen=True, slots=True)
class SetOperation:
    op: str  # "union", "intersect" or "except"
    left: "Expression"
    right: "Expression"
    pos: Position


@dataclass(frozen=True, slots=True)
class Between:
    """`relation between other`: relationships with both ends in `other`."""

    relation: "Expression"
    other: "Expression"
    pos: Position


@dataclass(frozen=True, slots=True)
class FromTo:
    """`relation from origin to target`, where either part may be absent."""

    relation: "Expression"
    origin: "Expression | None"
    target: "Expression | None"
    pos: Position


@dataclass(frozen=True, slots=True)
class Where:
    source: "Expression"
    condition: "Condition"
    pos: Position


# Resolved expressions.


@dataclass(frozen=True, slots=True)
class TypeRef:
    """All elements of a type: `types` holds the type and the types that extend it."""

    ident: str
    types: frozenset[str]
    pos: Position


@dataclass(frozen=True, slots=True)
class ElementRef:
    """An element, by its identifier, e.g. `function_3`."""

    identifier: str
    pos: Position


@dataclass(frozen=True, slots=True)
class Variable:
    """A parameter, `let`, `for each` or quantifier variable."""

    ident: str
    pos: Position


@dataclass(frozen=True, slots=True)
class EnumValue:
    value: str
    pos: Position


@dataclass(frozen=True, slots=True)
class Count:
    argument: "Expression"
    pos: Position


@dataclass(frozen=True, slots=True)
class DefinitionCall:
    """A call of a definition, or a reference to a definition without parameters."""

    ident: str
    arguments: tuple["Expression", ...]
    pos: Position


type Expression = (
    Name | This | Literal | ListLiteral | Call | Navigate | SetOperation | Between | FromTo | Where
    | TypeRef | ElementRef | Variable | EnumValue | Count | DefinitionCall
)  # fmt: skip


# --- Conditions ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Compare:
    op: str  # "=", "!=", "<", "<=", ">" or ">="
    left: Expression
    right: Expression
    pos: Position


@dataclass(frozen=True, slots=True)
class In:
    left: Expression
    right: Expression
    pos: Position


@dataclass(frozen=True, slots=True)
class IsEmpty:
    value: Expression
    negated: bool
    pos: Position


@dataclass(frozen=True, slots=True)
class TextMatch:
    op: str  # "contains" or "matches"
    value: Expression
    pattern: str
    pos: Position


@dataclass(frozen=True, slots=True)
class Quantifier:
    quantifier: str  # "every", "some" or "no"
    var: str
    source: Expression
    condition: "Condition"
    pos: Position


@dataclass(frozen=True, slots=True)
class ConditionCall:
    """A call of a definition whose body is a condition."""

    ident: str
    arguments: tuple[Expression, ...]
    pos: Position


@dataclass(frozen=True, slots=True)
class And:
    operands: tuple["Condition", ...]
    pos: Position


@dataclass(frozen=True, slots=True)
class Or:
    operands: tuple["Condition", ...]
    pos: Position


@dataclass(frozen=True, slots=True)
class Not:
    operand: "Condition"
    pos: Position


type Condition = Compare | In | IsEmpty | TextMatch | Quantifier | ConditionCall | And | Or | Not


# --- Rules --------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Parameter:
    ident: str
    type: str
    default: Literal | None
    pos: Position


@dataclass(frozen=True, slots=True)
class Let:
    var: str
    value: Expression
    pos: Position


@dataclass(frozen=True, slots=True)
class Show:
    value: Expression
    pos: Position


@dataclass(frozen=True, slots=True)
class Message:
    """A message with `{…}` interpolations: `parts` alternates text and expressions."""

    parts: tuple[str | Expression, ...]
    pos: Position


@dataclass(frozen=True, slots=True)
class Require:
    condition: Condition
    message: Message
    pos: Position


@dataclass(frozen=True, slots=True)
class ForEach:
    var: str
    source: Expression
    statements: tuple[Let | Require, ...]
    pos: Position


@dataclass(frozen=True, slots=True)
class Select:
    source: Expression
    columns: tuple[Expression, ...]
    order: Expression | None
    descending: bool
    pos: Position


@dataclass(frozen=True, slots=True)
class Define:
    ident: str
    parameters: tuple[Parameter, ...]
    body: Expression | Condition
    pos: Position


@dataclass(frozen=True, slots=True)
class DiagramRule:
    ident: str
    parameters: tuple[Parameter, ...]
    statements: tuple[Let | Show, ...]
    pos: Position


@dataclass(frozen=True, slots=True)
class CheckRule:
    ident: str
    parameters: tuple[Parameter, ...]
    severity: str  # "error", "warning" or "info"
    lets: tuple[Let, ...]
    foreach: ForEach
    pos: Position


@dataclass(frozen=True, slots=True)
class QueryRule:
    ident: str
    parameters: tuple[Parameter, ...]
    lets: tuple[Let, ...]
    select: Select
    pos: Position


type Rule = Define | DiagramRule | CheckRule | QueryRule
