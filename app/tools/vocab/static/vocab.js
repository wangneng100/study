// Vocabulary notebook page. All data and scheduling live on the server;
// this file fetches /vocab/api/words, draws the page, and posts what the user does.
(() => {
  "use strict";

  const API = document.getElementById("vocab").dataset.api;
  const MIN = 60e3, HOUR = 3600e3, DAY = 86400e3;
  let STEPS = [];          // review schedule, sent by the server
  let DONE = 8;            // stage at which a word is mastered

  const state = {
    words: [], loaded: false, note: "", translator: null,
    filter: "all", q: "", open: null, confirmDel: null,
    currentId: null, revealed: false, busy: false, cardError: "",
    adding: false, lastAdded: [], speakKey: null, working: null,
    suggestions: [],
  };
  let pendingFocus = null;
  let lastPointer = 0;

  const $ = (id) => document.getElementById(id);

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "disabled") el.disabled = true;
        else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? "" : v);
      }
    }
    for (const kid of kids.flat(2)) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const fill = (el, ...kids) => el.replaceChildren(...kids.flat(2).filter((k) => k != null && k !== false));

  async function api(method, path, body) {
    let res;
    try {
      res = await fetch(path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : {},
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw Object.assign(new Error("连不上本地服务，确认 python3 run.py 还在运行。"), { offline: true });
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(data.error || "没成功，请再试一次。"), { data });
    return data;
  }

  const isDue = (w, now) => w.stage < DONE && w.dueAt <= now;
  const dueList = (now) => state.words.filter((w) => isDue(w, now)).sort((a, b) => a.dueAt - b.dueAt);
  const putWord = (w) => { state.words = state.words.some((x) => x.id === w.id) ? state.words.map((x) => (x.id === w.id ? w : x)) : [w, ...state.words]; };

  function until(ts, now) {
    const d = ts - now;
    if (d <= 0) return "现在";
    if (d < HOUR) return Math.max(1, Math.round(d / MIN)) + " 分钟后";
    if (d < DAY) return Math.round(d / HOUR) + " 小时后";
    return Math.round(d / DAY) + " 天后";
  }
  const dateFmt = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const dayFmt = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" });

  /* ---------- rendering ---------- */

  function render() {
    const active = document.activeElement;
    const want = pendingFocus || (active && active.dataset ? active.dataset.fk : null);
    pendingFocus = null;
    const now = Date.now();
    renderHeader(now);
    renderSuggestions();
    renderAdded();
    renderStudy();
    renderCard(now);
    renderDays(now);
    renderChips(now);
    renderList(now);
    if (want) {
      const el = document.querySelector('[data-fk="' + want.replace(/["\\]/g, "") + '"]');
      if (el) el.focus({ preventScroll: true });
    }
  }

  function renderHeader(now) {
    const due = dueList(now).length;
    const mastered = state.words.filter((w) => w.stage >= DONE).length;
    $("stats").textContent = state.loaded ? `共 ${state.words.length} 词 · 已掌握 ${mastered}` : "";
    const pill = $("due-pill");
    pill.hidden = due === 0;
    pill.textContent = `${due} 个词该复习了`;
    $("note").hidden = !state.note;
    $("note").textContent = state.note;
    const t = state.translator;
    $("translator").textContent = !t ? ""
      : t.active === "onemin" ? "翻译和例句由 1min.ai 生成。"
      : t.hasOneMinKey ? "当前设置为只用 Google 翻译。"
      : "当前用 Google 翻译，例句来自词典，有些词没有。在 .env 里填上 ONEMIN_API_KEY 后会改用 1min.ai 生成释义和例句。";
  }

  // "Start studying": pick how many words, then go to the study page.
  function renderStudy() {
    const total = state.words.length;
    $("study-btn").disabled = total === 0;
    $("study-hint").textContent = total ? "不用等复习时间，现在就学一组。" : "先记下几个单词，才能开始学习。";
    if (!total) $("study-pick").hidden = true;
    const base = $("vocab").dataset.study;
    const counts = [5, 10, 20, 50].filter((n) => n < total);
    fill($("study-counts"),
      counts.map((n) => h("a", { class: "chip", href: `${base}?n=${n}` }, `${n} 个`)),
      h("a", { class: "chip", href: `${base}?n=${total}` }, `全部 ${total} 个`));
  }

  function speakBtn(w, text, key) {
    if (!window.speechSynthesis) return null;
    const on = state.speakKey === key;
    return h("button", {
      type: "button", class: "btn ghost", "data-fk": "say:" + key,
      "aria-label": on ? "停止朗读" : "朗读 " + text,
      onclick: () => (on ? stopSpeaking() : speak(w, text, key)),
    }, on ? "停止" : "朗读");
  }

  function entryBody(w, key) {
    return [
      h("div", { class: "entry-top" },
        h("span", { class: "entry-word" }, w.word),
        w.phonetic && h("span", { class: "phon" }, w.phonetic),
        speakBtn(w, w.word, key)),
      h("p", null, w.pos && h("span", { class: "pos" }, w.pos + " "), w.meaning),
      w.example && h("p", { class: "ex" }, w.example),
      w.exampleZh && h("p", { class: "ex-zh" }, w.exampleZh),
    ];
  }

  function renderAdded() {
    const items = state.lastAdded.map((id) => state.words.find((w) => w.id === id)).filter(Boolean);
    if (!items.length) { fill($("added")); return; }
    fill($("added"),
      h("div", { class: "added-head" },
        h("h3", { class: "mini-h" }, "刚记下的"),
        h("button", { type: "button", class: "btn ghost", "data-fk": "added-close", onclick: () => { state.lastAdded = []; render(); } }, "收起")),
      items.map((w) => h("div", { class: "entry" }, entryBody(w, "new:" + w.id))));
  }

  function renderCard(now) {
    const card = $("card");
    if (!state.loaded) { fill(card, h("div", { class: "rest" }, h("h3", null, "正在打开单词本…"))); return; }
    if (!state.words.length) {
      fill(card, h("div", { class: "rest" },
        h("h3", null, "单词本还是空的"),
        h("p", null, "在上面输入第一个不会的单词。记下 5 分钟后安排第一次复习，之后按 30 分钟、12 小时、1 天、2 天、4 天、7 天、15 天的间隔再复习，一共 8 次。")));
      return;
    }
    const due = dueList(now);
    let w = state.words.find((x) => x.id === state.currentId && x.stage < DONE);
    if (!w || (!isDue(w, now) && !state.busy)) {
      w = due[0] || null;
      if (!w || w.id !== state.currentId) { state.revealed = false; state.cardError = ""; }
      state.currentId = w ? w.id : null;
    }
    if (!w) {
      const next = state.words.filter((x) => x.stage < DONE).sort((a, b) => a.dueAt - b.dueAt)[0];
      fill(card, h("div", { class: "rest" },
        h("h3", null, next ? "现在没有要复习的词" : "所有单词都已掌握"),
        next
          ? h("p", null, "下一个是 ", h("span", { class: "next" }, next.word), "，" + until(next.dueAt, now) + "（" + dateFmt.format(next.dueAt) + "）。")
          : h("p", null, "8 次复习全部完成。继续添加新的单词吧。")));
      return;
    }
    const s = w.stage;
    const grade = (cls, key, title, sub, kind) => h("button", {
      type: "button", class: "grade " + cls, "data-fk": key, disabled: state.busy, onclick: () => gradeWord(w, kind),
    }, h("b", null, title), h("small", null, sub));
    fill(card,
      h("div", { class: "card-meta" },
        h("span", null, `还剩 ${due.length} 个`),
        h("span", null, `第 ${s + 1} / ${DONE} 次复习`)),
      h("div", { class: "ruled" + (w.word.length > 16 ? " long" : "") },
        h("div", { class: "lines", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i")),
        h("div", { class: "w" }, w.word)),
      h("div", { class: "card-sub" },
        w.phonetic && h("span", { class: "phon" }, w.phonetic),
        speakBtn(w, w.word, "card:" + w.id)),
      h("ol", { class: "steps", "aria-label": `第 ${s + 1} 次复习，共 ${DONE} 次` },
        STEPS.map((step, i) => h("li", { class: i < s ? "done" : i === s ? "now" : null }, step.short))),
      state.revealed
        ? [
            h("div", { class: "answer" },
              h("p", { class: "meaning" }, w.pos && h("span", { class: "pos" }, w.pos + " "), w.meaning),
              w.example && h("p", { class: "ex" }, w.example),
              w.exampleZh && h("p", { class: "ex-zh" }, w.exampleZh)),
            h("div", { class: "grades" },
              grade("forgot", "g1", "忘了", STEPS[0].label + "后重来", "forgot"),
              grade("fuzzy", "g2", "模糊", STEPS[s].label + "后再看", "fuzzy"),
              grade("got", "g3", "记得", s + 1 < DONE ? STEPS[s + 1].label + "后复习" : "完成，标为已掌握", "got")),
            h("p", { class: "keys" }, "键盘：1 忘了 · 2 模糊 · 3 记得"),
          ]
        : [
            h("button", { type: "button", class: "btn primary reveal", "data-fk": "reveal", onclick: reveal }, "看释义"),
            h("p", { class: "keys" }, "先在心里回忆意思，再按空格看释义"),
          ],
      state.cardError && h("p", { class: "status err", role: "alert" }, state.cardError));
  }

  function renderDays(now) {
    const start = new Date(now); start.setHours(0, 0, 0, 0);
    const counts = Array(7).fill(0);
    for (const w of state.words) {
      if (w.stage >= DONE) continue;
      const i = Math.max(0, Math.floor((w.dueAt - start.getTime()) / DAY));
      if (i < 7) counts[i]++;
    }
    const max = Math.max(1, ...counts);
    const names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
    fill($("days"), counts.map((n, i) => {
      const d = new Date(start.getTime() + i * DAY);
      const bar = h("span", { class: "bar" });
      bar.style.height = Math.round((n / max) * 100) + "%";
      return h("li", { class: i === 0 ? "today" : null },
        h("span", { class: "n" }, n),
        h("span", { class: "track", "aria-hidden": "true" }, bar),
        h("span", null, i === 0 ? "今天" : i === 1 ? "明天" : names[d.getDay()]));
    }));
  }

  const FILTERS = [
    ["all", "全部", () => true],
    ["due", "该复习", (w, now) => isDue(w, now)],
    ["learning", "学习中", (w, now) => w.stage < DONE && !isDue(w, now)],
    ["done", "已掌握", (w) => w.stage >= DONE],
  ];

  function renderChips(now) {
    fill($("chips"), FILTERS.map(([key, label, test]) =>
      h("button", {
        type: "button", class: "chip", "data-fk": "chip:" + key, "aria-pressed": String(state.filter === key),
        onclick: () => { state.filter = key; render(); },
      }, `${label} ${state.words.filter((w) => test(w, now)).length}`)));
  }

  function renderList(now) {
    const list = $("list");
    if (!state.loaded) { fill(list); return; }
    const test = FILTERS.find((f) => f[0] === state.filter)[2];
    const q = state.q.trim().toLowerCase();
    const rows = state.words
      .filter((w) => test(w, now) && (!q || w.word.toLowerCase().includes(q) || w.meaning.toLowerCase().includes(q)))
      .sort((a, b) => b.addedAt - a.addedAt || b.id - a.id);
    if (!rows.length) {
      fill(list, h("li", { class: "empty" }, state.words.length ? "没有符合条件的单词。" : "记下的单词会按添加时间列在这里。"));
      return;
    }
    fill(list, rows.map((w) => {
      const open = state.open === w.id;
      const done = w.stage >= DONE, due = isDue(w, now);
      const working = state.working === w.id;
      return h("li", null,
        h("button", {
          type: "button", class: "row", "data-fk": "row:" + w.id, "aria-expanded": String(open),
          onclick: () => { state.open = open ? null : w.id; state.confirmDel = null; render(); },
        },
          h("span", { class: "head" }, h("span", { class: "word" }, w.word), w.pos && h("span", { class: "pos" }, w.pos)),
          h("span", { class: "m" }, w.meaning),
          h("span", { class: "prog" + (done ? " done" : due ? " due" : "") },
            h("span", { class: "dots", role: "img", "aria-label": `已完成 ${w.stage} / ${DONE} 次复习` },
              STEPS.map((_, i) => h("i", { class: i < w.stage ? "on" : null }))),
            h("span", null, done ? "已掌握" : due ? "该复习了" : until(w.dueAt, now)))),
        open && h("div", { class: "detail" },
          w.phonetic && h("p", { class: "phon" }, w.phonetic),
          w.example && h("p", { class: "ex" }, w.example),
          w.exampleZh && h("p", { class: "ex-zh" }, w.exampleZh),
          h("p", { class: "facts" },
            `${dayFmt.format(w.addedAt)} 记下 · 复习 ${w.reviews} 次 · 忘记 ${w.lapses} 次` +
            (done ? "" : ` · 下次复习 ${dateFmt.format(w.dueAt)}`)),
          h("div", { class: "acts" },
            speakBtn(w, w.word, "list:" + w.id),
            h("button", { type: "button", class: "btn", "data-fk": "refresh:" + w.id, disabled: working, onclick: () => rowAction(w, "refresh") }, working ? "正在翻译…" : "重新翻译"),
            h("button", { type: "button", class: "btn", "data-fk": "reset:" + w.id, disabled: working, onclick: () => rowAction(w, "reset") }, "从头再学"),
            h("button", { type: "button", class: "btn danger", "data-fk": "del:" + w.id, onclick: () => deleteWord(w) },
              state.confirmDel === w.id ? "再点一次确认删除" : "删除"))));
    }));
  }

  /* ---------- actions ---------- */

  function reveal() {
    if (!state.currentId || state.revealed) return;
    state.revealed = true;
    pendingFocus = "g3";
    render();
  }

  async function gradeWord(w, kind) {
    if (state.busy) return;
    state.busy = true; state.cardError = ""; render();
    try {
      putWord((await api("POST", `${API}/${w.id}/review`, { grade: kind })).word);
      state.currentId = null; state.revealed = false;
      pendingFocus = "reveal";
    } catch (e) {
      state.cardError = e.message;
    }
    state.busy = false; render();
  }

  async function rowAction(w, action) {
    state.working = w.id; render();
    try { putWord((await api("POST", `${API}/${w.id}/${action}`)).word); setStatus("", ""); }
    catch (e) { setStatus("err", e.message); }
    state.working = null; render();
  }

  async function deleteWord(w) {
    if (state.confirmDel !== w.id) { state.confirmDel = w.id; render(); return; }
    state.confirmDel = null; state.open = null;
    try {
      await api("DELETE", `${API}/${w.id}`);
      state.words = state.words.filter((x) => x.id !== w.id);
    } catch (e) { setStatus("err", e.message); }
    render();
  }

  function speak(w, text, key) {
    const synth = window.speechSynthesis;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = w.lang || "en";
    const end = () => { if (state.speakKey === key) { state.speakKey = null; render(); } };
    u.onend = end; u.onerror = end;
    state.speakKey = key; render();
    synth.speak(u);
  }
  function stopSpeaking() { window.speechSynthesis.cancel(); state.speakKey = null; render(); }

  function setStatus(kind, text) {
    const el = $("add-status");
    el.className = "status" + (kind ? " " + kind : "");
    el.textContent = text || "";
  }

  function renderSuggestions() {
    const box = $("suggestions");
    if (!box) return;
    if (!state.suggestions || !state.suggestions.length) { fill(box); return; }
    fill(box, state.suggestions.map((s, idx) => {
      const entry = s.entry || {};
      return h("div", { class: "suggest-card", role: "alert" },
        h("div", { class: "suggest-head" },
          h("p", { class: "suggest-title" },
            "你输入的是 ",
            h("span", { class: "suggest-bad" }, s.original),
            "，是否是想输入 ",
            h("strong", { class: "suggest-good" }, s.suggested),
            "？"
          ),
          entry.meaning && h("p", { class: "suggest-preview" },
            entry.phonetic && h("span", { class: "phon" }, entry.phonetic + " "),
            entry.pos && h("span", { class: "pos" }, entry.pos + " "),
            entry.meaning
          )
        ),
        h("div", { class: "suggest-acts" },
          h("button", {
            type: "button",
            class: "btn primary",
            "data-fk": "accept-sug:" + idx,
            onclick: () => acceptSuggestion(s),
          }, `是，记下 ${s.suggested}`),
          h("button", {
            type: "button",
            class: "btn ghost",
            onclick: () => forceOriginal(s),
          }, `否，坚持记 ${s.original}`),
          h("button", {
            type: "button",
            class: "btn ghost",
            style: "color: var(--ink-3); margin-left: auto;",
            onclick: () => dismissSuggestion(s),
          }, "取消")
        )
      );
    }));
  }

  async function acceptSuggestion(s) {
    state.suggestions = state.suggestions.filter((x) => x !== s);
    renderSuggestions();
    await addWords({ entry: s.entry });
    $("add-input").value = "";
  }

  async function forceOriginal(s) {
    state.suggestions = state.suggestions.filter((x) => x !== s);
    renderSuggestions();
    await addWords({ text: s.original, force: true });
    $("add-input").value = "";
  }

  function dismissSuggestion(s) {
    state.suggestions = state.suggestions.filter((x) => x !== s);
    renderSuggestions();
  }

  async function addWords(payload) {
    if (state.adding) return;
    const input = $("add-input"), meaningEl = $("add-meaning");
    let body;
    if (payload) {
      body = payload;
    } else {
      const text = input.value.trim();
      const meaning = meaningEl.hidden ? "" : meaningEl.value.trim();
      if (!text) { setStatus("err", "先输入一个单词。"); return; }
      body = meaning ? { word: text, meaning } : { text };
    }
    state.adding = true; $("add-btn").disabled = true;
    setStatus("", "正在翻译…");
    try {
      const d = await api("POST", API, body);
      d.added.forEach(putWord);
      state.lastAdded = [...d.added, ...d.existing].map((w) => w.id);
      if (d.suggestions && d.suggestions.length) {
        state.suggestions = d.suggestions;
      } else if (!payload) {
        state.suggestions = [];
      }
      if (!payload) {
        input.value = d.failed.join("\n");
        meaningEl.value = ""; meaningEl.hidden = true;
      }
      const parts = [];
      if (d.added.length) parts.push(`已记下 ${d.added.length} 个词，${STEPS[0].label}后第一次复习。`);
      if (d.existing.length) parts.push(`${d.existing.length} 个已经在单词本里。`);
      if (d.failed.length) parts.push(`${d.failed.length} 个没查到，留在输入框里了。`);
      if (d.notice) parts.push(d.notice);
      if (d.suggestions && d.suggestions.length) parts.push("疑似拼写有误，请确认建议。");
      setStatus(d.failed.length || d.notice ? "err" : "ok", parts.join(" "));
    } catch (e) {
      if (e.data && e.data.manual) {
        meaningEl.hidden = false;
        setStatus("err", e.message + " 可以一次写一个词，在下面自己填释义。");
      } else setStatus("err", e.message);
    }
    state.adding = false; $("add-btn").disabled = false; render();
  }

  async function load() {
    try {
      const d = await api("GET", API);
      STEPS = d.steps; DONE = STEPS.length;
      state.words = d.words; state.translator = d.translator;
      state.loaded = true; state.note = "";
    } catch (e) {
      state.note = e.message;
    }
    render();
  }

  /* ---------- wiring ---------- */

  $("add-form").addEventListener("submit", (e) => { e.preventDefault(); addWords(); });
  $("add-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); addWords(); }
  });
  $("study-btn").addEventListener("click", () => {
    const pick = $("study-pick");
    pick.hidden = !pick.hidden;
    $("study-btn").setAttribute("aria-expanded", String(!pick.hidden));
  });
  $("q").addEventListener("input", (e) => { state.q = e.target.value; renderList(Date.now()); });
  $("due-pill").addEventListener("click", () => {
    $("review").scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });
  document.addEventListener("pointerdown", () => { lastPointer = Date.now(); }, true);
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;
    const tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "BUTTON" || tag === "SELECT") return;
    const w = state.words.find((x) => x.id === state.currentId);
    if (!w) return;
    if (!state.revealed && (e.key === " " || e.key === "Enter")) { e.preventDefault(); reveal(); }
    else if (state.revealed && ["1", "2", "3"].includes(e.key)) {
      e.preventDefault(); gradeWord(w, { 1: "forgot", 2: "fuzzy", 3: "got" }[e.key]);
    }
  });
  // Due times move with the clock: redraw twice a minute, and re-read when the tab is shown again.
  setInterval(() => { if (state.loaded && Date.now() - lastPointer > 1500 && !state.busy) render(); }, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !state.busy && !state.adding) load(); });

  render();
  load();
})();
