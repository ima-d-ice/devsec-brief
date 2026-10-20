import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, askPayload, expectOk, headers } from './common.js';

export const options = {
  vus: 1,
  iterations: 3,
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{endpoint:ask}': ['p(95)<60000'],
    'http_req_duration{endpoint:stream}': ['p(95)<60000'],
  },
};

export default function () {
  expectOk(http.get(`${BASE_URL}/health/live`, { tags: { endpoint: 'live' } }), 'live');
  expectOk(http.get(`${BASE_URL}/health/ready`, { tags: { endpoint: 'ready' } }), 'ready');

  const ask = http.post(`${BASE_URL}/ask`, askPayload(), {
    headers: headers(),
    tags: { endpoint: 'ask' },
  });
  expectOk(ask, 'ask');
  check(ask, { 'ask: answer present': (r) => r.body && r.body.length > 10 });

  const stream = http.post(`${BASE_URL}/ask/stream`, askPayload(), {
    headers: headers(),
    tags: { endpoint: 'stream' },
    timeout: '90s',
  });
  expectOk(stream, 'stream');
  check(stream, {
    'stream: sources event': (r) => r.body.includes('event: sources'),
    'stream: done event': (r) => r.body.includes('event: done'),
  });
  sleep(0.5);
}
