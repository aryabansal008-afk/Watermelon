import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const env = Object.fromEntries(readFileSync(".env", "utf8").split("\n").filter(Boolean).map(l => { const p=l.indexOf("="); return [l.slice(0,p),l.slice(p+1)]; }));

test("public landing, navigation, and mobile layout", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Your code remembers");
  await expect(page.getByRole("link", { name: "Recover Project History" }).first()).toBeVisible();
  await expect(page.getByText("ILLUSTRATIVE · NOT A LIVE FINDING")).toBeVisible();
  await page.screenshot({ path: ".artifacts/landing-desktop.png", fullPage: true });
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Features", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("context");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Recover Project History", exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: ".artifacts/landing-mobile.png", fullPage: true });
});

test("unauthorized API is protected and invalid login stays signed out", async ({ page, request }) => {
  const response = await request.get("/api/backend/v1/projects");
  expect(response.status()).toBe(401);
  await page.goto("/login");
  await page.getByLabel("Workspace password").fill("incorrect-password");
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await expect(page.locator(".auth-panel [role=alert]")).toContainText("Incorrect");
});

test("owner can navigate every workspace route", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.getByLabel("Workspace password").fill(env.OWNER_PASSWORD);
  await page.getByRole("button", { name: "Open my workspace" }).click();
  await expect(page).toHaveURL(/workspace\/.*\/dashboard/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "A fresh slice of context." })).toBeVisible();
  const projectId = page.url().match(/workspace\/([^/]+)/)?.[1];
  expect(projectId).toBeTruthy();
  const routes = [["projects", "Projects"], ["decisions", "Decision explorer"], ["discussions", "Discussions"], ["knowledge-graph", "Knowledge graph"], ["timeline", "The project’s paper trail"], ["code", "Code with context"], ["pull-requests", "PR intelligence"], ["ask", "Ask Watermelon"], ["integrations", "Keep your sources close."], ["settings", "Workspace settings"]];
  for (const [route, heading] of routes) {
    await page.goto(`/workspace/${projectId}/${route}`);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }
  await page.goto(`/workspace/${projectId}/integrations`);
  const openRouterCard = page.locator(".integration-card").filter({ has: page.getByRole("heading", { name: "OpenRouter" }) });
  await expect(openRouterCard.getByText("configured unverified", { exact: true })).toBeVisible();
  await page.goto(`/workspace/${projectId}/pull-requests`);
  await expect(page.getByRole("heading", { name: "PR intelligence" })).toBeVisible();
  await expect(page.getByRole("status", { name: "Loading workspace" })).toBeHidden({ timeout: 90_000 });
  await expect(page.locator(".table-wrap, .empty").first()).toBeVisible();
  await page.screenshot({ path: ".artifacts/pr-intelligence-error.png", fullPage: true });
  await page.goto(`/workspace/${projectId}/ask`);
  await page.getByLabel("Ask Watermelon").fill("What is Watermelon?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByText(/Watermelon is a project scoped engineering memory/).first()).toBeVisible();
  await page.screenshot({ path: ".artifacts/ask-watermelon-product-answer.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/workspace/${projectId}/dashboard`);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page.getByRole("heading", { name: "A fresh slice of context." })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
