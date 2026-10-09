"""The TatSu grammar of the selection language.

The grammar follows "Grammar" in doc/selection_language.md. Indentation-based blocks are turned into `{` and
`}` by archtool.language.blocks before parsing, so the grammar itself is free of indentation.

The parser is generated from this grammar into archtool/language/_parser.py, which is much faster than
compiling the grammar at run time. After changing the grammar, regenerate it with:

    uv run python -m archtool.language.grammar

A test checks that the generated parser is up to date.

Every kind of node has its own rule with a node type (`rule::Type`). The converter in
archtool.language.parser recognises nodes by these types. Notes on TatSu:

* Node types are only created when parsing with ModelBuilderSemantics.
* Constants (`` `x` ``) would be a simpler way to mark nodes, but TatSu evaluates them as Python expressions at
  every use, which makes parsing several times slower.
* Whitespace is not skipped before rules whose names start with a capital, so token rules have lowercase names.
* In the generated parser, an absent optional field gets a wrong value, unless its rule produces a node. So
  optional parts are always nodes, e.g. `params`, and variants such as `is empty` and `is not empty` are
  separate node types rather than an optional token.
"""

GRAMMAR = r"""
@@grammar :: Selection
@@whitespace :: /[ \t\r\n]+/
@@keyword :: define diagram check query let show for each in require otherwise select columns order by
@@keyword :: descending where between from to union intersect except and or not is empty contains matches
@@keyword :: every some no this true false error warning info

start::Rules = rules:{rule}* $ ;
expression_start = @:expression $ ;

rule = define | diagram | check | query ;

define::Define = 'define' ident:name_token params:[params] '=' body:define_body ;
define_body = @:condition &rule_end | @:expression ;
rule_end = 'define' | 'diagram' | 'check' | 'query' | $ ;

diagram::Diagram = 'diagram' ident:name_token params:[params] ':' '{' statements:{diagram_statement}+ '}' ;
diagram_statement = let | show ;

check::Check = 'check' ident:name_token params:[params] '(' severity:severity ')' ':'
    '{' lets:{let}* foreach:foreach '}' ;
severity = 'error' | 'warning' | 'info' ;
foreach::ForEach = 'for' 'each' var:name_token 'in' source:expression ':' '{' statements:{foreach_statement}+ '}' ;
foreach_statement = let | require ;
require::Require = 'require' condition:condition 'otherwise' message:message ;
message::Message = value:string_token ;

query::Query = 'query' ident:name_token params:[params] ':' '{' lets:{let}* select:select '}' ;
select::Select = 'select' source:expression ['columns' columns:arguments] [order:order] ;
order = descending_order | ascending_order ;
descending_order::DescendingOrder = 'order' 'by' key:expression 'descending' ;
ascending_order::AscendingOrder = 'order' 'by' key:expression ;

let::Let = 'let' var:name_token '=' value:expression ;
show::Show = 'show' value:expression ;

params::Params = '(' entries:','.{param}+ ')' ;
param::Param = ident:name_token ':' type:name_token ['=' default:literal] ;

expression::Expression = source:set_expression ['where' condition:condition] ;
set_expression::SetExpression = first:relation_expression rest:{set_operation}* ;
set_operation::SetOperation = op:('union' | 'intersect' | 'except') operand:relation_expression ;
relation_expression::RelationExpression = subject:path [tail:relation_tail] ;
relation_tail = between | from_to | to_only ;
between::Between = 'between' other:path ;
from_to::FromTo = 'from' origin:path ['to' target:path] ;
to_only::FromTo = 'to' target:path ;
path::Path = base:primary steps:{step}* ;
step::Step = '.' ident:name_token ['(' arguments:arguments ')'] ;
arguments = ','.{expression}+ ;

primary = this_expression | literal | list_expression | group_expression | call_expression | name_expression ;
this_expression::This = keyword:'this' ;
list_expression::List = '[' elements:[arguments] ']' ;
group_expression::Group = '(' inner:expression ')' ;
call_expression::Call = ident:name_token '(' arguments:arguments ')' ;
name_expression::Name = ident:name_token ;

literal = string_literal | number_literal | boolean_literal ;
string_literal::String = value:string_token ;
number_literal::Number = value:number_token ;
boolean_literal::Boolean = value:('true' | 'false') ;

condition::Or = first:conjunction rest:{or_operand}* ;
or_operand = 'or' @:conjunction ;
conjunction::And = first:negation rest:{and_operand}* ;
and_operand = 'and' @:negation ;
negation = not_condition | atom ;
not_condition::Not = 'not' inner:atom ;

atom = quantifier | test | group_condition | call_condition ;
quantifier::Quantifier = which:('every' | 'some' | 'no') var:name_token 'in' source:expression ':' inner:condition ;
test::Test = left:expression tail:test_tail ;
test_tail = comparison | membership | not_empty | empty | text_match ;
comparison::Compare = op:comparison_operator right:expression ;
membership::In = 'in' right:expression ;
not_empty::IsNotEmpty = keyword:'is' 'not' 'empty' ;
empty::IsEmpty = keyword:'is' 'empty' ;
text_match::TextMatch = op:('contains' | 'matches') pattern:string_token ;
group_condition::GroupCondition = '(' inner:condition ')' ;
call_condition::CallCondition = ident:name_token '(' arguments:arguments ')' ;
comparison_operator = '!=' | '<=' | '>=' | '=' | '<' | '>' ;

@name
name_token = /[A-Za-z_][A-Za-z0-9_]*/ ;
string_token = /"(?:[^"\\\n]|\\.)*"/ ;
number_token = /-?[0-9]+(?:\.[0-9]+)?/ ;
"""


def generate_parser() -> str:
    """The source code of the parser generated from GRAMMAR."""
    import tatsu

    return str(tatsu.to_python_sourcecode(GRAMMAR))


if __name__ == "__main__":
    from pathlib import Path

    Path(__file__).with_name("_parser.py").write_text(generate_parser(), encoding="utf-8")
