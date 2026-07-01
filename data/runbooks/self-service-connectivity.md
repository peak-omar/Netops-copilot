# Runbook: Self-service connectivity / ACL checks (non-technical requesters)

**Purpose:** let app, product, and project teams answer common network questions
themselves instead of opening a ticket to Network Engineering.

**Supported questions:**
- "Can source IP X reach destination IP Y on port Z?" -> firewall policy match.
- "Is VIP <name> created and healthy?" -> F5 virtual server + pool status.
- "Is pool <name> healthy / how many members are up?" -> F5 pool health.

**When the answer is 'blocked' or 'unhealthy':** the assistant drafts a
ServiceNow request (firewall change or LB investigation) and asks a human to
approve before anything is filed. The agent never changes firewall or LB config
directly - approval + change control always stays with a person.

**Assignment groups:** firewall changes -> Network Engineering; LB/app health ->
App On-call with Network Engineering as watcher.
