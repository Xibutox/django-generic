/**
 * Column normalisation and cell renderers.
 *
 * The server sends the column declaration; this turns it into the shape
 * DataTables wants, and decides how each cell is drawn.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var FILTER_TYPES = core.FILTER_TYPES;

  /**
   * Work out which filter engine a column uses.
   *
   * Accepts camelCase, snake_case and the DRF serializer field names,
   * because the same declaration travels through several layers.
   */
  function normalizeFilterType(column) {
    var supplied =
      column.filterType ||
      column.filter_type ||
      column.fieldType ||
      column.field_type ||
      column.type ||
      "";

    var normalized = String(supplied)
      .trim()
      .toLowerCase()
      .replace(/[\s_-]+/g, "");

    if (
      normalized &&
      Object.prototype.hasOwnProperty.call(
        core.FILTER_TYPE_ALIASES,
        normalized
      )
    ) {
      return core.FILTER_TYPE_ALIASES[normalized];
    }

    if (supplied) {
      window.console.warn(
        core.format(
          'Unknown filter type "%(type)s" for column "%(column)s".' +
            " Falling back to text.",
          { type: supplied, column: column.data || column.name }
        )
      );
    }

    return FILTER_TYPES.TEXT;
  }

  /**
   * Share the available width out between the columns.
   *
   * Weighted by the header length and clamped, so a column titled "ID"
   * does not get the same room as one titled "Estimated delivery date".
   */
  function calculateColumnWidths(columns) {
    var weights = columns.map(function (column) {
      var length = Array.from(column.title || "").length;
      return Math.max(7, Math.min(length + 4, 22));
    });

    var total = weights.reduce(function (sum, weight) {
      return sum + weight;
    }, 0) || 1;

    return weights.map(function (weight) {
      return ((weight / total) * 100).toFixed(3) + "%";
    });
  }

  function choiceLabels(column) {
    var labels = {};

    (column.choices || []).forEach(function (choice) {
      labels[String(choice.value)] = choice.label;
    });

    return labels;
  }

  /**
   * Render a cell as a link.
   *
   * `linkUrl` may hold `{field}` tokens, filled from the row the API
   * returned. `linkField` names a row field holding the whole URL.
   */
  function buildLinkRenderer(column) {
    var labels = choiceLabels(column);

    return function (data, renderingType, row) {
      // Ordering, filtering and exports want the raw value.
      if (renderingType !== "display") {
        return data;
      }

      if (data === null || data === undefined || data === "") {
        return "";
      }

      // A choice column linking to its row still shows the label, and
      // a date one the date as the page's language writes it.
      var text = Object.prototype.hasOwnProperty.call(labels, String(data))
        ? labels[String(data)]
        : column.filterType === FILTER_TYPES.DATE ||
            column.filterType === FILTER_TYPES.DATETIME
          ? core.formatStamp(data)
          : data;

      var url = null;

      if (column.linkField) {
        url = row[column.linkField];

        if (url && !core.isSafeUrl(url)) {
          url = null;
        }
      } else if (column.linkUrl) {
        // A row value reaching an href is a script injection waiting
        // to happen; escaping alone would not stop `javascript:`.
        url = core.fillTemplate(column.linkUrl, row);
      }

      if (!url) {
        return core.escapeHtml(text);
      }

      var target = column.linkTarget || "_self";
      var rel = target === "_blank" ? ' rel="noopener noreferrer"' : "";

      return (
        '<a href="' +
        core.escapeHtml(url) +
        '" target="' +
        core.escapeHtml(target) +
        '"' +
        rel +
        ">" +
        core.escapeHtml(text) +
        "</a>"
      );
    };
  }

  /**
   * Render a choice value as its label.
   *
   * Without this the cell shows the stored value while the filter
   * beside it offers the label - "essay" against "Essay".
   */
  function buildChoiceRenderer(column) {
    var labels = choiceLabels(column);

    return function (data, renderingType) {
      if (renderingType !== "display") {
        return data;
      }

      if (data === null || data === undefined || data === "") {
        return "";
      }

      var key = String(data);

      return core.escapeHtml(
        Object.prototype.hasOwnProperty.call(labels, key)
          ? labels[key]
          : data
      );
    };
  }

  /** The tags of a cell: a list, one tag, or a plain value. */
  function tagItems(data) {
    if (data === null || data === undefined || data === "") {
      return [];
    }

    return (Array.isArray(data) ? data : [data])
      .map(function (item) {
        return item !== null && typeof item === "object"
          ? item
          : { label: String(item) };
      })
      .filter(function (item) {
        return item.label !== undefined && item.label !== null && item.label !== "";
      });
  }

  function tagLabels(data) {
    return tagItems(data)
      .map(function (item) {
        return String(item.label);
      })
      .join(", ");
  }

  /**
   * One tag as HTML.
   *
   * One colour tints the tag, which then follows the theme; a
   * background draws it exactly, with a readable text colour when none
   * is given. Every colour is checked before it reaches the style
   * attribute, and the label is escaped.
   */
  function renderTag(tag, column) {
    var Generic = window.Generic;
    var colors = Generic && Generic.colors;
    var clean = colors
      ? colors.clean
      : function () {
          return "";
        };
    var background = clean(tag.background);
    var color = clean(tag.color);
    var className = "tag";
    var style = "";

    if (background) {
      className += " tag--solid";
      style =
        "--tag-background: " +
        background +
        "; --tag-text: " +
        (color || colors.readableOn(background)) +
        ";";
    } else if (color) {
      style = "--tag-color: " + color + ";";
    }

    var attributes =
      ' class="' +
      className +
      '"' +
      (style ? ' style="' + core.escapeHtml(style) + '"' : "") +
      (tag.title ? ' title="' + core.escapeHtml(tag.title) + '"' : "");

    var url =
      column.tagUrl && tag.id !== undefined && tag.id !== null
        ? core.fillTemplate(column.tagUrl, tag)
        : "";

    if (url) {
      return (
        '<a href="' +
        core.escapeHtml(url) +
        '"' +
        attributes +
        ">" +
        core.escapeHtml(tag.label) +
        "</a>"
      );
    }

    return "<span" + attributes + ">" + core.escapeHtml(tag.label) + "</span>";
  }

  /** Render one or several values as coloured tags. */
  function buildTagsRenderer(column) {
    return function (data, renderingType) {
      // Sorting, filtering and exports want the words.
      if (renderingType !== "display") {
        return tagLabels(data);
      }

      var tags = tagItems(data);

      if (!tags.length) {
        return "";
      }

      return (
        '<span class="tag-list">' +
        tags
          .map(function (tag) {
            return renderTag(tag, column);
          })
          .join("") +
        "</span>"
      );
    };
  }

  /**
   * A stored file, `{name, url, size}`: its name, linking to the
   * record's download endpoint. Sorting and filtering read the name.
   */
  function buildFileRenderer() {
    return function (data, renderingType) {
      var isObject = data !== null && typeof data === "object";
      var name = isObject ? data.name : data;

      if (renderingType !== "display") {
        return name || "";
      }

      if (!name) {
        return "";
      }

      var url = isObject ? data.url : "";

      if (!url || !core.isSafeUrl(url)) {
        return core.escapeHtml(name);
      }

      return (
        '<a class="dt-file" href="' +
        core.escapeHtml(url) +
        '">' +
        core.escapeHtml(name) +
        "</a>"
      );
    };
  }

  /** The icons of a cell whose address may be followed. */
  function iconItems(data) {
    return (Array.isArray(data) ? data : [])
      .filter(function (item) {
        return (
          item !== null &&
          typeof item === "object" &&
          item.url &&
          core.isSafeUrl(item.url)
        );
      });
  }

  function iconLabels(data) {
    return iconItems(data)
      .map(function (item) {
        return String(item.label || "");
      })
      .filter(Boolean)
      .join(", ");
  }

  /**
   * Shortcuts of the row, `[{icon, url, label, target}]`: each an icon
   * one clicks, named by its label for a pointer and a screen reader.
   */
  function buildIconsRenderer() {
    return function (data, renderingType) {
      if (renderingType !== "display") {
        return iconLabels(data);
      }

      var icons = iconItems(data);

      if (!icons.length) {
        return "";
      }

      return (
        '<span class="dt-icons">' +
        icons
          .map(function (item) {
            var label = core.escapeHtml(item.label || "");
            var blank = item.target === "_blank";

            return (
              '<a class="icon-button icon-button--sm dt-icons__link" href="' +
              core.escapeHtml(item.url) +
              '"' +
              (blank ? ' target="_blank" rel="noopener"' : "") +
              (label ? ' title="' + label + '" aria-label="' + label + '"' : "") +
              '><span class="icon material-symbols-outlined" aria-hidden="true">' +
              core.escapeHtml(item.icon || "link") +
              "</span></a>"
            );
          })
          .join("") +
        "</span>"
      );
    };
  }

  /** Render a boolean as a word rather than `true` / `false`. */
  function buildBooleanRenderer() {
    return function (data, renderingType) {
      if (renderingType !== "display") {
        return data;
      }

      if (data === null || data === undefined || data === "") {
        return "";
      }

      var truthy = data === true || data === "true" || data === 1;

      return (
        '<span class="dt-boolean dt-boolean--' +
        (truthy ? "yes" : "no") +
        '"><span class="icon material-symbols-outlined" aria-hidden="true">' +
        (truthy ? "check_circle" : "cancel") +
        "</span>" +
        core.escapeHtml(truthy ? core.t("Yes") : core.t("No")) +
        "</span>"
      );
    };
  }

  /**
   * A date, or a date and time, in the page's language. Only the text
   * shown changes: sorting, filtering and an edited cell's control all
   * keep reading the ISO value the row carries.
   */
  function buildDateRenderer() {
    return function (data, renderingType) {
      if (renderingType !== "display") {
        return data;
      }

      return core.escapeHtml(core.formatStamp(data));
    };
  }

  /**
   * Turn the server's column declaration into DataTables' own shape.
   */
  function normalizeColumns(columns) {
    var normalized = columns.map(function (column) {
      var filterType = normalizeFilterType(column);

      var displayType = String(
        column.displayType || column.display_type || column.type || ""
      )
        .trim()
        .toLowerCase();

      var result = {
        data: column.data,
        name: column.name || column.data,
        title: column.title || column.label || column.data,
        searchable: column.searchable !== false,
        orderable: column.orderable !== false,
        visible: column.visible !== false,
        exportable: column.exportable !== false,
        defaultContent: column.defaultContent != null
          ? column.defaultContent
          : "",
        className: column.className || "",
        filterType: filterType,
        displayType: displayType,
        filterKey:
          column.filterKey ||
          column.filter_key ||
          column.data ||
          column.name,
        autocompleteUrl:
          column.autocompleteUrl || column.autocomplete_url || null,
        minimumInputLength:
          column.minimumInputLength != null
            ? column.minimumInputLength
            : column.minimum_input_length != null
              ? column.minimum_input_length
              : 0,
        placeholder: column.placeholder || core.t("Select"),
        choices: column.choices || null,
        step: column.step,
        width: column.width,
        linkUrl: column.linkUrl || column.link_url || null,
        linkField: column.linkField || column.link_field || null,
        linkTarget: column.linkTarget || column.link_target || "_self",
        tagUrl: column.tagUrl || column.tag_url || null,
        // The filter editor may ask the endpoint for this column's
        // values, and offer "has all of" on a many-valued one.
        facets: Boolean(column.facets),
        filterMany: Boolean(column.filterMany || column.filter_many),
        render: column.render
      };

      if (!result.render) {
        if (displayType === "tags") {
          result.render = buildTagsRenderer(result);
        } else if (displayType === "file") {
          result.render = buildFileRenderer();
        } else if (displayType === "icons") {
          result.render = buildIconsRenderer();
        } else if (displayType === "link") {
          result.render = buildLinkRenderer(result);
        } else if (
          filterType === FILTER_TYPES.BOOLEAN ||
          displayType === FILTER_TYPES.BOOLEAN
        ) {
          result.render = buildBooleanRenderer();
        } else if (result.choices && result.choices.length) {
          result.render = buildChoiceRenderer(result);
        } else if (
          displayType === FILTER_TYPES.DATE ||
          displayType === FILTER_TYPES.DATETIME
        ) {
          result.render = buildDateRenderer();
        }
      }

      return result;
    });

    var widths = calculateColumnWidths(normalized);

    return normalized.map(function (column, index) {
      return Object.assign({}, column, {
        width: column.width || widths[index]
      });
    });
  }

  /**
   * Strip the keys that are ours, leaving what DataTables understands.
   *
   * `type` in particular means something entirely different to
   * DataTables, so passing ours through would change how it sorts.
   */
  function toDataTablesColumn(column) {
    var result = Object.assign({}, column);

    [
      "displayType",
      "filterType",
      "filterKey",
      "autocompleteUrl",
      "minimumInputLength",
      "placeholder",
      "linkField",
      "linkUrl",
      "linkTarget",
      "tagUrl",
      "facets",
      "facetsFailed",
      "filterMany",
      "choices",
      "type",
      "step",
      "exportable",
      "synthetic",
      "headerNode"
    ].forEach(function (key) {
      delete result[key];
    });

    // A column added by a feature - the selection checkboxes, the row
    // menu - keeps the header node it put in the page; a title would
    // overwrite it.
    if (column.synthetic) {
      delete result.title;
    }

    return result;
  }

  namespace.columns = {
    buildBooleanRenderer: buildBooleanRenderer,
    buildDateRenderer: buildDateRenderer,
    buildChoiceRenderer: buildChoiceRenderer,
    buildFileRenderer: buildFileRenderer,
    buildIconsRenderer: buildIconsRenderer,
    iconLabels: iconLabels,
    buildLinkRenderer: buildLinkRenderer,
    buildTagsRenderer: buildTagsRenderer,
    tagHtml: renderTag,
    tagLabels: tagLabels,
    calculateColumnWidths: calculateColumnWidths,
    choiceLabels: choiceLabels,
    normalizeColumns: normalizeColumns,
    normalizeFilterType: normalizeFilterType,
    toDataTablesColumn: toDataTablesColumn
  };
})(window, document);
