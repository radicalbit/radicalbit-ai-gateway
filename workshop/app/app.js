// Put a suggestion in the message box.
function fillMessage(text) {
  const input = document.getElementById('msg');
  if (!input || input.disabled) return;
  input.value = text;
  input.focus();
}

function scrollChat() {
  const messages = document.getElementById('messages');
  if (messages) messages.scrollTop = messages.scrollHeight;
}

// Model answers are Markdown. Parse it, then strip any HTML the model wrote.
// Images are dropped too: an image URL in an answer would make the browser
// call any address the model chose (a way to leak data from a prompt injection).
// Falls back to plain text if the libraries did not load (offline).
const PURIFY = { FORBID_TAGS: ['img', 'picture', 'source', 'video', 'audio', 'iframe'] };

// Show any HTML the model writes as plain text, never as markup. This also
// keeps redaction placeholders like <CREDIT_CARD> or <PERSON> visible, which
// the sanitizer would otherwise drop as unknown tags.
function escapeHtml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
if (window.marked) {
  marked.use({ renderer: { html({ text }) { return escapeHtml(text); } } });
}

function renderMarkdown(el, text) {
  if (window.marked && window.DOMPurify) {
    el.innerHTML = DOMPurify.sanitize(marked.parse(text, { breaks: true }), PURIFY);
  } else {
    el.textContent = text;
  }
}

// Bot bubbles arrive from the server as escaped plain text: render them once.
function renderBubbles() {
  document.querySelectorAll('.bubble.md:not([data-rendered])').forEach((el) => {
    if (el.id === 'stream-bubble') return;
    el.dataset.rendered = '1';
    renderMarkdown(el, el.textContent);
  });
}

// Reload both panels from the server (final verdict, history, buttons).
function refreshWorkspace() {
  htmx.ajax('GET', '/workspace', { target: '#workspace', swap: 'outerHTML' });
}

// An empty bot bubble means an answer is on its way: stream it in.
function startStream() {
  const row = document.querySelector('.is-streaming[data-stream]');
  if (!row || row.dataset.started) return;
  row.dataset.started = '1';
  const bubble = row.querySelector('.bubble');
  let text = '';
  const source = new EventSource(row.dataset.stream);
  source.addEventListener('token', (e) => {
    text += JSON.parse(e.data);
    renderMarkdown(bubble, text);
    scrollChat();
  });
  const finish = () => { source.close(); refreshWorkspace(); };
  source.addEventListener('done', finish);
  source.onerror = finish;
}

// Keep the raw request and response boxes open across turns once opened.
function rememberBoxes() {
  document.querySelectorAll('details.raw[id]').forEach((box) => {
    try {
      if (localStorage.getItem(box.id) === 'open') box.open = true;
    } catch (e) { /* storage blocked: boxes start closed */ }
    if (box.dataset.watched) return;
    box.dataset.watched = '1';
    box.addEventListener('toggle', () => {
      try { localStorage.setItem(box.id, box.open ? 'open' : 'closed'); } catch (e) {}
    });
  });
}

// After each update: render answers, start a pending stream, show the newest
// message, focus the box.
function settle() {
  rememberBoxes();
  renderBubbles();
  startStream();
  scrollChat();
  const input = document.getElementById('msg');
  if (input && !input.disabled) input.focus();
}

document.addEventListener('DOMContentLoaded', settle);
document.addEventListener('htmx:afterSettle', settle);
