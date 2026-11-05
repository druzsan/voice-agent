import { SegmentedControl, Stack } from '@mantine/core'
import { useState } from 'react'

import { CareDesk } from './desk/CareDesk.tsx'
import { Phone } from './phone/Phone.tsx'

type View = 'phone' | 'desk'

export default function App() {
  const [view, setView] = useState<View>('phone')
  return (
    <Stack gap={0} align="center">
      <SegmentedControl
        mt="sm"
        size="xs"
        value={view}
        onChange={(value) => {
          setView(value)
        }}
        data={[
          { label: 'Phone', value: 'phone' },
          { label: 'Care desk', value: 'desk' },
        ]}
      />
      {/* The phone stays mounted, so switching views doesn't end a call */}
      <div hidden={view !== 'phone'} style={{ width: '100%' }}>
        <Phone />
      </div>
      {view === 'desk' && <CareDesk />}
    </Stack>
  )
}
