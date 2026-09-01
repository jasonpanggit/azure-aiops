#!/usr/bin/env node
/**
 * Minimal stdio<->HTTP bridge for Microsoft's official Azure MCP Server
 * (@azure/mcp).
 *
 * Why this exists: azmcp's --transport http mode enforces its own Azure AD
 * JWT incoming-auth, which cannot currently be configured (no documented
 * env vars work) and whose only documented escape hatch,
 * --dangerously-disable-http-incoming-auth, crashes the process on startup
 * in every 3.0.0-beta version tested here (see
 * https://github.com/microsoft/mcp/issues/2459). The default stdio
 * transport has no such auth layer and works reliably, so this bridge
 * spawns azmcp once in stdio mode and exposes it over plain HTTP
 * (newline-delimited JSON-RPC request/response, one exchange per POST),
 * so upstream callers (APIM, Foundry agents) don't need to know or care
 * that the real transport underneath is stdio.
 *
 * Request handling is serialized (one in-flight request at a time) because
 * stdio JSON-RPC framing over a single child process doesn't give us a
 * built-in way to correlate concurrent request/response pairs beyond the
 * `id` field, and MCP tool calls here are infrequent, latency-tolerant
 * Azure Resource Manager/Monitor queries -- simplicity and correctness win
 * over throughput.
 */
'use strict';

const http = require('http');
const { spawn } = require('child_process');

const PORT = process.env.PORT || 8000;
const AZMCP_BIN = process.env.AZMCP_BIN || './node_modules/.bin/azmcp';
const AZMCP_ARGS = (process.env.AZMCP_ARGS || '--read-only --mode all --dangerously-disable-elicitation').split(' ').filter(Boolean);

let child = null;
let stdoutBuffer = '';
let pending = []; // FIFO of { resolve, reject } for in-flight requests, matched by response order

function startChild() {
  child = spawn(AZMCP_BIN, ['server', 'start', ...AZMCP_ARGS], {
    stdio: ['pipe', 'pipe', 'inherit'],
    env: process.env,
  });

  child.on('exit', (code, signal) => {
    console.error(`azmcp exited (code=${code}, signal=${signal}), restarting in 1s`);
    // Fail any requests still waiting on the dead process.
    for (const p of pending) p.reject(new Error('azmcp process exited'));
    pending = [];
    stdoutBuffer = '';
    setTimeout(startChild, 1000);
  });

  child.stdout.on('data', (chunk) => {
    stdoutBuffer += chunk.toString('utf8');
    let idx;
    while ((idx = stdoutBuffer.indexOf('\n')) >= 0) {
      const line = stdoutBuffer.slice(0, idx).trim();
      stdoutBuffer = stdoutBuffer.slice(idx + 1);
      if (!line) continue;
      const waiter = pending.shift();
      if (waiter) waiter.resolve(line);
      else console.error('Received unsolicited azmcp stdout line, dropping:', line);
    }
  });

  console.error(`azmcp started (pid=${child.pid})`);
}

function callAzmcp(requestLine) {
  return new Promise((resolve, reject) => {
    pending.push({ resolve, reject });
    child.stdin.write(requestLine + '\n', (err) => {
      if (err) {
        pending.pop();
        reject(err);
      }
    });
  });
}

startChild();

const server = http.createServer((req, res) => {
  if (req.method !== 'POST') {
    res.writeHead(405, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'method not allowed, use POST' }));
    return;
  }

  let body = '';
  req.on('data', (c) => { body += c; });
  req.on('end', async () => {
    let parsed;
    try {
      // Validate it's at least parseable JSON before forwarding, so a
      // malformed request doesn't desync the stdio framing.
      parsed = JSON.parse(body);
    } catch (e) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'invalid JSON body' }));
      return;
    }

    // JSON-RPC *notifications* (e.g. "notifications/initialized", which
    // every spec-compliant MCP client -- including Foundry -- sends right
    // after `initialize` completes) omit the `id` field and by protocol
    // definition never get a response line on stdout. Forwarding one of
    // these through callAzmcp() would push a waiter onto `pending` that
    // never resolves, hanging the HTTP response forever and, upstream,
    // tripping Foundry's "Initialization timed out" tool-enumeration
    // error. Fire-and-forget these to the child's stdin instead and
    // respond immediately with 202 (no body expected for notifications).
    if (parsed.id === undefined) {
      child.stdin.write(body.trim() + '\n', (err) => {
        if (err) {
          res.writeHead(502, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: `bridge error: ${err.message}` }));
          return;
        }
        res.writeHead(202, { 'Content-Type': 'application/json' });
        res.end();
      });
      return;
    }

    try {
      const responseLine = await callAzmcp(body.trim());
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(responseLine);
    } catch (e) {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: `bridge error: ${e.message}` }));
    }
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.error(`stdio-http bridge listening on 0.0.0.0:${PORT}`);
});
