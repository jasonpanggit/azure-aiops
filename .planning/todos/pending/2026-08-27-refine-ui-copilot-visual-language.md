---
created: 2026-08-27T12:17:49+08:00
title: Refine Copilot visual language
area: ui
severity: cosmetic
files:
  - web/src/components/ui/CopilotDrawerButton.tsx
  - web/src/app/globals.css
  - web/src/app/page.tsx
---

## Problem

The current UI feels too wordy and the Ask Copilot entry point does not visually belong to the surrounding theme. The home-page action is especially prominent and verbose, while the repeated page-level Copilot buttons use inconsistent text labels and styling.

## Solution

Audit the shared UI language and reduce unnecessary copy, starting with the Copilot entry points. Consider a compact icon-first control with an accessible label or tooltip, align its colors, shape, spacing, and hover states with the existing theme, and apply the same concise treatment consistently across pages without removing discoverability or keyboard/screen-reader support.
