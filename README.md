<div align="center">

<img src="assets/banner-feedseek.svg" alt="Feedseek" width="960">

<img src="assets/icons/favicon-96x96.png" alt="Feedseek" width="72">

# Feedseek 📡

**Self-updating, enhanced RSS/Atom + JSON feeds, built both where feeds are missing and where native feeds can be made better.**

[![feeds](https://img.shields.io/badge/feeds-105-d6541a?style=flat-square&logo=rss&logoColor=white)](feeds.yaml) [![CI](https://img.shields.io/github/actions/workflow/status/trvny/feedseek/update-feeds.yml?label=CI&logo=githubactions&logoColor=white&color=d6541a&style=flat-square)](https://github.com/trvny/feedseek/actions/workflows/update-feeds.yml) [![pages](https://img.shields.io/github/deployments/trvny/feedseek/github-pages?label=pages&logo=github&logoColor=white&color=d6541a&style=flat-square)](https://trvny.github.io/feedseek/) [![last commit](https://img.shields.io/github/last-commit/trvny/feedseek?color=d6541a&logo=git&logoColor=white&style=flat-square)](https://github.com/trvny/feedseek/commits/main) [![license](https://img.shields.io/github/license/trvny/feedseek?color=d6541a&style=flat-square)](LICENSE)
<a href="https://deepwiki.com/trvny/feedseek"><img src="https://deepwiki.com/badge.svg" alt="DeepWiki"></a>  
[![GitHubPages](https://img.shields.io/badge/-222222?style=for-the-badge&logo=githubpages&logoColor=white)](https://trvny.github.io/feedseek/)  
![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white) [![uv](https://img.shields.io/badge/uv-DE5FE9?style=flat-square&logo=uv&logoColor=white)](https://astral.sh)

[Polski](README_pl.md) · **English** · [简体中文](README_zh.md)  

[**📡 Feeds**](https://trvny.github.io/feedseek/) · [**📖 Reader**](https://trvny.github.io/feedseek/reader/) · [**🗂 Registry**](feeds.yaml) · [**🧭 Internals**](docs/)  

</div>

Feedseek discovers or builds feeds, normalizes entries, deduplicates them and publishes the generated output through GitHub Pages. The scheduled workflow refreshes sources every two hours, while source failures are isolated so one broken site does not sink the rest.

Feedseek is not only a generator for sites that lack feeds. Native RSS/Atom is a valuable upstream input, not an untouchable final product: when the source material allows it, Feedseek normalizes and enriches it into a more stable, complete, expressive and interoperable feed, with a JSON Feed 1.1 sidecar alongside the XML.

The goal is to use the useful semantics of RSS, Atom and JSON Feed as fully as the source allows: durable identity, canonical links, truthful publication/update dates, useful metadata, provenance, categories and media. Scraping and API adapters fill gaps that native sources leave behind. A failed or empty fetch does not replace the last known-good feed.

Inspired by [Olshansk/rss-feeds](https://github.com/Olshansk/rss-feeds) & [rss-bridge/rss-bridge](https://github.com/rss-bridge/rss-bridge).

## Feeds ![XML](https://img.shields.io/badge/XML-005FAD?logo=xml&logoColor=fff&style=plastic)

| Source ![rss](https://www.mozilla.org/media/img/trademarks/feed-icon-28x28.e077f1f611f0.png) | Feed <img src="assets/icons/rss-file-color-green.png" width="24" align="top"> |
| ------ | ---- |
| <img src="https://www.google.com/s2/favicons?domain=jbzd.com.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Jbzd.com.pl](https://jbzd.com.pl/) | [feed_jbzd.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_jbzd.xml) |
| <img src="https://www.google.com/s2/favicons?domain=wykop.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Wykop](https://wykop.pl/) | [feed_wykop.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_wykop.xml) |
| <img src="https://www.google.com/s2/favicons?domain=9gag.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [9GAG](https://9gag.com/) | [feed_9gag.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_9gag.xml) |
| <img src="https://www.google.com/s2/favicons?domain=4chan.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [4chan](https://www.4chan.org/) | [feed_4chan.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_4chan.xml) |
| <img src="https://www.google.com/s2/favicons?domain=join-lemmy.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [Lemmy](https://join-lemmy.org/) | [feed_lemmy.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_lemmy.xml) |
| <img src="https://www.google.com/s2/favicons?domain=cheezburger.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Cheezburger Network](https://www.cheezburger.com/) | [feed_cheezburger.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_cheezburger.xml) |
| <img src="https://www.google.com/s2/favicons?domain=memedroid.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Memedroid](https://www.memedroid.com/) | [feed_memedroid.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_memedroid.xml) |
| <img src="https://www.google.com/s2/favicons?domain=beatport.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Beatport Top 100](https://www.beatport.com/top-100) | [feed_beatport_top100.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_beatport_top100.xml) |
| <img src="https://icons.duckduckgo.com/ip3/ra.co.ico" width="16" height="16" align="absmiddle" alt=""> [RA (Resident Advisor)](https://ra.co/magazine) | [feed_ra.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_ra.xml) |
| <img src="https://www.google.com/s2/favicons?domain=audio.com.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Audio.com.pl](https://audio.com.pl/) | [feed_audio.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_audio.xml) |
| <img src="https://www.google.com/s2/favicons?domain=audacityteam.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [Audacity®](https://www.audacityteam.org/blog/) | [feed_audacity.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_audacity.xml) |
| <img src="https://www.google.com/s2/favicons?domain=spotify.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Spotify (newsroom + developers)](https://newsroom.spotify.com/) | [feed_spotify.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_spotify.xml) |
| <img src="https://www.google.com/s2/favicons?domain=foobar2000.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [foobar2000](https://www.foobar2000.org/news) | [feed_foobar2000.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_foobar2000.xml) |
| <img src="https://icons.duckduckgo.com/ip3/viewbits.com.ico" width="16" height="16" align="absmiddle" alt=""> [Daily Digest](https://api.viewbits.com/) | [feed_daily_digest.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_daily_digest.xml) |
| <img src="https://www.google.com/s2/favicons?domain=gist.github.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Daily Quote](https://gist.github.com/trvny/167d2271e3cf7d21e118aa7d906a7d2c) | [feed_daily_quote.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_daily_quote.xml) |
| <img src="https://www.google.com/s2/favicons?domain=theysaidso.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Quotes, Sayings & Jokes of the Day](https://theysaidso.com/) | [feed_theysaidso.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_theysaidso.xml) |
| <img src="https://www.google.com/s2/favicons?domain=dictionary.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Word of the Day (Dictionary.com,MW,AWAD,TFD)](https://www.dictionary.com/e/word-of-the-day/) | [feed_wotd.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_wotd.xml) |
| <img src="https://www.google.com/s2/favicons?domain=unsplash.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Unsplash (log + wallpapers)](https://unsplash.com/blog/) | [feed_unsplash.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_unsplash.xml) |
| <img src="https://www.google.com/s2/favicons?domain=gov.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Gov.pl](https://www.gov.pl/) | [feed_govpl_news.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_govpl_news.xml) |
| <img src="https://www.google.com/s2/favicons?domain=usa.gov&sz=32" width="16" height="16" align="absmiddle" alt=""> [US.gov](https://www.usa.gov/) | [feed_usgov.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_usgov.xml) |
| <img src="https://www.google.com/s2/favicons?domain=open-meteo.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Open-Meteo](https://open-meteo.com/) | [feed_open_meteo.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_open_meteo.xml) |
| <img src="https://www.google.com/s2/favicons?domain=openweathermap.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [OpenWeather](https://openweathermap.org/city/3093133) | [feed_openweather.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_openweather.xml) |
| <img src="https://www.google.com/s2/favicons?domain=visualcrossing.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Visual Crossing](https://www.visualcrossing.com/) | [feed_visualcrossing.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_visualcrossing.xml) |
| <img src="https://www.google.com/s2/favicons?domain=imgw.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [IMGW](https://danepubliczne.imgw.pl/) | [feed_imgw.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_imgw.xml) |
| <img src="https://www.google.com/s2/favicons?domain=weather.trfny.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Weather — Kościelec](https://weather.trfny.com/) | [feed_weather.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_weather.xml) |
| <img src="https://www.google.com/s2/favicons?domain=accuweather.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [AccuWeather News](https://www.accuweather.com/en/weather-news) | [feed_accuweather.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_accuweather.xml) |
| <img src="https://www.google.com/s2/favicons?domain=visualcrossing.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Visual Crossing Blog](https://www.visualcrossing.com/resources/) | [feed_visualcrossing_blog.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_visualcrossing_blog.xml) |
| <img src="https://www.google.com/s2/favicons?domain=reuters.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Reuters](https://www.reuters.com/) | [feed_reuters.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_reuters.xml) |
| <img src="https://www.google.com/s2/favicons?domain=wsj.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [WSJ](https://www.wsj.com/news/latest-headlines?mod=wsjfooter) | [feed_wsj.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_wsj.xml) |
| <img src="https://www.google.com/s2/favicons?domain=euronews.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Euronews](https://www.euronews.com/) | [feed_euronews.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_euronews.xml) |
| <img src="https://www.google.com/s2/favicons?domain=europa.eu&sz=32" width="16" height="16" align="absmiddle" alt=""> [Europa (UE)](https://european-union.europa.eu/) | [feed_europa.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_europa.xml) |
| <img src="https://www.google.com/s2/favicons?domain=understandingwar.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [Geopolitics (ISW;RUSI;CSIS;Carnegie)](https://understandingwar.org/research/) | [feed_geopolitics.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_geopolitics.xml) |
| <img src="https://www.google.com/s2/favicons?domain=pap.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [PAP](https://www.pap.pl/) | [feed_pap.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_pap.xml) |
| <img src="https://www.google.com/s2/favicons?domain=reddit.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [MultiReddit[OFF]](https://old.reddit.com/) | `feed_multireddit.xml` — disabled, not published |
| <img src="https://www.google.com/s2/favicons?domain=spidersweb.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Spider's Web](https://spidersweb.pl/) | [feed_spidersweb.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_spidersweb.xml) |
| <img src="https://www.google.com/s2/favicons?domain=wikipedia.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [Wikipedia (PL)](https://pl.wikipedia.org/) | [feed_wikipedia_pl.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_wikipedia_pl.xml) |
| <img src="https://www.google.com/s2/favicons?domain=baike.baidu.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Baidu Baike 热搜词条](https://baike.baidu.com/) | [feed_baidubaike.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_baidubaike.xml) |
| <img src="https://www.google.com/s2/favicons?domain=tvp.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [TVP](https://www.tvp.pl/) | [feed_tvp.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_tvp.xml) |
| <img src="https://icons.duckduckgo.com/ip3/trojka.polskieradio.pl.ico" width="16" height="16" align="absmiddle" alt=""> [Polskie Radio – Trójka](https://trojka.polskieradio.pl/) | [feed_trojka.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_trojka.xml) |
| <img src="https://www.google.com/s2/favicons?domain=polskieradio.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Polskie Radio – Czwórka](https://www.polskieradio.pl/10,czworka) | [feed_czworka.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_czworka.xml) |
| <img src="https://www.google.com/s2/favicons?domain=olx.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [OLX Group (OLX/OTOMOTO/Otodom)](https://www.olx.pl/) | [feed_olx.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_olx.xml) |
| <img src="https://www.google.com/s2/favicons?domain=toyota.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Toyota Global](https://pressroom.toyota.com/) | [feed_toyota_global.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_toyota_global.xml) |
| <img src="https://www.google.com/s2/favicons?domain=lexus.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Lexus Newsroom](https://pressroom.lexus.com/) | [feed_lexus_newsroom.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_lexus_newsroom.xml) |
| <img src="https://www.google.com/s2/favicons?domain=lenovo.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Lenovo StoryHub](https://news.lenovo.com/) | [feed_lenovo.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_lenovo.xml) |
| <img src="https://www.google.com/s2/favicons?domain=hp.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [HP Newsroom](https://www.hp.com/us-en/newsroom.html) | [feed_hp.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_hp.xml) |
| <img src="https://www.google.com/s2/favicons?domain=mi.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Xiaomi Newsroom](https://www.mi.com/global/discover/newsroom) | [feed_xiaomi.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_xiaomi.xml) |
| <img src="https://www.google.com/s2/favicons?domain=samsung.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Samsung Newsroom (global/PL)](https://news.samsung.com/global/) | [feed_samsung.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_samsung.xml) |
| <img src="https://www.google.com/s2/favicons?domain=sony.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Sony Corp](https://www.sony.com/en/SonyInfo/News/Press/) | [feed_sony.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_sony.xml) |
| <img src="https://www.google.com/s2/favicons?domain=apple.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Apple Newsroom](https://www.apple.com/pl/newsroom/) | [feed_apple.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_apple.xml) |
| <img src="https://www.google.com/s2/favicons?domain=microsoft.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Microsoft Blogs](https://blogs.microsoft.com/) | [feed_microsoft.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_microsoft.xml) |
| <img src="https://www.google.com/s2/favicons?domain=redhat.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Red Hat Enterprise](https://www.redhat.com/en/) | [feed_redhat.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_redhat.xml) |
| <img src="https://www.google.com/s2/favicons?domain=ubuntu.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Ubuntu](https://ubuntu.com/blog) | [feed_ubuntu.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_ubuntu.xml) |
| <img src="https://www.google.com/s2/favicons?domain=oracle.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Oracle](https://blogs.oracle.com/) | [feed_oracle.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_oracle.xml) |
| <img src="https://www.google.com/s2/favicons?domain=microsoft.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Microsoft Updates (Windows/Office/Copilot)](https://support.microsoft.com/en-us/windows) | [feed_microsoft_updates.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_microsoft_updates.xml) |
| <img src="https://www.google.com/s2/favicons?domain=blog.google&sz=32" width="16" height="16" align="absmiddle" alt=""> [Google (combined)](https://blog.google/) | [feed_google.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_google.xml) |
| <img src="https://www.google.com/s2/favicons?domain=blog.youtube&sz=32" width="16" height="16" align="absmiddle" alt=""> [YouTube Blog](https://blog.youtube/) | [feed_youtube.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_youtube.xml) |
| <img src="https://www.google.com/s2/favicons?domain=mozilla.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [Mozilla](https://blog.mozilla.org/) | [feed_mozilla.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_mozilla.xml) |
| <img src="https://www.google.com/s2/favicons?domain=meta.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Meta Newsroom](https://about.fb.com/news/) | [feed_meta_newsroom.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_meta_newsroom.xml) |
| <img src="https://www.google.com/s2/favicons?domain=thinkingmachines.ai&sz=32" width="16" height="16" align="absmiddle" alt=""> [AI-bridge (combined AI sources)](https://thinkingmachines.ai/blog/) | [feed_aibridge.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_aibridge.xml) |
| <img src="https://www.google.com/s2/favicons?domain=anthropic.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Anthropic](https://www.anthropic.com/) | [feed_anthropic.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_anthropic.xml) |
| <img src="https://www.google.com/s2/favicons?domain=claude.ai&sz=32" width="16" height="16" align="absmiddle" alt=""> [Claude](https://claude.com/blog) | [feed_claude.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_claude.xml) |
| <img src="https://www.google.com/s2/favicons?domain=openai.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [OpenAI](https://openai.com/news/) | [feed_openai.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_openai.xml) |
| <img src="https://www.google.com/s2/favicons?domain=x.ai&sz=32" width="16" height="16" align="absmiddle" alt=""> [xAI](https://x.ai/news) | [feed_xai.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_xai.xml) |
| <img src="https://www.google.com/s2/favicons?domain=huggingface.co&sz=32" width="16" height="16" align="absmiddle" alt=""> [Hugging Face](https://huggingface.co/) | [feed_huggingface.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_huggingface.xml) |
| <img src="https://www.google.com/s2/favicons?domain=skillsllm.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [LLM & MCP / Skills ecosystem](https://skillsllm.com/) | [feed_skillsllm.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_skillsllm.xml) |
| <img src="https://www.google.com/s2/favicons?domain=moltbook.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Moltbook](https://www.moltbook.com/) | [feed_moltbook.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_moltbook.xml) |
| <img src="https://www.google.com/s2/favicons?domain=uber.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Uber Newsroom](https://www.uber.com/us/en/newsroom/) | [feed_uber.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_uber.xml) |
| <img src="https://www.google.com/s2/favicons?domain=tencent.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Tencent](https://www.tencent.com/newsroom/) | [feed_tencent.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_tencent.xml) |
| <img src="https://www.google.com/s2/favicons?domain=aws.amazon.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [AWS](https://aws.amazon.com/blogs/) | [feed_aws.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_aws.xml) |
| <img src="https://www.google.com/s2/favicons?domain=onlyoffice.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [OPENOFFICE](https://www.onlyoffice.com/blog) | [feed_openoffice.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_openoffice.xml) |
| <img src="https://www.google.com/s2/favicons?domain=hashicorp.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [SaaS vendors](https://www.hashicorp.com/blog) | [feed_saas.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_saas.xml) |
| <img src="https://www.google.com/s2/favicons?domain=palantir.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Palantir](https://www.palantir.com/newsroom/) | [feed_palantir.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_palantir.xml) |
| <img src="https://www.google.com/s2/favicons?domain=cloudflare.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Cloudflare (log/community/research)](https://blog.cloudflare.com/) | [feed_cloudflare.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_cloudflare.xml) |
| <img src="https://www.google.com/s2/favicons?domain=docker.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Docker](https://www.docker.com/blog/) | [feed_docker.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_docker.xml) |
| <img src="https://www.google.com/s2/favicons?domain=gitlab.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [GitLab](https://about.gitlab.com/) | [feed_gitlab.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_gitlab.xml) |
| <img src="https://www.google.com/s2/favicons?domain=github.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [GitHub (tooling,trending)](https://github.blog/) | [feed_github.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_github.xml) |
| <img src="https://www.google.com/s2/favicons?domain=canva.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Canva](https://www.canva.com/newsroom/news/) | [feed_canva.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_canva.xml) |
| <img src="https://www.google.com/s2/favicons?domain=paint.net&sz=32" width="16" height="16" align="absmiddle" alt=""> [Paint.NET](https://blog.paint.net/) | [feed_paintnet.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_paintnet.xml) |
| <img src="https://www.google.com/s2/favicons?domain=greasespot.net&sz=32" width="16" height="16" align="absmiddle" alt=""> [UserScripts (Violentmonkey/Tampermonkey/Grease/Sleazy)](https://www.greasespot.net/) | [feed_userscripts.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_userscripts.xml) |
| <img src="https://www.google.com/s2/favicons?domain=nexusmods.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Nexus Mods News](https://www.nexusmods.com/news) | [feed_nexusmods_news.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_nexusmods_news.xml) |
| <img src="https://www.google.com/s2/favicons?domain=bethesda.net&sz=32" width="16" height="16" align="absmiddle" alt=""> [Bethesda](https://bethesda.net/pl-PL/news) | [feed_bethesda.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_bethesda.xml) |
| <img src="https://www.google.com/s2/favicons?domain=ea.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Electronic Arts](https://www.ea.com/pl-pl/news) | [feed_ea.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_ea.xml) |
| <img src="https://www.google.com/s2/favicons?domain=steampowered.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Steam](https://store.steampowered.com/news/) | [feed_steam.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_steam.xml) |
| <img src="https://www.google.com/s2/favicons?domain=gog.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [GOG pressroom](https://www.gog.com/blog) | [feed_gog.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_gog.xml) |
| <img src="https://www.google.com/s2/favicons?domain=nasa.gov&sz=32" width="16" height="16" align="absmiddle" alt=""> [NASA](https://www.nasa.gov/) | [feed_nasa.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_nasa.xml) |
| <img src="https://www.google.com/s2/favicons?domain=esa.int&sz=32" width="16" height="16" align="absmiddle" alt=""> [ESA](https://www.esa.int/) | [feed_esa.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_esa.xml) |
| <img src="https://www.google.com/s2/favicons?domain=pekao.com.pl&sz=32" width="16" height="16" align="absmiddle" alt=""> [Bank Pekao SA](https://www.pekao.com.pl/) | [feed_pekao.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_pekao.xml) |
| <img src="https://www.google.com/s2/favicons?domain=creativecommons.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [Open Sources (CC/OSI/SPDX/OGC/RFC/IETF)](https://creativecommons.org/blog/) | [feed_opensource.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_opensource.xml) |
| <img src="https://www.google.com/s2/favicons?domain=hackerone.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [HackerOne](https://www.hackerone.com/blog) | [feed_hackerone.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_hackerone.xml) |
| <img src="https://www.google.com/s2/favicons?domain=python.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [Python (combined ecosystem)](https://www.python.org/) | [feed_python.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_python.xml) |
| <img src="https://www.google.com/s2/favicons?domain=nodejs.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [JS \| Node (ecosystem)](https://nodejs.org/) | [feed_js_node.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_js_node.xml) |
| <img src="https://www.google.com/s2/favicons?domain=arxiv.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [arXiv (+LessWrong;80,000Hours)](https://arxiv.org/) | [feed_arxiv.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_arxiv.xml) |
| <img src="https://www.google.com/s2/favicons?domain=rssboard.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [RSS Boards](https://www.rssboard.org/) | [feed_rssboard.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_rssboard.xml) |
| <img src="https://www.google.com/s2/favicons?domain=v2ex.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [V2EX + sspai](https://www.v2ex.com/) | [feed_v2ex.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_v2ex.xml) |
| <img src="https://www.google.com/s2/favicons?domain=medium.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Medium](https://medium.com/) | [feed_medium.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_medium.xml) |
| <img src="https://www.google.com/s2/favicons?domain=lichess.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [Lichess](https://lichess.org/blog) | [feed_lichess.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_lichess.xml) |
| <img src="https://www.google.com/s2/favicons?domain=tunein.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Radios (TuneIn;Maxi Italo;Electro Swing)](https://tunein.com/) | [feed_radios.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_radios.xml) |
| <img src="https://www.google.com/s2/favicons?domain=timeanddate.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [DaTime (timeanddate;Office Holidays)](https://www.timeanddate.com/news/) | [feed_datime.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_datime.xml) |
| <img src="https://www.google.com/s2/favicons?domain=news.mit.edu&sz=32" width="16" height="16" align="absmiddle" alt=""> [MIT News](https://news.mit.edu/) | [feed_mit.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_mit.xml) |
| <img src="https://www.google.com/s2/favicons?domain=dwutygodnik.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Dwutygodnik](https://www.dwutygodnik.com/) | [feed_dwutygodnik.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_dwutygodnik.xml) |
| <img src="https://www.google.com/s2/favicons?domain=ffmpeg.org&sz=32" width="16" height="16" align="absmiddle" alt=""> [FFmpeg](https://ffmpeg.org/) | [feed_ffmpeg.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_ffmpeg.xml) |
| <img src="https://www.google.com/s2/favicons?domain=download-soundtracks.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [Download Soundtracks](https://download-soundtracks.com/) | [feed_download-soundtracks.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_download-soundtracks.xml) |
| <img src="https://www.google.com/s2/favicons?domain=youtube.com&sz=32" width="16" height="16" align="absmiddle" alt=""> [YouTubs (selected channels, no Shorts)](https://www.youtube.com/) | [feed_youtubs.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_youtubs.xml) |
| <img src="https://www.google.com/s2/favicons?domain=1337x.to&sz=32" width="16" height="16" align="absmiddle" alt=""> [1337x Trending[OFF]](https://1337x.to/trending) | `feed_1337x.xml` — disabled, not published |
| <img src="https://icons.duckduckgo.com/ip3/rutracker.org.ico" width="16" height="16" align="absmiddle" alt=""> [RuTracker](https://rutracker.org/) | [feed_rutracker.xml](https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_rutracker.xml) |

> Favicons are pulled live from Google's favicon service
> (`https://www.google.com/s2/favicons?domain=<host>`) or DuckDuckGo (`https://icons.duckduckgo.com/ip3/.ico`); no images are committed
> to the repo.

## Documentation

- [Pipeline, enrichment, local usage and repository layout](docs/architecture.md)
- [Per-feed sources and design trade-offs](docs/feeds.md)
- [Cache behavior and maintenance](docs/cache.md)
- [Generated source inventory](docs/sources.md)

The Android reader/player for these feeds lives in **[twojstar/kanarek](https://github.com/twojstar/kanarek)**.

## [License](LICENSE)

[![License](https://www.shieldcn.dev/github/license/trvny/feedseek.svg?variant=branded&size=xm&mode=light&theme=neutral&font=jetbrains-mono)](https://spdx.org/licenses/MIT)    [THIRD_PARTY_NOTICES](docs/THIRD_PARTY_NOTICES.md)

## 📰 Mini news

<!--README_FEED:START-->
- [How to Engage with New Media: A Strategic Guide for Nonprofit Organizations](https://carnegieendowment.org/research/2026/08/how-to-engage-with-new-media-a-strategic-guide-for-nonprofit-organizations)
- [How the U.S. Export-Import Bank Can Finally Join the Fight Against Climate Change](https://carnegieendowment.org/research/2026/09/renewable-energy-investment-united-states-exim-export-import-bank)
- [Far-right triumph in eastern Germany leaves migrants questioning their future](https://www.reuters.com/world/far-right-triumph-eastern-germany-leaves-migrants-questioning-their-future-2026-09-07/)
- [Nocny dramat przy Kościuszki. 42-latek pobity, zatrzymano trzy osoby - Przelom.pl - portal ziemi chrzanowskiej](https://news.google.com/atom/articles/CBMitAFBVV95cUxQc0FyTnY2T3YyZWN1ZjlYTXFNT0lJbFpuQWp4VTlPT1dEam53YlYzTmdJbUZ6a2F3QmVzbU1rUy1iZ0JIem85T2lUUm1aRFpPYkJ6MFFfOEdMbXpIdHdNbGNWZ2V1eVhIRThBU2ZpX09tQTNrbFhRci13LXM5SlpHeWE4TWxHSjVlV3hyUjlqanFERmRSS1hIZHl4QVU5clZhcDMyWWlhMmJ5Yjg0UmdlSjhBYlY?oc=5)
- [Paris investigates claim women were hidden from Hindu delegation at Eiffel Tower](https://www.reuters.com/business/media-telecom/paris-investigates-claim-women-were-hidden-hindu-delegation-eiffel-tower-2026-09-07/)
- [Nowa siedziba Nadleśnictwa Chrzanów. Powstanie okazały budynek - Przelom.pl - portal ziemi chrzanowskiej](https://news.google.com/atom/articles/CBMiuAFBVV95cUxPUHRNREYtdE5KOUJIdW1uRWhqZU1XU24xTkxLQjVGLVhwbFlXaEN2SmMwSjNBMjExT2tpUkRueC1FRUpLV1lUVHlCcHdDVWNKdTNDcHItWlZnQ251WERSOEN5MGthTW5iYmVvYVlzdm9qVC1uaF9mMmdIYU81dk94S0E2V0hKY1RuMGxiSDl2QWdmcW9RUDhYbXlReFl6TUwxVEJBZnJsUHNBb0VXcE5WbHAxNzlOcW96?oc=5)
<!--README_FEED:END-->

## 💬 Quote from the drawer

<!-- markdownlint-disable MD033 -->
<!--STARTS_HERE_QUOTE_README-->
<i>❝IBM 5120 from 1980 was the heaviest desktop computer ever made. It weighed about 105 pounds, not including the 130 pounds external floppy drive.❞</i>
<!--ENDS_HERE_QUOTE_README-->
<!-- markdownlint-enable MD033 -->

## Other stuff

[![kanarek](https://raw.githubusercontent.com/trvny/.github/main/assets/profile/pin-kanarek.svg)](https://github.com/twojstar/kanarek) [![tvpi](https://raw.githubusercontent.com/trvny/.github/main/assets/profile/pin-tvpi.svg)](https://github.com/trvny/tvpi)
