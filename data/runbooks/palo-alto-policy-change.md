# Runbook: Palo Alto policy change caused an outage

**When to use:** a recent Panorama commit/push correlates with the start of an
incident. Rules are evaluated top-down, first match wins, so a broad `deny`
placed above a specific `allow` will silently shadow it.

**Detect:**
- `GET /api/panorama/rules` and look for a rule whose name references a change ID
  (e.g. `block-*-CHG0092841`) sitting above the expected `allow`.
- Firewall traffic logs show `DENY ... rule=<that rule>` at high rate.

**Fix (change-controlled):**
- Disable/delete the offending rule, or move the specific `allow` above it.
- Commit and push to the affected device group.
- Verify with a policy match test for the impacted flow.

**Prevention:** pre-commit policy linting in CI, and a shadowed-rule check before
push.
