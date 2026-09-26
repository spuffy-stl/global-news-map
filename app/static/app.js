/* Global News Map frontend.
 * Map rendering is fully self-contained: bundled D3 + bundled Natural Earth
 * GeoJSON. No external tile servers, no CDN calls at runtime.
 *
 * Hierarchy drill-down: continent > region > country.
 * - zoom < 2.2:  continent markers
 * - 2.2 - 4.5:   region markers
 * - zoom >= 4.5: country markers (only countries with stories)
 * Stories are attributed server-side from each country's local news sources
 * (see app/sources.yaml); the client does no keyword matching.
 */
(function () {
  "use strict";

  var W = 960, H = 500;
  var Z_REGION = 2.2, Z_COUNTRY = 4.5;
  var svg = d3.select("#map");
  var projection = d3.geoNaturalEarth1().fitExtent([[8, 8], [W - 8, H - 8]], { type: "Sphere" });
  var path = d3.geoPath(projection);

  var storiesEl = document.getElementById("stories");
  var panelTitle = document.getElementById("panelTitle");
  var panelMeta = document.getElementById("panelMeta");
  var updatedEl = document.getElementById("updated");
  var chipsEl = document.getElementById("chips");
  var panelClose = document.getElementById("panelClose");
  var shareBtn = document.getElementById("shareBtn");
  var zoomResetBtn = document.getElementById("zoomReset");
  var zoomTipEl = document.getElementById("zoomTip");
  var freshBadge = document.getElementById("freshBadge");

  // Returning-visitor hook (SMA-381): show "N new since your last visit" on the
  // world view so repeat visitors see the daily crawl is producing fresh value.
  // SMA-497: measurability for the return hook. A returning visitor is anyone
  // with a recorded previous visit; on their first world view of the session
  // we fire return_visit {hours_away, new_count} so the hook's reach is
  // queryable in GA4, and a click on the badge fires return_badge_click.
  // lastVisitTs is also used for the NEW dots on story cards.
  var lastVisitTs = 0;
  var returnVisitFired = false;
  try { lastVisitTs = parseInt(window.localStorage.getItem("gnm_last_visit") || "0", 10) || 0; } catch (e) {}
  function isNewStory(s) {
    if (!lastVisitTs) return false;
    var t = Date.parse(s.published_at || s.fetched_at || "");
    return !!(t && t > lastVisitTs);
  }
  function updateFreshBadge(items) {
    try {
      var now = Date.now();
      var last = lastVisitTs;
      if (last > 0 && !returnVisitFired) {
        returnVisitFired = true;
        var n = items.filter(isNewStory).length;
        trackEvent("return_visit", {
          hours_away: Math.round((now - last) / 3600000),
          new_count: n
        });
        if (n > 0) {
          freshBadge.textContent = n + " new since your last visit";
          freshBadge.classList.remove("hidden");
        }
      }
      window.localStorage.setItem("gnm_last_visit", String(now));
      // NOTE: lastVisitTs intentionally keeps the *previous* visit's timestamp
      // for the rest of this session, so NEW dots stay correct on drill-down
      // views; only the stored value moves forward.
    } catch (e) { /* storage unavailable (private mode) — skip silently */ }
  }
  freshBadge.addEventListener("click", function () {
    trackEvent("return_badge_click", {});
    freshBadge.classList.add("hidden");
  });

  var continents = [];
  var active = { continent: null, region: null, country: null }; // slugs / ADMIN
  var mapZoom = null;

  // Continent color system: one distinctive hue per continent. Markers, chips,
  // glows and the breadcrumb all draw from here.
  var CONTINENT_COLORS = {
    "north-america": { c: "#60a5fa", dark: "#1e40af" },
    "latin-america": { c: "#34d399", dark: "#065f46" },
    "europe":        { c: "#a78bfa", dark: "#5b21b6" },
    "africa":        { c: "#fbbf24", dark: "#b45309" },
    "middle-east":   { c: "#fb7185", dark: "#9f1239" },
    "asia-pacific":  { c: "#22d3ee", dark: "#0e7490" }
  };
  function continentColor(slug) {
    var r = CONTINENT_COLORS[slug];
    return r ? r.c : "#38bdf8";
  }
  function hexToRgba(hex, a) {
    var n = parseInt(hex.replace("#", ""), 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }

  // Analytics: best-effort. Only present when a GA4 measurement ID is configured
  // server-side; never blocks the UI or throws if the tag hasn't loaded.
  function trackEvent(name, params) {
    try {
      if (typeof window.gtag === "function") window.gtag("event", name, params || {});
    } catch (e) { /* analytics is optional */ }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "&lt;": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Country URL slugs (SMA-399): mirror of country_slug() in app/main.py —
  // keep the two in sync. selectCountry() pushes /country/<slug> into the
  // URL via the History API; loading that URL deep-links into the country
  // view (the server injects window.GNM_INITIAL_COUNTRY for the first load).
  function countrySlug(admin) {
    return String(admin).toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function setPath(path) {
    try { window.history.replaceState(null, "", path); } catch (e) { /* sandboxed — ignore */ }
  }

  // Story-panel share button (SMA-445): visible only on a country view, shares
  // the canonical /country/<slug> URL — Web Share API on mobile, clipboard
  // fallback with a "Copied" confirmation on desktop.
  var CANONICAL_BASE = "https://globalnewsmap.net";
  var shareCountry = null; // {label, slug}
  function setShareCountry(label, admin) {
    if (label && admin) {
      shareCountry = { label: label, slug: countrySlug(admin) };
      shareBtn.classList.remove("hidden");
    } else {
      shareCountry = null;
      shareBtn.classList.add("hidden");
    }
  }
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        if (ok) resolve(); else reject(new Error("execCommand copy failed"));
      } catch (e) { reject(e); }
    });
  }
  shareBtn.addEventListener("click", function () {
    if (!shareCountry) return;
    var url = CANONICAL_BASE + "/country/" + shareCountry.slug;
    var title = shareCountry.label + " headlines -- Global News Map";
    if (navigator.share) {
      navigator.share({ title: title, text: title, url: url }).then(function () {
        trackEvent("share_country", { method: "webshare", country: shareCountry.slug });
      }, function () { /* dismissed — not a share */ });
      return;
    }
    copyText(url).then(function () {
      shareBtn.textContent = "✓ Copied";
      setTimeout(function () { shareBtn.textContent = "↗ Share"; }, 2000);
      trackEvent("share_country", { method: "clipboard", country: shareCountry.slug });
    }, function () {
      window.prompt("Copy this link:", url);
      trackEvent("share_country", { method: "prompt", country: shareCountry.slug });
    });
  });

  function relTime(iso) {
    if (!iso) return "";
    var t = new Date(iso).getTime();
    if (isNaN(t)) return "";
    var s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }

  function findContinent(slug) {
    return continents.find(function (c) { return c.slug === slug; });
  }
  function findRegion(contSlug, slug) {
    var c = findContinent(contSlug);
    return c ? c.regions.find(function (r) { return r.slug === slug; }) : null;
  }
  function findCountry(admin) {
    for (var i = 0; i < continents.length; i++) {
      var c = continents[i];
      for (var j = 0; j < c.regions.length; j++) {
        var r = c.regions[j];
        for (var k = 0; k < r.countries.length; k++) {
          if (r.countries[k].name === admin) {
            return { country: r.countries[k], region: r, continent: c };
          }
        }
      }
    }
    return null;
  }
  function regionStories(region) {
    return region.countries.reduce(function (n, c) { return n + (c.stories || 0); }, 0);
  }
  function continentStories(cont) {
    return cont.regions.reduce(function (n, r) { return n + regionStories(r); }, 0);
  }

  // ---------------------------------------------------------------------------
  // Map rendering + zoom
  // ---------------------------------------------------------------------------
  // Distinguish a drag (pan) from a tap so panning the map doesn't trigger
  // marker selection.
  function onTap(selection, handler) {
    selection
      .on("pointerdown", function (e) {
        var t = e.currentTarget;
        t._tapX = e.clientX; t._tapY = e.clientY;
      })
      .on("click", function (e, d) {
        var t = e.currentTarget;
        if (t._tapX != null && Math.hypot(e.clientX - t._tapX, e.clientY - t._tapY) > 6) return;
        handler(d);
      });
  }

  function applyCounterScale() {
    var k = d3.zoomTransform(svg.node()).k;
    svg.selectAll(".zoom-fix").attr("transform", "scale(" + 1 / k + ")");
  }

  function zoomTo(lon, lat, k) {
    var p = projection([lon, lat]);
    svg.transition().duration(600).call(
      mapZoom.transform,
      d3.zoomIdentity.translate(W / 2, H / 2).scale(k).translate(-p[0], -p[1])
    );
  }

  function markerGroup(layer, cls) {
    var m = layer.append("g").attr("class", "marker " + cls)
      .attr("tabindex", 0).attr("role", "button");
    m.append("g").attr("class", "zoom-fix");
    return m;
  }

  function decorateMarker(m, d, color, label, sub) {
    m.attr("aria-label", label);
    m.style("filter", "drop-shadow(0 0 7px " + hexToRgba(color, 0.75) + ")");
    var inner = m.select(".zoom-fix");
    inner.append("circle").attr("r", 16).attr("class", "pulse").attr("stroke", color);
    inner.append("circle").attr("r", 10.5).attr("class", "halo");
    inner.append("circle").attr("r", 6.5).attr("class", "dot").attr("fill", color);
    inner.append("text").attr("y", -24).attr("class", "label").text(label);
    if (sub) inner.append("text").attr("y", 30).attr("class", "sublabel").text(sub);
  }

  function drawMap() {
    var defs = svg.append("defs");
    var og = defs.append("radialGradient")
      .attr("id", "oceanGrad").attr("cx", "50%").attr("cy", "42%").attr("r", "78%");
    og.append("stop").attr("offset", "0%").attr("stop-color", "#172a4d");
    og.append("stop").attr("offset", "100%").attr("stop-color", "#0a1426");

    var zl = svg.append("g").attr("class", "zoom-layer");
    zl.append("path").datum({ type: "Sphere" }).attr("class", "ocean").attr("d", path);
    zl.append("path").datum(d3.geoGraticule10()).attr("class", "graticule").attr("d", path);
    zl.selectAll("path.country")
      .data(worldFeatures)
      .join("path")
      .attr("class", "country")
      .attr("d", path);

    // --- Continent markers ---
    var cl = zl.append("g").attr("class", "continent-markers");
    var cm = cl.selectAll("g.cmarker")
      .data(continents.filter(function (c) { return continentStories(c) > 0; }))
      .join("g").attr("class", "marker cmarker")
      .attr("transform", function (d) { return "translate(" + projection([d.lon, d.lat]) + ")"; })
      .attr("tabindex", 0).attr("role", "button")
      .attr("aria-label", function (d) { return d.name; });
    cm.append("g").attr("class", "zoom-fix");
    cm.each(function (d) {
      decorateMarker(d3.select(this), d, continentColor(d.slug), d.name,
        continentStories(d) + " stories");
    });
    onTap(cm, function (d) { selectContinent(d.slug, true); });
    cm.on("keydown", function (e, d) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectContinent(d.slug, true); }
    });

    // --- Region markers ---
    var rl = zl.append("g").attr("class", "region-markers");
    var regions = [];
    continents.forEach(function (c) {
      c.regions.forEach(function (r) {
        if (r.lat != null && regionStories(r) > 0) {
          regions.push({ region: r, continent: c });
        }
      });
    });
    var rm = rl.selectAll("g.rmarker")
      .data(regions)
      .join("g").attr("class", "marker rmarker")
      .attr("transform", function (d) { return "translate(" + projection([d.region.lon, d.region.lat]) + ")"; })
      .attr("tabindex", 0).attr("role", "button")
      .attr("aria-label", function (d) { return d.region.name; });
    rm.append("g").attr("class", "zoom-fix");
    rm.each(function (d) {
      decorateMarker(d3.select(this), d, continentColor(d.continent.slug), d.region.name,
        regionStories(d.region) + " stories");
    });
    onTap(rm, function (d) { selectRegion(d.continent.slug, d.region.slug, true); });
    rm.on("keydown", function (e, d) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectRegion(d.continent.slug, d.region.slug, true); }
    });

    // --- Country markers (only countries with stories) ---
    var kl = zl.append("g").attr("class", "country-markers");
    var countries = [];
    continents.forEach(function (c) {
      c.regions.forEach(function (r) {
        r.countries.forEach(function (ct) {
          if (ct.lat != null && ct.stories > 0) {
            countries.push({ country: ct, region: r, continent: c });
          }
        });
      });
    });
    countries.sort(function (a, b) { return b.country.stories - a.country.stories; });
    var km = kl.selectAll("g.kmarker")
      .data(countries, function (d) { return d.country.name; })
      .join("g").attr("class", "marker kmarker")
      .attr("transform", function (d) { return "translate(" + projection([d.country.lon, d.country.lat]) + ")"; })
      .attr("tabindex", 0).attr("role", "button")
      .attr("aria-label", function (d) { return d.country.label; });
    km.append("g").attr("class", "zoom-fix");
    km.each(function (d) {
      var inner = d3.select(this).select(".zoom-fix");
      var color = continentColor(d.continent.slug);
      d3.select(this).style("filter", "drop-shadow(0 0 5px " + hexToRgba(color, 0.7) + ")");
      var r = 4 + Math.min(7, Math.sqrt(d.country.stories) * 2);
      inner.append("circle").attr("class", "halo").attr("r", r + 4.5);
      inner.append("circle").attr("class", "cdot").attr("r", r).attr("fill", color)
        .attr("stroke", "rgba(255,255,255,0.92)").attr("stroke-width", 1);
      inner.append("title").text(d.country.label + " · " + d.country.stories + " stories");
    });
    onTap(km, function (d) { selectCountry(d.country.name, true); });
    km.on("keydown", function (e, d) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectCountry(d.country.name, true); }
    });

    mapZoom = d3.zoom()
      .scaleExtent([1, 8])
      .translateExtent([[-W * 0.6, -H * 0.6], [W * 1.6, H * 1.6]])
      .on("zoom", function (e) {
        zl.attr("transform", e.transform);
        applyCounterScale();
        var k = e.transform.k;
        svg.classed("level-continent", k < Z_REGION)
           .classed("level-region", k >= Z_REGION && k < Z_COUNTRY)
           .classed("level-country", k >= Z_COUNTRY);
        zoomResetBtn.classList.toggle("hidden", k <= 1.05);
        if (zoomTipEl) zoomTipEl.classList.toggle("hidden", k > 1.05);
      });
    svg.call(mapZoom);
    svg.classed("level-continent", true);

    zoomResetBtn.addEventListener("click", function () {
      trackEvent("reset_zoom");
      svg.transition().duration(450).call(mapZoom.transform, d3.zoomIdentity);
    });
  }

  // ---------------------------------------------------------------------------
  // Navigation: breadcrumb + chips
  // ---------------------------------------------------------------------------
  function crumbHTML() {
    var parts = ['<button type="button" class="crumb" data-nav="world">🌐 World</button>'];
    if (active.continent) {
      var c = findContinent(active.continent);
      parts.push('<button type="button" class="crumb" data-nav="continent">' + esc(c ? c.name : active.continent) + "</button>");
    }
    if (active.region) {
      var r = findRegion(active.continent, active.region);
      parts.push('<button type="button" class="crumb" data-nav="region">' + esc(r ? r.name : active.region) + "</button>");
    }
    if (active.country) {
      var f = findCountry(active.country);
      parts.push('<span class="crumb current">' + esc(f ? f.country.label : active.country) + "</span>");
    }
    return parts.join('<span class="crumb-sep">›</span>');
  }

  function drawNav() {
    var html = '<nav class="breadcrumb" aria-label="Location">' + crumbHTML() + "</nav>";
    html += '<div class="chips-row">';
    continents.forEach(function (c) {
      html += '<button type="button" class="chip' + (c.slug === active.continent ? " active" : "") +
        '" data-continent="' + esc(c.slug) + '" style="--chip-color:' + continentColor(c.slug) + '">' +
        esc(c.name) + "</button>";
    });
    html += "</div>";
    chipsEl.innerHTML = html;
    chipsEl.querySelectorAll("[data-nav]").forEach(function (b) {
      b.addEventListener("click", function () {
        var nav = b.getAttribute("data-nav");
        if (nav === "world") goWorld();
        else if (nav === "continent") selectContinent(active.continent, true);
        else if (nav === "region") selectRegion(active.continent, active.region, true);
      });
    });
    chipsEl.querySelectorAll("[data-continent]").forEach(function (b) {
      b.addEventListener("click", function () { selectContinent(b.getAttribute("data-continent"), true); });
    });
  }

  function markActive() {
    svg.selectAll("g.cmarker")
      .classed("active", function (d) { return d.slug === active.continent && !active.region; });
    svg.selectAll("g.rmarker")
      .classed("active", function (d) { return d.region.slug === active.region && !active.country; });
    svg.selectAll("g.kmarker")
      .classed("active", function (d) { return d.country.name === active.country; });
    drawNav();
  }

  // ---------------------------------------------------------------------------
  // SMA-496: sub-level drill chips inside story panels. The next drill level
  // is one tap away from where the user already is — no map manipulation
  // needed (continent panels get region chips, region panels get country
  // chips). Reuses the existing .chip styling.
  // ---------------------------------------------------------------------------
  function subDrillChipsHTML(items, kind) {
    if (!items || !items.length) return "";
    var btns = items.map(function (it) {
      var label = kind === "region" ? it.name : (it.label || it.name);
      var key = kind === "region" ? it.slug : it.name;
      return '<button type="button" class="chip sub" data-drill-kind="' + kind +
        '" data-drill-key="' + esc(key) + '">' + esc(label) + "</button>";
    }).join("");
    return '<div class="drill-row" aria-label="Drill down"><span class="drill-label">Drill down:</span>' + btns + "</div>";
  }
  function bindSubDrillChips(onTap) {
    storiesEl.querySelectorAll("[data-drill-key]").forEach(function (b) {
      b.addEventListener("click", function () {
        onTap(b.getAttribute("data-drill-kind"), b.getAttribute("data-drill-key"));
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Panel
  // ---------------------------------------------------------------------------
  // SMA-513: per-story share affordance. Each card links to the story's
  // canonical /country/<slug> deep link (not the publisher URL) so shares
  // drive traffic back to the map. Native share sheet on mobile, clipboard
  // fallback on desktop.
  function storyCard(s, level) {
    var pub = s.published_at ? relTime(s.published_at) : relTime(s.fetched_at);
    var favicon = "";
    try {
      var host = new URL(s.url).hostname.replace(/^www\./, "");
      favicon = '<img class="favicon" src="https://www.google.com/s2/favicons?domain=' +
        esc(host) + '&sz=32" alt="" loading="lazy" onerror="this.remove()">';
    } catch (e) { /* leave favicon empty on unparseable URL */ }
    var shareBtn = '<button type="button" class="share-story" data-slug="' + esc(countrySlug(s.country || "")) +
      '" data-title="' + esc(s.title || "") + '" data-level="' + esc(level || "") +
      '" title="Share this story" aria-label="Share this story">↗ Share</button>';
    return (
      '<article class="story" data-source="' + esc(s.source || "") + '">' +
        '<h3>' + (isNewStory(s) ? '<span class="newdot" title="New since your last visit">NEW</span>' : "") + favicon + '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.title) + "</a></h3>" +
        (s.summary ? "<p>" + esc(s.summary) + "</p>" : "") +
        '<div class="meta"><span>' + esc(s.source || "") + '</span>' +
        "<span>" + esc(pub) + "</span>" +
        '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">Read →</a>' + shareBtn + "</div>" +
      "</article>"
    );
  }

  // SMA-460: fire a per-render impression event so story CTR
  // (click_story / stories_shown) is measurable per view level.
  // One event per panel render, not per card, to avoid event spam.
  function renderStories(level, title, meta, items, extraHTML) {
    panelTitle.textContent = title;
    panelMeta.textContent = meta;
    var html = extraHTML || "";
    if (!items.length) {
      html += '<p class="hint">No headlines yet — the next daily crawl will pick this up.</p>';
    } else {
      html += items.map(function (s) { return storyCard(s, level); }).join("");
    }
    storiesEl.innerHTML = html;
    trackEvent("stories_shown", { level: level, count: items.length });
    if (window.innerWidth <= 900) {
      document.getElementById("panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function fetchHeadlines(params) {
    return fetch("/api/headlines?" + params + "&limit=15").then(function (r) { return r.json(); });
  }

  function loadWorldHeadlines() {
    // First-visit hook: show the freshest stories immediately so a new visitor
    // sees value without having to click anything (SMA-367), and every visit
    // starts with clickable headlines (SMA-366).
    panelTitle.textContent = "Top stories right now";
    panelMeta.textContent = "";
    setShareCountry(null, null);
    storiesEl.innerHTML = '<p class="hint">Loading headlines…</p>';
    fetch("/api/top-headlines?limit=15")
      .then(function (r) { return r.json(); })
      .then(function (items) {
        var hint = '<p class="hint hook">Fresh from local outlets worldwide — click a continent or region on the map to drill into local coverage.</p>';
        updateFreshBadge(items);
        renderStories("world", "Top stories right now",
          items.length ? "newest " + relTime(items[0].published_at || items[0].fetched_at) : "",
          items, hint);
      })
      .catch(function () {
        storiesEl.innerHTML = '<p class="hint">Could not load headlines. Please try again.</p>';
      });
  }

  function goWorld() {
    active = { continent: null, region: null, country: null };
    markActive();
    trackEvent("select_world");
    setPath("/");
    svg.transition().duration(450).call(mapZoom.transform, d3.zoomIdentity);
    loadWorldHeadlines();
  }

  function selectContinent(slug, zoom) {
    var c = findContinent(slug);
    if (!c) return;
    active = { continent: slug, region: null, country: null };
    markActive();
    trackEvent("select_continent", { continent: slug });
    setPath("/");
    setShareCountry(null, null);
    if (zoom) zoomTo(c.lon, c.lat, Z_REGION + 0.3);
    panelTitle.textContent = c.name;
    storiesEl.innerHTML = '<p class="hint">Loading headlines…</p>';
    panelMeta.textContent = "";
    fetchHeadlines("continent=" + encodeURIComponent(slug))
      .then(function (items) {
        renderStories("continent", c.name,
          continentStories(c) + " stories · newest " + (items.length ? relTime(items[0].published_at || items[0].fetched_at) : "—"),
          items, subDrillChipsHTML(c.regions, "region"));
        bindSubDrillChips(function (kind, key) { selectRegion(slug, key, true); });
      })
      .catch(function () {
        storiesEl.innerHTML = '<p class="hint">Could not load headlines. Please try again.</p>';
      });
  }

  function selectRegion(contSlug, slug, zoom) {
    var r = findRegion(contSlug, slug);
    if (!r) return;
    active = { continent: contSlug, region: slug, country: null };
    markActive();
    trackEvent("select_region", { region: slug });
    setPath("/");
    setShareCountry(null, null);
    if (zoom && r.lat != null) zoomTo(r.lon, r.lat, Z_COUNTRY + 0.3);
    panelTitle.textContent = r.name;
    storiesEl.innerHTML = '<p class="hint">Loading headlines…</p>';
    panelMeta.textContent = "";
    fetchHeadlines("region=" + encodeURIComponent(slug))
      .then(function (items) {
        var drillCountries = (r.countries || []).filter(function (ct) { return ct.stories > 0; });
        renderStories("region", r.name,
          regionStories(r) + " stories · newest " + (items.length ? relTime(items[0].published_at || items[0].fetched_at) : "—"),
          items, subDrillChipsHTML(drillCountries, "country"));
        bindSubDrillChips(function (kind, key) { selectCountry(key, true); });
      })
      .catch(function () {
        storiesEl.innerHTML = '<p class="hint">Could not load headlines. Please try again.</p>';
      });
  }

  function selectCountry(admin, zoom) {
    var f = findCountry(admin);
    if (!f) return;
    active = { continent: f.continent.slug, region: f.region.slug, country: admin };
    markActive();
    trackEvent("select_country", { country: admin });
    setPath("/country/" + countrySlug(admin));
    setShareCountry(f.country.label, admin);
    if (zoom && f.country.lat != null) zoomTo(f.country.lon, f.country.lat, Math.max(d3.zoomTransform(svg.node()).k, 5));
    var ct = f.country;
    storiesEl.innerHTML = '<p class="hint">Loading headlines…</p>';
    panelMeta.textContent = "";
    fetchHeadlines("country=" + encodeURIComponent(admin))
      .then(function (items) {
        var sources = (ct.sources || []).length
          ? '<div class="sources"><span class="sources-label">Sources:</span> ' +
            ct.sources.map(function (s) { return "<span class=\"source-tag\">" + esc(s) + "</span>"; }).join(" ") +
            "</div>"
          : "";
        renderStories("country", ct.label,
          (ct.stories || items.length) + " stories · " + f.region.name,
          items, sources);
      })
      .catch(function () {
        storiesEl.innerHTML = '<p class="hint">Could not load headlines. Please try again.</p>';
      });
  }

  function refreshStatus() {
    return fetch("/api/status")
      .then(function (r) { return r.json(); })
      .then(function (st) {
        var total = st.total_count || 0;
        var latest = st.last_fetched;
        updatedEl.textContent = latest
          ? "Updated " + relTime(latest) + " · " + total + " stories"
          : "No stories yet";
        return latest;
      })
      .catch(function () { updatedEl.textContent = "status unavailable"; return null; });
  }

  // SMA-487: the Refresh button is gone (refresh_headlines=0 in 7d across
  // 68 sessions). Freshness stays passive: refreshStatus() keeps the
  // "Updated ..." line current on load + every 60s, and freshBadge covers
  // new-arrival discovery.


  panelClose.addEventListener("click", goWorld);
  freshBadge.addEventListener("click", function () {
    freshBadge.classList.add("hidden");
  });

  // Track outbound story clicks (delegated; story cards are re-rendered).
  storiesEl.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest("a") : null;
    if (!a || !storiesEl.contains(a)) return;
    var art = a.closest("article");
    trackEvent("click_story", {
      level: active.country ? "country" : active.region ? "region" : "continent",
      source: art ? art.getAttribute("data-source") || "" : "",
    });
  });

  // Per-story share affordance (SMA-513): delegated; story cards are
  // re-rendered. Fires share_story {level, country, method} in GA4.
  storiesEl.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest ? e.target.closest(".share-story") : null;
    if (!btn || !storiesEl.contains(btn)) return;
    var slug = btn.getAttribute("data-slug");
    if (!slug) return;
    var title = btn.getAttribute("data-title") || "Global News Map";
    var url = CANONICAL_BASE + "/country/" + slug;
    var done = function (method) {
      trackEvent("share_story", {
        level: btn.getAttribute("data-level") || "unknown",
        country: slug,
        method: method,
      });
    };
    var confirmCopy = function () {
      var t = btn.textContent;
      btn.textContent = "✓ Copied";
      setTimeout(function () { btn.textContent = t; }, 1500);
    };
    if (navigator.share) {
      navigator.share({ title: title, text: title, url: url }).then(function () {
        done("webshare");
      }, function () { /* dismissed — not a share */ });
      return;
    }
    copyText(url).then(function () {
      confirmCopy();
      done("clipboard");
    }, function () {
      window.prompt("Copy this link:", url);
      done("prompt");
    });
  });

  var worldFeatures = [];

  // Country search box (SMA-393): text search over the already-loaded
  // /api/hierarchy data — no new API. Enter/pick selects via the same
  // selectCountry/selectRegion/selectContinent path as a map click.
  var searchInput = document.getElementById("countrySearch");
  var searchResultsEl = document.getElementById("searchResults");
  var searchIndex = [];   // {kind, label, sub, hay, ...ids}
  var searchMatches = [];
  var searchSel = -1;

  function buildSearchIndex() {
    searchIndex = [];
    continents.forEach(function (c) {
      searchIndex.push({
        kind: "continent", label: c.name, sub: "",
        hay: c.name.toLowerCase(), slug: c.slug
      });
      c.regions.forEach(function (r) {
        searchIndex.push({
          kind: "region", label: r.name, sub: c.name,
          hay: (r.name + " " + c.name).toLowerCase(),
          contSlug: c.slug, slug: r.slug
        });
        r.countries.forEach(function (ct) {
          searchIndex.push({
            kind: "country", label: ct.label || ct.name, sub: r.name + " · " + c.name,
            hay: ((ct.label || "") + " " + ct.name + " " + r.name).toLowerCase(),
            admin: ct.name
          });
        });
      });
    });
  }

  function searchPick(item) {
    closeSearch();
    searchInput.value = "";
    trackEvent("search_country", { kind: item.kind, value: item.label });
    if (item.kind === "country") selectCountry(item.admin, true);
    else if (item.kind === "region") selectRegion(item.contSlug, item.slug, true);
    else selectContinent(item.slug, true);
  }

  function closeSearch() {
    searchResultsEl.classList.add("hidden");
    searchResultsEl.innerHTML = "";
    searchInput.setAttribute("aria-expanded", "false");
    searchMatches = [];
    searchSel = -1;
  }

  function paintSearchSel() {
    var items = searchResultsEl.querySelectorAll(".search-item");
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("active", i === searchSel);
      items[i].setAttribute("aria-selected", i === searchSel ? "true" : "false");
    }
  }

  function renderSearch(q) {
    var query = q.trim().toLowerCase();
    if (!query) { closeSearch(); return; }
    var words = query.split(/\s+/);
    var matches = searchIndex.filter(function (it) {
      return words.every(function (w) { return it.hay.indexOf(w) !== -1; });
    });
    var rank = { country: 0, region: 1, continent: 2 };
    matches.sort(function (a, b) {
      var sa = score(a), sb = score(b);
      return (sa - sb) || (rank[a.kind] - rank[b.kind]) ||
        (a.label < b.label ? -1 : a.label > b.label ? 1 : 0);
    });
    function score(it) {
      var l = it.label.toLowerCase();
      if (l === query) return 0;
      if (l.indexOf(query) === 0) return 1;
      return 2;
    }
    searchMatches = matches.slice(0, 8);
    searchSel = -1;
    if (!searchMatches.length) {
      searchResultsEl.innerHTML =
        '<li class="search-empty">No place matches <strong>' + esc(q.trim()) +
        '</strong> — try a country or region name.</li>';
    } else {
      searchResultsEl.innerHTML = searchMatches.map(function (it, i) {
        return '<li role="option" aria-selected="false">' +
          '<button type="button" class="search-item" data-i="' + i + '">' +
          esc(it.label) +
          (it.sub ? ' <span class="sub">' + esc(it.sub) + "</span>" : "") +
          '<span class="kind">' + it.kind + "</span></button></li>";
      }).join("");
    }
    searchResultsEl.classList.remove("hidden");
    searchInput.setAttribute("aria-expanded", "true");
  }

  searchInput.addEventListener("input", function () { renderSearch(searchInput.value); });

  searchInput.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      searchInput.value = "";
      closeSearch();
      return;
    }
    if (searchResultsEl.classList.contains("hidden")) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      var n = searchMatches.length;
      if (!n) return;
      searchSel = e.key === "ArrowDown"
        ? (searchSel + 1) % n
        : (searchSel - 1 + n) % n;
      paintSearchSel();
    } else if (e.key === "Enter") {
      e.preventDefault();
      var item = searchMatches[searchSel >= 0 ? searchSel : 0];
      if (item) searchPick(item);
    }
  });

  searchResultsEl.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest ? e.target.closest(".search-item") : null;
    if (!btn) return;
    var item = searchMatches[parseInt(btn.getAttribute("data-i"), 10)];
    if (item) searchPick(item);
  });

  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target.closest(".search-wrap") : null;
    if (!searchResultsEl.classList.contains("hidden") && !t) {
      closeSearch();
    }
  });

  Promise.all([
    fetch("/api/hierarchy").then(function (r) { return r.json(); }),
    fetch("/static/data/countries-110m.geojson").then(function (r) { return r.json(); })
  ]).then(function (res) {
    continents = res[0].continents;
    worldFeatures = res[1].features;
    buildSearchIndex();
    drawMap();
    drawNav();
    // SMA-399 deep link: a /country/<slug> load boots straight into that
    // country's view (map zoom + story panel). The server injects
    // window.GNM_INITIAL_COUNTRY for those loads; the pathname fallback
    // covers in-app history entries. SMA-511 adds the same for
    // /region/<slug> via window.GNM_INITIAL_REGION ([contSlug, regionSlug]).
    var initialCountry = window.GNM_INITIAL_COUNTRY || null;
    var initialRegion = window.GNM_INITIAL_REGION || null;
    if (!initialCountry) {
      var pm = /^\/country\/([a-z0-9-]+)\/?$/.exec(window.location.pathname || "");
      if (pm) {
        var want = pm[1];
        continents.forEach(function (c) {
          c.regions.forEach(function (r) {
            r.countries.forEach(function (ct) {
              if (countrySlug(ct.name) === want) initialCountry = ct.name;
            });
          });
        });
      }
    }
    if (!initialRegion) {
      var rpm = /^\/region\/([a-z0-9-]+)\/?$/.exec(window.location.pathname || "");
      if (rpm) {
        var rwant = rpm[1];
        continents.forEach(function (c) {
          c.regions.forEach(function (r) {
            if (r.slug === rwant) initialRegion = [c.slug, r.slug];
          });
        });
      }
    }
    if (initialCountry && findCountry(initialCountry)) selectCountry(initialCountry, true);
    else if (initialRegion && findRegion(initialRegion[0], initialRegion[1])) {
      selectRegion(initialRegion[0], initialRegion[1], true);
      // selectRegion() resets the path to "/"; restore the deep-link URL so
      // the region page stays shareable and canonical in the address bar.
      setPath("/region/" + initialRegion[1]);
    }
    else loadWorldHeadlines();
    refreshStatus();
    setInterval(refreshStatus, 60000);
  }).catch(function (err) {
    storiesEl.innerHTML = '<p class="hint">Failed to load the map. Please reload the page.</p>';
    console.error(err);
  });
})();
