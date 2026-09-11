/* Global News Map frontend.
 * Map rendering is fully self-contained: bundled D3 + bundled Natural Earth
 * GeoJSON. No external tile servers, no CDN calls at runtime.
 */
(function () {
  "use strict";

  var W = 960, H = 500;
  var svg = d3.select("#map");
  var projection = d3.geoNaturalEarth1().fitExtent([[8, 8], [W - 8, H - 8]], { type: "Sphere" });
  var path = d3.geoPath(projection);

  var storiesEl = document.getElementById("stories");
  var panelTitle = document.getElementById("panelTitle");
  var panelMeta = document.getElementById("panelMeta");
  var updatedEl = document.getElementById("updated");
  var chipsEl = document.getElementById("chips");
  var refreshBtn = document.getElementById("refreshBtn");
  var panelClose = document.getElementById("panelClose");

  var regions = [];
  var activeSlug = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

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

  function drawMap(world) {
    svg.append("path").datum({ type: "Sphere" }).attr("class", "ocean").attr("d", path);
    svg.append("path").datum(d3.geoGraticule10()).attr("class", "graticule").attr("d", path);
    svg.selectAll("path.country")
      .data(world.features)
      .join("path")
      .attr("class", "country")
      .attr("d", path);

    var g = svg.append("g").attr("class", "markers");
    var m = g.selectAll("g.marker")
      .data(regions)
      .join("g")
      .attr("class", "marker")
      .attr("transform", function (d) { return "translate(" + projection([d.lon, d.lat]) + ")"; })
      .attr("tabindex", 0)
      .attr("role", "button")
      .attr("aria-label", function (d) { return d.name; })
      .on("click", function (e, d) { selectRegion(d.slug); })
      .on("keydown", function (e, d) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectRegion(d.slug); }
      });
    m.append("circle").attr("r", 15).attr("class", "pulse");
    m.append("circle").attr("r", 6).attr("class", "dot");
    m.append("text").attr("y", -22).attr("class", "label").text(function (d) { return d.name; });
  }

  function drawChips() {
    chipsEl.innerHTML = "";
    regions.forEach(function (r) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "chip" + (r.slug === activeSlug ? " active" : "");
      b.textContent = r.name;
      b.addEventListener("click", function () { selectRegion(r.slug); });
      chipsEl.appendChild(b);
    });
  }

  function markActive() {
    svg.selectAll("g.marker").classed("active", function (d) { return d.slug === activeSlug; });
    drawChips();
  }

  function storyCard(s) {
    var pub = s.published_at ? relTime(s.published_at) : relTime(s.fetched_at);
    return (
      '<article class="story">' +
        '<h3><a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.title) + "</a></h3>" +
        (s.summary ? "<p>" + esc(s.summary) + "</p>" : "") +
        '<div class="meta"><span>' + esc(s.source || "") + '</span>' +
        "<span>" + esc(pub) + "</span>" +
        '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">Read →</a></div>' +
      "</article>"
    );
  }

  function selectRegion(slug) {
    activeSlug = slug;
    markActive();
    var region = regions.find(function (r) { return r.slug === slug; });
    panelTitle.textContent = region ? region.name : "Top stories";
    storiesEl.innerHTML = '<p class="hint">Loading headlines…</p>';
    fetch("/api/headlines?region=" + encodeURIComponent(slug) + "&limit=12")
      .then(function (r) { return r.json(); })
      .then(function (items) {
        if (!items.length) {
          storiesEl.innerHTML = '<p class="hint">No headlines yet for this region. Try Refresh.</p>';
          panelMeta.textContent = "";
          return;
        }
        panelMeta.textContent = items.length + " stories · newest " + relTime(items[0].published_at || items[0].fetched_at);
        storiesEl.innerHTML = items.map(storyCard).join("");
        if (window.innerWidth <= 900) {
          document.getElementById("panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      })
      .catch(function () {
        storiesEl.innerHTML = '<p class="hint">Could not load headlines. Please try again.</p>';
      });
  }

  function refreshStatus() {
    return fetch("/api/status")
      .then(function (r) { return r.json(); })
      .then(function (st) {
        var latest = null, total = 0;
        Object.keys(st.regions || {}).forEach(function (k) {
          var info = st.regions[k];
          total += info.count;
          if (info.last_fetched && (!latest || info.last_fetched > latest)) latest = info.last_fetched;
        });
        updatedEl.textContent = latest
          ? "Updated " + relTime(latest) + " · " + total + " stories"
          : "No stories yet";
        return latest;
      })
      .catch(function () { updatedEl.textContent = "status unavailable"; return null; });
  }

  refreshBtn.addEventListener("click", function () {
    refreshBtn.disabled = true;
    refreshBtn.textContent = "⟳ Refreshing…";
    var before = null;
    refreshStatus().then(function (latest) {
      before = latest;
      return fetch("/api/refresh", { method: "POST" });
    }).then(function () {
      var tries = 0;
      var timer = setInterval(function () {
        tries++;
        refreshStatus().then(function (latest) {
          if ((before && latest && latest > before) || tries >= 30) {
            clearInterval(timer);
            refreshBtn.disabled = false;
            refreshBtn.textContent = "⟳ Refresh";
            if (activeSlug) selectRegion(activeSlug);
          }
        });
      }, 4000);
    }).catch(function () {
      refreshBtn.disabled = false;
      refreshBtn.textContent = "⟳ Refresh";
    });
  });

  panelClose.addEventListener("click", function () {
    activeSlug = null;
    markActive();
    panelTitle.textContent = "Top stories";
    panelMeta.textContent = "";
    storiesEl.innerHTML = '<p class="hint">Select a region on the map to see its top headlines.</p>';
  });

  Promise.all([
    fetch("/api/regions").then(function (r) { return r.json(); }),
    fetch("/static/data/countries-110m.geojson").then(function (r) { return r.json(); })
  ]).then(function (res) {
    regions = res[0];
    drawMap(res[1]);
    drawChips();
    refreshStatus();
    setInterval(refreshStatus, 60000);
  }).catch(function (err) {
    storiesEl.innerHTML = '<p class="hint">Failed to load the map. Please reload the page.</p>';
    console.error(err);
  });
})();
