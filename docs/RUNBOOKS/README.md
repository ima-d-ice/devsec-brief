# Runbooks

Each runbook is written for an on-call engineer who did not build the service.

- [API down](api-down.md)
- [Database down](database-down.md)
- [Groq outage](groq-outage.md)
- [Ingestion stale](ingestion-stale.md)
- [High latency](high-latency.md)

Start every incident with:

```bash
docker compose ps
curl -s http://127.0.0.1:8000/health/live
curl -s http://127.0.0.1:8000/health/ready
docker compose logs --since=15m api refresh
```

Never paste API keys or full request bodies into the incident channel.
