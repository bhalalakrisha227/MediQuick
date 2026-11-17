import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { apiError } from "../api/client";
import ProductCard from "../components/ProductCard";
import Icon from "../components/ui/Icon";
import { EmptyState, ErrorState, SkeletonGrid } from "../components/ui/States";
import { rupeesToPaise } from "../utils/money";

const paiseToRupees = (v) => (v ? String(Number(v) / 100) : "");

export default function ShopPage() {
  const [params, setParams] = useSearchParams();
  const [categories, setCategories] = useState([]);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [q, setQ] = useState(params.get("q") || "");
  const [minRs, setMinRs] = useState(paiseToRupees(params.get("min_price")));
  const [maxRs, setMaxRs] = useState(paiseToRupees(params.get("max_price")));

  useEffect(() => {
    api.get("/categories/").then((res) => setCategories(res.data.results)).catch(() => {});
  }, []);

  // Keep the form boxes in step with the URL (back button, "Clear filters").
  useEffect(() => {
    setQ(params.get("q") || "");
    setMinRs(paiseToRupees(params.get("min_price")));
    setMaxRs(paiseToRupees(params.get("max_price")));
  }, [params]);

  const query = params.toString();
  useEffect(() => {
    let stale = false;
    setError("");
    setData(null);
    api.get(`/products/?${query}`)
      .then((res) => { if (!stale) setData(res.data); })
      .catch((err) => { if (!stale) setError(apiError(err).message); });
    return () => { stale = true; };
  }, [query, reload]);

  // Changing any filter returns to page 1.
  function setParam(key, value) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  }
  function submitSearch(e) {
    e.preventDefault();
    setParam("q", q.trim());
  }
  function applyPrice(e) {
    e.preventDefault();
    const next = new URLSearchParams(params);
    for (const [key, rupees] of [["min_price", minRs], ["max_price", maxRs]]) {
      const paise = rupeesToPaise(rupees);
      if (paise === null) next.delete(key); else next.set(key, String(paise));
    }
    next.delete("page");
    setParams(next);
  }

  const category = params.get("category") || "";
  const rx = params.get("rx") || "";
  const hasFilters = ["q", "category", "rx", "min_price", "max_price", "sort"].some((k) => params.get(k));
  const page = data?.page || 1;

  const filterBar = (
    <div className="card mq-filterbar mb-4">
      <div className="row g-3 align-items-end">
        <div className="col-12 col-sm-6 col-lg-3">
          <label htmlFor="f-category">Category</label>
          <select id="f-category" className="form-select" value={category} onChange={(e) => setParam("category", e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => <option key={c.id} value={c.slug}>{c.name}</option>)}
          </select>
        </div>
        <div className="col-12 col-sm-6 col-lg-2">
          <label htmlFor="f-rx">Prescription</label>
          <select id="f-rx" className="form-select" value={rx} onChange={(e) => setParam("rx", e.target.value)}>
            <option value="">All medicines</option>
            <option value="otc">No prescription</option>
            <option value="prescription">Prescription needed</option>
          </select>
        </div>
        <form className="col-12 col-lg-4" onSubmit={applyPrice}>
          <label htmlFor="f-min">Price (Rs)</label>
          <div className="mq-filterbar__price">
            <input id="f-min" className="form-control" placeholder="Min" inputMode="decimal" value={minRs}
              onChange={(e) => setMinRs(e.target.value)} aria-label="Minimum price in rupees" />
            <span className="text-muted">to</span>
            <input className="form-control" placeholder="Max" inputMode="decimal" value={maxRs}
              onChange={(e) => setMaxRs(e.target.value)} aria-label="Maximum price in rupees" />
            <button className="btn btn-outline-primary">Apply</button>
          </div>
        </form>
        <div className="col-12 col-sm-6 col-lg-3">
          <label htmlFor="f-sort">Sort by</label>
          <select id="f-sort" className="form-select" value={params.get("sort") || "name"}
            onChange={(e) => setParam("sort", e.target.value === "name" ? "" : e.target.value)}>
            <option value="name">Name (A-Z)</option>
            <option value="price_asc">Price: low to high</option>
            <option value="price_desc">Price: high to low</option>
            <option value="newest">Newest</option>
          </select>
        </div>
      </div>
      {hasFilters && (
        <div className="mt-3">
          <button className="btn btn-link btn-sm p-0" onClick={() => setParams(new URLSearchParams())}>Clear all filters</button>
        </div>
      )}
    </div>
  );

  return (
    <>
      <section className="mq-pagehead">
        <div className="container py-4">
          <div className="row align-items-center g-3">
            <div className="col-lg-5">
              <h1 className="h3 mb-1">Shop medicines</h1>
              <p className="text-muted mb-0">Prescription medicines need a pharmacist-approved prescription.</p>
            </div>
            <div className="col-lg-7">
              <form onSubmit={submitSearch} className="d-flex gap-2">
                <div className="position-relative flex-grow-1">
                  <span className="position-absolute top-50 translate-middle-y ms-3 text-muted"><Icon name="search" size={18} /></span>
                  <input className="form-control ps-5" placeholder="Search by name, generic name or brand" maxLength={60}
                    value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
                </div>
                <button className="btn btn-primary">Search</button>
              </form>
            </div>
          </div>
        </div>
      </section>

      <main className="container py-4">
        {filterBar}
        <div className="row g-4">
          <div className="col-12">
            {error && <ErrorState message={error} onRetry={() => setReload((n) => n + 1)} />}
            {!data && !error && <SkeletonGrid count={8} />}
            {data && data.results.length === 0 && (
              <EmptyState icon="search" title="No products match your filters"
                action={hasFilters && <button className="btn btn-primary" onClick={() => setParams(new URLSearchParams())}>Clear filters</button>}>
                Try a different search or remove some filters.
              </EmptyState>
            )}
            {data && data.results.length > 0 && (
              <>
                <p className="small text-muted mb-3">{data.total} product{data.total === 1 ? "" : "s"}</p>
                <div className="row g-3">
                  {data.results.map((p) => (
                    <div key={p.id} className="col-6 col-md-4 col-xl-3"><ProductCard product={p} /></div>
                  ))}
                </div>
                <div className="d-flex justify-content-between align-items-center mt-4">
                  <button className="btn btn-outline-secondary btn-sm" disabled={page <= 1}
                    onClick={() => setParam("page", String(page - 1))}>Previous</button>
                  <span className="small text-muted">Page {page} of {data.total_pages}</span>
                  <button className="btn btn-outline-secondary btn-sm" disabled={page >= data.total_pages}
                    onClick={() => setParam("page", String(page + 1))}>Next</button>
                </div>
              </>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
