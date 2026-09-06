#!/usr/bin/env node
/**
 * HTTP bridge for Microsoft's stdio-only Azure MCP Server.
 *
 * One Azure MCP child is shared by every HTTP caller. Requests must therefore
 * be single-flight: writing multiple JSON-RPC requests concurrently can
 * associate responses with the wrong caller or leave later callers waiting
 * behind a hung operation until the upstream MCP deadline expires.
 */
'use strict';

const http = require('http');
const { spawn } = require('child_process');
const { createHash, timingSafeEqual } = require('crypto');
const { StringDecoder } = require('string_decoder');

const DEFAULT_PORT = 8000;
const DEFAULT_REQUEST_TIMEOUT_MS = 25_000;
const DEFAULT_QUEUE_TIMEOUT_MS = 5_000;
const DEFAULT_MAX_QUEUE_DEPTH = 32;
const DEFAULT_MAX_REQUEST_BYTES = 1_048_576;
const DEFAULT_MAX_RESPONSE_BYTES = 1_048_576;
const DEFAULT_RESTART_DELAY_MS = 1_000;

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

class BridgeError extends Error {
  constructor(statusCode, message) {
    super(message);
    this.name = 'BridgeError';
    this.statusCode = statusCode;
  }
}

function assertionMatches(actual, expected) {
  if (typeof actual !== 'string' || typeof expected !== 'string') return false;
  const digest = (value) => createHash('sha256').update(value, 'utf8').digest();
  return timingSafeEqual(digest(actual), digest(expected));
}

function validateJsonRpcEnvelope(payload) {
  if (!payload || Array.isArray(payload) || typeof payload !== 'object') {
    throw new BridgeError(400, 'request must be one JSON-RPC object');
  }
  if (payload.jsonrpc !== '2.0') {
    throw new BridgeError(400, 'jsonrpc must be "2.0"');
  }
  if (typeof payload.method !== 'string' || payload.method.length === 0) {
    throw new BridgeError(400, 'JSON-RPC method must be a non-empty string');
  }
  if (
    Object.hasOwn(payload, 'id')
    && payload.id !== null
    && typeof payload.id !== 'string'
    && !(typeof payload.id === 'number' && Number.isFinite(payload.id))
  ) {
    throw new BridgeError(400, 'JSON-RPC id must be a string, number, or null');
  }
  if (
    Object.hasOwn(payload, 'params')
    && (
      payload.params === null
      || typeof payload.params !== 'object'
    )
  ) {
    throw new BridgeError(400, 'JSON-RPC params must be an object or array');
  }
}

class StdioRequestQueue {
  constructor(options = {}) {
    this.requestTimeoutMs = positiveInteger(
      options.requestTimeoutMs,
      DEFAULT_REQUEST_TIMEOUT_MS,
    );
    this.queueTimeoutMs = positiveInteger(
      options.queueTimeoutMs,
      DEFAULT_QUEUE_TIMEOUT_MS,
    );
    this.maxQueueDepth = positiveInteger(
      options.maxQueueDepth,
      DEFAULT_MAX_QUEUE_DEPTH,
    );
    this.maxResponseBytes = positiveInteger(
      options.maxResponseBytes,
      DEFAULT_MAX_RESPONSE_BYTES,
    );
    this.restartDelayMs = Number.isSafeInteger(options.restartDelayMs)
      && options.restartDelayMs >= 0
      ? options.restartDelayMs
      : DEFAULT_RESTART_DELAY_MS;
    this.logger = options.logger || console;
    this.enforceInitialization = options.enforceInitialization !== false;
    this.spawnChild = options.spawnChild || (() => spawn(
      options.bin || './node_modules/.bin/azmcp',
      ['server', 'start', ...(options.args || [])],
      {
        stdio: ['pipe', 'pipe', 'inherit'],
        env: options.env || process.env,
      },
    ));

    this.child = null;
    this.stdoutBuffer = '';
    this.stdoutDecoder = new StringDecoder('utf8');
    this.queue = [];
    this.active = null;
    this.restartTimer = null;
    this.stopped = false;
    this.initialized = false;
    this._startChild();
  }

  request(payload) {
    if (!payload || payload.id === undefined) {
      return Promise.reject(new BridgeError(400, 'JSON-RPC request requires an id'));
    }
    return this._enqueue('request', payload);
  }

  notification(payload) {
    if (!payload || payload.id !== undefined) {
      return Promise.reject(new BridgeError(400, 'JSON-RPC notification must omit id'));
    }
    return this._enqueue('notification', payload);
  }

  stop() {
    if (this.stopped) return;
    this.stopped = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = null;

    const stoppedError = new BridgeError(503, 'bridge is stopping');
    if (this.active) {
      clearTimeout(this.active.executionTimer);
      this.active.reject(stoppedError);
      this.active = null;
    }
    for (const item of this.queue.splice(0)) {
      clearTimeout(item.queueTimer);
      item.reject(stoppedError);
    }

    const child = this.child;
    this.child = null;
    if (child && !child.killed) child.kill();
  }

  _enqueue(kind, payload) {
    if (this.stopped) {
      return Promise.reject(new BridgeError(503, 'bridge is stopping'));
    }
    if (!this.child) {
      return Promise.reject(new BridgeError(
        503,
        'Azure MCP child is restarting; client must reinitialize',
      ));
    }
    const depth = this.queue.length + (this.active ? 1 : 0);
    if (depth >= this.maxQueueDepth) {
      return Promise.reject(new BridgeError(429, 'Azure MCP request queue is full'));
    }

    return new Promise((resolve, reject) => {
      const item = {
        kind,
        payload,
        line: JSON.stringify(payload),
        resolve,
        reject,
        enqueuedAt: Date.now(),
        startedAt: null,
        queueTimer: null,
        executionTimer: null,
      };
      item.queueTimer = setTimeout(() => {
        const index = this.queue.indexOf(item);
        if (index < 0) return;
        this.queue.splice(index, 1);
        item.reject(new BridgeError(
          503,
          `Azure MCP queue wait timed out after ${this.queueTimeoutMs}ms`,
        ));
      }, this.queueTimeoutMs);
      this.queue.push(item);
      this._drain();
    });
  }

  _startChild() {
    if (this.stopped || this.child) return;

    let child;
    try {
      child = this.spawnChild();
    } catch (error) {
      this.logger.error(`failed to start azmcp: ${error.message}`);
      this._scheduleRestart();
      return;
    }

    this.child = child;
    this.stdoutBuffer = '';
    this.stdoutDecoder = new StringDecoder('utf8');
    this.initialized = false;
    child.stdout.on('data', (chunk) => this._handleStdout(child, chunk));
    child.stdin.on('error', (error) => this._handleChildFailure(
      child,
      new Error(`azmcp stdin failed: ${error.message}`),
    ));
    child.on('error', (error) => this._handleChildFailure(child, error));
    child.on('exit', (code, signal) => this._handleChildFailure(
      child,
      new Error(`azmcp exited (code=${code}, signal=${signal})`),
    ));
    this.logger.error(`azmcp started (pid=${child.pid ?? 'unknown'})`);
    this._drain();
  }

  _handleChildFailure(child, error) {
    if (child !== this.child) return;
    this.child = null;
    this.stdoutBuffer = '';
    this.stdoutDecoder = new StringDecoder('utf8');
    this.initialized = false;
    if (this.active) {
      const active = this.active;
      this.active = null;
      clearTimeout(active.executionTimer);
      active.reject(new BridgeError(502, error.message));
    }
    this._rejectQueuedForReinitialization();
    this.logger.error(error.message);
    this._scheduleRestart();
  }

  _scheduleRestart() {
    if (this.stopped || this.restartTimer) return;
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      this._startChild();
    }, this.restartDelayMs);
  }

  _restartChild(reason) {
    const child = this.child;
    this.child = null;
    this.stdoutBuffer = '';
    this.stdoutDecoder = new StringDecoder('utf8');
    this.initialized = false;
    if (child && !child.killed) child.kill();
    this._rejectQueuedForReinitialization();
    this.logger.error(reason);
    this._scheduleRestart();
  }

  _rejectQueuedForReinitialization() {
    const error = new BridgeError(
      503,
      'Azure MCP child restarted; client must reinitialize',
    );
    for (const item of this.queue.splice(0)) {
      clearTimeout(item.queueTimer);
      item.reject(error);
    }
  }

  _drain() {
    if (this.stopped || this.active || !this.child || this.queue.length === 0) {
      return;
    }

    const item = this.queue.shift();
    clearTimeout(item.queueTimer);
    if (
      this.enforceInitialization
      && !this.initialized
      && !(item.kind === 'request' && item.payload.method === 'initialize')
    ) {
      item.reject(new BridgeError(
        503,
        'Azure MCP child is not initialized; client must reinitialize',
      ));
      this._drain();
      return;
    }
    item.startedAt = Date.now();
    this.active = item;

    if (item.kind === 'notification') {
      item.executionTimer = setTimeout(() => {
        if (this.active !== item) return;
        this.active = null;
        item.reject(new BridgeError(
          504,
          `Azure MCP notification write timed out after ${this.requestTimeoutMs}ms`,
        ));
        this._restartChild('Azure MCP notification write timed out');
      }, this.requestTimeoutMs);

      try {
        this.child.stdin.write(`${item.line}\n`, (error) => {
          if (this.active !== item) return;
          clearTimeout(item.executionTimer);
          this.active = null;
          if (error) {
            item.reject(new BridgeError(502, `azmcp write failed: ${error.message}`));
            this._restartChild(`azmcp notification write failed: ${error.message}`);
          } else {
            item.resolve('');
            this._logCompletion(item, 0);
            this._drain();
          }
        });
      } catch (error) {
        if (this.active !== item) return;
        clearTimeout(item.executionTimer);
        this.active = null;
        item.reject(new BridgeError(502, `azmcp write failed: ${error.message}`));
        this._restartChild(`azmcp notification write failed: ${error.message}`);
      }
      return;
    }

    item.executionTimer = setTimeout(() => {
      if (this.active !== item) return;
      this.active = null;
      item.reject(new BridgeError(
        504,
        `Azure MCP request timed out after ${this.requestTimeoutMs}ms`,
      ));
      this._restartChild(`Azure MCP request ${String(item.payload.id)} timed out`);
    }, this.requestTimeoutMs);

    try {
      this.child.stdin.write(`${item.line}\n`, (error) => {
        if (!error || this.active !== item) return;
        clearTimeout(item.executionTimer);
        this.active = null;
        item.reject(new BridgeError(502, `azmcp write failed: ${error.message}`));
        this._restartChild(`azmcp request write failed: ${error.message}`);
      });
    } catch (error) {
      if (this.active !== item) return;
      clearTimeout(item.executionTimer);
      this.active = null;
      item.reject(new BridgeError(502, `azmcp write failed: ${error.message}`));
      this._restartChild(`azmcp request write failed: ${error.message}`);
    }
  }

  _handleStdout(child, chunk) {
    if (child !== this.child) return;
    this.stdoutBuffer += this.stdoutDecoder.write(chunk);
    if (Buffer.byteLength(this.stdoutBuffer, 'utf8') > this.maxResponseBytes) {
      this._failProtocol(
        new BridgeError(502, 'Azure MCP response exceeded the configured size limit'),
      );
      return;
    }

    let newlineIndex;
    while ((newlineIndex = this.stdoutBuffer.indexOf('\n')) >= 0) {
      const line = this.stdoutBuffer.slice(0, newlineIndex).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(newlineIndex + 1);
      if (!line) continue;

      let response;
      try {
        response = JSON.parse(line);
      } catch {
        this._failProtocol(new BridgeError(502, 'Azure MCP returned invalid JSON'));
        return;
      }

      if (
        !response
        || Array.isArray(response)
        || typeof response !== 'object'
        || response.jsonrpc !== '2.0'
      ) {
        this._failProtocol(new BridgeError(
          502,
          'Azure MCP returned an invalid JSON-RPC message',
        ));
        return;
      }
      if (response.id === undefined) {
        if (typeof response.method !== 'string') {
          this._failProtocol(new BridgeError(
            502,
            'Azure MCP returned an invalid JSON-RPC notification',
          ));
          return;
        }
        this.logger.info('received Azure MCP server notification');
        continue;
      }
      if (
        !Object.hasOwn(response, 'result')
        && !Object.hasOwn(response, 'error')
      ) {
        this._failProtocol(new BridgeError(
          502,
          'Azure MCP returned an invalid JSON-RPC response',
        ));
        return;
      }
      if (!this.active || this.active.kind !== 'request') {
        this._failProtocol(new BridgeError(502, 'received unsolicited Azure MCP response'));
        return;
      }
      if (!Object.is(response.id, this.active.payload.id)) {
        this._failProtocol(new BridgeError(
          502,
          `Azure MCP response id mismatch: expected ${String(this.active.payload.id)}`,
        ));
        return;
      }

      const item = this.active;
      this.active = null;
      clearTimeout(item.executionTimer);
      if (
        item.payload.method === 'initialize'
        && Object.hasOwn(response, 'result')
      ) {
        this.initialized = true;
      }
      item.resolve(line);
      this._logCompletion(item, Buffer.byteLength(line, 'utf8'));
      this._drain();
    }
  }

  _failProtocol(error) {
    if (this.active) {
      const item = this.active;
      this.active = null;
      clearTimeout(item.executionTimer);
      item.reject(error);
    }
    this._restartChild(error.message);
  }

  _logCompletion(item, responseBytes) {
    const completedAt = Date.now();
    this.logger.info(JSON.stringify({
      event: 'azure_mcp_bridge_request',
      method: item.payload.method,
      queue_ms: item.startedAt - item.enqueuedAt,
      execution_ms: completedAt - item.startedAt,
      response_bytes: responseBytes,
    }));
  }
}

function createHttpServer(queue, options = {}) {
  const maxRequestBytes = positiveInteger(
    options.maxRequestBytes,
    DEFAULT_MAX_REQUEST_BYTES,
  );
  const gatewayAssertion = options.gatewayAssertion;
  if (typeof gatewayAssertion !== 'string' || gatewayAssertion.length < 32) {
    throw new Error('AIOPS_GATEWAY_ASSERTION must contain at least 32 characters');
  }

  return http.createServer((request, response) => {
    if (request.method !== 'POST') {
      response.writeHead(405, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ error: 'method not allowed, use POST' }));
      return;
    }

    const suppliedAssertion = request.headers['x-aiops-gateway-assertion'];
    if (!assertionMatches(suppliedAssertion, gatewayAssertion)) {
      response.writeHead(401, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ error: 'unauthorized gateway' }));
      return;
    }

    const bodyChunks = [];
    let bodyBytes = 0;
    let tooLarge = false;
    request.on('data', (chunk) => {
      bodyBytes += chunk.length;
      if (bodyBytes > maxRequestBytes) {
        tooLarge = true;
        return;
      }
      bodyChunks.push(Buffer.from(chunk));
    });
    request.on('end', async () => {
      if (tooLarge) {
        response.writeHead(413, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ error: 'request body exceeds configured limit' }));
        return;
      }

      let payload;
      try {
        const body = Buffer.concat(bodyChunks, bodyBytes).toString('utf8');
        payload = JSON.parse(body);
        validateJsonRpcEnvelope(payload);
      } catch (error) {
        const statusCode = error instanceof BridgeError ? error.statusCode : 400;
        response.writeHead(statusCode, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ error: `invalid JSON body: ${error.message}` }));
        return;
      }

      try {
        if (payload.id === undefined) {
          await queue.notification(payload);
          response.writeHead(202, { 'Content-Type': 'application/json' });
          response.end();
          return;
        }

        const responseLine = await queue.request(payload);
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end(responseLine);
      } catch (error) {
        const statusCode = error instanceof BridgeError ? error.statusCode : 502;
        const headers = { 'Content-Type': 'application/json' };
        if (statusCode === 429 || statusCode === 503) headers['Retry-After'] = '1';
        response.writeHead(statusCode, headers);
        response.end(JSON.stringify({ error: `bridge error: ${error.message}` }));
      }
    });
  });
}

function main() {
  const bin = process.env.AZMCP_BIN || './node_modules/.bin/azmcp';
  const args = (
    process.env.AZMCP_ARGS
    || '--read-only --mode namespace --dangerously-disable-elicitation'
  ).split(' ').filter(Boolean);
  const queue = new StdioRequestQueue({
    bin,
    args,
    env: process.env,
    requestTimeoutMs: positiveInteger(
      process.env.AZMCP_REQUEST_TIMEOUT_MS,
      DEFAULT_REQUEST_TIMEOUT_MS,
    ),
    queueTimeoutMs: positiveInteger(
      process.env.AZMCP_QUEUE_TIMEOUT_MS,
      DEFAULT_QUEUE_TIMEOUT_MS,
    ),
    maxQueueDepth: positiveInteger(
      process.env.AZMCP_MAX_QUEUE_DEPTH,
      DEFAULT_MAX_QUEUE_DEPTH,
    ),
    maxResponseBytes: positiveInteger(
      process.env.AZMCP_MAX_RESPONSE_BYTES,
      DEFAULT_MAX_RESPONSE_BYTES,
    ),
  });
  const server = createHttpServer(queue, {
    gatewayAssertion: process.env.AIOPS_GATEWAY_ASSERTION,
    maxRequestBytes: positiveInteger(
      process.env.AZMCP_MAX_REQUEST_BYTES,
      DEFAULT_MAX_REQUEST_BYTES,
    ),
  });
  const port = positiveInteger(process.env.PORT, DEFAULT_PORT);

  server.requestTimeout = queue.requestTimeoutMs + queue.queueTimeoutMs + 5_000;
  server.listen(port, '0.0.0.0', () => {
    console.error(`stdio-http bridge listening on 0.0.0.0:${port}`);
  });

  const shutdown = () => {
    server.close(() => process.exit(0));
    queue.stop();
    setTimeout(() => process.exit(1), 5_000).unref();
  };
  process.once('SIGTERM', shutdown);
  process.once('SIGINT', shutdown);
}

if (require.main === module) main();

module.exports = {
  assertionMatches,
  BridgeError,
  StdioRequestQueue,
  createHttpServer,
  positiveInteger,
  validateJsonRpcEnvelope,
};
