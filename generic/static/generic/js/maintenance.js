/**
 * The banner of a planned restart, and the page that plans one.
 *
 * Three events reach every open page - the announcement, a minute
 * before, seconds before - and a fourth if it is called off. The banner
 * shows what is coming and counts down to it; the toasts are what
 * someone looking at another window notices.
 *
 * A page opened after the announcement is not left out: the frame
 * carries what is planned in its configuration (Generic.config()).
 *
 * Non-ASCII characters are written as \uXXXX escapes.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  /** The comment in the language this page is being read in. */
  function commentOf(announcement) {
    var comments = (announcement && announcement.comment) || {};
    var language = (document.documentElement.lang || "en").toLowerCase();

    return (
      comments[language] ||
      comments[language.split("-")[0]] ||
      comments.en ||
      ""
    );
  }

  /** "in 4 minutes", "in 35 seconds", "now". */
  function countdown(seconds) {
    if (seconds <= 5) {
      return t("now");
    }

    if (seconds < 90) {
      return Generic.format(t("in %(count)s seconds"), {
        count: Math.round(seconds)
      });
    }

    return Generic.format(t("in %(count)s minutes"), {
      count: Math.round(seconds / 60)
    });
  }

  function timeOf(announcement) {
    var date = new Date(announcement.scheduledAt);

    if (isNaN(date.getTime())) {
      return "";
    }

    return date.toLocaleTimeString(document.documentElement.lang || undefined, {
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  /**
   * The banner itself: one Alpine component in the frame, fed by the
   * socket and by whatever the page was loaded with.
   */
  function restartBanner() {
    return {
      announcement: null,
      phase: "",
      seconds: 0,
      ticker: null,

      init: function () {
        var self = this;
        var planned = (Generic.config().maintenance || null);

        if (planned) {
          this.show(planned, planned.phase || "announced");
        }

        ["announced", "reminder", "imminent", "restarting"].forEach(
          function (phase) {
            Generic.events.on("maintenance." + phase, function (payload) {
              self.show(payload, phase);
              self.announce(phase, payload);
            });
          }
        );

        Generic.events.on("maintenance.cancelled", function () {
          self.hide();
          Generic.toast(t("The restart was called off."), "success");
        });
      },

      show: function (announcement, phase) {
        this.announcement = announcement;
        this.phase = phase || "announced";
        this.seconds = Number(announcement.secondsUntil) || 0;
        this.tick();
      },

      hide: function () {
        this.announcement = null;
        this.phase = "";
        window.clearInterval(this.ticker);
        this.ticker = null;
      },

      /** Count down from the moment the page heard about it. */
      tick: function () {
        var self = this;

        window.clearInterval(this.ticker);
        this.ticker = window.setInterval(function () {
          self.seconds -= 1;

          if (self.seconds < -120) {
            // Long past, and nothing came: stop claiming it is coming.
            self.hide();
          }
        }, 1000);
      },

      announce: function (phase, payload) {
        var message = this.line(phase, payload);

        if (phase === "announced") {
          Generic.toast(message, "warning");
        } else if (phase === "reminder") {
          Generic.toast(message, "warning");
        } else if (phase === "imminent" || phase === "restarting") {
          Generic.toast(message, "error");
        }
      },

      line: function (phase, payload) {
        var when = timeOf(payload || this.announcement || {});

        if (phase === "restarting") {
          return (payload || {}).isManual
            ? t("The server is being restarted now.")
            : t("The server is restarting now.");
        }

        return Generic.format(t("Server restart at %(time)s."), {
          time: when
        });
      },

      // -- what the banner draws ------------------------------------

      get visible() {
        return Boolean(this.announcement);
      },

      get urgent() {
        return this.phase === "imminent" || this.phase === "restarting";
      },

      get title() {
        if (this.phase === "restarting") {
          return t("The server is restarting.");
        }

        return Generic.format(t("Server restart at %(time)s, %(when)s."), {
          time: timeOf(this.announcement || {}),
          when: countdown(this.seconds)
        });
      },

      get detail() {
        var announcement = this.announcement || {};
        var minutes = announcement.durationMinutes || 0;

        return Generic.format(
          t("Expected to last about %(count)s minutes."),
          { count: minutes }
        );
      },

      get comment() {
        return commentOf(this.announcement);
      }
    };
  }

  /**
   * The planning page: the form posts itself, this only calls a
   * planned restart off.
   */
  function restartPlanner(url) {
    return {
      cancel: function () {
        Generic.dialogs
          .confirm({
            title: t("Call off the restart?"),
            message: t("Everyone connected is told it is not happening."),
            confirmLabel: t("Call it off"),
            variant: "danger"
          })
          .then(function (confirmed) {
            if (!confirmed) {
              return;
            }

            Generic.api
              .delete(url)
              .then(function () {
                Generic.flash(t("The restart was called off."), "success");
                window.location.reload();
              })
              .catch(function (error) {
                Generic.toast(error.message, "error");
              });
          });
      }
    };
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("restartBanner", restartBanner);
    window.Alpine.data("restartPlanner", restartPlanner);
  });
})(window, document);
