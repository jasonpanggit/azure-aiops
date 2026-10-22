import { expect, type Locator } from "@playwright/test";

/** Prevent supporting cards from stretching to the height of unrelated content. */
export async function expectContentSized(cards: Locator) {
  expect(await cards.count()).toBeGreaterThan(0);
  for (const card of await cards.all()) {
    const trailingSpace = await card.evaluate(element => {
      const rect = element.getBoundingClientRect();
      const bottoms = Array.from(element.children)
        .map(child => child.getBoundingClientRect())
        .filter(child => child.height > 0)
        .map(child => child.bottom);
      return rect.bottom - Math.max(rect.top, ...bottoms);
    });
    expect(trailingSpace).toBeLessThanOrEqual(32);
  }
}
