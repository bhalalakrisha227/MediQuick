import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { isStaff, workspaceLinks } from "../utils/roles";
import Icon from "../components/ui/Icon";

// What each feature card promises is limited to what the system really does.
const FEATURES = [
  { icon: "bag", title: "Online Medicine Shopping",
    text: "Search the catalogue by name, category or price and see stock before you order." },
  { icon: "shield", title: "Prescription Verification",
    text: "A pharmacist reviews every prescription. Prescription medicines can be ordered only after approval, and only up to the approved quantities." },
  { icon: "lock", title: "Secure Orders",
    text: "Your orders and prescription files are private to you and the staff who need them to serve you." },
  { icon: "truck", title: "Fast Delivery",
    text: "Orders are delivered by our own delivery partners, and you confirm receipt with a one-time handover code." },
];

function HeroArt() {
  return (
    <svg viewBox="0 0 460 420" className="mq-hero__art mq-float" role="img" aria-label="Medicine capsule, prescription and shield illustration">
      <defs>
        <linearGradient id="gCard" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#ffffff" /><stop offset="1" stopColor="#e9f7f2" /></linearGradient>
        <linearGradient id="gTeal" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#14b8a6" /><stop offset="1" stopColor="#0f766e" /></linearGradient>
      </defs>
      <circle cx="230" cy="210" r="170" fill="#ffffff" opacity="0.06" />
      <circle cx="230" cy="210" r="120" fill="#ffffff" opacity="0.06" />
      {/* prescription card */}
      <g transform="rotate(-6 200 220)">
        <rect x="95" y="90" width="230" height="270" rx="22" fill="url(#gCard)" />
        <rect x="120" y="118" width="60" height="14" rx="7" fill="#0f766e" />
        <rect x="120" y="146" width="140" height="8" rx="4" fill="#cbd5e1" />
        <rect x="120" y="164" width="110" height="8" rx="4" fill="#cbd5e1" />
        <text x="120" y="226" fontFamily="Inter, Arial, sans-serif" fontSize="46" fontWeight="800" fill="#101b35">Rx</text>
        <rect x="120" y="250" width="160" height="8" rx="4" fill="#e2e8f0" />
        <rect x="120" y="268" width="130" height="8" rx="4" fill="#e2e8f0" />
        <rect x="120" y="300" width="84" height="30" rx="15" fill="#d9f5ec" />
        <path d="M137 315l7 7 14-14" fill="none" stroke="#0f766e" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        <text x="164" y="320" fontFamily="Inter, Arial, sans-serif" fontSize="13" fontWeight="700" fill="#0b5d57">Reviewed</text>
      </g>
      {/* capsule */}
      <g transform="rotate(35 340 140)">
        <rect x="280" y="108" width="130" height="58" rx="29" fill="#d9f5ec" />
        <path d="M345 108h6a29 29 0 010 58h-6z" fill="url(#gTeal)" />
        <path d="M345 108h-35a29 29 0 000 58h35z" fill="#ffffff" />
      </g>
      {/* shield */}
      <g transform="translate(300 250)">
        <path d="M60 0l60 22v50c0 40-26 66-60 78C26 138 0 112 0 72V22z" fill="url(#gTeal)" />
        <path d="M32 74l20 20 38-40" fill="none" stroke="#fff" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
      </g>
      {/* cross */}
      <g transform="translate(60 60)"><rect x="0" y="14" width="44" height="16" rx="8" fill="#7fe3cc" /><rect x="14" y="0" width="16" height="44" rx="8" fill="#7fe3cc" /></g>
      <circle cx="400" cy="330" r="9" fill="#7fe3cc" opacity="0.7" />
      <circle cx="70" cy="340" r="6" fill="#ffffff" opacity="0.5" />
    </svg>
  );
}

export default function HomePage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const staff = isStaff(user);
  const work = staff ? workspaceLinks(user.role) : [];
  const [q, setQ] = useState("");
  const [categories, setCategories] = useState([]);

  useEffect(() => {
    if (staff) return;
    api.get("/categories/").then((res) => setCategories(res.data.results)).catch(() => {});
  }, [staff]);

  function search(e) {
    e.preventDefault();
    navigate(`/shop?${new URLSearchParams(q.trim() ? { q: q.trim() } : {})}`);
  }

  return (
    <>
      <section className="mq-hero">
        <div className="container py-5">
          <div className="row align-items-center g-5 py-lg-4">
            <div className="col-lg-6">
              <span className="mq-eyebrow mb-4"><Icon name="heart" size={15} />Online pharmacy for India</span>
              <h1 className="mb-3">Your Health, <span>Our Priority.</span></h1>
              <p className="mq-hero__lead mb-4">
                MediQuick lets you search medicines, upload a prescription for pharmacist review,
                place a secure order and have it delivered by our own delivery partners.
              </p>
              {staff ? (
                <div className="d-flex flex-wrap gap-3">
                  {work.map((w, i) => (
                    <Link key={w.to} to={w.to} className={`btn btn-lg ${i === 0 ? "btn-teal" : "btn-light-outline"}`}><Icon name={w.icon} size={18} />{w.label}</Link>
                  ))}
                </div>
              ) : (
                <>
                  <form onSubmit={search} className="mq-search mb-4">
                    <Icon name="search" size={20} />
                    <input placeholder="Search medicines, e.g. paracetamol" maxLength={60} value={q}
                      onChange={(e) => setQ(e.target.value)} aria-label="Search medicines" />
                    <button className="btn btn-teal">Search</button>
                  </form>
                  <div className="d-flex flex-wrap gap-3">
                    <Link to="/shop" className="btn btn-lg btn-teal">Explore Medicines<Icon name="arrow" size={18} /></Link>
                    <Link to="/prescriptions/new" className="btn btn-lg btn-light-outline"><Icon name="upload" size={18} />Upload Prescription</Link>
                  </div>
                </>
              )}
            </div>
            <div className="col-lg-6"><HeroArt /></div>
          </div>
        </div>
      </section>

      <section className="mq-section">
        <div className="container">
          <div className="text-center mb-5">
            <div className="mq-section__eyebrow mb-2">Why MediQuick</div>
            <h2 className="mq-section__title">Careful about medicines, simple for you</h2>
          </div>
          <div className="row g-4">
            {FEATURES.map((f) => (
              <div key={f.title} className="col-sm-6 col-lg-3">
                <div className="card mq-feature mq-card-hover">
                  <div className="mq-feature__icon"><Icon name={f.icon} size={26} /></div>
                  <h3 className="mb-2">{f.title}</h3>
                  <p>{f.text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {!staff && (
      <section className="pb-5">
        <div className="container">
          <div className="row g-4">
            <div className="col-md-6">
              <Link to="/shop?rx=otc" className="card mq-feature mq-card-hover text-decoration-none">
                <div className="mq-feature__icon"><Icon name="pill" size={26} /></div>
                <h3>Everyday health</h3>
                <p>Products that do not need a prescription.</p>
              </Link>
            </div>
            <div className="col-md-6">
              <Link to="/shop?rx=prescription" className="card mq-feature mq-card-hover text-decoration-none">
                <div className="mq-feature__icon"><Icon name="clipboard" size={26} /></div>
                <h3>Prescription medicines</h3>
                <p>Upload your prescription; once a pharmacist approves it you can order the approved quantities.</p>
              </Link>
            </div>
          </div>

          {categories.length > 0 && (
            <div className="mt-5">
              <h2 className="h5 mb-3">Shop by category</h2>
              <div className="d-flex flex-wrap gap-2">
                {categories.map((c) => <Link key={c.id} className="mq-chip" to={`/shop?category=${c.slug}`}>{c.name}</Link>)}
              </div>
            </div>
          )}

          <div className="mq-cta-band mt-5 d-flex flex-column flex-md-row align-items-md-center justify-content-between gap-3">
            <div>
              <h2 className="h4 mb-1">Have a prescription?</h2>
              <p className="mb-0">Upload a photo or PDF. A pharmacist reviews it; you can follow its status in your account.</p>
            </div>
            <Link to="/prescriptions/new" className="btn btn-lg btn-light"><Icon name="upload" size={18} />Upload Prescription</Link>
          </div>
        </div>
      </section>
      )}
    </>
  );
}
