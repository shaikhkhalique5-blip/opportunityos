'use client';
import { FormEvent, useEffect, useMemo, useState } from 'react';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
const split = (v: FormDataEntryValue | null) => String(v || '').split(',').map(x=>x.trim()).filter(Boolean);

type Tab = 'analyze'|'product'|'history';

export default function Home(){
  const [tab,setTab]=useState<Tab>('analyze');
  const [products,setProducts]=useState<any[]>([]);
  const [runs,setRuns]=useState<any[]>([]);
  const [result,setResult]=useState<any>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');

  async function load(){
    try{
      const [p,r]=await Promise.all([fetch(`${API}/products`),fetch(`${API}/opportunities/runs`)]);
      if(p.ok) setProducts(await p.json());
      if(r.ok) setRuns(await r.json());
    }catch{}
  }
  useEffect(()=>{load()},[]);

  async function analyze(e:FormEvent<HTMLFormElement>){
    e.preventDefault(); setLoading(true); setError(''); setResult(null);
    const f=new FormData(e.currentTarget);
    const productId=Number(f.get('product_brain_id')||0)||null;
    const body:any={
      company_url:f.get('company_url'), product_brain_id:productId,
      seller_product:productId?null:f.get('seller_product'),
      icp:{geographies:split(f.get('geographies')),industries:split(f.get('industries')),buyers:split(f.get('buyers')),company_size:f.get('company_size')||null}
    };
    try{
      const r=await fetch(`${API}/opportunities/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const json=await r.json(); if(!r.ok) throw new Error(json.detail||'Analysis failed');
      setResult(json); await load();
    }catch(err:any){setError(err.message||'Analysis failed')} finally{setLoading(false)}
  }

  async function saveProduct(e:FormEvent<HTMLFormElement>){
    e.preventDefault(); setError('');
    const f=new FormData(e.currentTarget);
    const body={name:f.get('name'),product_description:f.get('product_description'),markets:split(f.get('markets')),problems_solved:split(f.get('problems_solved')),target_buyers:split(f.get('target_buyers')),differentiators:split(f.get('differentiators')),proof_points:split(f.get('proof_points'))};
    try{
      const r=await fetch(`${API}/products`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const j=await r.json(); if(!r.ok) throw new Error(j.detail||'Could not save Product Brain');
      (e.currentTarget as HTMLFormElement).reset(); await load(); setTab('analyze');
    }catch(err:any){setError(err.message)}
  }

  async function feedback(runId:number, value:string){
    await fetch(`${API}/opportunities/runs/${runId}/feedback`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({feedback:value})});
    await load();
  }

  const stats=useMemo(()=>({
    analyzed:runs.length,
    hot:runs.filter(x=>Number(x.score)>=80).length,
    accepted:runs.filter(x=>x.feedback==='accepted'||x.feedback==='meeting'||x.feedback==='sql'||x.feedback==='won').length,
    avg:runs.length?Math.round(runs.reduce((a,x)=>a+Number(x.score||0),0)/runs.length):0
  }),[runs]);

  return <div className="shell">
    <aside className="sidebar"><div className="brand">Scalee <span>OpportunityOS</span></div><div className="tag">AI Opportunity Intelligence</div><div className="nav">
      <button className={tab==='analyze'?'active':''} onClick={()=>setTab('analyze')}>◎ Opportunity Analyst</button>
      <button className={tab==='product'?'active':''} onClick={()=>setTab('product')}>◈ Product Brain</button>
      <button className={tab==='history'?'active':''} onClick={()=>setTab('history')}>≡ Analysis History</button>
    </div></aside>
    <main className="main">
      <div className="topbar"><div><div className="eyebrow">Level 3 Opportunity Analyst</div><h1 className="title">Know who to talk to — and why now.</h1><div className="muted">Evidence-backed intelligence before outbound begins.</div></div><span className="pill">V1 · Human-controlled outreach</span></div>
      {error&&<div className="error">{error}</div>}
      <div className="kpis"><div className="kpi"><span className="small">Analyzed</span><b>{stats.analyzed}</b></div><div className="kpi"><span className="small">Hot opportunities</span><b>{stats.hot}</b></div><div className="kpi"><span className="small">Accepted</span><b>{stats.accepted}</b></div><div className="kpi"><span className="small">Average score</span><b>{stats.avg}</b></div></div>

      {tab==='analyze'&&<div className="grid">
        <section className="card"><h2>Analyze a company</h2><p className="muted">The Research Engine checks the company site, relevant internal pages, recent news, and optional broader web search.</p>
          <form onSubmit={analyze}>
            <div className="field"><label>Company URL</label><input name="company_url" placeholder="https://company.com" required/></div>
            <div className="field"><label>Product Brain</label><select name="product_brain_id"><option value="">Use one-off product description</option>{products.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
            <div className="field"><label>One-off seller product (used if no Product Brain selected)</label><textarea name="seller_product" defaultValue="Qualified B2B meetings and pipeline generation for companies selling AI."/></div>
            <div className="row"><div className="field"><label>Geographies</label><input name="geographies" placeholder="India, GCC, UK, US"/></div><div className="field"><label>Company size</label><input name="company_size" placeholder="50-2000 employees"/></div></div>
            <div className="row"><div className="field"><label>Industries</label><input name="industries" placeholder="AI, SaaS, Fintech"/></div><div className="field"><label>Likely buyers</label><input name="buyers" placeholder="CRO, VP Sales, CEO"/></div></div>
            <button className="btn" disabled={loading}>{loading?'Researching + reasoning…':'Run Opportunity Analyst'}</button>
          </form>
        </section>
        <section className="stack">{result?<ResultCard result={result}/>:<div className="card empty"><h3>No analysis yet</h3><p>Run a company to see buying signals, evidence, score, buyer map, sales hook, and recommended action.</p></div>}</section>
      </div>}

      {tab==='product'&&<div className="grid"><section className="card"><h2>Create Product Brain</h2><p className="muted">Teach OpportunityOS what you sell, who buys it, and what real problems it solves.</p><form onSubmit={saveProduct}>
        <div className="field"><label>Name</label><input name="name" placeholder="Scalee Pipeline Generation" required/></div>
        <div className="field"><label>Product / offer</label><textarea name="product_description" placeholder="What exactly do you sell?" required/></div>
        <div className="field"><label>Markets</label><input name="markets" placeholder="India, GCC, UK, US"/></div>
        <div className="field"><label>Problems solved</label><textarea name="problems_solved" placeholder="Poor outbound pipeline, founder-led sales bottleneck, weak response rates"/></div>
        <div className="field"><label>Target buyers</label><input name="target_buyers" placeholder="Founder, CRO, VP Sales"/></div>
        <div className="field"><label>Differentiators</label><textarea name="differentiators" placeholder="What makes this offer credibly different?"/></div>
        <div className="field"><label>Proof points</label><textarea name="proof_points" placeholder="Case studies, results, customer proof"/></div>
        <button className="btn">Save Product Brain</button>
      </form></section><section className="card"><h2>Saved brains</h2>{products.length?<div className="productList">{products.map(p=><div className="productItem" key={p.id}><div><strong>{p.name}</strong><div className="small">{p.target_buyers?.join(', ')||'No buyers saved'}</div></div><span className="pill">#{p.id}</span></div>)}</div>:<div className="empty">No Product Brains yet.</div>}</section></div>}

      {tab==='history'&&<section className="card"><h2>Opportunity history</h2><p className="muted">Human feedback becomes the first layer of your future learning loop.</p>{runs.length?<div className="history">{runs.map(run=><div className="historyItem" key={run.id} onClick={()=>{setResult(run.response);setTab('analyze')}}><div className="historyTop"><div><strong>{run.company}</strong><div className="small">{new Date(run.created_at).toLocaleString()} · {run.confidence} confidence</div></div><div className="historyScore">{run.score}/100</div></div><p>{run.why_now}</p><div className="feedback" onClick={e=>e.stopPropagation()}>{['accepted','rejected','contacted','meeting','sql','won','lost'].map(v=><button key={v} onClick={()=>feedback(run.id,v)}>{run.feedback===v?'✓ ':''}{v}</button>)}</div></div>)}</div>:<div className="empty">No saved analyses yet.</div>}</section>}
    </main>
  </div>
}

function ResultCard({result}:{result:any}){
  const parts=result.score_breakdown||{};
  return <><div className="card"><div className="sectionLabel">{result.company}</div><div style={{display:'flex',justifyContent:'space-between',alignItems:'end'}}><div><div className="score">{result.opportunity_score}</div><div className="small">Opportunity score / 100</div></div><span className="pill">{result.confidence} confidence</span></div></div>
    <div className="card"><div className="sectionLabel">Why now</div><p className="hook">{result.why_now}</p><div className="sectionLabel">Likely problem</div><p>{result.likely_business_problem}</p><div className="row"><div><div className="sectionLabel">Best buyer</div><strong>{result.best_buyer}</strong></div><div><div className="sectionLabel">Secondary</div><strong>{result.secondary_buyer||'—'}</strong></div></div></div>
    <div className="card"><h3>Recent signals</h3>{result.recent_signals?.length?result.recent_signals.map((s:any,i:number)=><div className="signal" key={i}><strong>{s.type} · {s.strength}/100</strong><span>{s.description}</span><div className="small">{s.recency_days==null?'Date uncertain':`${s.recency_days} days ago`}</div></div>):<div className="empty">No strong signals found.</div>}</div>
    <div className="card"><h3>Score breakdown</h3>{Object.entries(parts).map(([k,v]:any)=><div className="metric" key={k}><span>{k.replaceAll('_',' ')}</span><strong>{Math.round(Number(v))}</strong></div>)}</div>
    <div className="card"><div className="sectionLabel">Sales hook</div><p className="hook">{result.sales_hook}</p><div className="sectionLabel">Recommended next action</div><p>{result.recommended_next_action}</p>{result.rejection_reason&&<div className="error">Reject / nurture reason: {result.rejection_reason}</div>}</div>
    <div className="card"><h3>Evidence</h3>{result.evidence?.map((e:any,i:number)=><div className="evidence" key={i}><strong>{e.claim}</strong><div className="small">{e.source_name} · {e.published_date||'date unknown'} · {e.confidence}% confidence</div><a href={e.source_url} target="_blank" rel="noreferrer">Open source ↗</a></div>)}</div></>
}
