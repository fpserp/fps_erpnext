/*
 * FPS Live Feed (/fps-feed) -- page script.
 *
 * Renders the snapshot embedded by www/fps-feed.html (<script id="fps-feed-data">,
 * contract docs/live_feed/snapshot.schema.md) and keeps the page "live":
 *   - relative times ("2 h ago") from the item's `at` against the SERVER clock
 *     (meta.now + time elapsed since load), never the phone clock alone;
 *   - header "Updated 12:00 \u00B7 next 16:00" / "the 16:00 update is late",
 *     recomputed every minute with the same rules as feed_logic.py;
 *   - a check for a newer snapshot (GET fps_erpnext.api.feed.get_feed_meta) when
 *     the page becomes visible again, every check_every_seconds, and on a tap
 *     of the LIVE pill -> location.reload() when generated_at differs -- unless
 *     a sheet is open or the reader scrolled in the last 30 s: then a
 *     "New update - tap to refresh" toast waits for them;
 *   - the "building" state (first deploy): polls every building_every_seconds
 *     until a snapshot exists, or says the first build failed;
 *   - a bottom sheet for every item, chip and section header; "Open in ERPNext"
 *     only where the server set can_open (the route is absent otherwise);
 *   - a one-time iOS "Add to Home Screen" hint (dismissal kept in localStorage).
 *
 * SAFETY: every string from the snapshot is typed by people in ERPNext. It is
 * only ever set with textContent / setAttribute, never parsed as HTML, and a
 * link is made only from a desk path (/app/... or /desk/...).
 * No external requests; the only request is the same-origin GET above.
 * Reduced motion: no count-up, no stagger, no pulse, no slide.
 */
(function () {
  "use strict";

  var doc = document;
  var html = doc.documentElement;
  var STATE = html.getAttribute("data-state") || "private";
  if (STATE === "private") return;

  var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  var data = {};
  try {
    var dataNode = doc.getElementById("fps-feed-data");
    data = JSON.parse((dataNode && dataNode.textContent) || "{}") || {};
  } catch (e) {
    data = {};
  }
  var meta = data.meta || {};
  var snap = data.snapshot || null;

  var METHOD = html.getAttribute("data-meta-method") || "fps_erpnext.api.feed.get_feed_meta";
  var CHECK_EVERY = Math.max(60, parseInt(html.getAttribute("data-check-every"), 10) || 600) * 1000;
  var BUILDING_EVERY = Math.max(5, parseInt(html.getAttribute("data-building-every"), 10) || 10) * 1000;
  var VIEWER = html.getAttribute("data-viewer") || "";

  // ------------------------------------------------------------------ time
  // Wall-clock strings ("YYYY-MM-DD HH:MM:SS", Asia/Dubai) are read as if they
  // were UTC, so all arithmetic below is independent of the phone's time zone.

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var SLOT_HOURS = [8, 12, 16, 20];          // feed_logic.SLOT_HOURS
  var SLOT_GRACE = 20 * 60000;               // feed_logic.SLOT_GRACE_MINUTES
  var LATE_GRACE = 30 * 60000;               // feed_logic.LATE_GRACE_MINUTES
  var MIN = 60000;
  var HOUR = 3600000;
  var DAY = 86400000;

  function wall(text) {
    var m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(String(text || ""));
    if (!m) return NaN;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0));
  }

  function isDateOnly(text) {
    return /^\d{4}-\d{2}-\d{2}$/.test(String(text || "").trim());
  }

  var loadedAt = Date.now();
  var serverAtLoad = wall(meta.now);
  if (isNaN(serverAtLoad)) {
    var d0 = new Date();
    serverAtLoad = Date.UTC(d0.getFullYear(), d0.getMonth(), d0.getDate(), d0.getHours(), d0.getMinutes(), d0.getSeconds());
  }

  function now() {
    return serverAtLoad + (Date.now() - loadedAt);
  }

  function pad(n) {
    return (n < 10 ? "0" : "") + n;
  }

  function hhmm(ms) {
    var d = new Date(ms);
    return pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes());
  }

  function dayNo(ms) {
    return Math.floor(ms / DAY);
  }

  function shortDate(ms) {
    var d = new Date(ms);
    return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()];
  }

  function slotStart(ms) {
    var day = dayNo(ms) * DAY;
    var hour = new Date(ms).getUTCHours();
    for (var i = SLOT_HOURS.length - 1; i >= 0; i--) {
      if (hour >= SLOT_HOURS[i]) return day + SLOT_HOURS[i] * HOUR;
    }
    return day - DAY + SLOT_HOURS[SLOT_HOURS.length - 1] * HOUR;
  }

  function nextSlotStart(ms) {
    var day = dayNo(ms) * DAY;
    for (var i = 0; i < SLOT_HOURS.length; i++) {
      var candidate = day + SLOT_HOURS[i] * HOUR;
      if (candidate > ms) return candidate;
    }
    return day + DAY + SLOT_HOURS[0] * HOUR;
  }

  function daySuffix(shown, n) {
    var days = dayNo(n) - dayNo(shown);
    if (days === 0) return "";
    if (days === 1) return " yesterday";
    return " on " + shortDate(shown);
  }

  // feed_logic.updated_label / next_slot_label / is_late, ported.
  function updatedLabel(gen, n) {
    var start = slotStart(gen);
    var shown = gen - start <= SLOT_GRACE ? start : gen;
    return hhmm(shown) + daySuffix(shown, n);
  }

  function nextSlotLabel(n) {
    var next = nextSlotStart(n);
    return hhmm(next) + (dayNo(next) > dayNo(n) ? " tomorrow" : "");
  }

  function isLate(gen, n) {
    if (isNaN(gen)) return false;
    var expected = slotStart(n);
    return gen < expected && n - expected > LATE_GRACE;
  }

  function relTime(at) {
    var t = wall(at);
    if (isNaN(t)) return "";
    var n = now();
    var days = dayNo(n) - dayNo(t);
    if (isDateOnly(at)) {
      // A bare date has no time: "today", never "0 min ago".
      if (days <= 0) return "today";
      if (days === 1) return "yesterday";
      if (days < 7) return days + " days ago";
      return shortDate(t);
    }
    var s = n - t;
    if (s < MIN) return "just now";
    if (s < HOUR) return Math.floor(s / MIN) + " min ago";
    if (days <= 0 || s < 6 * HOUR) return Math.floor(s / HOUR) + " h ago";
    if (days === 1) return "yesterday, " + hhmm(t);
    if (days < 7) return days + " days ago";
    return shortDate(t);
  }

  function absTime(at) {
    var t = wall(at);
    if (isNaN(t)) return "";
    return isDateOnly(at) ? shortDate(t) : shortDate(t) + ", " + hhmm(t);
  }

  // ----------------------------------------------------------------- money
  // Full figures for the sheet's hero (the rows already carry them); compact
  // only for the count-up frames -- the last frame is always the server's
  // `display`, so a number is never left half-way.

  function moneyFull(v) {
    var n = Math.round(Math.abs(v) * 100) / 100;
    var text = n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (v < 0 && n !== 0 ? "\u2212" : "") + "AED " + text;
  }

  function compact(v) {
    var neg = v < 0;
    var n = Math.abs(v);
    var tiers = [[1e9, "B"], [1e6, "M"], [1e3, "K"]];
    for (var i = 0; i < tiers.length; i++) {
      if (n >= tiers[i][0]) {
        var scaled = +(n / tiers[i][0]).toFixed(1);
        if (i > 0 && scaled >= 1000) {
          // rounding pushed it into the next unit up (999,960 -> 1M), as format_compact does
          i -= 1;
          scaled = +(n / tiers[i][0]).toFixed(1);
        }
        return (neg ? "\u2212" : "") + String(scaled) + tiers[i][1];
      }
    }
    return (neg && Math.round(n) ? "\u2212" : "") + String(Math.round(n));
  }

  // ------------------------------------------------------------------- DOM

  var SVGNS = "http://www.w3.org/2000/svg";

  function el(tag, cls, text) {
    var node = doc.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null && text !== "") node.textContent = String(text);
    return node;
  }

  function icon(name) {
    var svg = doc.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    var use = doc.createElementNS(SVGNS, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  function deskRoute(route) {
    // Only a desk path becomes a link (never javascript:, never another host).
    return typeof route === "string" && /^\/(app|desk)(\/|\?|$)/.test(route) ? route : null;
  }

  function openable(entry) {
    return !!(entry && entry.can_open === true && deskRoute(entry.route));
  }

  var KIND_ICON = {
    insight: "insight", job: "job", update: "update", customs: "customs", delivery: "delivery",
    invoice: "invoice", receipt: "receipt", overdue_customer: "customer", supplier_due: "supplier",
    bank: "bank", cash: "cash"
  };
  var KIND_LABEL = {
    insight: "Alert", job: "Job opened", update: "Job update", customs: "Customs cleared",
    delivery: "Delivery", invoice: "Invoice submitted", receipt: "Receipt", overdue_customer: "Overdue customer",
    supplier_due: "Supplier past due", bank: "Bank statements", cash: "Cash & bank"
  };
  var SEVERITY_LABEL = { critical: "Critical", warning: "Warning", info: "Info", positive: "Good" };
  var EVENT_KINDS = { job: 1, update: 1, customs: 1, delivery: 1, invoice: 1, receipt: 1 };
  // Standing lists: past due by definition, their group heading says so -- no
  // "Warning" label on each card.
  var PARTY_KINDS = { overdue_customer: 1, supplier_due: 1 };

  function tag(text, tone, iconName) {
    var t = el("span", "tag");
    if (tone) t.setAttribute("data-tone", tone);
    if (iconName) t.appendChild(icon(iconName));
    t.appendChild(el("span", null, text));
    return t;
  }

  function newTag() {
    var t = tag("NEW", "new");
    t.setAttribute("title", "New or changed since the previous update");
    return t;
  }

  function severityTag(severity) {
    if (severity !== "critical" && severity !== "warning") return null;
    return tag(SEVERITY_LABEL[severity], severity, severity);
  }

  function rowsList(rows) {
    var list = (rows || []).filter(function (r) { return r && (r.label || r.value); });
    if (!list.length) return null;
    var dl = el("dl", "rows");
    list.forEach(function (r) {
      var row = el("div", "row");
      row.appendChild(el("dt", null, r.label));
      row.appendChild(el("dd", null, r.value));
      dl.appendChild(row);
    });
    return dl;
  }

  function callout(text, tone) {
    var c = el("div", "callout");
    c.setAttribute("data-tone", tone || "info");
    c.appendChild(icon(tone === "critical" ? "critical" : tone === "warning" ? "warning" : "info"));
    c.appendChild(el("p", null, text));
    return c;
  }

  // ------------------------------------------------------------- the feed

  var staggerIndex = 0;
  var countNodes = [];

  function stagger(node) {
    if (reduceMotion) return;
    node.style.setProperty("--d", Math.min(staggerIndex, 14) * 35 + "ms");
    staggerIndex += 1;
  }

  // Delta vs the previous 7 days. "new" (nothing to compare with: a zero base)
  // must not read like the NEW badge, so it is spelled out with the base.
  function deltaText(delta, full) {
    if (!delta || !delta.text || delta.text === "\u2014" || delta.text === "-") return full && delta && delta.text ? "No earlier figure to compare" : "";
    var label = delta.label || "vs previous 7 days";
    if (delta.text === "new") {
      var base = delta.previous_display || "0";
      return full ? "Up from " + base + " in the previous 7 days" : "Up from " + base;
    }
    return full ? delta.text + " " + label : delta.text + " vs prev. 7d";
  }

  function deltaTone(delta) {
    return delta && delta.tone === "positive" ? "positive" : delta && delta.tone === "warning" ? "warning" : null;
  }

  function comparedLabel() {
    var cw = wall(snap && snap.compared_with);
    return isNaN(cw) ? "the previous update" : updatedLabel(cw, now());
  }

  function renderChip(chip, section) {
    var b = el("button", "chip glass");
    b.type = "button";
    b.setAttribute("data-tone", chip.tone || "neutral");
    b.setAttribute("aria-haspopup", "dialog");

    var label = el("span", "chip-label");
    if (chip.tone === "critical" || chip.tone === "warning") label.appendChild(icon(chip.tone));
    label.appendChild(el("span", null, chip.label));
    b.appendChild(label);

    var value = el("span", "chip-value");
    var shown = el("span", null, chip.display);
    shown.setAttribute("aria-hidden", "true");
    value.appendChild(shown);
    value.appendChild(el("span", "vh", chip.display));
    b.appendChild(value);
    if (typeof chip.value === "number" && isFinite(chip.value)) {
      countNodes.push({ node: shown, value: chip.value, display: String(chip.display || ""), currency: chip.unit === "currency" });
    }

    if (chip.sub) b.appendChild(el("span", "chip-sub", chip.sub));

    var tags = el("span", "chip-tags");
    var short = deltaText(chip.delta, false);
    if (short) {
      var dt = tag(short, deltaTone(chip.delta));
      dt.setAttribute("title", deltaText(chip.delta, true));
      tags.appendChild(dt);
    }
    if (chip.changed) {
      var since = chip.since_previous_display ? chip.since_previous_display + " since " + comparedLabel() : "Changed";
      tags.appendChild(tag(since, "info"));
    }
    if (tags.childNodes.length) b.appendChild(tags);

    b.addEventListener("click", function () { openSheet(chipSheet(chip, section), b); });
    stagger(b);
    return b;
  }

  // Card: [well] title (the party / the alert) over the full text width, the
  // subtitle, then one line with the kind tag, severity, time and -- at its
  // end -- the amount. NEW sits at the start of the title.
  function renderItem(item, section) {
    var b = el("button", "item glass" + (item.is_new ? " is-new" : ""));
    b.type = "button";
    b.setAttribute("data-severity", item.severity || "info");
    b.setAttribute("data-kind", item.kind || "");
    b.setAttribute("aria-haspopup", "dialog");

    var well = el("span", "well");
    well.setAttribute("aria-hidden", "true");
    well.appendChild(icon(KIND_ICON[item.kind] || "info"));
    b.appendChild(well);

    var main = el("span", "item-main");
    var title = el("span", "item-title");
    if (item.is_new) title.appendChild(newTag());
    title.appendChild(doc.createTextNode(String(item.title || "")));
    main.appendChild(title);
    if (item.subtitle) main.appendChild(el("span", "item-sub", item.subtitle));
    var line = el("span", "item-meta");
    if (item.tag) line.appendChild(tag(item.tag, "kind"));
    if ((item.severity === "critical" || item.severity === "warning") && !PARTY_KINDS[item.kind]) {
      var sev = el("span", "sev");
      sev.setAttribute("data-severity", item.severity);
      sev.appendChild(icon(item.severity));
      sev.appendChild(el("span", null, SEVERITY_LABEL[item.severity]));
      line.appendChild(sev);
    }
    if (item.at) {
      var t = el("time", "rel", relTime(item.at));
      t.setAttribute("data-at", item.at);
      t.setAttribute("datetime", String(item.at).replace(" ", "T"));
      line.appendChild(t);
    }
    if (item.amount_display) line.appendChild(el("span", "amount", item.amount_display));
    if (line.childNodes.length) main.appendChild(line);
    b.appendChild(main);

    b.addEventListener("click", function () { openSheet(itemSheet(item, section), b); });
    stagger(b);
    return b;
  }

  function groupOf(item) {
    if (EVENT_KINDS[item.kind]) return "events";
    if (item.kind === "overdue_customer" || item.kind === "supplier_due") return item.kind;
    return item.severity === "critical" || item.severity === "warning" ? "attention" : "notes";
  }

  var GROUP_LABEL = {
    attention: "Needs attention",
    events: "Latest activity",
    overdue_customer: "Most overdue customers",
    supplier_due: "Suppliers past due",
    notes: "Notes"
  };

  function sectionCounts(section) {
    var c = section.counts || {};
    var out = el("span", "sec-counts");
    function add(n, one, many, cls, iconName) {
      if (!n) return;
      var s = el("span", cls);
      if (iconName) s.appendChild(icon(iconName));
      s.appendChild(el("span", null, n + " " + (n === 1 ? one : many)));
      out.appendChild(s);
    }
    add(c.critical, "critical", "critical", "critical", "critical");
    add(c.warning, "warning", "warnings", "warning", "warning");
    add(c["new"], "new", "new", "new", null);
    if (!out.childNodes.length) out.appendChild(el("span", null, section.error ? "Not available" : "Nothing urgent"));
    return out;
  }

  function renderSection(section) {
    var sec = el("section", "section");
    sec.id = "sec-" + section.key;
    sec.setAttribute("aria-labelledby", "sec-title-" + section.key);

    var h = el("h2", "sec-h");
    var head = el("button", "sec-head");
    head.type = "button";
    head.setAttribute("aria-haspopup", "dialog");
    var titles = el("span", "sec-titles");
    var title = el("span", "sec-title", section.title);
    title.id = "sec-title-" + section.key;
    titles.appendChild(title);
    titles.appendChild(sectionCounts(section));
    head.appendChild(titles);
    var chev = icon("chevron");
    chev.setAttribute("class", "chev");
    head.appendChild(chev);
    head.addEventListener("click", function () { openSheet(sectionSheet(section), head); });
    h.appendChild(head);
    sec.appendChild(h);

    if (section.error) {
      var err = el("div", "sec-error");
      err.appendChild(icon("critical"));
      err.appendChild(el("p", null, section.error));
      sec.appendChild(err);
      return sec;
    }

    if (section.notice) {
      var notice = el("div", "sec-notice");
      notice.setAttribute("role", "note");
      notice.appendChild(icon("warning"));
      notice.appendChild(el("p", null, section.notice));
      sec.appendChild(notice);
    }

    if (section.chips && section.chips.length) {
      var chips = el("div", "chips");
      section.chips.forEach(function (chip) { chips.appendChild(renderChip(chip, section)); });
      sec.appendChild(chips);
    }

    var items = section.items || [];
    if (!items.length) {
      var empty = el("div", "empty glass", "Nothing to report " + ((snap && snap.since_label) || "") + ".");
      sec.appendChild(empty);
    }
    var list = null;
    var group = null;
    items.forEach(function (item) {
      var g = groupOf(item);
      if (g !== group || !list) {
        group = g;
        sec.appendChild(el("h3", "group", GROUP_LABEL[g] || ""));
        list = el("ul", "items");
        sec.appendChild(list);
      }
      var li = el("li");
      li.appendChild(renderItem(item, section));
      list.appendChild(li);
    });

    var more = (section.more || []).map(function (m) { return m && m.label; }).filter(Boolean);
    if (more.length) sec.appendChild(el("p", "more", "Not shown: " + more.join(" \u00B7 ") + "."));
    return sec;
  }

  function renderFoot() {
    var foot = el("footer", "foot");
    var gen = wall(snap.generated_at);
    var built = isNaN(gen) ? "" : "Built " + shortDate(gen) + " at " + hhmm(gen) + " from the FPS OPS and FPS ACC dashboards (last 7 days).";
    if (built) foot.appendChild(el("p", null, built));
    foot.appendChild(el("p", null, "Updates at 08:00, 12:00, 16:00 and 20:00 (" + (snap.time_zone || meta.time_zone || "Asia/Dubai") + ")."));
    if (VIEWER) foot.appendChild(el("p", null, "Signed in as " + VIEWER + "."));
    return foot;
  }

  function renderTabs(sections) {
    var nav = doc.getElementById("tabs");
    if (!nav) return;
    nav.textContent = "";
    sections.forEach(function (section, i) {
      var b = el("button", "tab");
      b.type = "button";
      b.setAttribute("data-target", "sec-" + section.key);
      b.setAttribute("aria-current", i === 0 ? "true" : "false");
      b.appendChild(el("span", null, section.title));
      var n = (section.counts && section.counts["new"]) || 0;
      if (n) {
        var c = el("span", "count", String(n));
        c.setAttribute("aria-label", n + " new");
        b.appendChild(c);
      }
      b.addEventListener("click", function () {
        var target = doc.getElementById("sec-" + section.key);
        if (!target) return;
        if (i === 0) {
          window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
        } else {
          target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
        }
      });
      nav.appendChild(b);
    });
  }

  var tabTicking = false;
  function updateActiveTab() {
    tabTicking = false;
    var nav = doc.getElementById("tabs");
    var top = doc.getElementById("top");
    if (!nav || !top) return;
    // A section is the one being read once its top has crossed the middle of
    // the viewport (the Accounts chips on screen -> the Accounts tab).
    var line = Math.max(top.getBoundingClientRect().bottom + 48, window.innerHeight / 2);
    var tabs = nav.querySelectorAll(".tab");
    var active = 0;
    for (var i = 0; i < tabs.length; i++) {
      var target = doc.getElementById(tabs[i].getAttribute("data-target"));
      if (target && target.getBoundingClientRect().top <= line) active = i;
    }
    // At the very bottom the last section is the one being read.
    if (window.innerHeight + window.scrollY >= doc.documentElement.scrollHeight - 2) active = tabs.length - 1;
    for (var j = 0; j < tabs.length; j++) tabs[j].setAttribute("aria-current", j === active ? "true" : "false");
  }

  function renderFeed() {
    var main = doc.getElementById("main");
    if (!main || !snap) return;
    main.textContent = "";
    if (!reduceMotion) main.classList.add("animate");
    var sections = snap.sections || [];
    renderTabs(sections);
    sections.forEach(function (section) { main.appendChild(renderSection(section)); });
    main.appendChild(renderFoot());
    main.setAttribute("aria-busy", "false");
    countUp();
    window.addEventListener("scroll", function () {
      lastScrollAt = Date.now();
      if (!tabTicking) {
        tabTicking = true;
        window.requestAnimationFrame(updateActiveTab);
      }
    }, { passive: true });
  }

  function countUp() {
    var nodes = countNodes;
    if (reduceMotion || !nodes.length || !window.requestAnimationFrame) return;
    var DURATION = 700;
    var start = null;
    function format(n, value) {
      if (n.currency) {
        var text = compact(value);
        return text.charAt(0) === "\u2212" ? "\u2212AED " + text.slice(1) : "AED " + text;
      }
      return String(Math.round(value));
    }
    function finish() {
      nodes.forEach(function (n) { n.node.textContent = n.display; });
    }
    function frame(ts) {
      if (start === null) start = ts;
      var p = Math.min(1, (ts - start) / DURATION);
      var eased = 1 - Math.pow(1 - p, 3);
      if (p >= 1) {
        finish();
        return;
      }
      nodes.forEach(function (n) { n.node.textContent = format(n, n.value * eased); });
      window.requestAnimationFrame(frame);
    }
    nodes.forEach(function (n) { n.node.textContent = format(n, 0); });
    window.requestAnimationFrame(frame);
    window.setTimeout(finish, DURATION + 400);   // a hidden tab gets no frames
  }

  function refreshTimes() {
    var times = doc.querySelectorAll("time[data-at]");
    for (var i = 0; i < times.length; i++) {
      var text = relTime(times[i].getAttribute("data-at"));
      if (times[i].textContent !== text) times[i].textContent = text;
    }
  }

  // ---------------------------------------------------------------- sheets

  function itemSheet(item, section) {
    var tags = [];
    if (item.tag) tags.push(tag(item.tag, "kind"));
    var sev = severityTag(item.severity);
    if (sev) tags.push(sev);
    if (item.is_new) tags.push(newTag());
    var when = item.at ? relTime(item.at) + " \u00B7 " + absTime(item.at) : "";
    return {
      kicker: section.title + " \u00B7 " + (KIND_LABEL[item.kind] || "Item"),
      title: item.title,
      subtitle: item.subtitle,
      iconName: KIND_ICON[item.kind] || "info",
      severity: item.severity,
      kind: item.kind,
      tags: tags,
      when: when,
      hero: typeof item.amount === "number" && isFinite(item.amount) ? moneyFull(item.amount) : null,
      callouts: item.note ? [{ text: item.note, tone: item.severity === "critical" || item.severity === "warning" ? item.severity : "info" }] : [],
      rows: item.detail,
      records: item.records,
      recordsMore: item.records_more,
      link: openable(item) ? item.route : null
    };
  }

  function chipSheet(chip, section) {
    var tags = [];
    var sev = severityTag(chip.tone);
    if (sev) tags.push(sev);
    var long = deltaText(chip.delta, true);
    if (long) tags.push(tag(long, deltaTone(chip.delta)));
    if (chip.changed) {
      tags.push(tag(chip.since_previous_display ? chip.since_previous_display + " since " + comparedLabel() : "Changed since " + comparedLabel(), "info"));
    }
    var callouts = [];
    if (chip.note) callouts.push({ text: chip.note, tone: chip.tone === "critical" ? "critical" : chip.tone === "warning" ? "warning" : "info" });
    return {
      kicker: section.title + " \u00B7 Figure",
      title: chip.label,
      subtitle: null,
      iconName: chip.tone === "critical" || chip.tone === "warning" ? chip.tone : chip.tone === "positive" ? "positive" : "info",
      severity: chip.tone === "neutral" ? "info" : chip.tone,
      tags: tags,
      // The sheet shows the full figure (DESIGN.md section 5); the card the compact one.
      hero: chip.unit === "currency" && typeof chip.value === "number" && isFinite(chip.value) ?
        moneyFull(chip.value) : chip.display,
      heroSub: chip.unit === "currency" && chip.display ? chip.display + (chip.sub ? " \u00B7 " + chip.sub : "") : chip.sub,
      callouts: callouts,
      definition: chip.definition,
      rows: chip.detail,
      link: openable(chip) ? chip.route : null
    };
  }

  function sectionSheet(section) {
    var c = section.counts || {};
    var tags = [];
    if (c.critical) tags.push(tag(c.critical + " critical", "critical", "critical"));
    if (c.warning) tags.push(tag(c.warning + (c.warning === 1 ? " warning" : " warnings"), "warning", "warning"));
    if (c["new"]) tags.push(tag(c["new"] + " new since " + comparedLabel(), "info"));
    var callouts = section.error ? [{ text: section.error, tone: "critical" }] : [];
    var rows = (section.detail || []).slice();
    var more = (section.more || []).map(function (m) { return m && m.label; }).filter(Boolean);
    if (more.length) rows.push({ label: "Not shown", value: more.join("; ") });
    return {
      kicker: "Section",
      title: section.title,
      subtitle: snap && snap.since_label ? "Events " + snap.since_label : null,
      iconName: section.key === "acc" ? "receipt" : "job",
      severity: "info",
      tags: tags,
      callouts: callouts,
      definition: section.definition,
      rows: rows
    };
  }

  var sheet = null;

  function sheetParts() {
    if (sheet) return sheet;
    var root = doc.getElementById("sheet-root");
    if (!root) return null;
    sheet = {
      root: root,
      panel: doc.getElementById("sheet"),
      scrim: doc.getElementById("scrim"),
      grab: doc.getElementById("sheet-grab"),
      head: doc.getElementById("sheet-head"),
      icon: doc.getElementById("sheet-icon"),
      kicker: doc.getElementById("sheet-kicker"),
      title: doc.getElementById("sheet-title"),
      sub: doc.getElementById("sheet-sub"),
      body: doc.getElementById("sheet-body"),
      foot: doc.getElementById("sheet-foot"),
      close: doc.getElementById("sheet-close"),
      isOpen: false,
      lastFocus: null,
      timer: null
    };
    sheet.close.addEventListener("click", closeSheet);
    sheet.scrim.addEventListener("click", closeSheet);
    root.addEventListener("keydown", onSheetKey);
    [sheet.grab, sheet.head].forEach(function (zone) {
      zone.addEventListener("pointerdown", dragStart);
      zone.addEventListener("pointermove", dragMove);
      zone.addEventListener("pointerup", dragEnd);
      zone.addEventListener("pointercancel", dragEnd);
    });
    return sheet;
  }

  function fillSheet(spec) {
    var s = sheet;
    s.icon.textContent = "";
    s.icon.setAttribute("data-severity", spec.severity || "info");
    s.icon.setAttribute("data-kind", spec.kind || "");
    s.icon.appendChild(icon(spec.iconName || "info"));
    s.kicker.textContent = spec.kicker || "";
    s.title.textContent = spec.title || "";
    s.sub.textContent = spec.subtitle || "";

    var body = s.body;
    body.textContent = "";
    if ((spec.tags && spec.tags.length) || spec.when) {
      var tags = el("div", "sheet-tags");
      (spec.tags || []).forEach(function (t) { tags.appendChild(t); });
      if (spec.when) tags.appendChild(el("span", null, spec.when));
      body.appendChild(tags);
    }
    if (spec.hero) body.appendChild(el("p", "hero", spec.hero));
    if (spec.heroSub) body.appendChild(el("p", "hero-sub", spec.heroSub));
    (spec.callouts || []).forEach(function (c) { body.appendChild(callout(c.text, c.tone)); });
    if (spec.definition) body.appendChild(el("p", "definition", spec.definition));
    var rows = rowsList(spec.rows);
    if (rows) body.appendChild(rows);

    var records = (spec.records || []).filter(Boolean);
    if (records.length) {
      body.appendChild(el("h3", "records-title", "Documents"));
      var list = el("div", "records");
      var lastGroup = null;
      records.forEach(function (r) {
        if (r.group && r.group !== lastGroup) {
          var gh = el("div", "records-group", r.group);
          gh.setAttribute("role", "heading");
          gh.setAttribute("aria-level", "4");
          list.appendChild(gh);
        }
        lastGroup = r.group || null;
        var link = openable(r);
        var row = el(link ? "a" : "div", "record");
        if (link) {
          row.setAttribute("href", r.route);
          row.setAttribute("target", "_blank");
          row.setAttribute("rel", "noopener");
        }
        var mainPart = el("span", "record-main");
        mainPart.appendChild(el("span", "record-title", r.title || r.name));
        if (r.subtitle) mainPart.appendChild(el("span", "record-sub", r.subtitle));
        row.appendChild(mainPart);
        if (r.value) row.appendChild(el("span", "record-value", r.value));
        if (link) {
          row.appendChild(icon("external"));
          row.setAttribute("aria-label", (r.title || r.name || "") + (r.subtitle ? ", " + r.subtitle : "") + (r.value ? ", " + r.value : "") + ". Open in ERPNext");
        }
        list.appendChild(row);
      });
      body.appendChild(list);
      if (spec.recordsMore) body.appendChild(el("p", "records-more", "+ " + spec.recordsMore + " more in ERPNext"));
    }

    s.foot.textContent = "";
    if (spec.link) {
      var a = el("a", "btn-primary");
      a.setAttribute("href", spec.link);
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener");
      a.appendChild(el("span", null, "Open in ERPNext"));
      a.appendChild(icon("external"));
      s.foot.appendChild(a);
      s.foot.hidden = false;
    } else {
      s.foot.hidden = true;
    }
  }

  function openSheet(spec, trigger) {
    var s = sheetParts();
    if (!s) return;
    window.clearTimeout(s.timer);
    fillSheet(spec);
    s.lastFocus = trigger || doc.activeElement;
    s.isOpen = true;
    s.panel.style.transform = "";
    s.root.hidden = false;
    html.classList.add("sheet-open");
    setInert(true);
    hideHint(true);
    s.body.scrollTop = 0;
    void s.panel.offsetWidth;   // commit the closed position so the slide runs
    s.root.classList.add("open");
    try {
      s.panel.focus({ preventScroll: true });
    } catch (e) {
      s.panel.focus();
    }
  }

  function closeSheet() {
    var s = sheet;
    if (!s || !s.isOpen) return;
    s.isOpen = false;
    s.root.classList.remove("open");
    s.panel.classList.remove("dragging");
    s.panel.style.transform = "";
    function done() {
      if (s.isOpen) return;
      s.root.hidden = true;
      html.classList.remove("sheet-open");
      setInert(false);
      hideHint(false);
      if (s.lastFocus && s.lastFocus.focus) {
        try {
          s.lastFocus.focus({ preventScroll: true });
        } catch (e) {
          s.lastFocus.focus();
        }
      }
    }
    if (reduceMotion) done();
    else s.timer = window.setTimeout(done, 260);
  }

  function setInert(on) {
    var app = doc.getElementById("app");
    if (!app) return;
    if (on) {
      app.setAttribute("inert", "");
      app.setAttribute("aria-hidden", "true");
    } else {
      app.removeAttribute("inert");
      app.removeAttribute("aria-hidden");
    }
  }

  function onSheetKey(e) {
    if (e.key === "Escape" || e.key === "Esc") {
      e.preventDefault();
      closeSheet();
      return;
    }
    if (e.key !== "Tab") return;
    var focusables = sheet.panel.querySelectorAll("a[href], button:not([disabled])");
    if (!focusables.length) return;
    var first = focusables[0];
    var last = focusables[focusables.length - 1];
    if (e.shiftKey && (doc.activeElement === first || doc.activeElement === sheet.panel)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && doc.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  // Drag the sheet down by its handle or header to close it.
  var drag = null;

  function dragStart(e) {
    if (!sheet || !sheet.isOpen) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (e.target && e.target.closest && e.target.closest("button, a")) return;
    drag = { id: e.pointerId, y0: e.clientY, t0: e.timeStamp, dy: 0 };
    sheet.panel.classList.add("dragging");
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch (err) { /* not capturable: the drag still works inside the zone */ }
  }

  function dragMove(e) {
    if (!drag || e.pointerId !== drag.id) return;
    drag.dy = Math.max(0, e.clientY - drag.y0);
    sheet.panel.style.transform = "translate(-50%, " + drag.dy + "px)";
  }

  function dragEnd(e) {
    if (!drag || e.pointerId !== drag.id) return;
    var dy = drag.dy;
    var speed = dy / Math.max(1, e.timeStamp - drag.t0);
    drag = null;
    sheet.panel.classList.remove("dragging");
    if (dy > 96 || (dy > 32 && speed > 0.6)) {
      closeSheet();
    } else {
      sheet.panel.style.transform = "";
    }
  }

  // ------------------------------------------------------- header / status

  function setLive(mode) {
    var live = doc.getElementById("live");
    var text = doc.getElementById("live-text");
    if (!live || !text) return;
    live.setAttribute("data-mode", mode);
    // Only a feed that is current says LIVE.
    text.textContent = { offline: "OFFLINE", late: "LATE", building: "PREPARING" }[mode] || "LIVE";
    live.setAttribute("aria-label", mode === "offline" ? "Offline: showing the last update" :
      mode === "late" ? "The scheduled update is late: check again" :
      mode === "building" ? "Preparing the first update: check now" : "Live feed: check for a newer update");
  }

  function renderStatus(fromServer) {
    var status = doc.getElementById("status");
    if (!status || STATE !== "ready") return;
    var n = now();
    var gen = wall(meta.generated_at);
    if (isNaN(gen)) return;
    var late = fromServer ? !!meta.late : isLate(gen, n);
    var updated = fromServer && meta.updated_label ? meta.updated_label : updatedLabel(gen, n);
    status.textContent = "";
    if (late) {
      status.appendChild(el("span", "late", "The " + hhmm(slotStart(n)) + " update is late"));
      status.appendChild(doc.createTextNode(" \u00B7 showing " + updated));
    } else {
      var next = fromServer && meta.next_slot ? meta.next_slot : nextSlotLabel(n);
      status.textContent = "Updated " + updated + " \u00B7 next " + next;
    }
    if (navigator.onLine === false) setLive("offline");
    else setLive(late ? "late" : "live");
  }

  function toast(text) {
    var old = doc.querySelector(".toast");
    if (old && old.classList.contains("toast-action")) return;   // the refresh offer stays
    if (old) old.remove();
    var t = el("div", "toast", text);
    t.setAttribute("role", "status");
    doc.body.appendChild(t);
    window.setTimeout(function () { t.remove(); }, 2400);
  }

  // ------------------------------------------------------ newer snapshot?

  var checking = false;
  var lastCheck = 0;
  var buildingTimer = null;
  var lastScrollAt = 0;
  var refreshOffered = false;

  // Reloading under a reader would close their sheet or jump their scroll:
  // when they are busy, offer the new update instead.
  function readerBusy() {
    return !!(sheet && sheet.isOpen) || Date.now() - lastScrollAt < 30000;
  }

  function offerRefresh() {
    if (refreshOffered) return;
    refreshOffered = true;
    var old = doc.querySelector(".toast");
    if (old) old.remove();
    var b = el("button", "toast toast-action", "New update \u00B7 tap to refresh");
    b.type = "button";
    b.setAttribute("aria-live", "polite");
    b.addEventListener("click", function () { window.location.reload(); });
    doc.body.appendChild(b);
  }

  function newerSnapshot() {
    if (readerBusy()) offerRefresh();
    else window.location.reload();
  }

  function fetchMeta() {
    return window.fetch("/api/method/" + encodeURIComponent(METHOD), {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" }
    }).then(function (r) {
      if (r.status === 401 || r.status === 403) {
        // Signed out (session expired) or no longer allowed: the page itself
        // sends the viewer to the login page or shows "private".
        window.location.reload();
        return null;
      }
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (j) {
      return j ? (j.message || {}) : null;
    });
  }

  function checkForUpdate(manual) {
    if (STATE !== "ready" || checking || !window.fetch) return;
    if (!manual && Date.now() - lastCheck < 15000) return;
    checking = true;
    lastCheck = Date.now();
    fetchMeta().then(function (m) {
      if (!m) return;
      if (m.generated_at && m.generated_at !== meta.generated_at) {
        if (manual) window.location.reload();   // the reader asked for it
        else newerSnapshot();
        return;
      }
      if (manual) toast("Up to date \u00B7 next update " + nextSlotLabel(now()));
    }).catch(function () {
      if (manual) toast(navigator.onLine === false ? "You are offline" : "Could not check for an update");
    }).then(function () {
      checking = false;
    });
  }

  function buildingFailed() {
    var card = doc.getElementById("building");
    if (!card) return;
    card.setAttribute("data-failed", "");
    card.textContent = "";
    var iconWrap = el("span", "calm-icon");
    iconWrap.setAttribute("aria-hidden", "true");
    iconWrap.appendChild(icon("warning"));
    card.appendChild(iconWrap);
    card.appendChild(el("h2", null, "The feed could not be prepared."));
    card.appendChild(el("p", null, "It will try again at " + (meta.next_slot || nextSlotLabel(now())) + ". Reloading this page tries once more."));
    var again = el("button", "btn-primary", "Try again");
    again.type = "button";
    again.addEventListener("click", function () { window.location.reload(); });
    card.appendChild(again);
    var status = doc.getElementById("status");
    if (status) status.textContent = "First update not ready";
    setLive("late");
  }

  function pollBuilding() {
    if (!window.fetch) return;
    fetchMeta().then(function (m) {
      if (!m) return;
      if (m.generated_at) {
        window.location.reload();
        return;
      }
      if (m.building === false) {
        window.clearInterval(buildingTimer);
        buildingTimer = null;
        buildingFailed();
      }
    }).catch(function () { /* try again on the next tick */ });
  }

  // ------------------------------------------------- Add to Home Screen

  var HINT_KEY = "fpsFeed.homeScreenHintDismissed";
  var hintWanted = false;

  function hideHint(sheetOpen) {
    var hint = doc.getElementById("hint");
    if (!hint || !hintWanted) return;
    hint.hidden = !!sheetOpen;
  }

  function maybeHint() {
    var hint = doc.getElementById("hint");
    if (!hint) return;
    var ua = navigator.userAgent || "";
    var ios = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    var standalone = navigator.standalone === true ||
      !!(window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);
    if (!ios || standalone) return;
    try {
      if (window.localStorage.getItem(HINT_KEY)) return;
    } catch (e) { /* storage blocked: show it, it just won't be remembered */ }
    doc.getElementById("hint-close").addEventListener("click", function () {
      hintWanted = false;
      hint.hidden = true;
      doc.body.classList.remove("has-hint");
      try {
        window.localStorage.setItem(HINT_KEY, "1");
      } catch (e) { /* not remembered */ }
    });
    window.setTimeout(function () {
      hintWanted = true;
      doc.body.classList.add("has-hint");
      if (!(sheet && sheet.isOpen)) hint.hidden = false;
    }, 1200);
  }

  // ------------------------------------------------------------------ start

  function onVisible() {
    if (doc.visibilityState === "hidden") return;
    refreshTimes();
    renderStatus(false);
    if (STATE === "ready") checkForUpdate(false);
    else if (STATE === "building") pollBuilding();
  }

  if (STATE === "ready" && snap) {
    renderFeed();
    renderStatus(true);
    var liveButton = doc.getElementById("live");
    if (liveButton) liveButton.addEventListener("click", function () { checkForUpdate(true); });
    window.setInterval(function () { checkForUpdate(false); }, CHECK_EVERY);
    window.setInterval(function () {
      if (doc.visibilityState === "hidden") return;
      refreshTimes();
      renderStatus(false);
    }, 60000);
  } else if (STATE === "building") {
    setLive("building");
    buildingTimer = window.setInterval(pollBuilding, BUILDING_EVERY);
    var buildingLive = doc.getElementById("live");
    if (buildingLive) buildingLive.addEventListener("click", pollBuilding);
  }

  doc.addEventListener("visibilitychange", onVisible);
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) onVisible();   // restored from the back/forward cache or resumed
  });
  window.addEventListener("online", function () {
    renderStatus(false);
    if (STATE === "ready") checkForUpdate(false);
  });
  window.addEventListener("offline", function () { setLive("offline"); });
  if (navigator.onLine === false) setLive("offline");
  window.addEventListener("online", function () {
    if (STATE === "building" && !doc.querySelector("#building[data-failed]")) setLive("building");
  });

  maybeHint();

  // For checks from the browser console (read-only helpers, no data).
  window.fpsFeed = {
    wall: wall, now: now, relTime: relTime, updatedLabel: updatedLabel,
    nextSlotLabel: nextSlotLabel, isLate: isLate, slotStart: slotStart, nextSlotStart: nextSlotStart,
    moneyFull: moneyFull, compact: compact
  };
})();
