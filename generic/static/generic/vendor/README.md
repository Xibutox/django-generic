# Vendored libraries

Shipped with the framework so a project runs offline and gets a
working interface without a build step. Each library keeps its own
licence file next to it.

| Library | Version | Licence | Taken from |
| --- | --- | --- | --- |
| DataTables (core only) | 3.0.3 | MIT | datatables.net |
| jQuery | 4.0.0 | MIT | jquery.com — needed by Select2 only |
| Select2 | 4.1.0 | MIT | select2.org |
| Alpine.js, plus focus, persist and anchor | 3.16.1 | MIT | via django-unfold |
| Material Symbols Outlined | variable font | Apache 2.0 | via django-unfold |
| Quill (the wiki's editor) | 2.0.3 | BSD-3-Clause | quilljs.com |
| Apache ECharts, and its French locale | 6.1.0 | Apache 2.0 | npm `echarts`, via jsDelivr |

ECharts is not linked by any template: `generic/js/charts.js` loads it,
and the locale matching the page's language, the first time a chart is
shown. Its `NOTICE` file travels with it, as the licence asks.

DataTables is the core build, without the Buttons, ColReorder or
FixedHeader extensions. The framework implements what it needs from
them itself: exports are server-side (every filtered row, not the page
on screen), copy and print work on the visible page, and the column
selector is its own. A project that wants an extension loads it in the
`datatable_vendor` block; the integration detects it.

To upgrade one, replace the file and update the version here.
