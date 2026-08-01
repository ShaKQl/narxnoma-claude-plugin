"""Tests for the belt-and-braces guard in conftest.py that refuses to
truncate a database whose name doesn't mark it as disposable. Needs no
database connection -- it only exercises DSN parsing and the refusal.
"""
import pytest

from conftest import require_disposable_test_database


def test_refuses_a_database_without_test_in_its_name():
    with pytest.raises(RuntimeError):
        require_disposable_test_database("postgresql://narxnoma@127.0.0.1:55432/narxnoma")


def test_does_not_raise_for_a_database_named_with_test_suffix():
    require_disposable_test_database("postgresql://narxnoma@127.0.0.1:55432/narxnoma_test")
