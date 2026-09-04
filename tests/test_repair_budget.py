"""Runnable checks for the SQL repair-budget wrapper.

No test framework: `python tests/test_repair_budget.py` (from the project root).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import _wrap_query_tool_with_repair_budget


class _FakeQueryTool:
    """Stand-in for sql_db_query that replays a fixed list of results."""

    name = "sql_db_query"
    description = "fake"
    args_schema = None

    def __init__(self, results):
        self._results = list(results)
        self._i = 0

    def run(self, query):
        r = self._results[min(self._i, len(self._results) - 1)]
        self._i += 1
        return r


def test_budget_exhausts_on_nth_failure():
    tool = _wrap_query_tool_with_repair_budget(
        _FakeQueryTool(["Error: boom"]), max_attempts=3
    )
    assert "[self-correction 1/3]" in tool.run("x")
    assert "[self-correction 2/3]" in tool.run("x")
    out = tool.run("x")
    assert "repair budget exhausted after 3" in out
    assert "Error: boom" in out


def test_success_resets_counter():
    tool = _wrap_query_tool_with_repair_budget(
        _FakeQueryTool(["Error: boom", "[(1,)]", "Error: boom"]), max_attempts=3
    )
    assert "[self-correction 1/3]" in tool.run("x")
    assert tool.run("x") == "[(1,)]"
    assert "[self-correction 1/3]" in tool.run("x")  # not 2/3


def test_plain_result_passes_through():
    tool = _wrap_query_tool_with_repair_budget(
        _FakeQueryTool(["[(42,)]"]), max_attempts=3
    )
    assert tool.run("x") == "[(42,)]"


if __name__ == "__main__":
    test_budget_exhausts_on_nth_failure()
    test_success_resets_counter()
    test_plain_result_passes_through()
    print("ok")
