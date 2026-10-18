import test from 'node:test';
import assert from 'node:assert/strict';
import { validateSource, configuration } from '../relay.mjs';

test('accept actual stream URLs and preserve signed query parameters', () => {
  assert.equal(validateSource(' rtsp://camera.example/live '), 'rtsp://camera.example/live');
  assert.equal(validateSource('https://video.example/live.m3u8?token=a%2Fb'), 'https://video.example/live.m3u8?token=a%2Fb');
});
test('reject webpages, files, bad payloads, and relay feedback loops', () => {
  for (const source of [null, {}, '', 'file:///etc/passwd', 'https://example.com/watch', 'http://example.com/video.mp4', 'rtsp://127.0.0.1:8554/firesight', 'rtmp://localhost:1935/firesight', 'rtsp://camera/live#bad']) assert.throws(() => validateSource(source));
});
test('source strings cannot inject YAML config', () => {
  const config = configuration('rtsp://camera/live\napiAddress: :1234');
  assert.ok(config.includes('source: "rtsp://camera/live\\napiAddress: :1234"'));
  assert.equal(config.match(/^apiAddress:/gm).length, 1);
  assert.ok(configuration(null).includes('source: "publisher"'));
  assert.throws(() => configuration(null, 'public.example'));
});
