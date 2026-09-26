/**
 * Select2, configured once for the whole framework.
 *
 * Relation fields in forms, relation filters in tables and classic
 * Django widgets all go through here, so they share one look, one
 * translation and one way of talking to the autocomplete endpoints:
 *
 *   GET <url>?q=term&page=2   ->  {"results": [{"id", "text"}],
 *                                  "pagination": {"more": true}}
 *   GET <url>?ids=3,7         ->  the labels of values already held
 *
 * Select2 only fires jQuery events. A `generic:change` event is
 * dispatched on the select as well, so code without jQuery hears about
 * a change too.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  function available() {
    var jQuery = window.jQuery;

    return Boolean(
      jQuery && jQuery.fn && typeof jQuery.fn.select2 === "function"
    );
  }

  function language() {
    return {
      errorLoading: function () {
        return t("The results could not be loaded.");
      },
      inputTooLong: function (args) {
        return Generic.format(t("Please delete %(count)s character(s)."), {
          count: args.input.length - args.maximum
        });
      },
      inputTooShort: function (args) {
        return Generic.format(t("Please enter %(count)s more character(s)."), {
          count: args.minimum - args.input.length
        });
      },
      loadingMore: function () {
        return t("Loading more results\u2026");
      },
      maximumSelected: function (args) {
        return Generic.format(t("You can only select %(count)s item(s)."), {
          count: args.maximum
        });
      },
      noResults: function () {
        return t("No results.");
      },
      removeAllItems: function () {
        return t("Remove all items");
      },
      removeItem: function () {
        return t("Remove item");
      },
      search: function () {
        return t("Search");
      },
      searching: function () {
        return t("Searching\u2026");
      }
    };
  }

  function findOption(select, value) {
    var key = String(value);

    return Array.prototype.find.call(select.options, function (option) {
      return option.value === key;
    });
  }

  /** An option for `value`, created if the list does not hold it. */
  function ensureOption(select, value, label) {
    var option = findOption(select, value);

    if (!option) {
      option = new Option(label || String(value), String(value), false, false);
      select.appendChild(option);
    } else if (label && option.textContent !== label) {
      // Select2 keeps what it first read from an option, so a relabelled
      // option would still show its old text - a pre-filled key, often.
      // A fresh option is read anew.
      var fresh = new Option(label, option.value, option.defaultSelected, option.selected);

      option.replaceWith(fresh);
      option = fresh;
    }

    return option;
  }

  function refresh(select) {
    if (available() && window.jQuery(select).data("select2")) {
      window.jQuery(select).trigger("change.select2");
    }
  }

  function notify(select) {
    select.dispatchEvent(new CustomEvent("generic:change", { bubbles: true }));
  }

  function normalize(values) {
    if (values === null || values === undefined || values === "") {
      return [];
    }

    return (Array.isArray(values) ? values : [values]).map(String);
  }

  /** Select exactly `values`, labelling new options from `labels`. */
  function setValues(select, values, labels) {
    var keys = normalize(values);

    labels = labels || {};

    keys.forEach(function (key) {
      ensureOption(select, key, labels[key]);
    });

    Array.prototype.forEach.call(select.options, function (option) {
      option.selected = keys.indexOf(option.value) !== -1;
    });

    if (!select.multiple && !keys.length) {
      select.value = "";
    }

    refresh(select);
  }

  /** Ask an autocomplete endpoint for the labels of `values`. */
  function resolveLabels(url, values) {
    var ids = normalize(values);

    if (!url || !ids.length) {
      return Promise.resolve({});
    }

    return Generic.api
      .get(url, { ids: ids.join(",") })
      .then(function (data) {
        var labels = {};

        ((data && data.results) || []).forEach(function (row) {
          labels[String(row.id)] = row.text;
        });

        return labels;
      })
      .catch(function () {
        return {};
      });
  }

  /**
   * Turn a <select> into a Select2 control.
   *
   * `url` switches to remote results; without it the options already in
   * the select are searched.
   */
  function init(select, options) {
    options = options || {};

    if (!available()) {
      return null;
    }

    var jQuery = window.jQuery;
    var $select = jQuery(select);
    var multiple = select.multiple;

    var config = {
      width: options.width || "100%",
      placeholder:
        options.placeholder || (multiple ? t("Choose\u2026") : t("Select\u2026")),
      allowClear:
        options.allowClear !== undefined ? Boolean(options.allowClear) : !multiple,
      closeOnSelect: !multiple,
      language: language(),
      disabled: Boolean(options.disabled || select.disabled)
    };

    if (options.dropdownParent) {
      config.dropdownParent = jQuery(options.dropdownParent);
    }

    if (options.url) {
      config.minimumInputLength = options.minimumInputLength || 0;
      config.ajax = {
        url: options.url,
        dataType: "json",
        delay: 250,
        cache: true,
        data: function (params) {
          return { q: params.term || "", page: params.page || 1 };
        },
        processResults: function (response) {
          return {
            results: ((response && response.results) || []).map(function (row) {
              return { id: String(row.id), text: row.text };
            }),
            pagination: {
              more: Boolean(
                response && response.pagination && response.pagination.more
              )
            }
          };
        }
      };
    }

    $select.select2(config);
    $select.on("select2:select select2:unselect select2:clear", function () {
      notify(select);
    });

    return $select;
  }

  function destroy(select) {
    if (!available()) {
      return;
    }

    var $select = window.jQuery(select);

    if ($select.data("select2")) {
      $select.off("select2:select select2:unselect select2:clear");
      $select.select2("destroy");
    }
  }

  /**
   * Enhance the selects a server-rendered form marked for it:
   *
   *   <select data-generic-select2='{"url": "/api/.../autocomplete/"}'>
   *
   * Skips the empty template row of a Django formset, which is cloned
   * later and enhanced then.
   */
  function initMarked(root) {
    (root || document)
      .querySelectorAll("select[data-generic-select2]")
      .forEach(function (select) {
        if (
          select.dataset.genericSelect2Ready === "true" ||
          /__prefix__/.test(select.name)
        ) {
          return;
        }

        var options = {};

        try {
          options = JSON.parse(select.dataset.genericSelect2 || "{}");
        } catch (error) {
          options = {};
        }

        select.dataset.genericSelect2Ready = "true";
        init(select, options);
      });
  }

  /**
   * Adapters for a multiple select that shows no chips: the search box
   * moves from the selection into the dropdown.
   *
   * The table filters use them, since a header cell has no room for a
   * list of chosen values. `search` false leaves the box out, for a
   * short fixed list. Null when Select2's modules cannot be reached.
   */
  function compactMultipleAdapters(search) {
    var amd = available() && window.jQuery.fn.select2.amd;

    if (!amd) {
      return null;
    }

    try {
      var Utils = amd.require("select2/utils");
      var dropdown = amd.require("select2/dropdown");

      if (search) {
        dropdown = Utils.Decorate(
          dropdown,
          amd.require("select2/dropdown/search")
        );
      }

      return {
        selectionAdapter: Utils.Decorate(
          amd.require("select2/selection/multiple"),
          amd.require("select2/selection/placeholder")
        ),
        dropdownAdapter: Utils.Decorate(
          dropdown,
          amd.require("select2/dropdown/attachBody")
        )
      };
    } catch (error) {
      return null;
    }
  }

  Generic.select2 = {
    available: available,
    compactMultipleAdapters: compactMultipleAdapters,
    destroy: destroy,
    ensureOption: ensureOption,
    init: init,
    initMarked: initMarked,
    language: language,
    refresh: refresh,
    resolveLabels: resolveLabels,
    setValues: setValues
  };

  Generic.ready(function () {
    initMarked(document);
  });

  document.addEventListener("formset:added", function (event) {
    initMarked(event.target);
  });
})(window, document);
