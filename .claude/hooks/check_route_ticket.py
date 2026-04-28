"""
PreToolUse hook per route_ticket.
Blocca deterministicamente il routing se:
- confidence < CONFIDENCE_THRESHOLD (default 0.5)
- categoria = emergenza_pericolo (sempre human review)
Questo è un guardrail hard, non basato su prompt.
"""

import json
import os
import sys

CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))

try:
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input", {})
    confidence = float(tool_input.get("confidence", 0.0))
    category = tool_input.get("category", "")

    if category == "emergenza_pericolo":
        print(json.dumps({
            "decision": "block",
            "reason": "EMERGENCY_ALWAYS_HUMAN: Le emergenze richiedono sempre revisione umana prima del routing."
        }))
        sys.exit(0)

    if confidence < CONFIDENCE_THRESHOLD:
        print(json.dumps({
            "decision": "block",
            "reason": f"LOW_CONFIDENCE: confidence={confidence:.2f} < soglia={CONFIDENCE_THRESHOLD}. Ticket inviato in human_review."
        }))
        sys.exit(0)

    # Lascia passare
    print(json.dumps({"decision": "allow"}))
    sys.exit(0)

except Exception as e:
    # In caso di errore nel hook, blocca per sicurezza
    print(json.dumps({"decision": "block", "reason": f"HOOK_ERROR: {e}"}))
    sys.exit(0)
