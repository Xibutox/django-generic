/**
 * The account page's API tokens: listed, created, copied once, revoked.
 *
 * A new token comes back from the server once, in the answer to its
 * creation; it is shown until the page is left, and never again.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  function readConfig(id) {
    var element = document.getElementById(id);

    try {
      return element ? JSON.parse(element.textContent) : {};
    } catch (error) {
      return {};
    }
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("apiTokens", function (configId) {
      var config = readConfig(configId);

      return {
        config: config,
        rows: [],
        loading: true,
        busy: false,
        error: "",
        created: null,
        name: "",
        scope: "read",
        days: String(config.defaultDays || ""),

        init: function () {
          this.load();
        },

        load: function () {
          var self = this;

          Generic.api
            .get(this.config.url)
            .then(function (rows) {
              self.rows = Array.isArray(rows) ? rows : [];
            })
            .catch(function (error) {
              self.error = error.message;
            })
            .finally(function () {
              self.loading = false;
            });
        },

        durations: function () {
          var max = this.config.maxDays;
          var options = [30, 90, 365]
            .filter(function (days) {
              return !max || days <= max;
            })
            .map(function (days) {
              return { value: String(days), label: Generic.format(t("%(days)s days"), { days: days }) };
            });

          if (!max) {
            options.push({ value: "", label: t("Never expires") });
          }

          return options;
        },

        scopeLabel: function (scope) {
          return scope === "read_write" ? t("Read and write") : t("Read only");
        },

        describe: function (row) {
          return [
            this.scopeLabel(row.scope),
            Generic.format(t("expires: %(when)s"), { when: this.when(row.expiry, "never") }),
            Generic.format(t("last used: %(when)s"), { when: this.when(row.last_used_at, "unused") })
          ].join(" \u00b7 ");
        },

        when: function (value, empty) {
          if (!value) {
            return empty === "never" ? t("never") : t("not yet");
          }

          return new Date(value).toLocaleString(document.documentElement.lang || undefined);
        },

        create: function () {
          var self = this;

          this.busy = true;
          this.error = "";

          Generic.api
            .post(this.config.url, {
              name: this.name,
              scope: this.scope,
              days: this.days ? Number(this.days) : null
            })
            .then(function (data) {
              self.created = data;
              self.name = "";
              self.load();
            })
            .catch(function (error) {
              self.error = error.message;
            })
            .finally(function () {
              self.busy = false;
            });
        },

        copy: function () {
          var text = this.created && this.created.token;

          if (!text || !window.navigator.clipboard) {
            return;
          }

          window.navigator.clipboard.writeText(text).then(function () {
            Generic.toast(t("Copied."), "success");
          });
        },

        revoke: function (row) {
          var self = this;

          Generic.dialogs
            .confirm({
              title: t("Revoke this token?"),
              message: Generic.format(
                t("%(name)s stops working at once, for whatever uses it."),
                { name: row.name }
              ),
              confirmLabel: t("Revoke"),
              variant: "danger"
            })
            .then(function (confirmed) {
              if (!confirmed) {
                return;
              }

              Generic.api
                .delete(self.config.url + row.id + "/")
                .then(function () {
                  self.load();
                })
                .catch(function (error) {
                  Generic.toast(error.message, "error");
                });
            });
        }
      };
    });
  });
})(window, document);
