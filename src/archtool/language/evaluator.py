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

"""Evaluating resolved expressions and conditions against a model.

At run time, an expression produces either a set of elements (a frozenset of identifiers) or a tuple of
values. Navigation applied to a set navigates from every element, and combines the results. Comparisons of
values hold if any value on the left and any value on the right compare as required.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from archtool.formats.datatypes import ListType, RefType
from archtool.formats.values import Float
from archtool.identifiers import identifier_key
from archtool.language.resolver import Program
from archtool.language.syntax import (
    And,
    Between,
    Call,
    Compare,
    Condition,
    ConditionCall,
    Count,
    DefinitionCall,
    ElementRef,
    EnumValue,
    Expression,
    FromTo,
    In,
    IsEmpty,
    ListLiteral,
    Literal,
    Message,
    Name,
    Navigate,
    Not,
    Or,
    Quantifier,
    SetOperation,
    TextMatch,
    This,
    TypeRef,
    Variable,
    Where,
)
from archtool.metamodel import Stereotype
from archtool.model import Element, Model

type ElementSet = frozenset[str]
type ValueList = tuple[object, ...]
type Result = ElementSet | ValueList

EMPTY: ElementSet = frozenset()


@dataclass(frozen=True, slots=True)
class Env:
    variables: dict[str, Result]
    this: str | None = None

    def bind(self, name: str, value: Result) -> "Env":
        return Env({**self.variables, name: value}, self.this)

    def with_this(self, this: str) -> "Env":
        return Env(self.variables, this)


class Evaluator:
    def __init__(self, program: Program, model: Model, label: Callable[[str], str] | None = None) -> None:
        self.program = program
        self.model = model
        self.metamodel = model.metamodel
        # Shows an element in a message; by default its identifier.
        self.label = label if label is not None else (lambda identifier: identifier)
        self._parents: dict[str, list[tuple[str, str]]] = {}
        self._children: dict[str, list[tuple[str, str]]] = {}
        for relationship in model.elements_of("HierarchyRelationship"):
            parent, child = relationship.values.get("parent"), relationship.values.get("child")
            if isinstance(parent, str) and isinstance(child, str):
                self._parents.setdefault(child, []).append((relationship.type, parent))
                self._children.setdefault(parent, []).append((relationship.type, child))
        self._columns = {name: {c.name: c for c in self.metamodel.columns(name)} for name in self.metamodel.types}

    # --- Expressions ---------------------------------------------------------------------------------------

    def expression(self, expression: Expression, env: Env) -> Result:
        match expression:
            case TypeRef(_, types):
                return frozenset(e.id for name in types for e in self.model.elements_of(name, include_subtypes=False))
            case ElementRef(identifier):
                return frozenset((identifier,)) if identifier in self.model else EMPTY
            case Variable(ident):
                return env.variables[ident]
            case This():
                assert env.this is not None
                return frozenset((env.this,))
            case Literal(value) | EnumValue(value):
                return (value,)
            case ListLiteral(items):
                results = [self.expression(item, env) for item in items]
                if results and all(isinstance(r, frozenset) for r in results):
                    return frozenset(i for r in results if isinstance(r, frozenset) for i in r)
                return tuple(v for r in results for v in _values(r))
            case Count(counted):
                return (len(self.expression(counted, env)),)
            case DefinitionCall(ident, arguments):
                body = self.program.defines[ident].rule.body
                assert not isinstance(body, (Compare, In, IsEmpty, TextMatch, Quantifier, ConditionCall, And, Or, Not))
                return self.expression(body, self.definition_env(ident, arguments, env))
            case Navigate(source, step, arguments):
                elements = self.elements(self.expression(source, env))
                argument: Result | None = None
                if arguments and isinstance(arguments[0], TypeRef):
                    argument = arguments[0].types  # A type argument, e.g. `covers` in `.sources(covers)`
                elif arguments:
                    argument = self.expression(arguments[0], env)
                return _combine(self.step(identifier, step, argument) for identifier in _sorted(elements))
            case SetOperation(op, left, right):
                left_set = self.elements(self.expression(left, env))
                right_set = self.elements(self.expression(right, env))
                if op == "union":
                    return left_set | right_set
                if op == "intersect":
                    return left_set & right_set
                return left_set - right_set
            case Between(relation, other):
                relationships = self.elements(self.expression(relation, env))
                ends = self.elements(self.expression(other, env))
                return frozenset(r for r in relationships if self.end_owner(r, "start") in ends and self.end_owner(r, "end") in ends)
            case FromTo(relation, origin, target):
                relationships = self.elements(self.expression(relation, env))
                origins = self.elements(self.expression(origin, env)) if origin is not None else None
                targets = self.elements(self.expression(target, env)) if target is not None else None
                return frozenset(
                    r for r in relationships
                    if (origins is None or self.end_owner(r, "start") in origins)
                    and (targets is None or self.end_owner(r, "end") in targets)
                )  # fmt: skip
            case Where(source, condition):
                elements = self.elements(self.expression(source, env))
                return frozenset(e for e in elements if self.condition(condition, env.with_this(e)))
            case Name() | Call():
                raise AssertionError("unresolved expression")

    def elements(self, result: Result) -> ElementSet:
        return result if isinstance(result, frozenset) else EMPTY

    def definition_env(self, ident: str, arguments: tuple[Expression, ...], env: Env) -> Env:
        parameters = self.program.defines[ident].rule.parameters
        variables: dict[str, Result] = {}
        for index, parameter in enumerate(parameters):
            if index < len(arguments):
                variables[parameter.ident] = self.expression(arguments[index], env)
            elif parameter.default is not None:
                variables[parameter.ident] = (parameter.default.value,)
        return Env(variables)

    # --- Navigation ----------------------------------------------------------------------------------------

    def step(self, identifier: str, step: str, argument: Result | None) -> Result:
        element = self.model.get(identifier)
        if step == "type":
            return (element.type,)
        if step == "id":
            return (identifier,)
        column = self._columns[element.type].get(step)
        if column is not None:
            value = element.values.get(step)
            is_reference = isinstance(column.datatype, RefType) or (
                isinstance(column.datatype, ListType) and isinstance(column.datatype.element, RefType)
            )
            items = () if value is None else value if isinstance(value, tuple) else (value,)
            if is_reference:
                return frozenset(str(item) for item in items if str(item) in self.model)
            return tuple(items)
        types = argument if isinstance(argument, frozenset) else None
        match step:
            case "parent":
                return frozenset(parent for _, parent in self._parents.get(identifier, ()))
            case "ancestors":
                return self._closure(identifier, lambda e: [p for _, p in self._parents.get(e, ())])
            case "children":
                return frozenset(child for h, child in self._children.get(identifier, ()) if types is None or h in types)
            case "descendants":
                depth = _number(argument) if argument is not None else None
                return self._closure(identifier, lambda e: [c for _, c in self._children.get(e, ())], depth)
            case "ports":
                return frozenset(
                    r.source for r in self.model.referrers(identifier)
                    if r.column == "owner" and self._is(r.source, Stereotype.PORT) and _of_type(self.model.get(r.source), types)
                )  # fmt: skip
            case "owner":
                return frozenset((identifier,))
            case "outgoing" | "incoming":
                return self._relationships(identifier, "start" if step == "outgoing" else "end", types)
            case "targets":
                return frozenset(self.end_owner(r, "end") for r in self._relationships(identifier, "start", types))
            case "sources":
                return frozenset(self.end_owner(r, "start") for r in self._relationships(identifier, "end", types))
            case "reachable":
                return self._closure(
                    identifier, lambda e: [self.end_owner(r, "end") for r in self._relationships(e, "start", types)]
                )
            case "refines" | "refined_by":
                near, far = ("start", "end") if step == "refines" else ("end", "start")
                refinements = [r for r in self._relationships(identifier, near, None) if self._is(r, Stereotype.REFINEMENT)]
                return frozenset(self.end_owner(r, far) for r in refinements)
            case "instances":
                return frozenset(r.source for r in self.model.referrers(identifier) if r.column == "template")
            case "constituents" | "aggregate":
                near, far = ("aggregate", "constituent") if step == "constituents" else ("constituent", "aggregate")
                breakdowns = [r.source for r in self.model.referrers(identifier) if r.column == near]
                return frozenset(str(self.model.get(b).values[far]) for b in breakdowns if far in self.model.get(b).values)
            case "chains":
                return frozenset(
                    r.source for r in self.model.referrers(identifier)
                    if r.column == "relationships" and _of_type(self.model.get(r.source), types)
                )  # fmt: skip
        return EMPTY

    def _relationships(self, identifier: str, end: str, types: ElementSet | None) -> ElementSet:
        """The relationships whose `end` ("start" or "end") is the element or one of its ports."""
        ends = [identifier]
        if not self._is(identifier, Stereotype.PORT):
            ends += [r.source for r in self.model.referrers(identifier) if r.column == "owner"]
        return frozenset(
            r.source for e in ends for r in self.model.referrers(e)
            if r.column == end and self._is(r.source, Stereotype.RELATIONSHIP) and _of_type(self.model.get(r.source), types)
        )  # fmt: skip

    def end_owner(self, relationship: str, end: str) -> str:
        """The entity at an end of a relationship: the owner of a port, or the entity itself."""
        value = self.model.get(relationship).values.get(end)
        if not isinstance(value, str) or value not in self.model:
            return ""
        if self._is(value, Stereotype.PORT):
            owner = self.model.get(value).values.get("owner")
            return owner if isinstance(owner, str) else ""
        return value

    def _is(self, identifier: str, stereotype: Stereotype) -> bool:
        return stereotype in self.metamodel.types[self.model.get(identifier).type].stereotype.chain()

    @staticmethod
    def _closure(start: str, next_of: Callable[[str], list[str]], depth: int | None = None) -> ElementSet:
        result: set[str] = set()
        frontier = [start]
        level = 0
        while frontier and (depth is None or level < depth):
            level += 1
            following = [n for e in frontier for n in next_of(e) if n not in result]
            result.update(following)
            frontier = following
        return frozenset(result)

    # --- Conditions ----------------------------------------------------------------------------------------

    def condition(self, condition: Condition, env: Env) -> bool:
        match condition:
            case Compare(op, left, right):
                left_result, right_result = self.expression(left, env), self.expression(right, env)
                if isinstance(left_result, frozenset) and isinstance(right_result, frozenset):
                    return (left_result == right_result) == (op == "=")
                if op == "!=":
                    return not _any_compare("=", _values(left_result), _values(right_result))
                return _any_compare(op, _values(left_result), _values(right_result))
            case In(left, right):
                left_result, right_result = self.expression(left, env), self.expression(right, env)
                if isinstance(left_result, frozenset) and isinstance(right_result, frozenset):
                    return left_result <= right_result
                right_values = [_comparable(v) for v in _values(right_result)]
                return all(_comparable(v) in right_values for v in _values(left_result))
            case IsEmpty(value, negated):
                return (len(self.expression(value, env)) == 0) != negated
            case TextMatch(op, value, pattern):
                texts = [_display(v) for v in _values(self.expression(value, env))]
                if op == "contains":
                    return any(pattern.casefold() in text.casefold() for text in texts)
                return any(re.search(pattern, text) is not None for text in texts)
            case Quantifier(quantifier, var, source, inner):
                elements = _sorted(self.elements(self.expression(source, env)))
                outcomes = (self.condition(inner, env.bind(var, frozenset((e,)))) for e in elements)
                if quantifier == "every":
                    return all(outcomes)
                if quantifier == "some":
                    return any(outcomes)
                return not any(outcomes)
            case ConditionCall(ident, arguments):
                body = self.program.defines[ident].rule.body
                assert isinstance(body, (Compare, In, IsEmpty, TextMatch, Quantifier, ConditionCall, And, Or, Not))
                return self.condition(body, self.definition_env(ident, arguments, env))
            case And(operands):
                return all(self.condition(c, env) for c in operands)
            case Or(operands):
                return any(self.condition(c, env) for c in operands)
            case Not(operand):
                return not self.condition(operand, env)

    # --- Messages ------------------------------------------------------------------------------------------

    def message(self, message: Message, env: Env) -> str:
        return "".join(part if isinstance(part, str) else self.text(self.expression(part, env)) for part in message.parts)

    def text(self, result: Result) -> str:
        if isinstance(result, frozenset):
            return ", ".join(self.label(identifier) for identifier in _sorted(result))
        return ", ".join(_display(value) for value in result)


def _of_type(element: Element, types: ElementSet | None) -> bool:
    return types is None or element.type in types


def _sorted(elements: Iterable[str]) -> list[str]:
    return sorted(elements, key=identifier_key)


def _values(result: Result) -> ValueList:
    if isinstance(result, frozenset):
        return tuple(_sorted(result))
    return result


def _combine(results: Iterable[Result]) -> Result:
    collected = list(results)
    if any(isinstance(r, tuple) for r in collected):
        return tuple(v for r in collected for v in _values(r))
    return frozenset(i for r in collected if isinstance(r, frozenset) for i in r)


def _number(result: Result) -> int:
    values = _values(result)
    value = _comparable(values[0]) if values else 0
    return int(value) if isinstance(value, (int, float)) else 0


def _comparable(value: object) -> object:
    if isinstance(value, Float):
        return value.value()
    return value


def _any_compare(op: str, left: ValueList, right: ValueList) -> bool:
    for a in left:
        for b in right:
            if _compare(op, _comparable(a), _comparable(b)):
                return True
    return False


def _compare(op: str, a: object, b: object) -> bool:
    if op == "=":
        return a == b
    numbers = (int, float)
    if not (isinstance(a, numbers) and isinstance(b, numbers)) or isinstance(a, bool) or isinstance(b, bool):
        return False
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    return a >= b


def _display(value: object) -> str:
    if isinstance(value, Float):
        return value.text
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
