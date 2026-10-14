'use strict';
let loading = false;
async function refresh() {
  if (loading) return;
  loading = true;
  try {
    const response = await fetch(document.body.dataset.apiUrl, {signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    document.getElementById('status').textContent =
      (data.subscribed && data.mqtt_connected ? 'MQTT yhdistetty.' : 'MQTT-yhteyttä tai topicin tilausta odotetaan.') +
      ` Näytetään ${data.messages.length} viestiä.`;
    const rows = data.messages.map(item => {
      const tr = document.createElement('tr');
      let payload = item.payload;
      if (item.encoding === 'base64') payload = '[base64] ' + payload;
      else { try { payload = JSON.stringify(JSON.parse(payload), null, 2); } catch {} }
      for (const [i, value] of [new Date(item.received_at).toLocaleString('fi-FI'), item.topic, payload, `${item.qos} / ${item.retained ? 'kyllä' : 'ei'}`].entries()) {
        const td = document.createElement('td');
        const el = i === 2 ? document.createElement('pre') : td;
        el.textContent = value;
        if (el !== td) td.append(el);
        tr.append(td);
      }
      return tr;
    });
    document.getElementById('messages').replaceChildren(...rows);
  } catch (error) {
    document.getElementById('status').textContent = 'Päivitys epäonnistui: ' + error.message + '. Näkyvät tiedot voivat olla vanhentuneita.';
  } finally { loading = false; }
}
document.getElementById('refresh').addEventListener('click', refresh);
refresh();
setInterval(refresh, 5000);
