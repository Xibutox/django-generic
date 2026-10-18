/**
 * A sheet of labels (generic.sites.labels): its Print button.
 */
(function (window, document) {
  "use strict";

  window.Generic.ready(function () {
    Array.prototype.forEach.call(document.querySelectorAll(".js-print-labels"), function (button) {
      button.addEventListener("click", function () {
        window.print();
      });
    });
  });
})(window, document);
