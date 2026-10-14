/**
 * Rights given on request: exporting tables, downloading files.
 *
 * Where the project makes people ask (GENERIC["ACCESS_ON_REQUEST"]),
 * every page knows which of them this reader lacks
 * (Generic.config().access.missing); the export menu and the file links
 * offer to ask in their place:
 *
 *   if (Generic.access.missing("export")) {
 *     Generic.access.ask("export");
 *   }
 *
 * The server checks every export and every download anyway: this only
 * says what to offer.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  var TITLES = {
    "export": function () {
      return t("Ask for permission to export");
    },
    download: function () {
      return t("Ask for permission to download files");
    }
  };

  function settings() {
    return Generic.config().access || null;
  }

  /** Whether this reader has to ask before doing `kind`. */
  function missing(kind) {
    var access = settings();

    return Boolean(
      access && access.url && (access.missing || []).indexOf(kind) !== -1
    );
  }

  /**
   * Ask for `kind`: a short message for whoever decides, then the
   * request. Resolves to the server's answer, or null when cancelled.
   */
  function ask(kind) {
    var access = settings();

    if (!access || !access.url) {
      return Promise.resolve(null);
    }

    return Generic.dialogs
      .fields({
        title: (TITLES[kind] || TITLES["export"])(),
        icon: "key",
        message: t(
          "An administrator will be told and will grant or refuse it. You will be notified of the answer."
        ),
        confirmLabel: t("Send the request"),
        fields: [
          {
            name: "message",
            label: t("Why do you need it? (optional)"),
            multiline: true,
            maxLength: 2000
          }
        ]
      })
      .then(function (values) {
        if (!values) {
          return null;
        }

        return Generic.api
          .post(access.url, {
            kind: kind,
            message: values.message || "",
            page: window.location.pathname + window.location.search
          })
          .then(function (answer) {
            Generic.toast(answer.detail, "success");

            return answer;
          })
          .catch(function (error) {
            // Too soon (429) is not a failure: the request waits.
            Generic.toast(error.message, error.status === 429 ? "info" : "error");

            return null;
          });
      });
  }

  Generic.access = {
    missing: missing,
    ask: ask
  };

  /**
   * The account page's section: each right given on request, held or
   * not, the request waiting, and a button to ask (or remind).
   */
  document.addEventListener("alpine:init", function () {
    window.Alpine.data("accessRights", function () {
      return {
        rights: [],
        loading: true,
        error: "",

        init: function () {
          this.load();
        },

        load: function () {
          var self = this;
          var access = settings();

          if (!access || !access.url) {
            self.loading = false;
            return;
          }

          Generic.api
            .get(access.url)
            .then(function (data) {
              self.rights = data.rights || [];
            })
            .catch(function (error) {
              self.error = error.message;
            })
            .then(function () {
              self.loading = false;
            });
        },

        describe: function (right) {
          if (right.held) {
            return t("You have this permission.");
          }

          if (right.status === "pending") {
            return Generic.format(t("Asked %(when)s, waiting for an answer."), {
              when: Generic.relativeTime(right.askedAt)
            });
          }

          if (right.status === "refused") {
            return Generic.format(t("Refused (asked %(when)s)."), {
              when: Generic.relativeTime(right.askedAt)
            });
          }

          return t("You do not have this permission.");
        },

        ask: function (right) {
          var self = this;

          ask(right.kind).then(function (answer) {
            if (answer && answer.rights) {
              self.rights = answer.rights;
            }
          });
        }
      };
    });
  });
})(window, document);
