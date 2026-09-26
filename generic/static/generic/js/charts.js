/**
 * Charts, drawn with Apache ECharts from the chart endpoints.
 *
 * The server says what to draw - categories, series, how values read -
 * in a shape that names no library (generic/sites/charts.py). This file
 * turns it into ECharts options, styled from the design tokens, so a
 * chart follows the theme, the user's appearance sliders and the dark
 * scheme like everything else on the page.
 *
 * ECharts itself is a megabyte: it is fetched the first time a chart
 * becomes visible, never on a page without one.
 *
 *   <section x-data="genericChart('config-id')">   generic/charts/chart.html
 *
 * A chart given a `table` follows that table: its filters and search
 * travel with every request, and a click on a bar or a slice filters
 * the table in return.
 *
 * Non-ASCII characters are written as \uXXXX escapes.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  /* -- Loading the library ---------------------------------------------- */

  var loading = null;
  var loadedLocales = {};

  function loadScript(url) {
    return new Promise(function (resolve, reject) {
      var script = document.createElement("script");

      script.src = url;
      script.async = true;
      script.onload = resolve;
      script.onerror = function () {
        script.remove();
        reject(new Error(t("The chart library could not be loaded.")));
      };
      document.head.appendChild(script);
    });
  }

  function language() {
    return (document.documentElement.lang || "en").slice(0, 2).toLowerCase();
  }

  /** ECharts, loaded once for the whole page. */
  function loadLibrary() {
    if (loading) {
      return loading;
    }

    var assets = Generic.config().assets || {};
    var locales = assets.echartsLocales || {};
    var ready = window.echarts
      ? Promise.resolve()
      : assets.echarts
        ? loadScript(assets.echarts)
        : Promise.reject(new Error(t("The chart library is not available.")));

    loading = ready
      .then(function () {
        var code = language();

        if (!locales[code] || loadedLocales[code]) {
          return null;
        }

        // A missing translation is no reason to draw nothing.
        return loadScript(locales[code]).then(
          function () {
            loadedLocales[code] = true;
          },
          function () {}
        );
      })
      .then(function () {
        return window.echarts;
      });

    loading.catch(function () {
      loading = null;
    });

    return loading;
  }

  function localeName() {
    var code = language();

    return loadedLocales[code] ? code.toUpperCase() : "EN";
  }

  /* -- Colours from the design tokens ------------------------------------ */

  /** OKLCH to sRGB hex, clamped into the gamut. */
  function oklchToHex(lightness, chroma, hue) {
    var radians = (hue * Math.PI) / 180;
    var a = chroma * Math.cos(radians);
    var b = chroma * Math.sin(radians);

    var l = Math.pow(lightness + 0.3963377774 * a + 0.2158037573 * b, 3);
    var m = Math.pow(lightness - 0.1055613458 * a - 0.0638541728 * b, 3);
    var s = Math.pow(lightness - 0.0894841775 * a - 1.291485548 * b, 3);

    var linear = [
      4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s
    ];

    return (
      "#" +
      linear
        .map(function (channel) {
          var value = Math.max(0, Math.min(1, channel));
          var encoded =
            value <= 0.0031308
              ? 12.92 * value
              : 1.055 * Math.pow(value, 1 / 2.4) - 0.055;
          var hex = Math.round(encoded * 255).toString(16);

          return hex.length === 1 ? "0" + hex : hex;
        })
        .join("")
    );
  }

  //: Hue offsets from the accent, spread so neighbours stay apart.
  var HUE_STEPS = [0, 145, 55, 215, 290, 25, 105, 250, 325, 180, 75, 350];

  /**
   * Series colours: the accent's hue first, then hues spread around the
   * wheel, at one perceptual lightness - so no series shouts louder
   * than another, and all of them read on the page's surface.
   */
  function palette(theme, count) {
    var colors = [];
    var chroma = Math.max(0.07, 0.15 * Math.min(theme.colorfulness, 1.3));
    var total = Math.max(count || 0, HUE_STEPS.length);

    for (var index = 0; index < total; index += 1) {
      var round = Math.floor(index / HUE_STEPS.length);
      var lightness = (theme.dark ? 0.74 : 0.6) + (theme.dark ? -0.1 : 0.1) * round;

      colors.push(
        oklchToHex(
          Math.max(0.3, Math.min(0.9, lightness)),
          chroma,
          (theme.hue + HUE_STEPS[index % HUE_STEPS.length]) % 360
        )
      );
    }

    return colors;
  }

  /** The tokens a chart is drawn with, resolved for the scheme in force. */
  function readTheme() {
    var colors = Generic.colors;
    var root = window.getComputedStyle(document.documentElement);

    function number(name, fallback) {
      var value = parseFloat(root.getPropertyValue(name));

      return isNaN(value) ? fallback : value;
    }

    var theme = {
      hue: number("--ui-hue", 262),
      colorfulness: number("--ui-colorfulness", 1),
      text: colors.resolve("var(--text-primary)"),
      secondary: colors.resolve("var(--text-secondary)"),
      muted: colors.resolve("var(--text-muted)"),
      border: colors.resolve("var(--border-color)"),
      surface: colors.resolve("var(--surface-raised)"),
      sunken: colors.resolve("var(--surface-sunken)"),
      accent: colors.resolve("var(--color-accent)"),
      font:
        root.getPropertyValue("--font-sans").trim() ||
        "system-ui, sans-serif"
    };

    theme.dark = colors.luminance(theme.surface) < 0.35;
    theme.palette = palette(theme, 12);

    return theme;
  }

  function withAlpha(color, alpha) {
    var channels = Generic.colors.rgb(color);

    return (
      "rgba(" + channels[0] + ", " + channels[1] + ", " + channels[2] + ", " +
      alpha + ")"
    );
  }

  /* -- Numbers ------------------------------------------------------------ */

  function formatValue(number, description, compact) {
    description = description || {};

    if (number === null || number === undefined || number === "") {
      return "\u2014";
    }

    var value = Number(number);

    if (isNaN(value)) {
      return String(number);
    }

    var decimals =
      description.decimals !== undefined && description.decimals !== null
        ? description.decimals
        : 2;
    var options = { maximumFractionDigits: decimals };

    if (description.format === "decimal" && !compact) {
      options.minimumFractionDigits = decimals;
    }

    if (compact && Math.abs(value) >= 10000) {
      options = { notation: "compact", maximumFractionDigits: 1 };
    }

    if (description.format === "percent") {
      options.style = "percent";
      value = value / 100;
    }

    var text;

    try {
      text = new Intl.NumberFormat(
        document.documentElement.lang || undefined,
        options
      ).format(value);
    } catch (error) {
      text = String(value);
    }

    return description.unit ? text + "\u202f" + description.unit : text;
  }

  /* -- Options -------------------------------------------------------------- */

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  /** `extra` over `base`, objects merged, anything else replaced. */
  function merge(base, extra) {
    if (!isObject(extra)) {
      return base;
    }

    Object.keys(extra).forEach(function (key) {
      if (isObject(base[key]) && isObject(extra[key])) {
        base[key] = merge(Object.assign({}, base[key]), extra[key]);
      } else {
        base[key] = extra[key];
      }
    });

    return base;
  }

  function categoryColor(payload, index) {
    var colors = payload.colors || [];

    return Generic.colors.clean(colors[index]);
  }

  function baseOption(payload, theme) {
    var description = payload.value || {};

    return {
      backgroundColor: "transparent",
      color: theme.palette,
      textStyle: { fontFamily: theme.font, color: theme.secondary },
      animationDuration: 350,
      aria: { enabled: true },
      tooltip: {
        confine: true,
        backgroundColor: theme.surface,
        borderColor: theme.border,
        borderWidth: 1,
        padding: [6, 10],
        textStyle: { color: theme.text, fontFamily: theme.font, fontSize: 12 },
        extraCssText:
          "border-radius: 8px; box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);",
        valueFormatter: function (value) {
          return formatValue(value, description);
        }
      }
    };
  }

  function legend(theme, extra) {
    return Object.assign(
      {
        type: "scroll",
        top: 0,
        left: 0,
        icon: "roundRect",
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 14,
        textStyle: { color: theme.secondary, fontSize: 12 },
        pageTextStyle: { color: theme.muted },
        pageIconColor: theme.secondary,
        pageIconInactiveColor: theme.border
      },
      extra || {}
    );
  }

  function cartesianOption(payload, theme) {
    var type = payload.type || "bar";
    var horizontal = Boolean(payload.horizontal);
    var categories = payload.categories || [];
    var series = payload.series || [];
    var description = payload.value || {};
    var showLegend = series.length > 1;
    var crowded = !horizontal && categories.length > 40;

    var categoryAxis = {
      type: "category",
      data: categories,
      inverse: horizontal,
      boundaryGap: type !== "line" && type !== "area",
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { show: false },
      axisLabel: { color: theme.muted, hideOverlap: true, fontSize: 11 }
    };

    var valueAxis = {
      type: "value",
      // Counts have no halves: without this a small maximum repeats
      // "1, 1, 2, 2" down the axis.
      minInterval: description.format === "integer" ? 1 : 0,
      axisLabel: {
        color: theme.muted,
        fontSize: 11,
        formatter: function (value) {
          return formatValue(value, description, true);
        }
      },
      splitLine: { lineStyle: { color: theme.border, type: "dashed" } }
    };

    var option = {
      grid: {
        // The first and last categories' labels are centred on their
        // bars and would overflow the edges - "05/19/2025" lost its 0 -
        // and containLabel counts neither.
        left: horizontal ? 4 : 28,
        right: horizontal ? 16 : 32,
        top: showLegend ? 36 : 12,
        bottom: crowded ? 44 : 4,
        containLabel: true
      },
      xAxis: horizontal ? valueAxis : categoryAxis,
      yAxis: horizontal ? categoryAxis : valueAxis,
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: type === "bar" ? "shadow" : "line",
          shadowStyle: { color: withAlpha(theme.border, 0.35) },
          lineStyle: { color: theme.border }
        }
      },
      series: series.map(function (entry) {
        var kind = entry.type || (type === "area" ? "line" : type);
        var color = Generic.colors.clean(entry.color);
        var result = {
          name: entry.name,
          type: kind,
          data: entry.data || [],
          emphasis: { focus: series.length > 1 ? "series" : "none" }
        };

        // A series may opt out - a capacity line over stacked bars.
        if (payload.stacked && entry.stack !== false) {
          result.stack = entry.stack || "total";
        }

        if (kind === "bar") {
          result.barMaxWidth = 44;
          result.itemStyle = {
            borderRadius: payload.stacked
              ? 0
              : horizontal
                ? [0, 4, 4, 0]
                : [4, 4, 0, 0]
          };
        }

        if (kind === "line") {
          result.symbol = "circle";
          result.symbolSize = 6;
          result.showSymbol = categories.length <= 40;
          result.lineStyle = { width: 2 };

          if (type === "area" || entry.area) {
            result.areaStyle = { opacity: 0.16 };
          }
        }

        if (color) {
          result.itemStyle = Object.assign(result.itemStyle || {}, {
            color: color
          });
        }

        // One series: a colour per category, when the data gives one.
        if (series.length === 1 && payload.colors) {
          result.data = result.data.map(function (value, index) {
            var own = categoryColor(payload, index);

            return own ? { value: value, itemStyle: { color: own } } : value;
          });
        }

        return result;
      })
    };

    if (showLegend) {
      option.legend = legend(theme);
    }

    if (crowded) {
      option.dataZoom = [
        { type: "inside" },
        {
          type: "slider",
          height: 16,
          bottom: 6,
          borderColor: theme.border,
          fillerColor: withAlpha(theme.accent, 0.15),
          handleStyle: { color: theme.surface, borderColor: theme.accent },
          moveHandleStyle: { color: theme.border },
          textStyle: { color: theme.muted },
          dataBackground: {
            lineStyle: { color: theme.border },
            areaStyle: { color: withAlpha(theme.border, 0.4) }
          }
        }
      ];
    }

    return option;
  }

  function pieOption(payload, theme) {
    var donut = payload.type === "donut";
    var categories = payload.categories || [];
    var entry = (payload.series || [])[0] || { data: [] };
    var description = payload.value || {};
    var labelled = categories.length <= 8;

    var data = categories.map(function (name, index) {
      var item = { name: name, value: (entry.data || [])[index] };
      var color = categoryColor(payload, index);

      if (color) {
        item.itemStyle = { color: color };
      }

      return item;
    });

    var series = {
      name: entry.name,
      type: "pie",
      radius: donut ? ["50%", "76%"] : [0, "76%"],
      center: ["50%", "54%"],
      avoidLabelOverlap: true,
      itemStyle: {
        borderColor: theme.surface,
        borderWidth: 2,
        borderRadius: donut ? 4 : 0
      },
      label: { show: labelled && !donut, color: theme.secondary },
      labelLine: { show: labelled && !donut, lineStyle: { color: theme.border } },
      data: data
    };

    if (donut) {
      // The hovered slice reads in the hole: drawn on the canvas, so the
      // label is text, never markup.
      series.label = {
        show: false,
        position: "center",
        formatter: function (params) {
          return (
            "{value|" + formatValue(params.value, description) + "}\n{name|" +
            String(params.name).replace(/[{}|]/g, "") + "}"
          );
        },
        rich: {
          value: { fontSize: 20, fontWeight: 600, color: theme.text, lineHeight: 26 },
          name: { fontSize: 12, color: theme.muted }
        }
      };
      series.emphasis = { label: { show: true }, scale: true, scaleSize: 4 };
    }

    return {
      tooltip: { trigger: "item" },
      legend: legend(theme, { top: 0 }),
      series: [series]
    };
  }

  function funnelOption(payload, theme) {
    var categories = payload.categories || [];
    var entry = (payload.series || [])[0] || { data: [] };

    return {
      tooltip: { trigger: "item" },
      legend: legend(theme),
      series: [
        {
          name: entry.name,
          type: "funnel",
          top: 36,
          bottom: 8,
          left: "8%",
          width: "84%",
          sort: "descending",
          gap: 2,
          label: {
            position: "inside",
            color: "#ffffff",
            textBorderColor: "rgba(0, 0, 0, 0.35)",
            textBorderWidth: 2
          },
          itemStyle: { borderColor: theme.surface, borderWidth: 1 },
          data: categories.map(function (name, index) {
            var item = { name: name, value: (entry.data || [])[index] };
            var color = categoryColor(payload, index);

            if (color) {
              item.itemStyle = { color: color };
            }

            return item;
          })
        }
      ]
    };
  }

  function heatmapOption(payload, theme) {
    var categories = payload.categories || [];
    var series = payload.series || [];
    var description = payload.value || {};
    var data = [];
    var highest = 0;

    series.forEach(function (entry, row) {
      (entry.data || []).forEach(function (value, column) {
        var number = Number(value) || 0;

        highest = Math.max(highest, number);
        data.push([column, row, number]);
      });
    });

    var axis = {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: theme.muted, fontSize: 11 },
      splitArea: { show: false }
    };

    return {
      tooltip: {
        trigger: "item",
        formatter: null
      },
      grid: { left: 4, right: 12, top: 8, bottom: 48, containLabel: true },
      xAxis: Object.assign({ type: "category", data: categories }, axis),
      yAxis: Object.assign(
        {
          type: "category",
          // The first series - the largest, or the first choice - on top.
          inverse: true,
          data: series.map(function (entry) {
            return entry.name;
          })
        },
        axis
      ),
      visualMap: {
        min: 0,
        max: Math.max(highest, 1),
        calculable: false,
        text: [formatValue(Math.max(highest, 1), description, true), "0"],
        itemGap: 8,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemWidth: 10,
        itemHeight: 140,
        textStyle: { color: theme.muted },
        formatter: function (value) {
          return formatValue(value, description, true);
        },
        inRange: { color: [theme.sunken, theme.palette[0]] }
      },
      series: [
        {
          name: description.label || "",
          type: "heatmap",
          data: data,
          label: {
            show: categories.length * series.length <= 150,
            color: theme.text,
            fontSize: 11,
            formatter: function (params) {
              return formatValue(params.value[2], description, true);
            }
          },
          itemStyle: {
            borderColor: theme.surface,
            borderWidth: 2,
            borderRadius: 3
          }
        }
      ]
    };
  }

  var customizers = {};

  /**
   * Adjust the options of the charts named `name` (or of every chart,
   * with "*") before they are drawn: what JSON cannot carry, such as a
   * formatter function.
   *
   *   Generic.charts.customize("opened", function (option, payload) {...});
   */
  function customize(name, callback) {
    (customizers[name] = customizers[name] || []).push(callback);
  }

  /** The ECharts options for a payload, in `theme`. */
  function buildOption(payload, theme) {
    var type = payload.type || "bar";
    var option = baseOption(payload, theme);
    var specific;

    if (type === "pie" || type === "donut") {
      specific = pieOption(payload, theme);
    } else if (type === "funnel") {
      specific = funnelOption(payload, theme);
    } else if (type === "heatmap") {
      specific = heatmapOption(payload, theme);
    } else {
      specific = cartesianOption(payload, theme);
    }

    if (specific.tooltip && specific.tooltip.formatter === null) {
      delete specific.tooltip.formatter;
    }

    merge(option, specific);
    merge(option, payload.options || {});

    [].concat(customizers["*"] || [], customizers[payload.name] || []).forEach(
      function (callback) {
        option = callback(option, payload, theme) || option;
      }
    );

    return option;
  }

  /* -- Filtering a table from a click --------------------------------------- */

  function tableElement(selector) {
    if (!selector) {
      return null;
    }

    try {
      return document.querySelector(selector);
    } catch (error) {
      return null;
    }
  }

  function tableController(selector) {
    var table = tableElement(selector);

    return table && table.genericDataTable ? table.genericDataTable : null;
  }

  /**
   * The filter condition picking one key of a dimension, in the shape
   * the table column's own filter control understands - or null when
   * the column cannot express it.
   */
  function conditionFor(controller, dimension, key, label, range) {
    if (!dimension || key === undefined || key === "__other__") {
      return null;
    }

    var column = controller.columns.find(function (entry) {
      return !entry.synthetic && entry.data === dimension.name;
    });

    if (!column || column.searchable === false) {
      return null;
    }

    var condition = null;

    // The bucket of records without a value.
    if (key === null) {
      condition = { operator: "empty" };
    } else {
      switch (column.filterType) {
        case "multiselect":
          condition = { operator: "any_of", value: [key], labels: {} };
          condition.labels[String(key)] = label;
          break;
        case "boolean":
          condition = { operator: key === true || key === "true" ? "is_true" : "is_false" };
          break;
        case "date":
        case "datetime":
          if (range) {
            condition = { operator: "between", value: range };
          }
          break;
        case "integer":
        case "float":
          condition = { operator: "equals", value: String(key) };
          break;
        default:
          condition = { operator: "equals", value: [String(key)] };
      }
    }

    if (!condition) {
      return null;
    }

    condition.column = column.filterKey || column.data;

    return condition;
  }

  /* -- The component ----------------------------------------------------------- */

  function readJson(id) {
    var element = document.getElementById(id);

    if (!element) {
      return {};
    }

    try {
      return JSON.parse(element.textContent) || {};
    } catch (error) {
      return {};
    }
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("genericChart", function (configId) {
      // Kept out of Alpine's reactive state: ECharts must see its own
      // objects, not proxies of them.
      var chart = null;
      var raw = null;
      var observer = null;
      var request = null;
      var sequence = 0;
      var lastParams = "";
      var cleanup = [];

      var config = Object.assign(
        {
          url: "",
          title: "",
          height: "18rem",
          period: "",
          periods: [],
          extraParams: {},
          table: "",
          topic: "",
          model: ""
        },
        readJson(configId)
      );

      return {
        config: config,
        payload: null,
        loading: false,
        error: "",
        view: "chart",
        period: config.period || "",
        linked: false,

        init: function () {
          var self = this;
          var canvas = this.$refs.canvas;
          var started = false;

          // Nothing is fetched until the chart can be seen: a chart in a
          // closed tab waits for the tab.
          observer = new window.ResizeObserver(function () {
            if (!canvas.offsetWidth) {
              return;
            }

            if (!started) {
              started = true;
              self.start();
              return;
            }

            if (chart) {
              chart.resize();
            }
          });
          observer.observe(canvas);

          // A page's own filters: new parameters, and the chart reloads.
          // Dispatched from anywhere - Alpine's $dispatch bubbles up to
          // the document - naming the chart, or all charts when unnamed:
          //   $dispatch("generic:chart-params",
          //             { chart: "workload", params: { group: "4" } })
          var onParams = function (event) {
            var detail = (event && event.detail) || {};
            var params = detail.params;

            if (detail.chart && detail.chart !== self.config.name) {
              return;
            }

            if (!params) {
              params = Object.assign({}, detail);
              delete params.chart;
            }

            self.config.extraParams = Object.assign(
              {},
              self.config.extraParams || {},
              params
            );

            if (started) {
              self.load();
            }
          };

          document.addEventListener("generic:chart-params", onParams);
          cleanup.push(function () {
            document.removeEventListener("generic:chart-params", onParams);
          });

          var redraw = Generic.debounce(function () {
            self.redraw();
          }, 80);

          ["generic:themechange", "generic:appearancechange"].forEach(
            function (name) {
              document.addEventListener(name, redraw);
              cleanup.push(function () {
                document.removeEventListener(name, redraw);
              });
            }
          );

          if (window.matchMedia) {
            var scheme = window.matchMedia("(prefers-color-scheme: dark)");

            if (scheme.addEventListener) {
              scheme.addEventListener("change", redraw);
              cleanup.push(function () {
                scheme.removeEventListener("change", redraw);
              });
            }
          }
        },

        destroy: function () {
          if (observer) {
            observer.disconnect();
          }

          cleanup.forEach(function (callback) {
            callback();
          });
          cleanup = [];

          if (chart) {
            chart.dispose();
            chart = null;
          }
        },

        start: function () {
          var self = this;
          var table = tableElement(this.config.table);

          this.follow();

          if (!table) {
            this.load();
            return;
          }

          if (table.genericDataTable) {
            this.link(table.genericDataTable);
            this.load();
            return;
          }

          // The table is about to start: its saved filters travel with
          // the first request, so the chart waits for them.
          var fallback = window.setTimeout(function () {
            self.load();
          }, 2000);

          table.addEventListener(
            "generic:datatable-ready",
            function (event) {
              window.clearTimeout(fallback);
              self.link(event.detail.controller);

              // The table's own first draw is what carries the
              // restored filters; loading then avoids asking twice.
              event.detail.api.one("xhr.dt", function () {
                self.load();
              });
            },
            { once: true }
          );
        },

        /** Follow a table: reload when its rows change for a new reason. */
        link: function (controller) {
          var self = this;

          if (!controller || !controller.instance) {
            return;
          }

          this.linked = true;

          var reload = Generic.debounce(function () {
            if (JSON.stringify(self.params()) !== lastParams) {
              self.load();
            }
          }, 150);

          controller.instance.on("xhr.dt", reload);
          cleanup.push(function () {
            try {
              controller.instance.off("xhr.dt", reload);
            } catch (error) {
              /* The table is gone already. */
            }
          });
        },

        /** Reload when a record of the model changes, anywhere. */
        follow: function () {
          var self = this;
          var topic = this.config.topic;

          if (!topic || !Generic.events) {
            return;
          }

          var reload = Generic.debounce(function () {
            self.load();
          }, 1200);

          Generic.events.subscribe(topic);
          cleanup.push(
            Generic.events.on("resource.changed", function (payload) {
              if (!payload.resource || payload.resource === self.config.model) {
                reload();
              }
            })
          );
        },

        params: function () {
          var params = Object.assign({}, this.config.extraParams || {});
          var controller = tableController(this.config.table);

          if (controller) {
            Object.assign(params, controller.currentParams());
          }

          if (this.period) {
            params.period = this.period;
          }

          return params;
        },

        load: function () {
          var self = this;
          var params = this.params();
          var current = (sequence += 1);

          lastParams = JSON.stringify(params);

          if (request) {
            request.abort();
          }

          request = window.AbortController ? new window.AbortController() : null;

          this.loading = true;
          this.error = "";

          return Promise.all([
            loadLibrary(),
            Generic.api.get(this.config.url, params, {
              signal: request ? request.signal : undefined
            })
          ])
            .then(function (results) {
              if (current !== sequence) {
                return;
              }

              raw = results[1] || {};
              self.payload = raw;
              self.draw(results[0]);
            })
            .catch(function (error) {
              if (current !== sequence || (error && error.name === "AbortError")) {
                return;
              }

              self.error =
                (error && error.message) || t("The chart could not be loaded.");
            })
            .then(function () {
              if (current === sequence) {
                self.loading = false;
              }
            });
        },

        draw: function (echarts) {
          var self = this;

          if (!echarts || !raw) {
            return;
          }

          if (!chart) {
            chart = echarts.init(this.$refs.canvas, null, {
              renderer: "canvas",
              locale: localeName()
            });
            chart.on("click", function (params) {
              self.select(params);
            });
          }

          chart.setOption(buildOption(raw, readTheme()), { notMerge: true });
        },

        redraw: function () {
          if (chart && raw) {
            chart.setOption(buildOption(raw, readTheme()), { notMerge: true });
          }
        },

        /** A click filters the linked table on what was clicked. */
        select: function (params) {
          var controller = tableController(this.config.table);

          if (!controller || !raw || !raw.dimension) {
            return;
          }

          var index = params.dataIndex;
          var seriesIndex = params.seriesIndex;

          if (raw.type === "heatmap" && Array.isArray(params.value)) {
            index = params.value[0];
            seriesIndex = params.value[1];
          }

          var keys = raw.keys || [];
          var entries = [
            conditionFor(
              controller,
              raw.dimension,
              keys[index],
              (raw.categories || [])[index],
              (raw.ranges || [])[index]
            )
          ];

          if (raw.split && raw.series && raw.series[seriesIndex]) {
            var series = raw.series[seriesIndex];

            entries.push(
              conditionFor(controller, raw.split, series.key, series.name, null)
            );
          }

          entries = entries.filter(Boolean);

          if (!entries.length) {
            return;
          }

          // Each clicked value replaces what filtered its column; one
          // request for all of them.
          entries.forEach(function (condition) {
            controller.setColumnCondition(condition, false);
          });

          controller.redraw();
        },

        toggleView: function () {
          this.view = this.view === "chart" ? "table" : "chart";

          if (this.view === "chart") {
            this.$nextTick(function () {
              if (chart) {
                chart.resize();
              }
            });
          }
        },

        format: function (value) {
          return formatValue(value, raw && raw.value);
        },

        download: function () {
          if (!chart) {
            return;
          }

          var link = document.createElement("a");

          link.href = chart.getDataURL({
            type: "png",
            pixelRatio: 2,
            backgroundColor: readTheme().surface
          });
          link.download = (this.config.name || "chart") + ".png";
          document.body.appendChild(link);
          link.click();
          link.remove();
        }
      };
    });
  });

  Generic.charts = {
    buildOption: buildOption,
    customize: customize,
    formatValue: formatValue,
    load: loadLibrary,
    palette: palette,
    readTheme: readTheme
  };
})(window, document);
