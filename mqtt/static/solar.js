'use strict';
const colors = ['#126da1', '#b14c17', '#7b40b7'];
const format = (v, digits = 2) => new Intl.NumberFormat('fi-FI', {maximumFractionDigits: digits}).format(v);
const clock = value => new Date(value).toLocaleTimeString('fi-FI', {hour:'2-digit', minute:'2-digit'});
const fullTime = value => new Date(value).toLocaleString('fi-FI');
const stale = value => Date.now() - Date.parse(value.time) > 120000;
function svgElement(name, attributes = {}, text) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, value);
  if (text !== undefined) el.textContent = text;
  return el;
}
function chart(metric, unit, data) {
  const target = document.getElementById(metric + '-chart');
  const points = data.phases.flatMap(p => p.series[metric]);
  if (!points.length) {
    const p = document.createElement('p'); p.className = 'empty';
    p.textContent = 'Ei mittauksia valitulla aikavälillä.'; target.replaceChildren(p); return;
  }
  const w = 900, h = 290, left = 75, right = 20, top = 16, bottom = 45;
  const start = Date.parse(data.start), end = Date.parse(data.end);
  let min = Math.min(...points.map(p => p.value)), max = Math.max(...points.map(p => p.value));
  const pad = Math.max((max - min) * .1, Math.abs(max) * .01, .1);
  min -= pad; max += pad;
  const x = time => left + (Date.parse(time) - start) / (end - start) * (w - left - right);
  const y = value => top + (max - value) / (max - min) * (h - top - bottom);
  const svg = svgElement('svg', {viewBox:`0 0 ${w} ${h}`, role:'img', 'aria-label':`${metric}, vaiheet L1–L3, ${unit}`});
  for (let i = 0; i <= 4; i++) {
    const value = min + (max - min) * i / 4, py = y(value);
    svg.append(svgElement('line', {x1:left, y1:py, x2:w-right, y2:py, stroke:'#e2e9ef'}));
    svg.append(svgElement('text', {x:left-10, y:py+4, 'text-anchor':'end'}, format(value, 1)));
    const time = new Date(start + (end-start) * i / 4).toISOString();
    svg.append(svgElement('text', {x:x(time), y:h-15, 'text-anchor':'middle'}, clock(time)));
  }
  data.phases.forEach((phase, index) => {
    let path = '', previous = null;
    phase.series[metric].forEach(point => {
      const gap = previous === null || Date.parse(point.time)-previous > data.bucket_seconds*1500;
      path += `${gap ? 'M' : 'L'}${x(point.time)},${y(point.value)} `;
      previous = Date.parse(point.time);
      const dot = svgElement('circle', {cx:x(point.time), cy:y(point.value), r:2.5, fill:colors[index], 'aria-hidden':'true'});
      dot.append(svgElement('title', {}, `L${phase.phase} · ${fullTime(point.time)} · ${format(point.value)} ${unit} · ${point.count} mittausta`));
      svg.append(dot);
    });
    svg.append(svgElement('path', {d:path, fill:'none', stroke:colors[index], 'stroke-width':2, 'pointer-events':'none', 'aria-hidden':'true'}));
  });
  target.replaceChildren(svg);
}
function latest(metric, unit, data) {
  const target = document.getElementById(metric + '-latest');
  target.replaceChildren(...data.phases.map((phase, index) => {
    const reading = phase.latest[metric], item = document.createElement('span');
    item.className = `latest-item l${index+1}`;
    item.textContent = `L${phase.phase}: ${reading ? format(reading.value) + ' ' + unit : '—'}`;
    const time = document.createElement('small');
    time.textContent = reading ? `${stale(reading) ? 'Vanha · ' : ''}${fullTime(reading.time)}` : 'Ei mittausta';
    item.append(time); return item;
  }));
}
function energy(data) {
  document.getElementById('energy').replaceChildren(...data.phases.map(phase => {
    const row = document.createElement('tr');
    const values = [`L${phase.phase}`];
    for (const metric of ['total', 'total_returned']) {
      const reading = phase.latest[metric];
      values.push(reading ? format(reading.value, 3) : '—', reading ? `${fullTime(reading.time)}${stale(reading) ? ' (vanha)' : ''}` : 'Ei mittausta');
    }
    for (const value of values) {const cell = document.createElement('td'); cell.textContent = value; row.append(cell);}
    return row;
  }));
}
let controller = null;
async function refresh() {
  if (controller) controller.abort();
  const active = new AbortController(); controller = active;
  const timeout = setTimeout(() => active.abort(), 15000);
  const status = document.getElementById('status');
  try {
    const hours = document.getElementById('hours').value;
    const response = await fetch(`${document.body.dataset.apiUrl}?hours=${hours}`, {signal:active.signal});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (controller !== active) return;
    for (const [metric, unit] of [['power','W'], ['current','A'], ['voltage','V']]) {
      chart(metric, unit, data); latest(metric, unit, data);
    }
    energy(data);
    status.className = data.mqtt_connected && data.subscribed ? '' : 'warning';
    status.textContent = `${data.mqtt_connected && data.subscribed ? 'MQTT yhdistetty' : 'MQTT-yhteyttä tai tilausta odotetaan'} · ${data.samples} mittausta · Päivitetty ${clock(data.end)}${data.samples ? '' : ' · Tarkista MQTT_TOPIC ja odota laitteen lähetystä.'}`;
    document.getElementById('device').textContent = data.device;
    document.getElementById('resolution').textContent = `Kuvaajien pisteet ovat ${data.bucket_seconds} sekunnin jaksojen näytekeskiarvoja. Lukuarvot ovat viimeisimmät mittaukset. Yli 2 minuuttia vanhat lukemat merkitään vanhoiksi. Päivitys 15 sekunnin välein.${data.skipped ? ` Ohitettu ${data.skipped} virheellistä arvoa.` : ''}`;
  } catch (error) {
    if (controller !== active) return;
    status.className = 'warning';
    status.textContent = `Päivitys epäonnistui (${error.name === 'AbortError' ? 'aikakatkaisu' : error.message}). Näkyvät tiedot voivat olla vanhentuneita.`;
  } finally {clearTimeout(timeout); if (controller === active) controller = null;}
}
document.getElementById('refresh').addEventListener('click', refresh);
document.getElementById('hours').addEventListener('change', refresh);
refresh();
setInterval(() => {if (!controller) refresh();}, 15000);
