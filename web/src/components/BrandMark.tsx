export function BrandMark({ inverse = false }: { inverse?: boolean }) {
  return <span className={'brand-mark' + (inverse ? ' brand-inverse' : '')}>
    <span className="brand-symbol">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="2.8" y="2.8" width="11.4" height="11.4" rx="2.8" fill="currentColor" opacity=".32" />
        <rect x="7.2" y="7.2" width="11.4" height="11.4" rx="2.8" fill="currentColor" opacity=".6" />
        <rect x="11.6" y="11.6" width="9.6" height="9.6" rx="2.4" fill="currentColor" />
      </svg>
    </span>
    <span className="brand-wordmark">CapabilityHub<span className="brand-edition">Pro</span></span>
  </span>
}
