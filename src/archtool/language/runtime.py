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

"""Running the rules of a meta model against a model: verification rules, queries, generation rules and labels."""

from dataclasses import dataclass, field

from archtool.errors import FormatError
from archtool.formats.values import Argument, Float, Parameter
from archtool.identifiers import identifier_key, split_identifier
from archtool.language.evaluator import ElementSet, Env, Evaluator, Result
from archtool.language.parser import parse_expression, parse_message, parse_rules
from archtool.language.resolver import Elements, Program, ResolveError, Resolver, Scope, StaticType, Values
from archtool.language.syntax import Expression, Let, Message, Navigate, Parameter as RuleParameter, Position, Rule, Variable
from archtool.metamodel import MetaModel
from archtool.model import Model


@dataclass(frozen=True, slots=True)
class ResolvedLabel:
    diagram_type: str | None
    type: str
    message: Message
    anchor: str | None


@dataclass(slots=True)
class Rules:
    """The resolved rules and labels of a meta model. Errors in them are collected in `errors`."""

    metamodel: MetaModel
    program: Program
    labels: list[ResolvedLabel] = field(default_factory=list)

    @property
    def errors(self) -> list[FormatError]:
        return self.program.errors


def load_rules(metamodel: MetaModel) -> Rules:
    """Parse and resolve the rules and labels of a meta model."""
    rules: list[Rule] = []
    errors: list[FormatError] = []
    for section in metamodel.rules:
        try:
            rules += parse_rules(section.text, metamodel.path, section.line)
        except FormatError as error:
            errors.append(error)
    resolver = Resolver(metamodel, rules)
    program = resolver.resolve(rules)
    program.errors[:0] = errors
    result = Rules(metamodel, program)
    for label in metamodel.labels:
        try:
            message = parse_message(label.text, Position(metamodel.path, label.line, 1))
            result.labels.append(ResolvedLabel(label.diagram_type, label.type, resolver.label(message, label.type), label.anchor))
        except FormatError as error:
            program.errors.append(error)
        except ResolveError as error:
            program.errors.append(error.format_error())
    return result


@dataclass(frozen=True, slots=True)
class CheckResult:
    severity: str
    rule: str
    element: str
    message: str


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]

    def records(self) -> list[dict[str, object]]:
        return [dict(zip(self.columns, row)) for row in self.rows]


class RuleError(Exception):
    """An error in using a rule, e.g. an unknown rule or a wrong argument."""


class Runner:
    def __init__(self, rules: Rules, model: Model) -> None:
        self.rules = rules
        self.program = rules.program
        self.model = model
        self._plain = Evaluator(self.program, model)
        self.evaluator = Evaluator(self.program, model, self.default_label)

    # --- Labels --------------------------------------------------------------------------------------------

    def default_label(self, identifier: str) -> str:
        """The default label of an element, or its identifier if it has none."""
        labels = self.labels(identifier, None)
        text = self._plain.message(labels[0].message, Env({}, identifier)) if labels else ""
        return text if text.strip() else identifier

    def label_texts(self, identifier: str, diagram_type: str | None) -> list[tuple[str, str | None]]:
        """The texts and anchors of the labels of an element in a diagram type. Elements inside a label are shown
        by their identifiers."""
        return [
            (self._plain.message(label.message, Env({}, identifier)), label.anchor)
            for label in self.labels(identifier, diagram_type)
        ]

    def labels(self, identifier: str, diagram_type: str | None) -> list[ResolvedLabel]:
        """The labels of an element in a diagram type (None: the default labels), from the most specific type or
        stereotype that has any."""
        element = self.model.get(identifier)
        metamodel = self.rules.metamodel
        owners = list(reversed(metamodel.ancestors(element.type)))
        owners += [s.value for s in reversed(metamodel.types[element.type].stereotype.chain())]
        for owner in owners:
            found = [label for label in self.rules.labels if label.type == owner and label.diagram_type == diagram_type]
            if found:
                return found
        return [] if diagram_type is None else self.labels(identifier, None)

    # --- Verification rules --------------------------------------------------------------------------------

    def checks(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        for rule in self.program.checks.values():
            env = self._parameters(rule.ident, rule.parameters, ())
            for let in rule.lets:
                env = env.bind(let.var, self.evaluator.expression(let.value, env))
            source = self.evaluator.elements(self.evaluator.expression(rule.foreach.source, env))
            for identifier in sorted(source, key=identifier_key):
                element_env = env.bind(rule.foreach.var, frozenset((identifier,)))
                for statement in rule.foreach.statements:
                    if isinstance(statement, Let):
                        element_env = element_env.bind(statement.var, self.evaluator.expression(statement.value, element_env))
                    elif not self.evaluator.condition(statement.condition, element_env):
                        message = self.evaluator.message(statement.message, element_env)
                        results.append(CheckResult(rule.severity, rule.ident, identifier, message))
        return results

    # --- Queries -------------------------------------------------------------------------------------------

    def query(self, name: str, arguments: tuple[tuple[str, str], ...] = ()) -> QueryResult:
        rule = self.program.queries.get(name)
        if rule is None:
            raise RuleError(f"unknown query '{name}'")
        env = self._parameters(name, rule.parameters, arguments)
        for let in rule.lets:
            env = env.bind(let.var, self.evaluator.expression(let.value, env))
        select = rule.select
        elements = sorted(self.evaluator.elements(self.evaluator.expression(select.source, env)), key=identifier_key)
        if select.order is not None:
            order = select.order
            keyed = [(self._sort_key(self.evaluator.expression(order, env.with_this(e))), e) for e in elements]
            keyed.sort(key=lambda pair: pair[0], reverse=select.descending)
            elements = [e for _, e in keyed]
        if not select.columns:
            return self._default_rows(elements)
        names = tuple(_column_name(column, index) for index, column in enumerate(select.columns, 1))
        rows = tuple(
            tuple(self._json(self.evaluator.expression(column, env.with_this(e))) for column in select.columns)
            for e in elements
        )
        return QueryResult(names, rows)

    def expression(self, text: str) -> QueryResult:
        """Evaluate an expression given on the command line: elements are listed with their default labels."""
        expression = parse_expression(text, "<expression>")
        resolver = Resolver(self.rules.metamodel, [d.rule for d in self.program.defines.values()])
        resolver.program.defines.update(self.program.defines)
        try:
            resolved, static_type = resolver.expression(expression, Scope({}))
        except ResolveError as error:
            raise error.format_error() from None
        result = self.evaluator.expression(resolved, Env({}))
        if isinstance(static_type, Elements) and isinstance(result, frozenset):
            return self._default_rows(sorted(result, key=identifier_key))
        return QueryResult(("value",), tuple((self._json((value,)),) for value in result))

    def _default_rows(self, elements: list[str]) -> QueryResult:
        return QueryResult(("id", "label"), tuple((e, self.default_label(e)) for e in elements))

    # --- Generation rules ----------------------------------------------------------------------------------

    def generate(self, name: str, arguments: tuple[tuple[str, str], ...] = ()) -> ElementSet:
        """The elements shown by a generated diagram."""
        rule = self.program.diagrams.get(name)
        if rule is None:
            raise RuleError(f"unknown generation rule '{name}'")
        env = self._parameters(name, rule.parameters, arguments)
        shown: set[str] = set()
        for statement in rule.statements:
            value = self.evaluator.expression(statement.value, env)
            if isinstance(statement, Let):
                env = env.bind(statement.var, value)
            else:
                shown |= self.evaluator.elements(value)
        return frozenset(shown)

    # --- Helpers -------------------------------------------------------------------------------------------

    def _parameters(self, rule: str, parameters: tuple[RuleParameter, ...], arguments: tuple[tuple[str, str], ...]) -> Env:
        given = dict(arguments)
        unknown = set(given) - {p.ident for p in parameters}
        if unknown:
            raise RuleError(f"'{rule}' has no parameter '{sorted(unknown)[0]}'")
        types = self.program.parameter_types.get(rule, ())
        variables: dict[str, Result] = {}
        for parameter, static_type in zip(parameters, types):
            if parameter.ident in given:
                variables[parameter.ident] = self._argument(rule, parameter.ident, given[parameter.ident], static_type)
            elif parameter.default is not None:
                variables[parameter.ident] = (parameter.default.value,)
            else:
                raise RuleError(f"'{rule}' needs a value for parameter '{parameter.ident}'")
        return Env(variables)

    def _argument(self, rule: str, name: str, text: str, static_type: StaticType) -> Result:
        text = text.strip()
        if isinstance(static_type, Elements):
            if split_identifier(text) is None or text not in self.model:
                raise RuleError(f"'{rule}': {name}={text} is not an element of the model")
            if self.model.get(text).type not in static_type.types:
                raise RuleError(f"'{rule}': {name}={text} is a {self.model.get(text).type}")
            return frozenset((text,))
        assert isinstance(static_type, Values)
        if static_type.kind == "number":
            try:
                return (float(text) if "." in text else int(text),)
            except ValueError:
                raise RuleError(f"'{rule}': {name}={text} is not a number") from None
        if static_type.kind == "bool":
            if text not in ("true", "false"):
                raise RuleError(f"'{rule}': {name}={text} is not true or false")
            return (text == "true",)
        if len(text) >= 2 and text[0] == text[-1] == '"':
            text = text[1:-1]
        return (text,)

    def _sort_key(self, result: Result) -> tuple[int, object]:
        values = sorted(result, key=identifier_key) if isinstance(result, frozenset) else list(result)
        if not values:
            return (1, "")
        first = values[0]
        if isinstance(first, Float):
            return (0, first.value())
        if isinstance(first, (int, float)) and not isinstance(first, bool):
            return (0, first)
        return (0, str(first))

    def _json(self, result: Result) -> object:
        """A value for JSON output: a single value, a list of values, or None."""
        values = sorted(result, key=identifier_key) if isinstance(result, frozenset) else [_json_scalar(v) for v in result]
        if not values:
            return None
        return values[0] if len(values) == 1 else values


def _json_scalar(value: object) -> object:
    if isinstance(value, Float):
        return value.value()
    if isinstance(value, Parameter):
        return value.name
    if isinstance(value, Argument):
        return f"{value.name}={value.text}"
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _column_name(column: Expression, index: int) -> str:
    if isinstance(column, Navigate):
        return column.step
    if isinstance(column, Variable):
        return column.ident
    return f"column_{index}"
