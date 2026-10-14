/**
 * The Server status page: one card per server, filled from its status
 * endpoint, refreshed every few seconds while the page is in view.
 *
 * A status is a sample - how busy the processors are right now - not
 * an event anything could push: nothing happens when a disk fills up a
 * little more. So this page asks, at the pace its reader chose, and
 * stops asking while it is hidden. Each server is asked on its own: one
 * that takes its time holds up its card, not the page.
 *
 * Values reach the page through x-text only; links through
 * Generic.isSafeUrl.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  /* Samples kept per server for the trend line: an hour at 30 s. */
  var HISTORY = 120;

  var ORDER = ["off", "ok", "warning", "error"];

  function readConfig(id) {
    var element = document.getElementById(id);

    try {
      return element ? JSON.parse(element.textContent) : {};
    } catch (error) {
      return {};
    }
  }

  function worst(levels) {
    var found = "ok";

    levels.forEach(function (level) {
      if (ORDER.indexOf(level) > ORDER.indexOf(found)) {
        found = level;
      }
    });

    return found === "off" ? "ok" : found;
  }

  function number(value, digits) {
    if (value === null || value === undefined || isNaN(value)) {
      return "";
    }

    return Number(value).toLocaleString(document.documentElement.lang || undefined, {
      maximumFractionDigits: digits === undefined ? 1 : digits
    });
  }

  function size(bytes) {
    return bytes === null || bytes === undefined ? "" : Generic.formatSize(bytes);
  }

  /* 3 d 4 h, 4 h 12 min, 12 min: two units are enough to read. */
  function duration(seconds) {
    if (seconds === null || seconds === undefined) {
      return "";
    }

    var days = Math.floor(seconds / 86400);
    var hours = Math.floor((seconds % 86400) / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);

    if (days) {
      return Generic.format(t("%(days)s d %(hours)s h"), { days: days, hours: hours });
    }

    if (hours) {
      return Generic.format(t("%(hours)s h %(minutes)s min"), { hours: hours, minutes: minutes });
    }

    if (minutes) {
      return Generic.format(t("%(minutes)s min"), { minutes: minutes });
    }

    return Generic.format(t("%(seconds)s s"), { seconds: Math.floor(seconds) });
  }

  function clock(date) {
    return date.toLocaleTimeString(document.documentElement.lang || undefined);
  }

  function safe(url) {
    return url && Generic.isSafeUrl(url) ? url : "";
  }

  function makeCard(server, local) {
    return {
      key: local ? "local" : "server-" + server.id,
      local: local,
      name: server.name,
      description: server.description || "",
      url: server.url,
      changeUrl: safe(server.changeUrl),
      level: "off",
      loading: false,
      status: null,
      error: "",
      elapsed: null,
      checkedAt: null,
      history: []
    };
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("serverStatus", function (configId) {
      var config = readConfig(configId);

      return {
        cards: [],
        refresh: Number(config.refresh) || 0,
        timer: null,

        init: function () {
          var self = this;

          this.cards = [makeCard({ name: t("This server"), url: config.localUrl }, true)].concat(
            (config.servers || []).map(function (server) {
              return makeCard(server, false);
            })
          );

          document.addEventListener("visibilitychange", function () {
            if (document.hidden) {
              self.stop();
            } else {
              self.refreshAll();
            }
          });

          this.refreshAll();
        },

        stop: function () {
          if (this.timer) {
            window.clearTimeout(this.timer);
            this.timer = null;
          }
        },

        /* The next round once this one is over: never two at once. */
        schedule: function () {
          var self = this;

          this.stop();

          if (!this.refresh || document.hidden || this.busy()) {
            return;
          }

          this.timer = window.setTimeout(function () {
            self.refreshAll();
          }, this.refresh * 1000);
        },

        busy: function () {
          return this.cards.some(function (card) {
            return card.loading;
          });
        },

        refreshAll: function () {
          var self = this;

          this.stop();

          return Promise.all(
            this.cards.map(function (card) {
              return self.load(card);
            })
          ).then(function () {
            self.schedule();
          });
        },

        load: function (card) {
          var started = Date.now();

          if (card.loading || !card.url) {
            return Promise.resolve();
          }

          card.loading = true;

          return Generic.api
            .get(card.url)
            .then(function (answer) {
              /* This server answers its status; another one's comes
                 wrapped in what this server learnt asking for it. */
              var status = card.local ? answer : answer.status;

              card.elapsed = card.local ? Date.now() - started : answer.elapsed_ms;
              card.error = card.local || answer.reachable ? "" : answer.error || t("Unreachable");
              card.status = status || null;

              if (card.local && status && status.server.title) {
                card.name = status.server.title;
              }
              card.level = card.error ? "error" : (status && status.level) || "error";

              if (status && status.system) {
                card.history.push({
                  at: Date.now(),
                  cpu: status.system.cpu.percent,
                  memory: status.system.memory.percent
                });

                if (card.history.length > HISTORY) {
                  card.history.shift();
                }
              }
            })
            .catch(function (error) {
              card.error = error.message || t("Unreachable");
              card.status = null;
              card.level = "error";
            })
            .finally(function () {
              card.loading = false;
              card.checkedAt = new Date();
            });
        },

        /* -- what the cards say ------------------------------------- */

        overall: function () {
          return worst(
            this.cards
              .filter(function (card) {
                return card.checkedAt;
              })
              .map(function (card) {
                return card.level;
              })
          );
        },

        overviewTitle: function () {
          var checked = this.cards.filter(function (card) {
            return card.checkedAt;
          });

          if (!checked.length) {
            return t("Asking the servers...");
          }

          return {
            ok: t("Every server is working"),
            warning: t("Something needs attention"),
            error: t("Something is not working")
          }[this.overall()];
        },

        overviewDetail: function () {
          var counts = { ok: 0, warning: 0, error: 0 };
          var last = null;

          this.cards.forEach(function (card) {
            if (card.checkedAt) {
              counts[card.level === "off" ? "ok" : card.level] += 1;

              if (!last || card.checkedAt > last) {
                last = card.checkedAt;
              }
            }
          });

          var parts = [
            Generic.format(t("%(count)s working"), { count: counts.ok })
          ];

          if (counts.warning) {
            parts.push(Generic.format(t("%(count)s to look at"), { count: counts.warning }));
          }

          if (counts.error) {
            parts.push(Generic.format(t("%(count)s failing"), { count: counts.error }));
          }

          if (last) {
            parts.push(Generic.format(t("checked at %(time)s"), { time: clock(last) }));
          }

          return parts.join(" \u00b7 ");
        },

        levelLabel: function (level) {
          return {
            off: t("Not checked"),
            ok: t("Working"),
            warning: t("Needs attention"),
            error: t("Not working")
          }[level] || level;
        },

        levelIcon: function (level) {
          return { ok: "check_circle", warning: "warning", error: "error" }[level] || "pending";
        },

        badgeClass: function (level) {
          return { ok: "badge--success", warning: "badge--warning", error: "badge--danger" }[level] || "";
        },

        subtitle: function (card) {
          var status = card.status;

          if (!status) {
            return "";
          }

          var parts = status.server.title !== card.name ? [status.server.title] : [];

          if (status.server.version) {
            parts.push(status.server.version);
          }

          parts.push(status.system.host.hostname);

          return parts.join(" \u00b7 ");
        },

        pageUrl: function (card) {
          return card.local || !card.status ? "" : safe(card.status.server.page_url);
        },

        restartText: function (card) {
          var restart = card.status.application.restart;
          var when = new Date(restart.scheduledAt);

          return Generic.format(t("A restart is planned at %(time)s, for about %(minutes)s min."), {
            time: when.toLocaleString(document.documentElement.lang || undefined),
            minutes: restart.durationMinutes
          });
        },

        gauges: function (card) {
          var system = card.status.system;
          var cpu = system.cpu;
          var memory = system.memory;
          var gauges = [
            {
              key: "cpu",
              icon: "memory",
              label: t("Processors"),
              percent: cpu.percent,
              level: cpu.level,
              value: cpu.percent === null ? t("Not measured") : number(cpu.percent) + " %",
              detail: [
                Generic.format(t("%(count)s cores"), { count: cpu.count }),
                cpu.load
                  ? Generic.format(t("load %(load)s"), {
                      load: cpu.load
                        .map(function (value) {
                          return number(value, 2);
                        })
                        .join(" / ")
                    })
                  : ""
              ]
                .filter(Boolean)
                .join(" \u00b7 ")
            },
            {
              key: "memory",
              icon: "memory_alt",
              label: t("Memory"),
              percent: memory.percent,
              level: memory.level,
              value: memory.percent === null ? t("Not measured") : number(memory.percent) + " %",
              detail:
                memory.total === null
                  ? ""
                  : Generic.format(t("%(used)s of %(total)s"), { used: size(memory.used), total: size(memory.total) })
            }
          ];

          if (memory.swap && memory.swap.total) {
            gauges.push({
              key: "swap",
              icon: "swap_horiz",
              label: t("Swap"),
              percent: memory.swap.percent,
              level: memory.swap.level,
              value: number(memory.swap.percent) + " %",
              detail: Generic.format(t("%(used)s of %(total)s"), {
                used: size(memory.swap.used),
                total: size(memory.swap.total)
              })
            });
          }

          system.disks.forEach(function (disk, index) {
            /* "System, Media files, Database default" lives on one disk:
               named after the first, the others in its tip. */
            var places = String(disk.label || "").split(", ");

            gauges.push({
              key: "disk-" + index,
              icon: "hard_drive",
              label: places.length > 1 ? places[0] + " +" + (places.length - 1) : places[0],
              title: disk.label + " (" + disk.path + ")",
              percent: disk.percent,
              level: disk.level,
              value: number(disk.percent) + " %",
              detail: Generic.format(t("%(free)s free of %(total)s"), { free: size(disk.free), total: size(disk.total) })
            });
          });

          return gauges;
        },

        /* The trend since the page was opened, as polyline points. */
        trend: function (card, name) {
          var samples = card.history;
          var count = samples.length;

          return samples
            .map(function (sample, index) {
              var value = sample[name];

              if (value === null || value === undefined) {
                return null;
              }

              var x = count > 1 ? (100 * index) / (count - 1) : 0;
              var y = 31 - (30 * Math.min(100, Math.max(0, value))) / 100;

              return x.toFixed(2) + "," + y.toFixed(2);
            })
            .filter(Boolean)
            .join(" ");
        },

        trendSpan: function (card) {
          var samples = card.history;

          if (samples.length < 2) {
            return "";
          }

          return Generic.format(t("over the last %(span)s"), {
            span: duration((samples[samples.length - 1].at - samples[0].at) / 1000)
          });
        },

        checkGroups: function (card) {
          var groups = [];
          var byName = {};

          (card.status.checks || []).forEach(function (check) {
            if (!byName[check.group]) {
              byName[check.group] = { name: check.group, checks: [] };
              groups.push(byName[check.group]);
            }

            byName[check.group].checks.push(check);
          });

          return groups;
        },

        milliseconds: function (value) {
          return value === null || value === undefined ? "" : Generic.format(t("%(ms)s ms"), { ms: number(value, 0) });
        },

        facts: function (card) {
          var status = card.status;
          var host = status.system.host;
          var process = status.system.process;
          var server = status.server;
          var application = status.application;
          var facts = [
            { label: t("Host"), value: host.hostname },
            { label: t("System"), value: [host.system, host.machine].filter(Boolean).join(" \u00b7 ") },
            { label: t("Up for"), value: duration(host.uptime) },
            { label: t("Application up for"), value: duration(process.uptime) },
            { label: t("Process"), value: Generic.format(t("PID %(pid)s"), { pid: process.pid }) },
            { label: t("Process memory"), value: size(process.memory) },
            { label: t("Threads"), value: process.threads === null ? "" : String(process.threads) },
            { label: t("Python"), value: host.python },
            { label: t("Django"), value: server.django },
            { label: t("django-generic"), value: server.framework },
            { label: t("Time zone"), value: server.time_zone },
            { label: t("Debug mode"), value: server.debug ? t("On") : t("Off") },
            { label: t("Accounts"), value: String(application.users) },
            { label: t("Signed in today"), value: String(application.users_today) },
            {
              label: t("Open sessions"),
              value: application.sessions === null ? "" : String(application.sessions)
            }
          ];

          if (!host.psutil) {
            facts.push({ label: t("Measured with"), value: t("the standard library (install psutil for more)") });
          }

          return facts.filter(function (fact) {
            return fact.value;
          });
        },

        footer: function (card) {
          if (!card.checkedAt) {
            return "";
          }

          var parts = [Generic.format(t("Checked at %(time)s"), { time: clock(card.checkedAt) })];

          if (card.elapsed !== null && card.elapsed !== undefined) {
            parts.push(Generic.format(t("answered in %(ms)s ms"), { ms: number(card.elapsed, 0) }));
          }

          if (card.status && card.status.duration_ms !== undefined) {
            parts.push(Generic.format(t("checks took %(ms)s ms"), { ms: number(card.status.duration_ms, 0) }));
          }

          return parts.join(" \u00b7 ");
        }
      };
    });
  });
})(window, document);
