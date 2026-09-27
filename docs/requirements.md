# DockFlow API — Requirements and the Five Questions

This document applies the requirements method from the *System Design* guide
(functional vs non-functional requirements, then the five questions asked before
any box is drawn) to the DockFlow API. It describes what the system is for and
how well it must do it. No architecture is decided here beyond what the answers
force into existence.

DockFlow is not a consumer photo app; it is a multi-tenant backend where tenants
(applications and organizations) submit documents and receive structured data
extracted by an LLM. That difference changes several answers, and the contrast
is called out where it matters.

---

## 1. Functional (core) requirements

Each is a feature you can see and test. If one is missing, the product is
visibly incomplete.

- A tenant account can be **created** and can **log in**, receiving an API key.
- A tenant **authenticates every request** with that API key.
- A tenant can **submit a document** (PDF, PNG, JPEG, TIFF, or DOCX) together
  with an **extraction schema** describing the fields to pull out.
- The system **extracts text** from the document and runs **schema-driven LLM
  extraction**, producing structured JSON.
- A tenant can **poll a job** for its status, progress, and final result.
- A tenant can **list their jobs** (paginated) and **cancel** a job that has not
  started processing.
- A tenant can register a **webhook** and be called back when a job completes.
- **Duplicate submissions** of the same file are detected rather than silently
  re-processed.

---

## 2. Non-functional requirements

These describe quality, not features. Nobody points at them in a demo, yet
everybody feels them when they are missing.

- **Availability.** The submit and status endpoints must stay up; a tenant's
  automation breaks the moment they cannot enqueue or check a job.
- **Latency.** Submission must acknowledge quickly. Extraction itself is
  asynchronous and may take seconds to minutes. Status polling must be cheap
  because clients poll it repeatedly.
- **Durability.** An uploaded file and a completed result must not be lost.
  Job records and their terminal status must survive a crash. Transient progress
  text is disposable.
- **Scale.** Many tenants, bursty submissions, and single documents large enough
  to require map-reduce across many model calls.
- **Tenant isolation and security.** Keys are hashed, every query is scoped to
  the owning tenant, and webhook destinations cannot be turned into internal
  network probes.
- **Cost.** LLM tokens dominate the bill. A design that wastes model calls is
  expensive regardless of how few servers it runs on.

### Non-functional requirements fight each other

You cannot buy everything on the menu. Stronger durability means more copies of
each file and result, which costs money. Higher availability means spare workers
sitting idle between bursts, and idle workers still bill you. Lower latency on
the compute path means more concurrent model calls, which raises both spend and
the risk of hitting provider rate limits. The job here is to decide what DockFlow
must have and what it can live without — the five questions below make that call.

---

## 3. The five questions

### 1. How many users, and how fast are they growing?

The "users" are **tenants**, and load is measured in **jobs**, not human page
views. One tenant integrating DockFlow into a pipeline can submit thousands of
documents in a batch, so per-tenant burstiness matters as much as tenant count.

Design toward the volume we are heading for, without provisioning for it today.
The architecture should evolve — stateless API replicas behind a load balancer,
a worker pool that scales on queue depth — without those pieces being switched on
prematurely. DockFlow already separates the API from the worker fleet, which is
the split that makes this evolution possible.

> Build a system for today's load whose architecture can grow, not today's load
> running on tomorrow's infrastructure.

### 2. Is the app read-heavy or write-heavy?

This is where DockFlow differs sharply from the photo app. The photo app is
read-heavy: people scroll far more than they post, so effort goes on the feed.

DockFlow is **compute-heavy on ingest**. Every submission triggers expensive
work — download, OCR or parse, then one or many LLM calls with a merge phase.
Reads (status polling, listing) are **frequent but individually trivial**.

So effort splits two ways:

- **The processing path is where the cost and the hard engineering live**: token
  budgeting, concurrency control, deduplication, and result caching. This is the
  equivalent of "the feed" — the part worth optimizing.
- **The status path must stay cheap under a high poll rate**: serve progress from
  a fast store so repeated polling does not hammer the primary database.

### 3. What can you never lose, and what can you afford to lose?

| Never lose | Can afford to lose |
|------------|--------------------|
| The uploaded file (until processed, per retention policy) | Transient progress text and percentages |
| A completed extraction result | In-flight non-terminal state (re-run recomputes it) |
| The job record and its terminal status | The duplicate-detection filter (rebuildable) |
| Tenant credentials | Circuit-breaker counters (they re-accrue) |

Losing a completed result means either re-paying for LLM work or handing the
customer nothing. That is where durability money goes: the primary database
(job records and results) with backups, and object storage (files) with
versioning and a lifecycle policy. Progress lives in an ephemeral store on
purpose — losing it costs nothing because it can be recomputed or simply moves on.

### 4. How much latency can you afford?

The guide's asymmetry gift applies directly, and DockFlow is built around it:

- **Submission** should return almost immediately (an accepted-and-queued
  acknowledgement), on the order of a few hundred milliseconds.
- **Status polling** should be fast (tens of milliseconds) because clients call
  it in a loop.
- **Extraction** is allowed to be slow — seconds to minutes — because it runs
  asynchronously on the worker fleet, out of the request path.

That asymmetry is the design gift: because processing is off the request path,
all the heavy, slow, expensive work can happen there while the two
tenant-facing paths stay fast.

*(One honest gap: today submission reads the whole file into memory and uploads
it to storage inside the request, so the "fast submit" promise weakens for large
files. Streaming the upload restores it. Noted here as a requirement the current
design does not fully meet, not fixed in this document.)*

### 5. What does it cost?

For DockFlow the dominant cost is **LLM tokens**, not servers. Every unnecessary
chunk is a paid model call, so the largest cost levers are on the processing
path: accurate token budgeting so documents are not split into more chunks than
the context truly requires, deterministic merging where the model is not needed,
and caching results for identical file-and-schema inputs so the same work is not
paid for twice. Server and storage cost is secondary and grows slowly by
comparison.

> Start simple, measure the system, and add complexity only when there is a
> demonstrated need.

DockFlow already sits at a sensible altitude — one deployable API plus a worker
pool, with Redis, PostgreSQL, and object storage — rather than a premature spread
of microservices. That restraint is the correct application of this question.

---

## 4. What the five questions gave us

No new architecture has been drawn, and we already know:

- The **processing path** (extraction plus LLM) is both the hard part and the
  expensive part; engineering effort and cost control belong there.
- **Results and uploaded files** need the strongest durability, while **progress**
  is disposable and belongs in an ephemeral store.
- **Submit and status must stay fast** while **processing is allowed to be slow**,
  because it runs asynchronously — the latency asymmetry is the system's backbone.
- The **monolith-plus-worker** shape is the right first structural decision. The
  guide's own advice is to split into services only when independent scaling or
  team size forces it, and neither forces it yet.

That is what having requirements means: before drawing a single new box, the
shape of the problem is already clear.
