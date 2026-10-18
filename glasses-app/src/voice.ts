// Glasses MIC delivers 16 kHz, 16-bit, mono PCM frames.
export const SAMPLE_RATE = 16000

// Wrap raw PCM chunks in a WAV header so any backend/transcription API can read it.
export function pcmToWav(chunks: Uint8Array[], sampleRate = SAMPLE_RATE): Blob {
  const dataLength = chunks.reduce((n, c) => n + c.length, 0)
  const header = new DataView(new ArrayBuffer(44))
  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) header.setUint8(offset + i, s.charCodeAt(i))
  }

  writeStr(0, 'RIFF')
  header.setUint32(4, 36 + dataLength, true)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  header.setUint32(16, 16, true)             // fmt chunk size
  header.setUint16(20, 1, true)              // PCM
  header.setUint16(22, 1, true)              // mono
  header.setUint32(24, sampleRate, true)
  header.setUint32(28, sampleRate * 2, true) // byte rate
  header.setUint16(32, 2, true)              // block align
  header.setUint16(34, 16, true)             // bits per sample
  writeStr(36, 'data')
  header.setUint32(40, dataLength, true)

  return new Blob([header.buffer, ...chunks.map((c) => c.slice().buffer)], { type: 'audio/wav' })
}

export function pcmSeconds(chunks: Uint8Array[], sampleRate = SAMPLE_RATE): number {
  return chunks.reduce((n, c) => n + c.length, 0) / (sampleRate * 2)
}
