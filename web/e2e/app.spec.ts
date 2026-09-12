import { existsSync, readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

// The API writes verification codes here (EA_VERIFICATION_DELIVERY=outbox).
const OUTBOX = new URL("../../e2e-outbox.jsonl", import.meta.url);

async function codeFor(destination: string): Promise<string> {
  for (let attempt = 0; attempt < 50; attempt++) {
    if (existsSync(OUTBOX)) {
      const sent = readFileSync(OUTBOX, "utf8")
        .split("\n")
        .filter(Boolean)
        .map((line) => JSON.parse(line) as { destination: string; code: string });
      const latest = sent.reverse().find((entry) => entry.destination === destination);
      if (latest) return latest.code;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`no verification code was sent to ${destination}`);
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test("sign up, verify, scan, sort out a namesake and act on the plan", async ({ page }) => {
  const errors = collectErrors(page);
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/");
  await page.getByRole("tab", { name: "Create account" }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-battery");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("tab", { name: "Your details" })).toBeVisible();

  // Prove the email with the code the server "sent".
  await page.getByLabel("Value", { exact: true }).fill(email);
  await page.getByRole("button", { name: "Add and send code" }).click();
  await page.getByLabel(`Verification code for ${email}`).fill(await codeFor(email));
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await expect(page.getByText("Verified", { exact: true })).toBeVisible();

  // A name, confirmed as mine, and a city to tell me apart from namesakes.
  const details = page.locator("form", { hasText: "Add a detail" });
  await details.getByLabel("Kind").selectOption("name");
  await details.getByLabel("Value", { exact: true }).fill("Maija Meikäläinen");
  await details.getByLabel(/This name is mine/).check();
  await details.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("Maija Meikäläinen", { exact: true })).toBeVisible();

  const context = page.locator("form", { hasText: "Tell yourself apart" });
  await context.getByLabel("Detail value").fill("Helsinki");
  await context.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("Helsinki", { exact: true })).toBeVisible();

  // The demo scan: the Oulu namesake is left out, and what is left is a
  // hypothesis until the person settles it -- a name and a city are not proof.
  await page.getByRole("tab", { name: "Footprint scan" }).click();
  await page.getByRole("button", { name: "Scan my footprint" }).click();
  await expect(page.getByText(/Left out 1 result/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Might be someone with your name" })).toBeVisible();

  // "Not me" removes one for good; "This is me" moves the other into the plan.
  const whitepages = page.locator(".findings.review .finding", { hasText: "whitepages" });
  await whitepages.getByRole("button", { name: "Not me" }).click();
  await expect(whitepages).toHaveCount(0);

  const spokeo = page.locator(".findings.review .finding", { hasText: "spokeo" });
  await spokeo.getByRole("button", { name: "This is me" }).click();
  await expect(page.getByRole("heading", { name: "About you" })).toBeVisible();

  await page.getByRole("button", { name: "See what to do about these" }).click();
  await expect(page.getByText("Opt out of Spokeo")).toBeVisible();

  // A strict CSP that blocked anything would show up here.
  expect(errors).toEqual([]);
});

test("an earlier scan opens in the panel when you ask to see it", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/");
  await page.getByRole("tab", { name: "Create account" }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-battery");
  await page.getByRole("button", { name: "Create account" }).click();

  await page.getByLabel("Value", { exact: true }).fill(email);
  await page.getByRole("button", { name: "Add and send code" }).click();
  await page.getByLabel(`Verification code for ${email}`).fill(await codeFor(email));
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await expect(page.getByText("Verified", { exact: true })).toBeVisible();

  const details = page.locator("form", { hasText: "Add a detail" });
  await details.getByLabel("Kind").selectOption("name");
  await details.getByLabel("Value", { exact: true }).fill("Maija Meikäläinen");
  await details.getByLabel(/This name is mine/).check();
  await details.getByRole("button", { name: "Add", exact: true }).click();

  // A city does not make a match confident, but it does keep the Oulu
  // namesake out, which is what leaves a clean list to click through.
  const context = page.locator("form", { hasText: "Tell yourself apart" });
  await context.getByLabel("Detail value").fill("Helsinki");
  await context.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("Helsinki", { exact: true })).toBeVisible();

  // Two scans, so the earlier-scans list appears at all.
  await page.getByRole("tab", { name: "Footprint scan" }).click();
  await page.getByRole("button", { name: "Scan my footprint" }).click();
  await expect(page.getByRole("heading", { name: "Might be someone with your name" })).toBeVisible();
  await page.getByRole("button", { name: "Scan my footprint" }).click();
  await expect(page.getByRole("heading", { name: "Earlier scans" })).toBeVisible();

  // The panel is above the list: clicking View has to bring the older scan
  // into it, and say which row is showing, or the button looks dead.
  const older = page.locator(".row").last();
  await older.getByRole("button", { name: "View" }).click();
  await expect(older.getByRole("button", { name: "Showing above" })).toBeVisible();
  await expect(page.locator(".row.selected")).toHaveCount(1);
});

test("a forgotten password can be reset with a code", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/");
  await page.getByRole("tab", { name: "Create account" }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-battery");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("tab", { name: "Your details" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();

  await page.getByRole("button", { name: "Forgot your password?" }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByRole("button", { name: "Send me a code" }).click();
  await expect(page.getByText(/a code is on its way/)).toBeVisible();

  await page.getByLabel("Code from the email").fill(await codeFor(email));
  await page.getByLabel("New password", { exact: true }).fill("a-brand-new-password");
  await page.getByRole("button", { name: "Set new password" }).click();

  // Straight into the app on the new password.
  await expect(page.getByRole("tab", { name: "Your details" })).toBeVisible();
});

test("the interface switches to Finnish", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Vaihda kieli suomeksi" }).click();
  await expect(page.getByRole("heading", { name: "Katso, missä henkilötietosi näkyvät." })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "fi");
  await expect(page.getByRole("tab", { name: "Luo tili" })).toBeVisible();
});
