"use client";
import { useState, useEffect } from "react";
import api from "@/lib/api";

interface Car {
  carId: string; brand: string; model: string; year: number;
  color?: string; vin?: string; purchasePrice?: number;
  sellingPrice?: number; images?: string[];
}

interface Props {
  car: Car;
  onClose: () => void;
  onSold: (txn: any) => void;
}

export default function MarkSoldModal({ car, onClose, onSold }: Props) {
  const [form, setForm] = useState({
    sellingPrice: car.sellingPrice?.toString() || "",
    purchasePrice: car.purchasePrice?.toString() || "",
    buyerName: "", buyerPhone: "", buyerEmail: "",
    paymentMethod: "cash", notes: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError(""); setLoading(true);
    try {
      const res = await api.post(`/api/v1/cars/${car.carId}/mark-sold`, {
        sellingPrice: parseFloat(form.sellingPrice),
        purchasePrice: form.purchasePrice ? parseFloat(form.purchasePrice) : undefined,
        buyerName: form.buyerName || undefined,
        buyerPhone: form.buyerPhone || undefined,
        buyerEmail: form.buyerEmail || undefined,
        paymentMethod: form.paymentMethod,
        notes: form.notes || undefined,
      });
      onSold(res.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to record sale. Please try again.");
    } finally { setLoading(false); }
  };

  const inp: React.CSSProperties = {background:"#F5F5F5",border:"1.5px solid #E5E5E5",borderRadius:"8px",padding:"0.75rem 1rem",color:"#1A1A1A",fontSize:"0.9rem",fontFamily:"var(--font-body)",outline:"none",width:"100%",boxSizing:"border-box" as const,transition:"border-color 0.2s"};
  const lbl: React.CSSProperties = {fontSize:"0.7rem",fontWeight:700,letterSpacing:"0.1em",textTransform:"uppercase" as const,color:"#525252"};

  return (
    <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.55)",display:"flex",alignItems:"center",justifyContent:"center",zIndex:1000,padding:"1rem"}}>
      <div style={{background:"#fff",borderRadius:"16px",width:"100%",maxWidth:"520px",maxHeight:"90vh",overflowY:"auto",boxShadow:"0 16px 48px rgba(0,0,0,0.2)"}}>
        {/* Header */}
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",padding:"1.25rem 1.5rem",background:"#1A1A1A",borderRadius:"16px 16px 0 0"}}>
          <div>
            <div style={{fontFamily:"var(--font-display)",fontSize:"1rem",letterSpacing:"0.1em",color:"#F47B20"}}>RECORD SALE</div>
            <div style={{fontSize:"0.8rem",color:"#A3A3A3",marginTop:"0.2rem"}}>{car.brand} {car.model} {car.year} · {car.carId}</div>
          </div>
          <button onClick={onClose} style={{background:"rgba(255,255,255,0.12)",border:"none",color:"#fff",width:"32px",height:"32px",borderRadius:"50%",cursor:"pointer",fontSize:"1rem"}}>✕</button>
        </div>

        {/* Car context */}
        <div style={{display:"flex",alignItems:"center",gap:"0.875rem",padding:"1rem 1.5rem",background:"#FFF7ED",borderBottom:"1px solid rgba(244,123,32,0.15)"}}>
          {car.images?.[0] && <img src={car.images[0]} alt="" style={{width:"60px",height:"46px",objectFit:"cover",borderRadius:"6px",flexShrink:0}}/>}
          <div>
            <div style={{fontWeight:700,fontSize:"0.95rem",color:"#1A1A1A"}}>{car.brand} {car.model} {car.year}</div>
            <div style={{fontSize:"0.8rem",color:"#737373"}}>{[car.color,car.vin&&`VIN: ${car.vin}`].filter(Boolean).join(" · ")}</div>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={submit} style={{padding:"1.5rem",display:"flex",flexDirection:"column",gap:"1rem"}}>
          {error && <div style={{background:"#FEF2F2",border:"1px solid #FCA5A5",color:"#DC2626",padding:"0.75rem",borderRadius:"8px",fontSize:"0.875rem"}}>{error}</div>}

          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"1rem"}}>
            <div style={{display:"flex",flexDirection:"column",gap:"0.4rem"}}>
              <label style={lbl}>Selling Price (₦) *</label>
              <input style={inp} type="number" min="0" placeholder="e.g. 5000000" value={form.sellingPrice} onChange={e=>setForm({...form,sellingPrice:e.target.value})} required onFocus={ev=>ev.target.style.borderColor="#F47B20"} onBlur={ev=>ev.target.style.borderColor="#E5E5E5"}/>
            </div>
            <div style={{display:"flex",flexDirection:"column",gap:"0.4rem"}}>
              <label style={lbl}>Purchase / Cost Price (₦)</label>
              <input style={inp} type="number" min="0" placeholder="Auto-filled if set" value={form.purchasePrice} onChange={e=>setForm({...form,purchasePrice:e.target.value})} onFocus={ev=>ev.target.style.borderColor="#F47B20"} onBlur={ev=>ev.target.style.borderColor="#E5E5E5"}/>
            </div>
          </div>

          <div style={{display:"flex",flexDirection:"column",gap:"0.4rem"}}>
            <label style={lbl}>Payment Method *</label>
            <select style={inp} value={form.paymentMethod} onChange={e=>setForm({...form,paymentMethod:e.target.value})}>
              {["cash","bank_transfer","card","installment","other"].map(m=><option key={m} value={m}>{m.replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase())}</option>)}
            </select>
          </div>

          <div style={{background:"#F5F5F5",borderRadius:"10px",padding:"1rem",display:"flex",flexDirection:"column",gap:"0.75rem"}}>
            <div style={{fontSize:"0.72rem",fontWeight:700,letterSpacing:"0.12em",color:"#A3A3A3",textTransform:"uppercase" as const}}>Buyer Details (Optional)</div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"0.75rem"}}>
              <div style={{display:"flex",flexDirection:"column",gap:"0.4rem"}}>
                <label style={lbl}>Buyer Name</label>
                <input style={{...inp,background:"#fff"}} placeholder="Full name" value={form.buyerName} onChange={e=>setForm({...form,buyerName:e.target.value})} onFocus={ev=>ev.target.style.borderColor="#F47B20"} onBlur={ev=>ev.target.style.borderColor="#E5E5E5"}/>
              </div>
              <div style={{display:"flex",flexDirection:"column",gap:"0.4rem"}}>
                <label style={lbl}>Buyer Phone</label>
                <input style={{...inp,background:"#fff"}} placeholder="+234..." value={form.buyerPhone} onChange={e=>setForm({...form,buyerPhone:e.target.value})} onFocus={ev=>ev.target.style.borderColor="#F47B20"} onBlur={ev=>ev.target.style.borderColor="#E5E5E5"}/>
              </div>
            </div>
            <div style={{display:"flex",flexDirection:"column",gap:"0.4rem"}}>
              <label style={lbl}>Buyer Email</label>
              <input style={{...inp,background:"#fff"}} type="email" placeholder="buyer@email.com" value={form.buyerEmail} onChange={e=>setForm({...form,buyerEmail:e.target.value})} onFocus={ev=>ev.target.style.borderColor="#F47B20"} onBlur={ev=>ev.target.style.borderColor="#E5E5E5"}/>
            </div>
          </div>

          <div style={{display:"flex",flexDirection:"column",gap:"0.4rem"}}>
            <label style={lbl}>Notes / Remarks</label>
            <textarea style={{...inp,minHeight:"70px",resize:"vertical" as const}} placeholder="Any notes about this sale..." value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})} onFocus={ev=>ev.target.style.borderColor="#F47B20"} onBlur={ev=>ev.target.style.borderColor="#E5E5E5"}/>
          </div>

          {/* Profit preview */}
          {form.sellingPrice && form.purchasePrice && (
            <div style={{background:"#F0FDF4",border:"1px solid #86EFAC",borderRadius:"8px",padding:"0.875rem",display:"flex",gap:"1rem",flexWrap:"wrap"}}>
              {[
                ["Selling Price",`₦${parseFloat(form.sellingPrice||"0").toLocaleString()}`,"#16A34A"],
                ["Cost Price",`₦${parseFloat(form.purchasePrice||"0").toLocaleString()}`,"#737373"],
                ["Gross Profit",`₦${(parseFloat(form.sellingPrice||"0")-parseFloat(form.purchasePrice||"0")).toLocaleString()}`, (parseFloat(form.sellingPrice||"0")-parseFloat(form.purchasePrice||"0"))>=0?"#16A34A":"#DC2626"],
              ].map(([l,v,c])=>(
                <div key={l} style={{flex:1,minWidth:"100px"}}>
                  <div style={{fontSize:"0.68rem",color:"#737373",fontWeight:600}}>{l}</div>
                  <div style={{fontSize:"1rem",fontWeight:700,color:c as string}}>{v}</div>
                </div>
              ))}
            </div>
          )}

          <div style={{display:"flex",gap:"0.75rem",marginTop:"0.5rem"}}>
            <button type="button" onClick={onClose} style={{flex:1,background:"#F5F5F5",border:"1.5px solid #E5E5E5",color:"#525252",borderRadius:"10px",padding:"0.875rem",fontFamily:"var(--font-body)",fontSize:"0.9rem",cursor:"pointer",fontWeight:600}}>Cancel</button>
            <button type="submit" disabled={loading||!form.sellingPrice} style={{flex:2,background:loading||!form.sellingPrice?"#D4D4D4":"#F47B20",color:"#fff",border:"none",borderRadius:"10px",padding:"0.875rem",fontFamily:"var(--font-display)",fontSize:"0.95rem",letterSpacing:"0.1em",cursor:loading||!form.sellingPrice?"not-allowed":"pointer",fontWeight:700}}>
              {loading?"Recording sale...":"CONFIRM SALE ✓"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
