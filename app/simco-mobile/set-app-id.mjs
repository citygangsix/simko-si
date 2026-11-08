#!/usr/bin/env node
/* Change the store id in one place, then run: node set-app-id.mjs com.example.simcosi */
import fs from "node:fs";
import path from "node:path";

const root = path.dirname(new URL(import.meta.url).pathname);
const nextId = process.argv[2] || "";
if (!/^[a-zA-Z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*)+$/.test(nextId)) {
  console.error("Usage: node set-app-id.mjs com.example.simcosi");
  process.exit(2);
}
const configPath = path.join(root, "app.config.json");
const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
const previous = config.appId;
config.appId = nextId;
fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n");

function replaceFile(rel, from, to) {
  const file = path.join(root, rel);
  if (!fs.existsSync(file)) return;
  const text = fs.readFileSync(file, "utf8");
  if (!text.includes(from)) return;
  fs.writeFileSync(file, text.split(from).join(to));
}

replaceFile("capacitor.config.json", previous, nextId);
replaceFile("android/app/build.gradle", `applicationId "${previous}"`, `applicationId "${nextId}"`);
replaceFile("android/app/build.gradle", `namespace "${previous}"`, `namespace "${nextId}"`);
const ios = path.join(root, "ios");
if (fs.existsSync(ios)) {
  for (const dirent of fs.readdirSync(ios, { recursive: true })) {
    const rel = String(dirent);
    if (!rel.endsWith(".pbxproj") && !rel.endsWith("Info.plist")) continue;
    replaceFile(path.join("ios", rel), previous, nextId);
  }
}
console.log(`App id is ${nextId}. Run npx cap sync if the native projects already exist.`);
