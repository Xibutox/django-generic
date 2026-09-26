/**
 * Dismissible flash messages.
 *
 * Success and info messages fade out on their own; warnings and errors
 * stay until dismissed, because they usually describe something the
 * user still has to act on.
 */
(function () {
  "use strict";

  var AUTO_DISMISS_LEVELS = ["success", "info"];
  var AUTO_DISMISS_DELAY = 6000;

  function dismiss(message) {
    message.remove();
  }

  function initialise() {
    var messages = document.querySelectorAll(".message");

    messages.forEach(function (message) {
      var button = message.querySelector(".js-dismiss-message");

      if (button) {
        button.addEventListener("click", function () {
          dismiss(message);
        });
      }

      var level = message.dataset.messageLevel;

      if (AUTO_DISMISS_LEVELS.indexOf(level) !== -1) {
        window.setTimeout(function () {
          dismiss(message);
        }, AUTO_DISMISS_DELAY);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialise);
  } else {
    initialise();
  }
})();
