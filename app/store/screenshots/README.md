# Screenshots

These were captured headless with `python3 store/tools/capture_screenshots.py`. The script uses Playwright Chromium against the bundled UI served by the dry-run local server (`PODCODER_DRY_RUN=1`), with the Reef Live theme. No real computer, model, or network is involved.

| Folder | CSS viewport | Scale | Pixels | Store use |
| --- | --- | --- | --- | --- |
| `phone-6.7in-1290x2796/` | 430×932 | 3 | 1290×2796 | App Store, 6.7-inch iPhone (required size) |
| `android-phone-1082x2402/` | 412×915 | 2.625 | 1082×2402 | Google Play phone screenshots |
| `zfold-cover-412x960/` | 412×960 | 2.625 | 1082×2520 | Z Fold cover screen (reference only) |
| `zfold-inner-750x832/` | 750×832 | 2.4 | 1800×1997 | Z Fold inner screen. Play 7-inch or 10-inch tablet slot, or a foldable showcase |
| `ipad-13in-2064x2752/` | 1032×1376 | 2 | 2064×2752 | App Store 13-inch iPad (required because the iOS target includes iPad) |

Shots in each folder:

1. `01-turtle-setup.png`: sea turtle screen asking for the computer address
2. `02-setup-detected.png`: setup after hardware detection (Granite, Ollama, and Aider chosen)
3. `03-messenger.png`: messenger chat list
4. `04-thread.png`: an open thread

## Caveats before uploading

- **Z Fold cover aspect ratio.** 1082×2520 is about 2.33:1. Play rejects screenshots whose long side is more than twice the short side. Use the cover shots for review or marketing only, or crop them to 1082×2164 before uploading.
- **Setup log contents.** `02-setup-detected.png` shows the hardware of the build box (Intel Xeon, 15.6 GB, no GPU), because the dry-run server detects the machine it runs on. For the final listing, re-run the script on the Aspire or the target computer, so the shot shows a real GPU and the Granite model chosen for it.
- **iPad.** The iOS project has `TARGETED_DEVICE_FAMILY = "1,2"` (iPhone and iPad), so App Store Connect requires 13-inch iPad shots. They are included. To ship iPhone-only instead, set the family to `1` in Xcode and skip the iPad folder.

Re-run from the repo root:

```
python3 store/tools/capture_screenshots.py            # all sizes
python3 store/tools/capture_screenshots.py ipad fold-cover   # only some (phone, android, fold-cover, fold-inner, ipad)
```
