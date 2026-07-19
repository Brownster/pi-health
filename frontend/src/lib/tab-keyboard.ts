import type { KeyboardEvent } from "react";

const NEXT_KEYS = new Set(["ArrowRight", "ArrowDown"]);
const PREVIOUS_KEYS = new Set(["ArrowLeft", "ArrowUp"]);

/** Implements automatic activation for tabs within the nearest tablist. */
export function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>): void {
  if (
    !NEXT_KEYS.has(event.key)
    && !PREVIOUS_KEYS.has(event.key)
    && event.key !== "Home"
    && event.key !== "End"
  ) {
    return;
  }

  const tablist = event.currentTarget.closest<HTMLElement>('[role="tablist"]');
  const tabs = tablist
    ? Array.from(tablist.querySelectorAll<HTMLButtonElement>('[role="tab"]:not([disabled])'))
    : [];
  const currentIndex = tabs.indexOf(event.currentTarget);
  if (currentIndex < 0 || tabs.length < 2) return;

  event.preventDefault();
  let nextIndex = currentIndex;
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = tabs.length - 1;
  if (NEXT_KEYS.has(event.key)) nextIndex = (currentIndex + 1) % tabs.length;
  if (PREVIOUS_KEYS.has(event.key)) nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;

  tabs[nextIndex].focus();
  tabs[nextIndex].click();
}
