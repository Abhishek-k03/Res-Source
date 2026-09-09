# Replication, Quorums, and CAP

## Synchronous and asynchronous replication

Under **synchronous** replication the primary waits for acknowledgement from its
replicas before confirming a write to the client. No acknowledged write is lost if
the primary fails, but a slow or unreachable replica stalls every write.

Under **asynchronous** replication the primary confirms immediately and ships
changes in the background. Writes stay fast and a failed replica does not block the
system, but a primary that fails before shipping loses recently acknowledged writes.
**Semi-synchronous** replication is the usual compromise: wait for one replica, and
let the rest follow asynchronously.

## Quorums

With N replicas, a write quorum W, and a read quorum R, the overlap condition
W + R > N guarantees that any read set intersects any write set, so a read always
sees the most recent acknowledged write. With N=3, W=2, R=2 the system tolerates one
failure while remaining strongly consistent.

Setting W + R <= N gives lower latency and higher availability but permits stale
reads. Systems that make this trade-off usually add anti-entropy — read repair,
hinted handoff, or Merkle-tree synchronisation — so replicas converge eventually.

## CAP

The CAP theorem states that during a **network partition** a system must choose
between consistency and availability; it cannot have both. It says nothing about the
partition-free case, where a well-built system provides both.

CAP is often misread as a permanent three-way choice. PACELC extends it more
usefully: **if** there is a Partition, trade Availability against Consistency;
**else**, in normal operation, trade Latency against Consistency. Most production
systems spend nearly all their time in the "else" branch, which is why
latency-versus-consistency is the decision that actually shapes a design.
