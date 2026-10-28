// electron-builder configuration.
//
// Signing: if a Developer ID certificate is provided (CSC_LINK / CSC_NAME)
// electron-builder signs with it, and notarizes when APPLE_ID,
// APPLE_APP_SPECIFIC_PASSWORD and APPLE_TEAM_ID are also set. Otherwise the app
// is ad-hoc signed ("-"): a valid (if untrusted) signature, which Apple Silicon
// requires for the bundle to launch at all.
// CI passes unset secrets as empty strings; treat those as absent.
for (const key of [
  "CSC_LINK",
  "CSC_NAME",
  "CSC_KEY_PASSWORD",
  "APPLE_ID",
  "APPLE_APP_SPECIFIC_PASSWORD",
  "APPLE_TEAM_ID",
]) {
  if (process.env[key] === "") delete process.env[key];
}

const signed = Boolean(process.env.CSC_LINK || process.env.CSC_NAME);
const notarize = signed && Boolean(
  process.env.APPLE_ID &&
    process.env.APPLE_APP_SPECIFIC_PASSWORD &&
    process.env.APPLE_TEAM_ID,
);

module.exports = {
  appId: "dev.loopprism.desktop",
  productName: "LoopPrism",
  copyright: "Copyright © Mark Zhang",
  directories: { output: "release", buildResources: "build" },
  files: ["src/**/*", "assets/**/*", "package.json"],
  // The PyInstaller one-dir bundle (built by `npm run sidecar`); the app
  // spawns Resources/sidecar/lprism/lprism.
  extraResources: [{ from: "sidecar/dist/lprism", to: "sidecar/lprism" }],
  artifactName: "LoopPrism-${version}-${arch}.${ext}",
  mac: {
    category: "public.app-category.developer-tools",
    icon: "build/icon.png",
    // Builds for the host architecture; the sidecar is frozen per-arch, so
    // arm64 and x64 are built on matching runners (see release-desktop.yml).
    target: ["dmg", "zip"],
    identity: signed ? undefined : "-",
    hardenedRuntime: signed,
    entitlements: "build/entitlements.mac.plist",
    entitlementsInherit: "build/entitlements.mac.plist",
    gatekeeperAssess: false,
    notarize,
  },
};
