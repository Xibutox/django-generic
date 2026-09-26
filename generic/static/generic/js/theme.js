/**
 * Light / dark / system theme toggle.
 *
 * Three states rather than two: a user who has not chosen follows the
 * operating system, and cycling returns them to that rather than
 * stranding them on a manual choice.
 *
 * The stored value is applied inline in base.html before first paint;
 * this file only handles the toggling afterwards.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "generic.theme";
  var ORDER = ["system", "light", "dark"];

  function read() {
    try {
      return window.localStorage.getItem(STORAGE_KEY) || "system";
    } catch (error) {
      /* Private mode, or site data blocked. */
      return "system";
    }
  }

  function write(theme) {
    try {
      if (theme === "system") {
        window.localStorage.removeItem(STORAGE_KEY);
      } else {
        window.localStorage.setItem(STORAGE_KEY, theme);
      }
    } catch (error) {
      /* Not being able to remember is survivable. */
    }
  }

  function apply(theme) {
    var root = document.documentElement;

    if (theme === "system") {
      delete root.dataset.theme;
    } else {
      root.dataset.theme = theme;
    }
  }

  function next(theme) {
    return ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];
  }

  function describe(theme) {
    return "Theme: " + theme;
  }

  function initialise() {
    var buttons = document.querySelectorAll(".js-theme-toggle");

    if (!buttons.length) {
      return;
    }

    var current = read();
    apply(current);

    buttons.forEach(function (button) {
      button.setAttribute("title", describe(current));

      button.addEventListener("click", function () {
        current = next(current);
        apply(current);
        write(current);

        buttons.forEach(function (other) {
          other.setAttribute("title", describe(current));
        });

        document.dispatchEvent(
          new CustomEvent("generic:themechange", {
            detail: { theme: current }
          })
        );
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialise);
  } else {
    initialise();
  }
})();
