# RFC: Replace PostgreSQL with Percona XtraDB Cluster for Multi-Master Replication

**Status:** Proposed
**Authors:** Database Platform Team
**Date:** 2024-03-20

## Summary

We propose replacing our PostgreSQL 15 primary-replica deployment with Percona XtraDB Cluster (PXC) 8.0 to achieve true multi-master replication with synchronous writes. Our current PostgreSQL setup suffers from replication lag during peak traffic, complex failover procedures, and an inability to scale writes horizontally. PXC's Galera-based synchronous replication provides multi-master writes, automatic node provisioning, and transparent failover — eliminating the operational pain of managing promotion and split-brain scenarios.

## Background

Our current database tier consists of:
- 1 PostgreSQL 15 primary (r6g.4xlarge) handling all writes
- 2 PostgreSQL 15 read replicas (r6g.2xlarge) for read scaling
- Streaming replication with async commit
- PgBouncer for connection pooling
- Manual failover via pg_promote + DNS update (~3-5 min downtime)

This architecture has served us for 3 years but is hitting limits:
- **Write bottleneck**: All writes funnel through a single primary. During flash sales and batch processing windows, write latency spikes to 200-400ms.
- **Replication lag**: Async streaming replication regularly falls 2-10 seconds behind during peak load, causing stale reads from replicas and occasional application errors.
- **Failover complexity**: Promoting a replica requires manual intervention, DNS propagation, connection pool draining, and sequence/slot verification. Our last unplanned failover took 4 minutes and 37 seconds.
- **Operational burden**: Managing replication slots, WAL retention, logical decoding slots for CDC, and replica drift detection requires significant DBA time.

## Proposed Solution

### Percona XtraDB Cluster 8.0

Deploy a 3-node Percona XtraDB Cluster using Galera synchronous replication:

- **Node 1**: us-east-1a (r6g.4xlarge) — write primary + reads
- **Node 2**: us-east-1b (r6g.4xlarge) — write primary + reads
- **Node 3**: us-east-1c (r6g.4xlarge) — write primary + reads

All three nodes accept writes simultaneously. Galera ensures every committed transaction is replicated to all nodes before acknowledgment (virtually synchronous — certification-based).

### Key architecture decisions

**Synchronous replication via Galera writeset certification**: Every transaction is certified across all nodes before commit. This eliminates replication lag entirely — reads from any node are always consistent. The tradeoff is slightly higher per-transaction latency (~2-5ms for certification), but our P99 write latency drops overall because we eliminate the single-writer bottleneck.

**ProxySQL for query routing**: Deploy ProxySQL in front of the cluster for:
- Automatic read/write splitting
- Connection pooling (replacing PgBouncer)
- Health-check based routing — removes nodes from rotation during SST/IST
- Query caching for hot read paths
- Graceful handling of cluster partition events

**Percona Monitoring and Management (PMM)**: Deploy PMM Server for cluster-aware monitoring, query analytics, and alerting. Replaces our current pg_stat_statements + Datadog integration for database metrics.

### Schema migration considerations

Our PostgreSQL schema uses several features that require translation:
- **JSONB columns** → JSON columns with generated columns for indexed paths
- **Array types** → Normalized junction tables or JSON arrays
- **CTEs (WITH queries)** → Supported in MySQL 8.0, mostly compatible
- **Window functions** → Fully supported in MySQL 8.0
- **Sequences** → AUTO_INCREMENT with Galera's auto_increment_increment/offset
- **LISTEN/NOTIFY** → Replace with polling or message queue (already moving to SQS)
- **Partial indexes** → Functional indexes or filtered covering indexes
- **Custom types/enums** → ENUM columns or lookup tables

### Application changes

- Replace `psycopg2`/`asyncpg` with `PyMySQL`/`aiomysql` across 14 services
- Update SQLAlchemy dialect from `postgresql` to `mysql+pymysql`
- Migrate Alembic revision history to new dialect
- Update 47 raw SQL queries that use PostgreSQL-specific syntax (ILIKE, string_agg, generate_series, etc.)
- Replace `ON CONFLICT DO UPDATE` (upsert) with `INSERT ... ON DUPLICATE KEY UPDATE`

## Migration Plan

### Phase 1: Parallel deployment (Weeks 1-3)
- Provision 3-node PXC cluster in staging
- Deploy PMM and ProxySQL
- Run pgloader to perform initial schema + data migration
- Configure Galera tuning: gcache.size=2G, wsrep_slave_threads=8, innodb_buffer_pool_size=48G
- Validate data integrity with pt-table-checksum

### Phase 2: Application migration (Weeks 4-7)
- Branch application code for MySQL dialect
- Migrate raw queries service-by-service (14 services)
- Run dual-write shadow testing: write to both PG and PXC, compare results
- Load test PXC cluster with production traffic replay via pt-query-digest

### Phase 3: Cutover (Week 8)
- Final pgloader sync with CDC via Debezium (PG → Kafka → PXC)
- Switch ProxySQL to accept production traffic
- Keep PostgreSQL running in read-only mode for 1 week as rollback safety net
- Decommission PostgreSQL after validation period

## Risks

- **Galera flow control**: Under heavy write load, slower nodes trigger flow control, throttling the entire cluster. Mitigated by uniform node sizing and gcache tuning.
- **DDL limitations**: Galera uses Total Order Isolation for DDL. Large ALTER TABLE operations lock writes cluster-wide. Mitigated by using pt-online-schema-change for all migrations.
- **Multi-master conflicts**: Concurrent writes to the same row on different nodes cause certification failures (deadlock errors). Mitigated by ProxySQL routing related writes to the same node and application-level retry logic.
- **Network partition**: Galera requires quorum (2 of 3 nodes). A network split isolating one node causes it to become non-primary. This is by design — prevents split-brain — but can surprise applications. ProxySQL health checks handle routing.
- **Query compatibility**: Some PostgreSQL queries have no direct MySQL equivalent. Identified 12 queries requiring significant rewrite, 35 requiring minor syntax changes.
- **Transaction size limits**: Galera replicates at transaction commit. Very large transactions (bulk inserts >100K rows) can cause cluster instability. Mitigated by chunking batch operations.

## Alternatives Considered

1. **PostgreSQL BDR (Bi-Directional Replication)**: True multi-master for Postgres, but requires EDB subscription ($180K/year) and has complex conflict resolution.
2. **Citus (distributed PostgreSQL)**: Excellent for horizontal scaling but requires sharding schema design and doesn't provide true multi-master.
3. **CockroachDB**: Distributed SQL with multi-master, but significant query compatibility issues and 3-5x higher per-query latency for our OLTP workload.
4. **Aurora PostgreSQL Multi-Master**: Was available in preview but AWS deprecated it. Aurora MySQL Multi-Master is also limited to 2 writer nodes and has restrictions.
5. **Upgrade PostgreSQL + Patroni**: Adds automatic failover but doesn't solve the write scaling problem. Still single-writer architecture.

## Cost Comparison

| Component | Current (PostgreSQL) | Proposed (PXC) | Delta |
|-----------|---------------------|----------------|-------|
| Database nodes | 1x r6g.4xlarge + 2x r6g.2xlarge ($4,800/mo) | 3x r6g.4xlarge ($7,200/mo) | +$2,400 |
| Storage (gp3) | 2TB primary + 2x 2TB replica ($960/mo) | 3x 2TB ($960/mo) | $0 |
| PgBouncer/ProxySQL | 2x t3.medium ($120/mo) | 3x t3.large ($240/mo) | +$120 |
| Monitoring | Datadog DB monitoring ($400/mo) | PMM Server t3.xlarge ($120/mo) | -$280 |
| DBA on-call burden | ~20 hrs/month incident response | ~8 hrs/month (estimated) | -12 hrs |
| **Total infra** | **$6,280/mo** | **$8,520/mo** | **+$2,240/mo** |

The $2,240/mo increase is offset by:
- Elimination of write bottleneck (est. $15K/mo in lost revenue during peak failures)
- Reduced DBA on-call hours (12 hrs/mo × $150/hr = $1,800/mo)
- Zero-downtime failover (current failover costs ~$8K per incident in SLA credits)
