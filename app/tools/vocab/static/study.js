// On-demand study session: /vocab/study?n=10
// The server sends each word with several quiz questions. The page asks one
// question per word and brings a word back, with a different question, until
// it is answered correctly.
(() => {
  "use strict";

  const cfg = document.getElementById("vocab").dataset;
  const count = Math.max(1, parseInt(new URLSearchParams(location.search).get("n"), 10) || 10);
  const $ = (id) => document.getElementById(id);
  const canSpeak = !!window.speechSynthesis;

  const TYPE_NAMES = {
    choose_meaning: "选出意思", choose_word: "选出单词", spell: "看意思拼写", cloze: "例句填空", listen: "听写",
  };
  const VERDICTS = { got: "答对了", fuzzy: "差一点", forgot: "答错了" };

  const state = {
    loaded: false, error: "",
    queue: [],            // items {word, questions, turn} still to answer correctly
    total: 0, cleared: 0,
    first: {},            // word id -> grade of the first answer, the one the server records
    // The question on screen:
    answered: false, grade: null, picked: null, typed: "", hints: 0, usedHint: false,
    busy: false, cardError: "",
  };
  let pendingFocus = null;

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "disabled") el.disabled = true;
        else if (k === "value") el.value = v;
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
      throw new Error("连不上本地服务，确认 python3 run.py 还在运行。");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "没成功，请再试一次。");
    return data;
  }

  const current = () => state.queue[0] || null;
  const question = (item) => item.questions[item.turn % item.questions.length];

  function say(w) {
    if (!canSpeak) return;
    const synth = window.speechSynthesis;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(w.word);
    u.lang = w.lang || "en";
    synth.speak(u);
  }
  const sayBtn = (w, label, cls) => canSpeak && h("button", { type: "button", class: cls || "btn ghost", "data-fk": "say", onclick: () => say(w) }, label || "朗读");

  /* ---------- checking typed answers ---------- */

  const norm = (s) => s.normalize("NFKC").trim().toLowerCase().replace(/\s+/g, " ");

  function editDistance(a, b) {
    let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const row = [i];
      for (let j = 1; j <= b.length; j++) {
        row[j] = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
      prev = row;
    }
    return prev[b.length];
  }

  function gradeTyped(typed, accept) {
    const t = norm(typed);
    if (!t) return "forgot";
    const targets = accept.map(norm);
    if (targets.includes(t)) return state.usedHint ? "fuzzy" : "got";
    // One letter off in a word of five or more letters counts as "almost".
    return targets.some((a) => a.length >= 5 && editDistance(t, a) === 1) ? "fuzzy" : "forgot";
  }

  // "g _ _ _ _" with `shown` letters revealed; spaces in phrases stay visible.
  function hintText(answer, shown) {
    let left = shown;
    return Array.from(answer).map((ch) => (ch === " " ? " " : left-- > 0 ? ch : "_")).join(" ");
  }

  /* ---------- rendering ---------- */

  function wordEntry(w) {
    return h("div", { class: "answer" },
      h("div", { class: "entry-top" },
        h("span", { class: "entry-word" }, w.word),
        w.phonetic && h("span", { class: "phon" }, w.phonetic),
        sayBtn(w)),
      h("p", { class: "meaning" }, w.pos && h("span", { class: "pos" }, w.pos + " "), w.meaning),
      w.example && h("p", { class: "ex" }, w.example),
      w.exampleZh && h("p", { class: "ex-zh" }, w.exampleZh));
  }

  function choiceBody(item, q) {
    const w = item.word;
    const asWord = q.type === "choose_word";
    return [
      asWord
        ? h("p", { class: "q-prompt" }, w.pos && h("span", { class: "pos" }, w.pos + " "), w.meaning)
        : [
            h("div", { class: "ruled" + (w.word.length > 16 ? " long" : "") },
              h("div", { class: "lines", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i")),
              h("div", { class: "w" }, w.word)),
            h("div", { class: "card-sub" }, w.phonetic && h("span", { class: "phon" }, w.phonetic), sayBtn(w)),
          ],
      h("div", { class: "options" }, q.options.map((text, i) => {
        const cls = !state.answered ? "" : i === q.answer ? " right" : i === state.picked ? " wrong" : "";
        return h("button", {
          type: "button", class: "option" + (asWord ? " word" : "") + cls, "data-fk": "opt" + i,
          disabled: state.answered || state.busy, onclick: () => submit(i === q.answer ? "got" : "forgot", i),
        }, h("span", { class: "k" }, i + 1), h("span", { class: "t" }, text));
      })),
      !state.answered && h("p", { class: "keys" }, `键盘：按 1–${q.options.length} 选择`),
    ];
  }

  function typedBody(item, q) {
    const w = item.word;
    const answer = q.accept[0];
    const prompt =
      q.type === "cloze" ? [h("p", { class: "q-prompt sentence" }, q.sentence), w.exampleZh && h("p", { class: "q-sub" }, w.exampleZh)]
      : q.type === "listen" ? [h("div", { class: "card-sub" }, sayBtn(w, "再听一遍", "btn"))]
      : [h("p", { class: "q-prompt" }, w.pos && h("span", { class: "pos" }, w.pos + " "), w.meaning)];
    return [
      prompt,
      h("form", { class: "type-row", onsubmit: (e) => { e.preventDefault(); if (!state.answered) submit(gradeTyped(state.typed, q.accept)); } },
        h("input", {
          type: "text", id: "typed", "data-fk": "typed", value: state.typed, disabled: state.answered || state.busy,
          autocomplete: "off", autocapitalize: "off", spellcheck: "false",
          "aria-label": q.type === "cloze" ? "填入空缺的单词" : "输入单词", placeholder: "输入单词，按回车确认",
          oninput: (e) => { state.typed = e.target.value; },
        }),
        !state.answered && h("button", { type: "submit", class: "btn primary", disabled: state.busy }, "确认")),
      !state.answered && h("div", { class: "type-acts" },
        h("span", { class: "hint" }, state.hints ? hintText(answer, state.hints) : ""),
        h("button", {
          type: "button", class: "btn", "data-fk": "hint", disabled: state.hints >= Math.ceil(Array.from(answer.replace(/ /g, "")).length / 2),
          onclick: () => { state.hints++; state.usedHint = true; pendingFocus = "typed"; render(); },
        }, state.hints ? "再提示一个字母" : "提示"),
        h("button", { type: "button", class: "btn", "data-fk": "giveup", disabled: state.busy, onclick: () => submit("forgot") }, "不知道")),
    ];
  }

  function render() {
    const active = document.activeElement;
    const want = pendingFocus || (active && active.dataset ? active.dataset.fk : null);
    pendingFocus = null;
    const card = $("card");

    $("bar").hidden = !state.total;
    $("bar-text").textContent = `已答对 ${state.cleared} / ${state.total}`;
    $("bar-fill").style.width = (state.total ? Math.round((state.cleared / state.total) * 100) : 0) + "%";

    const item = current();
    if (state.error) {
      fill(card, h("div", { class: "rest" }, h("h3", null, "打不开这一组"), h("p", null, state.error)));
    } else if (!state.loaded) {
      fill(card, h("div", { class: "rest" }, h("h3", null, "正在出题…")));
    } else if (!state.total) {
      fill(card, h("div", { class: "rest" },
        h("h3", null, "单词本还是空的"),
        h("p", null, "先回单词本记下几个单词，再来学习。"),
        h("div", { class: "end-acts" }, h("a", { class: "btn primary", href: cfg.home }, "回单词本"))));
    } else if (!item) {
      const tally = { got: 0, fuzzy: 0, forgot: 0 };
      Object.values(state.first).forEach((g) => { tally[g]++; });
      fill(card, h("div", { class: "rest" },
        h("h3", null, `这一组考完了，共 ${state.total} 个词`),
        h("p", null, "每个词第一次作答的结果："),
        h("div", { class: "tally" },
          h("span", { class: "got" }, `答对 ${tally.got}`),
          h("span", { class: "fuzzy" }, `差一点 ${tally.fuzzy}`),
          h("span", { class: "forgot" }, `答错 ${tally.forgot}`)),
        h("div", { class: "end-acts" },
          h("a", { class: "btn primary", href: `${cfg.study}?n=${count}`, "data-fk": "again" }, "再考一组"),
          h("a", { class: "btn", href: cfg.home }, "回单词本"))));
    } else {
      const q = question(item);
      const choice = q.type.startsWith("choose");
      fill(card,
        h("div", { class: "card-meta" },
          h("span", { class: "q-type" }, TYPE_NAMES[q.type]),
          h("span", null, (item.word.id in state.first ? "再考一次 · " : "") + `还剩 ${state.queue.length} 个词`)),
        choice ? choiceBody(item, q) : typedBody(item, q),
        state.answered && [
          h("p", { class: "verdict " + state.grade, role: "status" },
            VERDICTS[state.grade] + (state.grade === "fuzzy" ? (state.usedHint ? "：用了提示" : "：拼写差一个字母") : "") +
            (state.grade === "got" ? "" : "，这个词稍后换一种题再考。")),
          wordEntry(item.word),
          h("button", { type: "button", class: "btn primary next", "data-fk": "next", onclick: next }, state.queue.length > 1 || state.grade !== "got" ? "下一题" : "看结果"),
        ],
        state.cardError && h("p", { class: "status err", role: "alert" }, state.cardError));
    }
    if (want) {
      const el = document.querySelector('[data-fk="' + want + '"]');
      if (el && !el.disabled) el.focus({ preventScroll: true });
    }
  }

  /* ---------- flow ---------- */

  function show() {
    Object.assign(state, { answered: false, grade: null, picked: null, typed: "", hints: 0, usedHint: false, cardError: "" });
    const item = current();
    if (item) {
      const q = question(item);
      if (!q.type.startsWith("choose")) pendingFocus = "typed";
      if (q.type === "listen") say(item.word);
    } else {
      pendingFocus = "again";
    }
    render();
  }

  async function submit(grade, picked = null) {
    if (state.answered || state.busy) return;
    const item = current();
    // Only the first answer for a word is recorded; later attempts in the session are practice.
    if (!(item.word.id in state.first)) {
      state.busy = true; state.cardError = ""; render();
      try {
        await api("POST", `${cfg.api}/${item.word.id}/review`, { grade, study: true });
        state.first[item.word.id] = grade;
      } catch (e) {
        state.cardError = e.message;
        state.busy = false; render();
        return;
      }
      state.busy = false;
    }
    Object.assign(state, { answered: true, grade, picked });
    pendingFocus = "next";
    render();
  }

  function next() {
    const item = state.queue.shift();
    if (state.grade === "got") state.cleared++;
    else {
      item.turn++;                                                    // ask it another way next time
      state.queue.splice(Math.min(3, state.queue.length), 0, item);   // a few questions later
    }
    if (canSpeak) window.speechSynthesis.cancel();
    show();
  }

  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;
    const tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "A") return;
    const item = current();
    if (!item) return;
    if (state.answered) {
      if ((e.key === "Enter" || e.key === " ") && tag !== "BUTTON") { e.preventDefault(); next(); }
      return;
    }
    const q = question(item);
    if (q.type.startsWith("choose") && /^[1-9]$/.test(e.key) && +e.key <= q.options.length) {
      e.preventDefault();
      submit(+e.key - 1 === q.answer ? "got" : "forgot", +e.key - 1);
    }
  });

  (async () => {
    render();
    try {
      const d = await api("GET", `${cfg.batch}?n=${count}`);
      state.queue = d.items.map((item) => ({
        word: item.word,
        questions: item.questions.filter((q) => canSpeak || q.type !== "listen"),
        turn: 0,
      }));
      state.total = state.queue.length;
      state.loaded = true;
    } catch (e) {
      state.error = e.message;
      render();
      return;
    }
    show();
  })();
})();
