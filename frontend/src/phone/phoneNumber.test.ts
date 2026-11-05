import { describe, expect, it } from 'vitest'

import { isGermanPhone, randomPhone } from './phoneNumber.ts'

describe('randomPhone', () => {
  it('makes German mobile numbers', () => {
    for (let i = 0; i < 50; i++) {
      const number = randomPhone()
      expect(number).toMatch(/^\+49 1\d{2} \d{8}$/)
      expect(isGermanPhone(number)).toBe(true)
    }
  })

  it('differs from call to call', () => {
    expect(new Set(Array.from({ length: 20 }, () => randomPhone())).size).toBeGreaterThan(1)
  })
})

describe('isGermanPhone', () => {
  it.each(['+49 151 22000201', '0049 151 22000201', '0151 22000201', '+49 (151) 220-002'])(
    'accepts %s',
    (number) => {
      expect(isGermanPhone(number)).toBe(true)
    },
  )

  it.each(['', '12345', '+44 20 7946 0958', 'call me'])('rejects %s', (number) => {
    expect(isGermanPhone(number)).toBe(false)
  })
})
