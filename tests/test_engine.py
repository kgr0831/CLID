"""Graph engine: flow, conditional loops, reducers, checkpointing, errors."""

import unittest

from clid.graph import END, START, MemoryCheckpointer, StateGraph
from clid.graph.engine import GraphError
from clid.graph.state import REDUCERS


class TestEngine(unittest.TestCase):
    def test_linear_flow(self):
        g = StateGraph()
        g.add_node("a", lambda s: {"x": 1})
        g.add_node("b", lambda s: {"x": s["x"] + 1})
        g.add_edge(START, "a")
        g.add_edge("a", "b")
        g.add_edge("b", END)
        out = g.compile().invoke({})
        self.assertEqual(out["x"], 2)
        self.assertEqual(out["_last_node"], END)

    def test_conditional_loop_and_append_reducer(self):
        g = StateGraph(reducers=REDUCERS)
        g.add_node("a", lambda s: {"log": "a"})
        g.add_node("b", lambda s: {"log": "b", "n": s.get("n", 0) + 1})
        g.add_edge(START, "a")
        g.add_edge("a", "b")
        g.add_conditional_edges("b", lambda s: "loop" if s["n"] < 3 else "done",
                                {"loop": "a", "done": END})
        ck = MemoryCheckpointer()
        out = g.compile(checkpointer=ck).invoke({"n": 0, "log": []}, {"thread_id": "t"})
        self.assertEqual(out["n"], 3)
        self.assertEqual(out["log"].count("b"), 3)
        self.assertEqual(len(ck.history("t")), 6)  # a,b,a,b,a,b

    def test_missing_entry_raises(self):
        g = StateGraph()
        g.add_node("a", lambda s: {})
        with self.assertRaises(GraphError):
            g.compile()

    def test_unmapped_router_key_raises(self):
        g = StateGraph()
        g.add_node("a", lambda s: {})
        g.add_edge(START, "a")
        g.add_conditional_edges("a", lambda s: "nope", {"ok": END})
        with self.assertRaises(GraphError):
            g.compile().invoke({})

    def test_max_steps_guard(self):
        g = StateGraph()
        g.add_node("a", lambda s: {})
        g.add_edge(START, "a")
        g.add_edge("a", "a")  # infinite
        with self.assertRaises(GraphError):
            g.compile(max_steps=10).invoke({})


if __name__ == "__main__":
    unittest.main()
