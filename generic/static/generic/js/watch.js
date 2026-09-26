/**
 * The watches page: what this user is told about, and how.
 *
 * Every tick is written straight back through the endpoint. There is
 * no Save because there is nothing to lose: one checkbox is one PATCH
 * of one row, and the row says so while it is in flight.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("watchList", function (url) {
      return {
        url: url,
        rows: [],
        loading: true,
        error: "",

        init: function () {
          this.load();
        },

        load: function () {
          var self = this;

          if (!this.url) {
            this.loading = false;

            return;
          }

          Generic.api
            .get(this.url)
            .then(function (data) {
              self.rows = (data || []).map(function (row) {
                row.busy = false;

                return row;
              });
            })
            .catch(function (error) {
              self.error = error.message;
            })
            .finally(function () {
              self.loading = false;
            });
        },

        /** The row's own address, which the list endpoint does not give. */
        rowUrl: function (row) {
          return this.url + row.id + "/";
        },

        toggleEvent: function (row, name) {
          this.save(row, { events: without(row.events, name) });
        },

        toggleChannel: function (row, name) {
          this.save(row, { channels: without(row.channels, name) });
        },

        save: function (row, changes) {
          var self = this;

          if (row.busy) {
            return;
          }

          row.busy = true;

          Generic.api
            .patch(this.rowUrl(row), changes)
            .then(function (data) {
              // The server decides what is a valid combination; the
              // row shows what it kept, not what was asked for.
              row.events = data.events;
              row.channels = data.channels;
            })
            .catch(function (error) {
              Generic.toast(error.message, "error");
            })
            .finally(function () {
              row.busy = false;
            });
        },

        remove: function (row) {
          var self = this;

          if (row.busy) {
            return;
          }

          row.busy = true;

          Generic.api
            .delete(this.rowUrl(row))
            .then(function () {
              self.rows = self.rows.filter(function (other) {
                return other.id !== row.id;
              });
              Generic.toast(t("You will not be told any more."), "success");
            })
            .catch(function (error) {
              row.busy = false;
              Generic.toast(error.message, "error");
            });
        }
      };
    });
  });

  /** The list with `name` removed, or added if it was not there. */
  function without(values, name) {
    var list = (values || []).slice();
    var index = list.indexOf(name);

    if (index === -1) {
      list.push(name);
    } else {
      list.splice(index, 1);
    }

    return list;
  }
})(window, document);
