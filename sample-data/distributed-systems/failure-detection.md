# Failure Detection and Split Brain

## Heartbeats and timeouts

The usual failure detector is a heartbeat: each process periodically announces that
it is alive, and a peer that hears nothing within a timeout marks it suspect. The
timeout is a direct trade-off. A short one detects failures quickly but produces
false positives whenever the network is briefly slow; a long one is accurate but
leaves the system degraded for longer.

No failure detector on an asynchronous network can be both complete and accurate,
because a crashed process and an arbitrarily slow one are indistinguishable from the
outside.

## Phi accrual detection

Rather than a boolean verdict, a **phi accrual** detector outputs a suspicion level.
It keeps a sliding window of recent heartbeat inter-arrival times, fits a
distribution to them, and reports phi — the log-likelihood that a heartbeat this
late indicates failure. Applications choose their own threshold, so a cautious
component and an aggressive one can share a single detector. Because the window
adapts, the detector tightens on a fast network and loosens on a congested one
without any reconfiguration.

## Split brain

**Split brain** is two halves of a partitioned cluster both believing they lead,
each accepting writes. Reconciling the result afterwards is lossy at best.

Quorums are the standard defence: requiring a majority means at most one side can
make progress, since two majorities of the same cluster must intersect. A cluster
with an even number of nodes gains nothing over the next odd size down — a four-node
cluster tolerates one failure, exactly like a three-node one — so odd sizes are
conventional.

**Fencing** protects shared resources. A leader is issued a monotonically increasing
token; the resource rejects any token lower than the highest it has already seen, so
a deposed leader whose writes were merely delayed is refused.
