// usage: node smoke.js index.html DATA_DIR  -> runs the page script against a stub DOM
const fs = require("fs"), path = require("path");
const [html, dir] = process.argv.slice(2);
const code = fs.readFileSync(html, "utf8").match(/<script>([\s\S]*)<\/script>/)[1];
const els = {}; const el = (s) => els[s] || (els[s] = { innerHTML: "", classList: { toggle() {} }, hidden: false, dataset: {} });
let errs = 0;
global.document = { querySelector: el, addEventListener() {}, hidden: false };
global.location = { search: "?src=" + dir + "/", pathname: "/", protocol: "http:" };
global.addEventListener = () => {}; global.requestAnimationFrame = () => {}; global.navigator = { sendBeacon() {} };
global.PerformanceObserver = class { observe() {} };
global.fetch = async (u, o) => {
  if (o && o.method === "HEAD") return { headers: { get: () => null } };
  const p = u; if (!fs.existsSync(p)) return { ok: false };
  const t = fs.readFileSync(p, "utf8"); return { ok: true, text: async () => t };
};
const ce = console.error, cw = console.warn;
console.error = (...a) => { errs++; ce(...a); }; console.warn = (...a) => { errs++; cw(...a); };
eval(code + "\n;global.__s = state; global.__r = render;");
setTimeout(() => {
  for (const k of ["#head", "#filters", "#main", "#status"]) console.log(k, els[k].innerHTML.length);
  console.log("sections", (els["#main"].innerHTML.match(/<section/g) || []).length, "status", els["#status"].innerHTML.replace(/<[^>]+>/g, " ").replace(/\s+/g, " "));
  __s.on.delete(__s.all[0]); __r();  // filtered render
  console.log("filtered head", els["#head"].innerHTML.replace(/<[^>]+>/g, " ").replace(/\s+/g, " "));
  console.log("errors", errs); process.exit(errs ? 1 : 0);
}, 200);
