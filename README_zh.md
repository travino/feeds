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
- [How to Engage with New Media: A Strategic Guide for Nonprofit Organizations](https://carnegieendowment.org/research/2026/08/how-to-engage-with-new-media-a-strategic-guide-for-nonprofit-organizations)
- [How the U.S. Export-Import Bank Can Finally Join the Fight Against Climate Change](https://carnegieendowment.org/research/2026/09/renewable-energy-investment-united-states-exim-export-import-bank)
- [Far-right triumph in eastern Germany leaves migrants questioning their future](https://www.reuters.com/world/far-right-triumph-eastern-germany-leaves-migrants-questioning-their-future-2026-09-07/)
- [Nocny dramat przy Kościuszki. 42-latek pobity, zatrzymano trzy osoby - Przelom.pl - portal ziemi chrzanowskiej](https://news.google.com/atom/articles/CBMitAFBVV95cUxQc0FyTnY2T3YyZWN1ZjlYTXFNT0lJbFpuQWp4VTlPT1dEam53YlYzTmdJbUZ6a2F3QmVzbU1rUy1iZ0JIem85T2lUUm1aRFpPYkJ6MFFfOEdMbXpIdHdNbGNWZ2V1eVhIRThBU2ZpX09tQTNrbFhRci13LXM5SlpHeWE4TWxHSjVlV3hyUjlqanFERmRSS1hIZHl4QVU5clZhcDMyWWlhMmJ5Yjg0UmdlSjhBYlY?oc=5)
- [Paris investigates claim women were hidden from Hindu delegation at Eiffel Tower](https://www.reuters.com/business/media-telecom/paris-investigates-claim-women-were-hidden-hindu-delegation-eiffel-tower-2026-09-07/)
- [Nowa siedziba Nadleśnictwa Chrzanów. Powstanie okazały budynek - Przelom.pl - portal ziemi chrzanowskiej](https://news.google.com/atom/articles/CBMiuAFBVV95cUxPUHRNREYtdE5KOUJIdW1uRWhqZU1XU24xTkxLQjVGLVhwbFlXaEN2SmMwSjNBMjExT2tpUkRueC1FRUpLV1lUVHlCcHdDVWNKdTNDcHItWlZnQ251WERSOEN5MGthTW5iYmVvYVlzdm9qVC1uaF9mMmdIYU81dk94S0E2V0hKY1RuMGxiSDl2QWdmcW9RUDhYbXlReFl6TUwxVEJBZnJsUHNBb0VXcE5WbHAxNzlOcW96?oc=5)
<!--README_FEED:END-->

## 💬 抽屉里的引语

<!-- markdownlint-disable MD033 -->
<!--STARTS_HERE_QUOTE_README-->
<i>❝IBM 5120 from 1980 was the heaviest desktop computer ever made. It weighed about 105 pounds, not including the 130 pounds external floppy drive.❞</i>
<!--ENDS_HERE_QUOTE_README-->
<!-- markdownlint-enable MD033 -->

## 其他项目

[![kanarek](https://raw.githubusercontent.com/trvny/.github/main/assets/profile/pin-kanarek.svg)](https://github.com/twojstar/kanarek) [![tvpi](https://raw.githubusercontent.com/trvny/.github/main/assets/profile/pin-tvpi.svg)](https://github.com/trvny/tvpi)
