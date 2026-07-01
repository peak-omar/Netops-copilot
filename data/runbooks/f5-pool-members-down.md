# Runbook: F5 pool members down / VIP degraded

**Symptoms:** `checkout_vip` shows `degraded` or `offline`; one or more pool
members are `down`.

**Key insight:** F5 health monitors are usually a *symptom detector*, not the
root cause. If members go down together with `/healthz` returning 503, the app
behind them is failing - check the workload and its downstream dependencies
(database, cache, upstream APIs) before touching the load balancer.

**Triage order:**
1. `GET /api/f5/pool/<pool>` - how many members down, and the monitor reason.
2. Check the backing AKS workload for CrashLoop / not-ready pods.
3. Follow the pod error to its downstream dependency (often DB on 5432).

**Do not** simply force members up or restart the VIP - that masks the real
failure and prolongs the outage.
