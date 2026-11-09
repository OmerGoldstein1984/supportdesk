"""Agents package: router, four specialists, critic."""

from .base import SpecialistResult, critique, route_message, run_specialist
from .critic import CriticOutput
from .router import RouterOutput
from .specialist import make_specialist, system_prompt_for

__all__ = [
    "route_message",
    "critique",
    "SpecialistResult",
    "run_specialist",
    "RouterOutput",
    "CriticOutput",
    "make_specialist",
    "system_prompt_for",
]
