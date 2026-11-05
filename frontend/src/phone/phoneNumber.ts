// German mobile prefixes (without the leading 0)
const PREFIXES = [
  '151',
  '152',
  '157',
  '159',
  '160',
  '162',
  '163',
  '170',
  '171',
  '172',
  '176',
  '177',
]

// A random German mobile number to call from, e.g. "+49 151 23456789"
export function randomPhone(random: () => number = Math.random): string {
  const prefix = PREFIXES[Math.floor(random() * PREFIXES.length)] ?? '151'
  let subscriber = ''
  for (let digit = 0; digit < 8; digit++) {
    subscriber += String(Math.floor(random() * 10))
  }
  return `+49 ${prefix} ${subscriber}`
}

// Whether the backend will accept it as a German number (+49, 0049 or 0...)
export function isGermanPhone(value: string): boolean {
  const digits = value.replace(/[\s()/-]/g, '')
  return /^(\+49|0049|0)[1-9]\d{6,11}$/.test(digits)
}
