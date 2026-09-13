/* Global News Map frontend.
 * Map rendering is fully self-contained: bundled D3 + bundled Natural Earth
 * GeoJSON. No external tile servers, no CDN calls at runtime.
 *
 * Zoom drill-down: at low zoom the 6 region markers show; zooming past
 * ZOOM_THRESHOLD fades in country-level markers. Countries are attributed
 * from already-fetched region headlines by keyword matching on
 * title + summary (see ALIASES).
 */
(function () {
  "use strict";

  var W = 960, H = 500;
  var ZOOM_THRESHOLD = 2.2;
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
  var zoomResetBtn = document.getElementById("zoomReset");
  var zoomTipEl = document.getElementById("zoomTip");

  var regions = [];
  var worldFeatures = [];
  var activeSlug = null;       // region slug, or "country:<ADMIN>"
  var activeCountry = null;    // ADMIN name of selected country, if any
  var countryIndex = {};       // ADMIN -> { stories: [...], regionSlug }
  var mapZoom = null;

  // Region color system: one distinctive hue per region. Markers, chips and
  // glows all draw from here so the map reads as one coherent design.
  var REGION_COLORS = {
    "north-america": { c: "#60a5fa", dark: "#1e40af" },
    "latin-america": { c: "#34d399", dark: "#065f46" },
    "europe":        { c: "#a78bfa", dark: "#5b21b6" },
    "africa":        { c: "#fbbf24", dark: "#b45309" },
    "middle-east":   { c: "#fb7185", dark: "#9f1239" },
    "asia-pacific":  { c: "#22d3ee", dark: "#0e7490" }
  };
  function regionColor(slug) {
    var r = REGION_COLORS[slug];
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

  // ---------------------------------------------------------------------------
  // Country attribution
  // ---------------------------------------------------------------------------
  // ADMIN name -> match terms (lowercase). A term prefixed with "re:" is a raw
  // regex source (case-insensitive). Everything else matches on word
  // boundaries. Matching runs against title + summary only -- never the
  // source field (avoids e.g. "France 24" false positives).
  var ALIASES = {
    "United States of America": ["united states", "u.s.", "usa", "washington", "white house", "pentagon"],
    "Canada": ["canada", "canadian", "ottawa", "toronto", "vancouver", "montreal", "british columbia"],
    "Mexico": ["mexico", "mexican", "mexico city"],
    "Guatemala": ["guatemala", "guatemalan"],
    "Honduras": ["honduras", "honduran"],
    "El Salvador": ["el salvador", "salvadoran"],
    "Nicaragua": ["nicaragua", "nicaraguan"],
    "Costa Rica": ["costa rica", "costa rican"],
    "Panama": ["panama", "panamanian"],
    "Cuba": ["cuba", "cuban", "havana"],
    "Haiti": ["haiti", "haitian"],
    "Dominican Republic": ["dominican republic", "dominican"],
    "Jamaica": ["jamaica", "jamaican"],
    "Puerto Rico": ["puerto rico"],
    "Greenland": ["greenland"],
    "Brazil": ["brazil", "brazilian", "brasilia", "são paulo", "sao paulo", "rio de janeiro"],
    "Argentina": ["argentina", "argentine", "buenos aires"],
    "Chile": ["chile", "chilean", "santiago"],
    "Peru": ["peru", "peruvian", "lima"],
    "Colombia": ["colombia", "colombian", "bogotá", "bogota"],
    "Venezuela": ["venezuela", "venezuelan", "caracas"],
    "Ecuador": ["ecuador", "ecuadorean", "quito"],
    "Bolivia": ["bolivia", "bolivian", "la paz"],
    "Paraguay": ["paraguay", "paraguayan"],
    "Uruguay": ["uruguay", "uruguayan"],
    "United Kingdom": ["united kingdom", "u.k.", "britain", "england", "english", "london", "re:\\bbritish\\b(?!\\s+columbia)"],
    "Ireland": ["ireland", "irish", "dublin"],
    "France": ["france", "french", "paris", "macron"],
    "Germany": ["germany", "german", "berlin"],
    "Netherlands": ["netherlands", "dutch", "amsterdam", "the hague"],
    "Belgium": ["belgium", "belgian", "brussels"],
    "Spain": ["spain", "spanish", "madrid", "barcelona"],
    "Portugal": ["portugal", "portuguese", "lisbon"],
    "Italy": ["italy", "italian", "rome", "milan", "vatican", "pope", "holy see"],
    "Switzerland": ["switzerland", "swiss", "geneva", "zurich"],
    "Austria": ["austria", "austrian", "vienna"],
    "Czechia": ["czech", "czechia", "prague"],
    "Poland": ["poland", "polish", "warsaw"],
    "Hungary": ["hungary", "hungarian", "budapest"],
    "Romania": ["romania", "romanian", "bucharest"],
    "Greece": ["greece", "greek", "athens"],
    "Sweden": ["sweden", "swedish", "stockholm"],
    "Norway": ["norway", "norwegian", "oslo"],
    "Denmark": ["denmark", "danish", "copenhagen"],
    "Finland": ["finland", "finnish", "helsinki"],
    "Iceland": ["iceland", "icelandic"],
    "Ukraine": ["ukraine", "ukrainian", "kyiv", "kiev", "zelensky"],
    "Belarus": ["belarus", "belarusian", "minsk"],
    "Moldova": ["moldova", "moldovan", "chisinau"],
    "Russia": ["russia", "russian", "moscow", "kremlin", "putin"],
    "Turkey": ["turkey", "turkish", "türkiye", "turkiye", "ankara", "istanbul", "erdogan"],
    "Georgia": ["georgia", "georgian", "tbilisi"],
    "Armenia": ["armenia", "armenian", "yerevan"],
    "Azerbaijan": ["azerbaijan", "azerbaijani", "baku"],
    "Serbia": ["serbia", "serbian", "belgrade"],
    "Croatia": ["croatia", "croatian"],
    "Bosnia and Herzegovina": ["bosnia", "bosnian", "sarajevo", "herzegovina"],
    "Albania": ["albania", "albanian"],
    "North Macedonia": ["north macedonia", "macedonian", "skopje"],
    "Kosovo": ["kosovo"],
    "Cyprus": ["cyprus", "cypriot"],
    "Israel": ["israel", "israeli", "tel aviv", "jerusalem", "netanyahu"],
    "Palestine": ["palestine", "palestinian", "gaza", "west bank", "ramallah", "hamas"],
    "Lebanon": ["lebanon", "lebanese", "beirut", "hezbollah"],
    "Syria": ["syria", "syrian", "damascus", "assad"],
    "Jordan": ["jordan", "jordanian", "amman"],
    "Iraq": ["iraq", "iraqi", "baghdad"],
    "Iran": ["iran", "iranian", "tehran"],
    "Saudi Arabia": ["saudi arabia", "saudi", "riyadh"],
    "Yemen": ["yemen", "yemeni", "sanaa", "sana'a", "houthi"],
    "Qatar": ["qatar", "qatari", "doha"],
    "United Arab Emirates": ["united arab emirates", "u.a.e.", "emirati", "dubai", "abu dhabi"],
    "Kuwait": ["kuwait", "kuwaiti"],
    "Bahrain": ["bahrain", "bahraini"],
    "Oman": ["oman", "omani", "muscat"],
    "Egypt": ["egypt", "egyptian", "cairo"],
    "Morocco": ["morocco", "moroccan", "rabat"],
    "Algeria": ["algeria", "algerian", "algiers"],
    "Tunisia": ["tunisia", "tunisian", "tunis"],
    "Libya": ["libya", "libyan", "tripoli"],
    "Sudan": ["re:(?<!south )\\bsudan\\b", "khartoum", "sudanese", "darfur"],
    "South Sudan": ["south sudan", "juba"],
    "Ethiopia": ["ethiopia", "ethiopian", "addis ababa", "tigray"],
    "Somalia": ["somalia", "somali", "mogadishu", "somaliland"],
    "Kenya": ["kenya", "kenyan", "nairobi"],
    "Uganda": ["uganda", "ugandan", "kampala"],
    "United Republic of Tanzania": ["tanzania", "tanzanian", "dar es salaam", "dodoma"],
    "Rwanda": ["rwanda", "rwandan", "kigali"],
    "Democratic Republic of the Congo": ["democratic republic of the congo", "democratic republic of congo", "dr congo", "drc", "kinshasa", "congolese", "re:(?<!republic of the )(?<!republic of )\\bcongo\\b"],
    "Republic of the Congo": ["republic of the congo", "republic of congo", "brazzaville"],
    "Nigeria": ["nigeria", "nigerian", "lagos", "abuja"],
    "Niger": ["re:\\bniger\\b", "niamey", "nigerien"],
    "Mali": ["mali", "malian", "bamako", "timbuktu"],
    "Burkina Faso": ["burkina faso", "burkinabe", "ouagadougou"],
    "Senegal": ["senegal", "senegalese", "dakar"],
    "Guinea": ["re:(?<!papua new )(?<!equatorial )\\bguinea\\b(?!\\s*-\\s*bissau)", "conakry"],
    "Guinea-Bissau": ["guinea-bissau", "bissau"],
    "Sierra Leone": ["sierra leone", "freetown"],
    "Liberia": ["liberia", "liberian", "monrovia"],
    "Ivory Coast": ["ivory coast", "ivorian", "abidjan", "côte d'ivoire"],
    "Ghana": ["ghana", "ghanaian", "accra"],
    "Chad": ["chad", "chadian", "n'djamena"],
    "Cameroon": ["cameroon", "cameroonian", "yaoundé", "yaounde"],
    "Central African Republic": ["central african republic"],
    "Gabon": ["gabon", "gabonese"],
    "Angola": ["angola", "angolan", "luanda"],
    "Zambia": ["zambia", "zambian", "lusaka"],
    "Zimbabwe": ["zimbabwe", "zimbabwean", "harare"],
    "Mozambique": ["mozambique", "mozambican", "maputo"],
    "Madagascar": ["madagascar", "malagasy"],
    "South Africa": ["south africa", "south african", "johannesburg", "pretoria", "cape town"],
    "Namibia": ["namibia", "namibian"],
    "Botswana": ["botswana"],
    "eSwatini": ["eswatini", "swaziland", "swazi"],
    "China": ["china", "chinese", "beijing", "hong kong", "shanghai", "xi jinping"],
    "Mongolia": ["mongolia", "mongolian"],
    "North Korea": ["north korea", "pyongyang", "kim jong"],
    "South Korea": ["south korea", "seoul", "re:(?<!north )\\bkorea\\b", "re:(?<!north )\\bkorean\\b"],
    "Japan": ["japan", "japanese", "tokyo", "osaka"],
    "Taiwan": ["taiwan", "taiwanese", "taipei"],
    "Philippines": ["philippines", "philippine", "filipino", "manila"],
    "Vietnam": ["vietnam", "vietnamese", "hanoi"],
    "Laos": ["laos", "laotian"],
    "Cambodia": ["cambodia", "cambodian", "phnom penh"],
    "Thailand": ["thailand", "thai", "bangkok"],
    "Myanmar": ["myanmar", "burma", "burmese", "rohingya"],
    "Malaysia": ["malaysia", "malaysian", "kuala lumpur"],
    "Singapore": ["singapore", "singaporean"],
    "Indonesia": ["indonesia", "indonesian", "jakarta", "bali"],
    "Bangladesh": ["bangladesh", "bangladeshi", "dhaka"],
    "India": ["india", "indian", "delhi", "new delhi", "mumbai", "modi"],
    "Pakistan": ["pakistan", "pakistani", "islamabad", "karachi"],
    "Sri Lanka": ["sri lanka", "colombo"],
    "Nepal": ["nepal", "nepalese", "kathmandu"],
    "Afghanistan": ["afghanistan", "afghan", "kabul", "taliban"],
    "Kazakhstan": ["kazakhstan", "kazakh"],
    "Uzbekistan": ["uzbekistan", "uzbek"],
    "Australia": ["australia", "australian", "sydney", "canberra", "melbourne"],
    "New Zealand": ["new zealand", "auckland"],
    "Papua New Guinea": ["papua new guinea"],
    "Fiji": ["fiji", "fijian"]
  };

  var DISPLAY_OVERRIDES = {
    "United States of America": "United States",
    "United Republic of Tanzania": "Tanzania",
    "Democratic Republic of the Congo": "DR Congo",
    "Republic of the Congo": "Congo",
    "eSwatini": "Eswatini",
    "Bosnia and Herzegovina": "Bosnia"
  };

  function escRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function buildMatchers() {
    return worldFeatures.map(function (f) {
      var admin = f.properties.ADMIN;
      var terms = ALIASES[admin] || [admin.toLowerCase()];
      return {
        admin: admin,
        res: terms.map(function (t) {
          if (t.indexOf("re:") === 0) return new RegExp(t.slice(3), "i");
          // Trailing (?!\w) instead of \b: a term ending in "." (e.g. "u.s.")
          // would never match with \b, since there is no word boundary
          // between two non-word characters.
          return new RegExp("\\b" + escRegex(t) + "(?!\\w)", "i");
        })
      };
    });
  }

  var matchers = null;

  function attributeCountries(headlinesByRegion) {
    if (!matchers) matchers = buildMatchers();
    var idx = {};
    Object.keys(headlinesByRegion).forEach(function (slug) {
      (headlinesByRegion[slug] || []).forEach(function (s) {
        var text = (s.title || "") + " " + (s.summary || "");
        for (var i = 0; i < matchers.length; i++) {
          var m = matchers[i];
          for (var j = 0; j < m.res.length; j++) {
            if (m.res[j].test(text)) {
              var e = idx[m.admin];
              if (!e) e = idx[m.admin] = { stories: [], regionSlug: slug };
              e.stories.push(s);
              break;
            }
          }
        }
      });
    });
    return idx;
  }

  function countryPos(f) {
    var p = f.properties;
    var lon = p.LABEL_X, lat = p.LABEL_Y;
    if (typeof lon !== "number" || typeof lat !== "number") {
      var c = d3.geoCentroid(f);
      lon = c[0]; lat = c[1];
    }
    return projection([lon, lat]);
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

  function drawMap(world) {
    worldFeatures = world.features;

    // Gradient defs: ocean vignette + per-region "lit dot" gradients
    // (white-hot core -> region color -> deep edge).
    var defs = svg.append("defs");
    var og = defs.append("radialGradient")
      .attr("id", "oceanGrad").attr("cx", "50%").attr("cy", "42%").attr("r", "78%");
    og.append("stop").attr("offset", "0%").attr("stop-color", "#172a4d");
    og.append("stop").attr("offset", "100%").attr("stop-color", "#0a1426");
    Object.keys(REGION_COLORS).forEach(function (slug) {
      var rc = REGION_COLORS[slug];
      var g = defs.append("radialGradient")
        .attr("id", "dotg-" + slug).attr("cx", "38%").attr("cy", "32%").attr("r", "78%");
      g.append("stop").attr("offset", "0%").attr("stop-color", "#ffffff");
      g.append("stop").attr("offset", "38%").attr("stop-color", rc.c);
      g.append("stop").attr("offset", "100%").attr("stop-color", rc.dark);
    });

    var zl = svg.append("g").attr("class", "zoom-layer");
    zl.append("path").datum({ type: "Sphere" }).attr("class", "ocean").attr("d", path);
    zl.append("path").datum(d3.geoGraticule10()).attr("class", "graticule").attr("d", path);
    zl.selectAll("path.country")
      .data(world.features)
      .join("path")
      .attr("class", "country")
      .attr("d", path);

    // Region markers (visible at low zoom).
    var regionLayer = zl.append("g").attr("class", "region-markers");
    var m = regionLayer.selectAll("g.marker")
      .data(regions)
      .join("g")
      .attr("class", "marker")
      .attr("transform", function (d) { return "translate(" + projection([d.lon, d.lat]) + ")"; })
      .attr("tabindex", 0)
      .attr("role", "button")
      .attr("aria-label", function (d) { return d.name; });
    m.append("g").attr("class", "zoom-fix");
    m.style("filter", function (d) {
      return "drop-shadow(0 0 7px " + hexToRgba(regionColor(d.slug), 0.75) + ")";
    });
    var inner = m.select(".zoom-fix");
    inner.append("circle").attr("r", 16).attr("class", "pulse")
      .attr("stroke", function (d) { return regionColor(d.slug); });
    inner.append("circle").attr("r", 10.5).attr("class", "halo");
    inner.append("circle").attr("r", 6.5).attr("class", "dot")
      .attr("fill", function (d) { return "url(#dotg-" + d.slug + ")"; });
    inner.append("text").attr("y", -24).attr("class", "label").text(function (d) { return d.name; });
    onTap(m, function (d) { selectRegion(d.slug); });
    m.on("keydown", function (e, d) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectRegion(d.slug); }
    });

    // Country markers (visible past the zoom threshold; built once headlines load).
    zl.append("g").attr("class", "country-markers");

    mapZoom = d3.zoom()
      .scaleExtent([1, 8])
      .translateExtent([[-W * 0.6, -H * 0.6], [W * 1.6, H * 1.6]])
      .on("zoom", function (e) {
        zl.attr("transform", e.transform);
        applyCounterScale();
        svg.classed("zoomed-in", e.transform.k >= ZOOM_THRESHOLD);
        zoomResetBtn.classList.toggle("hidden", e.transform.k <= 1.05);
        if (zoomTipEl) zoomTipEl.classList.toggle("hidden", e.transform.k > 1.05);
      });
    svg.call(mapZoom);

    zoomResetBtn.addEventListener("click", function () {
      trackEvent("reset_zoom");
      svg.transition().duration(450).call(mapZoom.transform, d3.zoomIdentity);
    });
  }

  function buildCountryMarkers() {
    var data = Object.keys(countryIndex).map(function (admin) {
      var f = null;
      for (var i = 0; i < worldFeatures.length; i++) {
        if (worldFeatures[i].properties.ADMIN === admin) { f = worldFeatures[i]; break; }
      }
      if (!f) return null;
      var e = countryIndex[admin];
      return {
        admin: admin,
        display: DISPLAY_OVERRIDES[admin] || admin,
        stories: e.stories,
        regionSlug: e.regionSlug,
        xy: countryPos(f)
      };
    }).filter(function (d) { return d !== null; });
    data.sort(function (a, b) { return b.stories.length - a.stories.length; });

    var layer = svg.select("g.country-markers");
    var sel = layer.selectAll("g.cmarker").data(data, function (d) { return d.admin; });
    sel.exit().remove();
    var enter = sel.enter().append("g")
      .attr("class", "marker cmarker")
      .attr("tabindex", 0)
      .attr("role", "button")
      .attr("aria-label", function (d) { return d.display; });
    enter.append("g").attr("class", "zoom-fix");
    var inner = enter.select(".zoom-fix");
    inner.append("circle").attr("class", "halo").attr("fill", "none");
    inner.append("circle").attr("class", "cdot")
      .attr("fill", function (d) { return "url(#dotg-" + d.regionSlug + ")"; });
    inner.append("title").text(function (d) { return d.display + " · " + d.stories.length + " stories"; });
    onTap(enter, function (d) { selectCountry(d); });
    enter.on("keydown", function (e, d) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectCountry(d); }
    });

    var merged = enter.merge(sel);
    merged.attr("transform", function (d) { return "translate(" + d.xy + ")"; });
    merged.style("filter", function (d) {
      return "drop-shadow(0 0 5px " + hexToRgba(regionColor(d.regionSlug), 0.7) + ")";
    });
    merged.select(".cdot")
      .attr("r", function (d) { return 4 + Math.min(7, Math.sqrt(d.stories.length) * 2); });
    merged.select(".halo")
      .attr("r", function (d) { return 4 + Math.min(7, Math.sqrt(d.stories.length) * 2) + 4.5; });
    merged.select("title")
      .text(function (d) { return d.display + " · " + d.stories.length + " stories"; });
    applyCounterScale();
    updateCountryActive();
  }

  function updateCountryActive() {
    svg.selectAll("g.cmarker")
      .classed("active", function (d) { return !!activeCountry && d.admin === activeCountry; });
  }

  // ---------------------------------------------------------------------------
  // Panel
  // ---------------------------------------------------------------------------
  function drawChips() {
    chipsEl.innerHTML = "";
    regions.forEach(function (r) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "chip" + (r.slug === activeSlug ? " active" : "");
      b.textContent = r.name;
      b.style.setProperty("--chip-color", regionColor(r.slug));
      b.addEventListener("click", function () { selectRegion(r.slug); });
      chipsEl.appendChild(b);
    });
  }

  function markActive() {
    svg.selectAll("g.region-markers g.marker")
      .classed("active", function (d) { return d.slug === activeSlug; });
    updateCountryActive();
    drawChips();
  }

  function storyCard(s) {
    var pub = s.published_at ? relTime(s.published_at) : relTime(s.fetched_at);
    return (
      '<article class="story" data-source="' + esc(s.source || "") + '">' +
        '<h3><a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.title) + "</a></h3>" +
        (s.summary ? "<p>" + esc(s.summary) + "</p>" : "") +
        '<div class="meta"><span>' + esc(s.source || "") + '</span>' +
        "<span>" + esc(pub) + "</span>" +
        '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">Read →</a></div>' +
      "</article>"
    );
  }

  function renderStories(title, meta, items) {
    panelTitle.textContent = title;
    panelMeta.textContent = meta;
    if (!items.length) {
      storiesEl.innerHTML = '<p class="hint">No headlines yet. Try Refresh.</p>';
      return;
    }
    storiesEl.innerHTML = items.map(storyCard).join("");
    if (window.innerWidth <= 900) {
      document.getElementById("panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function selectRegion(slug) {
    activeSlug = slug;
    activeCountry = null;
    markActive();
    var region = regions.find(function (r) { return r.slug === slug; });
    trackEvent("select_region", { region: slug });
    panelTitle.textContent = region ? region.name : "Top stories";
    storiesEl.innerHTML = '<p class="hint">Loading headlines…</p>';
    panelMeta.textContent = "";
    fetch("/api/headlines?region=" + encodeURIComponent(slug) + "&limit=12")
      .then(function (r) { return r.json(); })
      .then(function (items) {
        renderStories(
          region ? region.name : "Top stories",
          items.length ? items.length + " stories · newest " + relTime(items[0].published_at || items[0].fetched_at) : "",
          items
        );
      })
      .catch(function () {
        storiesEl.innerHTML = '<p class="hint">Could not load headlines. Please try again.</p>';
      });
  }

  function selectCountry(d) {
    activeSlug = "country:" + d.admin;
    activeCountry = d.admin;
    markActive();
    trackEvent("select_country", { country: d.admin });
    var region = regions.find(function (r) { return r.slug === d.regionSlug; });
    storiesEl.innerHTML = '<p class="hint">Loading headlines…</p>';
    var items = d.stories.slice(0, 12);
    renderStories(
      d.display,
      d.stories.length + " stories" + (region ? " · via " + region.name : ""),
      items
    );
  }

  function loadAllHeadlines() {
    var jobs = regions.map(function (r) {
      return fetch("/api/headlines?region=" + encodeURIComponent(r.slug) + "&limit=50")
        .then(function (resp) { return resp.json(); })
        .then(function (items) { return { slug: r.slug, items: items }; })
        .catch(function () { return { slug: r.slug, items: [] }; });
    });
    return Promise.all(jobs).then(function (res) {
      var byRegion = {};
      res.forEach(function (x) { byRegion[x.slug] = x.items; });
      countryIndex = attributeCountries(byRegion);
      buildCountryMarkers();
      // If a country was selected before a refresh, re-select with new data.
      if (activeCountry && countryIndex[activeCountry]) {
        var e = countryIndex[activeCountry];
        selectCountry({
          admin: activeCountry,
          display: DISPLAY_OVERRIDES[activeCountry] || activeCountry,
          stories: e.stories,
          regionSlug: e.regionSlug
        });
      }
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
    trackEvent("refresh_headlines");
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
            loadAllHeadlines().then(function () {
              // Country re-selection (if any) is handled inside loadAllHeadlines.
              if (!activeCountry && activeSlug && activeSlug.indexOf("country:") !== 0) {
                selectRegion(activeSlug);
              }
            });
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
    activeCountry = null;
    markActive();
    panelTitle.textContent = "Top stories";
    panelMeta.textContent = "";
    storiesEl.innerHTML = '<p class="hint">Select a region on the map to see its top headlines.</p>';
  });

  // Track outbound story clicks (delegated; story cards are re-rendered).
  storiesEl.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest("a") : null;
    if (!a || !storiesEl.contains(a)) return;
    var art = a.closest("article");
    trackEvent("click_story", {
      region: activeSlug || "",
      source: art ? art.getAttribute("data-source") || "" : "",
    });
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
    return loadAllHeadlines();
  }).catch(function (err) {
    storiesEl.innerHTML = '<p class="hint">Failed to load the map. Please reload the page.</p>';
    console.error(err);
  });
})();
