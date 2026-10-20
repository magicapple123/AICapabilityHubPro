/** Reverses a legacy UTF-8/Windows-1252 display mismatch without writing source data. */
const legacyDecoder = new TextDecoder('windows-1252')
const utf8Decoder = new TextDecoder('utf-8', { fatal: true })
const byteForCharacter = new Map(Array.from({ length: 256 }, (_, byte) =>
  [legacyDecoder.decode(Uint8Array.of(byte)), byte] as const))

export function displayText(value: string) {
  if (!value || /[\u3400-\u9fff]/.test(value) || !/[ÃÂâäæåçèé]/.test(value)) return value
  const bytes: number[] = []
  for (const character of value) {
    const byte = byteForCharacter.get(character)
    if (byte === undefined) return value
    bytes.push(byte)
  }
  try {
    const decoded = utf8Decoder.decode(Uint8Array.from(bytes))
    return /[\u3400-\u9fff]/.test(decoded) ? decoded : value
  } catch { return value }
}
export function legacySearchText(value: string) {
  return /[\u3400-\u9fff]/.test(value) ? legacyDecoder.decode(new TextEncoder().encode(value)) : value
}
