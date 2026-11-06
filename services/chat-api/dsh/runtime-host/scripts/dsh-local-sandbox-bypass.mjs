// Local-sandbox bypass for dev hosts that have no usable sandbox backend
// (macOS without a working sandbox-exec, Linux without bubblewrap/Landlock,
// Windows without the ACL restricted-token runner).
//
// This is a DEV-ONLY helper. It simulates danger-full-access locally by
// skipping the sandbox runner wrap so the official DSH e2e tests can run
// unconfined. It does NOT change any product or test source — it only patches
// the LocalSandboxProvider prototype inside the test process.
//
// WARNING: this replaces EVERY sandbox confine() with a fully unconfined argv.
// On a host that DOES have a usable sandbox backend, using this bypasses real
// confinement — do NOT run it where sandboxing is a security requirement. It
// is meant for dev machines lacking a backend (e.g. macOS without a working
// sandbox-exec) where the runner would otherwise fail-closed and refuse to run
// any command at all.
//
// Usage:
//   npm run test:local
// which runs: node --import ./scripts/dsh-local-sandbox-bypass.mjs --test tests/*.test.mjs
import { readdirSync, existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";

// Locate the package root. npm run executes with cwd at the package root, so
// process.cwd()/node_modules/.pnpm exists immediately; the upward walk also
// supports invocation from a subdirectory. We guard with existsSync because
// intermediate ancestors have no node_modules and readdirSync would throw.
let root = process.cwd();
while (root !== dirname(root)) {
  if (existsSync(join(root, "node_modules", ".pnpm"))) break;
  root = dirname(root);
}
const pnpmDir = join(root, "node_modules", ".pnpm");

// Resolve the active DSH release train from the INSTALLED @deepseek-ai/dsh
// package rather than hard-coding a version.  A pinned version silently breaks
// `npm run test:local` on every release-train upgrade (this was pinned to
// 0.2.1-rc.3 while the 0.2.1-rc.5 train shipped 0.2.1-rc.5, and then broke
// again on 0.2.2-rc.1).  Deriving it keeps the helper working across upgrades
// and rollbacks without editing this file.
const activeTrain = (() => {
  try {
    return JSON.parse(
      readFileSync(join(root, "node_modules", "@deepseek-ai", "dsh", "package.json"), "utf8")
    ).version;
  } catch {
    return null;
  }
})();

const prefix = "@deepseek-ai+dsh-sandbox-local@";
const exactPrefix = activeTrain ? `${prefix}${activeTrain}` : null;
const versionOf = (dir) => dir.slice(prefix.length).split(/[_(@]/)[0];

// Prefer the directory matching the active train; fall back to any other
// installed copy (e.g. a rollback train) so the helper never hard-fails.
const candidates = readdirSync(pnpmDir)
  .filter((d) => d.startsWith(prefix))
  .sort((a, b) => {
    const aMatch = exactPrefix && versionOf(a) === activeTrain;
    const bMatch = exactPrefix && versionOf(b) === activeTrain;
    return Number(bMatch) - Number(aMatch);
  });

let LocalSandboxProvider;
let resolvedFrom;
for (const cand of candidates) {
  const entry = join(
    pnpmDir,
    cand,
    "node_modules",
    "@deepseek-ai",
    "dsh-sandbox-local",
    "lib",
    "index.js"
  );
  if (!existsSync(entry)) continue;
  const mod = await import(entry);
  if (mod.LocalSandboxProvider && typeof mod.LocalSandboxProvider.prototype.confine === "function") {
    LocalSandboxProvider = mod.LocalSandboxProvider;
    resolvedFrom = cand;
    break;
  }
}

if (!LocalSandboxProvider) {
  throw new Error(
    `local bypass: cannot find a usable @deepseek-ai/dsh-sandbox-local under node_modules/.pnpm` +
      (activeTrain ? ` (active train ${activeTrain})` : "")
  );
}
if (exactPrefix && versionOf(resolvedFrom) !== activeTrain) {
  process.emitWarning(
    `local bypass: using ${versionOf(resolvedFrom)} but active DSH train is ${activeTrain}; ` +
      `run pnpm install to sync the dependency graph`
  );
}

LocalSandboxProvider.prototype.confine = function (argv, policy, signal) {
  signal?.throwIfAborted();
  // Equivalent to danger-full-access: hand the raw argv back, fully unconfined,
  // with no sandbox backend prefix — exactly what bash-sandbox.execute() does
  // when the resolved mode is "danger-full-access".
  return Promise.resolve({
    argv,
    enforcement: "full",
    denialSignatures: [],
    runnerFailureRules: []
  });
};
