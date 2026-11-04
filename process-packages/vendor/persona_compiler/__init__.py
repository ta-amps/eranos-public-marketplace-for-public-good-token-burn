"""Standard-library compiler and linter for portable multi-harness agent role definitions."""

from .compiler import (
    SUPPORTED_HARNESS_TARGETS,
    compile_portable_role,
    score_delegation_description,
    strip_degrading_fluff,
    verify_permission_separation,
)

__all__ = [
    "SUPPORTED_HARNESS_TARGETS",
    "compile_portable_role",
    "score_delegation_description",
    "strip_degrading_fluff",
    "verify_permission_separation",
]
