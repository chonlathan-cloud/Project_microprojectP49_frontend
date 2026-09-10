# Design System: Spa 49 Application (Botanical Sanctuary)

## 1. Visual Identity & Vibe
- **Vibe:** Relaxing, Premium Organic, Authentic Thai Spa, Healing, and Serene.
- **Style:** Linen paper texture aesthetics, soft organic elevations, thin gold accents, and elegant botanical framing.
- **Shapes:** Soft rounded corners (`12px` to `16px`) for cards and containers. Full pill shapes (`999px`) for badges, tab toggles, and primary CTA buttons.

## 2. Color Palette
Derived from Spa 49 logo and menu visual identity:
*   **Primary Brand (Forest Green):** `#4E6148` - Main headers, solid section banners, active step indicators, and primary CTAs.
*   **Accent Brand (Spa Gold):** `#C3A36C` - Delicate borders, lotus icons, price text highlights, and divider lines.
*   **Background (Warm Cream):** `#F7F4EB` - Main background tone mimicking organic paper/linen texture.
*   **Surface / Card Fill:** `#FCFAF5` - Soft light cream for service cards, modals, and input fields.
*   **Text Primary (Deep Bark):** `#3A3F38` - Main titles, headings, and primary reading text.
*   **Text Secondary (Muted Olive):** `#7A8476` - Service duration labels, English subtitles, and descriptions.
*   **Status Confirmed / Paid (Sage Green):** `#2A9D8F` with `#E8F5E9` background.
*   **Status Pending / Reserved (Warm Amber):** `#D97706` with `#FEF3C7` background.

## 3. Typography
- **Headings (Display):** Serif (*Playfair Display* / *Lora* for EN, *Pridi* / *Sarabun* for TH). Elegant, high-end hospitality feel.
- **Body & UI Text:** Clean Sans-Serif (*Prompt* / *Inter*). High legibility for pricing, duration badges, and form controls.

## 4. UI Components & Elements
- **Pill Banner Headers:** Forest Green background (`#4E6148`), white/gold text, rounded pill ends (`999px`), decorated with lotus icons.
- **Service Cards:** Warm surface fill (`#FCFAF5`), thin gold border (`1px solid #C3A36C`), soft shadow (`0 4px 12px rgba(78, 97, 72, 0.06)`). Includes Thai/EN names, duration pill selector, bold gold price, and `+ Add to Cart` button.
- **Floating Cart Bar:** Sticky bottom bar in Forest Green (`#4E6148`), showing selected treatment count, guest count, longest participant timeline (mins), total price (`฿`), and a gold/white "Proceed to Book" button.
- **Participant Treatment Plan:** A compact ordered list per guest with sequence numbers, duration, price/included state, and accessible move/remove actions. Each guest can hold 1–3 treatments; Couple Package stays first on both plans and shows a single charge.
- **Room Schedule Matrix Slots:**
  - **Available:** Clean white card with thin gold outline, clickable to assign a room.
  - **Occupied / In Session:** Forest Green filled card displaying customer name, service duration, and assigned therapist ID.
  - **Buffer / Cleaning:** Soft yellow block representing a 15-minute sanitization window.
  - **Closed:** Diagonal grey striped background (`repeating-linear-gradient`) with a dark badge "Closed".
