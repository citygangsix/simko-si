# Themes

Simco SI paints chat, the sea-turtle screen, and the phone app from this folder. The default theme is **Reef Live**. A person can switch it, or choose **No theme / Plain**, from Tools.

## Add a theme

1. Create `themes/<id>/`.
2. Put `theme.css` in that folder. Scope every rule with `html[data-theme="<id>"]` so it does not leak into other themes.
3. Optional: `theme.js` that sets `window.simcoThemeLayer = { mount, unmount }` and draws art into `#themeStage`. The host removes that node when another theme is chosen.
4. Optional: `icon.png` and `splash.png` for a store-art variant. The shipped phone icon and splash stay the reef artwork until a release replaces them.
5. Add one object to the `themes` array in `themes/manifest.json`:

```json
{
  "id": "tidepool",
  "name": "Tide Pool",
  "animation": false,
  "stylesheet": "theme.css",
  "preview": "linear-gradient(155deg, #9ad7c8, #1d4e89)"
}
```

`id` matches the folder name. `preview` is the small swatch in the picker. Set `animation` to `true` only when the theme runs a motion layer. No other registry edit is required.

## What ships

| id | Name | Motion |
| --- | --- | --- |
| `reef-live` | Reef Live | Rays, caustics, bubbles, kelp, fish, turtle, clam, and starfish. Pauses when the tab is hidden, after 20 seconds idle, when reduced motion is requested, and when the battery is under 20% and not charging. |
| `reef-still` | Reef Still | The static reef photograph and the glass panels, with no creature layer. |
| `plain` | No theme / Plain | No photograph, no creature layer, no decorative animation. |

## Backgrounds

The shipped plates are the native masters: cleaned landscape 1280×720 and portrait 720×1280, plus a smaller 640-long-side mobile file. Each size is AVIF quality 60, WebP quality 80, and JPEG quality 82. Nothing is stretched to 3840.

The Real-ESRGAN x4plus step (1920 / 2560 / 3840) is deferred. `build_reef_backgrounds.py` keeps that step behind `--upscale` and does not run it unless that flag is passed.

## Reef loops (Reef Live)

Reef Live plays a real, seamless reef loop over the still plate when the WebView can play H.264:

| Layout | File | Size |
| --- | --- | --- |
| Wide: unfolded Fold, tablet, desktop (`width > 640px`) | `reef-live/video/reef-wide-720p.mp4` (1280×720, 10 s, 24 fps) | ~1.9 MB |
| Tall: folded cover screen, narrow phones (`max-width: 640px`) | `reef-live/video/reef-tall-720p.mp4` (720×1280, 10 s, 24 fps) | ~1.8 MB |

Both are muted, inline, looped, H.264 Main with faststart, re-encoded (CRF 31) from `/workspace/reef-video/reef-live-{landscape,portrait}-loop.mp4`. The source swaps live when the phone folds or unfolds. The video pauses whenever motion is off (hidden, 20 s idle, reduced motion, low battery, Plain). While a loop plays, the cartoon vector layer and canvas rays are hidden; if the video cannot play, the still plate and vector layer are used as before. No video was generated for this; these are the existing loops.

## Where the choice is kept

The browser stores `simcoTheme` in local storage and applies it before paint on `chat.html`, `/turtle`, and the Capacitor bundle. When someone is signed in, the same id is saved with `POST /api/settings` and restored on the next sign-in.
