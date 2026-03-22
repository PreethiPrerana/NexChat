/**
 * nexchat.js — NexChat frontend
 */

"use strict";

// Auth helpers

const Auth = {
  get access()  { return sessionStorage.getItem("nc_access"); },
  get refresh() { return sessionStorage.getItem("nc_refresh"); },
  get username(){ return sessionStorage.getItem("nc_username"); },

  save(access, refresh) {
    sessionStorage.setItem("nc_access",  access);
    sessionStorage.setItem("nc_refresh", refresh);
  },

  clear() {
    ["nc_access", "nc_refresh", "nc_username"].forEach(k => sessionStorage.removeItem(k));
  },

  isLoggedIn() { return !!this.access; },
};

if (!Auth.isLoggedIn()) {
  window.location.href = "/accounts/login/";
}

// API wrapper

const API = {
  async _fetch(url, opts = {}, retry = true) {
    opts.headers = {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${Auth.access}`,
      ...(opts.headers || {}),
    };
    let res = await fetch(url, opts);

    if (res.status === 401 && retry) {
      const refreshed = await this._refresh();
      if (refreshed) return this._fetch(url, opts, false);
      logout();
      return null;
    }
    return res;
  },

  async _refresh() {
    try {
      const res = await fetch("/api/auth/refresh/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh: Auth.refresh }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      Auth.save(data.access, data.refresh || Auth.refresh);
      return true;
    } catch { return false; }
  },

  async get(url, headers = {}) { return this._fetch(url, { headers }); },
  async post(url, body)       { return this._fetch(url, { method: "POST",   body: JSON.stringify(body) }); },
  async patch(url, body = {}) { return this._fetch(url, { method: "PATCH",  body: JSON.stringify(body) }); },
  async delete(url)           { return this._fetch(url, { method: "DELETE" }); },
};

// State

let rooms           = [];
let currentRoom     = null;
let activeRoomId    = null;          // room whose messages are currently displayed
let sockets         = new Map();     // roomId → WebSocket  (kept alive across room switches)
let reconnectTimers = new Map();     // roomId → timer
let meId            = null;
let newMsgCount     = 0;             // unread msgs arrived while scrolled up
let seenMsgIds      = new Map();     // roomId → Set<messageId>  (dedup across WS + notif)
let replyingTo      = null;          // { id, content, senderName } | null

// Boot

async function boot() {
  const meRes = await API.get("/api/auth/me/");
  if (!meRes || !meRes.ok) { logout(); return; }
  const me = await meRes.json();
  meId = me.id;
  document.getElementById("me-label").textContent = me.display_name || me.username;
  await loadRooms();
  connectNotifications();
}

// Notification WebSocket (per-user channel)
// Receives { "type": "new_room" } when a DM or invite arrives for this user.

let notifSocket = null;
let notifReconnectTimer = null;

function connectNotifications() {
  if (notifSocket) { notifSocket.close(); notifSocket = null; }
  clearTimeout(notifReconnectTimer);

  const proto = location.protocol === "https:" ? "wss" : "ws";
  notifSocket = new WebSocket(`${proto}://${location.host}/ws/notifications/?token=${Auth.access}`);

  notifSocket.onmessage = async ({ data }) => {
    let frame;
    try { frame = JSON.parse(data); } catch { return; }

    if (frame.type === "new_room") {
      await loadRooms();   // refresh sidebar — new DM or invite appeared

    } else if (frame.type === "new_message") {
      const rid = frame.room_id;

      if (rid === activeRoomId) {
        // Delivery fallback: if the room WS is not OPEN, append from the
        // notification payload directly (handles multi-worker / reconnecting).
        const ws = sockets.get(rid);
        if ((!ws || ws.readyState !== WebSocket.OPEN) && frame.payload) {
          appendNewMessage(rid, frame.payload);
        }
        // If WS is OPEN, handleFrame() already fired — appendNewMessage() dedupes.

      } else if (!sockets.has(rid)) {
        // Room socket not open → increment badge via notification channel
        incrementBadge(rid);
      }
      // If sockets.has(rid) but rid !== activeRoomId → handleFrame() already
      // called incrementBadge() for that non-active room socket.
    }
  };

  notifSocket.onclose = (e) => {
    notifSocket = null;
    // Don't reconnect if the user has already logged out (no token) or was
    // rejected by the server (4001).
    if (e.code !== 4001 && Auth.isLoggedIn()) {
      notifReconnectTimer = setTimeout(connectNotifications, 3000);
    }
  };
}

// Rooms

async function loadRooms() {
  const res = await API.get("/api/chat/rooms/");
  if (!res || !res.ok) return;
  rooms = await res.json();
  renderRoomLists();
}

function renderRoomLists() {
  const groupEl = document.getElementById("group-list");
  const dmEl    = document.getElementById("dm-list");
  groupEl.innerHTML = "";
  dmEl.innerHTML    = "";

  const groups  = rooms.filter(r => r.room_type === "group");
  const directs = rooms.filter(r => r.room_type === "direct");

  groups.forEach(r  => groupEl.appendChild(roomItem(r)));
  directs.forEach(r => dmEl.appendChild(roomItem(r)));

  if (!groups.length)  groupEl.innerHTML  = `<div style="padding:8px 10px;font-size:11px;color:var(--tm)">No group rooms yet</div>`;
  if (!directs.length) dmEl.innerHTML     = `<div style="padding:8px 10px;font-size:11px;color:var(--tm)">No DMs yet</div>`;
}

function roomItem(room) {
  const el = document.createElement("div");
  el.className = "room-item" + (currentRoom?.id === room.id ? " active" : "");
  el.dataset.roomId = room.id;

  const icon  = room.room_type === "group" ? "🏠" : "💬";
  const name  = roomDisplayName(room);
  const count = room.unread_count || 0;
  const badge = count > 0 && currentRoom?.id !== room.id
    ? `<span class="unread-badge" id="badge-${room.id}">${count > 99 ? "99+" : count}</span>`
    : `<span id="badge-${room.id}"></span>`;

  el.innerHTML = `
    <span class="ri-icon">${icon}</span>
    <span class="ri-name">${esc(name)}</span>
    ${badge}
  `;
  el.onclick = () => selectRoom(room);
  return el;
}

function roomDisplayName(room) {
  if (room.room_type === "group") return room.name || "Unnamed room";
  // DM: show the other participant's name
  const other = (room.members_detail || []).find(m => m.id !== meId);
  return other ? (other.display_name || other.username) : "Direct Message";
}

function amIAdmin(room) {
  return (room.members_detail || []).some(m => m.id === meId && m.is_admin);
}

// Select room & connect WebSocket

async function selectRoom(room) {
  if (activeRoomId === room.id) return;
  activeRoomId = room.id;
  currentRoom  = room;

  document.querySelectorAll(".room-item").forEach(el => {
    el.classList.toggle("active", el.dataset.roomId === room.id);
  });

  clearUnreadBadge(room.id);
  seenMsgIds.delete(room.id);   // reset dedup set so fresh load is clean
  renderChatShell(room);

  // If a socket for this room is already alive, reflect that in the UI immediately
  const existing = sockets.get(room.id);
  if (existing && existing.readyState === WebSocket.OPEN) {
    setWsBadge("connected");
    document.getElementById("send-btn")?.removeAttribute("disabled");
  }

  await loadHistory(room.id);
  await refreshCurrentRoom();
  updateReadReceipts();
  connectWS(room.id);

  // Mark room as read (fire-and-forget)
  API.post(`/api/chat/rooms/${room.id}/read/`, {}).then(res => {
    if (res && res.ok) {
      const me = (currentRoom?.members_detail || []).find(m => m.id === meId);
      if (me) me.last_read_at = new Date().toISOString();
    }
  });
}

function clearUnreadBadge(roomId) {
  const badge = document.getElementById(`badge-${roomId}`);
  if (badge) badge.outerHTML = `<span id="badge-${roomId}"></span>`;
  // Update room object too so re-renders don't show stale count
  const room = rooms.find(r => r.id === roomId);
  if (room) room.unread_count = 0;
}

function renderChatShell(room) {
  const main = document.getElementById("main-panel");
  const name = roomDisplayName(room);
  const manageBtn = room.room_type === "group"
    ? `<button class="icon-btn" style="margin-left:4px" title="Manage room" onclick="openManageRoom()">⚙</button>`
    : "";

  main.innerHTML = `
    <div class="chat-header">
      <span style="font-size:18px">${room.room_type === "group" ? "🏠" : "💬"}</span>
      <h3>${esc(name)}</h3>
      ${manageBtn}
      <span class="ws-status connecting" id="ws-badge">● connecting</span>
    </div>
    <div class="messages" id="messages"></div>
    <button class="new-msg-bar" id="new-msg-bar" onclick="jumpToLatest()"></button>
    <div class="reply-bar" id="reply-bar" style="display:none">
      <div class="reply-bar-inner">
        <span class="reply-bar-label">Replying to <strong id="reply-bar-name"></strong></span>
        <span class="reply-bar-preview" id="reply-bar-preview"></span>
      </div>
      <button class="reply-bar-cancel" onclick="cancelReply()" title="Cancel reply">✕</button>
    </div>
    <div class="composer">
      <textarea id="composer-input" rows="1" placeholder="Message ${esc(name)}…"
        oninput="autoResize(this)" onkeydown="composerKey(event)"></textarea>
      <button class="send-btn" id="send-btn" onclick="sendMessage()" disabled title="Send">➤</button>
    </div>
  `;
  newMsgCount = 0;
  replyingTo = null;
  document.getElementById("messages").addEventListener("scroll", onMessagesScroll);
  document.getElementById("composer-input").focus();
}

// Message history

async function loadHistory(roomId) {
  const container = document.getElementById("messages");
  if (!container) return;

  const res = await API.get(`/api/chat/rooms/${roomId}/messages/`);
  if (!res || !res.ok) return;

  const msgs = await res.json();

  // Only update the view if this room is still active
  if (roomId !== activeRoomId) return;

  container.innerHTML = "";

  if (!msgs.length) {
    const room = rooms.find(r => r.id === roomId) || currentRoom;
    if (room && room.room_type === "group" && (room.member_count || 0) <= 1) {
      container.innerHTML = `
        <div class="no-members-state">
          <div class="big">👥</div>
          <p>This group has no members yet.<br>Add people to start chatting!</p>
          <button class="btn-add-members" onclick="openManageRoom('add')">+ Add Members</button>
        </div>`;
    } else {
      container.innerHTML = `
        <div class="empty-state">
          <div class="big">👋</div>
          <p>No messages yet. Say hello!</p>
        </div>`;
    }
    seenMsgIds.set(roomId, new Set());
    return;
  }

  const ids = new Set();
  msgs.forEach(m => { appendMessage(m); ids.add(m.id); });
  seenMsgIds.set(roomId, ids);
  scrollBottom();
  updateReadReceipts();
}

// WebSocket
// One socket per room, kept alive across room switches.

function connectWS(roomId) {
  // Reuse if already open or connecting
  const existing = sockets.get(roomId);
  if (existing) {
    if (existing.readyState === WebSocket.OPEN) {
      if (activeRoomId === roomId) setWsBadge("connected");
      return;
    }
    if (existing.readyState === WebSocket.CONNECTING) {
      if (activeRoomId === roomId) setWsBadge("connecting");
      return;
    }
    // CLOSING or CLOSED — fall through and create a new one
  }

  clearTimeout(reconnectTimers.get(roomId));
  reconnectTimers.delete(roomId);

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws    = new WebSocket(`${proto}://${location.host}/ws/chat/${roomId}/?token=${Auth.access}`);
  sockets.set(roomId, ws);

  if (activeRoomId === roomId) setWsBadge("connecting");

  ws.onopen = () => {
    if (activeRoomId === roomId) {
      setWsBadge("connected");
      document.getElementById("send-btn")?.removeAttribute("disabled");
    }
  };

  ws.onmessage = ({ data }) => {
    let frame;
    try { frame = JSON.parse(data); } catch { return; }
    handleFrame(frame, roomId);
  };

  ws.onclose = (e) => {
    sockets.delete(roomId);
    if (activeRoomId === roomId) {
      setWsBadge("disconnected");
      document.getElementById("send-btn")?.setAttribute("disabled", "");
    }
    if (e.code === 4001 || e.code === 4003) { logout(); return; }
    // Reconnect — room socket stays alive for all open rooms
    const t = setTimeout(() => connectWS(roomId), 3000);
    reconnectTimers.set(roomId, t);
  };

  ws.onerror = () => {
    if (activeRoomId === roomId) setWsBadge("disconnected");
  };
}

function handleFrame(frame, roomId) {
  const isActive = roomId === activeRoomId;

  switch (frame.type) {
    case "message":
      if (isActive) {
        appendNewMessage(roomId, frame);   // deduped
        if (frame.message_type === "system") refreshCurrentRoom().then(updateReadReceipts);
      } else {
        incrementBadge(roomId);
      }
      break;
    case "user_join":
      if (isActive) appendSystemMsg(`${frame.user.display_name || frame.user.username} joined the group`);
      break;
    case "user_leave":
      if (isActive) appendSystemMsg(`${frame.user.display_name || frame.user.username} left`);
      break;
    case "read_receipt":
      // Always update members_detail so the data is correct when room becomes active
      const room = rooms.find(r => r.id === roomId);
      if (room) {
        const member = (room.members_detail || []).find(m => m.id === frame.user_id);
        if (member) member.last_read_at = frame.read_at;
      }
      if (isActive) updateReadReceipts();
      break;
    case "error":
      if (isActive) console.warn("WS error:", frame.code, frame.detail);
      break;
  }
}

// Increment the sidebar unread badge for a room
function incrementBadge(roomId) {
  const room = rooms.find(r => r.id === roomId);
  if (!room) return;
  room.unread_count = (room.unread_count || 0) + 1;
  const badge = document.getElementById(`badge-${roomId}`);
  if (!badge) return;
  const count = room.unread_count;
  badge.textContent  = count > 99 ? "99+" : String(count);
  badge.className    = "unread-badge";
}

/**
 * Append a new real-time message, deduplicating so it doesn't matter if both
 * the room WS and the notification WS deliver the same frame.
 */
function appendNewMessage(roomId, payload) {
  const msgId = payload.message_id || payload.id;
  if (!msgId) return;

  const ids = seenMsgIds.get(roomId) || new Set();
  if (ids.has(msgId)) return;
  ids.add(msgId);
  seenMsgIds.set(roomId, ids);

  appendMessage(payload);
  const isOwn = (payload.sender?.id ?? payload.sender_id) === meId;
  if (isOwn) scrollBottom(); else notifyNewMessage();
  API.post(`/api/chat/rooms/${roomId}/read/`, {});
}



// New-messages scroll indicator

function isAtBottom() {
  const el = document.getElementById("messages");
  return el ? (el.scrollHeight - el.scrollTop - el.clientHeight < 60) : true;
}

function notifyNewMessage() {
  if (isAtBottom()) {
    scrollBottom();
  } else {
    newMsgCount++;
    const bar = document.getElementById("new-msg-bar");
    if (bar) {
      bar.textContent = `↓ ${newMsgCount} new message${newMsgCount > 1 ? "s" : ""}`;
      bar.style.display = "block";
    }
  }
}

function jumpToLatest() {
  newMsgCount = 0;
  const bar = document.getElementById("new-msg-bar");
  if (bar) bar.style.display = "none";
  scrollBottom();
}

function onMessagesScroll() {
  if (isAtBottom() && newMsgCount > 0) jumpToLatest();
}

// Send

function sendMessage() {
  const input = document.getElementById("composer-input");
  if (!input) return;
  const content = input.value.trim();
  const ws = activeRoomId ? sockets.get(activeRoomId) : null;
  if (!content || !ws || ws.readyState !== WebSocket.OPEN) return;

  const frame = { type: "message", content };
  if (replyingTo) frame.reply_to_id = replyingTo.id;

  ws.send(JSON.stringify(frame));
  input.value = "";
  autoResize(input);
  cancelReply();
}

function startReply(msgId, senderName, content) {
  replyingTo = { id: msgId, senderName, content };
  const bar = document.getElementById("reply-bar");
  if (bar) {
    document.getElementById("reply-bar-name").textContent = senderName;
    document.getElementById("reply-bar-preview").textContent = content.length > 80 ? content.slice(0, 80) + "…" : content;
    bar.style.display = "flex";
  }
  document.getElementById("composer-input")?.focus();
}

function cancelReply() {
  replyingTo = null;
  const bar = document.getElementById("reply-bar");
  if (bar) bar.style.display = "none";
}

// Read / delivered receipt helpers

/**
 * Build the receipt HTML for an own message.
 * DM  → ✓ (not read) or ✓✓ (read)
 * Group → ✓ N read / M  (N = read count, M = total others = "delivered")
 */
function buildReceiptHtml(createdAt) {
  const others = (currentRoom?.members_detail || []).filter(m => m.id !== meId);
  if (!others.length) return `<span class="read-receipt" data-ts="${createdAt}">✓</span>`;

  const readCount = others.filter(m => m.last_read_at && m.last_read_at >= createdAt).length;
  const total     = others.length;
  const allRead   = readCount === total;

  if (currentRoom.room_type === "direct" || allRead) {
    // DM, or all members have read → show ✓✓
    return `<span class="read-receipt${allRead ? " read" : ""}" data-ts="${createdAt}">${allRead ? "✓✓" : "✓"}</span>`;
  }
  // Group — partial read: "✓ N read"
  return `<span class="read-receipt${readCount > 0 ? " read" : ""}" data-ts="${createdAt}">✓ ${readCount} read</span>`;
}

/** Re-evaluate every receipt span after a read_receipt WS event. */
function updateReadReceipts() {
  if (!currentRoom) return;
  const others = (currentRoom.members_detail || []).filter(m => m.id !== meId);
  if (!others.length) return;
  const isDM = currentRoom.room_type === "direct";

  document.querySelectorAll(".read-receipt[data-ts]").forEach(el => {
    const ts        = el.dataset.ts;
    const readCount = others.filter(m => m.last_read_at && m.last_read_at >= ts).length;
    const total     = others.length;
    const allRead   = readCount === total;

    el.classList.toggle("read", allRead || (isDM && readCount > 0));
    if (isDM || allRead) {
      el.textContent = allRead || readCount > 0 ? "✓✓" : "✓";
    } else {
      el.textContent = readCount > 0 ? `✓ ${readCount} read` : "✓";
    }
  });
}

// Message rendering

function appendMessage(msg) {
  if (msg.message_type === "system") {
    appendSystemMsg(msg.content);
    return;
  }
  if (msg.message_type === "invite") {
    appendInviteMessage(msg);
    return;
  }

  const container = document.getElementById("messages");
  if (!container) return;

  const empty = container.querySelector(".empty-state");
  if (empty) empty.remove();

  const isOwn = msg.sender?.id === meId;
  const name  = msg.sender?.display_name || msg.sender?.username || "Unknown";
  const ts    = formatTime(msg.created_at);
  const initials = name.slice(0, 2).toUpperCase();

  const el = document.createElement("div");
  const msgId = msg.message_id || msg.id;
  el.className = `msg${isOwn ? " own" : ""}`;
  el.dataset.msgId = msgId;

  const receiptHtml = isOwn ? buildReceiptHtml(msg.created_at) : "";

  // Reply quote block (shown above bubble if this message is a reply)
  let replyQuoteHtml = "";
  if (msg.reply_to) {
    const r = msg.reply_to;
    const rName = r.sender?.display_name || r.sender?.username || "Unknown";
    const rPreview = (r.content || "").length > 80 ? r.content.slice(0, 80) + "…" : (r.content || "");
    const rId = r.id || "";
    replyQuoteHtml = `
      <div class="reply-quote" onclick="scrollToMessage('${rId}')" title="Jump to original">
        <span class="reply-quote-name">${esc(rName)}</span>
        <span class="reply-quote-text">${esc(rPreview)}</span>
      </div>`;
  }

  el.innerHTML = `
    <div class="avatar">${initials}</div>
    <div class="bubble-wrap">
      ${!isOwn ? `<div class="sender-name">${esc(name)}</div>` : ""}
      ${replyQuoteHtml}
      <div class="bubble">${esc(msg.content)}</div>
      <div class="ts">${ts}${receiptHtml}</div>
    </div>
    <button class="reply-btn" title="Reply" onclick="startReply('${msgId}', '${esc(name)}', '${esc((msg.content || "").replace(/'/g, "\\'"))}')">↩</button>
  `;
  container.appendChild(el);
}

function scrollToMessage(msgId) {
  if (!msgId) return;
  const el = document.querySelector(`.msg[data-msg-id="${msgId}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("msg-highlight");
  setTimeout(() => el.classList.remove("msg-highlight"), 1500);
}

function appendInviteMessage(msg) {
  const container = document.getElementById("messages");
  if (!container) return;

  const empty = container.querySelector(".empty-state");
  if (empty) empty.remove();

  const meta     = msg.metadata || {};
  const isOwn    = msg.sender?.id === meId;
  const invStatus = meta.invite_status || "pending";
  const ts       = formatTime(msg.created_at);

  let actionsHtml = "";
  if (!isOwn) {
    if (invStatus === "pending") {
      actionsHtml = `
        <div class="invite-actions" id="invite-actions-${meta.invite_id}">
          <button class="btn-invite-join"
            onclick="respondInvite('${meta.invite_id}', 'accept')">✓ Join</button>
          <button class="btn-invite-decline"
            onclick="respondInvite('${meta.invite_id}', 'decline')">✗ Decline</button>
        </div>`;
    } else {
      const label = invStatus === "accepted" ? "✓ Joined" : "✗ Declined";
      actionsHtml = `<div class="invite-status-text ${invStatus}">${label}</div>`;
    }
  }

  const el = document.createElement("div");
  el.className = `msg${isOwn ? " own" : ""}`;
  el.innerHTML = `
    <div class="avatar" style="background:var(--yellow);font-size:16px">💌</div>
    <div class="bubble-wrap">
      ${!isOwn ? `<div class="sender-name">${esc(msg.sender?.display_name || msg.sender?.username || "")}</div>` : ""}
      <div class="invite-bubble">
        <div class="invite-icon">🏠</div>
        <div class="invite-content">
          <div class="invite-label">${isOwn ? "Invite sent" : "Group invite"}</div>
          <div class="invite-group-name">${esc(meta.group_name || "Group")}</div>
          ${actionsHtml}
        </div>
      </div>
      <div class="ts">${ts}</div>
    </div>
  `;
  container.appendChild(el);
}

async function respondInvite(inviteId, action) {
  const res = await API.post(`/api/chat/invites/${inviteId}/respond/`, { action });
  if (!res) return;
  const data = await res.json();

  if (!res.ok) {
    // Invite already responded to (stale UI) — reload to show the real status
    await loadHistory(activeRoomId);
    return;
  }

  const newStatus = action === "accept" ? "accepted" : "declined";

  // Update the action buttons in-place
  const actionsEl = document.getElementById(`invite-actions-${inviteId}`);
  if (actionsEl) {
    const label = action === "accept" ? "✓ Joined" : "✗ Declined";
    actionsEl.outerHTML = `<div class="invite-status-text ${newStatus}">${label}</div>`;
  }

  if (action === "accept" && data.room) {
    await loadRooms();
    const room = rooms.find(r => r.id === data.room.id);
    if (room) selectRoom(room);
  }
}

function appendSystemMsg(text) {
  const container = document.getElementById("messages");
  if (!container) return;
  const empty = container.querySelector(".empty-state, .no-members-state");
  if (empty) empty.remove();
  const el = document.createElement("div");
  el.className = "system-msg";
  el.textContent = text;
  container.appendChild(el);
  scrollBottom();
}

function setWsBadge(state) {
  const badge = document.getElementById("ws-badge");
  if (!badge) return;
  badge.className = `ws-status ${state}`;
  const labels = { connected: "● connected", connecting: "● connecting", disconnected: "● disconnected" };
  badge.textContent = labels[state] || state;
}

// Group creation

function openNewGroup() {
  document.getElementById("ng-name").value = "";
  document.getElementById("ng-error").textContent = "";
  openModal("modal-group");
}

async function createGroup() {
  const name  = document.getElementById("ng-name").value.trim();
  const errEl = document.getElementById("ng-error");
  errEl.textContent = "";

  if (!name) { errEl.textContent = "Room name is required."; return; }

  const res = await API.post("/api/chat/rooms/", { name });
  if (!res) return;
  const data = await res.json();
  if (!res.ok) { errEl.textContent = data.name?.[0] || JSON.stringify(data); return; }

  closeModal("modal-group");
  await loadRooms();
  const newRoom = rooms.find(r => r.id === data.id);
  if (newRoom) selectRoom(newRoom);
}

// DM creation

function openNewDM() {
  document.getElementById("dm-username").value = "";
  document.getElementById("dm-error").textContent = "";
  openModal("modal-dm");
}

async function createDM() {
  const username = document.getElementById("dm-username").value.trim();
  const errEl    = document.getElementById("dm-error");
  errEl.textContent = "";

  if (!username) { errEl.textContent = "Enter a username."; return; }

  const user = await resolveUsername(username);
  if (!user) {
    errEl.textContent = `User "${username}" not found.`;
    return;
  }

  const res = await API.post("/api/chat/rooms/direct/", { user_id: user.id });
  if (!res) return;
  const data = await res.json();
  if (!res.ok) { errEl.textContent = data.detail || JSON.stringify(data); return; }

  closeModal("modal-dm");
  await loadRooms();
  const newRoom = rooms.find(r => r.id === data.id);
  if (newRoom) selectRoom(newRoom);
}

async function resolveUsername(username) {
  const res = await API.get(`/api/auth/users/?search=${encodeURIComponent(username)}`);
  if (!res || !res.ok) return null;
  const results = await res.json();
  return results.find(u => u.username.toLowerCase() === username.toLowerCase()) || null;
}

// Group management modal

function openManageRoom(initialTab = "members") {
  if (!currentRoom || currentRoom.room_type !== "group") return;
  document.getElementById("manage-title").textContent = `Manage: ${currentRoom.name}`;
  document.getElementById("add-member-search").value = "";
  document.getElementById("add-member-results").innerHTML = "";

  // Only admins see the Invites and Add Member tabs
  const isAdmin = amIAdmin(currentRoom);
  const tabs = document.querySelectorAll(".mtab");
  // tabs[0]=Members, tabs[1]=Invites, tabs[2]=Add Member
  tabs[1].style.display = isAdmin ? "" : "none";
  tabs[2].style.display = isAdmin ? "" : "none";

  openModal("modal-manage");
  // If requested tab requires admin but user is not admin, fall back to members
  const tab = (initialTab === "add" || initialTab === "invites") && !isAdmin ? "members" : initialTab;
  showManageTab(tab);
}

function showManageTab(tab) {
  ["members", "invites", "add"].forEach((t, i) => {
    document.getElementById(`mtab-${t}`).classList.toggle("hidden", t !== tab);
    document.querySelectorAll(".mtab")[i].classList.toggle("active", t === tab);
  });
  if (tab === "members") loadManageMembers();
  if (tab === "invites") loadManageInvites();
  if (tab === "add")     searchAddMember();
}

async function loadManageMembers() {
  const res = await API.get(`/api/chat/rooms/${currentRoom.id}/members/`);
  if (!res || !res.ok) return;
  const members = await res.json();

  const iAmAdmin = members.some(m => m.user.id === meId && m.is_admin);
  const el = document.getElementById("manage-members-list");
  el.innerHTML = "";

  members.forEach(m => {
    const row = document.createElement("div");
    row.className = "manage-member-row";
    const initials = (m.user.display_name || m.user.username).slice(0, 2).toUpperCase();
    const adminControls = iAmAdmin && m.user.id !== meId ? `
      <div class="mm-actions">
        <button class="btn-sm ${m.is_admin ? "btn-demote" : "btn-promote"}"
          onclick="toggleAdmin(${m.user.id})"
          ${m.is_admin ? "Remove admin" : "Make admin"}
        </button>
        <button class="btn-sm btn-remove-member" onclick="removeMember(${m.user.id})">
          Remove
        </button>
      </div>
    ` : "";

    row.innerHTML = `
      <div class="mm-user">
        <div class="avatar" style="width:28px;height:28px;font-size:11px">${initials}</div>
        <div>
          <div class="mm-name">${esc(m.user.display_name || m.user.username)}</div>
          <div class="mm-handle">@${esc(m.user.username)}</div>
        </div>
        ${m.is_admin ? '<span class="admin-badge">Admin</span>' : ""}
      </div>
      ${adminControls}
    `;
    el.appendChild(row);
  });
}

async function loadManageInvites() {
  const res = await API.get(`/api/chat/rooms/${currentRoom.id}/invites/`);
  const el = document.getElementById("manage-invites-list");

  if (!res || !res.ok) {
    el.innerHTML = `<div class="mm-empty">Admin access required to view invites.</div>`;
    return;
  }
  const invites = await res.json();
  el.innerHTML = "";
  if (!invites.length) {
    el.innerHTML = `<div class="mm-empty">No invites yet.</div>`;
    return;
  }

  invites.forEach(inv => {
    const row = document.createElement("div");
    row.className = "manage-invite-row";
    const initials = (inv.invitee.display_name || inv.invitee.username).slice(0, 2).toUpperCase();
    row.innerHTML = `
      <div class="mm-user">
        <div class="avatar" style="width:28px;height:28px;font-size:11px">${initials}</div>
        <div>
          <div class="mm-name">${esc(inv.invitee.display_name || inv.invitee.username)}</div>
          <div class="mm-handle">@${esc(inv.invitee.username)}</div>
        </div>
      </div>
      <span class="invite-pill ${inv.status}">${inv.status}</span>
    `;
    el.appendChild(row);
  });
}

async function toggleAdmin(userId) {
  const res = await API.patch(`/api/chat/rooms/${currentRoom.id}/members/${userId}/`);
  if (!res || !res.ok) return;

  // Reload the room so members_detail (and is_admin flags) are fresh.
  // This is what makes newly promoted members see the admin tabs immediately
  // when they close and reopen the manage modal.
  await refreshCurrentRoom();
  loadManageMembers();
}

async function refreshCurrentRoom() {
  if (!currentRoom) return;
  const res = await API.get(`/api/chat/rooms/${currentRoom.id}/`);
  if (!res || !res.ok) return;
  const fresh = await res.json();

  // Update the rooms array and currentRoom reference
  const idx = rooms.findIndex(r => r.id === fresh.id);
  if (idx !== -1) rooms[idx] = fresh;
  currentRoom = fresh;

  // Re-evaluate admin tab visibility while modal is open
  const isAdmin = amIAdmin(currentRoom);
  const tabs = document.querySelectorAll(".mtab");
  if (tabs.length > 2) {
    tabs[1].style.display = isAdmin ? "" : "none";
    tabs[2].style.display = isAdmin ? "" : "none";
    if (!isAdmin) showManageTab("members");
  }
}

async function removeMember(userId) {
  if (!confirm("Remove this member from the group?")) return;
  const res = await API.delete(`/api/chat/rooms/${currentRoom.id}/members/${userId}/`);
  if (res && (res.ok || res.status === 204)) loadManageMembers();
}

async function searchAddMember() {
  const q = document.getElementById("add-member-search").value.trim();
  const resultsEl = document.getElementById("add-member-results");

  const url = q ? `/api/auth/users/?search=${encodeURIComponent(q)}` : "/api/auth/users/";
  const res = await API.get(url);
  if (!res || !res.ok) return;
  const allUsers = await res.json();

  // Exclude users who are already members of this room
  const existingIds = new Set((currentRoom?.members_detail || []).map(m => m.id));
  const users = allUsers.filter(u => !existingIds.has(u.id));

  resultsEl.innerHTML = "";
  if (!users.length) {
    resultsEl.innerHTML = `<div class="mm-empty">No users found.</div>`;
    return;
  }

  users.forEach(u => {
    const row = document.createElement("div");
    row.className = "add-member-row";
    row.innerHTML = `
      <span style="font-size:13px;color:var(--tb)">
        ${esc(u.display_name || u.username)}
        <span style="color:var(--tm);font-size:11px">@${esc(u.username)}</span>
      </span>
      <button class="btn-sm btn-invite-send" id="invite-btn-${u.id}"
        onclick="inviteToGroup(${u.id}, 'invite-btn-${u.id}')">Invite</button>
    `;
    resultsEl.appendChild(row);
  });
}

async function inviteToGroup(userId, btnId) {
  const btn = document.getElementById(btnId);
  if (btn) { btn.disabled = true; btn.textContent = "Sending…"; }

  const res = await API.post(`/api/chat/rooms/${currentRoom.id}/members/`, { user_id: userId });
  if (!res) { if (btn) { btn.disabled = false; btn.textContent = "Invite"; } return; }

  if (res.ok || res.status === 200 || res.status === 201) {
    if (btn) { btn.textContent = "Sent ✓"; }
  } else {
    const data = await res.json();
    if (btn) { btn.disabled = false; btn.textContent = data.detail || data.user_id?.[0] || "Error"; }
  }
}

// Utilities

function openModal(id)  { document.getElementById(id).classList.add("show"); }
function closeModal(id) { document.getElementById(id).classList.remove("show"); }

function logout() {
  // Close notification socket first — must happen before Auth.clear() so the
  // onclose handler sees isLoggedIn()=false and skips the reconnect timer.
  clearTimeout(notifReconnectTimer);
  if (notifSocket) { notifSocket.close(); notifSocket = null; }

  // Close all room sockets
  reconnectTimers.forEach(t => clearTimeout(t));
  reconnectTimers.clear();
  sockets.forEach(ws => ws.close());
  sockets.clear();

  Auth.clear();
  window.location.href = "/accounts/login/";
}

function scrollBottom() {
  const el = document.getElementById("messages");
  if (el) el.scrollTop = el.scrollHeight;
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 120) + "px";
}

function composerKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Close modals on backdrop click
document.querySelectorAll(".modal-overlay").forEach(overlay => {
  overlay.addEventListener("click", e => {
    if (e.target === overlay) overlay.classList.remove("show");
  });
});

// Start
boot();
