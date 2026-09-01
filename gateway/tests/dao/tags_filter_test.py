"""Unit tests for the shared tag-filter condition builder (no DB required)."""

from sqlalchemy import column, func, select, table

from radicalbit_ai_gateway.db.dao.tags_filter import add_tags_filter


def _compile_where(tags):
    T = table('t', column('TAGS'))
    conditions = []
    add_tags_filter(conditions, T.c['TAGS'], tags)
    if not conditions:
        return None, {}
    stmt = select(func.count()).select_from(T).where(*conditions)
    compiled = stmt.compile()
    return str(compiled), compiled.params


def test_no_tags_adds_no_conditions():
    conditions = []
    add_tags_filter(conditions, column('TAGS'), None)
    assert conditions == []


def test_empty_list_adds_no_conditions():
    conditions = []
    add_tags_filter(conditions, column('TAGS'), [])
    assert conditions == []


def test_single_tag_produces_one_hasany_condition():
    sql, params = _compile_where(['env=prod'])
    assert sql.count('hasAny(') == 1
    assert list(params.values()) == [['env=prod']]


def test_same_key_values_are_grouped_into_one_hasany_or():
    sql, params = _compile_where(['env=prod', 'env=staging'])
    assert sql.count('hasAny(') == 1
    assert list(params.values()) == [['env=prod', 'env=staging']]


def test_different_keys_produce_separate_anded_conditions():
    sql, params = _compile_where(['env=prod', 'cost_center=retail'])
    assert sql.count('hasAny(') == 2
    assert ' AND ' in sql
    assert sorted(params.values()) == sorted([['env=prod'], ['cost_center=retail']])


def test_tag_values_are_bound_parameters_not_inlined():
    """Regression test: values must never be interpolated as literal SQL text."""
    malicious = "prod'; DROP TABLE t; --"
    sql, params = _compile_where([f'env={malicious}'])
    assert malicious not in sql
    assert list(params.values()) == [[f'env={malicious}']]
