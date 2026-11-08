# Simko SI desktop release and signing — NOT executed

The authoritative shared feature source is `podcoder-translator-renter/`. Stage it
into the existing wrapper with `python3 tools/sync_desktop_wrapper.py /workspace/simko-si-tauri`.
The wrapper has additional setup/Granite fixes: the staging script preserves them,
replaces only shared modules whose historical hashes match, and merges the API hooks.
Config snapshots are under `desktop-wrapper/`. No credentials belong in this repo.
Existing installers remain OLD: staging Python source does not update an installer.

## Host targets

- Windows: `npm run build:windows` on Windows; native PyInstaller sidecar
  `src-tauri/binaries/simko-backend-x86_64-pc-windows-msvc.exe`.
- Linux: `npm run build:linux`; native sidecar
  `src-tauri/binaries/simko-backend-x86_64-unknown-linux-gnu`.
- Mac: `npm run build:mac:universal` on a Mac. The target is
  `universal-apple-darwin` (a CLI target, NOT a Tauri bundle config property).
  The selected config bundles `.app` and `.dmg`. Never run Mac builds on Linux.
- Base config lists available formats; use the platform scripts to avoid requesting
  incompatible bundle formats on a host. No signing identity/thumbprint is set.

## macOS checklist (requires Joseph's rental/purchase OK)

1. Approve a Mac rental and a budget/provider first. No rental has been provisioned.
2. Joseph enrolls in Apple Developer Program: **US $99/year**, regional taxes/currency
   may vary; organization enrollment may require D-U-N-S and legal authority.
3. On a Mac install Xcode command-line tools, Rust, Node and **universal2 Python**.
   Install Python dependencies from `backend/requirements-desktop.txt` and PyInstaller.
   Never copy credentials to source or command history. Optional Playwright must be
   installed separately; it is deliberately excluded from the frozen sidecar today.
4. Stage source locally; run all Python tests. Install Rust targets with
   `rustup target add aarch64-apple-darwin x86_64-apple-darwin`.
5. Build sidecar on the Mac from `backend/`: set `SIMKO_UNIVERSAL2=1` in the process
   environment; run `python3 -m PyInstaller simko-backend.spec --clean --noconfirm`.
   Every compiled Python extension must be universal2; a single-arch dependency is
   a build blocker, not a reason to label a binary universal. Inspect with `lipo -info`.
   Copy output to `src-tauri/binaries/simko-backend-universal-apple-darwin`.
6. Obtain Developer ID Application certificate in the Mac's login keychain.
   Set `APPLE_SIGNING_IDENTITY` and notarization credentials using the build
   environment/credential manager only (Apple API key or supported Apple ID flow).
   Sign nested PyInstaller executables/libraries with hardened runtime. Add only
   audited entitlements needed by Python, audio, loopback networking and subprocesses.
   Do NOT blindly disable library validation or enable a broad App Sandbox entitlement.
7. Run `npm run build:mac:universal`. Follow Tauri's current notarization flow.
   Apple notarization is included in membership (no separate per-submission fee).
   Verify `codesign --verify --deep --strict --verbose=2 "Simko SI.app"`, notarization
   status with `xcrun notarytool`, `xcrun stapler validate`, and Gatekeeper with
   `spctl --assess --type execute --verbose "Simko SI.app"`. Staple app/DMG tickets.
8. Test Intel AND Apple Silicon: first launch, spaces/non-ASCII paths, native keychain
   fallback, SMTP TLS, OAuth system-browser callback, mic permissions, notifications,
   app close/child cleanup, exports, quota gates, and no Granite/Wan co-residency.
9. DMG signing/notarization is NOT Mac App Store publication. Mac App Store sandbox,
   review, privacy manifest, external checkout policy, subprocess and browser
   automation compatibility need separate design/review. No store submission approved.

## Windows checklist

1. Joseph's Acer test remains required. Test existing installer before new releases;
   do not overwrite/relabel existing release artifacts as updated or signed.
2. Choose a current trusted code-signing certificate or approved managed signing
   service. **Cost varies by vendor, validation, hardware and duration**; obtain an
   exact quote and Joseph's approval before buying or creating paid resources.
   Modern OV/EV certificates may require hardware-backed keys; a raw PFX is not
   always available. TLS certificates are not code-signing certificates.
3. Install Windows SDK, Rust MSVC toolchain, Node, Python and dependencies. Build the
   native sidecar with PyInstaller, then sign it, app executable and installer.
4. Fill `bundle.windows.certificateThumbprint`, `digestAlgorithm=sha256`, and the
   certificate issuer's timestamp URL, or configure an audited custom sign command.
   These are deliberately null placeholders today. Never commit certificate keys.
5. Build with `npm run build:windows`; verify using `signtool verify /pa /all /v`.
   Test install/uninstall/update with a normal user, Defender, SmartScreen and Windows
   11 Smart App Control. Signing does not guarantee immediate SmartScreen reputation.
6. Microsoft Store: Joseph registers/verifies legal publisher identity in Partner
   Center and authorizes any submission. Current new-flow registration is **free**
   for individuals and companies (company fee removed May 7, 2026); confirm current
   regional terms before proceeding. Signing, packaging/review and store acceptance
   are separate. Win32 installer submission is not the same as an MSIX submission.

## Documentation checked November 7, 2026

- https://v2.tauri.app/distribute/macos-application-bundle/
- https://v2.tauri.app/distribute/sign/windows/
- https://developer.apple.com/programs/
- https://learn.microsoft.com/en-us/windows/apps/publish/whats-new-company-developer
- https://blogs.windows.com/windowsdeveloper/2026/05/07/publish-to-microsoft-store-as-a-company-now-with-free-registration-and-faster-onboarding/

No signing, notarization, store signup/submission, paid trial or Mac build was run.

## Free preparation audit (resumed local build)

Run `python3 tools/release_preflight.py` for committed configuration snapshots, or
`python3 tools/release_preflight.py --wrapper /workspace/simko-si-tauri` after staging.
This read-only check verifies platform-specific targets, universal Mac script,
empty signing placeholders and disabled feature flags. It never runs a build,
signing tool, certificate request, registration, notarization or upload.

Release evidence checklist (NOT performed by this task):
- [ ] Joseph's UI sign-off and Acer acceptance recorded.
- [ ] Exact Apple enrollment/Windows certificate costs approved separately.
- [ ] Native sidecar and wrapper versions match source; hash artifacts per platform.
- [ ] Intel + Apple Silicon and native Windows acceptance completed.
- [ ] Browser remains disabled in packaged releases until sandbox/approval audit.
- [ ] Mock checkout never grants production entitlements; production payment and
      remote ACL authority separately reviewed, configured and approved.
- [ ] Signing/notarization verification evidence retained without private keys.
- [ ] Joseph explicitly authorizes each publication/submission destination.

An `ok` preflight means **unsigned preparation only**, never release acceptance.
