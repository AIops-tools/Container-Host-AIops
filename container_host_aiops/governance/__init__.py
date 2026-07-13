"""Governance harness for container-host-aiops — audit, policy, budget, undo, sanitize.

A self-contained, vendored governance layer. container-host-aiops has NO dependency on
any external skill family — this package is its own copy of the harness:

  - ``@governed_tool`` — mandatory decorator on every MCP tool: policy pre-check,
    token/runaway budget guard, graduated-autonomy risk-tier gate, audit logging,
    and undo-token recording.
  - unified SQLite audit log under ``~/.container-host-aiops/`` (override with
    ``CONTAINER_HOST_AIOPS_HOME``).
  - ``sanitize`` — output hygiene (encoding-level defense) for API-returned text.

State lives under ``ops_home()`` (default ``~/.container-host-aiops``).
"""

from container_host_aiops.governance.audit import AuditEngine, get_engine
from container_host_aiops.governance.budget import BudgetExceeded, BudgetTracker, get_budget
from container_host_aiops.governance.decorators import PolicyDenied, governed_tool
from container_host_aiops.governance.patterns import Pattern, PatternMatch, get_pattern_engine
from container_host_aiops.governance.policy import TierDecision, get_policy_engine
from container_host_aiops.governance.sanitize import sanitize
from container_host_aiops.governance.undo import UndoStore, get_undo_store

__all__ = [
    "governed_tool",
    "sanitize",
    "PolicyDenied",
    "get_engine",
    "AuditEngine",
    "get_policy_engine",
    "TierDecision",
    "get_budget",
    "BudgetTracker",
    "BudgetExceeded",
    "get_undo_store",
    "UndoStore",
    "Pattern",
    "PatternMatch",
    "get_pattern_engine",
]
