// Runs the <script id="core"> block from app/index.html, the code the browser really
// runs, and calls its functions. Used by test_parity.py.
//
// stdin:  a JSON list of calls, each ["functionName", arg1, arg2, ...]
//         ({"$date": milliseconds} as an argument becomes a Date)
// stdout: a JSON list of results, in the same order
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const html = fs.readFileSync(path.join(__dirname, "..", "app", "index.html"), "utf8");
const match = html.match(/<script id="core">([\s\S]*?)<\/script>/);
if (!match) {
  console.error('app/index.html has no <script id="core"> block');
  process.exit(2);
}

const context = vm.createContext({});
vm.runInContext(match[1] + "\nglobalThis.Core = Core;", context);

const calls = JSON.parse(fs.readFileSync(0, "utf8"));
const revive = (arg) => (arg && typeof arg === "object" && "$date" in arg ? new Date(arg.$date) : arg);
const results = calls.map(([name, ...args]) => context.Core[name](...args.map(revive)));
process.stdout.write(JSON.stringify(results));
