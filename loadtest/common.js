import http from 'k6/http';
import { check } from 'k6';

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
export const API_KEY = __ENV.API_KEY || '';

export function headers(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra };
  if (API_KEY) h['X-API-Key'] = API_KEY;
  return h;
}

const QUERIES = [
  'What is CVE-2024-3094 and how do I remediate it?',
  'How should I handle HTTP/2 Rapid Reset?',
  'What is the Log4Shell remediation checklist?',
  'How do I detect PostgreSQL connection pool exhaustion?',
  'What does a good SLO error budget policy look like?',
  'How do I secure an SSE endpoint behind a reverse proxy?',
  'What is the difference between RED and USE metrics?',
  'How should I test backup and restore?',
  'How do I defend a RAG pipeline against prompt injection?',
  'What is the Kubernetes RBAC privilege escalation risk?',
];

export function randomQuery() {
  return QUERIES[Math.floor(Math.random() * QUERIES.length)];
}

export function askPayload() {
  return JSON.stringify({ query: randomQuery(), k: 6 });
}

export function expectOk(response, name) {
  return check(response, {
    [`${name}: status is 2xx`]: (r) => r.status >= 200 && r.status < 300,
  });
}
