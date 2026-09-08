#!/usr/bin/env python3
"""Deterministic increasing-whole-life analyzer (Python 3.9+, stdlib only)."""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path

V="1.0"; PT="increasing_whole_life"
CMP=("currency","entry_age","gender","underwriting_class","payment_period_years","premium_frequency","benefit_option")
DEF={"irr_stability_bps":10.0,"irr_stability_consecutive_years":5,"key_years":[5,10,20,30],"ranking_tolerance":1e-10,
     "pareto_metrics":{"liquidity.break_even_year":"min","liquidity.surrender_gap_ratio_y5":"min",
     "growth.guaranteed_cv_irr_y20":"max","growth.guaranteed_cv_irr_y30":"max","protection.death_cv_ratio_y20":"max"}}

class E(Exception): pass

def num(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(float(x))
def load(p):
    try: x=json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception as e: raise E(f"cannot read JSON {p}: {e}")
    if not isinstance(x,dict): raise E("top-level JSON must be an object")
    return x

def rules(root):
    p=root/"config"/"rules.json"; r=dict(DEF)
    if p.exists(): r.update(load(p))
    return r

def premiums(d):
    a,b=d.get("premium_schedule"),d.get("premium_cashflows")
    if a is not None and b is not None: raise E("use premium_schedule or premium_cashflows, not both")
    out=[]
    if a is not None:
        if not isinstance(a,dict) or not num(a.get("annual_amount")) or float(a["annual_amount"])<=0: raise E("invalid premium_schedule.annual_amount")
        n=a.get("years"); first=a.get("first_time_years",0); step=a.get("interval_years",1)
        if not isinstance(n,int) or isinstance(n,bool) or n<=0 or not num(first) or not num(step) or float(step)<=0: raise E("invalid premium_schedule timing")
        out=[{"time_years":float(first)+i*float(step),"amount":float(a["annual_amount"])} for i in range(n)]
    elif b is not None:
        if not isinstance(b,list) or not b: raise E("premium_cashflows must be non-empty")
        for i,r in enumerate(b):
            if not isinstance(r,dict) or not num(r.get("time_years")) or not num(r.get("amount")) or float(r["time_years"])<0 or float(r["amount"])<=0: raise E(f"invalid premium_cashflows[{i}]")
            out.append({"time_years":float(r["time_years"]),"amount":float(r["amount"])})
    else: raise E("premium_schedule or premium_cashflows is required")
    return sorted(out,key=lambda x:x["time_years"])

def validate(d, compare=False):
    err=[]; warn=[]; m=d.get("product")
    if d.get("schema_version") not in (None,V): err.append("unsupported schema_version")
    if not isinstance(m,dict): err.append("product must be object"); m={}
    if m.get("product_type")!=PT: err.append(f"product_type must be {PT}")
    if not m.get("name"): err.append("product.name required")
    for f in ("currency","entry_age","gender","payment_period_years"):
        if m.get(f) in (None,""): warn.append(f"product.{f} missing; comparison blocked")
    for f in ("entry_age","payment_period_years"):
        if m.get(f) is not None and (not isinstance(m[f],int) or isinstance(m[f],bool) or m[f]<0): err.append(f"product.{f} invalid")
    try: ps=premiums(d)
    except E as e: err.append(str(e)); ps=[]
    rows=d.get("policy_values")
    if not isinstance(rows,list) or not rows: err.append("policy_values must be non-empty"); rows=[]
    seen=set(); sources=d.get("sources",{})
    if not isinstance(sources,dict): err.append("sources must be object"); sources={}
    for i,r in enumerate(rows):
        if not isinstance(r,dict): err.append(f"policy_values[{i}] invalid"); continue
        y=r.get("year")
        if not isinstance(y,int) or isinstance(y,bool) or y<=0: err.append(f"policy_values[{i}].year invalid"); continue
        if y in seen: err.append(f"duplicate policy year {y}")
        seen.add(y)
        for f in ("guaranteed_cash_value","guaranteed_death_benefit"):
            if not num(r.get(f)) or float(r[f])<0: err.append(f"policy_values[{i}].{f} invalid")
        for f in ("illustrated_cash_value","illustrated_death_benefit"):
            if r.get(f) is not None and (not num(r[f]) or float(r[f])<0): err.append(f"policy_values[{i}].{f} invalid")
        ref=r.get("source_ref")
        if not ref: warn.append(f"policy_values[{i}] has no source_ref")
        elif ref not in sources: err.append(f"unknown source_ref {ref}")
    for k in ("partial_surrender_rule","policy_loan_rule"):
        r=d.get(k)
        if isinstance(r,dict) and r.get("source_ref") and r["source_ref"] not in sources: err.append(f"unknown {k}.source_ref")
    if compare:
        for f in CMP:
            if m.get(f) in (None,""): err.append(f"product.{f} required for comparison")
    if err: raise E("; ".join(err))
    return {"valid":True,"warnings":warn,"premium_cashflows":ps}

def cum(ps,t): return sum(x["amount"] for x in ps if x["time_years"]<t-1e-12)
def npv(r,fs): return sum(a/((1+r)**t) for t,a in fs)
def irr(fs):
    if not any(a<0 for _,a in fs) or not any(a>0 for _,a in fs): return None
    lo,hi=-.9,1.; flo,fhi=npv(lo,fs),npv(hi,fs)
    for _ in range(80):
        if math.isfinite(flo) and math.isfinite(fhi) and flo*fhi<=0: break
        hi*=2; fhi=npv(hi,fs)
    else: return None
    for _ in range(200):
        mid=(lo+hi)/2; fm=npv(mid,fs)
        if abs(fm)<1e-11 or hi-lo<1e-12: return mid
        if flo*fm<=0: hi,fhi=mid,fm
        else: lo,flo=mid,fm
    return (lo+hi)/2

def tirr(ps,y,v): return irr([(x["time_years"],-x["amount"]) for x in ps if x["time_years"]<y-1e-12]+[(float(y),float(v))])
def get(o,path):
    for p in path.split("."):
        if not isinstance(o,dict) or p not in o: return None
        o=o[p]
    return o

def analyze(d,r):
    ck=validate(d); ps=ck["premium_cashflows"]; w=list(ck["warnings"]); rows=sorted(d["policy_values"],key=lambda x:x["year"]); s=[]
    for x in rows:
        y=x["year"]; cp=cum(ps,y); cv=float(x["guaranteed_cash_value"]); db=float(x["guaranteed_death_benefit"])
        z={"year":y,"cumulative_premium":cp,"guaranteed_cash_value":cv,"guaranteed_death_benefit":db,
           "cash_value_ratio":cv/cp if cp else None,"surrender_gap_ratio":(cp-cv)/cp if cp else None,
           "guaranteed_cv_irr":tirr(ps,y,cv),"death_benefit_irr":tirr(ps,y,db),"death_cv_ratio":db/cv if cv else None,"source_ref":x.get("source_ref")}
        if x.get("illustrated_cash_value") is not None: z["illustrated_cash_value"]=float(x["illustrated_cash_value"]); z["illustrated_cv_irr"]=tirr(ps,y,z["illustrated_cash_value"])
        if x.get("illustrated_death_benefit") is not None: z["illustrated_death_benefit"]=float(x["illustrated_death_benefit"])
        s.append(z)
    by={x["year"]:x for x in s}; cand=next((x["year"] for x in s if x["cumulative_premium"] and x["guaranteed_cash_value"]>=x["cumulative_premium"]),None); be=bi=None
    if cand is not None:
        av=set(by)
        if all(y in av for y in range(1,cand+1)): be=cand
        else:
            p=[x["year"] for x in s if x["year"]<cand and x["guaranteed_cash_value"]<x["cumulative_premium"]]; bi=[(max(p)+1 if p else 1),cand]; w.append(f"Exact break-even not provable; interval={bi}")
    yv=lambda y,k: by.get(y,{}).get(k); g={}; p={}
    for y in map(int,r.get("key_years",DEF["key_years"])):
        g[f"guaranteed_cv_irr_y{y}"]=yv(y,"guaranteed_cv_irr"); p[f"death_benefit_irr_y{y}"]=yv(y,"death_benefit_irr"); p[f"death_cv_ratio_y{y}"]=yv(y,"death_cv_ratio")
        if yv(y,"illustrated_cv_irr") is not None: g[f"illustrated_cv_irr_y{y}"]=yv(y,"illustrated_cv_irr")
    vis=[(x["year"],x["guaranteed_cv_irr"]) for x in s if x["guaranteed_cv_irr"] is not None]; terminal=vis[-1][1] if vis else None; stable=None
    if terminal is not None:
        im=dict(vis); n=int(r.get("irr_stability_consecutive_years",5)); tol=float(r.get("irr_stability_bps",10))/10000
        for y,_ in vis:
            q=[im.get(y+i) for i in range(n)]
            if all(v is not None and abs(v-terminal)<=tol for v in q): stable=y; break
        if stable is None and d.get("analysis_mode","core")=="core": w.append("IRR stable year requires full consecutive annual rows")
    g.update({"terminal_guaranteed_cv_irr":terminal,"irr_stable_year":stable})
    if d.get("partial_surrender_rule") is None: w.append("partial_surrender_rule missing")
    if d.get("policy_loan_rule") is None: w.append("policy_loan_rule missing")
    return {"schema_version":V,"product":d["product"],"analysis_mode":d.get("analysis_mode","core"),"metrics":{
      "liquidity":{"break_even_year":be,"break_even_interval":bi,"surrender_gap_ratio_y5":yv(5,"surrender_gap_ratio"),"cash_value_ratio_y10":yv(10,"cash_value_ratio")},
      "growth":g,"protection":p,"flexibility":{"partial_surrender_rule":d.get("partial_surrender_rule"),"policy_loan_rule":d.get("policy_loan_rule")},
      "certainty":{"guaranteed_values_present":True,"illustrated_values_present":any(x.get("illustrated_cash_value") is not None or x.get("illustrated_death_benefit") is not None for x in rows),"guaranteed_and_illustrated_kept_separate":True}},
      "series":s,"sources":d.get("sources",{}),"warnings":w,"method_notes":["Policy-year value is terminal at t=year; renewal premium at t=year belongs to the next policy year.","death_benefit_irr is a death-scenario cashflow IRR, not an investment return.","Guaranteed and illustrated values are never mixed."]}

def signature(d): return [(round(x["time_years"],10),round(x["amount"],8)) for x in premiums(d)]
def gate(ds):
    if len(ds)<2: return {"comparable":False,"reasons":["at least two products required"]}
    for d in ds: validate(d,True)
    rs=[]
    for f in CMP:
        v=[d["product"].get(f) for d in ds]
        if any(x!=v[0] for x in v[1:]): rs.append(f"scenario mismatch: {f}={v!r}")
    ss=[signature(d) for d in ds]
    if any(x!=ss[0] for x in ss[1:]): rs.append("scenario mismatch: premium cashflow schedule")
    return {"comparable":not rs,"reasons":rs}

def specs(): return {"liquidity.break_even_year":"min","liquidity.surrender_gap_ratio_y5":"min","liquidity.cash_value_ratio_y10":"max","growth.guaranteed_cv_irr_y10":"max","growth.guaranteed_cv_irr_y20":"max","growth.guaranteed_cv_irr_y30":"max","protection.death_benefit_irr_y10":"max","protection.death_benefit_irr_y20":"max","protection.death_cv_ratio_y10":"max","protection.death_cv_ratio_y20":"max"}
def val(a,m): return get(a["metrics"],m)
def dominates(a,b,sp,t):
    strict=False
    for m,d in sp.items():
        av,bv=val(a,m),val(b,m)
        if av is None or bv is None: return False
        if d=="max":
            if av<bv-t:return False
            strict|=av>bv+t
        else:
            if av>bv+t:return False
            strict|=av<bv-t
    return strict

def compare(ds,r):
    g=gate(ds); aa=[analyze(d,r) for d in ds]; names=[a["product"]["name"] for a in aa]; out={"schema_version":V,"comparability":g,"products":aa,"rankings":{},"pareto_frontier":[],"dominated_by":{},"warnings":[]}
    if not g["comparable"]: out["warnings"].append("No cross-product ranking produced."); return out
    t=float(r.get("ranking_tolerance",1e-10))
    for m,d in specs().items():
        v=[(names[i],val(aa[i],m)) for i in range(len(aa)) if val(aa[i],m) is not None]
        if not v: continue
        v.sort(key=lambda x:x[1],reverse=d=="max"); best=v[0][1]; out["rankings"][m]={"direction":d,"ordered":v,"leaders":[n for n,x in v if abs(x-best)<=t]}
    sp=dict(r.get("pareto_metrics",DEF["pareto_metrics"])); out["pareto_metrics_used"]=list(sp); missing={names[i]:[m for m in sp if val(aa[i],m) is None] for i in range(len(aa))}; missing={k:v for k,v in missing.items() if v}
    if missing: out["warnings"].append(f"Pareto not produced; incomplete metrics: {missing}"); out["dominated_by"]={n:[] for n in names}; return out
    dom={n:[] for n in names}
    for i,a in enumerate(aa):
        for j,b in enumerate(aa):
            if i!=j and dominates(b,a,sp,t): dom[names[i]].append(names[j])
    out["dominated_by"]=dom; out["pareto_frontier"]=[n for n in names if not dom[n]]; return out

def dump(x,p=None):
    s=json.dumps(x,ensure_ascii=False,indent=2)
    if p: Path(p).write_text(s+"\n",encoding="utf-8")
    else: print(s)
def selftest(root):
    d=load(root/"tests/fixtures/example_product.json"); e=load(root/"tests/golden/example_expected.json"); r=rules(root); a=analyze(d,r)
    c={"break_even_year":a["metrics"]["liquidity"]["break_even_year"]==e["break_even_year"],"y20_cv_irr":abs(a["metrics"]["growth"]["guaranteed_cv_irr_y20"]-e["guaranteed_cv_irr_y20"])<1e-10,"y20_death_irr":abs(a["metrics"]["protection"]["death_benefit_irr_y20"]-e["death_benefit_irr_y20"])<1e-10}
    b=json.loads(json.dumps(d)); b["product"]["name"]="Golden Better"; [x.__setitem__("guaranteed_cash_value",x["guaranteed_cash_value"]*1.05) for x in b["policy_values"] if x["year"]>=20]; q=compare([d,b],r); c["comparison_gate"]=q["comparability"]["comparable"] and bool(q["pareto_frontier"])
    z=json.loads(json.dumps(b)); z["product"]["entry_age"]=41; q=compare([d,z],r); c["mismatch_blocks_ranking"]=not q["comparability"]["comparable"] and not q["rankings"]
    return {"ok":all(c.values()),"checks":c}

def main():
    ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest="cmd",required=True)
    x=sp.add_parser("validate"); x.add_argument("--input",required=True)
    x=sp.add_parser("analyze"); x.add_argument("--input",required=True); x.add_argument("--output")
    x=sp.add_parser("compare"); x.add_argument("--inputs",nargs="+",required=True); x.add_argument("--output")
    sp.add_parser("self-test"); a=ap.parse_args(); root=Path(__file__).resolve().parents[1]
    try:
        r=rules(root)
        if a.cmd=="validate": dump(validate(load(a.input)))
        elif a.cmd=="analyze": dump(analyze(load(a.input),r),a.output)
        elif a.cmd=="compare": dump(compare([load(x) for x in a.inputs],r),a.output)
        else:
            q=selftest(root); dump(q); return 0 if q["ok"] else 2
    except E as e: print(json.dumps({"ok":False,"error":str(e)},ensure_ascii=False),file=sys.stderr); return 2
    return 0
if __name__=="__main__": raise SystemExit(main())
