/**
 * The summary page of a record: figures, sections of values, and the
 * tables of its related records.
 *
 * The first paint comes from the JSON embedded in the page. When the
 * record changes - here, in another tab, or by someone else - the same
 * JSON is fetched again from the resource's summary endpoint. Related
 * tables start the first time their tab is shown, and keep their count
 * current as they reload.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  function readJson(id) {
    var element = document.getElementById(id);

    if (!element) {
      return null;
    }

    try {
      return JSON.parse(element.textContent);
    } catch (error) {
      return null;
    }
  }

  /** Start a related table, once the tables' script has loaded.
   *
   * This script and Alpine run before the tables' own script, so the
   * first tab may be shown before `GenericDataTables.start` exists.
   */
  function startTable(table) {
    var tables = window.GenericDataTables;

    if (tables && typeof tables.start === "function") {
      tables.start(table);
      return;
    }

    document.addEventListener(
      "generic:datatables-loaded",
      function () {
        window.GenericDataTables.start(table);
      },
      { once: true }
    );
  }

  /** The name of the history tab, which is not a related table. */
  var HISTORY_TAB = "__history";

  function normalize(data) {
    data = data || {};

    return {
      object: data.object || {},
      urls: data.urls || {},
      actions: data.actions || [],
      transitions: data.transitions || [],
      stats: data.stats || [],
      sections: data.sections || [],
      related: data.related || [],
      history: data.history || null,
      topic: data.topic || ""
    };
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("recordSummary", function (configId) {
      return {
        data: normalize(readJson(configId)),
        active: "",
        historyTab: HISTORY_TAB,
        counts: {},
        collapsed: {},
        busy: false,
        // How many tabs are drawn in the bar. The rest are behind the
        // button at its end; everything shows until the bar has been
        // measured, so a slow first paint is never a bar with gaps.
        visible: 99,
        overflow: false,
        measuring: false,

        init: function () {
          var self = this;

          this.data.sections.forEach(function (section) {
            self.collapsed[section.name] = Boolean(section.collapsed);
          });

          // "#related-tickets" opens that tab: an "Add" of a related
          // table comes back here that way. "#history" opens the one
          // tab that is not a related table.
          var hash = window.location.hash;
          var wanted = hash.replace(/^#related-/, "");
          var names = this.data.related.map(function (entry) {
            return entry.name;
          });

          if (this.data.history) {
            names.push(HISTORY_TAB);

            if (hash === "#history") {
              wanted = HISTORY_TAB;
            }
          }

          this.active = names.indexOf(wanted) !== -1 ? wanted : names[0] || "";

          // After every deferred script, DataTables among them.
          Generic.ready(function () {
            if (self.active) {
              self.show(self.active);
            }

            self.follow();
            self.watchWidth();
          });
        },

        /* -- The tab bar ------------------------------------------------
         *
         * One list, whatever a tab leads to: the related tables, then
         * the history. The bar draws as many as fit and hides the rest
         * behind a button, so a record with twenty related tables has
         * a bar as usable as a record with two.
         */

        get tabs() {
          var self = this;
          var list = this.data.related.map(function (entry) {
            return {
              name: entry.name,
              title: entry.title,
              icon: entry.icon,
              count: String(self.count(entry))
            };
          });

          if (this.data.history) {
            list.push({
              name: HISTORY_TAB,
              title: this.data.history.label,
              icon: "history",
              count: ""
            });
          }

          return list;
        },

        /** The tabs behind the button, and whether the open one is there. */
        get hidden() {
          return this.tabs.slice(this.visible);
        },

        get hiddenActive() {
          var active = this.active;

          return this.hidden.some(function (entry) {
            return entry.name === active;
          });
        },

        /** Re-measure whenever the bar's width - or a tab's - changes. */
        watchWidth: function () {
          var self = this;
          var bar = this.$root.querySelector(".summary-tabs-bar");

          if (!bar) {
            return;
          }

          this.measure();

          if (!window.ResizeObserver) {
            window.addEventListener(
              "resize",
              Generic.debounce(function () {
                self.measure();
              }, 150)
            );

            return;
          }

          // The window is not the only thing that changes this width:
          // pinning the navigation does too, without a resize event.
          new window.ResizeObserver(
            Generic.debounce(function () {
              self.measure();
            }, 100)
          ).observe(bar);
        },

        measure: function () {
          var wrapper = this.$root.querySelector(".summary-tabs-bar");
          var strip = this.$root.querySelector(".summary-tabs");

          if (!wrapper || !strip || this.measuring) {
            return;
          }

          this.measuring = true;
          // Widths are read with every tab shown - and with the button
          // shown, so the room left over is what the strip really has.
          // A hidden element measures zero, and nothing is painted
          // between the two lines below, so the bar never flickers.
          wrapper.classList.add("is-measuring");

          var tabs = strip.querySelectorAll(".summary-tab");
          var style = window.getComputedStyle(strip);
          var gap = parseFloat(style.columnGap || style.gap) || 0;
          var room =
            strip.clientWidth -
            (parseFloat(style.paddingLeft) || 0) -
            (parseFloat(style.paddingRight) || 0);
          var widths = [];
          var total = 0;
          var index;

          for (index = 0; index < tabs.length; index++) {
            widths.push(tabs[index].offsetWidth);
            total += widths[index] + (index ? gap : 0);
          }

          wrapper.classList.remove("is-measuring");
          this.measuring = false;

          if (!tabs.length || total <= room) {
            this.visible = tabs.length;
            return;
          }

          var used = 0;
          var fit = 0;

          for (index = 0; index < widths.length; index++) {
            var next = used + widths[index] + (index ? gap : 0);

            if (next > room) {
              break;
            }

            used = next;
            fit = index + 1;
          }

          // Always one tab in the bar: a bar holding nothing but the
          // button says nothing about where you are.
          this.visible = Math.max(1, fit);
        },

        related: function (name) {
          return (
            this.data.related.find(function (entry) {
              return entry.name === name;
            }) || {}
          );
        },

        count: function (entry) {
          var live = this.counts[entry.name];

          return live !== undefined ? live : entry.count;
        },

        /** The last thing the history has to say, in one line. */
        lastChange: function () {
          var last = this.data.history && this.data.history.last;

          if (!last) {
            return "";
          }

          return Generic.format(t("%(action)s by %(who)s, %(when)s"), {
            action: last.actionLabel,
            who: last.who,
            when: last.when
          });
        },

        show: function (name) {
          var self = this;

          this.active = name;

          this.$nextTick(function () {
            var table = document.querySelector(
              'table[data-related="' + window.CSS.escape(name) + '"]'
            );

            if (!table) {
              return;
            }

            // Started already: only the widths, measured while hidden.
            if (table.genericDataTable) {
              table.genericDataTable.instance.columns.adjust();
              return;
            }

            table.addEventListener(
              "generic:datatable-ready",
              function (event) {
                event.detail.api.on("xhr.dt", function (e, settings, json) {
                  if (json && typeof json.recordsTotal === "number") {
                    self.counts[name] = json.recordsTotal;
                    // A tab that has just learnt its total is wider
                    // than it was a moment ago.
                    self.$nextTick(function () {
                      self.measure();
                    });
                  }
                });
              },
              { once: true }
            );

            startTable(table);
          });
        },

        /** Open the History tab from the line at the top of the page.
         *
         * The tabs are below the fold on all but the shortest records,
         * so switching to one without bringing it into view looks like
         * a button that does nothing.
         */
        openHistory: function () {
          // $root, not $el: the expression is evaluated on the button
          // that was pressed, and $el is always that element.
          var root = this.$root;

          this.show(HISTORY_TAB);

          this.$nextTick(function () {
            var panel = root.querySelector(".summary-related");

            if (panel) {
              panel.scrollIntoView({ behavior: "smooth", block: "start" });
            }
          });
        },

        toggle: function (section) {
          this.collapsed[section.name] = !this.collapsed[section.name];
        },

        safeUrl: function (url) {
          return url && Generic.isSafeUrl(url) ? url : null;
        },

        /** A tag's classes: tinted by one colour, or drawn exactly. */
        tagClass: function (tag) {
          return Generic.colors.clean(tag.background) ? "tag tag--solid" : "tag";
        },

        /** Its colours, as custom properties the stylesheet reads. */
        tagStyle: function (tag) {
          var colors = Generic.colors;
          var background = colors.clean(tag.background);
          var color = colors.clean(tag.color);

          if (background) {
            return {
              "--tag-background": background,
              "--tag-text": color || colors.readableOn(background)
            };
          }

          return color ? { "--tag-color": color } : {};
        },

        moreLabel: function (count) {
          return Generic.format(t("and %(count)s more"), { count: count });
        },

        refresh: function () {
          var self = this;
          var url = this.data.urls.summary;

          if (!url) {
            return Promise.resolve();
          }

          return Generic.api
            .get(url)
            .then(function (data) {
              var collapsed = self.collapsed;

              self.data = normalize(data);
              // Folding is the user's: a refresh keeps it.
              self.data.sections.forEach(function (section) {
                if (collapsed[section.name] === undefined) {
                  collapsed[section.name] = Boolean(section.collapsed);
                }
              });
              self.$nextTick(function () {
                self.measure();
              });
            })
            .catch(function () {
              /* What is shown stays; the next change tries again. */
            });
        },

        /** Refresh when this record changes; its tables refresh alone. */
        follow: function () {
          var self = this;
          var topic = this.data.topic;

          if (!topic || !Generic.events) {
            return;
          }

          var refresh = Generic.debounce(function () {
            self.refresh();
          }, 400);

          Generic.events.subscribe(topic);
          Generic.events.on("resource.changed", function (payload) {
            var object = self.data.object;

            if (payload.resource && payload.resource !== object.model) {
              return;
            }

            if (payload.id !== null && payload.id !== undefined) {
              if (String(payload.id) !== object.pk) {
                return;
              }

              if (payload.change === "deleted" || payload.change === "delete") {
                Generic.toast(t("This record has just been deleted."), "warning");
                return;
              }
            }

            refresh();
          });
        },

        /**
         * Take one of the record's transitions: confirmed, or its
         * fields asked for, when it says so; the server checks again.
         */
        take: function (transition) {
          var self = this;
          var fields = transition.fields || [];
          var asked;

          if (fields.length) {
            asked = Generic.dialogs.fields({
              title: transition.label,
              message: transition.confirm,
              fields: fields,
              confirmLabel: transition.label,
              variant: transition.variant === "danger" ? "danger" : ""
            });
          } else if (transition.confirm) {
            asked = Generic.dialogs
              .confirm({
                title: transition.label,
                message: transition.confirm,
                confirmLabel: transition.label,
                variant: transition.variant === "danger" ? "danger" : ""
              })
              .then(function (yes) {
                return yes ? {} : null;
              });
          } else {
            asked = Promise.resolve({});
          }

          asked.then(function (values) {
            if (!values) {
              return;
            }

            self.busy = true;

            Generic.api
              .post(self.data.urls.transitions + transition.name + "/", values)
              .then(function (summary) {
                self.data = normalize(summary);
                Generic.toast(Generic.format(t("%(action)s: done."), { action: transition.label }), "success");
              })
              .catch(function (error) {
                var detail = error && error.data && error.data.detail;
                var first = error && error.data && !detail ? Object.values(error.data)[0] : null;

                Generic.toast(detail || (first && String(first)) || error.message, "error");

                return self.refresh();
              })
              .then(function () {
                self.busy = false;
              });
          });
        },

        /** Run one of the resource's bulk actions on this record. */
        run: function (action) {
          var self = this;
          var asked = action.confirm
            ? Generic.dialogs.confirm({
                title: action.label,
                message: action.confirm,
                confirmLabel: action.label,
                variant: action.variant === "danger" ? "danger" : ""
              })
            : Promise.resolve(true);

          asked.then(function (confirmed) {
            if (!confirmed) {
              return;
            }

            self.busy = true;

            Generic.api
              .post(self.data.urls.actions, {
                action: action.name,
                ids: [self.data.object.pk]
              })
              .then(function (result) {
                var level = (result && result.level) || "success";

                Generic.toast((result && result.message) || t("Done."), level);

                return self.refresh();
              })
              .catch(function (error) {
                var detail = error && error.data && error.data.detail;

                Generic.toast(detail || t("The action could not be run."), "error");
              })
              .then(function () {
                self.busy = false;
              });
          });
        }
      };
    });
  });
})(window, document);
