"""Visitor-language UI + lazy headline translation (SMA-829).

Everything here is inert unless config.TRANSLATION_ENABLED is set (default
OFF): with the flag off, detect_lang() always answers "en", localize() is a
no-op and no provider is ever called, so the site renders exactly as before.

Privacy (analytics stance, SMA-816): the visitor's language is derived per
request from the gnm_lang preference cookie (set only by the manual
switcher), Accept-Language, or Cloudflare's CF-IPCountry header. Nothing
about the visitor — IP, country, language — is stored or logged; the
database holds only per-headline translations, per-outlet languages and a
monthly character counter.

Lazy translation: a headline is translated only when a visitor asks for a
language it is not yet cached in. Translations are keyed by a hash of the
original title (db.headline_translations), so each headline is translated at
most once per language, ever. Each outlet's detected language is memoised
(db.source_languages); once an outlet is confidently known to publish in the
reader's language its headlines are never sent to the provider. A monthly
character ceiling (TRANSLATION_MONTHLY_CHAR_BUDGET) caps spend — once reached,
uncached headlines are served in the original language until the month
rolls over.
"""
import logging
import threading
import time
from datetime import datetime, timezone

import requests

from . import config, db

log = logging.getLogger("global-news-map.i18n")

DEFAULT_LANG = "en"
COOKIE_NAME = "gnm_lang"

# Native names, in switcher order.
LANGUAGES = {
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "pt": "Português",
    "it": "Italiano",
    "ar": "العربية",
    "ru": "Русский",
    "zh": "中文",
    "ja": "日本語",
    "hi": "हिन्दी",
    "tr": "Türkçe",
}
RTL = {"ar"}

# Visitor country (ISO-3166 alpha-2, from CF-IPCountry) -> UI language. Only
# consulted when Accept-Language names no supported language.
COUNTRY_LANG = {
    **dict.fromkeys(
        "ES MX AR CO CL PE VE EC GT CU BO DO HN PY SV NI CR PA UY PR GQ".split(), "es"),
    **dict.fromkeys("FR BE LU MC SN CI ML BF NE TG BJ GN CD CG GA CM MG HT".split(), "fr"),
    **dict.fromkeys("DE AT LI".split(), "de"),
    **dict.fromkeys("PT BR AO MZ CV GW ST TL".split(), "pt"),
    **dict.fromkeys("IT SM VA".split(), "it"),
    **dict.fromkeys(
        "SA AE EG IQ JO KW LB LY MA OM QA SY TN YE DZ BH SD PS MR".split(), "ar"),
    **dict.fromkeys("RU BY KZ KG".split(), "ru"),
    **dict.fromkeys("CN TW HK MO".split(), "zh"),
    "JP": "ja",
    "IN": "hi",
    "TR": "tr",
}

# --- UI chrome strings -------------------------------------------------------
# English is the source of truth and the fallback for any missing key. The
# client (app.js t()) carries the same English literals as fallbacks, so a
# page without window.GNM_I18N renders exactly as before.

STRINGS = {
    "en": {
        "search_ph": "🔍 Search {n} countries… ( / )",
        "loading": "loading…",
        "hook_title": "See what the world is reading today.",
        "hook_body": "Tap a glowing marker to read headlines from local outlets in {n} countries.",
        "hook_explore": "🌍 Take me to a trending country",
        "hook_search": "🔍 Find a country",
        "zoom_tip": "Tip: scroll or pinch to zoom — regions appear, then country-level stories.",
        "top_stories": "Top stories",
        "top_now": "Top stories right now",
        "share": "↗ Share",
        "copied": "✓ Copied",
        "select_hint": "Select a region on the map to see its top headlines.",
        "read_full": "Read the full story",
        "read_full_at": "Read the full story at {source}",
        "loading_headlines": "Loading headlines…",
        "load_failed": "Could not load headlines. Please try again.",
        "no_headlines": "No headlines yet — the next crawl (every 6 hours) will pick this up.",
        "world_hint": "Fresh from local outlets worldwide — click a continent or region on the map to drill into local coverage.",
        "stories": "{n} stories",
        "newest": "newest {t}",
        "sources": "Sources:",
        "updated": "Updated {t} · {n} stories",
        "no_stories": "No stories yet",
        "original": "Original",
        "language": "Language",
        "lang_auto": "Auto",
        "just_now": "just now",
        "m_ago": "{n}m ago",
        "h_ago": "{n}h ago",
        "d_ago": "{n}d ago",
        "cont.north-america": "North America",
        "cont.south-america": "Latin America",
        "cont.europe": "Europe",
        "cont.africa": "Africa",
        "cont.middle-east": "Middle East",
        "cont.asia-pacific": "Asia-Pacific",
    },
    "es": {
        "search_ph": "🔍 Buscar en {n} países… ( / )",
        "loading": "cargando…",
        "hook_title": "Mira lo que el mundo está leyendo hoy.",
        "hook_body": "Toca un marcador luminoso para leer titulares de medios locales de {n} países.",
        "hook_explore": "🌍 Llévame a un país en tendencia",
        "hook_search": "🔍 Buscar un país",
        "zoom_tip": "Consejo: desplázate o pellizca para hacer zoom — aparecen las regiones y luego las noticias de cada país.",
        "top_stories": "Noticias principales",
        "top_now": "Noticias principales ahora",
        "share": "↗ Compartir",
        "copied": "✓ Copiado",
        "select_hint": "Selecciona una región en el mapa para ver sus titulares principales.",
        "read_full": "Leer la noticia completa",
        "read_full_at": "Leer la noticia completa en {source}",
        "loading_headlines": "Cargando titulares…",
        "load_failed": "No se pudieron cargar los titulares. Inténtalo de nuevo.",
        "no_headlines": "Aún no hay titulares — la próxima actualización (cada 6 horas) los traerá.",
        "world_hint": "Recién llegado de medios locales de todo el mundo — haz clic en un continente o región del mapa para ver la cobertura local.",
        "stories": "{n} noticias",
        "newest": "la más reciente {t}",
        "sources": "Fuentes:",
        "updated": "Actualizado {t} · {n} noticias",
        "no_stories": "Aún no hay noticias",
        "original": "Original",
        "language": "Idioma",
        "lang_auto": "Automático",
        "just_now": "ahora mismo",
        "m_ago": "hace {n} min",
        "h_ago": "hace {n} h",
        "d_ago": "hace {n} d",
        "cont.north-america": "América del Norte",
        "cont.south-america": "América Latina",
        "cont.europe": "Europa",
        "cont.africa": "África",
        "cont.middle-east": "Oriente Medio",
        "cont.asia-pacific": "Asia-Pacífico",
    },
    "fr": {
        "search_ph": "🔍 Rechercher parmi {n} pays… ( / )",
        "loading": "chargement…",
        "hook_title": "Découvrez ce que le monde lit aujourd’hui.",
        "hook_body": "Touchez un marqueur lumineux pour lire les titres des médias locaux de {n} pays.",
        "hook_explore": "🌍 Montrez-moi un pays tendance",
        "hook_search": "🔍 Trouver un pays",
        "zoom_tip": "Astuce : faites défiler ou pincez pour zoomer — les régions apparaissent, puis l’actualité de chaque pays.",
        "top_stories": "À la une",
        "top_now": "À la une en ce moment",
        "share": "↗ Partager",
        "copied": "✓ Copié",
        "select_hint": "Sélectionnez une région sur la carte pour voir ses principaux titres.",
        "read_full": "Lire l’article complet",
        "read_full_at": "Lire l’article complet sur {source}",
        "loading_headlines": "Chargement des titres…",
        "load_failed": "Impossible de charger les titres. Veuillez réessayer.",
        "no_headlines": "Pas encore de titres — la prochaine collecte (toutes les 6 heures) s’en chargera.",
        "world_hint": "Tout frais des médias locaux du monde entier — cliquez sur un continent ou une région de la carte pour explorer la couverture locale.",
        "stories": "{n} articles",
        "newest": "le plus récent {t}",
        "sources": "Sources :",
        "updated": "Mis à jour {t} · {n} articles",
        "no_stories": "Pas encore d’articles",
        "original": "Original",
        "language": "Langue",
        "lang_auto": "Automatique",
        "just_now": "à l’instant",
        "m_ago": "il y a {n} min",
        "h_ago": "il y a {n} h",
        "d_ago": "il y a {n} j",
        "cont.north-america": "Amérique du Nord",
        "cont.south-america": "Amérique latine",
        "cont.europe": "Europe",
        "cont.africa": "Afrique",
        "cont.middle-east": "Moyen-Orient",
        "cont.asia-pacific": "Asie-Pacifique",
    },
    "de": {
        "search_ph": "🔍 {n} Länder durchsuchen… ( / )",
        "loading": "wird geladen…",
        "hook_title": "Sieh, was die Welt heute liest.",
        "hook_body": "Tippe auf eine leuchtende Markierung, um Schlagzeilen lokaler Medien aus {n} Ländern zu lesen.",
        "hook_explore": "🌍 Zeig mir ein Trendland",
        "hook_search": "🔍 Land suchen",
        "zoom_tip": "Tipp: scrollen oder zoomen — erst erscheinen Regionen, dann Meldungen pro Land.",
        "top_stories": "Top-Meldungen",
        "top_now": "Top-Meldungen gerade jetzt",
        "share": "↗ Teilen",
        "copied": "✓ Kopiert",
        "select_hint": "Wähle eine Region auf der Karte, um ihre Top-Schlagzeilen zu sehen.",
        "read_full": "Ganzen Artikel lesen",
        "read_full_at": "Ganzen Artikel bei {source} lesen",
        "loading_headlines": "Schlagzeilen werden geladen…",
        "load_failed": "Schlagzeilen konnten nicht geladen werden. Bitte erneut versuchen.",
        "no_headlines": "Noch keine Schlagzeilen — der nächste Abruf (alle 6 Stunden) holt sie.",
        "world_hint": "Frisch von lokalen Medien weltweit — klicke auf einen Kontinent oder eine Region, um die lokale Berichterstattung zu sehen.",
        "stories": "{n} Meldungen",
        "newest": "neueste {t}",
        "sources": "Quellen:",
        "updated": "Aktualisiert {t} · {n} Meldungen",
        "no_stories": "Noch keine Meldungen",
        "original": "Original",
        "language": "Sprache",
        "lang_auto": "Automatisch",
        "just_now": "gerade eben",
        "m_ago": "vor {n} Min.",
        "h_ago": "vor {n} Std.",
        "d_ago": "vor {n} T.",
        "cont.north-america": "Nordamerika",
        "cont.south-america": "Lateinamerika",
        "cont.europe": "Europa",
        "cont.africa": "Afrika",
        "cont.middle-east": "Naher Osten",
        "cont.asia-pacific": "Asien-Pazifik",
    },
    "pt": {
        "search_ph": "🔍 Pesquisar {n} países… ( / )",
        "loading": "carregando…",
        "hook_title": "Veja o que o mundo está lendo hoje.",
        "hook_body": "Toque em um marcador brilhante para ler manchetes de veículos locais de {n} países.",
        "hook_explore": "🌍 Leve-me a um país em alta",
        "hook_search": "🔍 Encontrar um país",
        "zoom_tip": "Dica: role ou faça pinça para ampliar — aparecem as regiões e depois as notícias de cada país.",
        "top_stories": "Principais notícias",
        "top_now": "Principais notícias agora",
        "share": "↗ Compartilhar",
        "copied": "✓ Copiado",
        "select_hint": "Selecione uma região no mapa para ver as principais manchetes.",
        "read_full": "Ler a notícia completa",
        "read_full_at": "Ler a notícia completa em {source}",
        "loading_headlines": "Carregando manchetes…",
        "load_failed": "Não foi possível carregar as manchetes. Tente novamente.",
        "no_headlines": "Ainda sem manchetes — a próxima coleta (a cada 6 horas) vai trazê-las.",
        "world_hint": "Direto de veículos locais do mundo todo — clique em um continente ou região do mapa para ver a cobertura local.",
        "stories": "{n} notícias",
        "newest": "mais recente {t}",
        "sources": "Fontes:",
        "updated": "Atualizado {t} · {n} notícias",
        "no_stories": "Ainda sem notícias",
        "original": "Original",
        "language": "Idioma",
        "lang_auto": "Automático",
        "just_now": "agora mesmo",
        "m_ago": "há {n} min",
        "h_ago": "há {n} h",
        "d_ago": "há {n} d",
        "cont.north-america": "América do Norte",
        "cont.south-america": "América Latina",
        "cont.europe": "Europa",
        "cont.africa": "África",
        "cont.middle-east": "Oriente Médio",
        "cont.asia-pacific": "Ásia-Pacífico",
    },
    "it": {
        "search_ph": "🔍 Cerca tra {n} paesi… ( / )",
        "loading": "caricamento…",
        "hook_title": "Scopri cosa legge il mondo oggi.",
        "hook_body": "Tocca un indicatore luminoso per leggere i titoli dei media locali di {n} paesi.",
        "hook_explore": "🌍 Portami in un paese di tendenza",
        "hook_search": "🔍 Trova un paese",
        "zoom_tip": "Suggerimento: scorri o pizzica per ingrandire — compaiono le regioni, poi le notizie di ogni paese.",
        "top_stories": "Notizie principali",
        "top_now": "Notizie principali adesso",
        "share": "↗ Condividi",
        "copied": "✓ Copiato",
        "select_hint": "Seleziona una regione sulla mappa per vederne i titoli principali.",
        "read_full": "Leggi l’articolo completo",
        "read_full_at": "Leggi l’articolo completo su {source}",
        "loading_headlines": "Caricamento dei titoli…",
        "load_failed": "Impossibile caricare i titoli. Riprova.",
        "no_headlines": "Ancora nessun titolo — il prossimo aggiornamento (ogni 6 ore) li porterà.",
        "world_hint": "Appena arrivati dai media locali di tutto il mondo — fai clic su un continente o una regione della mappa per la copertura locale.",
        "stories": "{n} notizie",
        "newest": "più recente {t}",
        "sources": "Fonti:",
        "updated": "Aggiornato {t} · {n} notizie",
        "no_stories": "Ancora nessuna notizia",
        "original": "Originale",
        "language": "Lingua",
        "lang_auto": "Automatica",
        "just_now": "adesso",
        "m_ago": "{n} min fa",
        "h_ago": "{n} h fa",
        "d_ago": "{n} g fa",
        "cont.north-america": "Nord America",
        "cont.south-america": "America Latina",
        "cont.europe": "Europa",
        "cont.africa": "Africa",
        "cont.middle-east": "Medio Oriente",
        "cont.asia-pacific": "Asia-Pacifico",
    },
    "ar": {
        "search_ph": "🔍 ابحث في {n} دولة… ( / )",
        "loading": "جارٍ التحميل…",
        "hook_title": "اكتشف ما يقرؤه العالم اليوم.",
        "hook_body": "اضغط على علامة مضيئة لقراءة عناوين وسائل الإعلام المحلية في {n} دولة.",
        "hook_explore": "🌍 خذني إلى دولة رائجة",
        "hook_search": "🔍 ابحث عن دولة",
        "zoom_tip": "نصيحة: مرّر أو اقرص للتكبير — تظهر المناطق ثم أخبار كل دولة.",
        "top_stories": "أهم الأخبار",
        "top_now": "أهم الأخبار الآن",
        "share": "↗ مشاركة",
        "copied": "✓ تم النسخ",
        "select_hint": "اختر منطقة على الخريطة لعرض أهم عناوينها.",
        "read_full": "اقرأ الخبر كاملًا",
        "read_full_at": "اقرأ الخبر كاملًا على {source}",
        "loading_headlines": "جارٍ تحميل العناوين…",
        "load_failed": "تعذّر تحميل العناوين. يُرجى المحاولة مرة أخرى.",
        "no_headlines": "لا توجد عناوين بعد — سيجلبها التحديث القادم (كل 6 ساعات).",
        "world_hint": "أحدث ما نشرته وسائل الإعلام المحلية حول العالم — انقر على قارة أو منطقة في الخريطة لاستكشاف التغطية المحلية.",
        "stories": "{n} خبر",
        "newest": "الأحدث {t}",
        "sources": "المصادر:",
        "updated": "حُدّث {t} · {n} خبر",
        "no_stories": "لا توجد أخبار بعد",
        "original": "الأصل",
        "language": "اللغة",
        "lang_auto": "تلقائي",
        "just_now": "الآن",
        "m_ago": "منذ {n} د",
        "h_ago": "منذ {n} س",
        "d_ago": "منذ {n} يوم",
        "cont.north-america": "أمريكا الشمالية",
        "cont.south-america": "أمريكا اللاتينية",
        "cont.europe": "أوروبا",
        "cont.africa": "أفريقيا",
        "cont.middle-east": "الشرق الأوسط",
        "cont.asia-pacific": "آسيا والمحيط الهادئ",
    },
    "ru": {
        "search_ph": "🔍 Поиск по {n} странам… ( / )",
        "loading": "загрузка…",
        "hook_title": "Узнайте, что сегодня читает мир.",
        "hook_body": "Нажмите на светящийся маркер, чтобы читать заголовки местных СМИ из {n} стран.",
        "hook_explore": "🌍 Покажите страну в тренде",
        "hook_search": "🔍 Найти страну",
        "zoom_tip": "Совет: прокрутите или сведите пальцы для масштаба — появятся регионы, затем новости стран.",
        "top_stories": "Главные новости",
        "top_now": "Главные новости сейчас",
        "share": "↗ Поделиться",
        "copied": "✓ Скопировано",
        "select_hint": "Выберите регион на карте, чтобы увидеть главные заголовки.",
        "read_full": "Читать полностью",
        "read_full_at": "Читать полностью на {source}",
        "loading_headlines": "Загрузка заголовков…",
        "load_failed": "Не удалось загрузить заголовки. Попробуйте ещё раз.",
        "no_headlines": "Заголовков пока нет — следующий сбор (каждые 6 часов) их добавит.",
        "world_hint": "Свежее от местных СМИ со всего мира — нажмите на континент или регион на карте, чтобы увидеть местные новости.",
        "stories": "Новостей: {n}",
        "newest": "последняя {t}",
        "sources": "Источники:",
        "updated": "Обновлено {t} · новостей: {n}",
        "no_stories": "Новостей пока нет",
        "original": "Оригинал",
        "language": "Язык",
        "lang_auto": "Автоматически",
        "just_now": "только что",
        "m_ago": "{n} мин назад",
        "h_ago": "{n} ч назад",
        "d_ago": "{n} д назад",
        "cont.north-america": "Северная Америка",
        "cont.south-america": "Латинская Америка",
        "cont.europe": "Европа",
        "cont.africa": "Африка",
        "cont.middle-east": "Ближний Восток",
        "cont.asia-pacific": "Азиатско-Тихоокеанский регион",
    },
    "zh": {
        "search_ph": "🔍 搜索 {n} 个国家… ( / )",
        "loading": "加载中…",
        "hook_title": "看看今天全世界在读什么。",
        "hook_body": "点击发光的标记，阅读 {n} 个国家本地媒体的头条新闻。",
        "hook_explore": "🌍 带我去一个热门国家",
        "hook_search": "🔍 查找国家",
        "zoom_tip": "提示：滚动或双指缩放 — 先显示地区，再显示各国新闻。",
        "top_stories": "热门新闻",
        "top_now": "此刻热门新闻",
        "share": "↗ 分享",
        "copied": "✓ 已复制",
        "select_hint": "在地图上选择一个地区，查看其热门头条。",
        "read_full": "阅读全文",
        "read_full_at": "在 {source} 阅读全文",
        "loading_headlines": "正在加载头条…",
        "load_failed": "无法加载头条，请重试。",
        "no_headlines": "暂无头条 — 下一次抓取（每 6 小时）会更新。",
        "world_hint": "来自全球本地媒体的最新消息 — 点击地图上的大洲或地区，深入了解本地报道。",
        "stories": "{n} 条新闻",
        "newest": "最新 {t}",
        "sources": "来源：",
        "updated": "更新于 {t} · {n} 条新闻",
        "no_stories": "暂无新闻",
        "original": "原文",
        "language": "语言",
        "lang_auto": "自动",
        "just_now": "刚刚",
        "m_ago": "{n} 分钟前",
        "h_ago": "{n} 小时前",
        "d_ago": "{n} 天前",
        "cont.north-america": "北美洲",
        "cont.south-america": "拉丁美洲",
        "cont.europe": "欧洲",
        "cont.africa": "非洲",
        "cont.middle-east": "中东",
        "cont.asia-pacific": "亚太地区",
    },
    "ja": {
        "search_ph": "🔍 {n}か国を検索… ( / )",
        "loading": "読み込み中…",
        "hook_title": "今日、世界が読んでいるニュースを見てみよう。",
        "hook_body": "光るマーカーをタップすると、{n}か国の地元メディアの見出しを読めます。",
        "hook_explore": "🌍 話題の国へ移動",
        "hook_search": "🔍 国を探す",
        "zoom_tip": "ヒント：スクロールまたはピンチで拡大 — 地域、続いて国別のニュースが表示されます。",
        "top_stories": "トップニュース",
        "top_now": "今のトップニュース",
        "share": "↗ 共有",
        "copied": "✓ コピーしました",
        "select_hint": "地図上の地域を選ぶと、その地域のトップ見出しが表示されます。",
        "read_full": "記事全文を読む",
        "read_full_at": "{source} で記事全文を読む",
        "loading_headlines": "見出しを読み込み中…",
        "load_failed": "見出しを読み込めませんでした。もう一度お試しください。",
        "no_headlines": "まだ見出しはありません — 次回の取得（6時間ごと）で反映されます。",
        "world_hint": "世界中の地元メディアから届いた最新ニュース — 地図上の大陸や地域をクリックして地元の報道を見てみましょう。",
        "stories": "{n}件のニュース",
        "newest": "最新 {t}",
        "sources": "情報源：",
        "updated": "{t}に更新 · {n}件のニュース",
        "no_stories": "まだニュースはありません",
        "original": "原文",
        "language": "言語",
        "lang_auto": "自動",
        "just_now": "たった今",
        "m_ago": "{n}分前",
        "h_ago": "{n}時間前",
        "d_ago": "{n}日前",
        "cont.north-america": "北米",
        "cont.south-america": "ラテンアメリカ",
        "cont.europe": "ヨーロッパ",
        "cont.africa": "アフリカ",
        "cont.middle-east": "中東",
        "cont.asia-pacific": "アジア太平洋",
    },
    "hi": {
        "search_ph": "🔍 {n} देशों में खोजें… ( / )",
        "loading": "लोड हो रहा है…",
        "hook_title": "देखिए आज दुनिया क्या पढ़ रही है।",
        "hook_body": "{n} देशों के स्थानीय समाचार माध्यमों की सुर्खियाँ पढ़ने के लिए किसी चमकते मार्कर पर टैप करें।",
        "hook_explore": "🌍 किसी ट्रेंडिंग देश पर ले चलें",
        "hook_search": "🔍 देश खोजें",
        "zoom_tip": "सुझाव: ज़ूम करने के लिए स्क्रॉल या पिंच करें — पहले क्षेत्र, फिर देश-स्तर की ख़बरें दिखेंगी।",
        "top_stories": "मुख्य ख़बरें",
        "top_now": "अभी की मुख्य ख़बरें",
        "share": "↗ साझा करें",
        "copied": "✓ कॉपी हो गया",
        "select_hint": "मुख्य सुर्खियाँ देखने के लिए मानचित्र पर कोई क्षेत्र चुनें।",
        "read_full": "पूरी ख़बर पढ़ें",
        "read_full_at": "{source} पर पूरी ख़बर पढ़ें",
        "loading_headlines": "सुर्खियाँ लोड हो रही हैं…",
        "load_failed": "सुर्खियाँ लोड नहीं हो सकीं। कृपया फिर से कोशिश करें।",
        "no_headlines": "अभी कोई सुर्खी नहीं — अगला अपडेट (हर 6 घंटे) इन्हें ले आएगा।",
        "world_hint": "दुनिया भर के स्थानीय माध्यमों से ताज़ा — स्थानीय कवरेज देखने के लिए मानचित्र पर किसी महाद्वीप या क्षेत्र पर क्लिक करें।",
        "stories": "{n} ख़बरें",
        "newest": "नवीनतम {t}",
        "sources": "स्रोत:",
        "updated": "{t} अपडेट हुआ · {n} ख़बरें",
        "no_stories": "अभी कोई ख़बर नहीं",
        "original": "मूल",
        "language": "भाषा",
        "lang_auto": "स्वचालित",
        "just_now": "अभी",
        "m_ago": "{n} मिनट पहले",
        "h_ago": "{n} घंटे पहले",
        "d_ago": "{n} दिन पहले",
        "cont.north-america": "उत्तरी अमेरिका",
        "cont.south-america": "लैटिन अमेरिका",
        "cont.europe": "यूरोप",
        "cont.africa": "अफ़्रीका",
        "cont.middle-east": "मध्य पूर्व",
        "cont.asia-pacific": "एशिया-प्रशांत",
    },
    "tr": {
        "search_ph": "🔍 {n} ülkede ara… ( / )",
        "loading": "yükleniyor…",
        "hook_title": "Dünyanın bugün ne okuduğunu görün.",
        "hook_body": "{n} ülkedeki yerel yayın organlarının manşetlerini okumak için parlayan bir işarete dokunun.",
        "hook_explore": "🌍 Beni gündemdeki bir ülkeye götür",
        "hook_search": "🔍 Ülke bul",
        "zoom_tip": "İpucu: yakınlaştırmak için kaydırın veya iki parmakla açın — önce bölgeler, sonra ülke haberleri görünür.",
        "top_stories": "Öne çıkan haberler",
        "top_now": "Şu anda öne çıkan haberler",
        "share": "↗ Paylaş",
        "copied": "✓ Kopyalandı",
        "select_hint": "Öne çıkan manşetleri görmek için haritada bir bölge seçin.",
        "read_full": "Haberin tamamını oku",
        "read_full_at": "Haberin tamamını {source} sitesinde oku",
        "loading_headlines": "Manşetler yükleniyor…",
        "load_failed": "Manşetler yüklenemedi. Lütfen tekrar deneyin.",
        "no_headlines": "Henüz manşet yok — bir sonraki tarama (6 saatte bir) bunları getirecek.",
        "world_hint": "Dünyanın dört bir yanındaki yerel yayınlardan taze haberler — yerel habercilik için haritada bir kıtaya veya bölgeye tıklayın.",
        "stories": "{n} haber",
        "newest": "en yeni {t}",
        "sources": "Kaynaklar:",
        "updated": "{t} güncellendi · {n} haber",
        "no_stories": "Henüz haber yok",
        "original": "Orijinal",
        "language": "Dil",
        "lang_auto": "Otomatik",
        "just_now": "az önce",
        "m_ago": "{n} dk önce",
        "h_ago": "{n} sa önce",
        "d_ago": "{n} gün önce",
        "cont.north-america": "Kuzey Amerika",
        "cont.south-america": "Latin Amerika",
        "cont.europe": "Avrupa",
        "cont.africa": "Afrika",
        "cont.middle-east": "Orta Doğu",
        "cont.asia-pacific": "Asya-Pasifik",
    },
}


def strings(lang):
    """The full UI string table for lang, English-filled for missing keys."""
    out = dict(STRINGS[DEFAULT_LANG])
    out.update(STRINGS.get(lang, {}))
    return out


def t(lang, key, **kw):
    s = STRINGS.get(lang, {}).get(key) or STRINGS[DEFAULT_LANG][key]
    for k, v in kw.items():
        s = s.replace("{" + k + "}", str(v))
    return s


# --- Language detection ------------------------------------------------------

def normalize(code):
    """'pt-BR' / 'zh-Hans' / 'EN' -> supported base code, or None."""
    if not code:
        return None
    base = code.strip().lower().replace("_", "-").split("-")[0]
    return base if base in LANGUAGES else None


def _from_accept_language(header):
    """First supported language in Accept-Language, honouring q-values."""
    prefs = []
    for i, part in enumerate((header or "").split(",")):
        bits = part.strip().split(";")
        if not bits[0]:
            continue
        q = 1.0
        for b in bits[1:]:
            b = b.strip()
            if b.startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        prefs.append((-q, i, bits[0]))
    for neg_q, _, tag in sorted(prefs):
        if neg_q < 0:
            lang = normalize(tag)
            if lang:
                return lang
    return None


def detect_lang(headers, cookies):
    """Visitor language for this request. Order: the manual switcher's
    preference cookie, Accept-Language, then the Cloudflare IP-country
    header. Always DEFAULT_LANG when translation is off. Nothing is stored."""
    if not config.TRANSLATION_ENABLED:
        return DEFAULT_LANG
    return (
        normalize(cookies.get(COOKIE_NAME))
        or _from_accept_language(headers.get("accept-language"))
        or COUNTRY_LANG.get((headers.get("cf-ipcountry") or "").upper())
        or DEFAULT_LANG
    )


def is_active(lang):
    """True when headlines should be localized for lang on this request."""
    return config.TRANSLATION_ENABLED and lang in LANGUAGES


# --- Providers ---------------------------------------------------------------
# Each provider takes (texts, target_lang) and returns [(translated,
# detected_source_lang)] in input order, or raises on failure.

_TIMEOUT = 4  # seconds — a slow provider must not stall page renders
_http = requests.Session()

# Provider-specific target codes where they differ from ours.
_AZURE_CODES = {"zh": "zh-Hans"}
_GOOGLE_CODES = {"zh": "zh-CN"}


def _azure(texts, lang):
    if not config.AZURE_TRANSLATOR_KEY:
        raise RuntimeError("AZURE_TRANSLATOR_KEY not set")
    headers = {"Ocp-Apim-Subscription-Key": config.AZURE_TRANSLATOR_KEY,
               "Content-Type": "application/json"}
    if config.AZURE_TRANSLATOR_REGION:
        headers["Ocp-Apim-Subscription-Region"] = config.AZURE_TRANSLATOR_REGION
    r = _http.post(
        "https://api.cognitive.microsofttranslator.com/translate",
        params={"api-version": "3.0", "to": _AZURE_CODES.get(lang, lang),
                "textType": "plain"},
        headers=headers,
        json=[{"Text": s} for s in texts],
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return [
        (row["translations"][0]["text"],
         normalize((row.get("detectedLanguage") or {}).get("language")))
        for row in r.json()
    ]


def _google(texts, lang):
    if not config.GOOGLE_TRANSLATE_API_KEY:
        raise RuntimeError("GOOGLE_TRANSLATE_API_KEY not set")
    r = _http.post(
        "https://translation.googleapis.com/language/translate/v2",
        params={"key": config.GOOGLE_TRANSLATE_API_KEY},
        json={"q": texts, "target": _GOOGLE_CODES.get(lang, lang), "format": "text"},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return [
        (row["translatedText"], normalize(row.get("detectedSourceLanguage")))
        for row in r.json()["data"]["translations"]
    ]


def _dev(texts, lang):
    """Offline stub for local testing: never touches the network or spends.
    'Detects' plain-ASCII titles as English; everything else is 'und'."""
    out = []
    for s in texts:
        src = "en" if s.isascii() else "und"
        out.append((s if src == lang else "[%s] %s" % (lang, s), src))
    return out


PROVIDERS = {"azure": _azure, "google": _google, "dev": _dev}

# Azure caps a request at 1000 elements / 50k chars; stay well inside both.
_BATCH = 100
# After a provider failure, serve originals for a while instead of
# re-trying (and stalling) on every request.
_BACKOFF_S = 300
_backoff_until = 0.0
# Serialises provider calls so concurrent requests for the same page don't
# pay to translate the same headlines twice.
_translate_lock = threading.Lock()


def _month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usage():
    """Current-month character usage vs the ceiling (for /api/status)."""
    u = db.get_translation_usage(_month())
    u["budget"] = config.TRANSLATION_MONTHLY_CHAR_BUDGET
    u["provider"] = config.TRANSLATION_PROVIDER
    return u


def _call_provider(texts, lang):
    global _backoff_until
    fn = PROVIDERS.get(config.TRANSLATION_PROVIDER)
    if fn is None:
        log.error("unknown TRANSLATION_PROVIDER %r", config.TRANSLATION_PROVIDER)
        return None
    if time.monotonic() < _backoff_until:
        return None
    out = []
    try:
        for i in range(0, len(texts), _BATCH):
            chunk = texts[i:i + _BATCH]
            out.extend(fn(chunk, lang))
            # Counted for the dev stub too, so the ceiling is testable offline.
            db.add_translation_usage(_month(), sum(len(s) for s in chunk))
    except Exception as e:
        # Log the failure class only — never the request (keys live in it).
        log.warning("translation provider %s failed: %s",
                    config.TRANSLATION_PROVIDER, type(e).__name__)
        _backoff_until = time.monotonic() + _BACKOFF_S
        return out or None
    return out


def _translate_missing(pending, lang):
    """pending: {title_hash: (title, source)} not yet cached for lang.
    Translates what the budget allows, caches it, memoises outlet
    languages. Returns {title_hash: (translated, source_lang)}."""
    with _translate_lock:
        # Another request may have filled these while we waited.
        cached = db.get_translations(pending.keys(), lang)
        todo = [(h, title, src) for h, (title, src) in pending.items() if h not in cached]
        if not todo:
            return cached
        # Spend ceiling: translate only what still fits this month.
        left = config.TRANSLATION_MONTHLY_CHAR_BUDGET - db.get_translation_usage(_month())["chars"]
        fit = []
        for row in todo:
            if len(row[1]) > left:
                break
            left -= len(row[1])
            fit.append(row)
        if len(fit) < len(todo):
            log.info("translation budget reached; %d headlines served untranslated",
                     len(todo) - len(fit))
        todo = fit
        if not todo:
            return cached
        results = _call_provider([title for _, title, _ in todo], lang)
        if not results:
            return cached
        rows, detections = [], []
        for (h, title, src), (translated, detected) in zip(todo, results):
            if detected == lang:
                translated = title  # already in the reader's language
            rows.append((h, translated, detected))
            cached[h] = (translated, detected)
            if detected:
                detections.append((src, detected))
        db.put_translations(rows, lang)
        db.record_source_languages(detections)
        return cached


# An outlet must be detected in the same language this many times in a row
# before its headlines skip the provider for readers of that language.
SOURCE_CONFIDENCE = 3


def localize(items, lang):
    """Return items with title_translated / title_lang added where a
    translation into lang exists or can be made. `title` always stays the
    original. A no-op (same list back) when translation is off."""
    if not items or not is_active(lang):
        return items
    try:
        hashes = [db.title_hash(it.get("title") or "") for it in items]
        cached = db.get_translations(hashes, lang)
        langs = db.get_source_languages(it.get("source") for it in items)
        pending = {}
        for h, it in zip(hashes, items):
            if h in cached or not (it.get("title") or "").strip():
                continue
            src_lang, agree = langs.get(it.get("source"), (None, 0))
            if src_lang == lang and agree >= SOURCE_CONFIDENCE:
                continue  # memoised: this outlet already writes in lang
            pending[h] = (it["title"], it.get("source"))
        if pending:
            cached.update(_translate_missing(pending, lang))
    except Exception:
        log.exception("headline localization failed; serving originals")
        return items
    out = []
    for h, it in zip(hashes, items):
        hit = cached.get(h)
        if hit and hit[0] and hit[0] != it.get("title"):
            it = dict(it, title_translated=hit[0], title_lang=hit[1] or "")
        out.append(it)
    return out
