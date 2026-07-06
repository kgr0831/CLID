"""A small, dependency-free StateGraph engine.

Semantics deliberately track LangGraph:

* State is a ``dict``. Each node is ``fn(state) -> dict`` of channel updates.
* Channel updates are merged with a *reducer*. Default reducer overwrites;
  register append-style reducers (e.g. for a ``log`` channel) via ``reducers``.
* Edges are static (``add_edge``) or conditional (``add_conditional_edges``):
  a router function inspects the state and returns a key into a path map.
* ``START`` / ``END`` are sentinel node names.
* ``compile`` returns a ``CompiledGraph`` you ``invoke(state, config)``.
* A checkpointer (see ``checkpoint.py``) snapshots state after every node,
  keyed by ``config["thread_id"]`` — this is the L-loop recovery point.
"""

from __future__ import annotations

from typing import Any, Callable

START = "__start__"
END = "__end__"

Node = Callable[[dict], dict]
Router = Callable[[dict], str]
Reducer = Callable[[Any, Any], Any]


def _overwrite(_old: Any, new: Any) -> Any:
    return new


def append_reducer(old: Any, new: Any) -> list:
    """Reducer that extends a list channel (old + new)."""
    base = list(old) if old else []
    if isinstance(new, list):
        base.extend(new)
    else:
        base.append(new)
    return base


class GraphError(RuntimeError):
    pass


class StateGraph:
    def __init__(self, reducers: dict[str, Reducer] | None = None) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, str] = {}
        self._conditional: dict[str, tuple[Router, dict[str, str]]] = {}
        self._entry: str | None = None
        self._reducers: dict[str, Reducer] = reducers or {}

    # ---- construction -----------------------------------------------------
    def add_node(self, name: str, fn: Node) -> "StateGraph":
        if name in (START, END):
            raise GraphError(f"{name!r} is reserved")
        if name in self._nodes:
            raise GraphError(f"duplicate node {name!r}")
        self._nodes[name] = fn
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        if src == START:
            self._entry = dst
            return self
        if src in self._conditional:
            raise GraphError(f"node {src!r} already has conditional edges")
        self._edges[src] = dst
        return self

    def add_conditional_edges(
        self, src: str, router: Router, path_map: dict[str, str]
    ) -> "StateGraph":
        if src in self._edges:
            raise GraphError(f"node {src!r} already has a static edge")
        self._conditional[src] = (router, path_map)
        return self

    def set_entry_point(self, name: str) -> "StateGraph":
        self._entry = name
        return self

    def compile(
        self, checkpointer: Any | None = None, max_steps: int = 1000
    ) -> "CompiledGraph":
        if self._entry is None:
            raise GraphError("no entry point (use add_edge(START, ...) or set_entry_point)")
        if self._entry not in self._nodes:
            raise GraphError(f"entry node {self._entry!r} is not defined")
        self._validate()
        return CompiledGraph(self, checkpointer, max_steps)

    def _validate(self) -> None:
        for src, dst in self._edges.items():
            if dst != END and dst not in self._nodes:
                raise GraphError(f"edge {src!r} -> {dst!r}: unknown target")
        for src, (_router, path_map) in self._conditional.items():
            for key, dst in path_map.items():
                if dst != END and dst not in self._nodes:
                    raise GraphError(f"conditional {src!r}[{key!r}] -> {dst!r}: unknown target")

    def _next(self, node: str, state: dict) -> str:
        if node in self._conditional:
            router, path_map = self._conditional[node]
            key = router(state)
            if key not in path_map:
                raise GraphError(f"router for {node!r} returned unmapped key {key!r}")
            return path_map[key]
        return self._edges.get(node, END)

    def _reducer_for(self, channel: str) -> Reducer:
        return self._reducers.get(channel, _overwrite)


class CompiledGraph:
    def __init__(self, graph: StateGraph, checkpointer: Any, max_steps: int) -> None:
        self._g = graph
        self._ckpt = checkpointer
        self._max_steps = max_steps

    def _merge(self, state: dict, updates: dict) -> dict:
        if not updates:
            return state
        for channel, value in updates.items():
            reducer = self._g._reducer_for(channel)
            state[channel] = reducer(state.get(channel), value)
        return state

    def invoke(self, state: dict, config: dict | None = None) -> dict:
        config = config or {}
        thread_id = config.get("thread_id", "default")
        on_step: Callable[[str, dict], None] | None = config.get("on_step")

        state = dict(state)
        node = self._g._entry
        step = 0
        while node != END:
            if step >= self._max_steps:
                raise GraphError(f"exceeded max_steps={self._max_steps} (cycle without END?)")
            fn = self._g._nodes[node]
            updates = fn(state) or {}
            state = self._merge(state, updates)
            state["_last_node"] = node
            state["_step"] = step
            if self._ckpt is not None:
                self._ckpt.put(thread_id, step, node, state)
            if on_step is not None:
                on_step(node, state)
            node = self._g._next(node, state)
            step += 1
        state["_last_node"] = END
        return state
