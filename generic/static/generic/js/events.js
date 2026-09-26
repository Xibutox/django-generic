/**
 * The events WebSocket, shared by everything on the page.
 *
 * One socket per tab: the notification bell, a table refreshing itself
 * and a project's own widgets all listen to the same connection rather
 * than opening one each.
 *
 * Every frame is re-dispatched on `document` twice - as
 * `generic:event` and as `generic:<type>` - so a listener can take
 * everything or only what concerns it:
 *
 *   Generic.events.on("notification.created", function (payload) {...});
 *
 * Reconnection backs off exponentially and gives up after a few tries.
 * Close code 4001 means the session is gone, so it stops at once; a
 * handshake the server refuses outright closes with 1006 instead,
 * which is why the attempts are capped rather than left unbounded.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var MAX_ATTEMPTS = 6;
  var SIGNED_OUT = 4001;

  function EventsClient() {
    this.socket = null;
    this.attempts = 0;
    this.topics = new Set();
    this.state = "idle";
    this.timer = null;
  }

  EventsClient.prototype.url = function () {
    var path = Generic.config().websocketUrl;

    if (!path) {
      return null;
    }

    if (/^wss?:\/\//.test(path)) {
      return path;
    }

    var scheme = window.location.protocol === "https:" ? "wss" : "ws";

    return scheme + "://" + window.location.host + path;
  };

  EventsClient.prototype.setState = function (state) {
    this.state = state;
    document.dispatchEvent(
      new CustomEvent("generic:socket", { detail: { state: state } })
    );
  };

  EventsClient.prototype.connect = function () {
    var url = this.url();

    if (!url || this.socket || !Generic.config().user.authenticated) {
      return;
    }

    var self = this;
    var socket;

    try {
      socket = new window.WebSocket(url);
    } catch (error) {
      this.setState("offline");
      return;
    }

    this.socket = socket;
    this.setState("connecting");

    socket.addEventListener("open", function () {
      self.attempts = 0;
      self.setState("open");

      // A reconnect starts a fresh server-side session: the topics
      // this tab followed have to be asked for again.
      self.topics.forEach(function (topic) {
        self.send({ action: "subscribe", topic: topic });
      });
    });

    socket.addEventListener("message", function (message) {
      var frame;

      try {
        frame = JSON.parse(message.data);
      } catch (error) {
        return;
      }

      if (!frame || !frame.type) {
        return;
      }

      document.dispatchEvent(
        new CustomEvent("generic:event", { detail: frame })
      );
      document.dispatchEvent(
        new CustomEvent("generic:" + frame.type, { detail: frame })
      );
    });

    socket.addEventListener("close", function (event) {
      self.socket = null;

      if (event.code === SIGNED_OUT) {
        self.setState("signed-out");
        return;
      }

      if (self.attempts >= MAX_ATTEMPTS) {
        self.setState("offline");
        return;
      }

      self.setState("reconnecting");
      self.attempts += 1;
      self.timer = window.setTimeout(function () {
        self.connect();
      }, Math.min(1000 * Math.pow(2, self.attempts), 30000));
    });
  };

  EventsClient.prototype.send = function (payload) {
    if (this.socket && this.socket.readyState === window.WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
      return true;
    }

    return false;
  };

  /** Follow a topic, now and after any reconnection. */
  EventsClient.prototype.subscribe = function (topic) {
    if (!topic) {
      return;
    }

    this.topics.add(topic);
    this.send({ action: "subscribe", topic: topic });
  };

  EventsClient.prototype.unsubscribe = function (topic) {
    this.topics.delete(topic);
    this.send({ action: "unsubscribe", topic: topic });
  };

  /**
   * Listen to one event type. Returns a function that stops listening.
   *
   * The handler receives the payload, then the whole frame.
   */
  EventsClient.prototype.on = function (type, handler) {
    var name = type === "*" ? "generic:event" : "generic:" + type;

    function listener(event) {
      var frame = event.detail || {};
      handler(frame.payload || {}, frame);
    }

    document.addEventListener(name, listener);

    return function () {
      document.removeEventListener(name, listener);
    };
  };

  EventsClient.prototype.close = function () {
    window.clearTimeout(this.timer);
    this.attempts = MAX_ATTEMPTS;

    if (this.socket) {
      this.socket.close();
    }
  };

  Generic.events = new EventsClient();

  Generic.ready(function () {
    Generic.events.connect();
  });
})(window, document);
