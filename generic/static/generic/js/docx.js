/**
 * The merge page: a template and documents chosen, put in order, sent
 * to the merge endpoint, and the merged file saved.
 *
 * Nothing is uploaded until the reader merges, and nothing is stored:
 * the files go with the request, in the order shown, and the answer is
 * the merged document.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  var EXTENSIONS = [".docx", ".dotx"];

  function readConfig(id) {
    var element = document.getElementById(id);

    try {
      return element ? JSON.parse(element.textContent) : {};
    } catch (error) {
      return {};
    }
  }

  function isWordFile(file) {
    var name = (file.name || "").toLowerCase();

    return EXTENSIONS.some(function (extension) {
      return name.slice(-extension.length) === extension;
    });
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("docxMerge", function (configId) {
      var config = readConfig(configId);
      var counter = 0;

      return {
        config: config,
        template: null,
        documents: [],
        name: "",
        pageBreaks: true,
        dragging: "",
        busy: false,
        error: "",

        limits: function () {
          return Generic.format(
            t("Word files (.docx, .dotx), up to %(count)s documents of %(size)s each."),
            {
              count: config.maxFiles,
              size: Generic.formatSize(config.maxSize)
            }
          );
        },

        size: function (file) {
          return Generic.formatSize(file.size);
        },

        /** The reason a file is refused here, or "". */
        problem: function (file) {
          if (!isWordFile(file)) {
            return Generic.format(
              t("%(name)s is not a Word file (.docx or .dotx)."),
              { name: file.name }
            );
          }

          if (config.maxSize && file.size > config.maxSize) {
            return Generic.format(t("%(name)s is too large: at most %(limit)s."), {
              name: file.name,
              limit: Generic.formatSize(config.maxSize)
            });
          }

          return "";
        },

        chooseTemplate: function (files) {
          var file = files && files[0];

          this.error = "";

          if (!file) {
            return;
          }

          this.error = this.problem(file);

          if (!this.error) {
            this.template = file;
          }
        },

        addDocuments: function (files) {
          var self = this;

          this.error = "";

          Array.prototype.forEach.call(files || [], function (file) {
            var problem = self.problem(file);

            if (problem) {
              self.error = problem;
              return;
            }

            if (config.maxFiles && self.documents.length >= config.maxFiles) {
              self.error = Generic.format(
                t("At most %(count)s documents can be merged at once."),
                { count: config.maxFiles }
              );
              return;
            }

            counter += 1;
            self.documents.push({ key: counter, file: file });
          });
        },

        dropped: function (event, target) {
          this.dragging = "";

          var files = event.dataTransfer ? event.dataTransfer.files : [];

          if (target === "template") {
            this.chooseTemplate(files);
          } else {
            this.addDocuments(files);
          }
        },

        picked: function (event, target) {
          if (target === "template") {
            this.chooseTemplate(event.target.files);
          } else {
            this.addDocuments(event.target.files);
          }

          // The same file chosen again is a change too.
          event.target.value = "";
        },

        move: function (index, step) {
          var other = index + step;

          if (other < 0 || other >= this.documents.length) {
            return;
          }

          var entry = this.documents.splice(index, 1)[0];

          this.documents.splice(other, 0, entry);
        },

        remove: function (index) {
          this.documents.splice(index, 1);
        },

        clearTemplate: function () {
          this.template = null;
        },

        canMerge: function () {
          return !this.busy && this.documents.length > 0 && config.url;
        },

        merge: function () {
          var self = this;

          if (!this.canMerge()) {
            return;
          }

          var body = new FormData();

          this.documents.forEach(function (entry) {
            body.append("documents", entry.file, entry.file.name);
          });

          if (this.template) {
            body.append("template", this.template, this.template.name);
          }

          body.append("name", this.name);
          body.append("page_breaks", this.pageBreaks ? "true" : "false");

          this.busy = true;
          this.error = "";

          Generic.api
            .download(config.url, body, { fallbackName: "merged.docx" })
            .then(function (name) {
              Generic.toast(
                Generic.format(t("%(name)s is ready."), { name: name }),
                "success"
              );
            })
            .catch(function (error) {
              self.error = error.message || t("The merge failed.");
            })
            .then(function () {
              self.busy = false;
            });
        }
      };
    });
  });
})(window, document);
