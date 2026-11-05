// Small line icons (24×24, current color)

interface IconProps {
  size?: number
}

function Icon({ size = 24, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export function PhoneIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />
    </Icon>
  )
}

export function HangUpIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <g transform="rotate(135 12 12)">
        <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />
      </g>
    </Icon>
  )
}

export function MicIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 17v4M8 21h8" />
    </Icon>
  )
}

export function MicOffIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M9 9V5a3 3 0 0 1 5.7-1.3M15 10v1a3 3 0 0 1-4.6 2.5" />
      <path d="M5 10a7 7 0 0 0 11.2 5.6M19 10a7 7 0 0 1-.6 2.8M12 17v4M8 21h8M3 3l18 18" />
    </Icon>
  )
}

export function SendIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 14 21 3M21 3l-6.5 18a.55.55 0 0 1-1 0L10 14l-7-3.5a.55.55 0 0 1 0-1z" />
    </Icon>
  )
}

export function KeypadIcon(props: IconProps) {
  return (
    <Icon {...props}>
      {[5, 12, 19].flatMap((y) =>
        [5, 12, 19].map((x) => <circle key={`${String(x)}-${String(y)}`} cx={x} cy={y} r={1.5} />),
      )}
    </Icon>
  )
}

export function KeyboardIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10" />
    </Icon>
  )
}
