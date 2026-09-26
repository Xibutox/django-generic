/**
 * Collapsible fieldsets.
 *
 * A fieldset marked ``classes: ("collapse",)`` starts closed, unless it
 * contains a field with an error \u2014 hiding the reason a form was
 * rejected is the one thing collapsing must never do.
 */
(function () {
  "use strict";

  function initialise() {
    var fieldsets = document.querySelectorAll(
      '[data-collapsible="true"]'
    );

    fieldsets.forEach(function (fieldset) {
      var legend = fieldset.querySelector(".fieldset__title");

      if (!legend) {
        return;
      }

      // Running twice would copy an already-emptied legend into a
      // second button and lose the label.
      if (fieldset.dataset.collapseReady === "1") {
        return;
      }

      fieldset.dataset.collapseReady = "1";

      var hasErrors = fieldset.querySelector(".field-errors") !== null;

      if (!hasErrors) {
        fieldset.classList.add("is-collapsed");
      }

      var button = document.createElement("button");
      button.type = "button";
      button.className = "fieldset__toggle";
      button.textContent = legend.textContent;
      button.setAttribute(
        "aria-expanded",
        String(!fieldset.classList.contains("is-collapsed"))
      );

      button.addEventListener("click", function () {
        var collapsed = fieldset.classList.toggle("is-collapsed");
        button.setAttribute("aria-expanded", String(!collapsed));
      });

      legend.textContent = "";
      legend.appendChild(button);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialise);
  } else {
    initialise();
  }
})();
