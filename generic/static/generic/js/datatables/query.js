/**
 * The filters of a table, as data.
 *
 * A filter tree is what the server reads (generic/api/filters.py):
 *
 *   { match: "all", conditions: [
 *       { column: "status", operator: "any_of", value: ["open"],
 *         labels: { open: "Open" } },
 *       { match: "any", conditions: [ ... ] } ] }
 *
 * This file knows how to build one, bring an older flat payload up to
 * date, tell whether a condition is complete, describe a condition in
 * words for its chip, and read the query language typed in the search
 * box:
 *
 *   status:open,pending   -tags:billing   hours:>=2   opened:30d
 *   due:2026-01-01..2026-03-31   title:"password reset"   assignee:empty
 *
 * Nothing here touches the page; filterbar.js draws it.
 *
 * Non-ASCII characters are written as \uXXXX escapes.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var t = core.t;
  var TYPES = core.FILTER_TYPES;

  var MATCH_ALL = "all";
  var MATCH_ANY = "any";

  /** Groups inside the top level, at most: the editor draws no deeper. */
  var MAX_GROUP_DEPTH = 1;

  var counter = 0;

  function uid() {
    counter += 1;

    return "f" + counter + "-" + Math.random().toString(36).slice(2, 7);
  }

  function clone(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function emptyTree() {
    return { id: uid(), match: MATCH_ALL, conditions: [] };
  }

  function isGroup(node) {
    return Boolean(node && typeof node === "object" && Array.isArray(node.conditions));
  }

  /* -- Columns ---------------------------------------------------------- */

  function keyOf(column) {
    return column.filterKey || column.data;
  }

  function filterable(columns) {
    return columns.filter(function (column) {
      return !column.synthetic && column.searchable !== false && keyOf(column);
    });
  }

  function columnFor(columns, key) {
    if (key === undefined || key === null) {
      return null;
    }

    for (var index = 0; index < columns.length; index += 1) {
      var column = columns[index];

      if (!column.synthetic && keyOf(column) === key && column.searchable !== false) {
        return column;
      }
    }

    return null;
  }

  /** "number", "date", "boolean", "multiselect" or "text". */
  function kind(column) {
    switch (column.filterType) {
      case TYPES.INTEGER:
      case TYPES.FLOAT:
        return "number";
      case TYPES.DATE:
      case TYPES.DATETIME:
        return "date";
      case TYPES.BOOLEAN:
        return "boolean";
      case TYPES.MULTISELECT:
        return "multiselect";
      default:
        return "text";
    }
  }

  /** What a new filter on `column` starts as. */
  function newCondition(column) {
    var operator = {
      text: "contains",
      number: "equals",
      date: "between",
      boolean: "is_true",
      multiselect: "any_of"
    }[kind(column)];

    var condition = { id: uid(), column: keyOf(column), operator: operator };

    if (operator === "any_of" || operator === "contains") {
      condition.value = [];
    }

    return condition;
  }

  /* -- The older payload -------------------------------------------------- */

  var LEGACY = {
    text: {
      exact: "equals",
      not_exact: "not_equals",
      starts: "starts_with",
      ends: "ends_with"
    },
    number: {
      exact: "equals",
      not_exact: "not_equals",
      greater_than: "gt",
      greater_or_equal: "gte",
      less_than: "lt",
      less_or_equal: "lte"
    },
    date: {
      exact: "on",
      not_exact: "not_on",
      equals: "on",
      not_equals: "not_on",
      greater_than: "after",
      greater_or_equal: "on_or_after",
      less_than: "before",
      less_or_equal: "on_or_before"
    },
    multiselect: { include: "any_of", exclude: "none_of" }
  };

  var TRUE_WORDS = ["true", "1", "yes", "y", "on", "oui", "vrai"];
  var FALSE_WORDS = ["false", "0", "no", "n", "off", "non", "faux"];

  function upgrade(node, column) {
    var group = kind(column);
    var operator = String(node.operator || "");
    var condition = {
      column: keyOf(column),
      operator: (LEGACY[group] && LEGACY[group][operator]) || operator
    };
    var value = clone(node.value);

    if (group === "boolean" && /^(not_)?(exact|equals)$/.test(operator)) {
      var truthy = TRUE_WORDS.indexOf(String(value).toLowerCase()) !== -1;
      var negated = operator.indexOf("not_") === 0;

      condition.operator = truthy !== negated ? "is_true" : "is_false";
      value = undefined;
    }

    // The older date range forms: "after" and "before" with an object.
    if (group === "date" && value && typeof value === "object" && !Array.isArray(value)) {
      if (operator === "after") {
        condition.operator = "on_or_after";
        value = value.from;
      } else if (operator === "before") {
        condition.operator = "on_or_before";
        value = value.to;
      }
    }

    if (value !== undefined) {
      condition.value = value;
    }

    if (node.labels && typeof node.labels === "object") {
      condition.labels = clone(node.labels);
    }

    return condition;
  }

  /**
   * A tree the controls can work with, from whatever was stored: a
   * tree, the older flat payload, or nothing. Columns that no longer
   * exist and operators they do not offer are dropped.
   */
  function normalize(input, columns) {
    if (!input || typeof input !== "object") {
      return emptyTree();
    }

    if (!isGroup(input)) {
      var tree = emptyTree();

      Object.keys(input).forEach(function (key) {
        var node = input[key];
        var column = columnFor(columns, key);

        if (!column || !node || typeof node !== "object") {
          return;
        }

        var condition = upgrade(node, column);

        if (core.findOperator(column, condition.operator)) {
          condition.id = uid();
          tree.conditions.push(condition);
        }
      });

      return tree;
    }

    return normalizeGroup(input, columns, 0);
  }

  function normalizeGroup(group, columns, depth) {
    var result = {
      id: group.id || uid(),
      match: group.match === MATCH_ANY ? MATCH_ANY : MATCH_ALL,
      conditions: []
    };

    group.conditions.forEach(function (node) {
      if (isGroup(node)) {
        if (depth < MAX_GROUP_DEPTH) {
          var child = normalizeGroup(node, columns, depth + 1);

          if (child.conditions.length) {
            result.conditions.push(child);
          }
        }

        return;
      }

      if (!node || typeof node !== "object") {
        return;
      }

      var column = columnFor(columns, node.column);

      if (!column) {
        return;
      }

      var condition = upgrade(node, column);

      if (!core.findOperator(column, condition.operator)) {
        return;
      }

      condition.id = node.id || uid();
      result.conditions.push(condition);
    });

    return result;
  }

  /* -- Completeness --------------------------------------------------------- */

  function arityOf(condition, column) {
    var operator = core.findOperator(column, condition.operator);

    return operator ? operator.arity : null;
  }

  function isComplete(condition, column) {
    var arity = arityOf(condition, column);
    var value = condition.value;

    switch (arity) {
      case "none":
        return true;
      case "many":
      case "choices":
        return Array.isArray(value)
          ? value.some(function (item) {
              return item !== null && item !== undefined && String(item) !== "";
            })
          : value !== null && value !== undefined && String(value) !== "";
      case "one":
        return value !== null && value !== undefined && String(value).trim() !== "";
      case "range":
        return Boolean(
          value &&
            typeof value === "object" &&
            ((value.from !== null && value.from !== undefined && value.from !== "") ||
              (value.to !== null && value.to !== undefined && value.to !== ""))
        );
      case "days":
        return Number(value) > 0 && Math.floor(Number(value)) === Number(value);
      default:
        return false;
    }
  }

  /** Conditions of a tree, depth first. */
  function flatten(tree) {
    var found = [];

    (function walk(group) {
      group.conditions.forEach(function (node) {
        if (isGroup(node)) {
          walk(node);
        } else {
          found.push(node);
        }
      });
    })(tree);

    return found;
  }

  function count(tree, columns) {
    return flatten(tree).filter(function (condition) {
      var column = columnFor(columns, condition.column);

      return column && isComplete(condition, column);
    }).length;
  }

  /** What the endpoint receives: complete conditions, no local keys. */
  function forRequest(tree, columns) {
    function walk(group) {
      var conditions = [];

      group.conditions.forEach(function (node) {
        if (isGroup(node)) {
          var child = walk(node);

          if (child) {
            conditions.push(child);
          }

          return;
        }

        var column = columnFor(columns, node.column);

        if (!column || !isComplete(node, column)) {
          return;
        }

        var item = { column: node.column, operator: node.operator };

        if (arityOf(node, column) !== "none") {
          item.value = clone(node.value);
        }

        conditions.push(item);
      });

      return conditions.length ? { match: group.match, conditions: conditions } : null;
    }

    return walk(tree);
  }

  /** What a saved view or the browser keeps: labels included. */
  function forState(tree) {
    var copy = clone(tree);

    (function strip(group) {
      delete group.id;
      group.conditions.forEach(function (node) {
        if (isGroup(node)) {
          strip(node);
        } else {
          delete node.id;
        }
      });
    })(copy);

    return copy;
  }

  /** The group holding `id`, and its index there. */
  function locate(tree, id) {
    var found = null;

    (function walk(group) {
      group.conditions.forEach(function (node, index) {
        if (found) {
          return;
        }

        if (node.id === id) {
          found = { group: group, index: index, node: node };
        } else if (isGroup(node)) {
          walk(node);
        }
      });
    })(tree);

    return found;
  }

  function remove(tree, id) {
    var place = locate(tree, id);

    if (!place) {
      return false;
    }

    place.group.conditions.splice(place.index, 1);
    prune(tree);

    return true;
  }

  /** Drop empty groups, and unwrap a group left with one condition. */
  function prune(tree) {
    tree.conditions = tree.conditions
      .map(function (node) {
        if (!isGroup(node)) {
          return node;
        }

        prune(node);

        return node.conditions.length === 1 ? node.conditions[0] : node;
      })
      .filter(function (node) {
        return !isGroup(node) || node.conditions.length;
      });

    return tree;
  }

  function conditionsOn(tree, key) {
    return flatten(tree).filter(function (condition) {
      return condition.column === key;
    });
  }

  /* -- Words ------------------------------------------------------------------ */

  function formatNumber(value) {
    var number = Number(value);

    if (value === "" || value === null || value === undefined || isNaN(number)) {
      return String(value);
    }

    try {
      return number.toLocaleString(document.documentElement.lang || undefined);
    } catch (error) {
      return String(number);
    }
  }

  function formatScalar(value, column) {
    var group = kind(column);

    if (group === "date") {
      return core.formatDate(String(value).slice(0, 10));
    }

    if (group === "number") {
      return formatNumber(value);
    }

    return "\u201c" + String(value) + "\u201d";
  }

  function choiceLabel(condition, column, value) {
    var key = String(value);

    if (condition.labels && Object.prototype.hasOwnProperty.call(condition.labels, key)) {
      return condition.labels[key];
    }

    var choices = column.choices || [];

    for (var index = 0; index < choices.length; index += 1) {
      if (String(choices[index].value) === key) {
        return choices[index].label;
      }
    }

    return key;
  }

  function joinLabels(labels, joiner) {
    if (labels.length <= 3) {
      return labels.join(joiner);
    }

    return (
      labels.slice(0, 2).join(joiner) +
      " " +
      core.format(t("and %(count)s more"), { count: labels.length - 2 })
    );
  }

  /**
   * A condition in words, split for its chip:
   * { field: "Status", operator: "is any of", value: "Open, Pending" }.
   */
  function describe(condition, column) {
    var operator = core.findOperator(column, condition.operator);
    var value = condition.value;
    var text = "";

    if (!operator) {
      return { field: column.title, operator: condition.operator, value: "" };
    }

    switch (operator.arity) {
      case "choices":
        text = joinLabels(
          (Array.isArray(value) ? value : [value]).map(function (item) {
            return choiceLabel(condition, column, item);
          }),
          ", "
        );
        break;
      case "many":
        text = joinLabels(
          (Array.isArray(value) ? value : [value]).map(function (item) {
            return formatScalar(item, column);
          }),
          " " + t("or") + " "
        );
        break;
      case "one":
        text = formatScalar(value, column);
        break;
      case "range":
        value = value || {};

        if (value.from && value.to) {
          text = formatScalar(value.from, column) + " \u2013 " + formatScalar(value.to, column);
        } else if (value.from) {
          text = "\u2265 " + formatScalar(value.from, column);
        } else if (value.to) {
          text = "\u2264 " + formatScalar(value.to, column);
        }
        break;
      case "days":
        text =
          condition.operator === "older_than_days"
            ? core.format(t("%(count)s days ago"), { count: value })
            : core.format(t("%(count)s days"), { count: value });
        break;
      default:
        text = "";
    }

    return { field: column.title, operator: operator.short || operator.label, value: text };
  }

  function describeText(condition, column) {
    var parts = describe(condition, column);

    return [parts.field, parts.operator, parts.value].filter(Boolean).join(" ");
  }

  /* -- The query language ------------------------------------------------------ */

  function squash(text) {
    return String(text || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[\s_-]+/g, "");
  }

  /** The column a typed name means: its key, or its title. */
  function findColumn(columns, name) {
    var wanted = squash(name);
    var candidates = filterable(columns);

    if (!wanted) {
      return null;
    }

    var exact = candidates.find(function (column) {
      return squash(keyOf(column)) === wanted || squash(column.title) === wanted;
    });

    if (exact) {
      return exact;
    }

    var prefixed = candidates.filter(function (column) {
      return squash(keyOf(column)).indexOf(wanted) === 0 || squash(column.title).indexOf(wanted) === 0;
    });

    if (prefixed.length === 1) {
      return prefixed[0];
    }

    // A word of the name: "hours" for "Estimated hours".
    var worded = candidates.filter(function (column) {
      var words = (String(keyOf(column)) + " " + String(column.title)).split(/[\s_-]+/);

      return words.some(function (word) {
        return squash(word).indexOf(wanted) === 0;
      });
    });

    return worded.length === 1 ? worded[0] : null;
  }

  /** Columns whose key or title starts with what was typed. */
  function suggestColumns(columns, typed) {
    var wanted = squash(typed);

    return filterable(columns).filter(function (column) {
      return (
        !wanted ||
        squash(keyOf(column)).indexOf(wanted) === 0 ||
        squash(column.title).indexOf(wanted) === 0 ||
        squash(column.title).indexOf(wanted) !== -1
      );
    });
  }

  /** Words and quoted phrases with where they sit in the text. */
  function tokenize(text) {
    var pattern = /[-!]?[^\s:"]+:(?:"[^"]*"?|[^\s]*)|"[^"]*"?|\S+/g;
    var tokens = [];
    var match;

    while ((match = pattern.exec(text))) {
      tokens.push({ text: match[0], start: match.index, end: match.index + match[0].length });
    }

    return tokens;
  }

  function unquote(text) {
    var value = String(text);

    if (value.charAt(0) === '"') {
      value = value.slice(1);

      if (value.charAt(value.length - 1) === '"') {
        value = value.slice(0, -1);
      }
    }

    return value;
  }

  /** Comma separated parts, quotes kept together. */
  function splitList(text) {
    var parts = [];
    var pattern = /"([^"]*)"?|([^,]+)/g;
    var match;

    while ((match = pattern.exec(text))) {
      var part = (match[1] !== undefined ? match[1] : match[2]).trim();

      if (part) {
        parts.push(part);
      }
    }

    return parts;
  }

  var RELATIVE_WORDS = {
    today: "today",
    yesterday: "yesterday",
    tomorrow: "tomorrow",
    thisweek: "this_week",
    lastweek: "last_week",
    nextweek: "next_week",
    thismonth: "this_month",
    lastmonth: "last_month",
    nextmonth: "next_month",
    thisquarter: "this_quarter",
    lastquarter: "last_quarter",
    thisyear: "this_year",
    lastyear: "last_year"
  };

  var COMPARISONS = {
    number: { "": "equals", "=": "equals", "!=": "not_equals", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte" },
    date: { "": "on", "=": "on", "!=": "not_on", ">": "after", ">=": "on_or_after", "<": "before", "<=": "on_or_before" }
  };

  var NEGATED = {
    equals: "not_equals",
    contains: "not_contains"
  };

  var ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
  var NUMBER = /^-?\d+(?:[.,]\d+)?$/;

  /**
   * The condition typed after "name:". Returns null when the text makes
   * no sense for the column. A multiselect keeps what it could not
   * match to a value in `unresolved`, for the caller to look up.
   */
  function conditionFromText(column, text, negated) {
    var key = keyOf(column);
    var group = kind(column);
    var raw = String(text).trim();
    var lower = squash(raw);
    var condition = null;

    if (!raw) {
      return null;
    }

    if (["empty", "none", "null", "vide", "aucun"].indexOf(lower) !== -1) {
      return { id: uid(), column: key, operator: negated ? "not_empty" : "empty" };
    }

    if (group === "boolean") {
      if (TRUE_WORDS.indexOf(lower) !== -1) {
        condition = { column: key, operator: negated ? "is_false" : "is_true" };
      } else if (FALSE_WORDS.indexOf(lower) !== -1) {
        condition = { column: key, operator: negated ? "is_true" : "is_false" };
      }
    } else if (group === "number" || group === "date") {
      var scalar = group === "number" ? NUMBER : ISO_DATE;
      var range = raw.split("..");

      if (range.length === 2) {
        var low = range[0].trim().replace(",", ".");
        var high = range[1].trim().replace(",", ".");

        if ((!low || scalar.test(low)) && (!high || scalar.test(high)) && (low || high) && !negated) {
          condition = { column: key, operator: "between", value: { from: low, to: high } };
        }
      } else if (group === "date" && RELATIVE_WORDS[lower] && !negated) {
        condition = { column: key, operator: RELATIVE_WORDS[lower] };
      } else if (group === "date" && /^\+?\d+d$/.test(lower) && !negated) {
        condition = {
          column: key,
          operator: lower.charAt(0) === "+" ? "next_days" : "last_days",
          value: parseInt(lower.replace(/\D/g, ""), 10)
        };
      } else {
        var match = /^(>=|<=|!=|>|<|=)?\s*(.+)$/.exec(raw);
        var symbol = match ? match[1] || "" : "";
        var body = match ? match[2].trim() : "";

        if (group === "number") {
          body = body.replace(",", ".");
        }

        if (match && scalar.test(body)) {
          var operator = COMPARISONS[group][symbol];

          if (negated) {
            operator = operator === "equals" ? "not_equals" : operator === "on" ? "not_on" : null;
          }

          if (operator) {
            condition = { column: key, operator: operator, value: body };
          }
        }
      }
    } else if (group === "multiselect" && column.textSearch && raw.charAt(0) === "~") {
      // "client:~acme": every client whose name contains the words.
      var searched = splitList(raw.slice(1));

      if (searched.length) {
        condition = {
          column: key,
          operator: negated ? "not_contains" : "contains",
          value: searched
        };
      }
    } else if (group === "multiselect") {
      var parts = splitList(raw);
      var values = [];
      var labels = {};
      var unresolved = [];

      parts.forEach(function (part) {
        var wanted = squash(part);
        var choice = (column.choices || []).find(function (entry) {
          return squash(entry.label) === wanted || squash(entry.value) === wanted;
        });

        if (choice) {
          values.push(choice.value);
          labels[String(choice.value)] = choice.label;
        } else {
          unresolved.push(part);
        }
      });

      condition = {
        column: key,
        operator: negated ? "none_of" : "any_of",
        value: values,
        labels: labels
      };

      if (unresolved.length) {
        condition.unresolved = unresolved;
      }
    } else {
      var words = splitList(raw);
      var textOperator = "contains";

      if (raw.charAt(0) === "=") {
        textOperator = "equals";
        words = splitList(raw.slice(1));
      } else if (raw.charAt(0) === "^") {
        textOperator = "starts_with";
        words = splitList(raw.slice(1));
      }

      // "Does not start with" is not offered: -name:^abc means nothing.
      if (words.length && !(negated && textOperator === "starts_with")) {
        condition = {
          column: key,
          operator: negated ? NEGATED[textOperator] : textOperator,
          value: words
        };
      }
    }

    if (condition) {
      condition.id = uid();
    }

    return condition;
  }

  /**
   * Read a search box value: the filter tokens it holds, and the words
   * left for the global search.
   *
   *   { tokens: [{ text, start, end, column, condition, partial }], free }
   */
  function parse(text, columns) {
    var tokens = [];
    var free = [];

    tokenize(String(text || "")).forEach(function (token) {
      var match = /^([-!]?)([^\s:"]+):(.*)$/.exec(token.text);
      var column = match ? findColumn(columns, match[2]) : null;

      if (!column) {
        free.push(token.text);
        return;
      }

      var value = unquote(match[3]);

      tokens.push({
        text: token.text,
        start: token.start,
        end: token.end,
        column: column,
        negated: Boolean(match[1]),
        value: value,
        partial: value === "" || (match[3].charAt(0) === '"' && match[3].slice(-1) !== '"'),
        condition: value ? conditionFromText(column, value, Boolean(match[1])) : null
      });
    });

    return { tokens: tokens, free: free.join(" ") };
  }

  /** How to type a condition: "status:open,pending". */
  function toText(condition, column) {
    var key = keyOf(column);
    var value = condition.value;
    var quote = function (item) {
      var textValue = String(item);

      return /[\s,"]/.test(textValue) ? '"' + textValue.replace(/"/g, "") + '"' : textValue;
    };

    switch (condition.operator) {
      case "empty":
        return key + ":empty";
      case "not_empty":
        return "-" + key + ":empty";
      case "is_true":
        return key + ":yes";
      case "is_false":
        return key + ":no";
      case "any_of":
      case "none_of":
        return (
          (condition.operator === "none_of" ? "-" : "") +
          key +
          ":" +
          (value || [])
            .map(function (item) {
              return quote(choiceLabel(condition, column, item));
            })
            .join(",")
        );
      case "between":
        return key + ":" + ((value && value.from) || "") + ".." + ((value && value.to) || "");
      case "last_days":
        return key + ":" + value + "d";
      case "next_days":
        return key + ":+" + value + "d";
      default:
        break;
    }

    // "-title:=Invoice" is "is not"; without the "=" it would read back
    // as "does not contain".
    var symbols = {
      equals: kind(column) === "text" ? "=" : "",
      not_equals: kind(column) === "text" ? "=" : "",
      gt: ">",
      gte: ">=",
      lt: "<",
      lte: "<=",
      on: "",
      not_on: "",
      before: "<",
      after: ">",
      on_or_before: "<=",
      on_or_after: ">=",
      contains: kind(column) === "multiselect" ? "~" : "",
      not_contains: kind(column) === "multiselect" ? "~" : "",
      starts_with: "^"
    };

    if (Object.prototype.hasOwnProperty.call(symbols, condition.operator)) {
      var negated = /^not_/.test(condition.operator) ? "-" : "";
      var items = Array.isArray(value) ? value : [value];

      return negated + key + ":" + symbols[condition.operator] + items.map(quote).join(",");
    }

    var relative = Object.keys(RELATIVE_WORDS).some(function (word) {
      return RELATIVE_WORDS[word] === condition.operator;
    });

    // Written as it is read out - "this-month" - and read back all the
    // same: the parser ignores dashes.
    return relative ? key + ":" + condition.operator.replace(/_/g, "-") : "";
  }

  namespace.query = {
    MATCH_ALL: MATCH_ALL,
    MATCH_ANY: MATCH_ANY,
    clone: clone,
    columnFor: columnFor,
    conditionFromText: conditionFromText,
    conditionsOn: conditionsOn,
    count: count,
    describe: describe,
    describeText: describeText,
    emptyTree: emptyTree,
    filterable: filterable,
    findColumn: findColumn,
    flatten: flatten,
    forRequest: forRequest,
    forState: forState,
    isComplete: isComplete,
    isGroup: isGroup,
    keyOf: keyOf,
    kind: kind,
    locate: locate,
    newCondition: newCondition,
    normalize: normalize,
    parse: parse,
    prune: prune,
    remove: remove,
    suggestColumns: suggestColumns,
    toText: toText,
    uid: uid
  };
})(window, document);
