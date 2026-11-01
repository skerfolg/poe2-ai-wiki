"""Code identity is stable across warm execution and reference-count changes."""

from pok.common.code_identity import code_sha256


def test_identity_does_not_change_with_reference_counts_or_warm_execution():
    def function(value):
        return value + 1

    before = code_sha256(function.__code__)
    references = [function.__code__] * 100
    for number in range(100):
        function(number)
    assert code_sha256(function.__code__) == before
    del references
    assert code_sha256(function.__code__) == before


def test_constant_change_and_nested_code_change_are_identified():
    first = compile("def outer():\n def inner(): return 1\n return inner()", "same.py", "exec")
    second = compile("def outer():\n def inner(): return 2\n return inner()", "same.py", "exec")
    assert code_sha256(first) != code_sha256(second)


def test_frozenset_iteration_order_is_not_code_identity():
    code = compile("x in {'first', 'second', 'third'}", "same.py", "eval")
    constants = tuple(
        frozenset(reversed(tuple(value))) if isinstance(value, frozenset) else value
        for value in code.co_consts
    )
    assert code_sha256(code) == code_sha256(code.replace(co_consts=constants))
