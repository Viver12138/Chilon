"""Read-only view over the frozen state machine contract.

Both the task service and the plan service need the same thing: a lookup from
`(state, trigger)` to the declared transition, plus the ordered state list. This
module is the single place that reads `schemas/state_machines.v1.json`, so no
service can quietly carry its own copy of the rules.

Lists in the contract are expanded: a transition may declare several from-states
or several equivalent triggers, and one declared edge can produce many lookup
keys.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Transition:
    id: str
    from_state: str
    to_state: str
    trigger: str
    guard: str


@dataclass(frozen=True)
class Aggregate:
    id: str
    states: list[str]
    initial_states: list[str]
    terminal_states: list[str]
    transitions: dict[tuple[str, str], Transition]

    @property
    def initial(self) -> str:
        return self.initial_states[0]

    def trigger_for(self, state: str, trigger: str) -> Transition | None:
        return self.transitions.get((state, trigger))

    def triggers_from(self, state: str) -> list[str]:
        return sorted(trigger for (from_state, trigger) in self.transitions if from_state == state)


def _contract_path() -> Path:
    override = os.environ.get("CHILON_SCHEMA_DIR")
    if override:
        return Path(override) / "state_machines.v1.json"
    # backend/app/services/contract.py -> repo root
    return Path(__file__).resolve().parents[3] / "schemas" / "state_machines.v1.json"


@lru_cache(maxsize=None)
def load(aggregate: str) -> Aggregate:
    raw = json.loads(_contract_path().read_text(encoding="utf-8"))
    agg = next(a for a in raw["aggregates"] if a["id"] == aggregate)

    table: dict[tuple[str, str], Transition] = {}
    for tr in agg["transitions"]:
        from_states = tr["from"] if isinstance(tr["from"], list) else [tr["from"]]
        triggers = tr["trigger"] if isinstance(tr["trigger"], list) else [tr["trigger"]]
        for from_state in from_states:
            for trigger in triggers:
                key = (from_state, trigger)
                if key in table:
                    raise RuntimeError(
                        f"contract has two transitions for {aggregate} {key}: "
                        f"{table[key].id} and {tr['id']}"
                    )
                table[key] = Transition(
                    id=tr["id"],
                    from_state=from_state,
                    to_state=tr["to"],
                    trigger=trigger,
                    guard=tr.get("guard", ""),
                )

    return Aggregate(
        id=agg["id"],
        states=list(agg["states"]),
        initial_states=list(agg.get("initial_states") or agg["states"]),
        terminal_states=list(agg.get("terminal_states") or []),
        transitions=table,
    )
