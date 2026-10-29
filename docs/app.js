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

let configuration = { apiBase: '', serverAddress: '83.88.146.132:25566', packShareUrl: null, packApprovalPending: false, githubRepoUrl: '' };
let session = null;
let available = null;
let currentStatus = null;
let suggestions = [];
let suggestionsLoaded = false;
let suggestionsLoading = false;
let suggestionsError = '';
let suggestionsRequest = 0;
let initializing = true;
let statusBusy = false;
let startBusy = false;
let runtimeBusy = false;
let runtimeLastChecked = 0;
let previewSequence = 0;
let previewTimer;
let toastTimer;
let releaseCatalog = null;
let releasesLoading = false;
let releasesError = '';
const RELEASE_KINDS = { mod: 'Mods', resourcepack: 'Ressourcepakker', shader: 'Shaders' };
const STORAGE_KEY = 'create-magic-friend-session';
const SORT_KEY = 'create-magic-suggestions-sort';
const pages = { oversigt: 'Oversigt', modforslag: 'Modforslag', 'kom-i-gang': 'Kom i gang', modpakken: 'Modpakken', nyt: 'Nyt på serveren' };

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
}

function saveSession(value) {
  if (session?.token !== value?.token) {
    suggestionsRequest++;
    suggestions = [];
    suggestionsLoaded = false;
    suggestionsLoading = false;
    suggestionsError = '';
    $('#submit-suggestion').disabled = false;
    setFeedback($('#suggestion-feedback'), '');
  }
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
  renderSuggestions();
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

function packLink(value) {
  const link = safeLink(value, ['www.curseforge.com', 'curseforge.com']);
  if (!link) return null;
  const url = new URL(link);
  return !url.port && /^\/minecraft\/(?:share|modpacks)\/[A-Za-z0-9_-]+\/?$/.test(url.pathname) ? url.href : null;
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

function releaseDownloadLink(value) {
  // Only files inside this site's downloads directory may become download links.
  return typeof value === 'string' && /^downloads\/Create-Magic-Lite-[0-9][A-Za-z0-9._+-]*\.zip$/.test(value)
    ? `./${value}` : null;
}

function catalogProjectLink(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port) return null;
    const curseforge = ['www.curseforge.com', 'curseforge.com'].includes(url.hostname)
      && /^\/minecraft\/(?:mc-mods|texture-packs|shaders)\/[A-Za-z0-9_-]+\/?$/.test(url.pathname);
    const modrinth = url.hostname === 'modrinth.com'
      && /^\/(?:mod|resourcepack|shader)\/[A-Za-z0-9_-]+\/?$/.test(url.pathname);
    return curseforge || modrinth ? `${url.origin}${url.pathname.replace(/\/$/, '')}` : null;
  } catch { return null; }
}

function readReleaseCatalog(data) {
  if (data?.schema_version !== 1 || !Array.isArray(data.releases) || !data.releases.length
      || data.releases.length > 100 || typeof data.latest_version !== 'string') throw new Error('Invalid release catalog');
  const readItems = items => {
    if (!Array.isArray(items) || items.length > 1000) throw new Error('Invalid release items');
    return items.map(item => {
      if (!item || !Object.hasOwn(RELEASE_KINDS, item.kind) || typeof item.name !== 'string'
          || !item.name.trim() || typeof item.version !== 'string'
          || !Number.isSafeInteger(item.project_id) || item.project_id < 1
          || !Number.isSafeInteger(item.file_id) || item.file_id < 1) throw new Error('Invalid release item');
      return {
        project_id: item.project_id, file_id: item.file_id, kind: item.kind,
        name: item.name.slice(0, 200), version: item.version.slice(0, 200),
        previous_version: typeof item.previous_version === 'string' ? item.previous_version.slice(0, 200) : '',
        url: catalogProjectLink(item.url), image_url: imageLink(item.image_url),
        environment: typeof item.environment === 'string' ? item.environment.slice(0, 80) : '',
      };
    });
  };
  const releases = data.releases.map(release => {
    if (!release || typeof release.version !== 'string' || !release.version.trim()
        || !release.changes) throw new Error('Invalid release');
    const text = value => typeof value === 'string' ? value.slice(0, 2000) : '';
    return {
      version: release.version.slice(0, 80), published_at: text(release.published_at),
      minecraft_version: text(release.minecraft_version), loader: text(release.loader),
      summary: text(release.summary), download_url: releaseDownloadLink(release.download_url),
      sha256: typeof release.sha256 === 'string' && /^[a-f0-9]{64}$/i.test(release.sha256) ? release.sha256 : '',
      items: readItems(release.items),
      changes: Object.fromEntries(['added', 'updated', 'removed'].map(kind => [kind, readItems(release.changes[kind])])),
    };
  });
  if (new Set(releases.map(release => release.version)).size !== releases.length) throw new Error('Duplicate release');
  const latest = releases.find(release => release.version === data.latest_version);
  if (!latest) throw new Error('Missing latest release');
  return { releases, latest };
}

function catalogItem(item, changed = false) {
  const row = element('li', changed ? 'release-change-item' : 'catalog-item');
  if (!changed && item.image_url) {
    const image = element('img', 'catalog-icon');
    image.src = item.image_url;
    image.alt = '';
    image.loading = 'lazy';
    image.referrerPolicy = 'no-referrer';
    image.addEventListener('error', () => { image.hidden = true; });
    row.append(image);
  }
  const content = element('div', 'catalog-item-content');
  const name = element(item.url ? 'a' : 'span', 'catalog-item-name', item.name);
  if (item.url) {
    name.href = item.url;
    name.target = '_blank';
    name.rel = 'noopener noreferrer';
  }
  content.append(name, element('span', 'catalog-item-version', item.previous_version && changed
    ? `${item.previous_version} → ${item.version}` : item.version));
  const environment = { client: 'Klient', server: 'Server', 'client-and-server': 'Klient + server' }[item.environment];
  if (!changed && environment) content.append(element('span', 'catalog-item-environment', environment));
  row.append(content);
  return row;
}

function renderCatalog() {
  const container = $('#mod-catalog');
  container.setAttribute('aria-busy', String(releasesLoading));
  if (!releaseCatalog) {
    container.replaceChildren(element('p', 'catalog-empty', releasesLoading
      ? 'Henter modlisten …' : 'Modlisten kunne ikke hentes. Prøv at hente den igen.'));
    $('#catalog-summary').textContent = '';
    return;
  }
  const items = releaseCatalog.latest.items;
  const query = $('#catalog-search').value.trim().toLocaleLowerCase('da-DK');
  const filtered = items.filter(item => `${item.name} ${item.version} ${item.environment} ${RELEASE_KINDS[item.kind]}`.toLocaleLowerCase('da-DK').includes(query));
  const fragment = document.createDocumentFragment();
  Object.entries(RELEASE_KINDS).forEach(([kind, title]) => {
    const groupItems = filtered.filter(item => item.kind === kind).sort((a, b) => a.name.localeCompare(b.name, 'da'));
    if (!groupItems.length) return;
    const group = element('section', 'catalog-group');
    const heading = element('h3', 'catalog-group-title', title);
    heading.append(element('span', 'count-badge', String(groupItems.length)));
    const list = element('ul', 'catalog-list');
    groupItems.forEach(item => list.append(catalogItem(item)));
    group.append(heading, list);
    fragment.append(group);
  });
  if (!filtered.length) fragment.append(element('p', 'catalog-empty', 'Ingen tilføjelser matcher din søgning. Prøv et andet navn.'));
  container.replaceChildren(fragment);
  $('#catalog-summary').textContent = query
    ? `${filtered.length} af ${items.length} tilføjelser matcher din søgning · version ${releaseCatalog.latest.version}`
    : `${items.filter(item => item.kind === 'mod').length} mods · ${items.filter(item => item.kind === 'resourcepack').length} ressourcepakker · ${items.filter(item => item.kind === 'shader').length} shaderpakke · version ${releaseCatalog.latest.version}`;
}

function renderReleaseHistory() {
  const history = $('#release-history');
  history.setAttribute('aria-busy', String(releasesLoading));
  if (!releaseCatalog) {
    history.replaceChildren(element('p', 'catalog-empty', releasesLoading
      ? 'Henter versionshistorikken …' : 'Versionshistorikken kunne ikke hentes. Prøv igen fra Modpakken.'));
    return;
  }
  const fragment = document.createDocumentFragment();
  releaseCatalog.releases.forEach(release => {
    const article = element('article', 'timeline-item release-entry');
    article.append(element('span', 'timeline-dot'));
    const date = new Date(release.published_at);
    if (!Number.isNaN(date.getTime())) {
      const time = element('time', '', date.toLocaleDateString('da-DK', { day: 'numeric', month: 'long', year: 'numeric' }));
      time.setAttribute('datetime', release.published_at);
      article.append(time);
    }
    article.append(element('h2', '', `Version ${release.version}`));
    if (release.summary) article.append(element('p', '', release.summary));
    article.append(element('p', 'release-platform', `Minecraft ${release.minecraft_version} · ${release.loader}`));
    const groups = element('div', 'release-changes');
    Object.entries({ added: 'Tilføjet', updated: 'Opdateret', removed: 'Fjernet' }).forEach(([kind, title]) => {
      const items = release.changes[kind];
      const details = element('details', 'release-change-group');
      const summary = element('summary', '', `${title} (${items.length})`);
      details.append(summary);
      if (items.length) {
        const list = element('ul', 'release-change-list');
        items.forEach(item => list.append(catalogItem(item, true)));
        details.append(list);
      } else details.append(element('p', 'release-no-changes', 'Ingen ændringer i denne gruppe.'));
      groups.append(details);
    });
    article.append(groups);
    if (release.download_url) {
      const download = element('a', 'text-link release-history-download', `Hent ZIP v${release.version}`);
      download.href = release.download_url;
      download.setAttribute('download', '');
      download.append(makeIcon('arrow-right'));
      article.append(download);
    }
    fragment.append(article);
  });
  history.replaceChildren(fragment);
}

function renderPublicReleases() {
  const latest = releaseCatalog?.latest;
  $$('.release-download').forEach(link => {
    link.hidden = !latest?.download_url;
    if (latest?.download_url) {
      link.href = latest.download_url;
      link.setAttribute('download', '');
      link.replaceChildren(document.createTextNode(`Hent modpakken ZIP v${latest.version}`), makeIcon('box'));
    } else link.removeAttribute('href');
  });
  $('#pack-release-version').textContent = latest ? `VERSION ${latest.version}` : 'DEN FÆLLES PAKKE';
  $('#latest-release-summary').textContent = latest
    ? `Version ${latest.version} · ${latest.summary}` : 'Se modpakken og versionshistorikken.';
  $('#release-integrity').hidden = !latest?.sha256;
  $('#release-sha256').textContent = latest?.sha256 || '';
  $('#release-retry').hidden = !releasesError;
  $('#release-retry').disabled = releasesLoading;
  const message = releasesError || (releasesLoading ? 'Henter den seneste udgivelse …'
    : latest?.download_url ? 'ZIP-filen kan hentes uden login, også når servercomputeren er slukket.'
      : 'Denne udgivelse har endnu ingen ZIP-fil.');
  setFeedback($('#releases-status'), message, !!releasesError);
  renderCatalog();
  renderReleaseHistory();
}

async function loadReleases() {
  if (releasesLoading) return;
  releasesLoading = true;
  releasesError = '';
  renderPublicReleases();
  try {
    const response = await fetch('./releases.json', {
      cache: 'no-store', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer',
      headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error('Release request failed');
    releaseCatalog = readReleaseCatalog(await response.json());
  } catch {
    releasesError = releaseCatalog
      ? 'Kunne ikke opdatere udgivelsen. Den senest hentede modliste og ZIP vises stadig.'
      : 'Kunne ikke hente udgivelsen. Prøv igen om lidt; du behøver ikke logge ind.';
  } finally {
    releasesLoading = false;
    renderPublicReleases();
  }
}
$('#catalog-search').addEventListener('input', renderCatalog);
$('#release-retry').addEventListener('click', loadReleases);

async function api(path, body, authenticated = true) {
  if (!configuration.apiBase) throw new Error('Forbindelsen til computeren er ikke aktiveret endnu.');
  const requestBase = configuration.apiBase;
  const requestToken = session?.token;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 18000);
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (authenticated && session) headers.Authorization = `Bearer ${session.token}`;
  try {
    const response = await fetch(requestBase + path, { method: body === undefined ? 'GET' : 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal, credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && authenticated) {
        if (requestToken === session?.token && requestBase === configuration.apiBase) {
          saveSession(null);
          renderStatus(null);
        }
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
  const token = session?.token;
  const base = configuration.apiBase;
  const current = () => token === session?.token && base === configuration.apiBase;
  statusBusy = true;
  try {
    const status = await api(session ? '/api/status' : '/health', undefined, !!session);
    if (!current()) return;
    available = true;
    renderStatus(session ? status : null);
  } catch (error) {
    if (!current()) return;
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
  const loginBase = configuration.apiBase;
  $('#login-submit').disabled = true;
  setFeedback($('#login-feedback'), 'Logger ind …');
  try {
    const result = await api('/api/login', { name, code }, false);
    if (configuration.apiBase !== loginBase) throw new Error('Forbindelsen er blevet opdateret. Log ind igen.');
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
  const submittedToken = session.token;
  const submittedBase = configuration.apiBase;
  $('#submit-suggestion').disabled = true;
  setFeedback($('#suggestion-feedback'), 'Sender dit forslag …');
  try {
    const result = await api('/api/suggestions', { url, reason });
    if (session?.token !== submittedToken || configuration.apiBase !== submittedBase) return;
    if (!result.suggestion?.id || !modLink(result.suggestion.url)) throw new Error('Gemningen kunne ikke bekræftes. Prøv at opdatere listen.');
    // A confirmed save remains visible even if the following list request fails.
    suggestionsRequest++;
    suggestionsLoading = false;
    suggestionsError = '';
    suggestions = [...suggestions.filter(item => String(item.id) !== String(result.suggestion.id)), result.suggestion];
    $('#suggestions-search').value = '';
    if (!result.duplicate) {
      $('#suggestions-sort').value = 'newest';
      rememberSuggestionSort();
    }
    renderSuggestions();
    setFeedback($('#suggestion-feedback'), result.duplicate ? 'Forslaget er allerede gemt. Det er markeret i listen nedenfor.' : 'Dit forslag er gemt. Det bliver også her næste gang, du besøger siden.');
    $('#suggestion-form').reset();
    previewSequence++;
    clearTimeout(previewTimer);
    renderPreview(null);
    await loadSuggestions();
    if (session?.token !== submittedToken || configuration.apiBase !== submittedBase) return;
    const savedCard = document.getElementById(`suggestion-${result.suggestion.id}`);
    savedCard?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    savedCard?.focus({ preventScroll: true });
  } catch (error) {
    if (session?.token === submittedToken && configuration.apiBase === submittedBase) setFeedback($('#suggestion-feedback'), error.message, true);
  } finally {
    if (session?.token === submittedToken && configuration.apiBase === submittedBase) $('#submit-suggestion').disabled = false;
  }
});

function emptySuggestions(title, message) {
  const empty = element('div', 'empty-state');
  empty.append(makeIcon('spark'), element('h3', '', title), element('p', '', message));
  $('#suggestions-list').replaceChildren(empty);
}

function renderSuggestions() {
  $('#suggestions-count').textContent = session && (suggestionsLoaded || suggestions.length) ? String(suggestions.length) : '—';
  $('#suggestions-list').setAttribute('aria-busy', String(suggestionsLoading || initializing));
  $('#suggestions-refresh').disabled = !session || suggestionsLoading || initializing;
  $('#suggestions-search').disabled = !session;
  $('#suggestions-summary').textContent = '';
  setFeedback($('#suggestions-status'), suggestionsError ? `${suggestionsError} ${suggestions.length ? 'Viser de senest hentede forslag. Brug Opdater liste for at prøve igen.' : 'Brug Opdater liste for at prøve igen.'}` : suggestionsLoading && suggestions.length ? 'Opdaterer listen …' : '', !!suggestionsError);
  if (initializing) { emptySuggestions('Henter dine forslag …', 'Kontrollerer forbindelsen og din adgang.'); return; }
  if (!session) { emptySuggestions('Her får nye idéer plads', 'Log ind for at se fællesskabets forslag.'); return; }
  if (!suggestionsLoaded && !suggestions.length) {
    emptySuggestions(suggestionsError ? 'Forslagene kunne ikke hentes' : 'Henter forslag …', suggestionsError ? 'Listen er ikke indlæst. Prøv igen med Opdater liste.' : 'Henter den gemte liste fra serveren.');
    return;
  }
  if (!suggestions.length) { emptySuggestions('Det første forslag kan være dit', 'Indsæt et modlink ovenfor. En begrundelse er helt valgfri.'); return; }
  const query = $('#suggestions-search').value.trim().toLocaleLowerCase('da-DK');
  const matching = suggestions.filter(item => !query || [item.title, item.url, item.description, item.reason, item.author].some(value => String(value || '').toLocaleLowerCase('da-DK').includes(query)));
  $('#suggestions-summary').textContent = query ? `Viser ${matching.length} af ${suggestions.length} forslag.` : `${suggestions.length} gemte forslag. Søg på navn eller link for at finde et tidligere forslag.`;
  if (!matching.length) { emptySuggestions('Ingen forslag matcher søgningen', 'Prøv et andet ord, eller ryd søgefeltet for at se alle forslag.'); return; }
  const newest = (a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0) || Number(b.id) - Number(a.id);
  const order = $('#suggestions-sort').value;
  const sorted = matching.sort((a, b) => order === 'votes' ? Number(b.votes || 0) - Number(a.votes || 0) || newest(a, b) : order === 'oldest' ? newest(b, a) : newest(a, b));
  const fragment = document.createDocumentFragment();
  sorted.forEach(suggestion => {
    const card = element('article', 'card suggestion-card');
    card.id = `suggestion-${suggestion.id}`;
    card.tabIndex = -1;
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
      const token = session?.token;
      const base = configuration.apiBase;
      const current = () => token === session?.token && base === configuration.apiBase;
      vote.disabled = true;
      try {
        const result = await api(`/api/suggestions/${encodeURIComponent(suggestion.id)}/vote`, {});
        if (!current()) return;
        suggestionsRequest++;
        suggestionsLoading = false;
        suggestionsError = '';
        suggestions = suggestions.map(item => String(item.id) === String(suggestion.id) ? result.suggestion : item);
        renderSuggestions();
      } catch (error) { if (current()) { showToast(error.message); vote.disabled = false; } }
    });
    footer.append(vote); card.append(footer); fragment.append(card);
  });
  $('#suggestions-list').replaceChildren(fragment);
}

async function loadSuggestions() {
  if (!session || !configuration.apiBase) { renderSuggestions(); return; }
  const request = ++suggestionsRequest;
  const token = session.token;
  const base = configuration.apiBase;
  const current = () => request === suggestionsRequest && token === session?.token && base === configuration.apiBase;
  suggestionsLoading = true;
  suggestionsError = '';
  renderSuggestions();
  try {
    const result = await api('/api/suggestions');
    if (!current()) return;
    if (!Array.isArray(result.suggestions)) throw new Error('Serveren sendte ikke en gyldig liste med forslag.');
    suggestions = result.suggestions;
    suggestionsLoaded = true;
  } catch (error) {
    if (current()) suggestionsError = error.message;
  } finally {
    if (current()) { suggestionsLoading = false; renderSuggestions(); }
  }
}
function rememberSuggestionSort() {
  try { localStorage.setItem(SORT_KEY, $('#suggestions-sort').value); } catch { /* Sorting still works without storage. */ }
}
$('#suggestions-sort').addEventListener('change', () => { rememberSuggestionSort(); renderSuggestions(); });
$('#suggestions-search').addEventListener('input', renderSuggestions);
$('#suggestions-refresh').addEventListener('click', loadSuggestions);

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
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    refreshStatus();
    if (location.hash === '#modforslag') loadSuggestions();
  }
});

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
      configuration.packShareUrl = packLink(runtime.packShareUrl);
      configuration.packApprovalPending = runtime.packApprovalPending === true;
      configuration.githubRepoUrl = safeLink(runtime.githubRepoUrl, ['github.com']);
    }
  } catch { /* Keep the last verified configuration during a temporary failure. */ }
  finally { runtimeBusy = false; }
  $$('.server-address').forEach(node => { node.textContent = configuration.serverAddress; });
  $$('.pack-share-link').forEach(link => {
    link.hidden = !configuration.packShareUrl || configuration.packApprovalPending;
    if (configuration.packShareUrl) link.href = configuration.packShareUrl;
    else link.removeAttribute('href');
  });
  $$('.pack-link-pending').forEach(node => { node.hidden = !!configuration.packShareUrl; });
  $$('.pack-fallback').forEach(node => { node.hidden = !!configuration.packShareUrl && !configuration.packApprovalPending; });
  $$('.pack-approval-pending').forEach(node => { node.hidden = !configuration.packShareUrl || !configuration.packApprovalPending; });
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
  try {
    const sort = localStorage.getItem(SORT_KEY);
    if (['newest', 'oldest', 'votes'].includes(sort)) $('#suggestions-sort').value = sort;
  } catch { /* Default sorting works when storage is unavailable. */ }
  route();
  // The public ZIP and inventory must not wait for the owner's PC or friend login.
  const releasesReady = loadReleases();
  await refreshConfiguration(true);
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY));
    if (saved && saved.apiBase === configuration.apiBase && typeof saved.token === 'string' && typeof saved.name === 'string') session = { token: saved.token, name: saved.name, expires_at: saved.expires_at };
  } catch { /* Ignore malformed or unavailable session storage. */ }
  initializing = false;
  renderAccount();
  renderStatus(null);
  await Promise.allSettled([releasesReady, refreshStatus(), ...(location.hash === '#modforslag' ? [loadSuggestions()] : [])]);
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 15000);
  setInterval(async () => {
    if (!document.hidden && await refreshConfiguration()) await refreshStatus();
  }, 30000);
}

initialize();
