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

"""Checking rules against a meta model, and resolving names.

The resolver gives every expression a static type: a set of elements of known types, or values of a known
kind. It reports unknown names (with suggestions), navigations that do not apply, mismatched comparisons,
ambiguous names inside `where`, and recursive definitions. It replaces bare names and calls by the resolved
nodes of archtool.language.syntax, which the evaluator works on.

See "Static checking" in doc/selection_language.md.
"""

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from archtool.errors import FormatError
from archtool.formats.datatypes import DataType, EnumType, ListType, RefType, SimpleType
from archtool.identifiers import split_identifier
from archtool.language.syntax import (
    And,
    Between,
    Call,
    CheckRule,
    Compare,
    Condition,
    ConditionCall,
    Count,
    Define,
    DefinitionCall,
    DiagramRule,
    ElementRef,
    EnumValue,
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
    TypeRef,
    Variable,
    Where,
)
from archtool.metamodel import MetaModel, Stereotype

# --- Static types -------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Elements:
    """A set of elements, of (some of) the given types."""

    types: frozenset[str]


@dataclass(frozen=True, slots=True)
class Values:
    """Values of a kind: "text", "number", "bool", "enum" (with its values), or "other"."""

    kind: str
    enum: tuple[str, ...] = ()


type StaticType = Elements | Values

CONDITION = "condition"  # The type of a definition whose body is a condition.

_TEXT_KINDS = {"id", "ident", "str", "text"}
_NUMBER_KINDS = {"int", "float"}

# Navigations defined by the core model, besides the core attributes of elements.
NAVIGATIONS = frozenset(
    {
        "parent", "children", "descendants", "ancestors", "ports", "owner", "outgoing", "incoming", "targets",
        "sources", "reachable", "refines", "refined_by", "instances", "constituents", "aggregate", "chains",
        "type", "id",
    }
)  # fmt: skip

# Navigations that take a type as argument, with the stereotype of that type.
_TYPE_ARGUMENTS = {
    "children": Stereotype.HIERARCHY_RELATIONSHIP,
    "ports": Stereotype.PORT,
    "outgoing": Stereotype.RELATIONSHIP,
    "incoming": Stereotype.RELATIONSHIP,
    "targets": Stereotype.RELATIONSHIP,
    "sources": Stereotype.RELATIONSHIP,
    "reachable": Stereotype.RELATIONSHIP,
    "chains": Stereotype.CHAIN,
}


# --- Results ------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class ResolvedDefine:
    rule: Define
    type: StaticType | str  # CONDITION for a condition
    parameter_types: tuple[StaticType, ...]


@dataclass(slots=True)
class Program:
    """The resolved rules of a meta model."""

    defines: dict[str, ResolvedDefine] = field(default_factory=dict)
    diagrams: dict[str, DiagramRule] = field(default_factory=dict)
    checks: dict[str, CheckRule] = field(default_factory=dict)
    queries: dict[str, QueryRule] = field(default_factory=dict)
    # Parameter types of diagram rules and queries, by rule name.
    parameter_types: dict[str, tuple[StaticType, ...]] = field(default_factory=dict)
    errors: list[FormatError] = field(default_factory=list)


class ResolveError(Exception):
    def __init__(self, pos: Position, message: str) -> None:
        super().__init__(message)
        self.pos = pos
        self.message = message

    def format_error(self) -> FormatError:
        return FormatError(self.pos.path, self.pos.line, self.pos.column, self.message)


class _Reported(Exception):
    """Raised when a rule uses a definition whose errors have been reported already."""


@dataclass(frozen=True, slots=True)
class Scope:
    variables: dict[str, StaticType]
    this: Elements | None = None

    def bind(self, name: str, static_type: StaticType) -> "Scope":
        return Scope({**self.variables, name: static_type}, self.this)

    def with_this(self, this: Elements) -> "Scope":
        return Scope(self.variables, this)


# --- The resolver -------------------------------------------------------------------------------------------


class Resolver:
    def __init__(self, metamodel: MetaModel, rules: Sequence[Rule] = ()) -> None:
        self.metamodel = metamodel
        self.all_types = frozenset(metamodel.types)
        self.program = Program()
        self._defines = {rule.ident: rule for rule in rules if isinstance(rule, Define)}
        self._resolving: list[str] = []
        self._failed: set[str] = set()  # Definitions with errors, which have been reported already.

    # --- Programs ------------------------------------------------------------------------------------------

    def resolve(self, rules: Sequence[Rule]) -> Program:
        seen: dict[str, Rule] = {}
        for rule in rules:
            try:
                if rule.ident in seen:
                    raise ResolveError(rule.pos, f"'{rule.ident}' is defined more than once")
                seen[rule.ident] = rule
                match rule:
                    case Define():
                        self.define(rule.ident, rule.pos)
                    case DiagramRule():
                        self.program.diagrams[rule.ident] = self.diagram_rule(rule)
                    case CheckRule():
                        self.program.checks[rule.ident] = self.check_rule(rule)
                    case QueryRule():
                        self.program.queries[rule.ident] = self.query_rule(rule)
            except _Reported:
                pass
            except ResolveError as error:
                self.program.errors.append(error.format_error())
        return self.program

    def define(self, ident: str, pos: Position) -> ResolvedDefine:
        resolved = self.program.defines.get(ident)
        if resolved is not None:
            return resolved
        if ident in self._failed:
            raise _Reported()
        if ident in self._resolving:
            cycle = " → ".join([*self._resolving[self._resolving.index(ident) :], ident])
            raise ResolveError(pos, f"definitions cannot refer to themselves: {cycle}")
        rule = self._defines[ident]
        self._resolving.append(ident)
        try:
            parameter_types = tuple(self.parameter_type(p) for p in rule.parameters)
            scope = Scope({p.ident: t for p, t in zip(rule.parameters, parameter_types)})
            body: Expression | Condition
            static_type: StaticType | str
            if isinstance(rule.body, (Compare, In, IsEmpty, TextMatch, Quantifier, ConditionCall, And, Or, Not)):
                body = self.condition(rule.body, scope)
                static_type = CONDITION
            else:
                body, static_type = self.expression(rule.body, scope)
        except ResolveError:
            self._failed.add(ident)
            raise
        finally:
            self._resolving.pop()
        resolved = ResolvedDefine(Define(rule.ident, rule.parameters, body, rule.pos), static_type, parameter_types)
        self.program.defines[ident] = resolved
        return resolved

    def parameter_type(self, parameter: Parameter) -> StaticType:
        name = parameter.type
        if name in self.metamodel.types or self._is_stereotype(name):
            static_type: StaticType = Elements(self.subtypes(name))
        elif name in ("int", "float"):
            static_type = Values("number")
        elif name == "bool":
            static_type = Values("bool")
        elif name in ("text", "str"):
            static_type = Values("text")
        else:
            candidates = [*self.metamodel.types, "int", "float", "bool", "text"]
            raise ResolveError(parameter.pos, f"unknown type '{name}'{_suggestion(name, candidates)}")
        if parameter.default is not None:
            default_type = _literal_type(parameter.default)
            if not isinstance(static_type, Values) or not _compatible(static_type, default_type):
                raise ResolveError(parameter.default.pos, f"the default of '{parameter.ident}' must be a {name}")
        return static_type

    def parameters(self, rule_ident: str, parameters: tuple[Parameter, ...]) -> Scope:
        types = tuple(self.parameter_type(p) for p in parameters)
        self.program.parameter_types[rule_ident] = types
        return Scope({p.ident: t for p, t in zip(parameters, types)})

    def diagram_rule(self, rule: DiagramRule) -> DiagramRule:
        scope = self.parameters(rule.ident, rule.parameters)
        statements: list[Let | Show] = []
        for statement in rule.statements:
            if isinstance(statement, Let):
                let, scope = self.let(statement, scope)
                statements.append(let)
            else:
                value, static_type = self.expression(statement.value, scope)
                self.require_elements(static_type, statement.value, "show")
                statements.append(Show(value, statement.pos))
        return DiagramRule(rule.ident, rule.parameters, tuple(statements), rule.pos)

    def check_rule(self, rule: CheckRule) -> CheckRule:
        for parameter in rule.parameters:
            if parameter.default is None:
                raise ResolveError(parameter.pos, "the parameters of verification rules must have a default")
        scope = self.parameters(rule.ident, rule.parameters)
        lets: list[Let] = []
        for statement in rule.lets:
            let, scope = self.let(statement, scope)
            lets.append(let)
        source, source_type = self.expression(rule.foreach.source, scope)
        element_type = self.require_elements(source_type, rule.foreach.source, "for each")
        scope = scope.bind(rule.foreach.var, element_type)
        statements: list[Let | Require] = []
        for item in rule.foreach.statements:
            if isinstance(item, Let):
                resolved_let, scope = self.let(item, scope)
                statements.append(resolved_let)
            else:
                condition = self.condition(item.condition, scope)
                statements.append(Require(condition, self.message(item.message, scope), item.pos))
        foreach = ForEach(rule.foreach.var, source, tuple(statements), rule.foreach.pos)
        return CheckRule(rule.ident, rule.parameters, rule.severity, tuple(lets), foreach, rule.pos)

    def query_rule(self, rule: QueryRule) -> QueryRule:
        scope = self.parameters(rule.ident, rule.parameters)
        lets: list[Let] = []
        for statement in rule.lets:
            let, scope = self.let(statement, scope)
            lets.append(let)
        return QueryRule(rule.ident, rule.parameters, tuple(lets), self.select(rule.select, scope), rule.pos)

    def select(self, select: Select, scope: Scope) -> Select:
        source, source_type = self.expression(select.source, scope)
        element_type = self.require_elements(source_type, select.source, "select")
        row_scope = scope.with_this(element_type)
        columns = tuple(self.expression(column, row_scope)[0] for column in select.columns)
        order = self.expression(select.order, row_scope)[0] if select.order is not None else None
        return Select(source, columns, order, select.descending, select.pos)

    def let(self, let: Let, scope: Scope) -> tuple[Let, Scope]:
        value, static_type = self.expression(let.value, scope)
        return Let(let.var, value, let.pos), scope.bind(let.var, static_type)

    def message(self, message: Message, scope: Scope) -> Message:
        parts = tuple(part if isinstance(part, str) else self.expression(part, scope)[0] for part in message.parts)
        return Message(parts, message.pos)

    def label(self, message: Message, type_name: str) -> Message:
        """Resolve the text of a label, for elements of a type (or stereotype)."""
        return self.message(message, Scope({}, Elements(self.subtypes(type_name))))

    # --- Expressions ---------------------------------------------------------------------------------------

    def expression(self, expression: Expression, scope: Scope, enum: tuple[str, ...] = ()) -> tuple[Expression, StaticType]:
        match expression:
            case Name():
                return self.name(expression, scope, enum)
            case This(pos):
                if scope.this is None:
                    raise ResolveError(pos, "'this' can only be used inside 'where'")
                return expression, scope.this
            case Literal():
                return expression, _literal_type(expression)
            case ListLiteral(items, pos):
                resolved = [self.expression(item, scope, enum) for item in items]
                item_types = [t for _, t in resolved]
                if item_types and all(isinstance(t, Elements) for t in item_types):
                    return ListLiteral(tuple(e for e, _ in resolved), pos), Elements(
                        frozenset(name for t in item_types if isinstance(t, Elements) for name in t.types)
                    )
                if any(isinstance(t, Elements) for t in item_types):
                    raise ResolveError(pos, "a list cannot mix elements and values")
                first = item_types[0] if item_types else Values("other")
                return ListLiteral(tuple(e for e, _ in resolved), pos), first
            case Call():
                return self.call(expression, scope)
            case Navigate(source, step, arguments, pos):
                resolved_source, source_type = self.expression(source, scope)
                if not isinstance(source_type, Elements):
                    raise ResolveError(pos, f"'.{step}' cannot be applied to values, only to elements")
                return self.navigate(resolved_source, source_type, step, arguments, scope, pos)
            case SetOperation(op, left, right, pos):
                resolved_left, left_type = self.expression(left, scope)
                resolved_right, right_type = self.expression(right, scope)
                left_elements = self.require_elements(left_type, left, op)
                right_elements = self.require_elements(right_type, right, op)
                types = left_elements.types | right_elements.types
                return SetOperation(op, resolved_left, resolved_right, pos), Elements(types)
            case Between(relation, other, pos):
                resolved_relation, relation_type = self.relation(relation, scope)
                resolved_other, other_type = self.expression(other, scope)
                self.require_elements(other_type, other, "between")
                return Between(resolved_relation, resolved_other, pos), relation_type
            case FromTo(relation, origin, target, pos):
                resolved_relation, relation_type = self.relation(relation, scope)
                resolved_origin = self.ends(origin, scope, "from")
                resolved_target = self.ends(target, scope, "to")
                return FromTo(resolved_relation, resolved_origin, resolved_target, pos), relation_type
            case Where(source, condition, pos):
                resolved_source, source_type = self.expression(source, scope)
                elements = self.require_elements(source_type, source, "where")
                resolved_condition = self.condition(condition, scope.with_this(elements))
                return Where(resolved_source, resolved_condition, pos), elements
            case TypeRef() | ElementRef() | Variable() | EnumValue() | Count() | DefinitionCall():
                raise AssertionError("already resolved")

    def relation(self, relation: Expression, scope: Scope) -> tuple[Expression, Elements]:
        resolved, static_type = self.expression(relation, scope)
        elements = self.require_elements(static_type, relation, "between")
        for name in elements.types:
            if not self.metamodel.is_a(name, Stereotype.RELATIONSHIP.value):
                raise ResolveError(_pos(relation), f"'{name}' is not a relationship type")
        return resolved, elements

    def ends(self, expression: Expression | None, scope: Scope, keyword: str) -> Expression | None:
        if expression is None:
            return None
        resolved, static_type = self.expression(expression, scope)
        self.require_elements(static_type, expression, keyword)
        return resolved

    def name(self, name: Name, scope: Scope, enum: tuple[str, ...]) -> tuple[Expression, StaticType]:
        ident = name.ident
        variable = scope.variables.get(ident)
        member = self.member_type(scope.this, ident, None) if scope.this is not None else None
        if variable is not None and member is not None:
            raise ResolveError(name.pos, f"'{ident}' is both a variable and an attribute of the element; "
                                         f"write 'this.{ident}' for the attribute")  # fmt: skip
        if variable is not None:
            return Variable(ident, name.pos), variable
        if member is not None and scope.this is not None:
            return self.navigate(This(name.pos), scope.this, ident, None, scope, name.pos)
        if ident in enum:
            # Compared with an enumeration, a value of that enumeration takes precedence over e.g. a type name.
            return EnumValue(ident, name.pos), Values("enum", enum)
        if ident in self._defines:
            return self.call(Call(ident, (), name.pos), scope)
        if ident in self.metamodel.types or self._is_stereotype(ident):
            return TypeRef(ident, self.subtypes(ident), name.pos), Elements(self.subtypes(ident))
        parts = split_identifier(ident)
        if parts is not None and parts[0] in self.metamodel.types:
            return ElementRef(ident, name.pos), Elements(frozenset((parts[0],)))
        candidates = [*scope.variables, *self.metamodel.types, *self._defines]
        if scope.this is not None:
            candidates += self.member_names(scope.this)
        raise ResolveError(name.pos, f"unknown name '{ident}'{_suggestion(ident, candidates)}")

    def call(self, call: Call, scope: Scope) -> tuple[Expression, StaticType]:
        ident = call.ident
        if ident == "count":
            if len(call.arguments) != 1:
                raise ResolveError(call.pos, "count() takes one argument")
            argument, _ = self.expression(call.arguments[0], scope)
            return Count(argument, call.pos), Values("number")
        if ident in self._defines:
            define, arguments = self.definition_arguments(call, scope)
            if define.type == CONDITION:
                raise ResolveError(call.pos, f"'{ident}' is a condition, not an expression")
            assert not isinstance(define.type, str)
            return DefinitionCall(ident, arguments, call.pos), define.type
        if scope.this is not None and ident in NAVIGATIONS:
            return self.navigate(This(call.pos), scope.this, ident, call.arguments, scope, call.pos)
        candidates = ["count", *self._defines, *NAVIGATIONS]
        raise ResolveError(call.pos, f"unknown function '{ident}'{_suggestion(ident, candidates)}")

    def definition_arguments(self, call: Call, scope: Scope) -> tuple[ResolvedDefine, tuple[Expression, ...]]:
        define = self.define(call.ident, call.pos)
        parameters = define.rule.parameters
        required = sum(1 for p in parameters if p.default is None)
        if not required <= len(call.arguments) <= len(parameters):
            raise ResolveError(call.pos, f"'{call.ident}' takes {_count(required, len(parameters))} arguments")
        arguments: list[Expression] = []
        for argument, parameter, parameter_type in zip(call.arguments, parameters, define.parameter_types):
            resolved, argument_type = self.expression(argument, scope)
            if not _compatible(parameter_type, argument_type):
                raise ResolveError(_pos(argument), f"argument '{parameter.ident}' of '{call.ident}' must be a {parameter.type}")
            arguments.append(resolved)
        return define, tuple(arguments)

    # --- Navigation ----------------------------------------------------------------------------------------

    def navigate(
        self,
        source: Expression,
        source_type: Elements,
        step: str,
        arguments: tuple[Expression, ...] | None,
        scope: Scope,
        pos: Position,
    ) -> tuple[Expression, StaticType]:
        resolved_arguments = self.navigation_arguments(step, arguments, scope, pos)
        static_type = self.member_type(source_type, step, resolved_arguments)
        if static_type is None:
            names = ", ".join(sorted(source_type.types)) or "nothing"
            suggestion = _suggestion(step, self.member_names(source_type))
            raise ResolveError(pos, f"'{step}' does not apply to {names}{suggestion}")
        return Navigate(source, step, resolved_arguments, pos), static_type

    def navigation_arguments(
        self, step: str, arguments: tuple[Expression, ...] | None, scope: Scope, pos: Position
    ) -> tuple[Expression, ...] | None:
        if arguments is None:
            return None
        if len(arguments) != 1:
            raise ResolveError(pos, f"'{step}' takes one argument")
        argument = arguments[0]
        if step == "descendants":
            resolved, static_type = self.expression(argument, scope)
            if static_type != Values("number"):
                raise ResolveError(_pos(argument), "the depth of 'descendants' must be a number")
            return (resolved,)
        stereotype = _TYPE_ARGUMENTS.get(step)
        if stereotype is None:
            raise ResolveError(pos, f"'{step}' takes no arguments")
        if not isinstance(argument, Name) or not (
            argument.ident in self.metamodel.types or self._is_stereotype(argument.ident)
        ):
            raise ResolveError(_pos(argument), f"the argument of '{step}' must be a {stereotype.value} type")
        ident = argument.ident
        if ident in self.metamodel.types:
            valid = self.metamodel.is_a(ident, stereotype.value)
        else:
            valid = stereotype in _stereotype(ident).chain()
        if not valid:
            raise ResolveError(argument.pos, f"'{ident}' is not a {stereotype.value} type")
        return (TypeRef(ident, self.subtypes(ident), argument.pos),)

    def member_type(self, source: Elements, step: str, arguments: tuple[Expression, ...] | None) -> StaticType | None:
        """The type of `.step` applied to elements of the source types, or None if it applies to none of them."""
        argument_types = arguments[0].types if arguments and isinstance(arguments[0], TypeRef) else None
        results: list[StaticType] = []
        for type_name in source.types:
            result = self._member_type(type_name, step, argument_types)
            if result is not None:
                results.append(result)
        if not results:
            return None
        if all(isinstance(r, Elements) for r in results):
            return Elements(frozenset(name for r in results if isinstance(r, Elements) for name in r.types))
        values = [r for r in results if isinstance(r, Values)]
        return values[0] if len(values) == len(results) else Values("other")

    def _member_type(self, type_name: str, step: str, argument_types: frozenset[str] | None) -> StaticType | None:
        if step == "type":
            return Values("text")
        if step == "id":
            return Values("text")
        for column in self.metamodel.columns(type_name):
            if column.name == step:
                return self.column_type(column.datatype)
        m = self.metamodel
        stereotype = m.types[type_name].stereotype
        is_entity = not stereotype.is_diagram()
        result: set[str] = set()
        if step in ("parent", "ancestors"):
            for h in self.of_stereotype(Stereotype.HIERARCHY_RELATIONSHIP):
                if m.is_a(type_name, self.single(h, "child")):
                    result |= self.subtypes(self.single(h, "parent"))
        elif step in ("children", "descendants"):
            for h in self.of_stereotype(Stereotype.HIERARCHY_RELATIONSHIP):
                if (argument_types is None or h in argument_types) and m.is_a(type_name, self.single(h, "parent")):
                    result |= self.subtypes(self.single(h, "child"))
        elif step == "ports":
            for p in self.of_stereotype(Stereotype.PORT):
                if (argument_types is None or p in argument_types) and self.matches(type_name, self.names(p, "owner")):
                    result.add(p)
        elif step == "owner" and is_entity:
            result.add(type_name)
        elif step in ("outgoing", "incoming", "targets", "sources", "reachable", "refines", "refined_by"):
            outgoing = step in ("outgoing", "targets", "reachable", "refines")
            if step in ("refines", "refined_by"):
                relationships = self.of_stereotype(Stereotype.REFINEMENT)
            else:
                relationships = [r for r in self.of_stereotype(Stereotype.RELATIONSHIP)
                                 if argument_types is None or r in argument_types]  # fmt: skip
            ports = [p for p in self.of_stereotype(Stereotype.PORT) if self.matches(type_name, self.names(p, "owner"))]
            for r in relationships:
                near, far = (self.names(r, "start"), self.names(r, "end"))
                if not outgoing:
                    near, far = far, near
                if not (self.matches(type_name, near) or any(self.matches(p, near) for p in ports)):
                    continue
                if step in ("outgoing", "incoming"):
                    result |= self.subtypes(r)
                else:
                    result |= self.owners(far)
        elif step == "instances" and stereotype is Stereotype.TEMPLATE_ENTITY:
            for i in self.of_stereotype(Stereotype.INSTANTIATION_ENTITY):
                if m.is_a(type_name, self.single(i, "template")):
                    result |= self.subtypes(i)
        elif step in ("constituents", "aggregate") and m.is_a(type_name, Stereotype.RELATIONSHIP.value):
            near_key, far_key = ("aggregate", "constituent") if step == "constituents" else ("constituent", "aggregate")
            for b in self.of_stereotype(Stereotype.RELATIONSHIP_BREAKDOWN):
                if m.is_a(type_name, self.single(b, near_key)):
                    result |= self.subtypes(self.single(b, far_key))
        elif step == "chains" and m.is_a(type_name, Stereotype.RELATIONSHIP.value):
            for c in self.of_stereotype(Stereotype.CHAIN):
                if (argument_types is None or c in argument_types) and m.is_a(type_name, self.single(c, "relationship")):
                    result |= self.subtypes(c)
        else:
            return None
        if not result:
            return None
        return Elements(frozenset(result))

    def column_type(self, datatype: DataType) -> StaticType:
        element = datatype.element if isinstance(datatype, ListType) else datatype
        match element:
            case RefType(targets):
                return Elements(frozenset(name for target in targets for name in self.subtypes(target)))
            case EnumType(values):
                return Values("enum", values)
            case SimpleType(kind) if kind in _TEXT_KINDS:
                return Values("text")
            case SimpleType(kind) if kind in _NUMBER_KINDS:
                return Values("number")
            case SimpleType("bool"):
                return Values("bool")
            case _:
                return Values("other")

    def member_names(self, source: Elements) -> list[str]:
        names = {"type", "id"}
        for type_name in source.types:
            names |= {column.name for column in self.metamodel.columns(type_name)}
            names |= {step for step in NAVIGATIONS if self._member_type(type_name, step, None) is not None}
        return sorted(names)

    # --- Conditions ----------------------------------------------------------------------------------------

    def condition(self, condition: Condition, scope: Scope) -> Condition:
        match condition:
            case Compare(op, left, right, pos):
                resolved_left, left_type, resolved_right, right_type = self.pair(left, right, scope)
                if isinstance(left_type, Elements) and isinstance(right_type, Elements):
                    if op not in ("=", "!="):
                        raise ResolveError(pos, f"elements can only be compared with = and !=, not {op}")
                elif isinstance(left_type, Values) and isinstance(right_type, Values):
                    if not _comparable(left_type, right_type):
                        raise ResolveError(pos, f"cannot compare {_describe(left_type)} with {_describe(right_type)}")
                    if op not in ("=", "!=") and "number" not in (left_type.kind, right_type.kind):
                        raise ResolveError(pos, f"only numbers can be compared with {op}")
                else:
                    raise ResolveError(pos, "cannot compare elements with values")
                return Compare(op, resolved_left, resolved_right, pos)
            case In(left, right, pos):
                resolved_left, left_type, resolved_right, right_type = self.pair(left, right, scope)
                if isinstance(left_type, Elements) != isinstance(right_type, Elements):
                    raise ResolveError(pos, "'in' cannot compare elements with values")
                return In(resolved_left, resolved_right, pos)
            case IsEmpty(value, negated, pos):
                return IsEmpty(self.expression(value, scope)[0], negated, pos)
            case TextMatch(op, value, pattern, pos):
                resolved, static_type = self.expression(value, scope)
                if not (isinstance(static_type, Values) and static_type.kind in ("text", "enum", "other")):
                    raise ResolveError(pos, f"'{op}' applies to text, not to {_describe(static_type)}")
                if op == "matches":
                    try:
                        re.compile(pattern)
                    except re.error as error:
                        raise ResolveError(pos, f"invalid regular expression: {error}") from None
                return TextMatch(op, resolved, pattern, pos)
            case Quantifier(quantifier, var, source, inner, pos):
                resolved_source, source_type = self.expression(source, scope)
                elements = self.require_elements(source_type, source, quantifier)
                resolved_inner = self.condition(inner, scope.bind(var, elements))
                return Quantifier(quantifier, var, resolved_source, resolved_inner, pos)
            case ConditionCall(ident, arguments, pos):
                if ident not in self._defines:
                    raise ResolveError(pos, f"unknown condition '{ident}'{_suggestion(ident, list(self._defines))}")
                define, resolved_arguments = self.definition_arguments(Call(ident, arguments, pos), scope)
                if define.type != CONDITION:
                    raise ResolveError(pos, f"'{ident}' is an expression, not a condition")
                return ConditionCall(ident, resolved_arguments, pos)
            case And(operands, pos):
                return And(tuple(self.condition(c, scope) for c in operands), pos)
            case Or(operands, pos):
                return Or(tuple(self.condition(c, scope) for c in operands), pos)
            case Not(operand, pos):
                return Not(self.condition(operand, scope), pos)

    def pair(self, left: Expression, right: Expression, scope: Scope) -> tuple[Expression, StaticType, Expression, StaticType]:
        """Resolve both sides of a comparison. A bare name on one side may be an enumeration value of the other."""
        try:
            resolved_left, left_type = self.expression(left, scope)
        except ResolveError as left_error:
            if not isinstance(left, Name):
                raise
            try:
                resolved_right, right_type = self.expression(right, scope)
            except ResolveError:
                raise left_error from None
            resolved_left, left_type = self.expression(left, scope, _enum_values(right_type))
            return resolved_left, left_type, resolved_right, right_type
        resolved_right, right_type = self.expression(right, scope, _enum_values(left_type))
        return resolved_left, left_type, resolved_right, right_type

    # --- Helpers -------------------------------------------------------------------------------------------

    def require_elements(self, static_type: StaticType, expression: Expression, keyword: str) -> Elements:
        if not isinstance(static_type, Elements):
            raise ResolveError(_pos(expression), f"'{keyword}' needs elements, not {_describe(static_type)}")
        return static_type

    def subtypes(self, name: str) -> frozenset[str]:
        if self._is_stereotype(name):
            return frozenset(t for t in self.metamodel.types if self.metamodel.is_a(t, name))
        return frozenset(self.metamodel.subtypes(name))

    def of_stereotype(self, stereotype: Stereotype) -> list[str]:
        return [name for name, t in self.metamodel.types.items() if stereotype in t.stereotype.chain()]

    def names(self, type_name: str, key: str) -> tuple[str, ...]:
        value = self.metamodel.property(type_name, key)
        if isinstance(value, tuple):
            return tuple(str(v) for v in value)
        if isinstance(value, str):
            return (value,)
        return ()

    def single(self, type_name: str, key: str) -> str:
        names = self.names(type_name, key)
        return names[0] if names else ""

    def matches(self, type_name: str, names: Iterable[str]) -> bool:
        return any(name and self.metamodel.is_a(type_name, name) for name in names)

    def owners(self, names: Iterable[str]) -> frozenset[str]:
        """The types of the entities at the end of a relationship: port types are replaced by their owners."""
        result: set[str] = set()
        for name in names:
            if self.metamodel.types[name].stereotype is Stereotype.PORT:
                for owner in self.names(name, "owner"):
                    result |= self.subtypes(owner)
            else:
                result |= self.subtypes(name)
        return frozenset(result)

    @staticmethod
    def _is_stereotype(name: str) -> bool:
        return name in {s.value for s in Stereotype}


def _stereotype(name: str) -> Stereotype:
    return next(s for s in Stereotype if s.value == name)


def _literal_type(literal: Literal) -> Values:
    value = literal.value
    if isinstance(value, bool):
        return Values("bool")
    if isinstance(value, (int, float)):
        return Values("number")
    return Values("text")


def _enum_values(static_type: StaticType) -> tuple[str, ...]:
    return static_type.enum if isinstance(static_type, Values) else ()


def _compatible(expected: StaticType, actual: StaticType) -> bool:
    if isinstance(expected, Elements) and isinstance(actual, Elements):
        return bool(expected.types & actual.types)
    if isinstance(expected, Values) and isinstance(actual, Values):
        return _comparable(expected, actual)
    return False


def _comparable(left: Values, right: Values) -> bool:
    if "other" in (left.kind, right.kind):
        return True
    kinds = {left.kind, right.kind}
    return len(kinds) == 1 or kinds == {"enum", "text"}


def _describe(static_type: StaticType) -> str:
    if isinstance(static_type, Elements):
        return "elements"
    return {"text": "text", "number": "numbers", "bool": "booleans", "enum": "enumeration values"}.get(
        static_type.kind, "values"
    )


def _count(low: int, high: int) -> str:
    return str(high) if low == high else f"{low} to {high}"


def _suggestion(name: str, candidates: Iterable[str]) -> str:
    matches = difflib.get_close_matches(name, sorted(set(candidates)), n=1)
    return f"; did you mean '{matches[0]}'?" if matches else ""


def _pos(expression: Expression) -> Position:
    return expression.pos
