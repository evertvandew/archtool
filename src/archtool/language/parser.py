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

"""Parsing rules and expressions into the syntax tree of archtool.language.syntax."""

import re
from functools import cache
from typing import Any

from tatsu.exceptions import FailedParse
from tatsu.semantics import ModelBuilderSemantics

from archtool.errors import FormatError
from archtool.language._parser import SelectionParser
from archtool.language.blocks import mark_blocks
from archtool.language.syntax import (
    And,
    Between,
    Call,
    CheckRule,
    Compare,
    Condition,
    ConditionCall,
    Define,
    DiagramRule,
    Expression,
    ForEach,
    FromTo,
    In,
    IsEmpty,
    Let,
    ListLiteral,
    Literal,
    Message,
    Name,
    Navigate,
    Not,
    Or,
    Parameter,
    Position,
    Quantifier,
    QueryRule,
    Require,
    Rule,
    Select,
    SetOperation,
    Show,
    TextMatch,
    This,
    Where,
)

# A node of TatSu's syntax tree: a typed node (see archtool.language.grammar), a list, a string or None.
type _Node = object

_STRING_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "{": "{", "}": "}"}


@cache
def _parser() -> Any:
    return SelectionParser()


def parse_rules(text: str, path: str, first_line: int = 1) -> list[Rule]:
    """Parse the text of a `@rules` section, which starts at `first_line` of `path`. Raises FormatError."""
    marked = mark_blocks(text, path, first_line)
    tree = _parse(marked, "start", path, first_line, 1)
    converter = _Converter(marked, path, first_line, 1)
    return [converter.rule(node) for node in _list(_get(tree, "rules"))]


def parse_expression(text: str, path: str, line: int = 1, column: int = 1) -> Expression:
    """Parse a single expression, e.g. from the command line, a message or a label. Raises FormatError."""
    tree = _parse(text, "expression_start", path, line, column)
    return _Converter(text, path, line, column).expression(tree)


def parse_message(text: str, pos: Position) -> Message:
    """Split a text into literal parts and `{…}` interpolations. `pos` is the position of its first character."""
    parts: list[str | Expression] = []
    index = 0
    for match in re.finditer(r"\{([^{}]*)\}", text):
        if match.start() > index:
            parts.append(text[index : match.start()])
        parts.append(parse_expression(match.group(1), pos.path, pos.line, pos.column + match.start(1)))
        index = match.end()
    if index < len(text):
        parts.append(text[index:])
    return Message(tuple(parts), pos)


def unescape_string(token: str) -> str:
    """The text of a string token, without the quotes, and with escape sequences replaced."""
    body = token[1:-1]
    result: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            result.append(_STRING_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            result.append(body[i])
            i += 1
    return "".join(result)


def _parse(text: str, start: str, path: str, line: int, column: int) -> _Node:
    try:
        return _parser().parse(text, start=start, parseinfo=True, semantics=ModelBuilderSemantics())
    except FailedParse as error:
        error_line, error_column = _line_and_column(text, error.pos)
        if error_line == 1:
            error_column += column - 1
        message = str(error.message).strip().removeprefix("error: ")
        raise FormatError(path, line + error_line - 1, error_column, message) from None


def _line_and_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    column = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, column


def _kind(node: _Node) -> str:
    """The node type of a node, as named in the grammar."""
    return type(node).__name__


def _get(node: _Node, field: str) -> _Node:
    return getattr(node, field, None)


def _list(node: _Node) -> list[_Node]:
    if node is None:
        return []
    if isinstance(node, (list, tuple)):
        return list(node)
    return [node]


def _str(node: _Node) -> str:
    assert isinstance(node, str), node
    return node


class _Converter:
    """Converts TatSu's syntax tree into the nodes of archtool.language.syntax."""

    def __init__(self, text: str, path: str, line: int, column: int) -> None:
        self.text = text
        self.path = path
        self.line = line
        self.column = column

    def pos(self, node: _Node) -> Position:
        info = _get(node, "parseinfo")
        offset = getattr(info, "pos", 0)
        while offset < len(self.text) and self.text[offset] in " \t\n{":
            offset += 1
        line, column = _line_and_column(self.text, offset)
        if line == 1:
            column += self.column - 1
        return Position(self.path, self.line + line - 1, column)

    # --- Rules -------------------------------------------------------------------------------------------

    def rule(self, node: _Node) -> Rule:
        ident = _str(_get(node, "ident"))
        parameters = tuple(self.parameter(p) for p in _list(_get(_get(node, "params"), "entries")))
        pos = self.pos(node)
        match _kind(node):
            case "Define":
                body = _get(node, "body")
                converted: Expression | Condition = (
                    self.condition(body) if _kind(body) == "Or" else self.expression(body)
                )
                return Define(ident, parameters, converted, pos)
            case "Diagram":
                statements = tuple(self.diagram_statement(s) for s in _list(_get(node, "statements")))
                return DiagramRule(ident, parameters, statements, pos)
            case "Check":
                lets = tuple(self.let(s) for s in _list(_get(node, "lets")))
                foreach = self.foreach(_get(node, "foreach"))
                return CheckRule(ident, parameters, _str(_get(node, "severity")), lets, foreach, pos)
            case "Query":
                lets = tuple(self.let(s) for s in _list(_get(node, "lets")))
                return QueryRule(ident, parameters, lets, self.select(_get(node, "select")), pos)
        raise AssertionError(f"unknown rule {_kind(node)}")

    def parameter(self, node: _Node) -> Parameter:
        default = _get(node, "default")
        literal = self.expression(default) if default is not None else None
        assert literal is None or isinstance(literal, Literal)
        return Parameter(_str(_get(node, "ident")), _str(_get(node, "type")), literal, self.pos(node))

    def diagram_statement(self, node: _Node) -> Let | Show:
        if _kind(node) == "Let":
            return self.let(node)
        return Show(self.expression(_get(node, "value")), self.pos(node))

    def let(self, node: _Node) -> Let:
        return Let(_str(_get(node, "var")), self.expression(_get(node, "value")), self.pos(node))

    def foreach(self, node: _Node) -> ForEach:
        statements: list[Let | Require] = []
        for statement in _list(_get(node, "statements")):
            if _kind(statement) == "Let":
                statements.append(self.let(statement))
            else:
                message_node = _get(statement, "message")
                token_pos = self.pos(message_node)
                text_pos = Position(token_pos.path, token_pos.line, token_pos.column + 1)
                message = parse_message(unescape_string(_str(_get(message_node, "value"))), text_pos)
                statements.append(Require(self.condition(_get(statement, "condition")), message, self.pos(statement)))
        return ForEach(_str(_get(node, "var")), self.expression(_get(node, "source")), tuple(statements), self.pos(node))

    def select(self, node: _Node) -> Select:
        columns = tuple(self.expression(c) for c in _list(_get(node, "columns")))
        order = _get(node, "order")
        return Select(
            self.expression(_get(node, "source")),
            columns,
            self.expression(_get(order, "key")) if order is not None else None,
            _kind(order) == "DescendingOrder",
            self.pos(node),
        )

    # --- Expressions -------------------------------------------------------------------------------------

    def expression(self, node: _Node) -> Expression:
        pos = self.pos(node)
        match _kind(node):
            case "Expression":
                source = self.expression(_get(node, "source"))
                condition = _get(node, "condition")
                return source if condition is None else Where(source, self.condition(condition), pos)
            case "SetExpression":
                result = self.expression(_get(node, "first"))
                for operation in _list(_get(node, "rest")):
                    operand = self.expression(_get(operation, "operand"))
                    result = SetOperation(_str(_get(operation, "op")), result, operand, pos)
                return result
            case "RelationExpression":
                relation = self.expression(_get(node, "subject"))
                tail = _get(node, "tail")
                if tail is None:
                    return relation
                if _kind(tail) == "Between":
                    return Between(relation, self.expression(_get(tail, "other")), pos)
                origin, target = _get(tail, "origin"), _get(tail, "target")
                return FromTo(
                    relation,
                    self.expression(origin) if origin is not None else None,
                    self.expression(target) if target is not None else None,
                    pos,
                )
            case "Path":
                result = self.expression(_get(node, "base"))
                for step in _list(_get(node, "steps")):
                    arguments = _get(step, "arguments")
                    converted = tuple(self.expression(a) for a in _list(arguments)) if arguments is not None else None
                    result = Navigate(result, _str(_get(step, "ident")), converted, self.pos(step))
                return result
            case "This":
                return This(pos)
            case "List":
                return ListLiteral(tuple(self.expression(item) for item in _list(_get(node, "elements"))), pos)
            case "Group":
                return self.expression(_get(node, "inner"))
            case "Call":
                arguments = tuple(self.expression(a) for a in _list(_get(node, "arguments")))
                return Call(_str(_get(node, "ident")), arguments, pos)
            case "Name":
                return Name(_str(_get(node, "ident")), pos)
            case "String":
                return Literal(unescape_string(_str(_get(node, "value"))), pos)
            case "Number":
                text = _str(_get(node, "value"))
                return Literal(float(text) if "." in text else int(text), pos)
            case "Boolean":
                return Literal(_get(node, "value") == "true", pos)
        raise AssertionError(f"unknown expression {_kind(node)}")

    # --- Conditions --------------------------------------------------------------------------------------

    def condition(self, node: _Node) -> Condition:
        pos = self.pos(node)
        match _kind(node):
            case "Or" | "And":
                operands = [_get(node, "first"), *_list(_get(node, "rest"))]
                converted = tuple(self.condition(operand) for operand in operands)
                if len(converted) == 1:
                    return converted[0]
                return Or(converted, pos) if _kind(node) == "Or" else And(converted, pos)
            case "Not":
                return Not(self.condition(_get(node, "inner")), pos)
            case "Quantifier":
                return Quantifier(
                    _str(_get(node, "which")),
                    _str(_get(node, "var")),
                    self.expression(_get(node, "source")),
                    self.condition(_get(node, "inner")),
                    pos,
                )
            case "Test":
                left = self.expression(_get(node, "left"))
                test = _get(node, "tail")
                match _kind(test):
                    case "Compare":
                        return Compare(_str(_get(test, "op")), left, self.expression(_get(test, "right")), pos)
                    case "In":
                        return In(left, self.expression(_get(test, "right")), pos)
                    case "IsEmpty" | "IsNotEmpty":
                        return IsEmpty(left, _kind(test) == "IsNotEmpty", pos)
                    case _:
                        pattern = unescape_string(_str(_get(test, "pattern")))
                        return TextMatch(_str(_get(test, "op")), left, pattern, pos)
            case "GroupCondition":
                return self.condition(_get(node, "inner"))
            case "CallCondition":
                arguments = tuple(self.expression(a) for a in _list(_get(node, "arguments")))
                return ConditionCall(_str(_get(node, "ident")), arguments, pos)
        raise AssertionError(f"unknown condition {_kind(node)}")
