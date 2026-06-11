# Handoff: 日历 AI 助手（Calendar + AI Agent）

## Overview
A calendar application paired with an always-on AI scheduling assistant. The AI
crawls the user's connected email inboxes, extracts dated items (deadlines,
flights, meetings), and pre-fills them into the calendar as **pending previews**
(dashed outline) awaiting one-tap confirmation. The selected direction is **B′ —
"暖纸 Bento + Discord 风助手"**: a warm-paper Bento month grid on the left and a
Discord-style chat panel on the right.

The calendar supports four switchable views: **月 (Month) / 周 (Week) / 日 (Day) /
议程 (Agenda)**.

## About the Design Files
The files in this bundle are **design references created in HTML/React (via inline
Babel JSX)** — prototypes that demonstrate the intended look, layout, and
view-switching behavior. They are **not production code to ship directly**.

The task is to **recreate these designs in the target codebase's existing
environment** (React, Vue, SwiftUI, native, etc.), using its established
component library, state patterns, and styling conventions. If no environment
exists yet, choose the most appropriate framework for the project and implement
there. Treat the JSX as a precise spec, not a drop-in.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, and the four
calendar views are all specified to the pixel. Recreate the UI faithfully using
the codebase's libraries. Note: the prototype's "‹ ›" prev/next paging and event
clicks are **non-functional stubs** (display only) — see Interactions for what
real behavior to build.

---

## Layout (whole screen)
- Root: a fixed **1440 × 940** frame, `display:flex`, background `#EFE9DC`.
- **Left — Calendar** (`.dD-cal`): `flex:1`, `padding:30px 32px`, column layout.
  - Header row (`.dD-top`): title + prev/next nav on the left, segmented view
    switcher (月/周/日/议程) on the right.
  - Body: swaps between Month grid / Week-Day time grid / Agenda list.
- **Right — AI panel** (`.dD-ai`): fixed `width:438px`, background `#F1ECE1`,
  `border-left:1px solid #E0D6C4`. Discord-style channel header, scrolling
  message feed, composer pinned at bottom.

---

## Views

### 1. Month (月) — default
- Weekday header row (Mon-first): `周一…周日`, mono caps, color `#A2937B`.
- 7×5 grid (`.dD-grid`), `gap:10px`. Each cell (`.dD-cell`): bg `#FBF8F1`,
  `border-radius:14px`, `padding:9px 9px 7px`, subtle shadow.
- Out-of-month cells: `.out`, bg at 45% opacity, day number `#C2B6A0`.
- **Today** cell: `box-shadow:0 0 0 2px #2A6FDB, 0 6px 16px rgba(42,111,219,.16)`,
  day number `#2A6FDB`.
- Event chips (`.dD-blk`): `border-radius:7px`, `padding:4px 8px`,
  `font-size:11.5px`, weight 600, single-line ellipsis. Leading time (`.tm`) in
  weight 700 at 70% opacity. Max 3 shown per cell, then `+N` more (`.dD-more`).
- **Pending** chips (`.pending`): transparent bg + `1.5px dashed` border in the
  type's ink color.

### 2. Week (周) — Jun 8–14
- Time grid. Columns: `56px` gutter + `repeat(7,1fr)` day columns.
- Day heads (`.wk-dh`): mono weekday caps + Newsreader day number (24px). Today's
  number is a filled `#2A6FDB` circle (36px) in white.
- All-day strip (`.dD-allday`): bordered top+bottom row holding `.ad-chip` chips.
- Body height = `(21−7)×50 = 700px`, hours **07:00–21:00**, `50px` per hour.
  - Hour gridlines: `1px solid #DAD0BC` across each column + 6px tick in gutter.
  - Hour labels (`.tg-hr`): mono 10.5px, `#9A8E7B`, right-aligned in gutter.
  - Timed events (`.tg-ev`): absolutely positioned, `top=(startHour−7)×50`,
    `height=max(durationHours×50, 38)`. `border-radius:8px`, soft bg + ink text;
    title (weight 700, 12.5px) over mono time range. Pending = dashed.
  - **Now line** (`.tg-now`): `2px solid #B14228` with a 9px dot at the left,
    rendered only in **today's** column at the current time.

### 3. Day (日) — Jun 10
- Identical time grid to Week, but a single day column (`56px 1fr`). Shows the
  now line and that day's timed events.

### 4. Agenda (议程)
- Scrolling list grouped by date, starting from today forward.
- Each group (`.ag-day`): `grid-template-columns:108px 1fr`, `gap:22px`,
  separated by `1px solid #E4DBC9` top borders.
  - Date label (`.ag-dl`): mono weekday caps, Newsreader `6/D` (30px), and a
    relative line (`今天 / 明天 / N 天后`) in `#B3A893`. Today's date is `#2A6FDB`.
  - Rows (`.ag-row`): bg `#FBF8F1`, `border-radius:11px`, `padding:11px 15px`.
    Layout: mono time (or `全天`) → 9px type dot → title (flex, ellipsis) → type
    chip (soft bg / ink text) → source text right-aligned `#A89A86`.
    Pending rows: transparent + dashed `#C9BCEC`.

---

## AI Panel (right)
- **Channel header** (`.dD-chh`, 56px): `#` glyph + channel name `日程助手` +
  divider + topic text + right-aligned bell/search/users icons (inline SVG).
- **Message feed** (`.dD-feed`): grouped messages, Discord style.
  - Date divider (`.dD-div`): centered mono pill between two hairlines.
  - Message row (`.dD-msg`): `grid-template-columns:40px 1fr`, `gap:14px`.
    - Avatar (`.dD-av`, 40px circle): bot = blue radial gradient with a white
      calendar glyph; user (`.me`) = green `#4F7A4A` circle with "我".
    - Header line: username (bot `#2A6FDB` / user `#4F7A4A`) + `应用` app tag +
      mono timestamp.
    - Body (`.dD-body`): 14.5px, line-height 1.5, `#393429`.
  - **User messages are right-aligned** (`.dD-msg.right`): avatar moves to the
    right column, content right-aligned, timestamp before the username.
  - **Summary embed** (`.dD-embed`): left accent bar, mono uppercase heading,
    rows of big Newsreader number + label + sub. Urgent numbers `#B14228`.
  - **Flight card** (`.dD-flight`): boarding-pass style. Purple banner ("邮件中发现
    航班" + 待确认 tag), PVG→HND route with mono airport codes (27px), flight no.
    pill, dashed flight path with plane SVG, perforation line, meta row (date /
    reminder / source). Distinct purple `#6A5BD0` AI accent.
  - **Action buttons** (`.dD-btns`): primary `✓ 确认加入日历` (`#2A6FDB`) + secondary
    `忽略`.
- **Composer** (`.dD-comp`): rounded box, `+` button, placeholder `给 #日程助手
  发消息…`, emoji/enter tools.

---

## Interactions & Behavior
- **View switcher** (working in prototype): clicking 月/周/日/议程 swaps the calendar
  body and updates the header title. Active button: bg `#2A6FDB`, white text,
  `box-shadow:0 2px 6px rgba(42,111,219,.25)`.
- **Prev/next "‹ ›"** (stub): build real paging — Month steps by month, Week by
  week, Day by day, Agenda scrolls/loads further out.
- **Event chips** (stub): should open an event detail / edit popover on click.
- **AI confirm/ignore** (stub): "确认加入日历" should convert a pending (dashed) event
  into a confirmed one (solid); "忽略" dismisses it.
- **Now line**: position from current time; only render within the visible
  today column and only if today is in range.

## State Management
- `view`: one of `'month' | 'week' | 'day' | 'agenda'` (currently `useState`,
  default `'month'`).
- `currentDate` / visible range (to make prev/next real).
- `events[]`: fetched from calendar + AI-extraction backends. Each event needs
  `status: 'confirmed' | 'pending'` to drive the dashed-preview styling.
- AI chat transcript + pending-suggestion queue.

## Design Tokens

### Colors
| Token | Hex | Use |
|---|---|---|
| Paper base | `#EFE9DC` | app background |
| Card / surface | `#FBF8F1` | cells, events, rows |
| AI panel bg | `#F1ECE1` | right panel |
| Ink primary | `#2B2622` | headings/body |
| Ink body | `#393429` | message body |
| Muted | `#A2937B` / `#9A8E7B` / `#B3A893` | labels, captions |
| Borders | `#E0D6C4` / `#E4DBC9` | panel + hairlines |
| Gridline | `#DAD0BC` | hour lines (week/day) |
| **Accent (blue)** | `#2A6FDB` | today, active tab, meetings, primary btn |
| Meeting soft | `#E1ECFB` | meeting chip bg |
| Deadline ink / soft | `#B14228` / `#F6E4DC` | deadlines, now line, urgent |
| Personal ink / soft | `#4F7A4A` / `#E4EFE2` | personal events, user avatar |
| AI ink / soft | `#6A5BD0` / `#EAE6FA` | AI suggestions, flight card |

Event types live in `data.js → typeMeta`: `deadline / meeting / personal / ai`,
each `{ label, ink, soft }`.

### Typography
- **Newsreader** (serif): large titles, day numbers, embed big-numbers.
- **IBM Plex Sans**: UI body, event titles, buttons.
- **IBM Plex Mono**: timestamps, weekday caps, hour labels, airport codes,
  numeric/label microcopy.

### Spacing / radius
- Grid gap `10px`; cell radius `14px`; chip radius `7px`; event radius `8px`;
  row radius `11px`; segmented control radius `13px`/`9px`.
- Time grid: `50px` per hour, `56px` gutter, range 07:00–21:00.

## Assets
- All icons are **inline SVG** (see `svgIcon()` at the bottom of
  `directionBD.jsx`): bell, search, users, plane, mail, plus the bot avatar
  calendar glyph (pure CSS). No external image assets.
- Fonts loaded from Google Fonts (Newsreader, IBM Plex Sans, IBM Plex Mono).

## Files
- `日历AI助手 - 方向探索.html` — entry point; loads React + data + direction files
  into a pan/zoom design canvas.
- `directionBD.jsx` — **the selected B′ design** (calendar with all four views +
  AI panel). This is the primary file to implement.
- `data.js` — shared mock data: `events`, `typeMeta`, `chat` transcript,
  `WEEKDAYS`, `TODAY` (= 10, i.e. Wed Jun 10 2026), `DAYS_IN_MONTH`.
- `design-canvas.jsx` — the pan/zoom presentation shell (presentation only; **not
  part of the product** — ignore when implementing).
- `directionA.jsx` / `directionB.jsx` / `directionC.jsx` — earlier exploratory
  directions, included for reference only.
