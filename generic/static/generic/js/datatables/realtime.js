/**
 * Tables that refresh themselves.
 *
 * A resource table follows its model's topic on the shared events
 * socket; when anyone changes a row - from a form, a bulk action, the
 * Django admin or a shell - the table reloads the page it is on.
 *
 * `realtimeEvents` lists other event types to reload on, and a
 * `generic:tables-reload` event on the document reloads every table.
 *
 * Another feature may hold the reload back, and may say which changes
 * it already knows about:
 *
 *   controller.holdsReload()         true while a reload would hurt -
 *                                    somebody typing in a grid - and
 *                                    the reload waits
 *   controller.skipsChange(payload)  true for a change this page made
 *                                    itself and already shows
 *   controller.releaseReload()       set here: call it when the hold
 *                                    ends, and a waiting reload runs
 *   controller.requestReload()       set here: ask for a reload that
 *                                    respects the hold
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;

  core.registerFeature({
    name: "realtime",

    init: function (controller) {
      var Generic = window.Generic;
      var topic = controller.options.realtimeTopic;
      var types = controller.options.realtimeEvents || [];

      controller.listen(document, "generic:tables-reload", function () {
        controller.reload(false);
      });

      controller.realtimeStops = [];

      if (!Generic || !Generic.events || (!topic && !types.length)) {
        return;
      }

      var waiting = false;

      // A burst of saves - an import, a bulk action - is one reload.
      var refresh = core.debounce(function () {
        // Redrawing takes every control out from under the reader, and
        // whatever they were typing with it. The rows come back when
        // they stop.
        if (controller.holdsReload && controller.holdsReload()) {
          waiting = true;

          return;
        }

        waiting = false;
        controller.reload(false);
      }, 600);

      controller.releaseReload = function () {
        if (waiting) {
          refresh();
        }
      };

      controller.requestReload = function () {
        waiting = true;
        refresh();
      };

      if (topic) {
        Generic.events.subscribe(topic);
        controller.realtimeStops.push(
          Generic.events.on("resource.changed", function (payload) {
            if (!payload || "resource." + payload.resource !== topic) {
              return;
            }

            if (controller.skipsChange && controller.skipsChange(payload)) {
              return;
            }

            refresh();
          })
        );
      }

      types.forEach(function (type) {
        controller.realtimeStops.push(Generic.events.on(type, refresh));
      });
    },

    destroy: function (controller) {
      (controller.realtimeStops || []).forEach(function (stop) {
        stop();
      });
      controller.realtimeStops = [];
    }
  });
})(window, document);
