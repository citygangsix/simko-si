"""Simco SI daily recommendations: rules propose, Thompson sampling ranks, max 3/day."""
from .engine import MAX_PER_DAY, TEMPLATES, ACTIONS, build_today, record_feedback, arm_for  # noqa: F401
