"""Shared fixtures for the container-host-aiops test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_approver(monkeypatch):
    """Record a synthetic approver annotation globally so audit rows carry one.

    It is only an annotation now — nothing requires or is gated by it. The
    governance-persistence tests clear it to check that a write still runs and
    audits with no approver set."""
    monkeypatch.setenv("CONTAINER_HOST_AUDIT_APPROVED_BY", "pytest")
