import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, askPayload, headers } from './common.js';

const HOLD = __ENV.DURATION || '60s';

export const options = {
  scenarios: {
    rest_ramp: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: 5 },
        { duration: HOLD, target: 10 },
        { duration: '10s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{endpoint:ask}': ['p(95)<60000'],
  },
};

export default function () {
  const response = http.post(`${BASE_URL}/ask`, askPayload(), {
    headers: headers(),
    tags: { endpoint: 'ask' },
  });
  check(response, {
    'ask: 2xx': (r) => r.status >= 200 && r.status < 300,
    'ask: body present': (r) => r.body && r.body.length > 10,
  });
  sleep(1);
}
