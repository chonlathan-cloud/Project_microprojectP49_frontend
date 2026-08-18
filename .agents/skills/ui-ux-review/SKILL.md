---
name: ui-ux-review
description: Review and plan frontend UI/UX for this repository as a senior product designer, with emphasis on task clarity, visual hierarchy, information density, product-specific character, design-system consistency, accessibility, responsive behavior, and detection of generic AI-generated patterns. Use for critiques, design reviews, UI implementation plans, post-implementation audits, frontend pull-request review, or before materially changing pages and components under frontend/ or SPA/. Do not use for backend-only, infrastructure, database, API-contract, or DevOps work with no user-interface impact.
---

# UI/UX Review

Review production interfaces for intentional product decisions. Optimize for usability, coherence, information efficiency, and long-term consistency—not vague goals such as “modern,” “premium,” or “clean.”

## Establish Context

Before reviewing:

1. Read [references/repository-context.md](references/repository-context.md) and classify the target as `receipt`, `spa-admin`, or `spa-customer`.
2. Read the target's authoritative design source listed there. Do not assume a repository-wide `DESIGN.md` exists.
3. For `SPA/`, also use `spa-branch-ux-ui` and obey its stricter source, implementation, and read-only Stitch boundaries.
4. Inspect the target page, its layout, relevant reusable components, styling or tokens, and related state-management code.
5. Inspect neighboring or comparable pages when they establish a pattern worth preserving.
6. State the user's primary task and the page's primary visual anchor before judging individual components.
7. Separate verified evidence from assumptions. If rendered output, a viewport, a language, or a state cannot be inspected, name the limitation.

Reuse established patterns when they support the task. Do not preserve a weak pattern merely because it already exists; explain why a deviation is justified and how it should become reusable.

## Select the Review Mode

Use the mode the user requests. Default to Critique Mode when the request is ambiguous. Do not move from critique to implementation planning, or from planning to code changes, without user approval.

### Critique Mode

Review only. Do not modify files.

Return these headings:

```markdown
### Primary user task
### Visual anchor
### Critical UX issues
### Visual hierarchy issues
### AI-generated patterns detected
### Recommended changes
```

Prefix every recommendation with exactly one action:

- `REMOVE` — eliminate content or chrome that does not help the task.
- `MERGE` — combine fragmented information or controls.
- `MOVE` — relocate content to match task sequence or importance.
- `REDUCE` — lower visual weight, repetition, decoration, or space.
- `EMPHASIZE` — strengthen the element that should guide attention.
- `REPLACE` — substitute a misleading or unsuitable pattern.
- `KEEP` — preserve an effective, product-specific decision.

Give the reason, user impact, and supporting evidence for each recommendation. Prioritize material issues; do not produce filler recommendations to make the review look comprehensive.

### Implementation Plan Mode

Convert an approved critique into a plan. Do not modify files.

For each change, specify:

- affected files and components;
- existing components or tokens to reuse;
- concrete layout and interaction changes;
- desktop, tablet, and mobile implications relevant to the surface;
- accessibility and semantic HTML implications;
- implementation risks, dependencies, and validation evidence needed.

Identify any recommendation that would alter backend behavior, API contracts, authentication, authorization, business logic, or domain models, and exclude it from the UI plan unless separately approved.

### Final Review Mode

Review the implemented result without modifying it. Inspect the relevant diff, code, and rendered states when available. Compare it with the approved critique and plan rather than introducing an unrelated redesign.

Score and explain:

- Visual hierarchy: `/10`
- Information density: `/10`
- Interaction clarity: `/10`
- Design-system consistency: `/10`
- Responsive UX: `/10`
- Accessibility: `/10`
- Product-specific character: `/10`
- AI-template smell: `LOW`, `MEDIUM`, or `HIGH`

List remaining issues and distinguish blockers from follow-up improvements. Do not approve when AI-template smell is `HIGH` or when a critical task, accessibility, responsive, or behavioral regression remains.

## Apply Product Reasoning

Answer these questions for every reviewed page:

1. What is the user's primary task?
2. What information should dominate visually?
3. What is secondary?
4. What can be removed?
5. What can be merged?
6. What should be de-emphasized?
7. Are actions prioritized correctly?
8. Is information density appropriate for the user and device?
9. Does the interface match the rest of its product surface?
10. Which elements make the page feel AI-generated?

Evaluate three dimensions:

- **Product and UX:** information architecture, task clarity, friction, action priority, discoverability, interaction clarity, and loading, empty, error, validation, success, and permission states.
- **Visual design:** hierarchy, typography, density, spacing rhythm, alignment, composition, balance, contrast, and component consistency.
- **Frontend quality:** reuse, responsive behavior, accessibility, semantic HTML, token usage, maintainability, and unnecessary dependency or style proliferation.

## Detect AI-Template Smell

Actively look for:

- excessive cards, nested cards, or containers added only to look designed;
- unnecessary shadows, gradients, rounded surfaces, badges, icons, or helper text;
- generic dashboard grids and one-card-per-metric composition;
- oversized headings, excessive whitespace, or low information density in operational tools;
- multiple competing primary actions or equal visual weight for unrelated information;
- icons where text is clearer, decorative centering, and repeated section wrappers;
- copied landing-page patterns that conflict with the actual workflow;
- arbitrary one-off styling that ignores nearby components or tokens.

Prefer decisions in this order:

`remove > simplify > merge > restructure > add`

Do not add UI merely to make the page appear more sophisticated. Preserve decoration only when it communicates hierarchy, state, brand, or interaction meaning.

## Protect Application Behavior

- Preserve backend behavior, API contracts, business logic, authentication, authorization, and domain models.
- Treat UI changes as behavior-preserving unless the user explicitly approves broader product changes.
- Reuse existing components and tokens when reasonable; avoid arbitrary one-off styles.
- Do not introduce dependencies without a concrete, documented benefit.
- Maintain desktop, tablet, and mobile behavior appropriate to the target surface.
- Maintain or improve keyboard access, semantics, focus visibility, contrast, reduced-motion behavior, labels, and status/error announcements.
- Do not claim visual, responsive, accessibility, lint, type-check, test, or build validation unless it was actually performed.

## Keep Reviews Decisive

Lead with the highest-impact finding. Tie every criticism to the primary task, visual anchor, product convention, or measurable accessibility/responsive concern. Avoid taste-only feedback and generic praise. When sources conflict, identify the conflict and follow the authority rules in the relevant project skill or design documentation.
