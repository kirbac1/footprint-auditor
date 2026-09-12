---
title: Footprint Auditor
emoji: 🔎
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: See where your personal data is exposed — a demo of the real pipeline
---

# Footprint Auditor — demo

This Space runs the **real** application: the same agent loop, the same
scope guard, the same claim check, the same namesake rules, the same plan and
letters. Only two things are replaced — the model is scripted and the search
results are invented — so **no real page is ever found**.

Sign in as the demo person with the button on the page, or create an account
to try the flow with an address of your own. Findings are synthetic either
way, and the page says so.

Source, design notes, guardrail contract and evals:
https://github.com/kirbac1/footprint-auditor

## What the demo shows

- The ownership gate: nothing is scanned until an email or phone is verified.
- A scan that searches, judges pages, and sets aside someone with the same
  name in another city.
- The steps as they happen, and afterwards the trace: every model call and
  tool call, with outcomes, tokens and timings.
- A plan with opt-out routes, and GDPR/CCPA letters in English or Finnish.

## Why a demo rather than the real thing

Running the real thing publicly means a model. A 30B model serving strangers
means renting a GPU at roughly $150–350 a month, and free inference tiers
forbid serving other people's traffic through them. It also means becoming a
data controller for other people's identifiers, which needs a privacy notice,
a retention schedule and processor agreements — none of which a free tier
provides.

So this is the honest version: everything except the model, in public, free.
To run it for real, clone the repository and point it at a model — including
one on your own machine, where nothing leaves it.
