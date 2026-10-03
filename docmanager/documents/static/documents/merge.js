/**
 * The "Merge Word files" page: the chosen files put in order, added
 * and removed. The form itself is a plain POST: each item is a hidden
 * input, in the order shown, and the answer is the merged file.
 */
(function (window, document) {
  "use strict";

  function readConfig(id) {
    var element = document.getElementById(id);

    try {
      return element ? JSON.parse(element.textContent) : {};
    } catch (error) {
      return {};
    }
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("documentsMerge", function (configId) {
      var config = readConfig(configId);
      var folder = document.getElementById("merge-folder");

      return {
        items: config.items || [],
        choices: config.choices || [],
        adding: "",
        folder: folder ? folder.value : "",

        available: function () {
          var chosen = this.items.map(function (item) {
            return item.key;
          });

          return this.choices.filter(function (choice) {
            return chosen.indexOf(choice.key) === -1;
          });
        },

        full: function () {
          return this.items.length >= (config.maxItems || 50);
        },

        add: function () {
          var key = this.adding;
          var choice = this.choices.filter(function (entry) {
            return entry.key === key;
          })[0];

          if (choice && !this.full()) {
            this.items.push(choice);
          }

          this.adding = "";
        },

        move: function (index, step) {
          var target = index + step;

          if (target < 0 || target >= this.items.length) {
            return;
          }

          var item = this.items.splice(index, 1)[0];

          this.items.splice(target, 0, item);
        },

        remove: function (index) {
          this.items.splice(index, 1);
        }
      };
    });
  });
})(window, document);
