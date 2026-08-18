# Repository UI/UX Context

Use this map to select sources and conventions. Re-inspect the repository for the current implementation; this file is routing guidance, not a substitute for reading code.

## Receipt Product

- Root: `frontend/`
- Framework: Next.js App Router, React, TypeScript, and Tailwind CSS.
- Pages: `frontend/src/app/`
- Reusable UI: `frontend/src/components/ui/`
- Layout: `frontend/src/components/layout/`
- Shared utilities and types: `frontend/src/lib/` and `frontend/src/types/`
- Visual design source: `Document/Google-stitch/DESIGN-V1.md`
- Interaction-flow source: `Document/Google-stitch/FLOW_STITCH.md`
- Feature-specific design source when reviewing FlowAccount receipt sync: `Document/DESING.md`

Inspect `frontend/tailwind.config.ts`, `frontend/src/app/globals.css`, the dashboard layout, and relevant UI primitives before recommending new styles. Current primitives include Button, Card, Input, and Label. Treat repeated Tailwind values as implementation evidence, not automatically as approved semantic tokens.

The product is an operational Smart P&L and receipt-validation application. Prefer scannable, high-trust, information-efficient workflows over generic dashboard decoration. Receipt validation may legitimately use split panes and grouped sections when they support document comparison; do not turn every subsection into an independent card by default.

## SPA Admin

- Root: `SPA/apps/admin-web/`
- Framework: Next.js App Router, React, TypeScript, and global CSS.
- Main feature components: `components/admin-dashboard.tsx` and `components/admin-module-pages.tsx`
- Tokens and responsive rules: `app/globals.css`
- Visual design source: `SPA/Document/DESING/Side-Admin/DESIGN.md`
- Flow source: `SPA/Document/DESING/Side-Admin/FLOW_STITCH.md`

Use `spa-branch-ux-ui` for every SPA review. Admin is desktop-first, bilingual, dense, and operational. Preserve rapid scanning, stable navigation, tables, status visibility, keyboard operation, and controlled disclosure of sensitive health information. Inspect the nested `AGENTS.md` before planning code changes because its Next.js instructions are version-specific.

## SPA Customer

- Root: `SPA/apps/customer-web/`
- Framework: Next.js App Router, React, TypeScript, and global CSS.
- Main booking component: `components/booking-experience.tsx`
- Tokens and responsive rules: `app/globals.css`
- Visual design source: `SPA/Document/DESING/Side-Customer/DESIGN.md`
- Flow source: `SPA/Document/DESING/Side-Customer/FLOW_STITCH.md`

Use `spa-branch-ux-ui` for every SPA review. Customer is mobile-first and bilingual. Preserve clear booking progress, services, duration, price, participant details, validation, confirmation, and a reachable primary action. Test Thai and English layouts and representative long content. Inspect the nested `AGENTS.md` before planning code changes.

## Source and Skill Precedence

1. Follow the user's explicit current instruction.
2. Follow repository and nested `AGENTS.md` instructions.
3. For `SPA/`, follow `spa-branch-ux-ui`, approved requirements and architecture, then the relevant design and flow sources.
4. For the receipt product, follow the relevant design and flow sources, then established reusable implementation patterns.
5. Treat existing UI as evidence, not unquestionable design authority.

There is no single repository-level `DESIGN.md`. Always name the design source actually read.

## Validation Routes

- Receipt frontend: run the relevant checks from `frontend/`; repository guidance requires lint and production build for implemented UI changes.
- SPA workspace: use the scripts in `SPA/package.json`, including lint, type-check, build, and relevant Playwright coverage.
- Validate only the target surface and risk-appropriate neighboring flows. Record commands, viewports, languages, states, and any limitation.
