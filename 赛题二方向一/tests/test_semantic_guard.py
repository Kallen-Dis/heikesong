# -*- coding: utf-8 -*-
"""用独立小型数据库验证连接放大和孤儿阻断，无需生成仓库。"""
import duckdb
import pytest

from src.semantic_guard import validate_relationships


@pytest.fixture()
def relationship_db():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE customers (customer_id VARCHAR); INSERT INTO customers VALUES ('C1')")
    conn.execute("CREATE TABLE products (product_id VARCHAR); INSERT INTO products VALUES ('P1')")
    conn.execute("CREATE TABLE carriers (carrier_id VARCHAR); INSERT INTO carriers VALUES ('K1')")
    conn.execute("CREATE TABLE orders (order_id VARCHAR, customer_id VARCHAR, product_id VARCHAR); INSERT INTO orders VALUES ('O1','C1','P1')")
    conn.execute("CREATE TABLE shipments (shipment_id VARCHAR, order_id VARCHAR, carrier_id VARCHAR); INSERT INTO shipments VALUES ('S1','O1','K1')")
    yield conn
    conn.close()


def test_valid_one_shipment_contract_passes(relationship_db):
    assert validate_relationships(relationship_db) == []


def test_duplicate_dimension_key_is_blocked(relationship_db):
    relationship_db.execute("INSERT INTO products VALUES ('P1')")
    issues = validate_relationships(relationship_db)
    assert any(i['code'] == 'duplicate_primary_key' and i['table'] == 'products' for i in issues)


def test_split_shipment_is_blocked_even_when_shipment_ids_unique(relationship_db):
    relationship_db.execute("INSERT INTO shipments VALUES ('S2','O1','K1')")
    issues = validate_relationships(relationship_db)
    assert any(i['code'] == 'shipment_fanout' and i['count'] == 1 for i in issues)


def test_orphan_is_blocked_before_inner_join_hides_it(relationship_db):
    relationship_db.execute("INSERT INTO orders VALUES ('O2','MISSING','P1')")
    issues = validate_relationships(relationship_db)
    assert any(i['code'] == 'orphan_foreign_key' and i['table'] == 'orders' for i in issues)


def test_null_primary_key_and_fk_are_blocked(relationship_db):
    relationship_db.execute("INSERT INTO shipments VALUES (NULL,'O1',NULL)")
    codes = {i['code'] for i in validate_relationships(relationship_db)}
    assert {'null_primary_key', 'orphan_foreign_key'} <= codes


def test_missing_schema_returns_a_blocking_issue():
    conn = duckdb.connect()
    try:
        assert validate_relationships(conn)[0]['code'] == 'relationship_schema_error'
    finally:
        conn.close()
