# Raft: Understandable Consensus

Raft divides time into **terms**, numbered consecutively. Each term begins with an
election. A server is always in one of three states: follower, candidate, or leader.

## Leader election

Followers expect periodic heartbeats (empty AppendEntries) from the leader. A
follower that receives no heartbeat within its **election timeout** becomes a
candidate: it increments the current term, votes for itself, and sends RequestVote
to every other server. A candidate becomes leader once it receives votes from a
**majority** of the cluster.

Election timeouts are randomised, typically between 150ms and 300ms. Without
randomisation, followers would time out simultaneously, split the vote, and repeat
the election indefinitely. Randomisation makes one server time out first in the
common case, so most elections finish in a single round.

A server grants its vote only if the candidate's log is **at least as up to date**
as its own, compared first by the term of the last entry and then by log length.
This restriction is what guarantees that a newly elected leader already holds every
committed entry.

## Log replication

All client requests go to the leader. The leader appends the command to its own log
and sends AppendEntries to followers in parallel. Once an entry is stored on a
majority of servers the leader marks it **committed**, applies it to its state
machine, and returns the result to the client.

AppendEntries carries the index and term of the entry immediately preceding the new
ones. A follower rejects the request if its log does not match at that point. The
leader then decrements its nextIndex for that follower and retries, and this
backtracking converges the follower's log onto the leader's.

## Safety

Raft never overwrites entries in the leader's own log; conflicts are always resolved
in the leader's favour on followers. Combined with the up-to-date voting restriction,
this yields the State Machine Safety property: if a server has applied an entry at a
given index, no other server will ever apply a different entry at that index.

## Membership changes

Naively switching configurations can produce two disjoint majorities and therefore
two leaders. Raft uses **joint consensus**: an intermediate configuration in which
decisions require majorities from both the old and the new configuration. Once the
joint configuration is committed, the cluster transitions to the new one alone.
