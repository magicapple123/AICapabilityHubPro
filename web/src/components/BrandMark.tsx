import { Layers3 } from 'lucide-react'

export function BrandMark({ inverse = false }: { inverse?: boolean }) {
  return <span className={'brand-mark' + (inverse ? ' brand-inverse' : '')}>
    <span className="brand-symbol"><Layers3 size={18} strokeWidth={1.7} /></span>
    <span className="brand-wordmark">CapabilityHub<span className="brand-edition">Pro</span></span>
  </span>
}
