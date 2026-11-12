/**
 * Frontend routes integration and page rendering tests.
 * Spawns next start on an isolated test port and validates all App Router routes.
 */
import { describe, it, before, after } from "node:test";
import assert from "node:assert";
import { spawn, ChildProcess } from "node:child_process";

const TEST_PORT = 3088;
const BASE_URL = `http://127.0.0.1:${TEST_PORT}`;

describe("Frontend Routes Integration & Page Rendering", () => {
  let serverProcess: ChildProcess | null = null;

  before(async () => {
    // Launch Next.js production server on the isolated test port
    serverProcess = spawn(
      "npx.cmd",
      ["next", "start", "-p", String(TEST_PORT)],
      {
        cwd: process.cwd(),
        shell: true,
        stdio: "pipe",
      }
    );

    // Wait until the server is responding to HTTP requests
    let ready = false;
    for (let i = 0; i < 30; i++) {
      try {
        const res = await fetch(`${BASE_URL}/`);
        if (res.status === 200) {
          ready = true;
          break;
        }
      } catch {
        // Wait and retry
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    assert.ok(ready, "Next.js server failed to start within the timeout period");
  });

  after(() => {
    if (serverProcess) {
      serverProcess.kill("SIGTERM");
      serverProcess = null;
    }
  });

  it("GET / (Overview) returns 200 OK and renders overview page elements", async () => {
    const res = await fetch(`${BASE_URL}/`);
    assert.strictEqual(res.status, 200);
    const html = await res.text();
    assert.ok(html.includes("<!DOCTYPE html>"));
    assert.ok(html.includes("SmartSight") || html.includes("Overview") || html.includes("camera"));
  });

  it("GET /live (Live camera page) returns 200 OK and renders live stream panel", async () => {
    const res = await fetch(`${BASE_URL}/live`);
    assert.strictEqual(res.status, 200);
    const html = await res.text();
    assert.ok(html.includes("<!DOCTYPE html>"));
    assert.ok(html.includes("Live camera") || html.includes("ESP32"));
  });

  it("GET /settings (Settings page) returns 200 OK and renders camera settings form", async () => {
    const res = await fetch(`${BASE_URL}/settings`);
    assert.strictEqual(res.status, 200);
    const html = await res.text();
    assert.ok(html.includes("<!DOCTYPE html>"));
    assert.ok(html.includes("Settings") || html.includes("Stream URL") || html.includes("ESP32"));
  });

  it("GET /recordings (Recordings page) returns 200 OK", async () => {
    const res = await fetch(`${BASE_URL}/recordings`);
    assert.strictEqual(res.status, 200);
    const html = await res.text();
    assert.ok(html.includes("<!DOCTYPE html>"));
  });

  it("GET /search (Smart search page) returns 200 OK", async () => {
    const res = await fetch(`${BASE_URL}/search`);
    assert.strictEqual(res.status, 200);
    const html = await res.text();
    assert.ok(html.includes("<!DOCTYPE html>"));
  });

  it("GET /activity (Activity feed page) returns 200 OK", async () => {
    const res = await fetch(`${BASE_URL}/activity`);
    assert.strictEqual(res.status, 200);
    const html = await res.text();
    assert.ok(html.includes("<!DOCTYPE html>"));
  });
});

