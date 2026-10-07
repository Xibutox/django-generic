/**
 * Shared vocabulary for the DataTables integration.
 *
 * Translation, filter types, operator tables, defaults, small helpers
 * and the feature registry. Everything else in `datatables/` builds on
 * this file, which is why it must load first.
 *
 * Every symbol is written as a \uXXXX escape rather than a literal
 * glyph. The file this was ported from had been through a latin-1
 * round trip and every accented word in it was corrupted; escapes
 * cannot be damaged that way.
 */
(function (window, document) {
  "use strict";

  var namespace = (window.GenericDataTables =
    window.GenericDataTables || {});

  /* -- Translation ---------------------------------------------------
   *
   * Django's JavaScript catalog defines `gettext` globally when the
   * page loads it. Without it, the English source string is used, so
   * a project that never wires the catalog still gets a working table.
   */

  function t(text) {
    return typeof window.gettext === "function"
      ? window.gettext(text)
      : text;
  }

  function format(text, values) {
    return String(text).replace(/%\((\w+)\)s/g, function (match, key) {
      return Object.prototype.hasOwnProperty.call(values, key)
        ? values[key]
        : match;
    });
  }

  /* -- Filter types -------------------------------------------------- */

  var FILTER_TYPES = Object.freeze({
    TEXT: "text",
    INTEGER: "integer",
    FLOAT: "float",
    DATE: "date",
    DATETIME: "datetime",
    BOOLEAN: "boolean",
    MULTISELECT: "multiselect"
  });

  var FILTER_TYPE_ALIASES = Object.freeze({
    text: FILTER_TYPES.TEXT,
    string: FILTER_TYPES.TEXT,
    char: FILTER_TYPES.TEXT,
    link: FILTER_TYPES.TEXT,
    tags: FILTER_TYPES.TEXT,
    integer: FILTER_TYPES.INTEGER,
    int: FILTER_TYPES.INTEGER,
    number: FILTER_TYPES.FLOAT,
    float: FILTER_TYPES.FLOAT,
    decimal: FILTER_TYPES.FLOAT,
    date: FILTER_TYPES.DATE,
    datetime: FILTER_TYPES.DATETIME,
    boolean: FILTER_TYPES.BOOLEAN,
    bool: FILTER_TYPES.BOOLEAN,
    multiselect: FILTER_TYPES.MULTISELECT,
    select: FILTER_TYPES.MULTISELECT
  });

  /* -- Operators -----------------------------------------------------
   *
   * What each filter engine offers (generic/api/filters.py), with the
   * words a filter is read with - "Status is any of Open, Pending" -
   * and the shape of value it takes:
   *
   *   none    no value: "is empty", "this month"
   *   many    one or several words or numbers, any of which may match
   *   one     one value
   *   range   a lower and an upper bound, either optional
   *   days    a number of days
   *   choices values picked from a list
   *
   * Built lazily and cached: the labels are translated, and the
   * catalog may not be loaded yet when this file runs.
   */

  var operatorCache = null;

  //: `short` is what a chip says, when shorter than the list's words.
  function op(value, label, arity, group, short) {
    return { value: value, label: label, arity: arity, group: group || "", short: short || label };
  }

  function emptyOperators() {
    return [op("empty", t("is empty"), "none"), op("not_empty", t("is not empty"), "none")];
  }

  function operators() {
    if (operatorCache) {
      return operatorCache;
    }

    var relative = t("Relative");
    var numbers = [
      op("equals", t("= equals"), "one", "", "="),
      op("not_equals", t("\u2260 does not equal"), "one", "", "\u2260"),
      op("gt", t("> greater than"), "one", "", ">"),
      op("gte", t("\u2265 at least"), "one", "", "\u2265"),
      op("lt", t("< less than"), "one", "", "<"),
      op("lte", t("\u2264 at most"), "one", "", "\u2264"),
      op("between", t("is between"), "range")
    ].concat(emptyOperators());
    var dates = [
      op("on", t("is on"), "one"),
      op("not_on", t("is not on"), "one"),
      op("before", t("is before"), "one"),
      op("after", t("is after"), "one"),
      op("on_or_before", t("is on or before"), "one"),
      op("on_or_after", t("is on or after"), "one"),
      op("between", t("is between"), "range"),
      op("today", t("is today"), "none", relative),
      op("yesterday", t("is yesterday"), "none", relative),
      op("tomorrow", t("is tomorrow"), "none", relative),
      op("this_week", t("is this week"), "none", relative),
      op("last_week", t("is last week"), "none", relative),
      op("next_week", t("is next week"), "none", relative),
      op("this_month", t("is this month"), "none", relative),
      op("last_month", t("is last month"), "none", relative),
      op("next_month", t("is next month"), "none", relative),
      op("this_quarter", t("is this quarter"), "none", relative),
      op("last_quarter", t("is last quarter"), "none", relative),
      op("this_year", t("is this year"), "none", relative),
      op("last_year", t("is last year"), "none", relative),
      op("last_days", t("is in the last"), "days", relative),
      op("next_days", t("is in the next"), "days", relative),
      op("older_than_days", t("is more than"), "days", relative)
    ].concat(emptyOperators());

    operatorCache = Object.freeze({
      text: [
        op("contains", t("contains"), "many"),
        op("not_contains", t("does not contain"), "many"),
        op("equals", t("is"), "many"),
        op("not_equals", t("is not"), "many"),
        op("starts_with", t("starts with"), "many"),
        op("ends_with", t("ends with"), "many")
      ].concat(emptyOperators()),
      integer: numbers,
      float: numbers,
      date: dates,
      datetime: dates,
      boolean: [
        op("is_true", t("is yes"), "none"),
        op("is_false", t("is no"), "none")
      ].concat(emptyOperators()),
      multiselect: [
        op("any_of", t("is any of"), "choices"),
        op("none_of", t("is none of"), "choices"),
        op("all_of", t("has all of"), "choices"),
        op("contains", t("contains"), "many"),
        op("not_contains", t("does not contain"), "many")
      ].concat(emptyOperators())
    });

    return operatorCache;
  }

  /** The operators a column offers, and the one a new filter starts with. */
  function operatorsFor(column) {
    var list = operators()[column.filterType] || operators().text;

    if (column.filterType === FILTER_TYPES.MULTISELECT) {
      list = list.filter(function (entry) {
        if (entry.value === "all_of") {
          return Boolean(column.filterMany);
        }

        // Words in the values' text: a relation, whose records the
        // server searches by name.
        if (entry.value === "contains" || entry.value === "not_contains") {
          return Boolean(column.textSearch);
        }

        return true;
      });
    }

    return list;
  }

  function findOperator(column, value) {
    var list = operatorsFor(column);

    for (var index = 0; index < list.length; index += 1) {
      if (list[index].value === value) {
        return list[index];
      }
    }

    return null;
  }

  /* -- Defaults ------------------------------------------------------ */

  function language() {
    return {
      processing: t("Loading\u2026"),
      search: "",
      searchPlaceholder: t("Search all columns\u2026"),
      lengthMenu: t("_MENU_ rows"),
      info: t("_START_ to _END_ of _TOTAL_ rows"),
      infoEmpty: t("No rows"),
      infoFiltered: t("(filtered from _MAX_ rows)"),
      zeroRecords: t("No matching rows"),
      emptyTable: t("No data available"),
      paginate: {
        first: t("First"),
        previous: t("Previous"),
        next: t("Next"),
        last: t("Last")
      }
    };
  }

  var DEFAULTS = Object.freeze({
    selector: ".js-generic-datatable, .js-drf-datatable",
    pageLength: 15,
    lengthMenu: [10, 15, 25, 50, 100],
    searchDelay: 350,
    stateSave: true,
    stateKey: null,
    filters: true,
    // The row of search fields under the headers: "open" from the
    // start, "toggle" behind a button, false not offered.
    filterRow: "open",
    columnSelector: true,
    columnSelectorLabel: "",
    excel: true,
    csv: false,
    copy: true,
    print: true,
    extraParams: {}
  });

  /* -- Features -------------------------------------------------------
   *
   * A feature is a plain object extending every table on the page. The
   * controller calls whichever of these it defines:
   *
   *   enabled(controller)  whether this table wants it at all
   *   prepare(controller)  before DataTables starts; may add a column
   *   header(controller, thead)
   *                        after the row of titles, before DataTables
   *                        starts; may add a row, which DataTables then
   *                        keeps in step with the columns shown
   *   top(controller)      a node for the band above the table
   *   loadState(controller, data)
   *   saveState(controller, data)
   *                        read and write the table's remembered state
   *   init(controller)     once the DataTables instance exists
   *   destroy(controller)
   */

  var featureRegistry = [];

  function registerFeature(feature) {
    featureRegistry.push(feature);
  }

  /* -- Helpers ------------------------------------------------------- */

  function readJsonScript(id, fallback) {
    if (!id) {
      return fallback;
    }

    var element = document.getElementById(id);

    if (!element) {
      throw new Error(
        format(t("Configuration script #%(id)s was not found."), {
          id: id
        })
      );
    }

    return JSON.parse(element.textContent);
  }

  function debounce(callback, delay) {
    var timer;

    return function () {
      var args = arguments;
      var context = this;

      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        callback.apply(context, args);
      }, delay);
    };
  }

  function escapeHtml(value) {
    var node = document.createElement("div");
    node.textContent = value === null || value === undefined
      ? ""
      : String(value);

    return node.innerHTML;
  }

  /**
   * Whether a URL is safe to put in an href.
   *
   * Escaping a URL does not make it safe: `javascript:alert(1)` is
   * perfectly valid HTML and runs on click. Only relative URLs and the
   * navigational schemes are allowed through.
   */
  function isSafeUrl(value) {
    var url = String(value).trim();

    if (/^[a-z][a-z0-9+.-]*:/i.test(url)) {
      return /^(https?|mailto|tel):/i.test(url);
    }

    // Relative, root-relative, protocol-relative or a fragment.
    return true;
  }

  /**
   * Fill `{field}` tokens of a URL template from a row.
   *
   * Every value is percent-encoded, and the result is refused if it is
   * not a navigational URL.
   */
  function fillTemplate(template, row) {
    var url = String(template || "").replace(/\{([^}]+)\}/g, function (match, field) {
      var value = row[field];

      if (value === null || value === undefined) {
        return "";
      }

      return encodeURIComponent(String(value));
    });

    return isSafeUrl(url) ? url : "";
  }

  /**
   * Render an ISO date for display, in the page's own language.
   *
   * The value handled here is always `YYYY-MM-DD`, which is what the
   * server's date filters accept.
   */
  function formatDate(value) {
    if (!value) {
      return "";
    }

    return formatStamp(String(value).slice(0, 10));
  }

  var STAMP = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/;
  var stampFormats = {};

  /**
   * A date, or a date and time, as the page's language writes one:
   * 26/09/2026 09:51 in French, 09/26/2026, 09:51 AM in English.
   *
   * The server sends ISO already in its active time zone, so the
   * wall-clock digits are drawn as they are - read as UTC and written
   * as UTC - rather than moved into the browser's own zone, which
   * would disagree with the day the filters count in. Anything that is
   * not ISO (a project's own TABLE_DATETIME_FORMAT) is left alone.
   */
  function formatStamp(value) {
    if (value === null || value === undefined || value === "") {
      return "";
    }

    var match = STAMP.exec(String(value));

    if (!match || typeof Intl === "undefined") {
      return String(value);
    }

    var withTime = match[4] !== undefined;
    var date = new Date(
      Date.UTC(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3]),
        withTime ? Number(match[4]) : 0,
        withTime ? Number(match[5]) : 0
      )
    );

    if (isNaN(date.getTime())) {
      return String(value);
    }

    var key = withTime ? "datetime" : "date";

    if (!stampFormats[key]) {
      var options = {
        timeZone: "UTC",
        year: "numeric",
        month: "2-digit",
        day: "2-digit"
      };

      if (withTime) {
        options.hour = "2-digit";
        options.minute = "2-digit";
      }

      stampFormats[key] = new Intl.DateTimeFormat(
        document.documentElement.lang || undefined,
        options
      );
    }

    return stampFormats[key].format(date);
  }

  function resolveExtraParams(options, table) {
    return typeof options.extraParams === "function"
      ? options.extraParams(table) || {}
      : options.extraParams || {};
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);

    if (className) {
      node.className = className;
    }

    if (text !== undefined && text !== null) {
      node.textContent = text;
    }

    return node;
  }

  function icon(name, extra) {
    var node = el(
      "span",
      "icon material-symbols-outlined" + (extra ? " " + extra : ""),
      name
    );
    node.setAttribute("aria-hidden", "true");

    return node;
  }

  namespace.core = {
    DEFAULTS: DEFAULTS,
    FILTER_TYPES: FILTER_TYPES,
    FILTER_TYPE_ALIASES: FILTER_TYPE_ALIASES,
    debounce: debounce,
    el: el,
    escapeHtml: escapeHtml,
    featureRegistry: featureRegistry,
    fillTemplate: fillTemplate,
    findOperator: findOperator,
    format: format,
    formatDate: formatDate,
    formatStamp: formatStamp,
    icon: icon,
    isSafeUrl: isSafeUrl,
    language: language,
    operators: operators,
    operatorsFor: operatorsFor,
    readJsonScript: readJsonScript,
    registerFeature: registerFeature,
    resolveExtraParams: resolveExtraParams,
    t: t
  };
})(window, document);
