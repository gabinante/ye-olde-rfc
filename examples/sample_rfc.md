# RFC: Migrate Observability Stack from Datadog to Open Source

**Status:** Proposed
**Authors:** Platform Team
**Date:** 2024-01-15

## Summary

We propose migrating our observability stack from Datadog to an open-source solution based on Prometheus, Grafana, Loki, and Honeycomb. This migration is motivated by rapidly increasing costs ($47K/month projected for Q2) and vendor lock-in concerns.

## Background

Our current observability setup relies entirely on Datadog for metrics, logs, and APM traces. While Datadog has served us well, several issues have emerged:

- **Cost**: Our Datadog bill has grown from $12K/month to $35K/month over the past year, with projections showing $47K/month by Q2 as we scale.
- **Vendor Lock-in**: All dashboards, alerts, and queries are proprietary. Migration would require rebuilding from scratch.
- **Feature Gaps**: Datadog's trace analysis lacks the ad-hoc query capabilities we need for debugging complex distributed systems.

## Proposed Solution

### Metrics: Amazon Managed Prometheus + Grafana
- Use Amazon Managed Service for Prometheus (AMP) for metric ingestion and storage
- Deploy Grafana for visualization and alerting
- Estimated cost: $5K/month

### Logs: Grafana Loki on S3
- Deploy Loki for log aggregation, using S3 for storage
- Label-based indexing keeps costs low
- Estimated cost: $3K/month

### Traces: Honeycomb
- Use Honeycomb for distributed tracing and APM
- Superior query engine for investigating latency issues
- Estimated cost: $8K/month

### Collection: OpenTelemetry Collector (Alloy)
- Deploy Grafana Alloy (OTel Collector distribution) as the universal telemetry agent
- Accepts OTLP, Prometheus, and Datadog formats
- Routes signals to appropriate backends

## Migration Plan

### Phase 1: Metrics (Weeks 1-4)
- Deploy AMP and Grafana
- Configure Alloy to dual-ship metrics to both Datadog and Prometheus
- Recreate critical dashboards in Grafana
- Validate data parity

### Phase 2: Logs (Weeks 5-8)
- Deploy Loki cluster
- Configure log shipping via Alloy
- Migrate log-based alerts
- Validate query capabilities

### Phase 3: Traces (Weeks 9-12)
- Enable Honeycomb integration
- Migrate APM dashboards and SLOs
- Decommission Datadog agents
- Cancel Datadog contract

## Risks

- **Data Loss During Migration**: Mitigated by dual-shipping during transition period
- **Alert Gaps**: Mitigated by running both systems in parallel
- **Team Ramp-up**: Engineers need training on new tools (estimated 1 week per team)
- **Loki Scaling**: Loki can struggle with high-cardinality labels; needs careful schema design

## Alternatives Considered

1. **Negotiate Datadog pricing**: Attempted; best offer was 15% discount, insufficient
2. **Full Grafana Cloud**: Would reduce operational burden but costs nearly as much as Datadog
3. **Elastic Stack**: Higher operational complexity, significant infrastructure requirements
4. **Do Nothing**: Costs continue to grow unsustainably

## Cost Summary

| Component | Current (Datadog) | Proposed | Savings |
|-----------|-------------------|----------|---------|
| Metrics   | $15K/month        | $5K/month| $10K    |
| Logs      | $12K/month        | $3K/month| $9K     |
| Traces    | $8K/month         | $8K/month| $0      |
| **Total** | **$35K/month**    | **$16K/month** | **$19K/month** |

Annual savings: ~$228K
