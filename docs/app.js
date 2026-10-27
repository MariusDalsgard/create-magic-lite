const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const SVG_NS = 'http://www.w3.org/2000/svg';
const icons = {
  home: ['m3 10 9-7 9 7', 'M5 9v12h14V9', 'M9 21v-8h6v8'],
  spark: ['m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z', 'M20 2v4M18 4h4'],
  compass: ['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0', 'm16 8-3 5-5 3 3-5Z'],
  box: ['m12 3 9 5v9l-9 5-9-5V8Z', 'm3 8 9 5 9-5M12 13v9M7.5 5.5l9 5'],
  clock: ['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0', 'M12 7v5l3 2'],
  'arrow-right': ['M4 12h16m-6-6 6 6-6 6'],
  'arrow-up-right': ['M6 18 18 6M6 6h12v12'],
  leaf: ['M20 3c-8-1-15 3-15 10a6 6 0 0 0 11 3c3-4 4-9 4-13Z', 'M4 21 15 10'],
  server: ['M4 3h16v7H4ZM4 14h16v7H4ZM8 6.5h.01M8 17.5h.01M13 6.5h4M13 17.5h4'],
  copy: ['M9 9h11v12H9Z', 'M15 9V3H3v12h6'],
  play: ['m8 4 12 8-12 8Z'],
  shield: ['m12 3 8 3v6c0 4-3 7-8 10-5-3-8-6-8-10V6Z', 'm8 12 3 3 5-6'],
  heart: ['M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z'],
  lightbulb: ['M9 18h6M9 22h6', 'M8 14a7 7 0 1 1 8 0c-1 1-1 2-1 4H9c0-2 0-3-1-4Z'],
  lock: ['M5 10h14v11H5Z', 'M8 10V6a4 4 0 0 1 8 0v4M12 14v3'],
  mountain: ['m2 21 7-15 5 9 3-5 5 11Z', 'm6 12 3 2 3-2'],
  sun: ['M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0', 'M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5'],
  layers: ['m12 2 10 5-10 5L2 7Z', 'm2 12 10 5 10-5M2 17l10 5 10-5'],
  info: ['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0', 'M12 11v6M12 7h.01'],
  calendar: ['M3 5h18v17H3ZM3 10h18M7 2v6M17 2v6M7 14h2M15 14h2M7 18h2'],
  image: ['M3 3h18v18H3Z', 'm3 16 6-6 5 6 3-3 4 4M16 7h.01'],
  map: ['m3 5 6-3 6 3 6-3v17l-6 3-6-3-6 3ZM9 2v17M15 5v17'],
  x: ['m6 6 12 12M6 18 18 6'],
  'chevron-up': ['m6 15 6-6 6 6'],
};

function makeIcon(name) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.6', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' }).forEach(([key, value]) => svg.setAttribute(key, value));
  (icons[name] || icons.box).forEach(d => { const path = document.createElementNS(SVG_NS, 'path'); path.setAttribute('d', d); svg.append(path); });
  return svg;
}
$$('[data-icon]').forEach(element => element.replaceChildren(makeIcon(element.dataset.icon)));

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

let configuration = { apiBase: '', serverAddress: '83.88.146.132:25566', packShareUrl: null, githubRepoUrl: '' };
let session = null;
let available = null;
let currentStatus = null;
let suggestions = [];
let statusBusy = false;
let startBusy = false;
let runtimeBusy = false;
let runtimeLastChecked = 0;
let previewSequence = 0;
let previewTimer;
let toastTimer;
const STORAGE_KEY = 'create-magic-friend-session';
const pages = { oversigt: 'Oversigt', modforslag: 'Modforslag', 'kom-i-gang': 'Kom i gang', modpakken: 'Modpakken', nyt: 'Nyt på serveren' };

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
}

function saveSession(value) {
  session = value;
  try {
    if (value) sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ ...value, apiBase: configuration.apiBase }));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch { /* The session remains usable when browser storage is unavailable. */ }
  renderAccount();
}

function renderAccount() {
  $('#account-name').textContent = session ? session.name : 'Du er gæst';
  $('#account-hint').textContent = session ? 'Venneadgang er aktiv' : 'Log ind med vennekoden';
  $('#account-avatar').textContent = session ? [...session.name][0].toLocaleUpperCase('da-DK') : '?';
  $('#suggestions-login').hidden = !!session;
  $('#suggestion-fields').disabled = !session || !available;
  if (!session) {
    suggestions = [];
    renderSuggestions();
  }
}

function setFeedback(target, message, error = false) {
  target.textContent = message;
  target.classList.toggle('error', error);
}

function apiBaseFrom(value) {
  try {
    const url = new URL(value);
    if (url.username || url.password || url.search || url.hash) return '';
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) return '';
    return url.href.replace(/\/$/, '');
  } catch { return ''; }
}

function safeLink(value, hosts, pathPrefix = '/') {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && hosts.includes(url.hostname.toLowerCase()) && url.pathname.startsWith(pathPrefix) ? url.href : null;
  } catch { return null; }
}

function modLink(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return null;
    const modrinth = url.hostname === 'modrinth.com' && /^\/mod\/[A-Za-z0-9_-]+\/?$/.test(url.pathname);
    const curseforge = ['www.curseforge.com', 'curseforge.com'].includes(url.hostname) && /^\/minecraft\/mc-mods\/[A-Za-z0-9_-]+\/?$/.test(url.pathname);
    return modrinth || curseforge ? `${url.origin}${url.pathname.replace(/\/$/, '')}` : null;
  } catch { return null; }
}

function imageLink(value) {
  return safeLink(value, ['cdn.modrinth.com', 'media.forgecdn.net', 'mediafilez.forgecdn.net', 'edge.forgecdn.net', 'www.curseforge.com']);
}

async function api(path, body, authenticated = true) {
  if (!configuration.apiBase) throw new Error('Forbindelsen til computeren er ikke aktiveret endnu.');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 18000);
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (authenticated && session) headers.Authorization = `Bearer ${session.token}`;
  try {
    const response = await fetch(configuration.apiBase + path, { method: body === undefined ? 'GET' : 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal, credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && authenticated) {
        saveSession(null);
        renderStatus(null);
        throw new Error('Din adgang er udløbet. Log ind med vennekoden igen.');
      }
      if (response.status === 429) throw new Error('Lidt for mange forsøg. Vent et øjeblik, og prøv igen.');
      if (response.status === 401) throw new Error('Navn eller vennekode blev ikke godkendt. Prøv igen.');
      throw new Error(typeof data.message === 'string' ? data.message.slice(0, 350) : 'Handlingen kunne ikke gennemføres. Prøv igen.');
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError' || error instanceof TypeError) {
      // The tunnel address can change when the PC reconnects. Never repeat a
      // mutation automatically; load the new public configuration for next use.
      void refreshConfiguration();
      throw new Error('Kan ikke nå Marius\' computer lige nu. Prøv igen om lidt.');
    }
    throw error;
  } finally { clearTimeout(timeout); }
}

function renderStatus(status, problem = '') {
  currentStatus = status;
  const pill = $('#status-pill');
  let label = 'Afventer forbindelse';
  let style = 'pending';
  let button = 'Forbindelse afventer';
  let help = 'Siden er klar. Forbindelsen til Marius\' computer er endnu ikke aktiveret.';
  let enabled = false;
  if (configuration.apiBase && available === null) {
    label = 'Henter status';
    button = 'Kontrollerer forbindelsen …';
    help = 'Kontakter Marius\' computer. Det tager normalt et øjeblik.';
  } else if (configuration.apiBase && available === false) {
    label = 'Ingen forbindelse';
    button = 'Kan ikke nå computeren';
    help = problem || 'Marius\' computer og forbindelsen til panelet skal være tændt. Vi prøver automatisk igen.';
  } else if (available && !session) {
    label = 'Log ind for status';
    button = 'Log ind for at starte';
    help = 'Brug vennekoden fra Marius for at se status og starte serveren.';
    enabled = true;
  } else if (status) {
    const state = status.state;
    if (state === 'online') {
      label = 'Online'; style = 'online'; button = 'Serveren er klar';
      help = 'Hop ind i Minecraft, og brug serveradressen ovenfor.';
    } else if (state === 'starting') {
      label = 'Starter'; style = 'starting'; button = 'Serveren starter …';
      help = 'Mods og verden indlæses. Status opdateres automatisk.';
    } else if (state === 'stopping') {
      label = 'Gemmer verden'; style = 'starting'; button = 'Vent på serveren';
      help = 'Verdenen gemmes lige nu. Vent, til serveren er klar til start.';
    } else {
      label = 'Offline'; style = 'offline'; button = 'Start serveren';
      enabled = status.can_start === true;
      help = enabled ? 'Start den her — det kan tage lidt tid at indlæse alle mods.' : 'Serveren er offline. Den kan snart startes igen; status opdateres automatisk.';
    }
  } else if (available && session) {
    label = 'Henter status'; button = 'Henter status …';
    help = 'Kontrollerer, om Minecraft-serveren er klar.';
  }
  if (startBusy) { button = 'Sender start …'; enabled = false; }
  pill.className = `status-pill ${style}`;
  $('span', pill).textContent = label;
  $('#start-label').textContent = button;
  $('#start-button').disabled = !enabled;
  $('#server-help').textContent = help;
  const players = $('#player-count');
  const online = status?.state === 'online' && Number.isInteger(status?.players?.online) ? String(status.players.online) : '—';
  const maximum = Number.isInteger(status?.players?.max) ? status.players.max : 10;
  players.replaceChildren(document.createTextNode(online + ' '), element('small', '', `/ ${maximum}`));
  $('#suggestion-fields').disabled = !session || !available;
}

async function refreshStatus() {
  if (statusBusy || !configuration.apiBase) return;
  statusBusy = true;
  try {
    const status = await api(session ? '/api/status' : '/health', undefined, !!session);
    available = true;
    renderStatus(session ? status : null);
  } catch (error) {
    available = false;
    renderStatus(null, error.message);
  } finally { statusBusy = false; }
}

function showLogin() {
  if (!configuration.apiBase) { showToast('Forbindelsen til computeren er ikke aktiveret endnu.'); return; }
  setFeedback($('#login-feedback'), '');
  if (!$('#login-dialog').open) $('#login-dialog').showModal();
}

$('#start-button').addEventListener('click', async () => {
  if (!session) { showLogin(); return; }
  if (!currentStatus?.can_start || startBusy) return;
  startBusy = true;
  renderStatus(currentStatus);
  try {
    const result = await api('/api/start', {});
    showToast(result.started ? 'Start er sendt. Serveren gør sig klar.' : (result.message || 'Serverens status er opdateret.'));
    renderStatus({ ...currentStatus, state: result.state || 'starting', can_start: false });
  } catch (error) { showToast(error.message); }
  finally { startBusy = false; await refreshStatus(); }
});

$('#login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const name = $('#login-name').value.trim();
  const code = $('#login-code').value.trim();
  if (!name || !code) return;
  $('#login-submit').disabled = true;
  setFeedback($('#login-feedback'), 'Logger ind …');
  try {
    const result = await api('/api/login', { name, code }, false);
    if (typeof result.token !== 'string' || !result.token) throw new Error('Login gav ikke en gyldig adgang. Prøv igen.');
    available = true;
    saveSession({ token: result.token, name: typeof result.name === 'string' ? result.name : name, expires_at: result.expires_at });
    $('#login-code').value = '';
    $('#login-dialog').close();
    showToast(`Velkommen, ${session.name}.`);
    await Promise.allSettled([refreshStatus(), loadSuggestions()]);
  } catch (error) { setFeedback($('#login-feedback'), error.message, true); }
  finally { $('#login-submit').disabled = false; }
});

$('#account-button').addEventListener('click', () => {
  if (!session) { showLogin(); return; }
  $('#account-description').textContent = `Du bruger panelet som ${session.name}. Du kan starte serveren, foreslå mods og stemme på idéer.`;
  $('#account-dialog').showModal();
});
$('#close-login').addEventListener('click', () => $('#login-dialog').close());
$('#close-account').addEventListener('click', () => $('#account-dialog').close());
$('#logout-button').addEventListener('click', () => {
  saveSession(null);
  $('#account-dialog').close();
  renderStatus(null);
  showToast('Du er logget ud af panelet.');
});
$$('[data-login]').forEach(button => button.addEventListener('click', showLogin));
$$('dialog').forEach(dialog => dialog.addEventListener('click', event => {
  if (event.target !== dialog) return;
  const rect = dialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
}));

function thumbnail(url, title) {
  const valid = imageLink(url);
  const fallback = () => { const node = element('span', 'mod-thumbnail mod-placeholder'); node.setAttribute('aria-hidden', 'true'); node.append(makeIcon('box')); return node; };
  if (!valid) return fallback();
  const img = element('img', 'mod-thumbnail');
  img.src = valid;
  img.alt = '';
  img.loading = 'lazy';
  img.referrerPolicy = 'no-referrer';
  img.addEventListener('error', () => img.replaceWith(fallback()), { once: true });
  return img;
}

function renderPreview(metadata) {
  const target = $('#mod-preview');
  target.replaceChildren();
  target.hidden = !metadata;
  if (!metadata) return;
  const content = element('div');
  content.append(element('span', 'preview-tag', metadata.source || 'Modforslag'), element('h3', '', metadata.title || 'Dit modforslag'));
  content.append(element('p', '', metadata.description || 'Linket er klar. Et billede vises, hvis moddens side tilbyder et.'));
  target.append(thumbnail(metadata.image_url, metadata.title), content);
}

$('#mod-url').addEventListener('input', () => {
  clearTimeout(previewTimer);
  const sequence = ++previewSequence;
  const url = modLink($('#mod-url').value.trim());
  renderPreview(null);
  if (!url || !session) return;
  previewTimer = setTimeout(async () => {
    try {
      const preview = await api('/api/preview', { url });
      if (sequence === previewSequence) renderPreview(preview);
    } catch {
      if (sequence === previewSequence) renderPreview({ title: 'Linket er klar', description: 'Forhåndsvisningen kunne ikke hentes lige nu. Du kan stadig sende forslaget.', source: 'Forhåndsvisning' });
    }
  }, 700);
});

$('#suggestion-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!session) { showLogin(); return; }
  const url = modLink($('#mod-url').value.trim());
  if (!url) {
    setFeedback($('#suggestion-feedback'), 'Brug et direkte HTTPS-link til en Minecraft-mod på Modrinth eller CurseForge, fx modrinth.com/mod/modnavn.', true);
    $('#mod-url').focus();
    return;
  }
  const reason = $('#mod-reason').value.trim();
  $('#submit-suggestion').disabled = true;
  setFeedback($('#suggestion-feedback'), 'Sender dit forslag …');
  try {
    const result = await api('/api/suggestions', { url, reason });
    setFeedback($('#suggestion-feedback'), result.duplicate ? 'Den mod er allerede foreslået. Find den nedenfor, og giv den din stemme.' : 'Dit forslag er sendt. Tak for idéen!');
    $('#suggestion-form').reset();
    previewSequence++;
    clearTimeout(previewTimer);
    renderPreview(null);
    await loadSuggestions();
  } catch (error) { setFeedback($('#suggestion-feedback'), error.message, true); }
  finally { $('#submit-suggestion').disabled = false; }
});

function emptySuggestions(title, message) {
  const empty = element('div', 'empty-state');
  empty.append(makeIcon('spark'), element('h3', '', title), element('p', '', message));
  $('#suggestions-list').replaceChildren(empty);
}

function renderSuggestions() {
  $('#suggestions-count').textContent = String(suggestions.length);
  if (!session) { emptySuggestions('Her får nye idéer plads', 'Log ind for at se fællesskabets forslag.'); return; }
  if (!suggestions.length) { emptySuggestions('Det første forslag kan være dit', 'Indsæt et modlink ovenfor. En begrundelse er helt valgfri.'); return; }
  const sorted = [...suggestions].sort((a, b) => $('#suggestions-sort').value === 'votes' ? Number(b.votes || 0) - Number(a.votes || 0) || Date.parse(b.created_at) - Date.parse(a.created_at) : Date.parse(b.created_at) - Date.parse(a.created_at));
  const fragment = document.createDocumentFragment();
  sorted.forEach(suggestion => {
    const card = element('article', 'card suggestion-card');
    const header = element('div', 'suggestion-card-header');
    const heading = element('div');
    const title = element('h3');
    const url = modLink(suggestion.url);
    if (url) { const link = element('a', '', suggestion.title || 'Modforslag'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; title.append(link); }
    else title.textContent = suggestion.title || 'Modforslag';
    heading.append(title, element('span', 'source-label', suggestion.source || 'Modforslag'));
    header.append(thumbnail(suggestion.image_url, suggestion.title), heading);
    card.append(header);
    if (suggestion.description) card.append(element('p', 'suggestion-description', suggestion.description));
    if (suggestion.reason) card.append(element('p', 'suggestion-reason', suggestion.reason));
    const footer = element('div', 'suggestion-card-footer');
    const date = new Date(suggestion.created_at);
    const dateText = Number.isNaN(date.getTime()) ? '' : ` · ${date.toLocaleDateString('da-DK', { day: 'numeric', month: 'short' })}`;
    footer.append(element('span', 'suggestion-author', `${suggestion.author || 'En ven'}${dateText}`));
    const vote = element('button', 'vote-button');
    vote.type = 'button';
    vote.setAttribute('aria-pressed', String(!!suggestion.voted));
    vote.setAttribute('aria-label', `${suggestion.voted ? 'Fjern din stemme fra' : 'Stem på'} ${suggestion.title || 'modforslaget'}. ${Number(suggestion.votes) || 0} stemmer.`);
    vote.append(makeIcon('chevron-up'), document.createTextNode(String(Number(suggestion.votes) || 0)));
    vote.addEventListener('click', async () => {
      vote.disabled = true;
      try {
        const result = await api(`/api/suggestions/${encodeURIComponent(suggestion.id)}/vote`, {});
        suggestions = suggestions.map(item => String(item.id) === String(suggestion.id) ? result.suggestion : item);
        renderSuggestions();
      } catch (error) { showToast(error.message); vote.disabled = false; }
    });
    footer.append(vote); card.append(footer); fragment.append(card);
  });
  $('#suggestions-list').replaceChildren(fragment);
}

async function loadSuggestions() {
  if (!session || !configuration.apiBase) { renderSuggestions(); return; }
  try {
    const result = await api('/api/suggestions');
    suggestions = Array.isArray(result.suggestions) ? result.suggestions : [];
    renderSuggestions();
  } catch (error) { emptySuggestions('Forslagene kunne ikke hentes', error.message); }
}
$('#suggestions-sort').addEventListener('change', renderSuggestions);

$$('.copy-address').forEach(button => button.addEventListener('click', async () => {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
    await navigator.clipboard.writeText(configuration.serverAddress);
    showToast('Serveradressen er kopieret.');
  } catch {
    const code = $('.server-address', button.parentElement) || $('.server-address');
    const range = document.createRange();
    range.selectNodeContents(code);
    const selection = window.getSelection();
    selection.removeAllRanges(); selection.addRange(range);
    showToast('Adressen er markeret. Brug Kopiér eller Ctrl+C.');
  }
}));

function route(focus = false) {
  const requested = location.hash.slice(1);
  const page = Object.hasOwn(pages, requested) ? requested : 'oversigt';
  $$('.page').forEach(section => { const active = section.id === `page-${page}`; section.hidden = !active; section.classList.toggle('active-page', active); });
  $$('.nav-link').forEach(link => { const active = link.hash === `#${page}`; link.classList.toggle('active', active); if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current'); });
  $('#breadcrumb-current').textContent = pages[page];
  document.title = `${pages[page]} · Create & Magic Lite`;
  if (focus) { window.scrollTo({ top: 0, behavior: 'instant' }); $('#main').focus({ preventScroll: true }); }
  if (page === 'modforslag') loadSuggestions();
}
window.addEventListener('hashchange', () => route(true));
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshStatus(); });

async function refreshConfiguration(force = false) {
  if (runtimeBusy || (!force && Date.now() - runtimeLastChecked < 12000)) return false;
  runtimeBusy = true;
  runtimeLastChecked = Date.now();
  const previousBase = configuration.apiBase;
  try {
    const response = await fetch(`./runtime.json?v=${Date.now()}`, { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (response.ok) {
      const runtime = await response.json();
      configuration.apiBase = apiBaseFrom(runtime.apiBase);
      if (typeof runtime.serverAddress === 'string' && /^[A-Za-z0-9.\-]+:\d{1,5}$/.test(runtime.serverAddress)) configuration.serverAddress = runtime.serverAddress;
      configuration.packShareUrl = safeLink(runtime.packShareUrl, ['www.curseforge.com', 'curseforge.com'], '/minecraft/share/');
      configuration.githubRepoUrl = safeLink(runtime.githubRepoUrl, ['github.com']);
    }
  } catch { /* Keep the last verified configuration during a temporary failure. */ }
  finally { runtimeBusy = false; }
  $$('.server-address').forEach(node => { node.textContent = configuration.serverAddress; });
  $$('.pack-share-link').forEach(link => {
    link.hidden = !configuration.packShareUrl;
    if (configuration.packShareUrl) link.href = configuration.packShareUrl;
    else link.removeAttribute('href');
  });
  $$('.pack-link-pending, .pack-fallback').forEach(node => { node.hidden = !!configuration.packShareUrl; });
  if (configuration.githubRepoUrl) { $('#github-link').href = configuration.githubRepoUrl; $('#github-link').hidden = false; }
  if (previousBase && previousBase !== configuration.apiBase) {
    available = null;
    saveSession(null);
    renderStatus(null);
    showToast('Forbindelsen er blevet opdateret. Log ind igen med vennekoden.');
  }
  return previousBase !== configuration.apiBase;
}

async function initialize() {
  route();
  await refreshConfiguration(true);
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY));
    if (saved && saved.apiBase === configuration.apiBase && typeof saved.token === 'string' && typeof saved.name === 'string') session = { token: saved.token, name: saved.name, expires_at: saved.expires_at };
  } catch { /* Ignore malformed or unavailable session storage. */ }
  renderAccount();
  renderStatus(null);
  await refreshStatus();
  if (location.hash === '#modforslag') await loadSuggestions();
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 15000);
  setInterval(async () => {
    if (!document.hidden && await refreshConfiguration()) await refreshStatus();
  }, 30000);
}

initialize();
