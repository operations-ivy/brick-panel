// CALENDAR and SHOPPING: Home Assistant's calendars and its shopping list.
//
// CALENDAR is a month grid (a tap picks a day) over an agenda from that day
// on; a tap on an event opens its details. SHOPPING is the list, needed
// first, a tap ticking an item off or back on (shown at once, until Home
// Assistant confirms or CONFIRM_MS pass). Both are open to anyone, as on
// LCARS. Long lists page with buttons rather than scroll: the stage takes
// every touch itself. Only transform and opacity animate.
"use strict";

const SHOP_ROWS = 8;
const CAL_WEEKDAYS = ["S", "M", "T", "W", "T", "F", "S"];

const calView = { month: 0, selected: null, detail: null };
const shopView = { page: 0, sent: {} }; // sent: uid -> { done, at }

function household() {
  return (state && state.household) || null;
}

// ---- CALENDAR ----

function calTone(e) {
  if (e.now || e.soon) return "now";
  return e.past ? "past" : "";
}

function calCell(d, selected, today) {
  const cls = [d.ours ? "" : "other", d.date === today ? "today" : "", d.date === selected ? "sel" : "", d.tone].join(" ");
  const dots = d.count ? `<span class="dots">${"<i></i>".repeat(Math.min(d.count, 3))}${d.count > 3 ? "<em>+</em>" : ""}</span>` : "";
  return `<button class="cal-day ${cls}" data-act="cal-day" data-arg="${d.date}"><span class="n">${d.day}</span>${dots}</button>`;
}

// The agenda: the selected day's events, then the days after, as far as
// `rows` lines go (a day's heading is a line).
function calAgenda(c, from, rows) {
  const days = Object.keys(c.days).filter((k) => k >= from).sort();
  const lines = [];
  if (!days.length || days[0] !== from) lines.push(`<div class="ag-empty">NOTHING ON ${esc(from === c.today ? "TODAY" : "THIS DAY")}</div>`);
  for (const day of days) {
    if (lines.length >= rows - 1) break;
    if (day !== from || lines.length) lines.push(`<div class="ag-day">${esc(c.names[day] || day)}</div>`);
    for (const e of c.days[day]) {
      if (lines.length >= rows) break;
      const soon = e.soon ? `<em>IN ${e.soon} MIN</em>` : e.now ? "<em>NOW</em>" : "";
      lines.push(`<button class="ag-event ${calTone(e)}" data-act="cal-event" data-arg="${esc(e.id)}">
        <span class="w">${esc(e.when)}</span><span class="t">${esc(e.summary)}</span>${soon}</button>`);
    }
  }
  return lines.slice(0, rows).join("");
}

function calDetail(el, c) {
  let pane = el.querySelector(".cal-detail");
  if (!pane) {
    pane = document.createElement("div");
    pane.className = "cal-detail";
    el.appendChild(pane);
  }
  const e = calView.detail && c && c.events[calView.detail];
  if (!e) {
    pane.classList.remove("open");
    return;
  }
  const where = e.where ? box("WHERE", `<div class="ev-text">${esc(e.where)}</div>`) : "";
  const notes = e.notes ? box("NOTES", `<div class="ev-text notes">${esc(e.notes).replace(/\n/g, "<br>")}</div>`) : "";
  paint(pane, `<div class="ev-title">${esc(e.summary)}</div>${box("WHEN", `<div class="ev-text">${esc(e.when)}</div>`)}
    ${where}${notes}<button class="key big ev-back" data-act="cal-close">BACK</button>`);
  if (!pane.classList.contains("open")) {
    pane.classList.add("open");
    pane.animate([{ opacity: 0, transform: "translate3d(0,24px,0)" }, { opacity: 1, transform: "translate3d(0,0,0)" }],
      { duration: 180, easing: "cubic-bezier(.2,.75,.2,1)" });
  }
}

function renderCalendar(el, st, back) {
  const shell = appShell(el, "calendar", back);
  const h = st.household;
  const c = h && h.calendar;
  if (!c || !c.available) {
    badge(shell.badge, "OFFLINE", "dim");
    setText(shell.kicker, "SCHEDULE // HOME ASSISTANT");
    paint(shell.body, box("STANDBY", `<div class="soon">${esc(c ? c.message : "No Home Assistant token in the panel's settings.")}</div>`));
    calDetail(el, null);
    return;
  }
  setText(shell.kicker, `SCHEDULE // ${c.today_name}`);
  if (c.stale_minutes !== null && c.stale_minutes !== undefined) badge(shell.badge, `${c.stale_minutes} MIN OLD`, "warn");
  else badge(shell.badge, c.today_left ? `${c.today_left} TODAY` : "CLEAR", c.next && (c.next.soon || c.next.now) ? "warn" : "ok");

  calView.month = Math.min(calView.month, c.months.length - 1);
  const m = c.months[calView.month];
  const selected = calView.selected || c.today;
  const head = `<div class="cal-head">
      <button class="key cal-step" data-act="cal-month" data-arg="-1" ${calView.month > 0 ? "" : "disabled"}><b class="tri left"></b></button>
      <button class="key cal-name" data-act="cal-today">${esc(m.name)}</button>
      <button class="key cal-step" data-act="cal-month" data-arg="1" ${calView.month < c.months.length - 1 ? "" : "disabled"}><b class="tri right"></b></button>
    </div>`;
  const weekdays = `<div class="cal-wd">${CAL_WEEKDAYS.map((d) => `<span>${d}</span>`).join("")}</div>`;
  const grid = `<div class="cal-grid w${m.weeks.length}">${m.weeks.flat().map((d) => calCell(d, selected, c.today)).join("")}</div>`;
  const rows = m.weeks.length === 6 ? 6 : 7;
  const tab = selected === c.today ? "TODAY" : (c.names[selected] || selected).toUpperCase();
  const agenda = `<div class="panel-box agenda"><span class="tab">FROM ${esc(tab)}</span><div class="body">${calAgenda(c, selected, rows)}</div></div>`;
  paint(shell.body, head + weekdays + grid + agenda);
  calDetail(el, c);
}

function calendarBillboard(st) {
  const c = st.household && st.household.calendar;
  if (!c || !c.available) return { text: "--", lit: false };
  const n = c.next;
  if (n && n.soon) return { text: `IN ${n.soon} MIN`, lit: true };
  if (n && n.now && !n.all_day) return { text: "NOW ON", lit: true };
  return { text: c.today_left ? `${c.today_left} TODAY` : "CLEAR", lit: false };
}

// ---- SHOPPING ----

function shopShown(item) {
  const sent = shopView.sent[item.uid];
  if (!sent) return item.done;
  if (item.done === sent.done || performance.now() - sent.at > CONFIRM_MS) {
    delete shopView.sent[item.uid];
    return item.done;
  }
  return sent.done;
}

function shopTick(uid) {
  const h = household();
  const item = h && h.shopping.items.find((i) => i.uid === uid);
  if (!item) return;
  const done = !shopShown(item);
  shopView.sent[uid] = { done, at: performance.now() };
  ask("/api/shopping", { uid, done });
  renderShopping(screens.shopping, state, backOf("shopping"));
}

function renderShopping(el, st, back) {
  const shell = appShell(el, "shopping", back);
  const h = st.household;
  const s = h && h.shopping;
  setText(shell.kicker, "SUPPLY MANIFEST // HOME ASSISTANT");
  if (!s || !s.available) {
    badge(shell.badge, "OFFLINE", "dim");
    paint(shell.body, box("STANDBY", `<div class="soon">${esc(s ? s.message : "No Home Assistant token in the panel's settings.")}</div>`));
    return;
  }
  const shown = s.items.map((i) => ({ ...i, done: shopShown(i) }));
  const needed = shown.filter((i) => !i.done).length;
  badge(shell.badge, s.link ? "OFFLINE" : needed ? `${needed} NEEDED` : "ALL SET", s.link ? "bad" : needed ? "warn" : "ok");
  const pages = Math.max(1, Math.ceil(shown.length / SHOP_ROWS));
  shopView.page = Math.min(shopView.page, pages - 1);
  const rows = shown.slice(shopView.page * SHOP_ROWS, (shopView.page + 1) * SHOP_ROWS).map((i) => {
    const flying = i.uid in shopView.sent ? "flying" : "";
    return `<button class="shop-item ${i.done ? "done" : ""} ${flying}" data-act="shop-tick" data-arg="${esc(i.uid)}">
      <i class="check"></i><span>${esc(i.summary)}</span></button>`;
  }).join("");
  const summary = `<div class="shop-sum"><span class="v">${needed}</span><span class="k">ITEM${needed === 1 ? "" : "S"} NEEDED<br>${shown.length - needed} IN THE CART</span></div>`;
  const empty = shown.length ? "" : box("EMPTY", `<div class="soon">Nothing on the list. Add items from the Home Assistant app.</div>`);
  const pager = pages > 1 ? `<div class="pager">
      <button class="key cal-step" data-act="shop-page" data-arg="-1" ${shopView.page > 0 ? "" : "disabled"}><b class="tri up"></b></button>
      <span>PAGE ${shopView.page + 1}/${pages}</span>
      <button class="key cal-step" data-act="shop-page" data-arg="1" ${shopView.page < pages - 1 ? "" : "disabled"}><b class="tri down"></b></button></div>` : "";
  paint(shell.body, summary + empty + `<div class="shop-list">${rows}</div>` + pager);
}

function shoppingBillboard(st) {
  const s = st.household && st.household.shopping;
  if (!s || !s.available) return { text: "--", lit: false };
  return { text: s.needed ? `${s.needed} NEEDED` : "ALL SET", lit: false };
}

// ---- Actions and leaving ----

Object.assign(ACTIONS, {
  "cal-day": (date) => {
    calView.selected = date;
    renderCalendar(screens.calendar, state, backOf("calendar"));
  },
  "cal-month": (delta) => {
    const c = household() && household().calendar;
    if (!c || !c.available) return;
    calView.month = Math.max(0, Math.min(c.months.length - 1, calView.month + Number(delta)));
    const key = c.months[calView.month].key;
    calView.selected = calView.month === 0 ? null : `${key}-01`;
    renderCalendar(screens.calendar, state, backOf("calendar"));
  },
  "cal-today": () => {
    calView.month = 0;
    calView.selected = null;
    renderCalendar(screens.calendar, state, backOf("calendar"));
  },
  "cal-event": (id) => {
    calView.detail = id;
    renderCalendar(screens.calendar, state, backOf("calendar"));
  },
  "cal-close": () => {
    calView.detail = null;
    const pane = screens.calendar.querySelector(".cal-detail");
    if (pane) {
      pane.animate([{ opacity: 1, transform: "translate3d(0,0,0)" }, { opacity: 0, transform: "translate3d(0,24px,0)" }],
        { duration: 140, easing: "ease-in" }).finished.then(() => { if (!calView.detail) pane.classList.remove("open"); });
    }
  },
  "shop-tick": (uid) => shopTick(uid),
  "shop-page": (delta) => {
    shopView.page = Math.max(0, shopView.page + Number(delta));
    renderShopping(screens.shopping, state, backOf("shopping"));
  },
});

// Leaving CALENDAR or SHOPPING: back to today, the first page, no details.
function leaveHousehold(name) {
  if (name === "calendar") {
    Object.assign(calView, { month: 0, selected: null, detail: null });
    const pane = screens.calendar.querySelector(".cal-detail");
    if (pane) pane.classList.remove("open");
  }
  if (name === "shopping") shopView.page = 0;
  renderHousehold(); // covered now, so it's ready the next time it opens
}

function renderHousehold() {
  if (!state) return;
  renderCalendar(screens.calendar, state, backOf("calendar"));
  renderShopping(screens.shopping, state, backOf("shopping"));
}
