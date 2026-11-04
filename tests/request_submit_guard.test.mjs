// Exercise the actual form submit handler with offline dependencies only.
// No browser, real token, timer, fetch, model call or service is used.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../web/src/components/RequestBox.tsx', import.meta.url), 'utf8');
const start = source.indexOf('  async function submit(');
const end = source.indexOf('\n  const kindWords', start);
assert.ok(start >= 0 && end > start, 'The inspected submit boundaries must exist');
let handler = source.slice(start, end);
for (const [from, to] of [
  ['event: FormEvent<HTMLFormElement>', 'event'],
  ['querySelector<HTMLElement>', 'querySelector'],
  [' as { key?: string; principal_id?: string; profile?: { organization_type: string } }', ''],
  ['(path: string, body: unknown, shared = false)', '(path, body, shared = false)'],
]) {
  assert.equal(handler.split(from).length - 1, 1, `Reinspect the TypeScript annotation: ${from}`);
  handler = handler.replace(from, to);
}

function fixture({ wait = 0, matches = false, rejectLookupOnce = false } = {}) {
  const calls = [], sending = [], problems = [], navigations = [];
  let release, lookupCalls = 0;
  const lookup = new Promise(resolve => { release = resolve; });
  class SendError extends Error {}
  const ok = value => ({ status: 200, ok: true, json: async () => value });
  const state = {
    submitting: { current: false }, waitingUntil: wait,
    setTried() {}, setProblem(value) { problems.push(value); },
    unmet: [], box: { current: null }, SNAPSHOT: false,
    navigator: { onLine: true },
    draft: { text: 'Example public grant deadlines', name: 'Example group', type: 'Community group', causes: '', links: '', frequency: 'one-off', cadence: '' },
    newRequest: { current: false },
    acceptUnaudited: false,
    fetchCachedLibrary() { lookupCalls++; return rejectLookupOnce && lookupCalls === 1 ? Promise.reject(new Error('Fixture lookup failed')) : lookup; },
    searchLibrary() { return matches ? [{ id: 'fixture-process', title: 'An existing example' }] : []; },
    setHits(value) { state.hits = value; },
    setSending(value) { sending.push(value); },
    minted: { current: null }, FABRIC_PUBLIC_URL: 'https://fixture.invalid',
    async fetch(url, options) {
      const path = new URL(url).pathname;
      calls.push({ path, body: JSON.parse(options.body) });
      if (path === '/v1/session/requester') return ok({ key: 'fixture-key', principal_id: 'fixture-principal', profile: { organization_type: 'Community group' } });
      if (path.startsWith('/v1/stores/')) return ok({ version: 1 });
      if (path === '/v1/tasks') return ok({ task_id: JSON.parse(options.body).task_id });
      throw new Error('Unexpected fixture route');
    },
    failure: async () => new SendError('Fixture failure'),
    outputs: ['information'], prefs: {}, prefsBrief: () => null, improvedRequest: () => null,
    page: { frequency: { default_cadence: 'weekly' }, advanced: {}, states: { snapshot: 'Fixture snapshot' } },
    Date: { now: () => 1793640000000 },
    rememberKey() {}, rememberSent() {}, EMPTY: {}, setDraft() {}, saveDraft() {},
    navigateWithTransition(url) { navigations.push(url); }, flushSync: fn => fn(), SendError, Error,
    hits: null,
  };
  const submit = vm.runInNewContext(`${handler}\nsubmit`, state, { timeout: 1000 });
  return { state, calls, sending, problems, navigations, release: () => release([]), submit: () => submit({ preventDefault() {} }), lookups: () => lookupCalls };
}

test('one normal intention saves and enqueues once, then clears the attempt guard', async () => {
  const f = fixture(); f.release(); await f.submit();
  assert.equal(f.calls.length, 3); assert.equal(f.navigations.length, 1);
  assert.equal(f.state.submitting.current, false); assert.deepEqual(f.sending, [true, false]);
});

test('duplicate activations during a held library read share one attempt', async () => {
  const f = fixture(); const first = f.submit(); const second = f.submit();
  assert.equal(f.state.submitting.current, true); assert.deepEqual(f.sending, [true]);
  assert.equal(f.lookups(), 1); f.release(); await Promise.all([first, second]);
  assert.equal(f.calls.length, 3); assert.equal(f.calls.filter(c => c.path === '/v1/tasks').length, 1);
  assert.equal(f.navigations.length, 1); assert.equal(f.state.submitting.current, false);
});

test('a live rate or quota deadline preserves the message and makes no request', async () => {
  const f = fixture({ wait: 1793640000 + 3600 }); f.release(); await f.submit();
  assert.equal(f.lookups(), 0); assert.equal(f.calls.length, 0); assert.deepEqual(f.problems, []);
  assert.deepEqual(f.sending, []); assert.equal(f.state.submitting.current, false);
});

test('an expired wait does not block a new intention', async () => {
  const f = fixture({ wait: 1793640000 - 1 }); f.release(); await f.submit();
  assert.equal(f.calls.length, 3); assert.equal(f.state.submitting.current, false);
});

test('a library match releases the guard and allows intentional send-anyway', async () => {
  const f = fixture({ matches: true }); f.release(); await f.submit();
  assert.equal(f.state.hits.length, 1); assert.equal(f.calls.length, 0);
  assert.equal(f.state.submitting.current, false); assert.deepEqual(f.sending, [true, false]);
  f.state.newRequest.current = true; await f.submit();
  assert.equal(f.calls.length, 3); assert.equal(f.lookups(), 1);
});

test('a failed library read shows a problem, releases the guard and permits retry', async () => {
  const f = fixture({ rejectLookupOnce: true }); f.release(); await f.submit();
  assert.equal(f.calls.length, 0); assert.equal(f.state.submitting.current, false);
  assert.equal(f.problems.at(-1).kind, 'refused'); assert.equal(f.problems.at(-1).filed, false);
  await f.submit(); assert.equal(f.calls.length, 3); assert.equal(f.state.submitting.current, false);
});

test('validation and offline exits never leave an attempt locked', async () => {
  const f = fixture(); f.release(); f.state.unmet = ['need']; await f.submit();
  assert.equal(f.calls.length, 0); assert.equal(f.state.submitting.current, false);
  f.state.unmet = []; f.state.navigator.onLine = false; await f.submit();
  assert.equal(f.calls.length, 0); assert.equal(f.state.submitting.current, false);
  f.state.navigator.onLine = true; await f.submit(); assert.equal(f.calls.length, 3);
});
