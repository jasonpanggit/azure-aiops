import { expect, type Locator } from "@playwright/test";

/** Keep explanatory prose as wide as its own container, without changing columns. */
export async function expectFullWidthProse(paragraphs: Locator) {
  expect(await paragraphs.count()).toBeGreaterThan(0);
  for (const paragraph of await paragraphs.all()) {
    await expect(paragraph).toHaveCSS("max-width", "none");
    const geometry = await paragraph.evaluate(element => {
      const parent = element.parentElement!;
      const style = getComputedStyle(parent);
      const available = parent.clientWidth
        - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return { width: element.getBoundingClientRect().width, available };
    });
    expect(geometry.available).toBeGreaterThan(0);
    expect(geometry.width).toBeGreaterThanOrEqual(geometry.available - 2);
    expect(geometry.width).toBeLessThanOrEqual(geometry.available + 2);
  }
}

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
