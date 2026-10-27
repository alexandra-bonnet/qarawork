import pytest

from samd_traceability_mcp.core import (
    Requirement, analyze, extract_test_references, is_test_file,
)


def req(number):
    return Requirement(number, f"Requirement {number}", f"https://github.com/example/app/issues/{number}")


def test_links_and_gaps():
    source = 'def test_login():\n    """Requirement: #1"""\n    assert True\n'
    result = analyze([req(3), req(1)], {
        "tests/test_login.py": source,
        "docs/overview.md": "Requirement: #3",
    }, repository="example/app")
    assert result["linked_count"] == 1
    assert result["unlinked_count"] == 1
    assert result["requirements"][0]["issue"] == 1


def test_dangling():
    source = 'def test_example():\n    """Requirement: #99"""\n    pass\n'
    result = analyze([req(1)], {"tests/test_a.py": source}, repository="example/app")
    assert result["references_to_non_requirement_issues"][0]["issue"] == 99


def test_test_file_detection():
    assert is_test_file("tests/a.py")
    assert is_test_file("package/test_a.py")
    assert not is_test_file("src/main.py")
    assert not is_test_file("examples/test_authentication.py")
    assert not is_test_file("package/examples/test_fake.py")
    assert is_test_file("tests/test_authentication.py")


def test_example_paths_do_not_count_as_evidence():
    example = 'def test_demo():\n    """Requirement: #12"""\n    pass\n'
    result = analyze([req(12)], {"examples/test_demo.py": example}, repository="example/app")
    assert result["scanned_test_files"] == 0
    assert result["unlinked_count"] == 1
    assert result["references_to_non_requirement_issues"] == []


def test_duplicate_numbers():
    with pytest.raises(ValueError):
        analyze([req(1), req(1)], {}, repository="example/app")


def test_do_not_confuse_fixture_strings_with_links():
    source = '''
def test_coverage_engine():
    sample = {"docs": "Requirement: #3", "fake": "Requirement: #99"}
    assert sample
'''
    assert extract_test_references(source) == set()


def test_function_docstring_is_a_valid_link():
    source = '''
def test_login():
    """Requirement: #2"""
    assert True
'''
    assert extract_test_references(source) == {2}


def test_comments_and_module_docstrings_are_not_links():
    source = '''"""Requirement: #33"""
# Requirement: #34
def test_login():
    # Requirement: #35
    assert True
'''
    assert extract_test_references(source) == set()


def test_syntax_error_fails_closed():
    with pytest.raises(ValueError):
        extract_test_references("def test_bad(\n")
