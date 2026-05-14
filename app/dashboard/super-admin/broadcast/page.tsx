"use client";
import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";

const ROLE_OPTIONS = [
  { value:"all",          label:"All Users",       icon:"👥" },
  { value:"PUBLIC_USER",  label:"Buyers Only",     icon:"🛒" },
  { value:"DEALER_ADMIN", label:"Dealers Only",    icon:"🏢" },
  { value:"DEALER_STAFF", label:"Staff Only",      icon:"👤" },
  { value:"PARTNER_USER", label:"Partners Only",   icon:"🤝" },
  { value:"specific",     label:"Specific Users",  icon:"🎯" },
];

export default function BroadcastPage() {
  const [form, setForm] = useState({ title:"", message:"", targetRole:"all", type:"announcement" });
  const [attachUrl, setAttachUrl]   = useState("");
  const [attachName, setAttachName] = useState("");
  const [attachType, setAttachType] = useState<"image"|"video"|"document"|"">("");
  const [uploading, setUploading]   = useState(false);
  const [sending, setSending]       = useState(false);
  const [result, setResult]         = useState<any>(null);
  const [err, setErr]               = useState("");
  const [history, setHistory]       = useState<any[]>([]);

  // Specific user search
  const [userSearch, setUserSearch]     = useState("");
  const [userResults, setUserResults]   = useState<any[]>([]);
  const [selectedUsers, setSelectedUsers] = useState<any[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get("/api/v1/admin/broadcasts").then(r=>setHistory(r.data?.broadcasts||[])).catch(()=>{});
  }, []);

  // User search debounce
  useEffect(() => {
    if (userSearch.length < 2 || form.targetRole !== "specific") { setUserResults([]); return; }
    setSearchLoading(true);
    const t = setTimeout(async () => {
      try {
        const res = await api.get("/api/v1/admin/users", { params:{ search:userSearch, limit:10 } });
        setUserResults(res.data?.users || []);
      } catch { }
      finally { setSearchLoading(false); }
    }, 350);
    return () => clearTimeout(t);
  }, [userSearch, form.targetRole]);

  const addUser = (u: any) => {
    if (!selectedUsers.find(x => x._id === u._id)) {
      setSelectedUsers(p => [...p, u]);
    }
    setUserSearch(""); setUserResults([]);
  };
  const removeUser = (id: string) => setSelectedUsers(p => p.filter(u => u._id !== id));

  const handleAttach = async (file: File) => {
    setUploading(true); setErr("");
    try {
      const fd = new FormData(); fd.append("file", file);
      const res = await api.post("/api/v1/admin/upload/document", fd, { headers:{"Content-Type":"multipart/form-data"} });
      setAttachUrl(res.data.url);
      setAttachName(res.data.name || file.name);
      setAttachType(res.data.type || (res.data.isVideo?"video":res.data.isImage?"image":"document"));
    } catch(e:any) { setErr("Upload failed: " + (e.response?.data?.detail || e.message)); }
    finally { setUploading(false); }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title.trim() || !form.message.trim()) { setErr("Title and message are required"); return; }
    if (form.targetRole === "specific" && selectedUsers.length === 0) { setErr("Select at least one user"); return; }
    setSending(true); setErr("");
    try {
      const payload: any = {
        title: form.title, message: form.message,
        targetRole: form.targetRole === "specific" ? "all" : form.targetRole,
      };
      if (form.targetRole === "specific") {
        payload.targetUserIds = selectedUsers.map(u => u._id || u.userId);
      }
      if (attachUrl) {
        payload.documentUrl = attachUrl;
        payload.documentName = attachName;
        payload.documentType = attachType;
      }
      const res = await api.post("/api/v1/admin/broadcast", payload);
      setResult(res.data);
      setHistory(prev => [{...form, attachUrl, attachName, attachType, sentAt:new Date().toISOString(), sentTo:res.data.sentTo||0, selectedUsers:[...selectedUsers]}, ...prev]);
      setForm({ title:"", message:"", targetRole:"all", type:"announcement" });
      setAttachUrl(""); setAttachName(""); setAttachType("");
      setSelectedUsers([]); setUserSearch("");
    } catch(e:any) { setErr(e.response?.data?.detail || "Failed to send"); }
    finally { setSending(false); }
  };

  const fmtDate = (iso: string) => { try { return new Date(iso).toLocaleString("en-NG"); } catch { return "-"; } };
  const fi: React.CSSProperties = { background:"#F5F5F5", border:"1.5px solid #E5E5E5", borderRadius:"8px", padding:"0.75rem 1rem", color:"#1A1A1A", fontSize:"0.875rem", fontFamily:"var(--font-body)", outline:"none", width:"100%", boxSizing:"border-box" as const };
  const lbl: React.CSSProperties = { fontSize:"0.68rem", fontWeight:700, letterSpacing:"0.1em", textTransform:"uppercase" as const, color:"#525252", display:"block", marginBottom:"0.35rem" };

  return (
    <div style={{display:"flex",flexDirection:"column",gap:"1.5rem",fontFamily:"var(--font-body)"}}>
      <div>
        <h2 style={{fontFamily:"var(--font-display)",fontSize:"1.6rem",letterSpacing:"0.05em",color:"#1A1A1A",lineHeight:1}}>Broadcast Messages</h2>
        <p style={{fontSize:"0.82rem",color:"#737373",marginTop:"0.3rem"}}>Send announcements with attachments — delivered to recipients' inbox as an announcement they can view and reply to.</p>
      </div>

      {result && (
        <div style={{background:"#F0FDF4",border:"1px solid #86EFAC",color:"#15803D",padding:"0.875rem 1.25rem",borderRadius:"8px",fontSize:"0.875rem",display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <span>✅ Sent to <strong>{result.sentTo||"all"}</strong> users successfully.</span>
          <button onClick={()=>setResult(null)} style={{background:"none",border:"none",color:"inherit",cursor:"pointer"}}>✕</button>
        </div>
      )}
      {err && (
        <div style={{background:"#FEF2F2",border:"1px solid #FCA5A5",color:"#DC2626",padding:"0.875rem 1.25rem",borderRadius:"8px",fontSize:"0.875rem",display:"flex",justifyContent:"space-between"}}>
          <span>❌ {err}</span><button onClick={()=>setErr("")} style={{background:"none",border:"none",color:"inherit",cursor:"pointer"}}>✕</button>
        </div>
      )}

      <div style={{display:"grid",gridTemplateColumns:"1fr 340px",gap:"1.25rem"}}>
        {/* Compose */}
        <div style={{background:"#fff",border:"1.5px solid #E5E5E5",borderRadius:"12px",padding:"1.5rem",display:"flex",flexDirection:"column",gap:"1.25rem"}}>
          <div style={{fontFamily:"var(--font-display)",fontSize:"0.78rem",letterSpacing:"0.15em",color:"#737373"}}>COMPOSE ANNOUNCEMENT</div>

          <form onSubmit={handleSend} style={{display:"flex",flexDirection:"column",gap:"1.25rem"}}>

            {/* Target audience */}
            <div>
              <label style={lbl}>Send To</label>
              <div style={{display:"flex",flexDirection:"column",gap:"0.35rem"}}>
                {ROLE_OPTIONS.map(r => (
                  <button key={r.value} type="button" onClick={()=>{setForm({...form,targetRole:r.value});setSelectedUsers([]);}}
                    style={{display:"flex",alignItems:"center",gap:"0.75rem",padding:"0.55rem 0.875rem",background:form.targetRole===r.value?"#FFF7ED":"#F5F5F5",border:`1.5px solid ${form.targetRole===r.value?"#F47B20":"#E5E5E5"}`,borderRadius:"8px",cursor:"pointer",fontFamily:"var(--font-body)",fontSize:"0.825rem",color:form.targetRole===r.value?"#C4621A":"#525252",transition:"all 0.2s",textAlign:"left" as const}}>
                    <span>{r.icon}</span><span>{r.label}</span>
                    {form.targetRole===r.value&&<span style={{marginLeft:"auto",color:"#F47B20",fontWeight:700}}>✓</span>}
                  </button>
                ))}
              </div>
            </div>

            {/* Specific user search */}
            {form.targetRole === "specific" && (
              <div>
                <label style={lbl}>Search & Select Recipients</label>
                <div style={{position:"relative"}}>
                  <input style={{...fi,paddingRight:"2rem"}} placeholder="Search by name, email or username..."
                    value={userSearch} onChange={e=>setUserSearch(e.target.value)} />
                  {searchLoading && <span style={{position:"absolute",right:"0.75rem",top:"50%",transform:"translateY(-50%)",fontSize:"0.8rem",color:"#A3A3A3"}}>⏳</span>}
                  {userResults.length > 0 && (
                    <div style={{position:"absolute",top:"calc(100%+4px)",left:0,right:0,background:"#fff",border:"1.5px solid #E5E5E5",borderRadius:"8px",zIndex:50,maxHeight:"200px",overflowY:"auto",boxShadow:"0 8px 24px rgba(0,0,0,0.1)"}}>
                      {userResults.map(u => (
                        <div key={u._id} onClick={()=>addUser(u)}
                          style={{display:"flex",alignItems:"center",gap:"0.625rem",padding:"0.625rem 0.875rem",cursor:"pointer",borderBottom:"1px solid #F5F5F5",transition:"background 0.15s"}}
                          onMouseEnter={e=>(e.currentTarget as HTMLElement).style.background="#FFF7ED"}
                          onMouseLeave={e=>(e.currentTarget as HTMLElement).style.background="#fff"}>
                          <div style={{width:"28px",height:"28px",borderRadius:"50%",background:"#F47B20",color:"#fff",display:"flex",alignItems:"center",justifyContent:"center",fontSize:"0.8rem",flexShrink:0}}>
                            {u.fullName?.charAt(0)||"?"}
                          </div>
                          <div>
                            <div style={{fontSize:"0.825rem",fontWeight:500,color:"#1A1A1A"}}>{u.fullName}</div>
                            <div style={{fontSize:"0.7rem",color:"#A3A3A3"}}>{u.role?.replace(/_/g," ")} · {u.email}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {selectedUsers.length > 0 && (
                  <div style={{display:"flex",flexWrap:"wrap",gap:"0.4rem",marginTop:"0.625rem"}}>
                    {selectedUsers.map(u => (
                      <div key={u._id} style={{background:"#FFF7ED",border:"1px solid rgba(244,123,32,0.3)",borderRadius:"20px",padding:"0.25rem 0.625rem",fontSize:"0.75rem",color:"#C4621A",display:"flex",alignItems:"center",gap:"0.375rem"}}>
                        {u.fullName}
                        <button type="button" onClick={()=>removeUser(u._id)} style={{background:"none",border:"none",cursor:"pointer",color:"#DC2626",fontSize:"0.8rem",padding:0,lineHeight:1}}>×</button>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{fontSize:"0.7rem",color:"#A3A3A3",marginTop:"0.375rem"}}>{selectedUsers.length} recipient{selectedUsers.length!==1?"s":""} selected</div>
              </div>
            )}

            {/* Type pills */}
            <div>
              <label style={lbl}>Message Type</label>
              <div style={{display:"flex",gap:"0.4rem",flexWrap:"wrap"}}>
                {["announcement","warning","update","promotion","onboarding"].map(t=>(
                  <button key={t} type="button" onClick={()=>setForm({...form,type:t})}
                    style={{background:form.type===t?"#1A1A1A":"transparent",border:"1.5px solid",borderColor:form.type===t?"#1A1A1A":"#E5E5E5",borderRadius:"20px",padding:"0.3rem 0.875rem",fontSize:"0.75rem",cursor:"pointer",color:form.type===t?"#fff":"#737373",fontFamily:"var(--font-body)",textTransform:"capitalize" as const,transition:"all 0.2s"}}>
                    {t}
                  </button>
                ))}
              </div>
            </div>

            {/* Title */}
            <div>
              <label style={lbl}>Subject / Title *</label>
              <input style={fi} placeholder="e.g. Welcome to CARSTRIMS!" value={form.title} onChange={e=>setForm({...form,title:e.target.value})} required/>
            </div>

            {/* Message */}
            <div>
              <label style={lbl}>Message Body *</label>
              <textarea style={{...fi,minHeight:"140px",resize:"vertical" as const}} rows={6}
                placeholder="Write your message. Recipients can view and reply to this in their inbox." value={form.message} onChange={e=>setForm({...form,message:e.target.value})} required/>
              <div style={{fontSize:"0.68rem",color:"#A3A3A3",textAlign:"right",marginTop:"0.25rem"}}>{form.message.length} characters</div>
            </div>

            {/* Attachment: image, video, or document */}
            <div>
              <label style={lbl}>Attachment <span style={{fontWeight:400,textTransform:"none" as const,color:"#A3A3A3"}}>(image, video, or document)</span></label>
              {attachUrl ? (
                <div style={{display:"flex",alignItems:"center",gap:"0.75rem",background:"#F5F5F5",border:"1.5px solid #E5E5E5",borderRadius:"8px",padding:"0.75rem"}}>
                  {attachType==="image" && <img src={attachUrl} alt="" style={{width:"56px",height:"44px",objectFit:"cover",borderRadius:"4px"}}/>}
                  {attachType==="video" && <video src={attachUrl} style={{width:"56px",height:"44px",objectFit:"cover",borderRadius:"4px"}}/>}
                  {attachType==="document" && <span style={{fontSize:"1.5rem"}}>📄</span>}
                  <div style={{flex:1,minWidth:0}}>
                    <div style={{fontSize:"0.8rem",fontWeight:600,color:"#1A1A1A",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{attachName}</div>
                    <div style={{fontSize:"0.7rem",color:"#A3A3A3",textTransform:"capitalize"}}>{attachType} attachment</div>
                  </div>
                  <button type="button" onClick={()=>{setAttachUrl("");setAttachName("");setAttachType("");}}
                    style={{background:"#FEF2F2",border:"1px solid rgba(220,38,38,0.3)",color:"#DC2626",borderRadius:"6px",padding:"0.3rem 0.6rem",fontSize:"0.75rem",cursor:"pointer"}}>
                    ✕ Remove
                  </button>
                </div>
              ) : (
                <button type="button" onClick={()=>fileRef.current?.click()} disabled={uploading}
                  style={{background:"#F5F5F5",border:"1.5px dashed #D4D4D4",borderRadius:"8px",padding:"0.875rem 1.25rem",fontSize:"0.825rem",cursor:"pointer",color:"#737373",width:"100%",display:"flex",alignItems:"center",justifyContent:"center",gap:"0.5rem",opacity:uploading?0.6:1}}>
                  {uploading?"⏳ Uploading...":"📎 Attach image, video, or document"}
                </button>
              )}
              <input ref={fileRef} type="file" accept="image/*,video/*,application/pdf,.doc,.docx"
                style={{display:"none"}} onChange={e=>{const f=e.target.files?.[0];if(f) handleAttach(f); e.target.value="";}}/>
            </div>

            {/* Preview */}
            <div style={{background:"#F5F5F5",border:"1.5px solid #E5E5E5",borderLeft:"3px solid #F47B20",borderRadius:"8px",padding:"1rem",display:"flex",flexDirection:"column",gap:"0.4rem"}}>
              <div style={{fontSize:"0.65rem",letterSpacing:"0.12em",textTransform:"uppercase" as const,color:"#A3A3A3"}}>Preview (as seen by recipient)</div>
              <div style={{fontWeight:700,fontSize:"0.9rem",color:"#1A1A1A"}}>{form.title||"Your announcement title..."}</div>
              <div style={{fontSize:"0.8rem",color:"#737373",lineHeight:1.5,whiteSpace:"pre-wrap"}}>{form.message||"Your message body will appear here..."}</div>
              {attachUrl && attachType==="image" && <img src={attachUrl} alt="" style={{maxWidth:"180px",borderRadius:"6px",marginTop:"0.25rem"}}/>}
              {attachUrl && attachType==="video" && <video src={attachUrl} controls style={{maxWidth:"100%",borderRadius:"6px",maxHeight:"120px",marginTop:"0.25rem"}}/>}
              {attachUrl && attachType==="document" && <div style={{fontSize:"0.78rem",color:"#1D4ED8"}}>📄 {attachName}</div>}
            </div>

            <button type="submit" disabled={sending||uploading}
              style={{background:"#F47B20",color:"#fff",border:"none",borderRadius:"8px",padding:"0.875rem",fontFamily:"var(--font-display)",fontSize:"0.9rem",letterSpacing:"0.1em",cursor:"pointer",opacity:sending||uploading?0.6:1,transition:"opacity 0.2s"}}>
              {sending?"Sending...":`📢 Send Announcement${form.targetRole==="specific"&&selectedUsers.length>0?` to ${selectedUsers.length} user${selectedUsers.length!==1?"s":""}`:""}`}
            </button>
          </form>
        </div>

        {/* History sidebar */}
        <div style={{background:"#fff",border:"1.5px solid #E5E5E5",borderRadius:"12px",padding:"1.5rem",display:"flex",flexDirection:"column",gap:"1rem"}}>
          <div style={{fontFamily:"var(--font-display)",fontSize:"0.78rem",letterSpacing:"0.15em",color:"#737373"}}>SENT BROADCASTS</div>
          {history.length===0 ? (
            <div style={{display:"flex",flexDirection:"column",alignItems:"center",gap:"0.5rem",padding:"2rem",textAlign:"center",color:"#737373",fontSize:"0.875rem"}}>
              <span style={{fontSize:"2rem"}}>📭</span><p>No broadcasts sent yet</p>
            </div>
          ) : (
            <div style={{display:"flex",flexDirection:"column",gap:"0.75rem",overflowY:"auto",maxHeight:"640px"}}>
              {history.map((h,i)=>(
                <div key={i} style={{background:"#F5F5F5",border:"1px solid #E5E5E5",borderRadius:"8px",padding:"0.875rem",display:"flex",flexDirection:"column",gap:"0.3rem"}}>
                  <div style={{display:"flex",alignItems:"center",gap:"0.4rem",flexWrap:"wrap"}}>
                    <span style={{fontSize:"0.68rem",fontWeight:600,textTransform:"capitalize" as const,padding:"0.15rem 0.5rem",borderRadius:"20px",background:"rgba(244,123,32,0.1)",color:"#F47B20",border:"1px solid rgba(244,123,32,0.2)"}}>{h.type||"announcement"}</span>
                    <span style={{fontSize:"0.68rem",color:"#A3A3A3"}}>→ {h.selectedUsers?.length>0?`${h.selectedUsers.length} users`:ROLE_OPTIONS.find(r=>r.value===h.targetRole)?.label||h.targetRole}</span>
                    {h.sentTo&&<span style={{fontSize:"0.65rem",color:"#A3A3A3",marginLeft:"auto"}}>{h.sentTo} sent</span>}
                  </div>
                  <div style={{fontWeight:600,fontSize:"0.875rem",color:"#1A1A1A"}}>{h.title}</div>
                  <div style={{fontSize:"0.78rem",color:"#737373",lineHeight:1.4}}>{(h.message||"").slice(0,80)}{(h.message||"").length>80?"...":""}</div>
                  {h.attachType&&<div style={{fontSize:"0.7rem",color:"#737373",textTransform:"capitalize"}}>📎 {h.attachType}: {h.attachName||"attachment"}</div>}
                  <div style={{fontSize:"0.68rem",color:"#A3A3A3",fontFamily:"monospace"}}>{fmtDate(h.sentAt)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <style>{`@media(max-width:900px){div[style*="gridTemplateColumns:1fr 340px"]{grid-template-columns:1fr!important}}`}</style>
    </div>
  );
}
