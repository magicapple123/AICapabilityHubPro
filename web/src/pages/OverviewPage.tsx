import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { ArrowDownRight, ArrowUpRight, CircleCheck, Sparkles, Zap } from 'lucide-react'
import { useRef } from 'react'
import { useNavigate } from 'react-router-dom'

gsap.registerPlugin(ScrollTrigger)

const capabilityCards = [
  { name: '多轮对话', desc: '按能力提交消息，核对回复与实际费用', meta: 'CHAT · 受控执行', route: '/chat?capability_id=1', tone: 'from-[#d6f77b] to-[#6e8d28]', image: 'https://picsum.photos/seed/vision/1200/900', span: 'md:col-span-6 md:row-span-2' },
  { name: '文本摘要', desc: '独立文本输入，按摘要能力的目录单价执行', meta: 'SUMMARY · 独立输入', route: '/chat?capability_id=2', tone: 'from-[#eeece1] to-[#94998a]', image: 'https://picsum.photos/seed/abstract/900/900', span: 'md:col-span-6 md:row-span-2' },
  { name: 'Schema 输入', desc: '参数要求可查看，不兼容输入在执行前拒绝', meta: 'SCHEMA · 参数校验', route: '/chat', tone: 'from-[#bad5ff] to-[#506881]', image: 'https://picsum.photos/seed/sound/900/650', span: 'md:col-span-4' },
  { name: '按能力计费', desc: '目录价格贯穿积分预检、账单与余额核验', meta: 'BILLING · 实际费用', route: '/usage', tone: 'from-[#f7b18a] to-[#704c40]', image: 'https://picsum.photos/seed/knowledge/900/650', span: 'md:col-span-4' },
  { name: '调用追踪', desc: '通过 requestId 关联结果、账单和积分流水', meta: 'TRACE · 调用核验', route: '/usage', tone: 'from-[#d4b0ff] to-[#5a4e70]', image: 'https://picsum.photos/seed/data/900/650', span: 'md:col-span-4' },
]

export function OverviewPage() {
  const navigate = useNavigate()
  const page = useRef<HTMLDivElement>(null)
  useGSAP(() => {
    const intro = gsap.timeline()
    intro.from('.hero-reveal', { y: 32, opacity: 0, duration: 0.8, stagger: 0.08, ease: 'power3.out' })
    gsap.from('.scroll-card', { scale: 0.8, opacity: 0.2, duration: 1, stagger: 0.12, ease: 'power3.out', scrollTrigger: { trigger: '.scroll-gallery', start: 'top 75%', end: 'bottom 30%', scrub: true } })
    gsap.to('.pinned-copy', { opacity: 1, scrollTrigger: { trigger: '.desire-section', start: 'top 20%', end: 'bottom 70%', scrub: true, pin: '.pinned-copy' } })
    gsap.fromTo('.word-reveal', { opacity: 0.1 }, { opacity: 1, stagger: 0.08, scrollTrigger: { trigger: '.word-reveal-wrap', start: 'top 75%', end: 'bottom 45%', scrub: true } })
    return () => intro.kill()
  }, { scope: page })

  return <div ref={page} className="bg-[#11130f]">
    <section className="relative mx-auto grid min-h-[calc(100vh-88px)] w-full max-w-[1500px] items-center gap-14 px-5 pb-28 pt-16 md:grid-cols-[1.05fr_.95fr] md:px-10 md:pb-40 md:pt-20">
      <div className="relative z-10">
        <p className="hero-reveal mb-7 flex items-center gap-2 text-xs uppercase tracking-[0.28em] text-[#c9f05b]"><span className="h-2 w-2 rounded-full bg-[#c9f05b]" />AICAPABILITYHUB PRO</p>
        <h1 className="hero-reveal max-w-6xl text-[clamp(3rem,6vw,6rem)] font-medium leading-[.94] tracking-[-.07em] text-[#f4f4ef]">选定一种能力，<span className="text-[#c9f05b]">看清</span><br />每一次调用。</h1>
        <p className="hero-reveal mt-8 max-w-xl text-base leading-7 text-white/55 md:text-lg">面向开发者的 AI 能力执行与计量平台。选择聊天或文本摘要，按 Schema 输入，核对实际积分、账单与 requestId。</p>
        <div className="hero-reveal mt-10 flex flex-wrap gap-3"><button onClick={() => navigate('/capabilities')} className="group flex items-center gap-3 rounded-full bg-[#c9f05b] px-6 py-3 text-sm font-semibold text-[#11130f] transition hover:bg-white">查看能力目录 <ArrowUpRight size={16} className="transition group-hover:translate-x-1 group-hover:-translate-y-1" /></button><button onClick={() => navigate('/chat')} className="rounded-full border border-white/20 px-6 py-3 text-sm text-white transition hover:border-[#c9f05b] hover:text-[#c9f05b]">打开调试台</button></div>
      </div>
      <div className="hero-reveal relative min-h-[440px] overflow-hidden rounded-[2rem] bg-[#22271e] md:min-h-[590px]"><img className="absolute inset-0 h-full w-full object-cover grayscale contrast-125 opacity-70 mix-blend-luminosity" src="https://picsum.photos/seed/ai-lab/1200/1500" alt="抽象的 AI 实验室光影" /><div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(201,240,91,.72),transparent_32%),linear-gradient(135deg,rgba(17,19,15,.1),rgba(17,19,15,.88))]" /><div className="absolute bottom-6 left-6 right-6 flex items-end justify-between"><div><p className="mb-2 text-xs uppercase tracking-[0.2em] text-white/60">Capability execution</p><p className="max-w-xs text-2xl leading-tight text-white">参数、费用与结果，沿同一条调用链核验。</p></div><span className="flex h-12 w-12 items-center justify-center rounded-full bg-white text-[#11130f]"><ArrowDownRight size={20} /></span></div></div>
    </section>
    <section className="border-y border-white/10 py-6"><div className="mx-auto flex max-w-[1500px] gap-12 overflow-hidden px-5 text-xs uppercase tracking-[0.24em] text-white/35 md:px-10"><div className="flex min-w-max gap-12 animate-[marquee_24s_linear_infinite]"><span>CAPABILITY-DRIVEN</span><span>SCHEMA INPUT</span><span>PER-CAPABILITY BILLING</span><span>REQUEST TRACE</span><span>CONTROLLED EXECUTORS</span><span>CHAT &amp; SUMMARY</span><span>ISOLATED E2E</span></div></div></section>
    <section className="mx-auto max-w-[1500px] px-5 py-32 md:px-10 md:py-48"><div className="mb-12 flex items-end justify-between gap-8"><div><p className="mb-4 text-sm text-[#c9f05b]">Pro 的执行与核验能力</p><h2 className="max-w-3xl text-4xl font-medium tracking-[-.05em] text-[#f4f4ef] md:text-6xl">从输入要求，到费用与结果。</h2></div><button onClick={() => navigate('/capabilities')} className="hidden items-center gap-2 text-sm text-white/55 transition hover:text-[#c9f05b] md:flex">查看能力目录 <ArrowUpRight size={16} /></button></div><div className="grid grid-flow-dense gap-3 md:grid-cols-12 md:grid-rows-4">{capabilityCards.map((card) => <button key={card.name} onClick={() => navigate(card.route)} className={`scroll-card group relative min-h-[270px] overflow-hidden rounded-[1.5rem] bg-gradient-to-br ${card.tone} p-6 text-left ${card.span}`}><img className="absolute inset-0 h-full w-full object-cover opacity-25 grayscale transition duration-700 group-hover:scale-105 group-hover:opacity-40" src={card.image} alt="" /><div className="absolute inset-0 bg-gradient-to-t from-[#11130f]/85 via-transparent to-transparent" /><div className="relative flex h-full flex-col justify-between"><span className="flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-white/65"><Zap size={13} />{card.meta}</span><div><h3 className="text-2xl font-medium tracking-[-.04em] text-white md:text-3xl">{card.name}</h3><p className="mt-2 max-w-xs text-sm text-white/65">{card.desc}</p></div></div></button>)}</div></section>
    <section className="desire-section mx-auto grid max-w-[1500px] gap-16 px-5 py-32 md:grid-cols-[.7fr_1.3fr] md:px-10 md:py-48"><div className="pinned-copy self-start md:pt-16"><p className="mb-5 text-sm text-[#c9f05b]">让每次执行留下可核对的记录</p><h2 className="max-w-md text-4xl font-medium leading-[.98] tracking-[-.05em] text-[#f4f4ef] md:text-6xl">输入清楚，结果可查。</h2></div><div className="scroll-gallery space-y-5"><div className="rounded-[1.75rem] border border-white/10 bg-[#181c17] p-8 md:p-12"><div className="mb-16 flex items-center justify-between text-xs text-white/45"><span className="flex items-center gap-2"><CircleCheck size={15} className="text-[#c9f05b]" /> REQUEST TRACE</span><span>RESULT / BILL / POINTS</span></div><p className="word-reveal-wrap max-w-2xl text-3xl leading-[1.15] tracking-[-.04em] text-white md:text-5xl">{['选择能力，', '校验参数，', '执行请求。', '再用', '同一个', 'requestId', '核对结果、', '账单与积分。'].map((word) => <span key={word} className="word-reveal mr-[.22em] inline-block">{word}</span>)}</p></div><div className="rounded-[1.75rem] bg-[#c9f05b] p-8 text-[#11130f] md:p-12"><Sparkles size={24} /><p className="mt-20 max-w-lg text-3xl font-medium leading-tight tracking-[-.04em] md:text-5xl">“按能力执行，让参数、费用与调用结果可追踪。”</p><p className="mt-8 text-sm font-semibold uppercase tracking-[.2em] text-[#11130f]/55">AICapabilityHub Pro / Capability-driven execution</p></div></div></section>
    <footer className="border-t border-white/10"><div className="mx-auto flex max-w-[1500px] flex-col gap-10 px-5 py-16 md:flex-row md:items-end md:justify-between md:px-10 md:py-24"><div><p className="mb-5 text-4xl font-medium tracking-[-.06em] text-white md:text-6xl">选择能力，<br /><span className="text-[#c9f05b]">开始一次可核验的调用。</span></p><button onClick={() => navigate('/chat')} className="mt-4 flex items-center gap-3 rounded-full bg-white px-6 py-3 text-sm font-semibold text-[#11130f] transition hover:bg-[#c9f05b]">进入在线调试 <ArrowUpRight size={16} /></button></div><p className="max-w-xs text-sm leading-6 text-white/40">AICapabilityHub Pro<br />Capability-driven AI execution, billing, and tracing.</p></div></footer>
  </div>
}
