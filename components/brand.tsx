import Link from "next/link";
export function Melon({ size = 38 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M5 15c0 16 9 27 21 27s20-11 20-27H5Z" fill="#FFD84D" stroke="#111" strokeWidth="2.5" transform="rotate(-18 24 24)"/><path d="M7 12c0 15 8 24 19 24s18-9 18-24H7Z" fill="#FF4778" stroke="#111" strokeWidth="2.5" transform="rotate(-18 24 24)"/><path d="m15 19 1 3m10-6 1 4m9-6 1 3m-13 8 1 3" stroke="#111" strokeWidth="3" strokeLinecap="round"/></svg>;
}
export function Brand({ compact = false }: { compact?: boolean }) { return <Link className="brand" href="/" aria-label="Watermelon home"><Melon />{!compact && <span>watermelon<span className="brand-period">.</span></span>}</Link>; }
