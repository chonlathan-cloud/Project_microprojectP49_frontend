---
name: spa-branch-ux-ui
description: Design, review, implement, and visually validate UX/UI for the Spa branch application under SPA/, covering the SPA-Admin-Views desktop operations experience and SPA-Customer-Views customer booking experience. Use for Spa branch journeys, wireframes, screen specifications, design-system application, responsive behavior, accessibility, bilingual Thai/English UI, frontend components, visual QA, or comparison with the two approved Stitch projects. Do not use for the receipt frontend, unrelated Stitch projects, backend-only work, or business/architecture documents with no UX/UI impact.
---

# Spa Branch UX/UI

Build a coherent Spa branch experience from approved product artifacts, local design sources, and two read-only Stitch projects. Keep Admin and Customer visually related while optimizing each surface for its users and devices.

## Enforce Boundaries

- Create or modify application code only under `SPA/`. Do not place Spa application code in the repository's existing `frontend/` directory.
- Use only these Stitch projects:
  - `SPA-Admin-Views` — `4396310542632779378`
  - `SPA-Customer-Views` — `16425235465563176187`
- Treat Stitch as read-only. Allow only listing and retrieval operations such as `list_projects`, `get_project`, `list_screens`, `get_screen`, and `list_design_systems`.
- Never call Stitch tools that create, generate, edit, apply, upload, update, or delete. If a task would benefit from a Stitch mutation, provide a proposed prompt or change specification for the user instead.
- Do not use any other Stitch project as inspiration, fallback, or source material.
- Do not invent business rules, roles, permissions, pricing, availability logic, booking constraints, or backend contracts. Mark missing decisions and defer them to the requirements/design sequence.

## Authenticate Stitch Safely

1. Try one read-only call through the configured Stitch MCP connection first. The repository configuration maps `X-Goog-Api-Key` from the `STITCH_API_KEY` environment variable.
2. If the call returns a generic authentication failure such as `Auth required` or `401`, or reports a missing/invalid API-key credential, retrieve the latest enabled value of Secret Manager secret `STITCH-API-KEY` from GCP project `the49-487609`. Supply it only to the runtime process as `STITCH_API_KEY` for one retry; honor any required cloud or sandbox approval.
3. Never print the value, return it in tool output, place it in a command argument, write it to disk, persist it in `.codex/config.toml`, or commit it. Capture it directly from Secret Manager into the environment of the process that needs it.
4. Retry one read-only Stitch call. If the response says OAuth 2.0 is required, API keys are unsupported, or equivalent, stop. Do not repeatedly read the secret; report that an OAuth flow is required because an API key cannot replace OAuth authorization.
5. If the current Codex Desktop MCP transport cannot reload environment variables, explain that the Desktop application must be restarted after a secure environment update. Continue from approved local `DESIGN.md` and `FLOW_STITCH.md` sources when live Stitch access is unavailable and label that limitation.

## Respect the Delivery Sequence

Use approved artifacts in this order as they become available:

1. Business requirements
2. HLD
3. TTD
4. LLD
5. UX/UI implementation

Before approved business requirements exist, limit work to exploratory UX, source analysis, inventories, and clearly labeled assumptions. Do not scaffold the production Spa application or lock in architecture prematurely.

For implementation work, read all approved artifacts that affect the requested surface. If a required artifact is missing or materially ambiguous, identify the exact decision needed instead of silently choosing product behavior.

## Route the Task

1. Classify the surface as `admin`, `customer`, or `cross-surface`.
2. Classify the outcome as `explore`, `specify`, `implement`, or `audit`.
3. Read [references/sources.md](references/sources.md), then load only the Admin, Customer, or shared sources required for the task.
4. Read [references/quality-gates.md](references/quality-gates.md) before producing UI specifications, code, or a UX/UI audit.
5. Inspect existing files under `SPA/` before proposing paths or creating components.

## Resolve Source Conflicts

Apply authority by dimension rather than treating every source as interchangeable:

- Follow the user's explicit current instruction first.
- For behavior, permissions, states, data, and acceptance criteria, follow approved business requirements and HLD/TTD/LLD; use `FLOW_STITCH.md` only where those artifacts are silent.
- For visual identity, tokens, typography, shape, and component styling, follow the relevant local `DESIGN.md`; use the matching Stitch project to interpret composition and visual intent.
- Treat existing application code as implementation evidence, not product authority.
- Surface unresolved contradictions. Do not blend conflicting rules into a new rule.

## Design the Experience

### Admin

- Optimize for receptionists and branch managers performing dense, time-sensitive operational work.
- Use desktop-first information architecture, scannable tables, keyboard-friendly controls, stable navigation, visible system status, and efficient bulk or inline actions.
- Preserve health-alert visibility without exposing sensitive information more broadly than the approved requirements permit.

### Customer

- Optimize for mobile-first booking, service discovery, bilingual comprehension, and low-friction completion.
- Keep pricing, duration, selected items, booking progress, validation, and confirmation continuously understandable.
- Adapt Stitch's current desktop canvases into responsive mobile experiences; do not copy their reported dimensions as target viewports.

### Cross-surface

- Keep service names, booking states, time semantics, pricing display, and brand tokens consistent.
- Adapt information density and interaction patterns to each user group rather than forcing identical layouts.
- Specify loading, empty, validation, partial-failure, offline/retry, permission-denied, and success states when relevant.

## Implement Under SPA

- Inspect approved HLD/TTD/LLD before choosing the framework, routing, state management, API layer, or folder layout.
- Reuse components and tokens inside the new Spa application when they genuinely serve both surfaces.
- Keep domain behavior outside presentational components.
- Externalize realistic fixtures and label them as mock data until contracts are approved.
- Support Thai and English without fixed-width text assumptions. Account for longer translations, Thai line breaking, locale-aware dates/times, and Thai baht formatting.
- Use semantic HTML, visible focus, keyboard operation, sufficient contrast, reduced-motion support, and accessible names.
- Avoid decorative complexity that reduces operational speed or booking clarity.

## Validate Before Completion

- Run the Spa application's available lint, type-check, test, and production-build commands in proportion to the change.
- Perform visual checks at the target viewports listed in [references/quality-gates.md](references/quality-gates.md).
- Compare relevant pages against the matching Stitch screens through read-only retrieval when visual fidelity matters.
- Check both Thai and English states, primary interaction paths, responsive behavior, focus order, empty/error states, and representative long content.
- Report changed files, verified commands/viewports, material assumptions, source conflicts, and remaining requirements gaps.
