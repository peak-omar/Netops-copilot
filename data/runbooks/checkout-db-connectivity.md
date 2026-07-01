# Runbook: Checkout API down - database connectivity

**Symptoms:** checkout-api pods in CrashLoopBackOff, F5 `checkout_pool` members
failing `/healthz`, `checkout_vip` degraded/offline, 5xx spike on checkout.

**Most common root cause:** the app-tier can no longer reach the checkout
database on TCP 5432. This is almost always one of:
1. A Palo Alto security policy change that denies `app-tier (10.20.0.0/16)` ->
   `db-tier (10.30.5.0/24)` on 5432 (look for a recently pushed rule / change ID).
2. A database outage or failover.
3. A NAT/route change.

**Triage:**
- Run a firewall policy match for `10.20.4.x -> 10.30.5.10:5432`. If `deny`,
  identify the matching rule and the change that introduced it.
- Correlate the firewall deny rate with the pod restart count and pool-down count.

**Remediation (requires human approval / change control):**
- Roll back or correct the offending Panorama rule so app-tier -> db-tier:5432 is
  `allow`, then commit + push.
- F5 pool members auto-recover once `/healthz` passes again.

**Owning team:** Network Engineering (firewall), with App On-call for validation.
