/** ServiceWhy mark: a receipt with a question mark ("why", backed by a receipt). The product motif is "No receipt, no claim." */
export function Logo({ className = "size-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={`shrink-0 ${className}`} aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" className="fill-accent" />
      <path className="fill-accent-fg" d="M9 7h14v18l-2.33-2-2.34 2L16 23l-2.33 2-2.34-2L9 25z" />
      <path className="stroke-accent" fill="none" strokeWidth="1.8" strokeLinecap="round" d="M13.6 12.4a2.4 2.4 0 1 1 3.6 2.1c-.8.5-1.2 1-1.2 1.9" />
      <circle cx="16" cy="19.2" r="1.05" className="fill-accent" />
    </svg>
  );
}

/** Logo plus the two-tone wordmark; the link name stays "ServiceWhy". */
export function Wordmark({ className = "text-xl" }: { className?: string }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <Logo />
      <span className={`font-semibold tracking-tight text-ink ${className}`}>
        Service<span className="text-accent-ink">Why</span>
      </span>
    </span>
  );
}
