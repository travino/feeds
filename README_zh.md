<div align="center">

<img src="assets/banner-feedseek.svg" alt="Feedseek" width="960">

<img src="assets/icons/favicon-96x96.png" alt="Feedseek" width="72">

# Feedseek 📡

**自动更新并增强 RSS/Atom + JSON feed：既为没有 feed 的网站补齐，也把已有的原生 feed 做得更好。**

[![feeds](https://img.shields.io/badge/feeds-105-d6541a?style=flat-square&logo=rss&logoColor=white)](feeds.yaml) [![CI](https://img.shields.io/github/actions/workflow/status/trvny/feedseek/update-feeds.yml?label=CI&logo=githubactions&logoColor=white&color=d6541a&style=flat-square)](https://github.com/trvny/feedseek/actions/workflows/update-feeds.yml) [![pages](https://img.shields.io/github/deployments/trvny/feedseek/github-pages?label=pages&logo=github&logoColor=white&color=d6541a&style=flat-square)](https://trvny.github.io/feedseek/) [![last commit](https://img.shields.io/github/last-commit/trvny/feedseek?color=d6541a&logo=git&logoColor=white&style=flat-square)](https://github.com/trvny/feedseek/commits/main) [![license](https://img.shields.io/github/license/trvny/feedseek?color=d6541a&style=flat-square)](LICENSE)
<a href="https://deepwiki.com/trvny/feedseek"><img src="https://deepwiki.com/badge.svg" alt="DeepWiki"></a>  
[![GitHubPages](https://img.shields.io/badge/-222222?style=for-the-badge&logo=githubpages&logoColor=white)](https://trvny.github.io/feedseek/)  
![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white) [![uv](https://img.shields.io/badge/uv-DE5FE9?style=flat-square&logo=uv&logoColor=white)](https://astral.sh)

[Polski](README_pl.md) · [English](README.md) · **简体中文**  

[**📡 Feeds**](https://trvny.github.io/feedseek/) · [**📖 Reader**](https://trvny.github.io/feedseek/reader/) · [**🗂 Registry**](feeds.yaml) · [**🧭 Internals**](docs/)  

</div>

Feedseek 会发现已有 feed，或在必要时构建新的 feed；随后统一条目格式、去重，并通过 GitHub Pages 发布结果。计划工作流每两小时刷新来源，同时把单个来源的故障隔离开，避免一个网站出问题拖垮全部 feed。

Feedseek 不只是为没有 feed 的网站生成替代品。原生 RSS/Atom 是很有价值的上游输入，但并不是不可改动的最终产品：只要源数据允许，Feedseek 就会继续规范化和增强它，生成更稳定、更完整、语义更丰富、兼容性更好的 feed，并在 XML 旁发布 JSON Feed 1.1。

目标是在源数据允许的范围内尽可能充分利用 RSS、Atom 和 JSON Feed 的能力，包括稳定的条目标识、规范链接、可信的发布时间与更新时间、有用的元数据、来源信息、分类和媒体。抓取器和 API adapter 用来补齐原生来源留下的缺口。失败或空的抓取结果不会覆盖最后一次成功生成的 feed。

灵感来自 [Olshansk/rss-feeds](https://github.com/Olshansk/rss-feeds) 与 [rss-bridge/rss-bridge](https://github.com/rss-bridge/rss-bridge)。

## Feeds ![XML](https://img.shields.io/badge/XML-005FAD?logo=xml&logoColor=fff&style=plastic)

Feed 列表会持续变化，因此中文 README 不复制整张动态表。当前完整清单请直接查看：

- [Feeds 页面](https://trvny.github.io/feedseek/)
- [源注册表 `feeds.yaml`](feeds.yaml)
- [自动生成的来源清单](docs/sources.md)

每个输出 feed 都可以从 GitHub Pages 或仓库中的 `feeds/` 目录访问。网站 favicon 在渲染时从 Google favicon 服务或 DuckDuckGo 获取，不会把这些图片提交进仓库。

## 文档

- [流水线、enrichment、本地使用方式与仓库结构](docs/architecture.md)
- [各 feed 的来源与设计取舍](docs/feeds.md)
- [缓存行为与维护](docs/cache.md)
- [自动生成的来源清单](docs/sources.md)

这些 feed 对应的 Android 阅读器/播放器位于 **[twojstar/kanarek](https://github.com/twojstar/kanarek)**。

## [许可证](LICENSE)

[![License](https://www.shieldcn.dev/github/license/trvny/feedseek.svg?variant=branded&size=xm&mode=light&theme=neutral&font=jetbrains-mono)](https://spdx.org/licenses/MIT)    [THIRD_PARTY_NOTICES](docs/THIRD_PARTY_NOTICES.md)

## 📰 小新闻

<!--README_FEED:START-->
- [America Walks Away from Global Democracy](https://carnegieendowment.org/research/2026/09/america-walks-away-from-global-democracy)
- [Przy blokach spółdzielnia posadzi drzewa - Przelom.pl - portal ziemi chrzanowskiej](https://news.google.com/atom/articles/CBMinAFBVV95cUxQRVJFaGJ1SGpLbm1DcEZNT3NaSlpMNWVBZmZIcTZ0cG1iUkJKeE9HZXVDTjFabk1ZQ0lwRGs2MGg5X2JCMmt2d0ktd1l6TkwwcUhJUnl0SUZRNF9CSTcyTlBVVjQ1aVZEeDF2S1pEc3NlUFBWdzBvQzcwYmVYQlRqTWxDR0NKY1plVVJkTGNrZlFnaUJtbVRqLTd2c2c?oc=5)
- [Trump says Iran war will end right after U.S. midterm elections](https://www.reuters.com/world/middle-east/trump-says-iran-war-will-end-right-after-us-midterm-elections-2026-09-09/)
- [Trump says Putin wants to make a deal in Ukraine](https://www.reuters.com/world/europe/trump-says-putin-wants-make-deal-ukraine-2026-09-09/)
- [EXCLUSIVE: OpenAI’s rogue agents used at least 10 more sites for unauthorized comms, researchers say](https://www.reuters.com/world/openais-rogue-agents-used-least-10-more-sites-unauthorized-comms-researchers-say-2026-09-09/)
- [The Fallout of the U.S.–Canada Trade War Won’t Be Limited to North America](https://carnegieendowment.org/emissary/2026/09/us-canada-trade-war-fallout-asia)
<!--README_FEED:END-->

## 💬 抽屉里的引语

<!-- markdownlint-disable MD033 -->
<!--STARTS_HERE_QUOTE_README-->
<i>❝“Two years from now, spam will be solved.”— Bill Gates, 2004❞</i>
<!--ENDS_HERE_QUOTE_README-->
<!-- markdownlint-enable MD033 -->

## 其他项目

[![kanarek](https://raw.githubusercontent.com/trvny/.github/main/assets/profile/pin-kanarek.svg)](https://github.com/twojstar/kanarek) [![tvpi](https://raw.githubusercontent.com/trvny/.github/main/assets/profile/pin-tvpi.svg)](https://github.com/trvny/tvpi)
