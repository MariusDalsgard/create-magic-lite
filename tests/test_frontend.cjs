const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// Exercise the shipped browser code without installing a DOM or browser package.
// Startup networking is omitted; each test controls real fetch responses explicitly.
const source = readFileSync(path.join(__dirname, '../docs/app.js'), 'utf8')
  .replace(/\binitialize\(\);\s*$/, '');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

function response(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data };
}

function harness(stored = {}) {
  const nodes = new Map();
  const pendingFetches = [];
  const calls = [];
  const storage = new Map(Object.entries(stored));
  const documentEvents = new Map();

  class Node {
    constructor(tag = 'div') {
      this.tagName = tag;
      this.children = [];
      this.attributes = new Map();
      this.events = new Map();
      this.dataset = {};
      this.className = '';
      this.value = '';
      this.hidden = false;
      this.disabled = false;
      this._text = '';
      this.classList = {
        toggle: (name, enabled) => {
          const classes = new Set(this.className.split(/\s+/).filter(Boolean));
          const add = enabled ?? !classes.has(name);
          if (add) classes.add(name); else classes.delete(name);
          this.className = [...classes].join(' ');
          return add;
        },
        add: (...names) => names.forEach(name => this.classList.toggle(name, true)),
        remove: (...names) => names.forEach(name => this.classList.toggle(name, false)),
        contains: name => this.className.split(/\s+/).includes(name),
      };
    }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this._text = String(value); this.children = []; }
    append(...children) {
      for (let child of children) {
        if (typeof child === 'string') { const text = new Node('#text'); text.textContent = child; child = text; }
        if (child.tagName === '#fragment') { this.append(...child.children); continue; }
        child.parentElement = this;
        this.children.push(child);
      }
    }
    appendChild(child) { this.append(child); return child; }
    replaceChildren(...children) { this._text = ''; this.children = []; this.append(...children); }
    replaceWith(child) {
      if (!this.parentElement) return;
      const parent = this.parentElement;
      parent.children[parent.children.indexOf(this)] = child;
      child.parentElement = parent;
    }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    removeAttribute(name) { this.attributes.delete(name); }
    addEventListener(type, callback) {
      if (!this.events.has(type)) this.events.set(type, []);
      this.events.get(type).push(callback);
    }
    async fire(type) {
      for (const callback of this.events.get(type) || []) await callback({ preventDefault() {}, target: this });
    }
    focus() {}
    scrollIntoView() {}
    reset() { for (const id of ['mod-url', 'mod-reason']) node(id).value = ''; }
    querySelector(selector) {
      const match = this.descendants().find(child => selector.startsWith('.')
        ? child.classList.contains(selector.slice(1)) : child.tagName === selector);
      if (match) return match;
      const child = new Node(selector);
      this.append(child);
      return child;
    }
    querySelectorAll(selector) {
      return this.descendants().filter(child => selector.startsWith('.')
        ? child.classList.contains(selector.slice(1)) : child.tagName === selector);
    }
    descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
  }

  function node(id) {
    if (!nodes.has(id)) { const item = new Node(); item.id = id; nodes.set(id, item); }
    return nodes.get(id);
  }
  node('suggestions-sort').value = 'newest';
  const document = {
    hidden: false,
    querySelector: selector => node(selector.replace(/^#/, '')),
    querySelectorAll: () => [],
    getElementById: id => nodes.get(id) || [...nodes.values()].flatMap(item => item.descendants()).find(item => item.id === id) || null,
    createElement: tag => new Node(tag),
    createElementNS: (_, tag) => new Node(tag),
    createDocumentFragment: () => new Node('#fragment'),
    createTextNode: text => { const item = new Node('#text'); item.textContent = text; return item; },
    addEventListener: (type, callback) => documentEvents.set(type, callback),
  };
  const browserStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  };
  const context = vm.createContext({
    document, window: { addEventListener() {}, scrollTo() {} },
    location: { hash: '#modforslag' }, navigator: {},
    sessionStorage: browserStorage, localStorage: browserStorage,
    URL, AbortController, AbortSignal, console,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1,
    fetch: (url, options) => {
      calls.push({ url, options });
      assert.ok(pendingFetches.length, `Unexpected fetch: ${url}`);
      return Promise.resolve(pendingFetches.shift());
    },
  });
  const run = code => vm.runInContext(code, context);
  run(source);
  run("initializing = false; configuration.apiBase = 'https://panel.example'; available = true; saveSession({ token: 'session-a', name: 'Marius' });");
  return {
    node, run, calls, storage, document, documentEvents,
    enqueue: value => pendingFetches.push(value),
    listText: () => node('suggestions-list').textContent,
    titles: () => node('suggestions-list').descendants().filter(n => n.tagName === 'h3').map(n => n.textContent),
  };
}

function suggestion(id, title, extra = {}) {
  return {
    id, title, url: `https://modrinth.com/mod/mod-${id}`, description: '', reason: '',
    author: 'Marius', created_at: id <= 2 ? '2026-10-27T21:31:49Z' : '2026-10-29T12:40:34Z',
    votes: id <= 2 ? 1 : 0, voted: false, source: 'Modrinth', image_url: null,
    ...extra,
  };
}

const mapsAndNewerMods = [
  suggestion(1, 'Xaeros World Map', { url: 'https://www.curseforge.com/minecraft/mc-mods/xaeros-world-map' }),
  suggestion(2, 'Xaeros Minimap', { url: 'https://www.curseforge.com/minecraft/mc-mods/xaeros-minimap' }),
  ...Array.from({ length: 12 }, (_, index) => suggestion(index + 3, `New mod ${index + 3}`)),
];

async function load(h, items = mapsAndNewerMods) {
  h.enqueue(response({ suggestions: items }));
  await h.run('loadSuggestions()');
}

test('runtime configuration opens both permanent CurseForge projects and existing share links', async () => {
  const h = harness();
  const download = h.node('pack-download-test');
  const pending = h.node('pack-pending-test');
  h.document.querySelectorAll = selector => selector === '.pack-share-link' ? [download]
    : selector === '.pack-link-pending' ? [pending] : [];
  for (const url of [
    'https://www.curseforge.com/minecraft/modpacks/create-magic-lite',
    'https://curseforge.com/minecraft/modpacks/create-magic-lite/',
    'https://www.curseforge.com/minecraft/share/tLT6EZy0',
  ]) {
    h.enqueue(response({ apiBase: 'https://panel.example', packShareUrl: url }));
    await h.run('refreshConfiguration(true)');
    assert.equal(h.run('configuration.packShareUrl'), url);
    assert.equal(download.href, url);
    assert.equal(download.hidden, false);
    assert.equal(pending.hidden, true);
  }
});

test('invalid pack destinations hide download links instead of retaining a stale project link', async () => {
  const h = harness();
  const download = h.node('pack-download-test');
  const pending = h.node('pack-pending-test');
  h.document.querySelectorAll = selector => selector === '.pack-share-link' ? [download]
    : selector === '.pack-link-pending' ? [pending] : [];
  for (const url of [
    null,
    'https://www.curseforge.com/minecraft/modpacks/',
    'https://www.curseforge.com/minecraft/modpacks/create-magic-lite/files',
    'https://www.curseforge.com/minecraft/mc-mods/create',
    'https://www.curseforge.com/minecraft/share/',
    'https://www.curseforge.com.evil.example/minecraft/modpacks/create-magic-lite',
    'https://name:password@www.curseforge.com/minecraft/modpacks/create-magic-lite',
    'https://www.curseforge.com:8443/minecraft/modpacks/create-magic-lite',
    'http://www.curseforge.com/minecraft/modpacks/create-magic-lite',
    'javascript:alert(1)',
  ]) {
    h.run("configuration.packShareUrl = 'https://www.curseforge.com/minecraft/modpacks/previous-pack';");
    download.hidden = false;
    pending.hidden = true;
    h.enqueue(response({ apiBase: 'https://panel.example', packShareUrl: url }));
    await h.run('refreshConfiguration(true)');
    assert.equal(h.run('configuration.packShareUrl'), null, String(url));
    assert.equal(download.hidden, true, String(url));
    assert.equal(pending.hidden, false, String(url));
  }
});

test('a pending CurseForge project becomes downloadable only after its approval flag clears', async () => {
  const h = harness();
  const download = h.node('pack-download-test');
  const pendingLink = h.node('pack-pending-test');
  const approval = h.node('pack-approval-test');
  const fallback = h.node('pack-fallback-test');
  const nodes = new Map([
    ['.pack-share-link', [download]], ['.pack-link-pending', [pendingLink]],
    ['.pack-approval-pending', [approval]], ['.pack-fallback', [fallback]],
  ]);
  h.document.querySelectorAll = selector => nodes.get(selector) || [];
  const url = 'https://www.curseforge.com/minecraft/modpacks/create-magic-lite';
  for (const pending of [true, false]) {
    h.enqueue(response({ apiBase: 'https://panel.example', packShareUrl: url, packApprovalPending: pending }));
    await h.run('refreshConfiguration(true)');
    assert.equal(h.run('configuration.packShareUrl'), url);
    assert.equal(download.hidden, pending);
    assert.equal(approval.hidden, !pending);
    assert.equal(fallback.hidden, !pending);
    assert.equal(pendingLink.hidden, true);
    assert.equal(h.run('session.token'), 'session-a');
  }
});

test('fresh page restores its session without briefly presenting an empty list', async () => {
  const h = harness();
  h.run("session = null; configuration.apiBase = ''; initializing = true;");
  const runtime = deferred();
  h.enqueue(runtime.promise);
  h.enqueue(response({ state: 'offline', players: { online: 0, max: 10 }, can_start: true }));
  h.enqueue(response({ suggestions: mapsAndNewerMods }));
  const startup = h.run('initialize()');
  assert.notEqual(h.node('suggestions-count').textContent, '0');
  assert.doesNotMatch(h.listText(), /Log ind|Det første forslag kan være dit/);
  runtime.resolve(response({ apiBase: 'https://panel.example' }));
  await startup;
  assert.equal(h.node('suggestions-count').textContent, '14');
  assert.match(h.listText(), /Xaeros World Map/);
});

test('loading and failed initial requests do not claim the saved list is empty', async () => {
  const h = harness();
  const pending = deferred();
  h.enqueue(pending.promise);
  const loading = h.run('loadSuggestions()');
  assert.notEqual(h.node('suggestions-count').textContent, '0');
  assert.doesNotMatch(h.listText(), /Det første forslag kan være dit/);
  pending.resolve(response({ message: 'Temporary outage' }, 503));
  await loading;
  assert.notEqual(h.node('suggestions-count').textContent, '0');
  assert.doesNotMatch(h.listText(), /Det første forslag kan være dit/);
  h.run('renderSuggestions()');
  assert.doesNotMatch(h.listText(), /Det første forslag kan være dit/);
  assert.match(h.listText() + h.node('suggestions-status').textContent, /Temporary outage|kunne ikke|forbindelse/i);
});

test('a confirmed empty response is distinguished from an unavailable list', async () => {
  const h = harness();
  await load(h, []);
  assert.equal(h.node('suggestions-count').textContent, '0');
  assert.match(h.listText(), /første forslag|ingen forslag/i);
});

test('temporary refresh failure preserves previously loaded map suggestions', async () => {
  const h = harness();
  await load(h);
  h.enqueue(response({ message: 'Temporary outage' }, 503));
  await h.run('loadSuggestions()');
  assert.equal(h.node('suggestions-count').textContent, '14');
  assert.match(h.listText(), /Xaeros World Map/);
  assert.match(h.listText(), /Xaeros Minimap/);
  assert.match(h.node('suggestions-status').textContent, /Temporary outage|kunne ikke|forbindelse/i);
});

test('search finds older map suggestions while preserving the total and full list', async () => {
  const h = harness();
  await load(h);
  h.node('suggestions-search').value = 'MAP';
  await h.node('suggestions-search').fire('input');
  assert.deepEqual(new Set(h.titles()), new Set(['Xaeros World Map', 'Xaeros Minimap']));
  assert.equal(h.node('suggestions-count').textContent, '14');
  assert.match(h.node('suggestions-summary').textContent, /2.*14/);
  h.node('suggestions-search').value = 'no-such-mod';
  await h.node('suggestions-search').fire('input');
  assert.doesNotMatch(h.listText(), /Det første forslag kan være dit/);
  assert.match(h.listText(), /ingen|matcher|søgning/i);
  h.node('suggestions-search').value = '';
  await h.node('suggestions-search').fire('input');
  assert.equal(h.titles().length, 14);
});

test('oldest sorting exposes earlier suggestions and persists across a fresh page', async () => {
  const h = harness();
  await load(h);
  h.node('suggestions-sort').value = 'oldest';
  await h.node('suggestions-sort').fire('change');
  assert.deepEqual(h.titles().slice(0, 2), ['Xaeros World Map', 'Xaeros Minimap']);
  assert.equal(h.storage.get('create-magic-suggestions-sort'), 'oldest');
  const fresh = harness(Object.fromEntries(h.storage));
  fresh.run("session = null; configuration.apiBase = ''; initializing = true;");
  fresh.enqueue(response({ apiBase: 'https://panel.example' }));
  fresh.enqueue(response({ state: 'offline', players: { online: 0, max: 10 }, can_start: true }));
  fresh.enqueue(response({ suggestions: mapsAndNewerMods }));
  await fresh.run('initialize()');
  assert.equal(fresh.node('suggestions-sort').value, 'oldest');
  assert.deepEqual(fresh.titles().slice(0, 2), ['Xaeros World Map', 'Xaeros Minimap']);
});

test('a late old-session response cannot replace the newly loaded suggestions', async () => {
  const h = harness();
  const pending = deferred();
  h.enqueue(pending.promise);
  const oldRequest = h.run('loadSuggestions()');
  h.run("saveSession({token: 'session-b', name: 'Another friend'})");
  await load(h, [suggestion(20, 'Current saved suggestion')]);
  pending.resolve(response({ suggestions: [suggestion(1, 'Stale suggestion')] }));
  await oldRequest;
  assert.deepEqual(h.titles(), ['Current saved suggestion']);
});

test('a late 401 from the previous session does not log out the new session', async () => {
  const h = harness();
  const pending = deferred();
  h.enqueue(pending.promise);
  const oldRequest = h.run('loadSuggestions()');
  h.run("saveSession({token: 'session-b', name: 'Another friend'})");
  await load(h, [suggestion(20, 'Current saved suggestion')]);
  pending.resolve(response({ message: 'Expired' }, 401));
  await oldRequest;
  assert.equal(h.run('session.token'), 'session-b');
  assert.deepEqual(h.titles(), ['Current saved suggestion']);
});

test('successful submission remains visible even when the subsequent refresh fails', async () => {
  const h = harness();
  await load(h);
  const added = suggestion(15, 'Newly saved mod');
  h.node('mod-url').value = added.url;
  h.node('mod-reason').value = 'A useful new idea';
  h.enqueue(response({ suggestion: added, duplicate: false }));
  const pendingRefresh = deferred();
  h.enqueue(pendingRefresh.promise);
  const submission = h.node('suggestion-form').fire('submit');
  // Let POST headers and JSON parsing resolve while keeping its GET pending.
  for (let turn = 0; turn < 8; turn++) await Promise.resolve();
  assert.match(h.listText(), /Newly saved mod/);
  pendingRefresh.resolve(response({ message: 'Temporary outage' }, 503));
  await submission;
  assert.match(h.listText(), /Newly saved mod/);
  assert.match(h.node('suggestion-feedback').textContent, /gemt|sendt|tak/i);
  assert.equal(h.node('suggestions-count').textContent, '15');
});

test('a delayed vote response cannot overwrite the next signed-in friend\'s vote', async () => {
  const h = harness();
  const original = suggestion(1, 'Xaeros World Map', { votes: 1, voted: false });
  const findVote = () => h.node('suggestions-list').descendants().find(item =>
    item.tagName === 'button' && item.getAttribute('aria-label')?.includes(original.title));
  await load(h, [original]);
  const pendingVote = deferred();
  h.enqueue(pendingVote.promise);
  const oldVote = findVote().fire('click');
  h.run("saveSession(null); saveSession({token: 'session-b', name: 'Another friend'});");
  // The first friend's new vote exists, but the current friend has not voted.
  await load(h, [{ ...original, votes: 2, voted: false }]);
  pendingVote.resolve(response({ suggestion: { ...original, votes: 2, voted: true } }));
  await oldVote;
  assert.equal(h.run('session.token'), 'session-b');
  assert.equal(findVote().getAttribute('aria-pressed'), 'false');
  assert.equal(findVote().textContent, '2');
});

test('an older list response cannot undo a subsequently confirmed vote', async () => {
  const h = harness();
  const original = suggestion(1, 'Xaeros World Map', { votes: 0, voted: false });
  const findVote = () => h.node('suggestions-list').descendants().find(item =>
    item.tagName === 'button' && item.getAttribute('aria-label')?.includes(original.title));
  await load(h, [original]);
  const pendingList = deferred();
  h.enqueue(pendingList.promise);
  const oldList = h.run('loadSuggestions()');
  h.enqueue(response({ suggestion: { ...original, votes: 1, voted: true } }));
  await findVote().fire('click');
  assert.equal(findVote().getAttribute('aria-pressed'), 'true');
  pendingList.resolve(response({ suggestions: [original] }));
  await oldList;
  assert.equal(findVote().getAttribute('aria-pressed'), 'true');
  assert.equal(findVote().textContent, '1');
  assert.equal(h.node('suggestions-list').getAttribute('aria-busy'), 'false');
});
