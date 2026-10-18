const $ = id => document.getElementById(id);
let lastRevision = -1;
function feedback(text, error = false) { $('feedback').textContent = text; $('feedback').classList.toggle('error', error); }
function tab(pull) {
  $('source-form').hidden = !pull; $('publisher').hidden = pull;
  $('pull-tab').classList.toggle('selected', pull); $('publish-tab').classList.toggle('selected', !pull);
}
$('pull-tab').onclick = () => tab(true);
$('publish-tab').onclick = () => tab(false);
async function configure(path, data) {
  $('connect').disabled = $('enable-publish').disabled = true;
  feedback('Configuring receiver…');
  try {
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    feedback('Configuration accepted. Live status below confirms when media arrives.');
    await refresh();
  } catch (error) { feedback(error.message, true); }
  finally { $('connect').disabled = $('enable-publish').disabled = false; }
}
$('source-form').onsubmit = event => { event.preventDefault(); configure('/api/source', { url: $('url').value }); };
$('enable-publish').onclick = () => configure('/api/publisher', {});
document.querySelectorAll('[data-copy]').forEach(button => button.onclick = async () => {
  try { await navigator.clipboard.writeText($(button.dataset.copy).textContent); button.textContent = 'Copied'; setTimeout(() => button.textContent = 'Copy', 1500); }
  catch { feedback('Select the address and copy it manually.', true); }
});
async function refresh() {
  try {
    const response = await fetch('/api/status');
    if (!response.ok) throw new Error('Status unavailable');
    const state = await response.json();
    $('badge').textContent = state.ready ? '● RECEIVING' : state.relayRunning ? 'WAITING' : 'OFFLINE';
    $('relay').textContent = state.relayRunning ? 'Running' : 'Unavailable';
    $('tracks').textContent = state.tracks.join(', ') || '—';
    $('bytes').textContent = (state.bytesReceived / 1e6).toFixed(2) + ' MB';
    $('readers').textContent = state.readers;
    $('screen-title').textContent = !state.relayRunning ? 'Video relay offline' : state.configured ? 'Connecting to source' : 'Waiting for video';
    $('screen-message').textContent = state.message;
    $('lan').textContent = state.lanEnabled ? `LAN enabled. Replace 127.0.0.1 with your Mac's reachable IP: ${state.lanIPs.join(', ')}. Teammates must be on the same network.` : 'Local access only. Start with MEDIA_BIND=0.0.0.0 npm start to allow LAN video connections.';
    if (state.ready && ($('player').hidden || state.revision !== lastRevision)) $('player').src = state.urls.player;
    $('player').hidden = !state.ready; $('empty').hidden = state.ready;
    if (!state.ready) $('player').removeAttribute('src');
    lastRevision = state.revision;
  } catch { $('badge').textContent = 'OFFLINE'; $('relay').textContent = 'Unavailable'; $('player').hidden = true; $('player').removeAttribute('src'); $('empty').hidden = false; $('screen-title').textContent = 'Receiver offline'; $('screen-message').textContent = 'Start the local receiver with npm start.'; }
}
async function poll() { await refresh(); setTimeout(poll, 2000); }
poll();
