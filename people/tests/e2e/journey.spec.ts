// Both people complete a request → session → wrap-up journey in demo mode.
import { expect, test, type Browser, type Page } from "@playwright/test";

async function signIn(browser: Browser, name: RegExp, viewport?: { width: number; height: number }) {
  const ctx = await browser.newContext(viewport ? { viewport } : {});
  const page = await ctx.newPage();
  await page.goto("/login");
  await page.getByRole("button", { name }).click();
  await page.waitForURL((u) => u.pathname === "/");
  return page;
}

/** On phones the room is split into tabs; on desktop everything is visible. */
async function tab(page: Page, name: "Chat" | "Together" | "Notes") {
  const t = page.getByRole("tab", { name });
  if (await t.isVisible()) await t.click();
}

/** The live indicator only shows "Live" once the page is hydrated and subscribed. */
async function live(page: Page) {
  await expect(page.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible({ timeout: 15_000 });
}

async function resetDemo(page: Page) {
  await page.goto("/setup");
  await page.getByRole("button", { name: "Reset demo data" }).click();
  await expect(page.getByText("Back to the starting sample data.")).toBeVisible();
}

test("asker and helper complete a session end to end", async ({ browser }, info) => {
  const shots = (n: string) => info.outputPath(`${n}.png`);
  const maya = await signIn(browser, /^Maya/);
  await resetDemo(maya);
  const omar = await signIn(browser, /^Omar/);

  // Maya asks.
  await maya.goto("/");
  await maya.getByLabel("What are you trying to figure out?").fill("I understand Arabic, but I'm nervous speaking it.");
  await maya.getByRole("button", { name: /Find someone/ }).click();
  await maya.waitForURL(/requests\/new/);
  await expect(maya.getByText(/Suggested from keywords/)).toBeVisible();
  await maya.getByRole("button", { name: "Text", exact: true }).click(); // voice only
  await maya.getByRole("button", { name: /See who can help/ }).click();
  await expect(maya.getByText("People who could help")).toBeVisible();
  await expect(maya.getByText("Speaks Jordanian Arabic")).toBeVisible();
  await expect(maya.getByText("Available now for voice")).toBeVisible();
  await maya.getByRole("button", { name: "Ask Omar" }).click();
  await expect(maya.getByText("Waiting for a reply")).toBeVisible();
  await expect(maya.getByText(/session only starts once they accept/)).toBeVisible();

  // Omar sees the invitation and accepts.
  await omar.goto("/helping");
  await expect(omar.getByText("I understand Arabic, but I'm nervous speaking it.")).toBeVisible();
  await omar.screenshot({ path: shots("helper-inbox"), fullPage: true });
  await omar.getByRole("button", { name: "Accept" }).click();
  await omar.waitForURL(/\/sessions\/[0-9a-f-]{36}$/);

  // Maya's waiting page updates live (no manual reload) and links to the session.
  await expect(maya.getByText("You're matched.")).toBeVisible({ timeout: 15_000 });
  await maya.getByRole("link", { name: /Go to session/ }).click();
  await maya.waitForURL(/\/sessions\/[0-9a-f-]{36}$/);
  const sessionUrl = maya.url();
  await live(maya);
  await live(omar);

  // Realtime text both ways.
  await maya.getByRole("textbox", { name: "Message" }).fill("Marhaba! Can we start slowly?");
  await maya.getByRole("button", { name: "Send" }).click();
  await expect(omar.getByText("Marhaba! Can we start slowly?")).toBeVisible({ timeout: 15_000 });
  await omar.getByRole("textbox", { name: "Message" }).fill("Of course — keefik?");
  await omar.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(maya.getByText("Of course — keefik?")).toBeVisible({ timeout: 15_000 });

  // Learn layout: shared checklist, shared notes and private notes.
  await tab(omar, "Together");
  await omar.getByRole("textbox", { name: "New item" }).fill("Greet someone in Ammani Arabic");
  await omar.getByRole("button", { name: "Add item" }).click();
  await tab(maya, "Together");
  await expect(maya.getByText("Greet someone in Ammani Arabic")).toBeVisible({ timeout: 15_000 });
  await tab(maya, "Notes");
  await tab(omar, "Notes");
  await maya.getByLabel("Shared notes").fill("keefik = how are you (to a woman)");
  await expect(maya.getByText("Saved").first()).toBeVisible({ timeout: 10_000 });
  await maya.getByLabel("Private notes").fill("Practise every morning");
  await expect(omar.getByLabel("Shared notes")).toHaveValue(/keefik = how are you/, { timeout: 15_000 });
  await expect(omar.getByLabel("Private notes")).toHaveValue("");

  // Calls are clearly unavailable without LiveKit; nothing is simulated.
  await tab(maya, "Chat");
  await expect(maya.getByText("Voice and video aren't set up on this server")).toBeVisible();
  await maya.screenshot({ path: shots("room"), fullPage: true });

  // An outsider can't open the session or get a call token.
  const chris = await signIn(browser, /^Chris/);
  await chris.goto(sessionUrl); // streamed response, so check content rather than status
  await expect(chris.getByRole("heading", { name: "Nothing here" })).toBeVisible();
  await expect(chris.getByText("Marhaba! Can we start slowly?")).toHaveCount(0);
  const token = await chris.request.post(`${sessionUrl.replace("/sessions/", "/api/sessions/")}/token`);
  expect([404, 501]).toContain(token.status());

  // End and wrap up.
  await maya.getByRole("button", { name: "End session" }).click();
  await maya.getByRole("dialog", { name: "Confirm" }).getByRole("button", { name: "End session" }).click();
  await maya.waitForURL(/\/wrap$/);
  await expect(omar.getByText("This session has ended.")).toBeVisible({ timeout: 15_000 });
  await maya.getByRole("button", { name: "Yes" }).click();
  await maya.getByRole("button", { name: "5 of 5" }).click();
  await maya.getByLabel(/happy to talk with Omar again/).check();
  await maya.getByRole("button", { name: "Save", exact: true }).click();
  await expect(maya.getByText("Feedback sent — thank you.")).toBeVisible();
  await expect(maya.getByLabel("What I learned")).toHaveValue(/keefik/);
  await maya.getByRole("button", { name: "Save to My learning" }).click();
  await expect(maya.getByText("Saved.")).toBeVisible();
  await maya.screenshot({ path: shots("wrap"), fullPage: true });
  await maya.goto("/learning");
  await expect(maya.getByText("I understand Arabic, but I'm nervous speaking it.").first()).toBeVisible();
});

test("no-match state explains itself and offers real options", async ({ browser }) => {
  const maya = await signIn(browser, /^Maya/);
  await resetDemo(maya);
  await maya.goto("/requests/new?q=" + encodeURIComponent("Can someone show me Arabic calligraphy on video?") + "&topic=languages.arabic.egyptian");
  await maya.getByRole("button", { name: "Text" }).click();
  await maya.getByRole("button", { name: "Voice" }).click();
  await maya.getByRole("button", { name: "Video" }).click();
  await maya.getByRole("button", { name: /See who can help/ }).click();
  await expect(maya.getByText("Nobody available right now")).toBeVisible();
  await expect(maya.getByText(/We won.t pretend otherwise/)).toBeVisible();
  await expect(maya.getByRole("button", { name: "Leave my question" })).toBeVisible();
  await expect(maya.getByRole("button", { name: "Pick a time" })).toBeVisible();
  await maya.getByRole("button", { name: "Leave my question" }).click();
  await expect(maya.getByText(/waiting for a written reply/)).toBeVisible();
});

test("helper can decline, and the asker sees an honest status", async ({ browser }) => {
  const maya = await signIn(browser, /^Maya/);
  await resetDemo(maya);
  const chris = await signIn(browser, /^Chris/);
  await maya.goto("/requests/new?q=" + encodeURIComponent("Why does my rice keep coming out mushy?") + "&intent=ask");
  await maya.getByRole("button", { name: /See who can help/ }).click();
  await maya.getByRole("button", { name: "Ask Chris" }).click();
  await expect(maya.getByText("Waiting for a reply")).toBeVisible();
  await chris.goto("/helping");
  await chris.getByRole("button", { name: "Decline" }).click();
  await expect(maya.getByText(/can't make it this time/)).toBeVisible({ timeout: 15_000 });
  await expect(maya.getByText("People who could help")).toBeVisible();
});

test("moderator dashboard is moderator-only", async ({ browser }) => {
  const maya = await signIn(browser, /^Maya/);
  await maya.goto("/moderation");
  await expect(maya.getByText("Moderators only")).toBeVisible();
  const sam = await signIn(browser, /^Sam/);
  await sam.goto("/moderation");
  await expect(sam.getByRole("heading", { name: "Moderation" })).toBeVisible();
  await sam.getByRole("button", { name: /Open evidence/ }).first().click();
  await expect(sam.getByText(/Your access was recorded/)).toBeVisible();
});

test("main navigation works", async ({ browser }, info) => {
  const maya = await signIn(browser, /^Maya/);
  const isPhone = info.project.name === "phone";
  const nav = maya.getByRole("navigation", { name: "Main" }).filter({ visible: true });
  const targets = isPhone ? ["Requests", "Sessions", "Profile", "Home"] : ["My requests", "Helping", "Sessions", "My learning", "Profile", "Home"];
  for (const label of targets) {
    await nav.getByRole("link", { name: new RegExp(`^${label}`) }).click();
    await expect(nav.getByRole("link", { name: new RegExp(`^${label}`) })).toHaveAttribute("aria-current", "page");
  }
});
