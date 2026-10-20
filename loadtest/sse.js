import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, askPayload, headers } from './common.js';

const HOLD = __ENV.DURATION || '60s';

export const options = {
  scenarios: {
    sse: {
      executor: 'constant-vus',
      vus: Number(__ENV.VUS || 5),
      duration: HOLD,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{endpoint:stream}': ['p(95)<90000'],
  },
};

export default function () {
  const response = http.post(`${BASE_URL}/ask/stream`, askPayload(), {
    headers: headers(),
    tags: { endpoint: 'stream' },
    timeout: '120s',
  });
  check(response, {
    'stream: 2xx': (r) => r.status >= 200 && r.status < 300,
    'stream: sources': (r) => r.body.includes('event: sources'),
    'stream: done': (r) => r.body.includes('event: done'),
  });
  sleep(0.5);
}
