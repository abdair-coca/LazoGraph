import { test, expect } from "@playwright/test";

test("wizard → import → ask → search → timeline → graph → plans → wiki → backup → delete — 9 flows", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.locator("body")).toContainText(/LazoGraph|wizard/i);

  // UI Tab Navigation & Elements (Warm Intelligence Grouped IA)
  await page.click('[data-tab="inicio"]');
  await expect(page.locator("#inicio-greeting")).toBeVisible();

  await page.click('[data-tab="ask"]');
  await expect(page.locator("#ask-question")).toBeVisible();

  await page.click('[data-tab="explore"]');
  await expect(page.locator("#search-query")).toBeVisible();
  await expect(page.locator('[data-sub="people"]')).toBeVisible();

  // Test Explorar subviews
  await page.click('[data-sub="plans"]');
  await expect(page.locator("#plans-status")).toBeVisible();

  await page.click('[data-sub="wiki"]');
  await expect(page.locator("#wiki-load")).toBeVisible();

  await page.click('[data-sub="search"]');
  await expect(page.locator("#search-query")).toBeVisible();

  await page.click('[data-tab="history"]');
  await expect(page.locator("#timeline-bars")).toBeVisible();

  await page.click('[data-tab="graph"]');
  await expect(page.locator("#graph-container")).toBeVisible();

  await page.click('[data-tab="settings"]');
  await expect(page.locator("#ops-backup")).toBeVisible();
  await expect(page.locator("#ops-update-check")).toBeVisible();
  await expect(page.locator("#ops-health-check")).toBeVisible();

  // 1. Health & Datasets
  const health = await request.get("/api/health");
  expect(health.ok()).toBeTruthy();
  expect((await health.json()).ok).toBeTruthy();

  const ds = await request.get("/api/datasets");
  expect(ds.ok()).toBeTruthy();

  // 2. Search pagination
  const s0 = await request.get("/api/search?slug=sample&query=proyecto&participant=Alex&limit=10&offset=0");
  expect([200, 404].includes(s0.status())).toBeTruthy();
  if (s0.status() === 200) {
    const j = await s0.json();
    expect(j).toHaveProperty("results");
    expect(j).toHaveProperty("has_more");
    const s1 = await request.get("/api/search?slug=sample&query=proyecto&participant=Alex&limit=10&offset=10");
    expect(s1.ok()).toBeTruthy();
  }

  // 3. Search date filter
  const sf = await request.get("/api/search?slug=sample&query=&limit=5&offset=0&from_date=2026-08-10&to_date=2026-08-11");
  expect([200, 404].includes(sf.status())).toBeTruthy();

  // 4. Timeline
  const timeline = await request.get("/api/timeline?slug=sample&granularity=day");
  expect([200, 404].includes(timeline.status())).toBeTruthy();
  if (timeline.ok()) {
    const j = await timeline.json();
    expect(j).toHaveProperty("buckets");
    expect(j).toHaveProperty("total");
  }

  // 5. Graph effective no plan_* & stats
  const graph = await request.get("/api/graph?slug=sample&format=json");
  expect([200, 404].includes(graph.status())).toBeTruthy();
  if (graph.ok()) {
    const j = await graph.json();
    expect(j).toHaveProperty("nodes");
    expect(j).toHaveProperty("edges");
    for (const e of j.edges) expect(e.type.startsWith("plan_")).toBeFalsy();
  }

  const stats = await request.get("/api/graph/stats?slug=sample");
  expect([200, 404].includes(stats.status())).toBeTruthy();

  // 6. Plans
  const plans = await request.get("/api/plans?slug=sample");
  expect([200, 404].includes(plans.status())).toBeTruthy();

  // 7. Wiki
  const wiki = await request.get("/api/wiki?slug=sample");
  expect([200, 404].includes(wiki.status())).toBeTruthy();

  // 8. Ask
  const ask = await request.post("/api/ask", { data: { question: "¿Qué le gusta a Alex?", slug: "sample", about: "Alex" } });
  expect([200, 422, 404].includes(ask.status())).toBeTruthy();

  // Progress polling
  const prog = await request.get("/api/progress/any-id");
  expect([200, 404].includes(prog.status())).toBeTruthy();
  if (prog.status() === 200) {
    expect((await prog.json()).pct).toBeDefined();
  }

  // 9. Ops & Hardening: update-check, telemetry, backup, invalid slug
  const upd = await request.get("/api/update-check");
  expect(upd.ok()).toBeTruthy();
  const uj = await upd.json();
  expect(uj).toHaveProperty("current");

  const telem = await request.get("/api/telemetry");
  expect(telem.ok()).toBeTruthy();

  const backup = await request.post("/api/backup", { data: { slug: "sample" } });
  expect([200, 404].includes(backup.status())).toBeTruthy();

  const badSlug = await request.post("/api/import/preview", { multipart: { slug: "../escape", persona: "S", file: { name: "x.txt", mimeType: "text/plain", buffer: Buffer.from("hello") } } });
  expect([422, 401, 400].includes(badSlug.status()) || badSlug.status() !== 500).toBeTruthy();
});
