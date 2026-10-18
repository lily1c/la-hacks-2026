export function validateSource(input) {
  if (typeof input !== 'string' || input.length > 4096) throw new Error('Enter a video stream URL.');
  let url;
  try { url = new URL(input.trim()); } catch { throw new Error('Enter a complete URL including rtsp://, rtmp://, or https://.'); }
  if (!['rtsp:', 'rtsps:', 'rtmp:', 'rtmps:', 'http:', 'https:'].includes(url.protocol)) throw new Error('Supported sources: RTSP, RTMP, or an HTTP(S) HLS playlist.');
  if (!url.hostname || url.hash) throw new Error('The stream URL must have a host and no # fragment.');
  if (['http:', 'https:'].includes(url.protocol) && !url.pathname.endsWith('.m3u8')) throw new Error('For HTTP(S), use the direct .m3u8 playlist URL, not a webpage or MP4.');
  if (['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) && ['1935', '8554', '8888'].includes(url.port)) throw new Error('This points back to the local relay. Use the original source or publisher mode.');
  return url.href;
}

export function configuration(source, bind = '127.0.0.1') {
  if (!['127.0.0.1', '0.0.0.0'].includes(bind)) throw new Error('MEDIA_BIND must be 127.0.0.1 or 0.0.0.0');
  return `logLevel: warn
api: true
apiAddress: 127.0.0.1:9997
rtsp: true
rtspAddress: ${bind}:8554
rtspTransports: [tcp]
rtmp: true
rtmpAddress: ${bind}:1935
hls: true
hlsAddress: ${bind}:8888
hlsVariant: mpegts
hlsAllowOrigins: ["http://127.0.0.1:8787", "http://localhost:8787"]
webrtc: false
srt: false
moq: false
paths:
  firesight:
    source: ${JSON.stringify(source || 'publisher')}
    rtspTransport: tcp
`;
}
