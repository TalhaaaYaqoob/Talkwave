"""Telecom compliance services.

Phase A (active): internal DNC/suppression list, consent management, TCPA
calling-hours enforcement, AI disclosure, and a pre-call compliance gate that
the campaign dispatcher consults before every outbound call.

Phase B (future): external registry sync (FTC DNC, UK TPS/CTPS) and
STIR/SHAKEN attestation checks plug into the same interfaces.
"""

from api.services.compliance.consent_manager import ConsentManager, consent_manager
from api.services.compliance.dnc_service import DNCService, dnc_service
from api.services.compliance.pre_call_gate import (
    ComplianceResult,
    PreCallComplianceGate,
    pre_call_gate,
)

__all__ = [
    "ConsentManager",
    "consent_manager",
    "DNCService",
    "dnc_service",
    "ComplianceResult",
    "PreCallComplianceGate",
    "pre_call_gate",
]
