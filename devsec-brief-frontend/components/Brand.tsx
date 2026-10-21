"use client";

export function ShieldIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 3l7 2.8v5.4c0 4.4-2.9 8.3-7 9.8-4.1-1.5-7-5.4-7-9.8V5.8L12 3z" />
      <path d="M9.5 11.5l1.8 1.8 3.4-3.6" />
    </svg>
  );
}

export function BrandMark({ size = 36 }: { size?: number }) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-[10px]"
      style={{
        width: size,
        height: size,
        background: "var(--brand)",
        color: "var(--brand-text)",
      }}
    >
      <ShieldIcon size={Math.round(size * 0.52)} />
    </div>
  );
}
