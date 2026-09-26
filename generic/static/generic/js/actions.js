/**
 * Bulk selection on a listing.
 *
 * The subtlety is "select all": the header checkbox only ever selects
 * the rows on screen. Acting on everything the current filters match is
 * a second, explicit step, because the two mean very different things
 * on page 1 of 400.
 */
(function () {
  "use strict";

  function initialise() {
    var form = document.querySelector(".changelist-form");

    if (!form) {
      return;
    }

    var selectAll = form.querySelector(".js-select-all");
    var rows = Array.prototype.slice.call(
      form.querySelectorAll(".js-select-row")
    );
    var acrossInput = form.querySelector(".js-select-across");
    var acrossToggle = form.querySelector(".js-select-across-toggle");
    var counter = form.querySelector(".js-selection-counter");
    var count = form.querySelector(".js-selection-count");
    var bar = form.querySelector(".actions-bar");
    var total = bar ? parseInt(bar.dataset.totalCount, 10) || 0 : 0;

    if (!rows.length) {
      return;
    }

    function selectedCount() {
      return rows.filter(function (row) {
        return row.checked;
      }).length;
    }

    function clearAcross() {
      if (acrossInput) {
        acrossInput.value = "0";
      }

      if (acrossToggle) {
        acrossToggle.hidden = true;
      }
    }

    function render() {
      var selected = selectedCount();
      var acrossActive = acrossInput && acrossInput.value === "1";

      if (counter) {
        counter.hidden = selected === 0;
      }

      if (count) {
        count.textContent = acrossActive ? String(total) : String(selected);
      }

      if (acrossToggle && !acrossActive) {
        // Offered only once the whole visible page is selected, and
        // only when there is more beyond it.
        acrossToggle.hidden = !(
          selected === rows.length && total > rows.length
        );
      }

      if (selectAll) {
        selectAll.checked = selected === rows.length && selected > 0;
        selectAll.indeterminate = selected > 0 && selected < rows.length;
      }
    }

    if (selectAll) {
      selectAll.addEventListener("change", function () {
        rows.forEach(function (row) {
          row.checked = selectAll.checked;
        });
        clearAcross();
        render();
      });
    }

    rows.forEach(function (row) {
      row.addEventListener("change", function () {
        clearAcross();
        render();
      });
    });

    if (acrossToggle) {
      acrossToggle.addEventListener("click", function () {
        if (acrossInput) {
          acrossInput.value = "1";
        }

        acrossToggle.hidden = true;
        render();
      });
    }

    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialise);
  } else {
    initialise();
  }
})();
