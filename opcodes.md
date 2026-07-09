# CHI Coherent Opcodes Reference

> Based on AMBA CHI Architecture Specification (Issue E / F)
> Covers: RN-initiated request opcodes, HN behavior, and Credit-Based Flow Control

---

## Table of Contents

1. [Overview](#overview)
2. [CHI Node Types](#chi-node-types)
3. [Channel Overview](#channel-overview)
4. [RN-Initiated Request Opcodes](#rn-initiated-request-opcodes)
   - [Read Requests](#read-requests)
   - [Write Requests](#write-requests)
   - [Atomic Requests](#atomic-requests)
   - [Cache Maintenance Operations (CMO)](#cache-maintenance-operations-cmo)
   - [Stash Requests](#stash-requests)
   - [Miscellaneous Requests](#miscellaneous-requests)
5. [HN Behavior on Receiving Requests](#hn-behavior-on-receiving-requests)
6. [Credit-Based Flow Control](#credit-based-flow-control)
   - [Requester Credits (RN side)](#requester-credits-rn-side)
   - [Completer Credits (HN/SN side)](#completer-credits-hnsn-side)

---

## Overview

CHI (Coherent Hub Interface) is ARM's protocol for cache-coherent communication
between Request Nodes (RN), Home Nodes (HN), and Subordinate Nodes (SN).

All transactions are initiated by an **RN** (Request Node). The **HN** (Home Node)
acts as the coherency manager and orchestrates snoops, data responses, and
completion acknowledgments.

---

## CHI Node Types

| Node Type | Description |
|-----------|-------------|
| **RN-F**  | Fully coherent Request Node (e.g., CPU cluster) |
| **RN-D**  | DVM-only Request Node |
| **RN-I**  | Non-coherent Request Node (e.g., I/O master) |
| **HN-F**  | Fully coherent Home Node (with snoop filter/directory) |
| **HN-I**  | Non-coherent Home Node |
| **SN-F**  | Fully coherent Subordinate Node (e.g., memory controller) |
| **SN-I**  | Non-coherent Subordinate Node |

---

## Channel Overview

CHI uses the following logical channels:

| Channel | Abbreviation | Direction         | Purpose                              |
|---------|-------------|-------------------|--------------------------------------|
| Request | REQ         | RN → HN           | Transaction requests                 |
| Snoop   | SNP         | HN → RN           | Snoop requests to coherent RNs       |
| Response| RSP         | RN ↔ HN ↔ SN     | Completion, acknowledgment signals   |
| Data    | DAT         | RN ↔ HN ↔ SN     | Data transfer (read/write data)      |

---

## RN-Initiated Request Opcodes

### Read Requests

These opcodes are used by the RN to fetch data from the system, with varying
cache state intentions.

---

#### `ReadNoSnp`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | `0x00` |
| **Channel** | REQ (RN → HN-I or HN-F) |
| **Used by** | RN-I, RN-F (for non-coherent reads) |

**What RN does:**
Requests a read of a cache line without requiring coherency. Used for
non-coherent masters or when the RN does not intend to cache the data.

**What HN does:**
- Forwards the request to the appropriate SN.
- Returns data via DAT channel with `DataSepResp` or `CompData`.
- No snoops are issued.
- Sends `Comp` or `CompData` to complete the transaction.

**Usage:** Peripheral/IO reads, non-cacheable memory accesses.

---

#### `ReadOnce`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | `0x01` |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests a single read of a cache line. The RN does **not** intend to keep
the line cached after use (transient read).

**What HN does:**
- May snoop other RNs if the line could be dirty.
- Returns data in `UC` (Unique Clean) or `SC` (Shared Clean) state.
- Sends `CompData` or `DataSepResp` + `RespSepData`.
- Line is not tracked in the snoop filter after completion.

**Usage:** Streaming reads, software prefetch with no retention intent.

---

#### `ReadOnceCleanInvalid`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | `0x02` |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Read the line once and hint to the HN that any cached copy should be
invalidated after the read (cache-friendly hint for streaming).

**What HN does:**
- Snoops with `SnpOnce` or `SnpCleanInvalid` as appropriate.
- Returns data and invalidates other cached copies.

**Usage:** Streaming workloads where cached copies are no longer useful.

---

#### `ReadOnceMakeInvalid`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | `0x03` |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Read the line once and request that all cached copies (including dirty data)
be invalidated. Data may be discarded rather than written back.

**What HN does:**
- Issues `SnpMakeInvalid` to other RNs.
- Returns data (possibly discarding dirty data per policy).

**Usage:** Bulk invalidation with a final read pass.

---

#### `ReadClean`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | `0x04` |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests a cache line in a clean state (`UC` or `SC`). The RN intends to
cache the line but will not modify it (or will use a separate upgrade).

**What HN does:**
- Snoops other RNs if needed to ensure no dirty copy exists.
- Returns line in `UC` or `SC` state.
- Updates snoop filter.

**Usage:** Read-only data sharing between multiple cores.

---

#### `ReadNotSharedDirty`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | `0x05` |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests a cache line in `UC`, `SC`, or `UD` (Unique Dirty) state — but
explicitly **not** in `SD` (Shared Dirty) state.

**What HN does:**
- Snoops as needed.
- Ensures the returned state is not `SD`.
- May return `UC` or `UD`.

**Usage:** When the RN wants exclusive or clean access, avoiding shared-dirty
overhead.

---

#### `ReadShared`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | `0x06` |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests a cache line in any shared or unique state (`UC`, `SC`, `UD`, `SD`).
Most permissive read — the RN accepts whatever state the HN provides.

**What HN does:**
- Checks snoop filter/directory.
- May snoop other RNs.
- Returns data in the most efficient available state.
- Updates snoop filter.

**Usage:** General-purpose cacheable reads (most common read opcode).

---

#### `ReadUnique`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | `0x07` |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests exclusive ownership of a cache line (intends to write). The RN
expects the line in `UC` or `UD` state with no other sharers.

**What HN does:**
- Issues invalidating snoops (`SnpUnique`) to all other RNs holding the line.
- Collects dirty data if any RN has a dirty copy.
- Returns line in `UC` or `UD` state.
- Removes all other entries from snoop filter.

**Usage:** Write-before-read (full cache line overwrite), acquiring exclusive
ownership.

---

#### `ReadPreferUnique`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | `0x08` |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Like `ReadShared` but with a preference for unique state. The RN will accept
shared state if unique is not available without extra cost.

**What HN does:**
- Returns `UC`/`UD` if possible without additional snoops.
- Falls back to `SC`/`SD` if other sharers exist and snooping would be costly.

**Usage:** Optimistic exclusive reads (e.g., lock acquisition attempts).

---

### Write Requests

---

#### `WriteNoSnpFull` / `WriteNoSnpPtl`

| Field       | Detail |
|-------------|--------|
| **Opcodes** | `WriteNoSnpFull`: Full cache line write (no snoop) |
|             | `WriteNoSnpPtl`: Partial cache line write (no snoop) |
| **Channel** | REQ (RN → HN-I) |
| **Used by** | RN-I, RN-F (non-coherent writes) |

**What RN does:**
Writes data to memory without coherency involvement. Sends data on DAT channel
after receiving `DBIDResp` from HN.

**What HN does:**
- Responds with `DBIDResp` (Data Buffer ID) to grant the RN permission to send data.
- Receives write data on DAT channel.
- Forwards to SN.
- Sends `Comp` to RN on completion.

**Usage:** Non-coherent DMA writes, MMIO writes.

---

#### `WriteUniqueFull` / `WriteUniquePtl`

| Field       | Detail |
|-------------|--------|
| **Opcodes** | `WriteUniqueFull`: Full line write with coherency |
|             | `WriteUniquePtl`: Partial line write with coherency |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Writes data to a cache line. The RN must not hold the line in cache after
the write (write-and-invalidate semantics). Sends data after `DBIDResp`.

**What HN does:**
- Issues `SnpUniqueFwd` or `SnpInvalid` snoops to invalidate other copies.
- Sends `DBIDResp` to RN.
- Receives write data.
- Merges with any dirty snoop response data.
- Sends `Comp` to RN.

**Usage:** Producer-consumer patterns, write-invalidate coherency.

---

#### `WriteUniqueFullStash` / `WriteUniquePtlStash`

| Field       | Detail |
|-------------|--------|
| **Opcodes** | Stash variants of WriteUnique |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Writes data and requests that the HN stash (pre-load) the data into a
target RN's cache for future use.

**What HN does:**
- Processes the write as `WriteUnique`.
- Additionally issues a `SnpStash` to the target RN specified in the request.

**Usage:** Software-directed prefetch/stash optimizations.

---

#### `WriteBackFull` / `WriteBackPtl`

| Field       | Detail |
|-------------|--------|
| **Opcodes** | Eviction write-back of dirty data |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Evicts a dirty cache line back to the HN. The RN transitions the line to
`Invalid` state after the write-back.

**What HN does:**
- Sends `DBIDResp` or `CompDBIDResp`.
- Receives dirty data on DAT channel.
- Updates memory/SN.
- Sends `Comp` if not already combined.

**Usage:** Cache eviction of dirty (Modified) lines.

---

#### `WriteCleanFull`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | Clean dirty data, retain in cache |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Writes back dirty data to memory but **retains** the line in cache in a
clean state (`SC` or `UC`).

**What HN does:**
- Sends `DBIDResp`.
- Receives data.
- Updates memory.
- Sends `Comp`. Line remains tracked in snoop filter.

**Usage:** Cache clean operations (e.g., DMA coherency flush without eviction).

---

#### `WriteEvictFull`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | Evict clean line |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Notifies HN that a clean cache line is being evicted. No data is sent
(line is clean, memory is up to date).

**What HN does:**
- Updates snoop filter to remove the RN's entry.
- Sends `Comp`.
- No data transfer required.

**Usage:** Capacity eviction of clean lines — lightweight notification.

---

#### `WriteNoSnpZero` / `WriteUniqueZero`

| Field       | Detail |
|-------------|--------|
| **Opcodes** | Zero-data write variants |
| **Channel** | REQ (RN → HN) |
| **Used by** | RN-F, RN-I |

**What RN does:**
Requests a zero-data write — signals intent to write zeros without
actually transferring data on the DAT channel.

**What HN does:**
- Generates zero data internally and writes to memory.
- No DAT channel transfer needed from RN.
- Sends `Comp`.

**Usage:** Memory zeroing/initialization optimizations.

---

### Atomic Requests

---

#### `AtomicStore`

| Field       | Detail |
|-------------|--------|
| **Opcodes** | `AtomicStore{ADD, CLR, EOR, SET, SMAX, SMIN, UMAX, UMIN}` |
| **Channel** | REQ (RN → HN-F or SN) |
| **Used by** | RN-F, RN-I |

**What RN does:**
Sends an atomic store operation with data. The operation is performed
atomically at the HN or SN. No return data expected.

**What HN does:**
- Forwards to SN if non-cacheable, or handles at HN if cacheable.
- Performs the atomic operation.
- Sends `Comp` (no data returned).

**Usage:** Atomic counters, flags, non-return atomics.

---

#### `AtomicLoad`

| Field       | Detail |
|-------------|--------|
| **Opcodes** | `AtomicLoad{ADD, CLR, EOR, SET, SMAX, SMIN, UMAX, UMIN}` |
| **Channel** | REQ (RN → HN-F or SN) |
| **Used by** | RN-F, RN-I |

**What RN does:**
Sends an atomic load-op. The old value of the memory location is returned
to the RN.

**What HN does:**
- Performs the atomic read-modify-write.
- Returns the **original** (pre-operation) value via DAT channel (`CompData`).

**Usage:** Fetch-and-add, fetch-and-or style operations.

---

#### `AtomicSwap`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | Atomic swap |
| **Channel** | REQ (RN → HN-F or SN) |
| **Used by** | RN-F, RN-I |

**What RN does:**
Sends a new value; atomically swaps it with the current memory value.
Receives the old value.

**What HN does:**
- Atomically swaps memory contents with the provided value.
- Returns old value via `CompData`.

**Usage:** Lock acquisition, exchange primitives.

---

#### `AtomicCompare`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | Compare-and-swap (CAS) |
| **Channel** | REQ (RN → HN-F or SN) |
| **Used by** | RN-F, RN-I |

**What RN does:**
Sends a compare value and a swap value. If memory matches the compare
value, it is replaced with the swap value.

**What HN does:**
- Performs CAS atomically.
- Returns the original memory value regardless of success/failure.

**Usage:** Lock-free data structures, CAS loops.

---

### Cache Maintenance Operations (CMO)

---

#### `CleanUnique`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests to clean (write back if dirty) and obtain unique ownership of a
cache line. The RN currently holds the line in a shared state and wants
to upgrade to unique/writable.

**What HN does:**
- Issues `SnpCleanInvalid` or `SnpUnique` to other sharers.
- Collects dirty data if needed.
- Sends `Comp` with `RetToSrc` indication.
- RN transitions line to `UC`.

**Usage:** Write upgrade — shared → unique (e.g., copy-on-write).

---

#### `MakeUnique`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests unique ownership without needing the data returned (RN will
overwrite the entire line). Faster than `ReadUnique` when full line
is being written.

**What HN does:**
- Issues `SnpMakeInvalid` to all other RNs.
- Sends `Comp` (no data returned to requester).
- RN transitions to `UC` and writes its own data.

**Usage:** Full cache line write with prior shared ownership — avoids
unnecessary data fetch.

---

#### `CleanShared`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests that a dirty cache line be cleaned (written back to memory)
across the system, without invalidating any copies.

**What HN does:**
- Issues `SnpCleanShared` to all RNs with the line.
- Dirty copies are written back to memory.
- All copies transition to clean state.
- Sends `Comp`.

**Usage:** DMA coherency — ensure memory is up to date before DMA read.

---

#### `CleanSharedPersist` / `CleanSharedPersistSep`

| Field       | Detail |
|-------------|--------|
| **Opcodes** | Persistent clean (to persistent memory) |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Like `CleanShared` but additionally requests that data be persisted to
persistent memory (e.g., NVDIMM). `Sep` variant separates the completion
of coherency clean from persistence acknowledgment.

**What HN does:**
- Cleans all dirty copies.
- Issues persistence request to SN.
- Sends `Comp` and optionally `PersistComp` separately.

**Usage:** Persistent memory (PMEM) coherency and durability.

---

#### `CleanInvalid`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests that a cache line be cleaned (if dirty) and invalidated across
all RNs in the system.

**What HN does:**
- Issues `SnpCleanInvalid` to all RNs.
- Dirty data written back to memory.
- All copies invalidated.
- Sends `Comp`.

**Usage:** Full system cache flush for a line (e.g., before hardware
reconfiguration or power management).

---

#### `MakeInvalid`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests invalidation of a cache line across all RNs **without** writing
back dirty data (dirty data may be discarded).

**What HN does:**
- Issues `SnpMakeInvalid` to all RNs.
- Dirty data is discarded (not written to memory).
- Sends `Comp`.

**Usage:** Discard-and-invalidate — when dirty data is no longer needed
(e.g., freed memory regions).

---

### Stash Requests

---

#### `StashOnceUnique` / `StashOnceShared`

| Field       | Detail |
|-------------|--------|
| **Opcodes** | Software-directed prefetch/stash |
| **Channel** | REQ (RN → HN-F) |
| **Used by** | RN-F |

**What RN does:**
Requests that the HN pre-load (stash) a cache line into a target RN's
cache in either unique or shared state, in anticipation of future use.

**What HN does:**
- Issues `SnpStashUnique` or `SnpStashShared` to the target RN.
- Target RN may accept or decline the stash (hint only).
- Sends `Comp` to the requesting RN.

**Usage:** Software prefetch hints, producer-consumer pre-staging.

---

### Miscellaneous Requests

---

#### `DVMOp`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | Distributed Virtual Memory operation |
| **Channel** | REQ (RN → MN / HN) |
| **Used by** | RN-F, RN-D |

**What RN does:**
Sends a DVM (TLB/BTB/I-cache) invalidation message to the system.
Used to maintain virtual memory coherency across cores.

**What HN does:**
- Broadcasts `SnpDVMOp` to all relevant RNs.
- Collects acknowledgments.
- Sends `Comp` to the requesting RN.

**Usage:** TLB shootdowns, instruction cache invalidations, branch
predictor invalidations.

---

#### `PCrdReturn`

| Field       | Detail |
|-------------|--------|
| **Opcode**  | Protocol Credit Return |
| **Channel** | REQ (RN → HN) |
| **Used by** | RN-F, RN-I |

**What RN does:**
Returns a protocol credit that was previously granted by the HN but
is no longer needed by the RN.

**What HN does:**
- Reclaims the credit for reuse.
- No completion response sent.

**Usage:** Credit management — returning unused protocol credits.

---

## HN Behavior on Receiving Requests

The HN-F follows this general pipeline for most requests:

```
1. Receive REQ from RN
   ↓
2. Allocate a transaction tracker (TXN ID)
   ↓
3. Lookup snoop filter / directory
   ↓
4. Determine snoop action (if any)
   ↓
5. Issue snoops to relevant RNs (SNP channel)
   ↓
6. Collect snoop responses (RSP/DAT from snooped RNs)
   ↓
7. Issue request to SN if memory access needed
   ↓
8. Receive data from SN or snooped RN
   ↓
9. Forward data to requesting RN (DAT channel)
   ↓
10. Send Comp / CompData / CompDBIDResp to RN
    ↓
11. Wait for CompAck from RN (if required)
    ↓
12. Update snoop filter / directory
    ↓
13. Deallocate transaction tracker
```

### Key HN Response Opcodes

| Opcode           | Direction  | Meaning |
|------------------|------------|---------|
| `CompData`       | HN → RN    | Completion with data |
| `DataSepResp`    | HN → RN    | Data part of separate response |
| `RespSepData`    | HN → RN    | Response part of separate response |
| `Comp`           | HN → RN    | Completion without data |
| `CompDBIDResp`   | HN → RN    | Combined completion + data buffer ID |
| `DBIDResp`       | HN → RN    | Data buffer ID (permission to send write data) |
| `RetryAck`       | HN → RN    | Retry — no resources available, send PCrdRequest |
| `PCrdGrant`      | HN → RN    | Protocol credit granted (retry now allowed) |

---

## Credit-Based Flow Control

CHI uses two types of credit-based flow control to prevent deadlock and
manage buffer resources:

### 1. Link-Level Credits (L-Credits)

- Operate at the **physical channel level**.
- Control the number of flits that can be sent on a channel.
- Managed independently per channel (REQ, RSP, DAT, SNP).
- Sender can only transmit when it holds L-Credits.
- Receiver returns L-Credits as it frees buffer space.
- **Not directly visible** to the protocol layer.

---

### 2. Protocol-Level Credits (P-Credits)

Protocol credits control the number of **outstanding transactions** that
an RN can have in flight toward an HN.

---

### Requester Credits (RN Side)

The RN must hold a **Protocol Credit (P-Credit)** before sending most
request types to the HN.

#### Flow:

```
RN                          HN
 |                           |
 |--- PCrdRequest (REQ) ---->|   (RN requests a protocol credit)
 |                           |
 |<-- PCrdGrant (RSP) -------|   (HN grants credit when resources available)
 |                           |
 |--- [Actual Request] ----->|   (RN sends request using the credit)
 |                           |
 |<-- RetryAck (RSP) --------|   (If HN can't accept: retry later)
```

#### Key Points:
- The RN sends a `PCrdRequest` to ask for a protocol credit.
- The HN responds with `PCrdGrant` when it has tracker resources available.
- If the HN cannot accept a new transaction immediately, it responds with
  `RetryAck` to the original request, and the RN must wait for `PCrdGrant`
  before retrying.
- `PCrdReturn` is sent by the RN to return an unused granted credit.

#### Credit Types (`CreditType` field):

| Value | Credit Type     | Used For |
|-------|-----------------|----------|
| `0x0` | `DontCare`      | Any request type |
| `0x1` | `ReadNoSnp`     | Non-coherent reads |
| `0x2` | `ReadOnce` etc. | Coherent reads |
| `0x3` | `WriteNoSnp`    | Non-coherent writes |
| `0x4` | `WriteUnique`   | Coherent writes |
| `0x5` | `Atomic`        | Atomic operations |
| `0x6` | `DVMOp`         | DVM operations |
| `0x7` | `StashOnce`     | Stash operations |

> ⚠️ Exact credit type encodings vary by CHI revision — always refer to
> your specific spec version.

---

### Completer Credits (HN/SN Side)

The **completer** (HN or SN) uses credits to manage its internal resources
such as:
- **Transaction trackers** (one per in-flight transaction)
- **Data buffers** (for write data)
- **Snoop filter entries**

#### DBIDResp — Data Buffer Credit

When an RN sends a write request, it must wait for the HN to grant a
**Data Buffer ID (DBID)** before sending write data:

```
RN                              HN
 |                               |
 |--- WriteUniqueFull (REQ) ---->|
 |                               |
 |<-- DBIDResp (RSP) ------------|   (HN allocates a data buffer, grants DBID)
 |                               |
 |--- Write Data (DAT, DBID=X) ->|   (RN sends data using the DBID)
 |                               |
 |<-- Comp (RSP) ----------------|   (HN confirms write complete)
```

- The `DBID` field in `DBIDResp` identifies which buffer the data should
  be associated with.
- The RN **must not** send write data until it receives `DBIDResp` or
  `CompDBIDResp`.
- `CompDBIDResp` combines `Comp` + `DBIDResp` in a single response for
  efficiency.

#### CompAck — Requester Acknowledgment

For certain transactions, the HN requires the RN to send a `CompAck`
after receiving `Comp` or `CompData`:

```
RN                              HN
 |                               |
 |<-- CompData (DAT) ------------|
 |                               |
 |--- CompAck (RSP) ------------>|   (RN confirms it received completion)
 |                               |
 (HN can now safely deallocate tracker)
```

- `CompAck` is required for transactions that modify the snoop filter
  (e.g., `ReadUnique`, `CleanUnique`, `MakeUnique`).
- It prevents the HN from issuing a snoop before the RN has processed
  the completion — avoiding protocol hazards.
- The `ExpCompAck` bit in the request indicates whether `CompAck` is expected.

---

### Credit Flow Summary Table

| Credit Type      | Direction    | Purpose |
|------------------|--------------|---------|
| **L-Credit**     | Bidirectional| Link-level flit flow control |
| **P-Credit**     | HN → RN      | Protocol-level transaction slots |
| **DBID**         | HN → RN      | Write data buffer allocation |
| **CompAck**      | RN → HN      | Transaction completion confirmation |
| **PCrdReturn**   | RN → HN      | Return unused P-Credit |

---

### Deadlock Avoidance

CHI's credit system is carefully designed to avoid deadlock:

1. **Retry mechanism**: `RetryAck` + `PCrdGrant` ensures the HN never
   silently drops requests.
2. **Ordered credit return**: L-Credits are returned in a defined order
   to prevent circular dependencies.
3. **Separate channels**: REQ, RSP, DAT, SNP channels have independent
   credit pools — a stall on one channel does not block another.
4. **CompAck ordering**: Ensures snoop filter updates happen only after
   the RN has acknowledged completion, preventing race conditions.

---

*Document generated from CHI Architecture Specification knowledge base.*
*Always cross-reference with your specific CHI Issue (E/F/G) for exact encodings.*