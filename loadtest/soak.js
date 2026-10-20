import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, askPayload, headers } from './common.js';

const HOLD = __ENV.DURATION || '10m';

export const options = {
  scenarios: {
    soak: {
      executor: 'constant-vus',
      vus: Number(__ENV.VUS || 5),
      duration: HOLD,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{endpoint:ask}': ['p(95)<60000'],
    'http_req_duration{endpoint:live}': ['p(95)<500'],
  },
};

export default function () {
  if (Math.random() < 0.1) {
    check(http.get(`${BASE_URL}/health/live`, { tags: { endpoint: 'live' } }), {
      'live: 2xx': (r) => r.status === 200,
    });
  }
  const response = http.post(`${BASE_URL}/ask`, askPayload(), {
    headers: headers(),
    tags: { endpoint: 'ask' },
  });
  check(response, { 'ask: 2xx': (r) => r.status >= 200 && r.status < 300 });
  sleep(2);
}
