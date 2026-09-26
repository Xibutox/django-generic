/**
 * The History tab of a record's page.
 *
 * One entry per version, newest first: what changed against the
 * version before it, who changed it and when, and - on demand - the
 * whole record as that version held it. The server has already written
 * every value out, so nothing here has to know what a field meant.
 *
 * Fetched the first time the tab is shown and never again on its own:
 * a page open in the corner of a screen should not poll a table of
 * everything that has ever happened.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  /** What each kind of change looks like in the margin. */
  var ICONS = {
    created: "add_circle",
    updated: "edit",
    deleted: "delete"
  };

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("recordHistory", function (url) {
      return {
        url: url || "",
        entries: [],
        expanded: {},
        count: 0,
        offset: 0,
        hasMore: false,
        loading: false,
        loaded: false,
        error: "",
        // A value that was not set. An em dash, so a blank cell is
        // told apart from a cell nobody has looked at.
        emptyLabel: String.fromCharCode(8212),

        /** First page, once. Called again by every tab switch. */
        load: function () {
          if (this.loaded || !this.url) {
            return;
          }

          this.loaded = true;
          this.fetch(0);
        },

        more: function () {
          if (!this.loading && this.hasMore) {
            this.fetch(this.offset);
          }
        },

        fetch: function (offset) {
          var self = this;

          this.loading = true;
          this.error = "";

          Generic.api
            .get(this.url, offset ? { offset: offset } : {})
            .then(function (data) {
              var results = (data && data.results) || [];

              self.entries = offset ? self.entries.concat(results) : results;
              self.count = (data && data.count) || 0;
              self.offset = self.entries.length;
              self.hasMore = Boolean(data && data.hasMore);
            })
            .catch(function (error) {
              self.error = error.message || t("The history could not be read.");
            })
            .finally(function () {
              self.loading = false;
            });
        },

        icon: function (entry) {
          return ICONS[entry.action] || "edit";
        },

        versionLabel: function (entry) {
          return Generic.format(t("version %(number)s"), {
            number: entry.version
          });
        },

        toggle: function (entry) {
          this.expanded[entry.id] = !this.expanded[entry.id];
        }
      };
    });
  });
})(window, document);
