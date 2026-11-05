import { SimpleGrid, Stack, Text, UnstyledButton } from '@mantine/core'

import classes from './Phone.module.css'

const KEYS: readonly (readonly [string, string])[] = [
  ['1', ''],
  ['2', 'ABC'],
  ['3', 'DEF'],
  ['4', 'GHI'],
  ['5', 'JKL'],
  ['6', 'MNO'],
  ['7', 'PQRS'],
  ['8', 'TUV'],
  ['9', 'WXYZ'],
  ['*', ''],
  ['0', '+'],
  ['#', ''],
]

interface KeypadProps {
  onKey: (key: string) => void
  disabled: boolean
}

export function Keypad({ onKey, disabled }: KeypadProps) {
  return (
    <SimpleGrid cols={3} spacing="xs" verticalSpacing="xs" className={classes['keypad']}>
      {KEYS.map(([key, letters]) => (
        <UnstyledButton
          key={key}
          className={classes['key']}
          disabled={disabled}
          aria-label={key === '#' ? '# (send)' : key}
          onClick={() => {
            onKey(key)
          }}
        >
          <Stack gap={0} align="center">
            <Text fz={22} fw={500} lh={1.1}>
              {key}
            </Text>
            <Text fz={9} c="dimmed" lh={1} h={9}>
              {key === '#' ? 'SEND' : letters}
            </Text>
          </Stack>
        </UnstyledButton>
      ))}
    </SimpleGrid>
  )
}
