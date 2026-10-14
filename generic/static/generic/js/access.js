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

  /* -- Disclaimers -----------------------------------------------------
   *
   * EXPORT_DISCLAIMER and DOWNLOAD_DISCLAIMER: a reminder, a box to
   * tick, then the export or the download. A reminder rather than a
   * lock - whoever may export still may - so it lives here alone.
   */

  function disclaimerOf(kind) {
    var access = settings();

    return (access && access.disclaimers && access.disclaimers[kind]) || null;
  }

  /**
   * Show `kind`'s reminder, if the project has one. Resolves to true
   * once the box is ticked and the reader goes on - at once when there
   * is no reminder - and to false when they cancel.
   */
  function confirmFor(kind) {
    var disclaimer = disclaimerOf(kind);

    if (!disclaimer) {
      return Promise.resolve(true);
    }

    var dialog = Generic.dialogs.open({ title: disclaimer.title, icon: "privacy_tip" });
    var body = document.createElement("div");

    body.className = "stack disclaimer";
    String(disclaimer.text)
      .split(/\n\s*\n/)
      .forEach(function (paragraph) {
        var node = document.createElement("p");

        node.className = "disclaimer__text";
        node.textContent = paragraph.trim();
        body.appendChild(node);
      });

    var toggle = document.createElement("label");
    var box = document.createElement("input");
    var label = document.createElement("span");

    toggle.className = "disclaimer__accept";
    box.type = "checkbox";
    label.className = "disclaimer__label";
    label.textContent = disclaimer.checkbox;
    toggle.append(box, label);
    body.appendChild(toggle);
    dialog.body.appendChild(body);

    var cancel = document.createElement("button");
    var accept = document.createElement("button");

    cancel.type = accept.type = "button";
    cancel.className = "button button--ghost";
    cancel.textContent = t("Cancel");
    accept.className = "button button--primary";
    accept.textContent = kind === "download" ? t("Download") : t("Export");
    accept.disabled = true;

    box.addEventListener("change", function () {
      accept.disabled = !box.checked;
    });
    cancel.addEventListener("click", function () {
      dialog.close(false);
    });
    accept.addEventListener("click", function () {
      if (box.checked) {
        dialog.close(true);
      }
    });
    dialog.footer.append(cancel, accept);
    box.focus();

    return dialog.closed.then(function (result) {
      return result === true;
    });
  }

  /** Whether `href` is a file the framework serves: a record's
   * (`.../<pk>/files/<field>/`) or a wiki's (`/wiki/files/<id>/`). */
  var FILE_PATH = /\/files\/[^\/?#]+\/?$/;

  function isFileLink(anchor) {
    if (!anchor || !anchor.href || anchor.origin !== window.location.origin) {
      return false;
    }

    return FILE_PATH.test(anchor.pathname);
  }

  // Every file link of every page, whoever drew it: the summary, the
  // tables' cells, a project's own icons, the wiki. Captured before
  // the browser follows it, and followed again once ticked.
  document.addEventListener(
    "click",
    function (event) {
      if (!disclaimerOf("download") || event.defaultPrevented || event.button !== 0) {
        return;
      }

      var anchor = event.target.closest ? event.target.closest("a[href]") : null;

      if (!isFileLink(anchor)) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      confirmFor("download").then(function (accepted) {
        if (!accepted) {
          return;
        }

        if (anchor.target === "_blank" || event.ctrlKey || event.metaKey) {
          window.open(anchor.href, "_blank", "noopener");
        } else {
          window.location.href = anchor.href;
        }
      });
    },
    true
  );

  Generic.access = {
    missing: missing,
    ask: ask,
    confirm: confirmFor,
    disclaimer: disclaimerOf
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
