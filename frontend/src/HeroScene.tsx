/**
 * The product in one picture: grid on the left, a car on the right, and energy
 * that only flows when the hours are clean.
 *
 * Inline SVG rather than a WebGL scene — it is a few kB, scales to any width,
 * and every element is a real DOM node so it inherits the theme's colours. The
 * carbon arc across the top is the actual shape of a Spanish night: high in the
 * evening, dipping after midnight, which is exactly why the schedule shifts.
 */
export default function HeroScene({ reduced }: { reduced?: boolean }) {
  const anim = !reduced;
  return (
    <svg className="heroScene" viewBox="0 0 720 260" role="img"
      aria-label="A pylon feeding a charging post and an electric car, with energy flowing during the cleanest hours of the night">
      <defs>
        <linearGradient id="gsCable" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#d95926" />
          <stop offset="55%" stopColor="#7a6fa0" />
          <stop offset="100%" stopColor="#3987e5" />
        </linearGradient>
        <linearGradient id="gsBody" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2b3648" />
          <stop offset="100%" stopColor="#161d28" />
        </linearGradient>
        <linearGradient id="gsArc" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#d95926" stopOpacity=".85" />
          <stop offset="45%" stopColor="#8a6f7a" stopOpacity=".5" />
          <stop offset="70%" stopColor="#3987e5" stopOpacity=".9" />
          <stop offset="100%" stopColor="#3987e5" stopOpacity=".5" />
        </linearGradient>
        <radialGradient id="gsGlow">
          <stop offset="0%" stopColor="#3987e5" stopOpacity=".55" />
          <stop offset="100%" stopColor="#3987e5" stopOpacity="0" />
        </radialGradient>
        <filter id="gsSoft" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
      </defs>

      {/* Carbon intensity across the night — the signal being scheduled against */}
      <path d="M40 62 C 150 34, 250 40, 330 74 S 500 132, 600 118 S 680 96, 700 88"
        fill="none" stroke="url(#gsArc)" strokeWidth="2.5" strokeLinecap="round" />
      <text x="40" y="46" className="hsTick">18:00 · dirty</text>
      <text x="558" y="146" className="hsTick">03:00 · clean</text>
      {anim && (
        <circle r="3.5" fill="#3987e5">
          <animateMotion dur="7s" repeatCount="indefinite" rotate="auto"
            path="M40 62 C 150 34, 250 40, 330 74 S 500 132, 600 118 S 680 96, 700 88" />
          <animate attributeName="opacity" values="0;1;1;0" dur="7s" repeatCount="indefinite" />
        </circle>
      )}

      {/* Transmission pylon */}
      <g stroke="#3d4c62" strokeWidth="2" fill="none" strokeLinecap="round">
        <path d="M78 232 L96 132 M136 232 L118 132" />
        <path d="M96 132 L118 132" />
        <path d="M84 196 L130 196 M88 172 L126 172" />
        <path d="M72 152 L142 152" />
        <path d="M72 152 L60 146 M142 152 L154 146" />
        <path d="M92 108 L107 96 L122 108" />
      </g>
      {/* Lines running off to the wider grid */}
      <path d="M0 138 C 30 150, 50 150, 72 152" stroke="#33415a" strokeWidth="1.5" fill="none" />
      <path d="M142 152 C 200 158, 250 176, 300 186" stroke="#33415a" strokeWidth="1.5" fill="none" />

      {/* Charging post */}
      <rect x="316" y="150" width="26" height="82" rx="6" fill="url(#gsBody)" stroke="#3d4c62" />
      <rect x="322" y="160" width="14" height="18" rx="3" fill="#0d131c" stroke="#3d4c62" />
      <circle cx="329" cy="169" r="3" fill="#3987e5">
        {anim && <animate attributeName="opacity" values=".25;1;.25" dur="2.4s" repeatCount="indefinite" />}
      </circle>

      {/* Cable: post to car */}
      <path id="gsCablePath" d="M342 186 C 386 214, 424 214, 468 190"
        fill="none" stroke="url(#gsCable)" strokeWidth="3.5" strokeLinecap="round" />
      {anim && [0, 1, 2].map((i) => (
        <circle key={i} r="3" fill="#7fb4f5">
          <animateMotion dur="2.2s" begin={`${i * 0.73}s`} repeatCount="indefinite"
            path="M342 186 C 386 214, 424 214, 468 190" />
        </circle>
      ))}

      {/* Car */}
      <ellipse cx="576" cy="236" rx="118" ry="10" fill="url(#gsGlow)" filter="url(#gsSoft)" />
      <path d="M486 206 L494 176 C 500 160, 512 152, 530 150 L618 150
               C 636 152, 650 160, 660 176 L668 206 Z"
        fill="url(#gsBody)" stroke="#4a5a72" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M508 176 C 514 164, 522 160, 534 159 L612 159
               C 626 160, 634 165, 640 176 Z" fill="#0e141d" stroke="#3d4c62" />
      <rect x="486" y="200" width="182" height="12" rx="6" fill="#1a2230" stroke="#3d4c62" />
      <circle cx="518" cy="214" r="17" fill="#0d131c" stroke="#4a5a72" strokeWidth="2" />
      <circle cx="636" cy="214" r="17" fill="#0d131c" stroke="#4a5a72" strokeWidth="2" />
      <circle cx="518" cy="214" r="6" fill="#2b3648" />
      <circle cx="636" cy="214" r="6" fill="#2b3648" />

      {/* Charge port, taking current */}
      <rect x="472" y="182" width="12" height="14" rx="3" fill="#0d131c" stroke="#3987e5" />

      {/* State of charge on the flank */}
      <rect x="536" y="182" width="70" height="11" rx="3" fill="#0b111a" stroke="#3d4c62" />
      <rect x="538" y="184" width="20" height="7" rx="2" fill="#3987e5">
        {anim && <animate attributeName="width" values="8;66;8" dur="6.5s" repeatCount="indefinite" />}
      </rect>
    </svg>
  );
}
