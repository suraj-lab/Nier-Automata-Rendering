// Tests the reviewed state script only; never loads support.js, a browser, CDNs or game files.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = path.join(__dirname, '../menu-design/design_handoff_nier_render_panel/NieR Render Panel.dc.html');
const html = fs.readFileSync(source, 'utf8');
const matches = [...html.matchAll(/<script\s+type="text\/x-dc"\s+data-dc-script>([\s\S]*?)<\/script>/g)];
assert.equal(matches.length, 1);
const handlers = new Map();
class DCLogic {
  setState(update, callback) {
    Object.assign(this.state, typeof update === 'function' ? update(this.state) : update);
    if (callback) callback();
  }
}
const context = vm.createContext({
  DCLogic,
  React: { createRef: () => ({ current: null }) },
  window: {
    addEventListener: (name, callback) => handlers.set(name, callback),
    removeEventListener: (name, callback) => {
      if (handlers.get(name) === callback) handlers.delete(name);
    }
  }
}, { codeGeneration: { strings: false, wasm: false } });
vm.runInContext(matches[0][1] + '\nglobalThis.TestComponent = Component; globalThis.scenarios = SCEN;',
                context, { timeout: 1000 });
const make = () => new context.TestComponent();
let tested = 0;
function test(name, fn) { fn(); ++tested; console.log('PASS ' + name); }

test('initial state is clean', () => {
  const c = make();
  assert.equal(c.renderVals().nNone, true);
  assert.equal(c.renderVals().dirty, false);
});
test('edit and successful save do not change active rendering', () => {
  const c = make(); c.select('Native');
  assert.equal(c.state.saved, 'Custom75');
  assert.equal(c.renderVals().activeMode, 'Custom75');
  assert.equal(c.renderVals().renderDim, '2580×1080');
  assert.equal(c.renderVals().nDirty, true);
  c.renderVals().save();
  assert.equal(c.state.saved, 'Native');
  assert.equal(c.renderVals().activeMode, 'Custom75');
  assert.equal(c.renderVals().renderDim, '2580×1080');
  assert.equal(c.renderVals().nSaved, true);
});
test('failed save preserves prior saved value and edited selection', () => {
  const c = make(); c.select('Native'); c.setState({ saveFails: true }); c.renderVals().save();
  assert.equal(c.state.saved, 'Custom75'); assert.equal(c.state.edited, 'Native');
  assert.equal(c.renderVals().nError, true); assert.equal(c.renderVals().nSaved, false);
  c.setState({ saveFails: false }); c.renderVals().save();
  assert.equal(c.state.saved, 'Native'); assert.equal(c.renderVals().nSaved, true);
});
test('discard clears save error without undoing a completed save', () => {
  const c = make(); c.select('Native'); c.renderVals().save();
  c.select('Custom75'); c.setState({ saveFails: true }); c.renderVals().save(); c.renderVals().discard();
  assert.equal(c.state.saved, 'Native'); assert.equal(c.state.edited, 'Native');
  assert.equal(c.state.saveError, false); assert.equal(c.renderVals().nSaved, true);
});
test('close and reopen retain unsaved selection without saving', () => {
  const c = make(); c.select('Native'); c.close(); c.openPanel();
  assert.equal(c.state.saved, 'Custom75'); assert.equal(c.state.edited, 'Native');
  assert.equal(c.state.savedThisSession, false);
});
test('startup failure persists through a successful save and blanks dimensions', () => {
  const c = make(); c.setState({ startupFail: true }); c.select('Native'); c.renderVals().save();
  assert.equal(c.state.startupFail, true); assert.equal(c.renderVals().applied, false);
  assert.equal(c.renderVals().renderDim, '—'); assert.equal(c.renderVals().displayDim, '—');
});
test('capability fixture disables Custom75 and leaves Windows unknown size unknown', () => {
  const c = make(); c.load({ scenario: 'windows' }); c.select('Custom75');
  assert.equal(c.state.edited, 'Native'); assert.equal(c.renderVals().c75Disabled, true);
  assert.equal(c.renderVals().renderDim, '—');
});
test('changing capability data enables Custom75 without changing Windows scenario', () => {
  const c = make(); c.load({ scenario: 'windows' }); context.scenarios.windows.c75ok = true;
  try { c.select('Custom75'); assert.equal(c.state.edited, 'Custom75'); }
  finally { context.scenarios.windows.c75ok = false; }
});
test('Escape closes combo before panel; Insert reopens with edit intact', () => {
  const c = make(); c.componentDidMount(); c.select('Native'); c.openCombo();
  const key = key => handlers.get('keydown')({ key, preventDefault() {} });
  key('Escape'); assert.equal(c.state.comboOpen, false); assert.equal(c.state.open, true);
  key('Escape'); assert.equal(c.state.open, false);
  key('Insert'); assert.equal(c.state.open, true); assert.equal(c.state.edited, 'Native');
  c.componentWillUnmount(); assert.equal(handlers.size, 0);
});
test('saving back to active mode removes the restart notice', () => {
  const c = make(); c.select('Native'); c.renderVals().save();
  c.select('Custom75'); c.renderVals().save(); assert.equal(c.renderVals().nNone, true);
});

// Characterize export-only quirks; these are NOT requirements for the C++ implementation.
{
  const c = make(); c.select('Native'); c.setState({ saveFails: true });
  c.renderVals().save(); c.renderVals().save();
  assert.equal(c.state.saveFails, true); assert.equal(c.state.saveError, true);
  c.renderVals().toggleStartup(); assert.equal(c.state.startupFail, true);
  c.renderVals().toggleStartup(); assert.equal(c.state.startupFail, false);
}
console.log(JSON.stringify({ passed: true, scenarios: tested,
  known_export_quirks: ['Next save fails remains armed', 'Startup failure toggle can clear without restart'],
  limitations: 'state script only; no browser rendering, ImGui, filesystem writes or game integration tested' }));
