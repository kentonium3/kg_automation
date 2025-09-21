# Execution Context Identification (ECI)

**Goal:** Allow any AI/agent/script to know *where it is executing* without broadcasting presence.

## Core ideas
- Each machine asserts a **local-only identity** (beacon file and/or env var). No cloud broadcast required.
- Workers (Claude/agents) read local identity and only claim jobs that match.
- Jobs specify `requested_executor` as machine IDs and/or capability labels.

## Local beacons (keep private)
- **Windows:** `C:\temp\MACHINE_ID_<n>.txt`
- **macOS:** `~/Library/Application Support/KG/MACHINE_ID_<n>.txt`
- Optional env var: `KG_PLATFORM=<n>`
- Policy: Machine ID files must **not** live in Dropbox (avoid cross-system confusion). See Machine ID policy in the migration docs. 

## Worker matching (summary)
1. Read local machine ID (beacon → env → hostname).
2. Peek at job JSON:
   - If `requested_executor` is empty → eligible to claim.
   - If `requested_executor` includes this machine (or role it provides) → claim.
   - Otherwise → skip.
3. On claim, move job to `claimed/` and proceed as usual.

## Why no heartbeat?
- You rarely log out, may work on both machines in one session, and agents will distribute work across them.
- We only need **execution context**, not "presence." This keeps the system reliable and simpler to operate.

## Optional: Prompt tags on mobile
For voice prompting (iPhone/iPad), you can still use tiny prompt tags like `[KG:P:iPhone]` to give AIs quick context, but execution never depends on them.

## Relationship to Job Protocol
The job contract remains JSON-based. ECI ensures the right worker picks up the right job without any presence broadcasting.
