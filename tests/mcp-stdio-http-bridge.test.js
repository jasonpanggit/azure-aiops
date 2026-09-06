'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const http = require('node:http');
const test = require('node:test');

const {
  BridgeError,
  StdioRequestQueue,
  createHttpServer,
} = require('../scripts/mcp-stdio-http-bridge');

class FakeWritable extends EventEmitter {
  constructor() {
    super();
    this.writes = [];
  }

  write(value, callback) {
    this.writes.push(value);
    if (callback) setImmediate(callback);
    return true;
  }
}

class FakeChild extends EventEmitter {
  constructor() {
    super();
    this.stdin = new FakeWritable();
    this.stdout = new EventEmitter();
    this.killed = false;
  }

  kill() {
    if (this.killed) return;
    this.killed = true;
    setImmediate(() => this.emit('exit', null, 'SIGTERM'));
  }
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
const TEST_GATEWAY_ASSERTION = 'test-gateway-assertion-1234567890';

function respond(child, payload) {
  child.stdout.emit('data', Buffer.from(`${JSON.stringify(payload)}\n`));
}

function createHarness(options = {}) {
  const children = [];
  const queue = new StdioRequestQueue({
    spawnChild: () => {
      const child = new FakeChild();
      children.push(child);
      return child;
    },
    logger: { error() {}, info() {} },
    requestTimeoutMs: 250,
    queueTimeoutMs: 100,
    restartDelayMs: 0,
    enforceInitialization: false,
    ...options,
  });
  return { children, queue };
}

async function startHttpServer(t, queue) {
  const server = createHttpServer(queue, {
    gatewayAssertion: TEST_GATEWAY_ASSERTION,
  });
  t.after(() => new Promise((resolve) => server.close(resolve)));
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return server;
}

function postHttpChunks(server, chunks, assertion = TEST_GATEWAY_ASSERTION) {
  const address = server.address();
  return new Promise((resolve, reject) => {
    const headers = { 'Content-Type': 'application/json' };
    if (assertion !== null) {
      headers['X-AIOps-Gateway-Assertion'] = assertion;
    }
    const request = http.request({
      host: '127.0.0.1',
      port: address.port,
      path: '/',
      method: 'POST',
      headers,
    }, (response) => {
      const responseChunks = [];
      response.on('data', (chunk) => responseChunks.push(chunk));
      response.on('end', () => resolve({
        body: Buffer.concat(responseChunks).toString('utf8'),
        statusCode: response.statusCode,
      }));
    });
    request.on('error', reject);
    for (let index = 0; index < chunks.length - 1; index += 1) {
      request.write(chunks[index]);
    }
    request.end(chunks.at(-1));
  });
}

test('serializes concurrent JSON-RPC requests through one stdio child', async (t) => {
  const { children, queue } = createHarness();
  t.after(() => queue.stop());
  const child = children[0];

  const first = queue.request({ jsonrpc: '2.0', id: 1, method: 'first' });
  const second = queue.request({ jsonrpc: '2.0', id: 2, method: 'second' });
  await tick();

  assert.equal(child.stdin.writes.length, 1);
  assert.match(child.stdin.writes[0], /"id":1/);

  respond(child, { jsonrpc: '2.0', id: 1, result: { value: 'first' } });
  assert.match(await first, /"value":"first"/);
  await tick();

  assert.equal(child.stdin.writes.length, 2);
  assert.match(child.stdin.writes[1], /"id":2/);
  respond(child, { jsonrpc: '2.0', id: 2, result: { value: 'second' } });
  assert.match(await second, /"value":"second"/);
});

test('orders notifications between requests without waiting for a response', async (t) => {
  const { children, queue } = createHarness();
  t.after(() => queue.stop());
  const child = children[0];

  const initialize = queue.request({
    jsonrpc: '2.0',
    id: 'init',
    method: 'initialize',
  });
  const initialized = queue.notification({
    jsonrpc: '2.0',
    method: 'notifications/initialized',
  });
  const listTools = queue.request({
    jsonrpc: '2.0',
    id: 'tools',
    method: 'tools/list',
  });

  await tick();
  assert.equal(child.stdin.writes.length, 1);
  respond(child, { jsonrpc: '2.0', id: 'init', result: {} });
  await initialize;
  await initialized;
  await tick();

  assert.equal(child.stdin.writes.length, 3);
  assert.match(child.stdin.writes[1], /notifications\/initialized/);
  assert.match(child.stdin.writes[2], /tools\/list/);
  respond(child, { jsonrpc: '2.0', id: 'tools', result: { tools: [] } });
  await listTools;
});

test('fails and restarts on a mismatched JSON-RPC response id', async (t) => {
  const { children, queue } = createHarness();
  t.after(() => queue.stop());

  const request = queue.request({ jsonrpc: '2.0', id: 7, method: 'tools/list' });
  await tick();
  respond(children[0], { jsonrpc: '2.0', id: 8, result: {} });

  await assert.rejects(
    request,
    (error) => error instanceof BridgeError
      && error.statusCode === 502
      && /response id mismatch/.test(error.message),
  );
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(children.length, 2);
});

test('times out an active request and replaces the desynchronized child', async (t) => {
  const { children, queue } = createHarness({ requestTimeoutMs: 20 });
  t.after(() => queue.stop());

  const request = queue.request({ jsonrpc: '2.0', id: 1, method: 'slow' });
  await assert.rejects(
    request,
    (error) => error instanceof BridgeError
      && error.statusCode === 504
      && /timed out/.test(error.message),
  );
  await new Promise((resolve) => setTimeout(resolve, 25));
  assert.equal(children[0].killed, true);
  assert.equal(children.length, 2);
});

test('rejects queued work when child restart invalidates MCP session state', async (t) => {
  const { children, queue } = createHarness({
    queueTimeoutMs: 250,
    requestTimeoutMs: 20,
  });
  t.after(() => queue.stop());

  const active = queue.request({ jsonrpc: '2.0', id: 1, method: 'slow' });
  const queued = queue.request({ jsonrpc: '2.0', id: 2, method: 'tools/list' });

  await assert.rejects(active, (error) => error.statusCode === 504);
  await assert.rejects(
    queued,
    (error) => error instanceof BridgeError
      && error.statusCode === 503
      && /must reinitialize/.test(error.message),
  );
  await new Promise((resolve) => setTimeout(resolve, 25));
  assert.equal(children.length, 2);
  assert.equal(children[1].stdin.writes.length, 0);
});

test('requires a fresh initialize handshake after child restart', async (t) => {
  const { children, queue } = createHarness({
    enforceInitialization: true,
    restartDelayMs: 20,
  });
  t.after(() => queue.stop());
  const firstChild = children[0];

  const initialize = queue.request({
    jsonrpc: '2.0',
    id: 'init-1',
    method: 'initialize',
  });
  respond(firstChild, { jsonrpc: '2.0', id: 'init-1', result: {} });
  await initialize;

  const mismatched = queue.request({
    jsonrpc: '2.0',
    id: 'broken',
    method: 'tools/list',
  });
  respond(firstChild, { jsonrpc: '2.0', id: 'wrong', result: {} });
  await assert.rejects(mismatched, (error) => error.statusCode === 502);
  await assert.rejects(
    queue.request({ jsonrpc: '2.0', id: 'during-restart', method: 'tools/list' }),
    (error) => error.statusCode === 503 && /reinitialize/.test(error.message),
  );

  await new Promise((resolve) => setTimeout(resolve, 30));
  const replacement = children[1];
  await assert.rejects(
    queue.request({ jsonrpc: '2.0', id: 'before-init', method: 'tools/list' }),
    (error) => error.statusCode === 503 && /must reinitialize/.test(error.message),
  );
  assert.equal(replacement.stdin.writes.length, 0);

  const reinitialize = queue.request({
    jsonrpc: '2.0',
    id: 'init-2',
    method: 'initialize',
  });
  respond(replacement, { jsonrpc: '2.0', id: 'init-2', result: {} });
  await reinitialize;
  const listTools = queue.request({
    jsonrpc: '2.0',
    id: 'after-init',
    method: 'tools/list',
  });
  respond(replacement, {
    jsonrpc: '2.0',
    id: 'after-init',
    result: { tools: [] },
  });
  await listTools;
});

test('times out a notification write that never completes', async (t) => {
  const { children, queue } = createHarness({ requestTimeoutMs: 20 });
  t.after(() => queue.stop());
  children[0].stdin.write = () => true;

  await assert.rejects(
    queue.notification({
      jsonrpc: '2.0',
      method: 'notifications/initialized',
    }),
    (error) => error instanceof BridgeError
      && error.statusCode === 504
      && /notification write timed out/.test(error.message),
  );
  await new Promise((resolve) => setTimeout(resolve, 25));
  assert.equal(children[0].killed, true);
  assert.equal(children.length, 2);
});

test('expires queued requests before the upstream MCP deadline', async (t) => {
  const { children, queue } = createHarness({
    queueTimeoutMs: 20,
    requestTimeoutMs: 250,
  });
  t.after(() => queue.stop());
  const child = children[0];

  const active = queue.request({ jsonrpc: '2.0', id: 1, method: 'slow' });
  const queued = queue.request({ jsonrpc: '2.0', id: 2, method: 'queued' });

  await assert.rejects(
    queued,
    (error) => error instanceof BridgeError
      && error.statusCode === 503
      && /queue wait timed out/.test(error.message),
  );
  respond(child, { jsonrpc: '2.0', id: 1, result: {} });
  await active;
});

test('rejects excess queue depth with backpressure', async (t) => {
  const { children, queue } = createHarness({ maxQueueDepth: 2 });
  t.after(() => queue.stop());
  const child = children[0];

  const active = queue.request({ jsonrpc: '2.0', id: 1, method: 'active' });
  const queued = queue.request({ jsonrpc: '2.0', id: 2, method: 'queued' });
  await assert.rejects(
    queue.request({ jsonrpc: '2.0', id: 3, method: 'rejected' }),
    (error) => error instanceof BridgeError
      && error.statusCode === 429
      && /queue is full/.test(error.message),
  );

  respond(child, { jsonrpc: '2.0', id: 1, result: {} });
  await active;
  await tick();
  respond(child, { jsonrpc: '2.0', id: 2, result: {} });
  await queued;
});

test('preserves multibyte UTF-8 split across child stdout chunks', async (t) => {
  const { children, queue } = createHarness();
  t.after(() => queue.stop());
  const child = children[0];

  const request = queue.request({ jsonrpc: '2.0', id: 1, method: 'unicode' });
  await tick();
  const encoded = Buffer.from(`${JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    result: { name: 'network-😀' },
  })}\n`);
  const emojiIndex = encoded.indexOf(Buffer.from('😀'));
  child.stdout.emit('data', encoded.subarray(0, emojiIndex + 2));
  child.stdout.emit('data', encoded.subarray(emojiIndex + 2));

  const response = JSON.parse(await request);
  assert.equal(response.result.name, 'network-😀');
});

test('handles child stdin EPIPE without crashing the bridge', async (t) => {
  const { children, queue } = createHarness();
  t.after(() => queue.stop());
  const child = children[0];

  const request = queue.request({ jsonrpc: '2.0', id: 1, method: 'tools/list' });
  await tick();
  const error = new Error('broken pipe');
  error.code = 'EPIPE';
  child.stdin.emit('error', error);

  await assert.rejects(
    request,
    (failure) => failure instanceof BridgeError
      && failure.statusCode === 502
      && /stdin failed/.test(failure.message),
  );
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(children.length, 2);
});

test('recovers when child stdin write throws synchronously', async (t) => {
  const { children, queue } = createHarness();
  t.after(() => queue.stop());
  children[0].stdin.write = () => {
    throw new Error('write exploded');
  };

  await assert.rejects(
    queue.request({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
    (error) => error instanceof BridgeError
      && error.statusCode === 502
      && /write exploded/.test(error.message),
  );
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(children.length, 2);
});

test('rejects valid JSON with an invalid JSON-RPC shape', async (t) => {
  const { children, queue } = createHarness();
  t.after(() => queue.stop());

  const request = queue.request({ jsonrpc: '2.0', id: 1, method: 'tools/list' });
  await tick();
  children[0].stdout.emit('data', Buffer.from('null\n'));

  await assert.rejects(
    request,
    (error) => error instanceof BridgeError
      && error.statusCode === 502
      && /invalid JSON-RPC message/.test(error.message),
  );
});

test('preserves multibyte UTF-8 split across HTTP request chunks', async (t) => {
  let receivedPayload;
  const queue = {
    async request(payload) {
      receivedPayload = payload;
      return JSON.stringify({ jsonrpc: '2.0', id: payload.id, result: {} });
    },
  };
  const server = await startHttpServer(t, queue);

  const encoded = Buffer.from(JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/call',
    params: { name: 'documentation', query: 'network 😀 guidance' },
  }));
  const emojiIndex = encoded.indexOf(Buffer.from('😀'));
  const result = await postHttpChunks(server, [
    encoded.subarray(0, emojiIndex + 2),
    encoded.subarray(emojiIndex + 2),
  ]);

  assert.equal(result.statusCode, 200);
  assert.equal(receivedPayload.params.query, 'network 😀 guidance');
});

test('rejects direct callers without the APIM gateway assertion', async (t) => {
  let calls = 0;
  const server = await startHttpServer(t, {
    async request() {
      calls += 1;
      return '{}';
    },
  });
  const body = Buffer.from(JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/list',
  }));

  const missing = await postHttpChunks(server, [body], null);
  const incorrect = await postHttpChunks(server, [body], 'x'.repeat(32));

  assert.equal(missing.statusCode, 401);
  assert.equal(incorrect.statusCode, 401);
  assert.equal(calls, 0);
});

test('rejects malformed JSON-RPC envelopes before queueing', async (t) => {
  let calls = 0;
  const queue = {
    async request() {
      calls += 1;
      return '{}';
    },
    async notification() {
      calls += 1;
    },
  };
  const server = await startHttpServer(t, queue);
  const invalidPayloads = [
    {},
    { jsonrpc: '1.0', id: 1, method: 'tools/list' },
    { jsonrpc: '2.0', id: 1 },
    { jsonrpc: '2.0', id: {}, method: 'tools/list' },
    { jsonrpc: '2.0', id: 1, method: 'tools/call', params: 'invalid' },
  ];

  for (const payload of invalidPayloads) {
    const result = await postHttpChunks(
      server,
      [Buffer.from(JSON.stringify(payload))],
    );
    assert.equal(result.statusCode, 400);
  }
  assert.equal(calls, 0);
});
