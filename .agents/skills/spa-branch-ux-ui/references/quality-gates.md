# Spa Branch UX/UI Quality Gates

Apply the relevant gates to specifications, implementation, and audits. Report gates that cannot yet be evaluated.

## Product and Flow

- Tie every screen and primary action to an approved user goal.
- Preserve a clear entry, progress state, completion state, and recovery path.
- Show the consequences of destructive, financial, scheduling, and status-changing actions before confirmation.
- Define loading, empty, validation, permission, conflict, retry, and success states where relevant.
- Do not imply live availability, successful payment, confirmed booking, or saved data without an approved contract and response state.

## Admin Usability

- Verify dense pages at `1280px`, `1440x900`, and `1920x1080`.
- Keep primary filters, date context, branch context, system status, and high-frequency actions discoverable.
- Support keyboard navigation and visible focus through tables, dialogs, drawers, forms, menus, and calendars.
- Avoid information encoded by color alone; pair status colors with text and/or icons.
- Prevent tables, drawers, and sticky regions from hiding critical controls or content.

## Customer Usability

- Verify at `360x800`, `390x844`, and `430x932`.
- Keep tap targets at least `44x44px` unless an approved platform convention provides an equivalent accessible target.
- Keep total price, total duration, selected services, booking step, and primary CTA understandable throughout booking.
- Preserve entered information when validation fails or the user moves backward.
- Avoid horizontal scrolling for core booking content.

## Visual System

- Use the relevant local `DESIGN.md` tokens and component intent.
- Maintain the shared Forest Green and Spa Gold identity while respecting Admin density and Customer serenity.
- Use consistent spacing, radius, type hierarchy, status semantics, and interaction states.
- Treat Stitch screenshots as visual references, not pixel dimensions or automatic implementation code.

## Bilingual Content

- Check Thai and English independently; do not validate layout using English alone.
- Avoid truncating service names, health notices, prices, dates, and confirmation details.
- Use locale-aware date, time, number, and Thai baht formatting.
- Define the language-switch behavior and persistence only when requirements approve it.

## Accessibility

- Target WCAG 2.2 AA unless approved requirements set a stricter baseline.
- Meet contrast requirements in default, hover, focus, disabled, error, and selected states.
- Provide semantic headings, landmarks, labels, error associations, live status announcements, and dialog focus management.
- Support keyboard-only use and reduced motion.
- Give icons accessible names when they communicate meaning; hide purely decorative icons from assistive technology.

## Verification Evidence

- Record the commands run and their results.
- Record viewports and languages checked.
- Identify the Stitch screens compared, if any.
- Separate verified behavior from assumptions or visually inferred behavior.
- List unresolved requirement, architecture, content, and backend-contract gaps.

