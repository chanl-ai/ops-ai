/* Ops AI embedded chat loader (c-131). The page loads it with one script tag and calls OpsChat.init once.
 *
 * The chat runs in a cross-origin iframe served by the embed app; this script draws only the launcher and the frame,
 * and passes the session the bank's server minted. The host page never receives message text.
 *
 * Messages with the iframe carry a fixed `ops-chat:` type. Every message received is checked for its window (the
 * iframe's) and its origin (the embed app's), and every message sent names that one origin, never '*'.
 *   loader -> iframe: identify { session, signIn }, open, close
 *   iframe -> loader: ready (repeated until identified), identified, opened, closed, signed-out, session-ended,
 *                     sign-in, message { role, at }, error { code }
 */
(function () {
  'use strict';
  if (window.OpsChat) return;

  var PREFIX = 'ops-chat:';
  var DEFAULT_TTL_S = 900;
  // A session is refreshed this long before it ends, so a person typing never meets an expired one.
  var REFRESH_EARLY_S = 60;
  var script = document.currentScript;
  var scriptOrigin = script && script.src ? new URL(script.src, location.href).origin : location.origin;

  var config = null;
  var host = scriptOrigin;
  var frame = null;
  var panel = null;
  var launcher = null;
  var isOpen = false;
  // null while the config read is in flight; false when the deployment does not list this page.
  var listed = null;
  var openWhenListed = false;
  var identified = false;
  var session; // undefined: not asked yet; null: signed out; string: a session
  var refreshTimer = null;
  var refreshing = null;
  var lastEnded = 0;
  var handlers = {};

  function emit(event, payload) {
    (handlers[event] || []).slice().forEach(function (fn) {
      try {
        fn(payload);
      } catch (e) {
        setTimeout(function () {
          throw e;
        });
      }
    });
  }

  function post(type, data) {
    if (!frame || !frame.contentWindow) return;
    var msg = { type: PREFIX + type };
    if (data) for (var k in data) if (Object.prototype.hasOwnProperty.call(data, k)) msg[k] = data[k];
    frame.contentWindow.postMessage(msg, host);
  }

  function sendIdentity() {
    post('identify', { session: session || null, signIn: !!(config && config.onSignIn) });
  }

  function schedule(expiresIn) {
    clearTimeout(refreshTimer);
    var ttl = typeof expiresIn === 'number' && expiresIn > 0 ? expiresIn : DEFAULT_TTL_S;
    refreshTimer = setTimeout(function () {
      refresh();
    }, Math.max(ttl - REFRESH_EARLY_S, ttl / 2) * 1000);
  }

  function accept(value) {
    var token = value && typeof value === 'object' ? value.session : value;
    var expiresIn = value && typeof value === 'object' ? value.expiresIn : undefined;
    var was = session;
    session = typeof token === 'string' && token ? token : null;
    if (session) schedule(expiresIn);
    else {
      clearTimeout(refreshTimer);
      identified = false;
      if (was !== null) emit('signed-out');
    }
    sendIdentity();
  }

  // One call to the page's getSession at a time; a 401 and a timer arriving together share it.
  function refresh() {
    if (!config || !config.getSession) return Promise.resolve();
    if (refreshing) return refreshing;
    refreshing = Promise.resolve()
      .then(function () {
        return config.getSession();
      })
      .then(accept, function () {
        emit('error', { code: 'session_unavailable' });
        accept(null);
      })
      .then(function () {
        refreshing = null;
      });
    return refreshing;
  }

  function onMessage(event) {
    if (!frame || event.source !== frame.contentWindow || event.origin !== host) return;
    var data = event.data;
    if (!data || typeof data.type !== 'string' || data.type.indexOf(PREFIX) !== 0) return;
    var type = data.type.slice(PREFIX.length);
    if (type === 'ready') {
      // Repeated by the iframe until it is identified, so a session that arrives late is still delivered.
      if (session === undefined) refresh();
      else sendIdentity();
    } else if (type === 'identified') {
      if (!identified) {
        identified = true;
        emit('ready');
      }
    } else if (type === 'session-ended') {
      // One fresh session per ended one: a second end within seconds means the page's endpoint hands out sessions
      // that do not work here (another deployment or origin), so the chat signs out instead of asking forever.
      identified = false;
      var now = Date.now();
      if (now - lastEnded < 5000) accept(null);
      else refresh();
      lastEnded = now;
    } else if (type === 'signed-out') {
      emit('signed-out');
    } else if (type === 'sign-in') {
      if (config && config.onSignIn) config.onSignIn();
    } else if (type === 'closed') {
      setOpen(false);
    } else if (type === 'opened') {
      // The iframe's own acknowledgement; open was already emitted when the panel showed.
    } else if (type === 'message') {
      // Role and time only: the text stays in the iframe.
      emit('message', { role: data.role === 'user' ? 'user' : 'assistant', at: typeof data.at === 'string' ? data.at : '' });
    } else if (type === 'error') {
      emit('error', { code: typeof data.code === 'string' ? data.code : 'unknown' });
    }
  }

  function css(el, styles) {
    for (var k in styles) el.style[k] = styles[k];
  }

  function build() {
    if (launcher) return;
    var root = document.createElement('div');
    root.setAttribute('data-ops-chat', '');
    // Closed: page scripts cannot reach in through the host element (the frame holds the conversation anyway).
    var shadow = root.attachShadow({ mode: 'closed' });
    launcher = document.createElement('button');
    launcher.type = 'button';
    launcher.setAttribute('aria-label', 'Open chat');
    launcher.setAttribute('aria-expanded', 'false');
    launcher.setAttribute('aria-controls', 'ops-chat-panel');
    launcher.textContent = 'Chat';
    css(launcher, {
      position: 'fixed', right: '20px', bottom: '20px', zIndex: '2147483646', height: '48px', minWidth: '48px',
      padding: '0 18px', borderRadius: '24px', border: '0', background: '#111827', color: '#fff',
      font: '600 14px system-ui, sans-serif', cursor: 'pointer', boxShadow: '0 4px 14px rgba(0,0,0,.2)',
    });
    launcher.addEventListener('click', function () {
      setOpen(!isOpen);
    });
    panel = document.createElement('div');
    panel.id = 'ops-chat-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Chat');
    css(panel, {
      position: 'fixed', right: '20px', bottom: '80px', zIndex: '2147483647', width: 'min(400px, calc(100vw - 32px))',
      height: 'min(640px, calc(100vh - 112px))', borderRadius: '12px', overflow: 'hidden', display: 'none',
      boxShadow: '0 12px 40px rgba(0,0,0,.25)', background: '#fff',
    });
    shadow.appendChild(launcher);
    shadow.appendChild(panel);
    document.body.appendChild(root);
  }

  // The iframe is created on first open, so a page whose visitors never open the chat loads nothing more.
  function ensureFrame() {
    if (frame) return;
    frame = document.createElement('iframe');
    frame.title = 'Chat';
    frame.src =
      host + '/embed/' + encodeURIComponent(config.deployment) + '?tenant=' + encodeURIComponent(config.tenant);
    frame.setAttribute('allow', 'clipboard-write');
    css(frame, { border: '0', width: '100%', height: '100%' });
    panel.appendChild(frame);
  }

  function setOpen(open) {
    if (listed === null) openWhenListed = open;
    if (!listed || open === isOpen) return;
    build();
    isOpen = open;
    if (open) ensureFrame();
    panel.style.display = open ? 'block' : 'none';
    launcher.setAttribute('aria-expanded', String(open));
    launcher.setAttribute('aria-label', open ? 'Close chat' : 'Open chat');
    post(open ? 'open' : 'close');
    emit(open ? 'open' : 'close');
    if (open) frame.focus();
    else launcher.focus();
  }

  window.addEventListener('message', onMessage);

  window.OpsChat = {
    init: function (options) {
      if (config) throw new Error('OpsChat.init runs once per page.');
      if (!options || !options.deployment || !options.tenant) throw new Error('OpsChat.init needs deployment and tenant.');
      config = {
        deployment: String(options.deployment),
        tenant: String(options.tenant),
        getSession: typeof options.getSession === 'function' ? options.getSession : null,
        onSignIn: typeof options.onSignIn === 'function' ? options.onSignIn : null,
      };
      if (options.host) host = new URL(String(options.host)).origin;
      // The deployment answers its config only to a page origin it lists, so an unlisted page draws nothing.
      return fetch(host + '/v1/widget/' + encodeURIComponent(config.deployment) + '/config?tenant=' + encodeURIComponent(config.tenant))
        .then(function (r) {
          if (!r.ok) throw new Error(String(r.status));
          listed = true;
          build();
          if (openWhenListed) setOpen(true);
        })
        .catch(function () {
          listed = false;
          emit('error', { code: 'origin_not_allowed' });
        });
    },
    open: function () {
      setOpen(true);
    },
    close: function () {
      setOpen(false);
    },
    identify: function (value) {
      accept(value);
    },
    on: function (event, fn) {
      (handlers[event] = handlers[event] || []).push(fn);
    },
    off: function (event, fn) {
      handlers[event] = (handlers[event] || []).filter(function (h) {
        return h !== fn;
      });
    },
  };
  window.dispatchEvent(new Event('ops-chat:load'));
})();
