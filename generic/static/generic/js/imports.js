/**
 * The import page: a file chosen, its columns matched, a preview, the
 * import.
 *
 * The server does every step. This component holds the file between
 * them and sends it again each time - with the columns the reader
 * matched - so nothing is stored on the server between the preview and
 * the import, and the import is checked again from scratch.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  var ACTIONS = {
    create: { label: "To create", badge: "badge--success" },
    update: { label: "To update", badge: "badge--info" },
    unchanged: { label: "Unchanged", badge: "" },
    error: { label: "Error", badge: "badge--danger" }
  };

  function readConfig(id) {
    var element = document.getElementById(id);

    try {
      return element ? JSON.parse(element.textContent) : {};
    } catch (error) {
      return {};
    }
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("resourceImport", function (configId) {
      var config = readConfig(configId);

      return {
        config: config,
        schema: config.schema || { columns: [] },
        file: null,
        dragging: false,
        headers: [],
        mapping: [],
        missing: [],
        result: null,
        busy: false,
        error: "",

        limits: function () {
          var size = this.schema.maxFileSize
            ? Math.round((this.schema.maxFileSize / 1024 / 1024) * 10) / 10
            : null;

          return Generic.format(
            t("Excel (.xlsx) or CSV, up to %(rows)s rows and %(size)s MB."),
            { rows: this.schema.maxRows, size: size }
          );
        },

        keyText: function () {
          var column = this.column(this.schema.key);

          return Generic.format(
            t("A row whose %(key)s already exists updates that record."),
            { key: column ? column.title : this.schema.key }
          );
        },

        column: function (name) {
          return (this.schema.columns || []).find(function (column) {
            return column.name === name;
          });
        },

        columnTitle: function (name) {
          var column = this.column(name);

          return column ? column.title : name ? name : "\u2014";
        },

        missingText: function () {
          var self = this;

          return Generic.format(
            t("Required for new records, and matched by no column: %(columns)s."),
            {
              columns: this.missing
                .map(function (name) {
                  return self.columnTitle(name);
                })
                .join(", ")
            }
          );
        },

        stepTitle: function () {
          return this.result && this.result.committed ? t("Imported") : t("Preview");
        },

        actionLabel: function (action) {
          return t((ACTIONS[action] || ACTIONS.error).label);
        },

        badgeClass: function (action) {
          return (ACTIONS[action] || ACTIONS.error).badge;
        },

        count: function (action) {
          return this.result ? this.result.counts[action] || 0 : 0;
        },

        sample: function (index) {
          var line = this.result && this.result.preview[0];

          return line ? line.cells[index] || "" : "";
        },

        canImport: function () {
          return (
            !this.busy &&
            this.file &&
            this.result &&
            !this.result.committed &&
            !this.count("error") &&
            this.result.rows > 0
          );
        },

        choose: function (event) {
          var files = event.target.files;

          if (files && files.length) {
            this.take(files[0]);
          }
        },

        drop: function (event) {
          var files = event.dataTransfer && event.dataTransfer.files;

          this.dragging = false;

          if (files && files.length) {
            this.take(files[0]);
          }
        },

        take: function (file) {
          this.file = file;
          this.headers = [];
          this.mapping = [];
          this.result = null;
          this.error = "";
          // A new file: its columns are guessed again by the server.
          this.send(false, true);
        },

        remap: function (index, name) {
          var self = this;

          // A column goes to one field: whichever had it lets go.
          this.mapping = this.mapping.map(function (current, position) {
            if (position === index) {
              return name || null;
            }

            return name && current === name ? null : current;
          });
          window.clearTimeout(this.timer);
          this.timer = window.setTimeout(function () {
            self.preview();
          }, 250);
        },

        preview: function () {
          this.send(false, false);
        },

        commit: function () {
          var self = this;

          Generic.dialogs
            .confirm({
              title: t("Import"),
              message: Generic.format(
                t("Create %(create)s and update %(update)s records?"),
                { create: this.count("create"), update: this.count("update") }
              ),
              confirmLabel: t("Import")
            })
            .then(function (confirmed) {
              if (confirmed) {
                self.send(true, false);
              }
            });
        },

        send: function (commit, guess) {
          var self = this;
          var body = new FormData();

          if (!this.file) {
            return;
          }

          body.append("file", this.file);
          body.append("commit", commit ? "true" : "false");

          if (!guess && this.mapping.length) {
            body.append("mapping", JSON.stringify(this.mapping));
          }

          this.busy = true;
          this.error = "";

          Generic.api
            .post(this.config.urls.run, body)
            .then(function (data) {
              self.result = data;
              self.headers = data.headers;
              self.mapping = data.mapping;
              self.missing = data.missing || [];

              if (data.committed) {
                Generic.toast(
                  Generic.format(t("%(create)s created, %(update)s updated."), {
                    create: data.counts.create,
                    update: data.counts.update
                  }),
                  "success"
                );
              } else if (commit) {
                self.error = t("Nothing was imported: fix the rows with errors first.");
              }
            })
            .catch(function (error) {
              self.error = error.message;
              self.result = null;
            })
            .finally(function () {
              self.busy = false;
            });
        }
      };
    });
  });
})(window, document);
