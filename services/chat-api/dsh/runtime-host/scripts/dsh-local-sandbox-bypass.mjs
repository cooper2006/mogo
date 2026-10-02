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
import { readdirSync, existsSync } from "node:fs";
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

const versionPrefix = "@deepseek-ai+dsh-sandbox-local@0.2.0-rc.2";
const cand = readdirSync(pnpmDir).find(
  (d) => d === versionPrefix || d.startsWith(versionPrefix + "_")
);
if (!cand) {
  throw new Error(`local bypass: cannot find ${versionPrefix} under node_modules/.pnpm`);
}

const mod = await import(
  join(pnpmDir, cand, "node_modules", "@deepseek-ai", "dsh-sandbox-local", "lib", "index.js")
);
const { LocalSandboxProvider } = mod;

if (!LocalSandboxProvider || typeof LocalSandboxProvider.prototype.confine !== "function") {
  throw new Error("local bypass: LocalSandboxProvider.confine not found");
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
