// A small stand-in for the dashboard runtime (Claude's Data artifact type), so
// dashboard/index.html runs as a plain web page on made-up data. Loaders are
// skipped: demo-data.js already gives each source as rows.
(function () {
  const calcs = [];
  const draws = {};
  const results = {};
  const get = (id) => {
    if (results[id]) return results[id];
    const rows = (window.DEMO_DATA || {})[id];
    return rows ? { status: 'ok', data: rows, columns: rows.length ? Object.keys(rows[0]) : [] } : { status: 'missing', data: [] };
  };
  const drawAll = () => {
    document.querySelectorAll('[data-draw]').forEach((el) => {
      const fn = draws[el.getAttribute('data-draw')];
      if (!fn) return;
      try { fn(el); } catch (e) { console.error(el.getAttribute('data-draw'), e); }
    });
  };
  window.dash = {
    colors: [],
    loader() {},
    calc(id, o) { calcs.push({ id, inputs: o.inputs, fn: o.fn }); },
    draw(name, fn) { draws[name] = fn; },
    data: get,
    onData(fn) { window.addEventListener('dash-demo-ready', () => fn()); },
    refresh() {}, params: () => ({}), setParams() {}, resetParams() {}, setLink() {},
  };
  window.addEventListener('load', () => {
    calcs.forEach(({ id, inputs, fn }) => {
      try { results[id] = { status: 'ok', data: fn(...inputs.map((i) => get(i).data)) }; }
      catch (e) { console.error(id, e); results[id] = { status: 'error', data: null, message: String(e) }; }
    });
    drawAll();
    window.dispatchEvent(new Event('dash-demo-ready'));
    let timer;
    window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(drawAll, 150); });
  });
})();
