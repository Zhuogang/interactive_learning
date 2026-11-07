// Drives app/index.html in a real browser, the way a learner would, against a throwaway copy
// of the repo. The real CLI runs against that copy too, so the hand-off between them is real.
//
//   npm install --no-save playwright && npx playwright install chromium
//   node tests/e2e.js
//
// Optional: CHROMIUM_PATH=/path/to/chrome   use a browser you already have
//           E2E_SHOTS=/some/folder          save a screenshot of each screen, to look at
const { chromium } = require("playwright");
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");

const REPO = path.resolve(__dirname, "..");
const OUT = process.env.E2E_SHOTS || null;
const EXE = process.env.CHROMIUM_PATH || undefined;
const ID = "learning-how-to-learn";
const PKEY = `il:progress:${ID}`;
let BASE = "";

if (OUT) fs.mkdirSync(OUT, { recursive: true });
const SITE = fs.mkdtempSync(path.join(os.tmpdir(), "il-e2e-"));
for (const dir of ["app", "projects", "tools", "templates", "schema"]) {
  fs.cpSync(path.join(REPO, dir), path.join(SITE, dir), { recursive: true });
}
const deck = JSON.parse(fs.readFileSync(path.join(SITE, "projects", ID, "deck.json"), "utf8"));
const il = (...args) => spawnSync("python3", ["tools/il.py", ...args], { cwd: SITE, encoding: "utf8" });

let passed = 0;
const failures = [];
function check(name, cond, detail) {
  if (cond) passed += 1;
  else {
    failures.push(name + (detail !== undefined ? `  -> ${JSON.stringify(detail)}` : ""));
    console.log("  FAIL", failures[failures.length - 1]);
  }
}
const section = (name) => console.log("\n== " + name);

const strip = (s) => s.replace(/\*\*/g, "").replace(/\*/g, "").replace(/`/g, "");
const norm = (s) => s.replace(/\s+/g, " ").trim();
async function currentCard(page) {
  const title = norm(await page.textContent("h1"));
  return deck.questions.find((q) => norm(strip(q.prompt)) === title);
}
const logOf = (page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) || "{}").log || [], PKEY);
const progressOf = (page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) || "null"), PKEY);

async function clickOption(page, wantCorrect) {
  const card = await currentCard(page);
  const target = card.options.find((o) => (o.correct === true) === wantCorrect);
  for (const b of await page.$$(".option")) {
    if (norm(await b.textContent()).includes(norm(strip(target.text)))) {
      await b.click();
      return card;
    }
  }
  throw new Error("option not found: " + target.text);
}

// Attach error tracking to a page. progress.json 404s are expected until a file exists.
function track(page, errors) {
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/progress\.json|404/.test(m.text() + (m.location().url || ""))) errors.push("console: " + m.text());
  });
  return page;
}

async function noHorizontalScroll(page, label) {
  const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  check(`no horizontal scroll: ${label}`, m.sw <= m.cw, m);
}

async function smallTargets(page) {
  return page.evaluate(() => [...document.querySelectorAll("button, a.btn, a.crumb, .file-btn")]
    .filter((el) => el.offsetParent !== null && !el.classList.contains("linkish"))
    .map((el) => ({ t: el.textContent.trim().slice(0, 30), h: Math.round(el.getBoundingClientRect().height) }))
    .filter((x) => x.h < 44));
}

// Note: a full-page capture of a tall page on an emulated phone briefly leaves mobile emulation,
// so <kbd> hints can show up in these images. The assertions check the live page instead.
async function shot(page, name) {
  if (OUT) await page.screenshot({ path: path.join(OUT, name + ".png"), fullPage: true });
}

// The settings panel remembers being open, so only click when it's closed.
async function openSettings(page, how = "click") {
  if (!(await page.isVisible("text=Export progress"))) await page[how](".panel > summary");
}

const freePort = () => new Promise((resolve) => {
  const s = net.createServer();
  s.listen(0, "127.0.0.1", () => {
    const { port } = s.address();
    s.close(() => resolve(port));
  });
});

async function waitForServer(url) {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch (_) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("the static server didn't start");
}

let server = null;
let browser = null;

(async () => {
  const port = await freePort();
  BASE = `http://127.0.0.1:${port}`;
  server = spawn("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1"], { cwd: SITE, stdio: "ignore" });
  await waitForServer(BASE + "/projects/manifest.json");
  browser = await chromium.launch({ executablePath: EXE });
  const errors = [];

  // ---------------------------------------------------------------------------------------------
  section("A. First run: the whole daily loop, by mouse, light mode, desktop");
  {
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 }, colorScheme: "light", acceptDownloads: true });
    const page = track(await ctx.newPage(), errors);
    await page.goto(BASE + "/app/");
    await page.waitForSelector("h1");
    check("one deck: lands straight on the deck page", page.url().endsWith(`#/d/${ID}`), page.url());
    check("deck title", (await page.textContent("h1")) === "Learning How to Learn");
    check("the focused heading shows no focus ring", (await page.evaluate(() => getComputedStyle(document.querySelector("h1")).outlineStyle)) === "none");
    check("anchor placeholder comes from the deck", (await page.getAttribute("#anchor", "placeholder")) === "pour my morning coffee");
    let text = await page.innerText("body");
    check("minimum CTA says one card", /Answer one card/.test(text));
    check("queue summary", /0 due · 5 new/.test(text), text.slice(0, 300));
    check("no streak language", !/streak/i.test(text.replace("No streak to protect", "")));
    check("calibration empty state", /After a few answers/.test(text));
    await shot(page, "01-deck-fresh");

    await page.fill("#anchor", "pour my morning coffee");
    await page.press("#anchor", "Tab");
    check("anchor saved", (await progressOf(page)).settings.anchor === "pour my morning coffee");

    await page.click("a.btn.primary");
    await page.waitForSelector(".option");
    let card = await currentCard(page);
    check("first card is the first concept's pretest", card && card.id === "retrieval-pretest", card && card.id);
    text = await page.innerText("body");
    check("labelled as a guess", /Guess first/.test(text) && /just guess/.test(text));
    check("pretest asks for no confidence", (await page.$$("[data-conf]")).length === 0);
    const html0 = await page.content();
    check("no feedback in the DOM before answering", !card.options.some((o) => html0.includes(o.why)));
    check("options all shown", (await page.$$(".option")).length === card.options.length);
    await shot(page, "02-pretest");

    await clickOption(page, false);
    await page.waitForSelector(".banner");
    text = await page.innerText("body");
    check("a wrong guess is reassured", /that's fine/.test(text), text.slice(0, 200));
    check("every option's why is now shown", card.options.every((o) => norm(text).includes(norm(strip(o.why)))));
    check("correct option marked with a label", /Correct/.test(text));
    let log = await logOf(page);
    check("pretest logged", log.length === 1 && log[0].pretest === true && log[0].via === "app" && log[0].conf === "guess", log);
    check("focus lands on Next", await page.evaluate(() => document.activeElement && document.activeElement.textContent === "Next"));
    await shot(page, "03-pretest-revealed");

    await page.click("[data-primary]");
    await page.waitForSelector(".yes");
    text = await page.innerText("body");
    check("stops and celebrates at the minimum", /Yes!/.test(text) && /full success/.test(text));
    check("repeats their recipe, in their words", text.includes('"After I pour my morning coffee, I will answer one card."'), text);
    check("first show-up day", /first show-up day/.test(text));
    check("stopping is the primary action", /Stop here/.test(await page.textContent("[data-primary]")));
    check("offers bonus reps", /Keep going \(4 more\)/.test(text), text);
    await page.waitForTimeout(1000);
    await shot(page, "04-celebrate");

    await page.click("text=Keep going");
    await page.waitForSelector(".note, .answer");
    text = await page.innerText("body");
    check("concept intro comes after the pretest", /New concept/.test(text) && /Retrieval practice/.test(text));
    check("intro has analogy, example and source pointer", /Think of it like this/.test(text) && /For example/.test(text) && /PRINCIPLES\.md §1/.test(text));
    await shot(page, "05-intro");
    await page.click("[data-primary]");

    await page.waitForSelector("textarea");
    card = await currentCard(page);
    check("next is the short recall card", card.type === "short", card.id);
    const html1 = await page.content();
    check("answer not in the DOM before commit", !html1.includes(card.answer) && !card.key_points.some((k) => html1.includes(k)));
    check("confidence labels", (await page.innerText(".triple")).replace(/\s+/g, " ").includes("Guessing") && /I think so/.test(await page.innerText(".triple")) && /I know it/.test(await page.innerText(".triple")));
    await shot(page, "06-short-answer");
    await page.fill('textarea[aria-label="Your answer"]', "It was about timing: <b>five minutes</b> vs a week.");
    await page.click('[data-conf="think"]');
    await page.waitForSelector("[data-grade]");
    text = await page.innerText("body");
    check("typed answer echoed as text, not HTML", /<b>five minutes<\/b>/.test(text));
    check("answer shown after commit", norm(text).includes(norm(card.answer)));
    log = await logOf(page);
    check("the reveal goes on the record, as missed until graded", log.length === 2 && log[1].q === card.id && log[1].grade === "again" && log[1].conf === "think", log);
    const boxes = await page.$$(".checks input");
    check("key points are tickable", boxes.length === card.key_points.length);
    await boxes[0].check();
    check("one tick suggests partly", (await page.getAttribute('[data-grade="partly"]', "class")).includes("sugg-on"));
    await boxes[1].check();
    check("all ticks suggest got it", (await page.getAttribute('[data-grade="good"]', "class")).includes("sugg-on"));
    check("suggestion moves", !(await page.getAttribute('[data-grade="partly"]', "class")).includes("sugg-on"));
    await shot(page, "07-short-revealed");
    await page.click('[data-grade="good"]');
    await page.waitForFunction(() => !document.querySelector("[data-grade]"));
    log = await logOf(page);
    check("self-grade logged with score from ticks", log[1].q === "retrieval-recall" && log[1].grade === "good" && log[1].score === 1 && log[1].conf === "think", log[1]);
    check("toast teaches the schedule", /Up to box 1\. Next review tomorrow/.test(await page.textContent("#toast")), await page.textContent("#toast"));

    // Miss a short card: it must come back later in this session.
    card = await currentCard(page);
    check("third card is the why card", card.id === "retrieval-why", card.id);
    await page.click('[data-conf="know"]');
    await page.click('[data-grade="again"]');
    check("confident miss comforts", /fix best/.test(await page.textContent("#toast")));
    check("miss logged", (await logOf(page))[2].grade === "again");

    // MCQ: confidence is locked until an answer is picked, and wrong + "I know it" is hypercorrection copy.
    await page.waitForSelector(".option");
    card = await currentCard(page);
    check("confidence locked before picking", await page.isDisabled('[data-conf="know"]'));
    await shot(page, "08-mcq-unpicked");
    await clickOption(page, false);
    check("confidence unlocked after picking", !(await page.isDisabled('[data-conf="know"]')));
    check("picked option is pressed", (await page.$$('.option[aria-pressed="true"]')).length === 1);
    await shot(page, "09-mcq-picked");
    await page.click('[data-conf="know"]');
    await page.waitForSelector(".banner");
    text = await page.innerText(".banner");
    check("confident wrong answer gets the hypercorrection note", /fix best/.test(text) && /later this session/.test(text), text);
    await shot(page, "10-mcq-confident-wrong");
    await page.click("[data-primary]");

    // Correct guess on the last new card.
    await page.waitForSelector(".option");
    card = await currentCard(page);
    await clickOption(page, true);
    await page.click('[data-conf="guess"]');
    await page.waitForSelector(".banner");
    text = await page.innerText(".banner");
    check("correct guess counts as partly", /counts as partly/.test(text), text);
    log = await logOf(page);
    check("correct guess: grade partly, score 1", log[log.length - 1].grade === "partly" && log[log.length - 1].score === 1, log[log.length - 1]);
    await shot(page, "11-correct-guess");
    await page.click("[data-primary]");

    // The two misses come back. Get them right.
    const seenRetries = [];
    for (let i = 0; i < 4; i++) {
      await page.waitForSelector("h1");
      if (await page.$(".title")) break;
      card = await currentCard(page);
      seenRetries.push(card.id);
      if (card.type === "mcq") {
        await clickOption(page, true);
        await page.click('[data-conf="think"]');
        await page.waitForSelector(".banner");
        if (seenRetries.length === 1) {
          text = await page.innerText(".banner");
          check("a same-day retry can't promote", /only once a day|stays in box 1|Right/.test(text), text);
        }
        await page.click("[data-primary]");
      } else {
        await page.click('[data-conf="think"]');
        await page.click('[data-grade="good"]');
      }
      await page.waitForFunction(() => !document.querySelector(".banner"));
    }
    check("both missed cards came back", seenRetries.includes("retrieval-why") && seenRetries.includes("retrieval-apply"), seenRetries);

    await page.waitForSelector(".title");
    text = await page.innerText("body");
    check("done screen", /That's everything for today/.test(text), text);
    check("done counts", /1 guess/.test(text) && /missed/.test(text), text);
    check("normalizes misses", /60% right is normal/.test(text));
    check("next-up line", /Next up: \d+ cards? tomorrow/.test(text), text);
    await shot(page, "12-done");

    await page.click("[data-primary]");
    await page.waitForSelector(".pill");
    text = await page.innerText("body");
    check("deck page: today counts", /Today counts/.test(text));
    check("no more new cards today", /Nothing else is due/.test(text), text.slice(0, 400));
    check("one show-up day", /1 of the last 28 days · 1 in total/.test(text), text);
    check("today's dot is filled", (await page.$$(".day.on.today")).length === 1 && (await page.$$(".day.on")).length === 1);
    check("28 cells", (await page.$$(".day")).length === 28);
    check("a started concept keeps its progress bar while collapsed", await page.isVisible(".concept details .meter"));
    check("only started concepts can be opened", (await page.$$(".concept details")).length === 1);
    check("unseen summaries aren't on the page", !(await page.content()).includes(deck.concepts[1].summary.slice(0, 30)));
    await shot(page, "13-deck-after");

    // Changing a setting mustn't lose your place.
    await openSettings(page);
    await page.fill('[data-setting="new_per_day"]', "9");
    await page.evaluate(() => window.scrollTo(0, 400));
    const scrolled = await page.evaluate(() => window.scrollY);
    await page.press('[data-setting="new_per_day"]', "Tab");
    await page.waitForSelector("a.btn:has-text('Bonus reps')");
    check("changing a setting keeps the panel open", await page.isVisible("text=Export progress"));
    check("changing a setting keeps your place", scrolled > 0 && (await page.evaluate(() => window.scrollY)) === scrolled, scrolled);
    check("changing a setting keeps focus on the field", await page.evaluate(() => document.activeElement.dataset.setting === "new_per_day"));

    // Bonus reps later the same day: no second celebration, and the bar counts them.
    await page.click("a.btn:has-text('Bonus reps')");
    await page.waitForSelector(".prompt");
    const before = (await logOf(page)).length;
    const extra = await currentCard(page);
    if (extra && extra.type === "mcq") {
      await clickOption(page, true);
      await page.click('[data-conf="think"]');
      await page.waitForSelector(".banner");
      check("the bar counts bonus reps", /bonus reps?/.test(await page.innerText(".study-bar")), await page.innerText(".study-bar"));
      await page.click("[data-primary]");
    } else {
      if (!extra) await page.click("[data-primary]"); // the new concept's intro
      await page.waitForSelector("[data-conf]");
      await page.click('[data-conf="think"]');
      await page.click('[data-grade="good"]');
    }
    await page.waitForSelector(".prompt, .title");
    check("a bonus rep was recorded", (await logOf(page)).length === before + 1);
    check("a bonus rep doesn't celebrate again", !(await page.$(".yes")));
    await ctx.close();
  }

  // ---------------------------------------------------------------------------------------------
  section("B. Keyboard only");
  {
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } });
    const page = track(await ctx.newPage(), errors);
    await page.goto(`${BASE}/app/#/d/${ID}/study`);
    await page.waitForSelector(".option");
    const kbd = await page.locator(".option kbd").first().isVisible();
    check("number hints visible with a mouse", kbd);
    await page.keyboard.press("1");
    await page.waitForSelector(".banner");
    check("1 answers the pretest", (await logOf(page)).length === 1);
    check("focus on Next", await page.evaluate(() => document.activeElement.textContent === "Next"));
    await page.keyboard.press("Enter");
    await page.waitForSelector(".yes");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    await page.waitForSelector(".note");
    await page.keyboard.press("Enter");
    await page.waitForSelector("textarea");
    // Typing in the box must not trigger shortcuts.
    await page.focus("textarea");
    await page.keyboard.type("gtk 123");
    check("typing doesn't fire shortcuts", (await page.$$("[data-grade]")).length === 0 && (await page.inputValue("textarea")) === "gtk 123");
    await page.evaluate(() => document.activeElement.blur());
    await page.keyboard.press("t");
    await page.waitForSelector("[data-grade]");
    await page.keyboard.press("3");
    await page.waitForFunction(() => !document.querySelector("[data-grade]"));
    const log = await logOf(page);
    check("t then 3 graded it", log[1].conf === "think" && log[1].grade === "good", log[1]);
    // Unavailable keys do nothing.
    await page.waitForSelector("textarea");
    await page.evaluate(() => document.activeElement.blur());
    await page.keyboard.press("1");
    check("grade keys don't fire before the reveal", (await logOf(page)).length === 2);
    await ctx.close();
  }

  // ---------------------------------------------------------------------------------------------
  section("C. Coming back tomorrow, with the real clock moved forward");
  {
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } });
    const page = track(await ctx.newPage(), errors);
    const start = new Date(); start.setHours(9, 0, 0, 0);
    await page.clock.install({ time: start });
    await page.goto(`${BASE}/app/#/d/${ID}/study`);
    await page.waitForSelector(".option");
    await clickOption(page, true);
    await page.waitForSelector(".banner");
    const first = await logOf(page);
    check("pretest correct still starts in box 1", /starts in box 1/.test(await page.innerText(".banner")));
    check("pretest correct is a good guess", /Good guess/.test(await page.innerText(".banner")));
    // Tomorrow.
    await page.clock.setSystemTime(new Date(start.getTime() + 86400000));
    await page.goto(`${BASE}/app/#/d/${ID}`);
    await page.reload();
    await page.waitForSelector(".btn.primary");
    const text = await page.innerText("body");
    check("the pretest card is due the next day", /1 due · 5 new/.test(text), text.slice(0, 400));
    check("yesterday doesn't count for today", /Answer one card/.test(text));
    check("no guilt", !/missed|behind|overdue|catch up/i.test(text.split("How sure")[0].replace("Missed days carry no penalty", "")));
    await page.click("a.btn.primary");
    await page.waitForSelector(".option");
    const eyebrow = await page.innerText(".eyebrow");
    check("a pretest card coming back is a review, not a guess", /Review/.test(eyebrow) && !/Guess first/.test(eyebrow), eyebrow);
    check("reviews ask for confidence", (await page.$$("[data-conf]")).length === 3);
    await clickOption(page, true);
    await page.click('[data-conf="know"]');
    await page.waitForSelector(".banner");
    check("moves up with a longer gap", /Up to box 2\. Next review in 3 days/.test(await page.innerText(".banner")), await page.innerText(".banner"));
    const log = await logOf(page);
    check("second answer isn't flagged pretest", !log[1].pretest && first.length === 1, log);
    await ctx.close();
  }

  // ---------------------------------------------------------------------------------------------
  section("D. Teach-it card: jargon, word limit, rubric, explain again, save");
  {
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 }, permissions: ["clipboard-read", "clipboard-write"] });
    const page = track(await ctx.newPage(), errors);
    await page.goto(`${BASE}/app/`);
    await page.waitForSelector("h1");
    // All of retrieval except the teach-it card already answered, a week ago.
    const old = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
    const seeded = deck.questions.filter((q) => q.concept === "retrieval" && q.type !== "feynman")
      .map((q, i) => ({ at: `${old}T09:00:0${i}`, q: q.id, grade: "good", score: 1, conf: "know", via: "chat", ...(q.purpose === "pretest" ? { pretest: true } : {}) }));
    const later = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
    await page.evaluate(([k, log, settings]) => localStorage.setItem(k, JSON.stringify({ format: 1, deck: "learning-how-to-learn", settings, log, feynman: {}, gaps: [] })),
      [PKEY, seeded, { minimum: 1, new_per_day: 1, anchor: "" }]);
    await page.reload();
    await page.waitForSelector(".btn");
    // Clear the reviews by answering until the teach-it card arrives.
    await page.click("a.btn.primary");
    let card;
    for (let i = 0; i < 12; i++) {
      await page.waitForSelector(".prompt, .yes");
      if (await page.$(".yes")) { await page.click("text=Keep going"); await page.waitForSelector(".prompt"); }
      card = await currentCard(page);
      if (card && card.type === "feynman") break;
      if (card.type === "mcq") { await clickOption(page, true); await page.click('[data-conf="know"]'); await page.waitForSelector(".banner"); await page.click("[data-primary]"); await page.waitForFunction(() => !document.querySelector(".banner")); }
      else { await page.click('[data-conf="know"]'); await page.click('[data-grade="good"]'); await page.waitForFunction(() => !document.querySelector("[data-grade]")); }
    }
    check("reaches the teach-it card", card && card.id === "retrieval-teach", card && card.id);
    let text = await page.innerText("body");
    check("shows audience and limit", /For:\s*a curious 12-year-old/.test(text) && /Limit:\s*100 words/.test(text), text.slice(0, 300));
    check("shows the jargon to avoid", /Avoid:/.test(text) && /testing effect/.test(text));
    const htmlT = await page.content();
    check("rubric hidden before committing", !card.rubric.some((r) => htmlT.includes(r)));
    check("follow-ups hidden before committing", !card.follow_ups.some((f) => htmlT.includes(f)));
    const area = 'textarea[aria-label="Your explanation"]';
    await page.fill(area, "Quizzing is like walking a path.");
    check("word count", /6 \/ 100 words/.test(await page.innerText(".counter")), await page.innerText(".counter"));
    check("no jargon flagged yet", !(await page.isVisible(".spotted")));
    await page.fill(area, "Retrieval practice helps. The TESTING EFFECTS are real. Encoding too.");
    const spotted = await page.innerText(".spotted");
    check("jargon flagged live, case-insensitive, with plurals", /retrieval practice/.test(spotted) && /testing effect/.test(spotted) && /encoding/.test(spotted), spotted);
    check("flagged chips highlighted", (await page.$$(".chip.hit")).length === 3);
    await page.fill(area, "retrievalpractice is not a word");
    check("no false positive inside a word", !(await page.isVisible(".spotted")));
    await page.fill(area, Array(120).fill("word").join(" "));
    check("over the word limit is flagged", /over/.test(await page.getAttribute(".counter span", "class")) && /Over the limit/.test(await page.innerText(".counter")));
    await page.fill(area, "Quizzing makes memories stronger because you pull them out. Rereading just feels familiar. Like walking a forest path: each walk clears it. Quizzing also shows what you don't know yet.");
    await shot(page, "14-teach-write");
    await page.click('[data-conf="think"]');
    await page.waitForSelector("[data-grade]");
    text = await page.innerText("body");
    check("rubric shown after committing", card.rubric.every((r) => text.includes(r)));
    check("follow-ups shown after committing", card.follow_ups.every((f) => text.includes(f)));
    check("on the record as missed until graded", (await logOf(page)).find((e) => e.q === card.id).grade === "again");
    await shot(page, "15-teach-revealed");
    // Explain again keeps the words, resets the commit.
    await page.click("text=Explain it again, more simply");
    await page.waitForSelector(area);
    check("explain again keeps the text", /forest path/.test(await page.inputValue(area)));
    check("explain again focuses the box", await page.evaluate(() => document.activeElement.tagName === "TEXTAREA"));
    await page.fill(area, "Quizzing beats rereading: pulling a memory out makes it stronger, like walking a forest path. Rereading only feels familiar. And quizzing shows what you don't know yet.");
    await page.click('[data-conf="know"]');
    await page.waitForSelector("[data-grade]");
    await page.click("text=Copy for your tutor");
    await page.waitForTimeout(150);
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    check("copy for tutor includes the card and their words", clip.includes(card.id) && clip.includes("Quizzing beats rereading") && /don't rewrite/.test(clip), clip);
    const ticks = await page.$$(".checks input");
    for (const t of ticks.slice(0, 4)) await t.check();
    await page.click('[data-grade="partly"]');
    await page.waitForFunction(() => !document.querySelector("[data-grade]"));
    const p = await progressOf(page);
    const entry = p.log.find((e) => e.q === card.id);
    check("logged once with rubric score", p.log.filter((e) => e.q === card.id).length === 1 && entry.grade === "partly" && entry.score === 0.8 && entry.conf === "know", entry);
    const saved = (p.feynman.retrieval || [])[0];
    check("teach-back saved in their words", saved && saved.q === card.id && saved.text.startsWith("Quizzing beats rereading") && saved.score === 0.8 && saved.words > 10, saved);
    check("explaining again leaves one teach-back, not two", p.feynman.retrieval.length === 1, p.feynman);

    await ctx.close();

    // A week later, the same card shows what they wrote last time, but only after they commit.
    const ctx2 = await browser.newContext({ viewport: { width: 1100, height: 900 } });
    const next = track(await ctx2.newPage(), errors);
    await next.goto(`${BASE}/app/`);
    await next.waitForSelector("h1");
    await next.evaluate(([k, day]) => localStorage.setItem(k, JSON.stringify({
      format: 1, deck: "learning-how-to-learn", settings: { minimum: 1, new_per_day: 0, anchor: "" },
      log: [{ at: day + "T09:00:00", q: "retrieval-teach", grade: "partly", score: 0.6, via: "app" }],
      feynman: { retrieval: [{ at: day + "T09:00:00", q: "retrieval-teach", text: "my words from last week", words: 5, score: 0.6 }] },
      gaps: [],
    })), [PKEY, old]);
    await next.reload();
    await next.waitForSelector("a.btn.primary");
    await next.click("a.btn.primary");
    await next.waitForSelector(area);
    check("earlier explanation hidden while writing", !(await next.content()).includes("my words from last week"));
    await next.fill(area, "new attempt");
    await next.click('[data-conf="think"]');
    await next.waitForSelector("[data-grade]");
    await next.click("details.gap >> nth=0");
    check("earlier explanation shown after committing", await next.isVisible("text=my words from last week"));
    await ctx2.close();
  }

  // ---------------------------------------------------------------------------------------------
  section("E. Gaps, settings, export, and the round trip through the real CLI");
  {
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 }, acceptDownloads: true });
    const page = track(await ctx.newPage(), errors);
    await page.goto(`${BASE}/app/#/d/${ID}`);
    await page.waitForSelector("#anchor");
    await page.fill("#anchor", 'brew my "first" tea');
    await page.press("#anchor", "Tab");
    await openSettings(page);
    await page.fill('[data-setting="minimum"]', "2");
    await page.press('[data-setting="minimum"]', "Tab");
    await page.waitForSelector("a.btn.primary");
    check("raised minimum changes the CTA", /Answer 2 cards/.test(await page.innerText("body")));
    await page.click("a.btn.primary");
    await page.waitForSelector(".option");
    await clickOption(page, false);
    await page.waitForSelector(".banner");
    // Note a gap.
    await page.click(".gap summary");
    await page.fill('textarea[aria-label="What confused you?"]', 'Why does "rereading" feel\nso good?');
    await page.click("text=Save the gap");
    check("gap toast", /Gaps can become new cards/.test(await page.textContent("#toast")));
    await page.click("[data-primary]");
    check("doesn't celebrate before a minimum of 2", !(await page.$(".yes")));
    await page.waitForSelector(".note");
    await page.click("[data-primary]");
    await page.waitForSelector("textarea");
    await page.click('[data-conf="know"]');
    await page.click('[data-grade="partly"]');
    await page.waitForSelector(".yes");
    check("celebrates at a minimum of 2", /today's 2 cards/.test(await page.innerText("body")), await page.innerText("body"));
    await page.click("text=Stop here");
    await page.waitForSelector(".pill");
    let text = await page.innerText("body");
    check("gaps listed on the deck page", /Gaps \(1\)/.test(text) && /feel\s+so good/.test(text), text);
    check("bonus reps offered after the minimum", /Bonus reps \(3 available\)/.test(text), text);
    await shot(page, "16-deck-with-gap");

    // Export.
    await openSettings(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("text=Export progress")]);
    check("export filename", dl.suggestedFilename() === `progress-${ID}.json`, dl.suggestedFilename());
    const exportPath = path.join(SITE, dl.suggestedFilename());
    await dl.saveAs(exportPath);
    const exported = fs.readFileSync(exportPath, "utf8");
    check("export has one answer per line", exported.split("\n").filter((l) => l.startsWith('    {"at"')).length >= 3, exported);
    check("scores print as floats like Python's", /"score": 0\.0/.test(exported) || /"score": 0\.5/.test(exported), exported);

    // Real CLI: import into a repo with no progress yet, byte-compare.
    const imp = il("import", ID, exportPath);
    check("il.py import works", imp.status === 0 && /merged 2 new/.test(imp.stdout), imp);
    const onDisk = fs.readFileSync(path.join(SITE, "projects", ID, "progress.json"), "utf8");
    check("CLI writes the export back byte-for-byte", onDisk === exported, { onDisk, exported });
    const again = il("import", ID, exportPath);
    check("second import adds nothing", /merged 0 new/.test(again.stdout) && fs.readFileSync(path.join(SITE, "projects", ID, "progress.json"), "utf8") === exported);
    const gaps = JSON.parse(il("gaps", ID, "--json").stdout);
    check("gap reached the CLI", gaps.length === 1 && gaps[0].q === "retrieval-pretest" && /rereading/.test(gaps[0].text), gaps);
    const status = il("status", ID).stdout;
    check("CLI status sees the settings", /open gaps: 1/.test(status), status);
    const settings = il("settings", ID).stdout;
    check("settings survived the first import", /minimum 2/.test(settings) && /brew my "first" tea/.test(settings), settings);

    // Queues agree: CLI vs app, on the same log.
    const cliQueue = JSON.parse(il("due", ID, "--json").stdout).items.map((i) => i.q);
    await page.goto(`${BASE}/app/#/d/${ID}/study`);
    await page.reload();
    await page.waitForSelector(".prompt");
    let first = await currentCard(page);
    if (!first) { await page.click("[data-primary]"); await page.waitForSelector(".prompt"); first = await currentCard(page); }
    check("app and CLI agree on the next card", first && first.id === cliQueue[0], { first: first && first.id, cliQueue });

    // Chat -> app: an answer recorded by the CLI shows up in a fresh browser, on its own.
    const rec = il("record", ID, cliQueue[0], "good", "--conf", "know");
    check("il.py record", rec.status === 0, rec);
    il("gaps", ID, "--close", gaps[0].at, "--card", "retrieval-why");
    const ctx2 = await browser.newContext({ viewport: { width: 1100, height: 900 } });
    const fresh = track(await ctx2.newPage(), errors);
    await fresh.goto(`${BASE}/app/#/d/${ID}`);
    await fresh.waitForSelector("#anchor");
    text = await fresh.innerText("body");
    check("new browser adopts the chat answers", /Today counts/.test(text), text.slice(0, 300));
    check("new browser adopts settings from the file", (await fresh.inputValue("#anchor")) === 'brew my "first" tea');
    check("closed gap stays closed", !/Gaps \(/.test(text));
    // And the original browser, which has its own local copy, merges without duplicates.
    await page.goto(`${BASE}/app/#/d/${ID}`);
    await page.reload();
    await page.waitForSelector("#anchor");
    const merged = await progressOf(page);
    const keys = merged.log.map((e) => e.at + e.q);
    check("existing browser merges without duplicates", new Set(keys).size === keys.length && merged.log.length === 3, merged.log);
    check("gap closed from the CLI closes in the app", !/Gaps \(/.test(await page.innerText("body")));
    await ctx2.close();

    // Import in the app: bad file, wrong deck, good file.
    await openSettings(page);
    const importInput = page.locator('.panel input[type=file]').first();
    const junk = path.join(SITE, "junk.json");
    fs.writeFileSync(junk, "{nope");
    await importInput.setInputFiles(junk);
    await page.waitForFunction(() => /isn't valid JSON/.test(document.getElementById("toast").textContent));
    check("bad JSON is refused kindly", true);
    fs.writeFileSync(junk, JSON.stringify({ deck: "other", log: [] }));
    await importInput.setInputFiles(junk);
    await page.waitForFunction(() => /not "learning-how-to-learn"/.test(document.getElementById("toast").textContent));
    check("wrong deck is refused kindly", true);
    fs.writeFileSync(junk, JSON.stringify({ deck: ID, log: [{ at: "2020-01-01T09:00:00", q: "retrieval-why", grade: "good", score: 1.0 }] }));
    await importInput.setInputFiles(junk);
    await page.waitForFunction(() => /Merged 1 new answer/.test(document.getElementById("toast").textContent));
    check("good import merges", (await logOf(page)).some((e) => e.at.startsWith("2020")));
    await page.waitForSelector("#anchor");

    // Reset.
    await openSettings(page);
    page.once("dialog", (d) => d.dismiss());
    await page.click("button:has-text('Reset')");
    check("dismissing reset keeps the data", (await logOf(page)).length >= 4);
    page.once("dialog", (d) => d.accept());
    await page.click("button:has-text('Reset')");
    await page.waitForTimeout(400);
    const after = await page.evaluate((k) => localStorage.getItem(k), PKEY);
    check("reset clears this browser's copy", after === null || !/2020-01-01/.test(after), after);
    await ctx.close();
    fs.rmSync(path.join(SITE, "projects", ID, "progress.json"));
  }

  // ---------------------------------------------------------------------------------------------
  section("F. Hostile deck: nothing in a deck may run");
  {
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } });
    const page = track(await ctx.newPage(), errors);
    await page.goto(`${BASE}/app/`);
    await page.waitForSelector("h1");
    await page.goto(`${BASE}/app/#/`);
    await page.waitForSelector(".file-btn");
    await shot(page, "17-home");
    const evil = "<img src=x onerror=\"window.__pwned=1\"><script>window.__pwned=1</script>";
    const nasty = {
      format: 1, id: "evil-deck", title: "Evil " + evil, subtitle: evil, source: { kind: "topic", title: "x" },
      habit: { suggested_anchor: '"><img src=x onerror="window.__pwned=1">' },
      concepts: [{ id: "c", title: "C " + evil, summary: `S ${evil} [click](javascript:window.__pwned=1) [ok](https://example.com/?a=1&b="2) \`<b>code</b>\``,
        analogy: evil, example: evil, read: "Read " + evil, read_url: "javascript:window.__pwned=1", jargon: [evil, "a(b", "c[d"] }],
      questions: [
        { id: "p", concept: "c", type: "mcq", purpose: "pretest", prompt: "P " + evil, ref: evil, explanation: evil,
          options: [{ text: "A " + evil, correct: true, why: evil }, { text: "B " + evil, why: evil }] },
        { id: "s", concept: "c", type: "short", purpose: "recall", prompt: "S " + evil, answer: evil, key_points: [evil, evil], explanation: evil },
        { id: "f", concept: "c", type: "feynman", purpose: "teach", prompt: "F " + evil, audience: evil, word_limit: 5, rubric: [evil, evil], follow_ups: [evil] },
        { id: "bad", concept: "nope", type: "mcq", purpose: "recall", prompt: "dropped", options: [] },
        { id: "weird", concept: "c", type: "essay", purpose: "recall", prompt: "dropped" },
      ],
    };
    const file = path.join(SITE, "evil.json");
    fs.writeFileSync(file, JSON.stringify(nasty));
    await page.locator("input[type=file]").first().setInputFiles(file);
    await page.waitForSelector("#anchor");
    check("opens a picked deck", page.url().endsWith("#/d/evil-deck"), page.url());
    check("warns about unusable cards", /2 cards couldn't be used/.test(await page.innerText("body")), (await page.innerText("body")).slice(0, 300));
    await page.click("a.btn.primary");
    await page.waitForSelector(".option");
    await page.locator(".option").first().click();
    await page.waitForSelector(".banner");
    await page.click("[data-primary]");
    await page.waitForSelector(".yes");
    await page.click("text=Keep going");
    await page.waitForSelector(".answer");
    const hrefs = await page.$$eval("a[href]", (as) => as.map((a) => a.getAttribute("href")));
    check("no javascript: links", !hrefs.some((h) => /^javascript:/i.test(h)), hrefs);
    check("https link is kept", hrefs.some((h) => h.startsWith("https://example.com/")), hrefs);
    check("code renders as text", (await page.innerText(".answer")).includes("<b>code</b>"));
    await page.click("[data-primary]");
    await page.waitForSelector("textarea");
    await page.click('[data-conf="know"]');
    await page.waitForSelector("[data-grade]");
    await page.click('[data-grade="good"]');
    await page.waitForSelector('textarea[aria-label="Your explanation"]');
    await page.fill('textarea[aria-label="Your explanation"]', "a(b c[d");
    check("regex characters in jargon don't crash, and match", (await page.$$(".chip.hit")).length === 2, (await page.$$(".chip.hit")).length);
    await page.click('[data-conf="know"]');
    await page.waitForSelector("[data-grade]");
    await page.waitForTimeout(300);
    check("nothing from the deck ran", (await page.evaluate(() => window.__pwned)) === undefined);
    check("no stray elements", (await page.$$("#app img, #app script")).length === 0);
    await page.click('[data-grade="good"]');
    await page.waitForSelector(".title");

    // Home lists it, and it survives a reload. Then forget it.
    await page.goto(`${BASE}/app/#/`);
    await page.reload();
    await page.waitForSelector(".deck-row");
    check("home lists both decks", (await page.$$(".deck-row")).length === 2);
    check("still nothing ran", (await page.evaluate(() => window.__pwned)) === undefined);
    check("completed deck shows as counted", /Today counts/.test(await page.innerText(".deck-row >> nth=0")));
    await page.click(".deck-row >> nth=0");
    await page.waitForSelector("#anchor");
    await openSettings(page);
    await page.click("text=Forget this deck file");
    await page.waitForFunction(() => /Forgot the deck file/.test(document.getElementById("toast").textContent));
    await page.waitForSelector(".deck-row");
    check("forgetting removes it from the list", (await page.$$(".deck-row")).length === 1);

    // Not a deck at all.
    fs.writeFileSync(file, '{"hello": "world"}');
    await page.locator("input[type=file]").first().setInputFiles(file);
    await page.waitForFunction(() => /doesn't look like a deck/.test(document.getElementById("toast").textContent));
    check("a non-deck file is refused", true);
    fs.writeFileSync(file, "not json");
    await page.locator("input[type=file]").first().setInputFiles(file);
    await page.waitForFunction(() => /isn't valid JSON/.test(document.getElementById("toast").textContent));
    check("a non-JSON file is refused", true);

    // Unknown deck in the URL.
    await page.goto(`${BASE}/app/#/d/no-such-deck`);
    await page.waitForFunction(() => /That didn't load/.test(document.body.innerText));
    check("unknown deck is a friendly error", /no deck called "no-such-deck"/.test(await page.innerText("body")));
    await ctx.close();
  }

  // ---------------------------------------------------------------------------------------------
  section("G. Opened as a file://, the way many people will try it first");
  {
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } });
    const page = await ctx.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
    await page.goto("file://" + path.join(SITE, "app", "index.html"));
    await page.waitForSelector(".panel");
    const text = await page.innerText("body");
    check("explains the file:// problem", /can't load from a file/.test(text) && /python3 -m http\.server 8000/.test(text), text);
    await shot(page, "18-file-protocol");
    await page.locator("input[type=file]").first().setInputFiles(path.join(SITE, "projects", ID, "deck.json"));
    await page.waitForSelector("#anchor");
    check("picking a deck.json works there", (await page.textContent("h1")) === "Learning How to Learn");
    await page.click("a.btn.primary");
    await page.waitForSelector(".option");
    await page.locator(".option").first().click();
    await page.waitForSelector(".banner");
    check("no JS errors on file://", pageErrors.length === 0, pageErrors);
    await ctx.close();
  }

  // ---------------------------------------------------------------------------------------------
  section("H. localStorage blocked (private windows, strict settings)");
  {
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 }, acceptDownloads: true });
    await ctx.addInitScript(() => {
      const nope = () => { throw new DOMException("denied", "SecurityError"); };
      Storage.prototype.setItem = nope;
      Storage.prototype.getItem = nope;
      Storage.prototype.removeItem = nope;
    });
    const page = track(await ctx.newPage(), errors);
    await page.goto(`${BASE}/app/#/d/${ID}/study`);
    await page.waitForSelector(".option");
    await page.locator(".option").first().click();
    await page.waitForSelector(".banner");
    check("warns that progress won't save", /won't save your progress/.test(await page.textContent("#toast")), await page.textContent("#toast"));
    await page.click("[data-primary]");
    await page.waitForSelector(".yes");
    check("still reaches the celebration", true);
    await page.click("text=Stop here");
    await page.waitForSelector(".pill");
    check("in-memory progress still works", /Today counts/.test(await page.innerText("body")));
    await openSettings(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("text=Export progress")]);
    const saved = path.join(SITE, "mem.json");
    await dl.saveAs(saved);
    check("can still export from memory", JSON.parse(fs.readFileSync(saved, "utf8")).log.length === 1);
    await ctx.close();
  }

  // ---------------------------------------------------------------------------------------------
  section("I. Phones: dark mode, touch, no sideways scroll, tap targets");
  for (const [w, h, name] of [[360, 740, "phone"], [320, 568, "tiny"]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: "dark", hasTouch: true, isMobile: true, deviceScaleFactor: 2 });
    const page = track(await ctx.newPage(), errors);
    const tag = (n) => `${name}-${n}`;
    await page.goto(`${BASE}/app/`);
    await page.waitForSelector("#anchor");
    await noHorizontalScroll(page, tag("deck"));
    await shot(page, tag("deck"));
    check(`bg is dark (${name})`, (await page.evaluate(() => getComputedStyle(document.body).backgroundColor)) === "rgb(23, 22, 19)");
    await page.tap("a.btn.primary");
    await page.waitForSelector(".option");
    await noHorizontalScroll(page, tag("pretest"));
    check(`no focus jump into a text box (${name})`, await page.evaluate(() => document.activeElement.tagName !== "TEXTAREA"));
    check(`tap targets (${name}) pretest`, (await smallTargets(page)).length === 0, await smallTargets(page));
    await shot(page, tag("pretest"));
    await page.locator(".option").first().tap();
    await page.waitForSelector(".banner");
    await noHorizontalScroll(page, tag("revealed"));
    await shot(page, tag("revealed"));
    await page.tap("[data-primary]");
    await page.waitForSelector(".yes");
    await page.waitForTimeout(1000);
    await noHorizontalScroll(page, tag("celebrate"));
    check(`tap targets (${name}) celebrate`, (await smallTargets(page)).length === 0, await smallTargets(page));
    await shot(page, tag("celebrate"));
    await page.tap("text=Keep going");
    await page.waitForSelector(".answer");
    await noHorizontalScroll(page, tag("intro"));
    await shot(page, tag("intro"));
    await page.tap("[data-primary]");
    await page.waitForSelector("textarea");
    await noHorizontalScroll(page, tag("short"));
    check(`tap targets (${name}) short`, (await smallTargets(page)).length === 0, await smallTargets(page));
    await page.tap('[data-conf="think"]');
    await page.waitForSelector("[data-grade]");
    await noHorizontalScroll(page, tag("short revealed"));
    const hints = await page.$$eval("kbd", (ks) => ks.map((k) => getComputedStyle(k).display));
    check(`touch: keyboard hints are hidden (${name})`, hints.length > 0 && hints.every((d) => d === "none"), hints);
    check(`tap targets (${name}) grade`, (await smallTargets(page)).length === 0, await smallTargets(page));
    await shot(page, tag("short-revealed"));
    await page.tap('[data-grade="partly"]');
    await page.goto(`${BASE}/app/#/d/${ID}`);
    await page.waitForSelector("#anchor");
    await openSettings(page, "tap");
    await noHorizontalScroll(page, tag("settings open"));
    await shot(page, tag("deck-after"));
    await ctx.close();
  }

  // ---------------------------------------------------------------------------------------------
  section("J. Reduced motion, two tabs");
  {
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 }, reducedMotion: "reduce" });
    const a = track(await ctx.newPage(), errors);
    await a.goto(`${BASE}/app/#/d/${ID}/study`);
    await a.waitForSelector(".option");
    const b = track(await ctx.newPage(), errors);
    await b.goto(`${BASE}/app/#/d/${ID}/study`);
    await b.waitForSelector(".option");
    await a.locator(".option").first().click();
    await a.waitForSelector(".banner");
    await a.click("[data-primary]");
    await a.waitForSelector(".yes");
    check("reduced motion: no burst", !(await a.isVisible(".burst")));
    check("reduced motion: no pop animation", (await a.evaluate(() => getComputedStyle(document.querySelector(".yes")).animationName)) === "none");
    await a.click("text=Keep going");
    await a.waitForSelector(".note");
    await a.click("[data-primary]");
    await a.waitForSelector("textarea");
    await a.click('[data-conf="think"]');
    await a.click('[data-grade="good"]');
    await a.waitForFunction(() => !document.querySelector("[data-grade]"));
    // Tab B has a stale in-memory copy. Answering there must not erase tab A's answers.
    await b.locator(".option").first().click();
    await b.waitForSelector(".banner");
    const log = await logOf(b);
    check("two tabs don't lose each other's answers", log.length === 3, log.map((e) => e.q));
    await ctx.close();
  }

  section("L. Regressions: things a code review found");
  {
    const removeFile = () => fs.rmSync(path.join(SITE, "projects", ID, "progress.json"), { force: true });
    const fresh = async (extra = {}) => {
      const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 }, ...extra });
      return [ctx, track(await ctx.newPage(), errors)];
    };
    const seed = async (page, value) => {
      await page.goto(`${BASE}/app/`);
      await page.waitForSelector("h1");
      await page.evaluate(([k, v]) => localStorage.setItem(k, JSON.stringify(v)), [PKEY, { format: 1, deck: ID, log: [], feynman: {}, gaps: [], ...value }]);
      await page.reload();
      await page.waitForSelector("#anchor");
    };
    const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);

    // Seeing an answer and leaving is on the record, and can't be retried as a fresh attempt.
    {
      const [ctx, page] = await fresh();
      await seed(page, { settings: { minimum: 1, new_per_day: 5, anchor: "" }, log: [{ at: `${weekAgo}T09:00:00`, q: "retrieval-pretest", grade: "again", score: 0, pretest: true, via: "app" }] });
      // Answer the due pretest so the next card is the short one.
      await page.click("a.btn.primary");
      await page.waitForSelector(".option");
      await clickOption(page, true);
      await page.click('[data-conf="think"]');
      await page.waitForSelector(".banner");
      await page.click("[data-primary]");
      await page.waitForSelector(".yes");
      await page.click("text=Keep going");
      await page.waitForSelector(".note");
      await page.click("[data-primary]");
      await page.waitForSelector("textarea");
      const card = await currentCard(page);
      await page.click('[data-conf="know"]');
      await page.waitForSelector("[data-grade]");
      await page.click("text=× Stop");
      await page.waitForSelector("#anchor");
      const entry = (await logOf(page)).find((e) => e.q === card.id);
      check("leaving after a reveal counts as missed", entry && entry.grade === "again" && entry.conf === "know" && entry.score === 0, entry);
      await page.reload();
      await page.waitForSelector("#anchor");
      await page.click("a.btn:has-text('Bonus reps')");
      await page.waitForSelector(".prompt, .note");
      const again = await currentCard(page);
      check("a revealed card isn't offered again as new today", !again || again.id !== card.id, again && again.id);
      await ctx.close();
    }

    // Their teach-back survives leaving before they grade it.
    {
      const [ctx, page] = await fresh();
      const seen = deck.questions.filter((q) => q.concept === "retrieval" && q.type !== "feynman");
      await seed(page, { settings: { minimum: 1, new_per_day: 1, anchor: "" }, log: seen.map((q, i) => ({ at: `${new Date(Date.now() + 86400000).toISOString().slice(0, 10)}T09:00:0${i}`, q: q.id, grade: "good", score: 1, via: "app" })) });
      await page.click("a.btn.primary");
      await page.waitForSelector('textarea[aria-label="Your explanation"]');
      await page.fill('textarea[aria-label="Your explanation"]', "my unfinished words");
      await page.click('[data-conf="think"]');
      await page.waitForSelector("[data-grade]");
      await page.click("text=× Stop");
      await page.waitForSelector("#anchor");
      const saved = ((await progressOf(page)).feynman.retrieval || [])[0];
      check("a teach-back is kept even if they leave before grading", saved && saved.text === "my unfinished words" && saved.score === 0, saved);
      await ctx.close();
    }

    // Grade decides score; shortcuts work after ticking a box.
    {
      const [ctx, page] = await fresh();
      await seed(page, { settings: { minimum: 1, new_per_day: 5, anchor: "" }, log: [{ at: `${weekAgo}T09:00:00`, q: "retrieval-pretest", grade: "again", score: 0, pretest: true, via: "app" }] });
      await page.click("a.btn.primary");
      await page.waitForSelector(".option");
      await clickOption(page, true);
      await page.click('[data-conf="think"]');
      await page.waitForSelector(".banner");
      await page.click("[data-primary]");
      await page.waitForSelector(".yes");
      await page.click("text=Keep going");
      await page.waitForSelector(".note");
      await page.click("[data-primary]");
      await page.waitForSelector("textarea");
      const first = await currentCard(page);
      await page.click('[data-conf="think"]');
      await page.waitForSelector(".checks input");
      for (const box of await page.$$(".checks input")) await box.check();
      await page.click('[data-grade="again"]');
      await page.waitForFunction(() => !document.querySelector("[data-grade]"));
      const missed = (await logOf(page)).find((e) => e.q === first.id);
      check("every box ticked but graded Missed scores 0", missed.grade === "again" && missed.score === 0, missed);
      await page.waitForSelector("textarea");
      const second = await currentCard(page);
      await page.click('[data-conf="think"]');
      await page.waitForSelector(".checks input");
      await (await page.$(".checks input")).click();
      check("the checkbox has focus", await page.evaluate(() => document.activeElement.type === "checkbox"));
      await page.keyboard.press("3");
      await page.waitForFunction(() => !document.querySelector("[data-grade]"));
      const viaKey = (await logOf(page)).find((e) => e.q === second.id);
      check("grade shortcuts still work after ticking a box", viaKey.grade === "good" && viaKey.score === 1, viaKey);
      await ctx.close();
    }

    // Settings: clearing sticks, the CLI reaches the browser, and a stale tab can't undo a change.
    {
      const [ctx, page] = await fresh();
      await page.goto(`${BASE}/app/`);
      await page.waitForSelector("#anchor");
      await page.fill("#anchor", "brush my teeth");
      await page.press("#anchor", "Tab");
      await page.reload();
      await page.waitForSelector("#anchor");
      check("the anchor is saved", (await page.inputValue("#anchor")) === "brush my teeth");
      await page.fill("#anchor", "");
      await page.press("#anchor", "Tab");
      await page.reload();
      await page.waitForSelector("#anchor");
      check("the anchor can be cleared", (await page.inputValue("#anchor")) === "");

      await new Promise((r) => setTimeout(r, 1100)); // settings timestamps have one-second resolution
      const changed = il("settings", ID, "--minimum", "3", "--anchor", "from the cli");
      check("il.py settings", changed.status === 0, changed);
      await page.reload();
      await page.waitForSelector("#anchor");
      check("il.py settings reach a browser with its own copy", /Answer 3 cards/.test(await page.innerText("body")) && (await page.inputValue("#anchor")) === "from the cli");
      removeFile();

      // A change to the anchor alone travels through an export, with nothing else to carry it.
      const [ctx3, solo] = await fresh({ acceptDownloads: true });
      await solo.goto(`${BASE}/app/`);
      await solo.waitForSelector("#anchor");
      await solo.fill("#anchor", "only the anchor changed");
      await solo.press("#anchor", "Tab");
      await openSettings(solo);
      const [dl] = await Promise.all([solo.waitForEvent("download"), solo.click("text=Export progress")]);
      const soloPath = path.join(SITE, "solo.json");
      await dl.saveAs(soloPath);
      il("import", ID, soloPath);
      check("an anchor changed on its own reaches the CLI", /only the anchor changed/.test(il("settings", ID).stdout), il("settings", ID).stdout);
      removeFile();
      await ctx3.close();

      const other = track(await ctx.newPage(), errors);
      await other.goto(`${BASE}/app/#/d/${ID}`);
      await other.waitForSelector("#anchor");
      await new Promise((r) => setTimeout(r, 1100));
      await openSettings(page);
      await page.fill('[data-setting="minimum"]', "2");
      await page.press('[data-setting="minimum"]', "Tab");
      await page.waitForSelector("a.btn.primary");
      await other.click("a.btn.primary");
      await other.waitForSelector(".option");
      await other.locator(".option").first().click();
      await other.waitForSelector(".banner");
      check("a stale tab can't undo a newer settings change", (await progressOf(other)).settings.minimum === 2, (await progressOf(other)).settings);
      await ctx.close();
    }

    // A gap can be closed right after another edit swapped the progress object.
    {
      const [ctx, page] = await fresh();
      await seed(page, { settings: { minimum: 1, new_per_day: 5, anchor: "" }, gaps: [{ at: `${weekAgo}T09:00:00`, text: "why?" }] });
      await page.fill("#anchor", "typed, not yet saved");
      await page.click(".gap-item button"); // blurring the field saves it first
      await page.waitForFunction(() => !/Gaps \(/.test(document.body.innerText));
      const after = await progressOf(page);
      check("closing a gap right after another edit sticks", after.gaps[0].closed === true, after.gaps);
      check("and the other edit is kept too", after.settings.anchor === "typed, not yet saved");
      await ctx.close();
    }

    // Running out of cards before the minimum is a full day.
    {
      const [ctx, page] = await fresh();
      await seed(page, { settings: { minimum: 3, new_per_day: 0, anchor: "" }, log: [{ at: `${weekAgo}T09:00:00`, q: "retrieval-pretest", grade: "again", score: 0, pretest: true, via: "app" }] });
      check("the button only promises what's available", /Answer one card/.test(await page.innerText("a.btn.primary")), await page.innerText("a.btn.primary"));
      await page.click("a.btn.primary");
      await page.waitForSelector(".option");
      await clickOption(page, true);
      await page.click('[data-conf="think"]');
      await page.waitForSelector(".banner");
      await page.click("[data-primary]");
      await page.waitForSelector(".yes");
      check("running out of cards still celebrates", /That's everything for today/.test(await page.innerText("body")));
      check("with nothing left, the only choice is Done", /Done/.test(await page.innerText("[data-primary]")) && !(await page.isVisible("text=Keep going")));
      await page.click("[data-primary]");
      await page.waitForSelector(".title");
      check("Done leads to the summary", /Next up/.test(await page.innerText("body")));
      await page.click("[data-primary]");
      await page.waitForSelector(".pill");
      check("today counts on the deck page", /Today counts/.test(await page.innerText("body")));
      await ctx.close();
    }

    // Chat answers reach an open tab without a reload.
    {
      const [ctx, page] = await fresh();
      await page.goto(`${BASE}/app/`);
      await page.waitForSelector("a.btn.primary");
      il("record", ID, "retrieval-pretest", "good", "--conf", "know");
      await page.click("text=← All decks");
      await page.waitForSelector(".deck-row");
      check("navigating picks up answers from chat", /Today counts/.test(await page.innerText(".deck-row")), await page.innerText(".deck-row"));
      removeFile();
      await ctx.close();

      const [ctx2, tab] = await fresh();
      await tab.goto(`${BASE}/app/`);
      await tab.waitForSelector("a.btn.primary");
      await tab.evaluate(() => window.scrollTo(0, 300));
      il("record", ID, "retrieval-pretest", "good", "--conf", "know");
      await tab.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
      await tab.waitForSelector(".pill");
      check("coming back to the tab picks up answers from chat", /Today counts/.test(await tab.innerText("body")));
      check("and keeps your place", (await tab.evaluate(() => window.scrollY)) === 300);

      // ...but never yanks a study session out from under you.
      await tab.click("a.btn:has-text('Bonus reps')");
      await tab.waitForSelector(".prompt, .note");
      // A rebuilt screen would look identical but lose whatever they've typed, so mark this one.
      await tab.evaluate(() => { document.querySelector("#app > *").dataset.mark = "same"; });
      await tab.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
      await tab.waitForTimeout(300);
      check("coming back mid-session leaves the screen alone", (await tab.evaluate(() => document.querySelector("#app > *").dataset.mark)) === "same");
      removeFile();
      await ctx2.close();
    }

    // Bad data can't break a deck.
    {
      const [ctx, page] = await fresh();
      await seed(page, { settings: { minimum: 1, new_per_day: 5, anchor: "" }, log: [{ at: "2026-13-45T00:00:00", q: "retrieval-why", grade: "good" }, { at: "garbage", q: 5, grade: "nope" }] });
      check("bad rows in browser storage don't break the deck", /Answer one card/.test(await page.innerText("body")));
      await openSettings(page);
      const bad = path.join(SITE, "bad-rows.json");
      fs.writeFileSync(bad, JSON.stringify({ deck: ID, settings: [1], feynman: [1], log: [
        { at: "2026-13-45T00:00:00", q: "retrieval-why", grade: "good" },
        { at: "2020-01-01T09:00:00", q: "retrieval-why", grade: "good", score: 1.0 },
      ] }));
      await page.locator(".panel input[type=file]").first().setInputFiles(bad);
      await page.waitForFunction(() => /Merged 1 new answer\. Skipped 1 malformed row\./.test(document.getElementById("toast").textContent));
      check("an import reports what it skipped", true);
      check("the deck still works afterwards", (await page.$("a.btn.primary")) !== null);

      // And a bad file from the repo side is left out too.
      fs.writeFileSync(path.join(SITE, "projects", ID, "progress.json"), JSON.stringify({ deck: ID, log: [{ at: "2026-13-45T00:00:00", q: "retrieval-why", grade: "good" }], feynman: "x", settings: "x" }));
      await page.reload();
      await page.waitForSelector("#anchor");
      check("a bad progress.json doesn't break the app", (await page.textContent("h1")) === "Learning How to Learn");
      fs.writeFileSync(path.join(SITE, "projects", ID, "progress.json"), "{not json");
      await page.reload();
      await page.waitForSelector("#anchor");
      check("an unparseable progress.json doesn't break the app", (await page.textContent("h1")) === "Learning How to Learn");
      removeFile();
      await ctx.close();
    }
  }

  section("K. A brand-new project, straight from il.py new");
  {
    const made = il("new", "my-topic", "--title", 'My "new" topic', "--kind", "topic");
    check("il.py new works", made.status === 0, made);
    const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } });
    const page = track(await ctx.newPage(), errors);
    await page.goto(`${BASE}/app/`);
    await page.waitForSelector(".deck-row");
    check("with two decks, the app starts on the list", (await page.$$(".deck-row")).length === 2);
    await page.click(".deck-row >> nth=1");
    await page.waitForSelector("#anchor");
    check("the title survives its quotes", (await page.textContent("h1")) === 'My "new" topic');
    check("an empty deck says what to do", /no cards yet/.test(await page.innerText("body")));
    check("an empty deck offers no study button", !(await page.$("a.btn.primary")));
    await shot(page, "19-empty-deck");
    await ctx.close();
  }

  check("no JS errors anywhere", errors.length === 0, errors.slice(0, 10));
  console.log(`\n${passed} checks passed, ${failures.length} failed`);
  for (const f of failures) console.log(" - " + f);
  return failures.length ? 1 : 0;
})().catch((e) => {
  console.error("\nThe test script itself failed:", e);
  for (const f of failures) console.log(" - " + f);
  return 2;
}).then(async (code) => {
  if (browser) await browser.close();
  if (server) server.kill();
  fs.rmSync(SITE, { recursive: true, force: true });
  process.exit(code);
});
