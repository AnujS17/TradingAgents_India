// Ported from web/design/landing-fintech/index.html lines 1254-1292 (the
// footer). Static — no data, no client state, so this stays a server
// component, matching SiteNav.
//
// The disclaimer paragraph below is carried over verbatim, TODO(legal)
// comment included: this is a Global Constraint from the design plan, not
// ordinary visual content, so it is not rewritten, trimmed, or "resolved"
// here.
//
// The source's bottom-right line ("Alternate design direction, compare with
// web/design/landing/index.html") is design-review scaffolding comparing two
// competing static mockups — it has no meaning once assembled into the real
// app, so it is dropped rather than ported; the copyright line is kept.
export function SiteFooter() {
  return (
    <footer className="border-t border-[#EBEBEB]">
      <div className="max-w-screen-xl mx-auto px-6 lg:px-8 py-14">
        <div className="grid md:grid-cols-4 gap-10">
          <div className="md:col-span-2">
            <a href="#" className="flex items-center gap-2.5 font-tight font-extrabold text-lg text-[#010101]">
              <span className="w-8 h-8 rounded-lg grad-navy flex items-center justify-center text-white text-sm font-black">
                B
              </span>
              Bench
            </a>
            <p className="text-sm text-[#757575] mt-4 max-w-sm leading-relaxed">
              Bench is a research tool for Indian-listed equities. Nothing on this page is
              investment advice or a recommendation to buy or sell any security.
              {/* TODO(legal): have this reviewed. Add entity name, SEBI status and full disclosures before launch. */}
            </p>
          </div>
          <div>
            <p className="text-xs font-black uppercase tracking-[0.09em] mb-4">Product</p>
            <ul className="space-y-2.5 text-sm text-[#757575]">
              <li>
                <a href="#how" className="transition hover:opacity-75">
                  How it works
                </a>
              </li>
              <li>
                <a href="#use-cases" className="transition hover:opacity-75">
                  Use cases
                </a>
              </li>
              <li>
                <a href="#deck" className="transition hover:opacity-75">
                  What you get
                </a>
              </li>
              <li>
                <a href="#live" className="transition hover:opacity-75">
                  Watch it run
                </a>
              </li>
            </ul>
          </div>
          <div>
            <p className="text-xs font-black uppercase tracking-[0.09em] mb-4">Company</p>
            <ul className="space-y-2.5 text-sm text-[#757575]">
              <li>
                <a href="#faq" className="transition hover:opacity-75">
                  FAQ
                </a>
              </li>
              <li>
                <a href="#" className="transition hover:opacity-75">
                  Privacy policy
                </a>
              </li>
              <li>
                <a href="#" className="transition hover:opacity-75">
                  Terms
                </a>
              </li>
            </ul>
          </div>
        </div>
        <div className="border-t border-[#EBEBEB] mt-10 pt-6 flex flex-col sm:flex-row justify-between items-center gap-3">
          <p className="text-xs text-[#757575]">© 2026 Bench. Research tool, not investment advice.</p>
        </div>
      </div>
    </footer>
  );
}
