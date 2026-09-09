# Paxos and Multi-Paxos

Paxos solves consensus among unreliable processes. A single instance of the
protocol, **Basic Paxos**, agrees on exactly one value.

## Roles and phases

Processes act as proposers, acceptors, and learners; one process usually plays all
three roles. Basic Paxos runs in two phases:

1. **Prepare.** A proposer picks a proposal number n and sends Prepare(n) to a
   majority of acceptors. An acceptor that has not already responded to a higher
   number promises never to accept a proposal below n, and returns the
   highest-numbered proposal it has already accepted.
2. **Accept.** If the proposer hears back from a majority, it sends Accept(n, v).
   The value v must be the value of the highest-numbered proposal returned in phase
   one; only if no acceptor had accepted anything may the proposer choose freely.

A value is chosen once a majority of acceptors have accepted it. Because any two
majorities intersect, no two different values can ever be chosen.

## Multi-Paxos

Running Basic Paxos per command costs two round trips. **Multi-Paxos** elects a
stable distinguished proposer — effectively a leader — and skips phase one for
subsequent commands, reducing the steady state to a single round trip. Phase one is
re-run only when leadership changes.

## Comparison with Raft

Paxos and Raft make the same safety guarantees and both require a majority quorum,
but they differ in structure:

- **Leadership.** In Paxos a leader is an optimisation layered on top of the
  protocol. In Raft leadership is fundamental, and the protocol is defined in terms
  of it.
- **Log handling.** Paxos allows holes in the log, with instances agreed out of
  order and reconciled later. Raft requires logs to be contiguous and enforces the
  Log Matching property, which is what makes its recovery so simple.
- **Election restriction.** Raft forbids electing a leader whose log is missing
  committed entries. Paxos permits it and recovers the missing values through phase
  one instead.

The Raft authors argue this structure is the whole point: the two protocols are
comparable in performance, but Raft is specified in a way that is easier to
implement correctly.
