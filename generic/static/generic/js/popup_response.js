/**
 * Runs inside the popup after a related object was saved.
 *
 * Hands the result to the window that opened it and closes. The payload
 * is read from a json_script element rather than an inline literal, so
 * no server value is ever interpolated into executable code.
 *
 * A popup opened by `Generic.dialogs.record` - in a dialog's frame, or
 * the window it falls back to - names its request (`requestId`): the
 * page holding it is told the way a resource's form tells it, and
 * closes the dialog itself.
 */
(function () {
  "use strict";

  var element = document.getElementById("popup-response-data");
  var framed = window.parent && window.parent !== window;
  var host = window.opener || (framed ? window.parent : null);

  if (!element || !host) {
    return;
  }

  var data;

  try {
    data = JSON.parse(element.textContent);
  } catch (error) {
    if (window.opener) {
      window.close();
    }
    return;
  }

  if (data.requestId) {
    host.postMessage(
      {
        type: "generic:relation-saved",
        requestId: data.requestId,
        id: data.newValue || data.value,
        label: data.obj || ""
      },
      window.location.origin
    );
  }

  if (window.opener) {
    window.opener.dispatchEvent(
      new CustomEvent("generic:popupresponse", { detail: data })
    );
    window.close();
  }
})();
