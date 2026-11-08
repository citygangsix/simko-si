# Frontier Chatbot UI Handoff

## 1. High-Level Product / Page Purpose

This page is the meditation site's in-app chatbot workspace. In the live site, it is mounted as the `Chatbot` tab inside the main website shell rather than being a separate standalone app.

Its job is to give the site a premium AI-workspace feel instead of a simple help widget. The intended experience is closer to a branded assistant dashboard: users should feel like they are entering a focused mentor/chat environment with themes, workspace tabs, Explore entry points, and future room for real AI workflows.

From a product perspective, it currently plays three roles:

- It replaces the older `AI Coach` screen.
- It acts as a branded "Frontier" chatbot shell inside the meditation site.
- It provides a staging area for future chat, explore, project, and mentor flows.

The UX target is "premium, immersive, customizable, and assistant-first" rather than "simple utility chat box."

## 2. Current Layout Structure

### Overall page shell

The chatbot page sits inside the existing meditation-site layout. The top site navigation remains visible, and when the `Chatbot` tab is active the chatbot component pushes its own theme upward into the outer app shell.

Main layout hierarchy:

1. Website top navigation (`Navigation.tsx`)
2. Large chatbot canvas card with rounded corners
3. Left sidebar
4. Inner chatbot top bar
5. Main content area with heading, tabs, and content panels

### Sidebar

The sidebar is the left rail inside the chatbot card.

Expanded state:

- width: `300px`
- shows the MentorsAI image logo at top-left
- shows actions:
  - `New chat`
  - `Search chats`
  - `Library`
- shows the `GPTmentors` label block
- shows an `Explore` button
- shows a highlighted workspace card for `digital_AEnnergy`
- shows the Explore submenu list
- shows `Your Chats`
- shows a workspace info card
- shows the profile card (`Jo Sim`, `Plus`)

Collapsed state:

- width: `92px`
- shows expand button
- shows compact hover-logo image
- shows icon-only actions
- shows bottom avatar only

### Top navigation

There are two nav layers:

Outer site nav:

- handled by `src/components/Navigation.tsx`
- contains the site logo and tabs:
  - `Home`
  - `Meditation`
  - `Meet the Masters`
  - `Shop`
  - `Chatbot`
- while the chatbot tab is active, this nav receives a chrome theme object from the chatbot page

Inner chatbot top bar:

- left side has the model/mode launcher:
  - `MentorsAi`
  - version `5.1`
- right side has utility buttons:
  - group chat icon
  - temporary chat icon
  - current mode pill
  - theme button that opens the color wheel/theme panel

### Hero / logo area

There is no separate hero block in the current live chatbot page. The closest equivalent is:

- the MentorsAI image logo at the top of the sidebar
- the centered workspace heading area in the main panel

Important note: the requested "Frontier multicolor wordmark above heading" is **not currently implemented** in the live component.

### Heading

The main heading is centered in the content area:

- `What can I help with?`

It sits above the tabbed workspace content and currently serves as the page's primary headline.

### Search / input area

The actual chat-style composer currently appears only in the `Frontier` tab.

It contains:

- left icon button: `MessageSquarePlus`
- centered text input with placeholder `Ask anything`
- right-side icon buttons:
  - `Mic`
  - `AudioLines`

The search/composer shell theme currently changes based on `theme`:

- `light` uses white shell
- dark/colorful use a darker shell (`bg-[#3e3e3e]`)

### Spacing and visual hierarchy

The visual hierarchy is:

1. Outer site nav
2. Large rounded chatbot card
3. Sidebar vs main workspace split
4. Chatbot top bar
5. Centered heading
6. Workspace tabs (`Frontier`, `Explore`, `Projects`, `Recents`)
7. Content panels within the selected workspace

Spacing is intentionally generous:

- outer page padding: `px-4 py-6 md:px-6 lg:px-8`
- chatbot card uses large rounding: `rounded-[32px]`
- main content uses centered max widths:
  - `max-w-5xl` outer
  - `max-w-3xl` on composer area
  - `max-w-2xl` for tab list

## 3. Component Structure

## Major files

### `/Users/xxx/Downloads/meditate-shop-coach (3)/src/components/MentorChatbotPage.tsx`

This is the main Frontier chatbot UI component. It contains nearly all of the live chatbot UI and behavior.

Responsibilities:

- renders sidebar
- renders inner chatbot top bar
- renders workspace tabs
- renders the search/composer area
- renders Explore / Projects / Recents panels
- manages theme state
- samples colors from the color wheel image
- computes a chrome theme object for the host app shell

### `/Users/xxx/Downloads/meditate-shop-coach (3)/src/components/AppLayout.tsx`

This file mounts the chatbot page into the meditation site.

Responsibilities:

- owns the active site tab
- renders `MentorChatbotPage` when `activeTab === 'chatbot'`
- stores `chatbotChromeTheme`
- applies chatbot theme colors to the outer page background
- passes the chatbot theme into `Navigation`

### `/Users/xxx/Downloads/meditate-shop-coach (3)/src/components/Navigation.tsx`

This is the meditation site's top nav.

Responsibilities:

- renders site-level tab buttons
- adapts nav colors when chatbot theme is active
- keeps the chatbot integrated into the rest of the site shell

## Main functions / structures inside `MentorChatbotPage.tsx`

### `mixWithWhite(rgbString, amount)`

Utility to tint an RGB color toward white.

Used for:

- brightening active custom colors
- generating lighter page and nav surfaces

### `mixWithBlack(rgbString, amount)`

Utility to darken an RGB color toward black.

Used for:

- darkening sidebar backgrounds based on custom wheel colors

### `MentorChatbotPage`

The main React component.

It owns all current UI state for the chatbot shell.

## State organization

### Theme / color state

- `theme: 'dark' | 'light' | 'colorful'`
- `hoverColor: string | null`
- `lockedColor: string | null`
- `colorLocked: boolean`
- `colorWheelOpen: boolean`
- `imageLoaded: boolean`

These drive:

- nav background
- sidebar background
- main gradient background
- outer app shell theme propagation

### Workspace/content state

- `selectedMode: 'auto' | 'instant' | 'thinking'`
- `workspaceTab: 'frontier' | 'explore' | 'projects' | 'recents'`
- `selectedExploreCategory`
- `query`

### UI shell state

- `sidebarExpanded`
- `modelMenuOpen`
- `groupChatTooltipOpen`
- `temporaryChatTooltipOpen`

### Refs

- `colorWheelRef`
- `modelMenuRef`
- `canvasRef`
- `imageRef`

These support:

- click-outside closing behavior
- color sampling from the color wheel image

## 4. Approved UI Behavior

This section distinguishes between the approved/finalized rules and what the current live component is actually doing.

### Sidebar expanded vs collapsed

Current live behavior:

- expanded shows full labels, Explore submenu, recent chats, workspace card, and profile card
- collapsed shows icon-only controls and a compact logo
- expand/collapse is controlled by:
  - `PanelLeftClose`
  - `PanelLeftOpen`

This behavior is live and implemented.

### Explore behavior

Current live behavior:

- there is an `Explore` button in the sidebar
- clicking `Explore` switches `workspaceTab` to `explore`
- the selected Explore category is shown in both:
  - sidebar submenu list
  - main Explore tab chip row
- selecting a category updates the main Explore panel content

### Exact Explore submenu items

The current live component includes these exact items:

- `Multi-Mentor`
- `Match AI`
- `MECCA: socialmedia-dashboard`
- `CoinBank`
- `Shop`
- `Earn Money $`
- `Philanthropy`

Internal label/display split:

- chip row labels in main content use:
  - `Multi-Mentor`
  - `Match AI`
  - `MECCA`
  - `Coin Bank`
  - `Shop`
  - `Earn Money`
  - `Philanthropy`
- sidebar submenu uses the exact menu labels above, including:
  - `MECCA: socialmedia-dashboard`
  - `CoinBank`
  - `Earn Money $`

### Top-left icon should not spin

Approved rule:

- top-left icon should not spin

Current live status:

- no spin animation is applied in the current component
- the top-left asset is a static image

So this rule is satisfied by omission.

### Frontier multicolor wordmark above heading

Approved rule:

- a Frontier multicolor wordmark should appear above the heading

Current live status:

- **not implemented**
- the live page currently jumps straight to the centered heading `What can I help with?`

### Search bar should match surrounding theme/background

Current live behavior:

- implemented partially
- search shell adapts by theme:
  - `light` -> white shell
  - non-light -> darker shell
- input text colors also adapt by theme

Gap:

- the search bar is not yet using a richer colorful-mode-specific shell treatment beyond the shared dark shell

## 5. Theme System Behavior

## Current live theme behavior

### Light theme

Current live behavior:

- `theme === 'light'`
- nav defaults to white
- sidebar becomes light gray
- main background becomes a light gray gradient
- text switches to dark text classes
- prompt chips become white with gray text
- search shell becomes white

### Dark theme

Current live behavior:

- `theme === 'dark'`
- nav defaults to very dark
- sidebar becomes dark
- main background becomes a dark gray gradient
- text becomes white / muted gray
- prompt chips use translucent dark styling
- search shell uses `bg-[#3e3e3e]`

### Colorful / rainbow mode

Current live behavior:

- `theme === 'colorful'`
- default colorful state uses a purple-to-deep-dark gradient
- nav becomes purple-toned
- app shell becomes purple/dark
- if an active wheel color exists, that color overrides major surfaces

## Important approved-rule gaps

Approved/finalized behavior requested:

- custom color only works in colorful mode
- color wheel hover/click is disabled unless colorful mode is selected
- `Reset Color` appears only in colorful mode when a color is locked
- Light button resets to default light theme
- Dark button resets to default dark theme

Current live implementation:

- custom wheel color currently affects the UI in **all theme modes**
- hover and click sampling on the color wheel are **not gated** by `theme === 'colorful'`
- `Reset Color` currently appears whenever `colorLocked` is true, regardless of theme
- the Light and Dark buttons currently only call:
  - `setTheme('light')`
  - `setTheme('dark')`
- those buttons do **not** currently clear `lockedColor` or `colorLocked`

In short: the approved theme rules are **not fully enforced yet** in the current live component.

## 6. Persistence / State Behavior

### What is currently stored in localStorage

Current live status:

- nothing

There is currently **no localStorage persistence** in the live `MentorChatbotPage.tsx`.

### What is temporary state only

All current UI state is temporary React state only, including:

- theme
- hover color
- locked color
- color lock flag
- selected mode
- selected workspace tab
- selected Explore category
- sidebar expanded/collapsed state
- query text
- menu / popover visibility

### How theme/color state is restored

Current live status:

- theme/color state is **not restored**
- refreshing the page resets the component to its defaults

Important historical note:

- an older source version in another folder previously used localStorage keys for theme/color/sidebar persistence
- that persistence logic has not been ported into the live component in this repo

## 7. Styling / System Notes

### Tailwind usage

The page is built primarily with Tailwind utility classes.

Examples:

- layout
- spacing
- rounding
- borders
- backdrop blur
- text colors
- hover states
- tabs styling

### Inline styles

Inline styles are used where colors are dynamic at runtime.

Examples:

- inner nav background color
- sidebar background color
- main gradient background
- outer app background from `chatbotChromeTheme`
- top site nav colors from the chatbot

### Icons used

Icons come from `lucide-react`, including:

- `AudioLines`
- `Check`
- `ChevronDown`
- `ChevronRight`
- `Compass`
- `FolderKanban`
- `Library`
- `MessageSquarePlus`
- `Mic`
- `MoonStar`
- `PanelLeftClose`
- `PanelLeftOpen`
- `Search`
- `Sparkles`
- `SunMedium`
- `Users`

### Hardcoded assets / images

Current live component depends on hardcoded external image URLs:

- sidebar logo:
  - `https://d64gsuwffb70l.cloudfront.net/687e9ed9ad2a7bae91f4fe1d_1764718804303_7ba02100.png`
- collapsed/hover logo:
  - `https://d64gsuwffb70l.cloudfront.net/687e9ed9ad2a7bae91f4fe1d_1764716303936_2e116c49.png`
- rainbow spiral icon:
  - `https://d64gsuwffb70l.cloudfront.net/687e9ed9ad2a7bae91f4fe1d_1764719402041_34b80ad9.png`
- colorful theme preview button:
  - `https://d64gsuwffb70l.cloudfront.net/687e9ed9ad2a7bae91f4fe1d_1764724971618_2147c89b.png`
- color wheel:
  - `https://d64gsuwffb70l.cloudfront.net/687e9ed9ad2a7bae91f4fe1d_1768751077510_cb2f8c89.png`
- site header logo in `Navigation.tsx`:
  - `https://d64gsuwffb70l.cloudfront.net/688c1582401ba33c8d548d7c_1758680182006_76c19f45.webp`

### Host app assumptions

The chatbot assumes:

- it is mounted inside the meditation site's tab system
- it can push theme colors up into the outer site shell through `onChromeThemeChange`
- the project uses React + TypeScript + Tailwind
- local path alias `@/` is configured
- `Tabs`, `TabsList`, `TabsTrigger`, and `TabsContent` are available from the local UI system

## 8. Known Limitations / Not Yet Implemented

### UI shell only

This page is still mostly a UI shell. It is not yet a fully working chatbot product.

### Not connected to a real backend / assistant system

Currently not implemented:

- no real message send flow
- no assistant responses
- no streaming
- no conversation persistence
- no API integration
- no auth-aware user data

### Explore is static content

The Explore section is currently static demo content:

- category descriptions are hardcoded
- cards are hardcoded
- no routing into real category experiences

### Projects and Recents are static

- Projects uses hardcoded sample cards
- Recents uses hardcoded chat names
- no persistence or data source

### Theme system still needs enforcement work

Not fully implemented relative to approved rules:

- custom color should only apply in colorful mode
- color wheel hover/click should be disabled outside colorful mode
- `Reset Color` should appear only in colorful mode with a locked color
- switching to light/dark should reset theme to default light/dark

### Missing approved visual element

Still missing:

- Frontier multicolor wordmark above heading

### Production hardening gaps

Still needed:

- persistence
- backend integration
- accessibility pass
- keyboard interaction audit
- responsive polish audit
- error handling for remote assets
- asset localization instead of relying on external image URLs

## 9. Resume Instructions

### Files that matter most

Primary files for continuing work:

- `/Users/xxx/Downloads/meditate-shop-coach (3)/src/components/MentorChatbotPage.tsx`
- `/Users/xxx/Downloads/meditate-shop-coach (3)/src/components/AppLayout.tsx`
- `/Users/xxx/Downloads/meditate-shop-coach (3)/src/components/Navigation.tsx`

If theme persistence is restored from earlier experiments, the old reference implementations outside this live repo may also be useful, but the live work should stay centered on the three files above.

## Resume From Here

1. Enforce the finalized theme rules in `MentorChatbotPage.tsx`.
   Make the color wheel inert unless `theme === 'colorful'`, clear locked colors when switching to `light` or `dark`, and only render `Reset Color` when colorful mode is active and a color is locked.

2. Add the missing Frontier multicolor wordmark above the `What can I help with?` heading.
   Keep it visually aligned with the current centered layout rather than redesigning the page.

3. Restore persistence for the user-facing shell state.
   Save and restore at minimum:
   - selected theme
   - locked custom color
   - sidebar expanded/collapsed state
   - optionally selected workspace tab

4. Turn the composer into a real chat entry point.
   Add submit behavior, message list rendering, loading states, error handling, and a backing API integration for assistant responses.

5. Convert Explore / Projects / Recents from static placeholders into real product surfaces.
   Start by deciding which of these should become route-backed views, which should stay in-tab panels, and what data model will feed them.
