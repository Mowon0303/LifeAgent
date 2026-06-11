// Direction B — "Bold Blocks / Command"
// Warm paper calendar with solid color event blocks; deep-ink AI command panel.
function DirectionB() {
  const C = window.CAL;
  const byDay = {};
  C.events.forEach(e => { (byDay[e.day] = byDay[e.day] || []).push(e); });
  const cells = [];
  for (let d = 1; d <= C.DAYS_IN_MONTH; d++) cells.push({ day: d, out: false });
  let t = 1; while (cells.length < 35) cells.push({ day: t++, out: true });

  return (
    <div className="dB">
      <style>{`
        .dB { width:1440px; height:940px; display:flex; background:#EFE9DC;
          font-family:'IBM Plex Sans',sans-serif; color:#221F1A; }
        .dB-cal { flex:1; display:flex; flex-direction:column; padding:30px 32px; min-width:0; }
        .dB-top { display:flex; align-items:center; justify-content:space-between; margin-bottom:24px; }
        .dB-tl { display:flex; align-items:center; gap:18px; }
        .dB-title { font-size:40px; font-weight:700; letter-spacing:-1px; line-height:1; }
        .dB-title em { font-style:normal; color:#A2937B; font-weight:500; }
        .dB-nav { display:flex; gap:6px; }
        .dB-nav button { width:38px; height:38px; border-radius:11px; border:0; background:#E2D9C6; color:#5C5446;
          font-size:17px; cursor:pointer; }
        .dB-nav button:hover { background:#D6CBB4; }
        .dB-seg { display:flex; background:#221F1A; border-radius:13px; padding:4px; gap:3px; }
        .dB-seg button { border:0; background:transparent; color:#A6A096; padding:9px 18px; border-radius:9px;
          font-size:13px; font-weight:600; cursor:pointer; }
        .dB-seg button.on { background:#2A6FDB; color:#fff; }
        .dB-week { display:grid; grid-template-columns:repeat(7,1fr); gap:10px; margin-bottom:10px; }
        .dB-week span { font-size:12px; font-weight:700; letter-spacing:.06em; color:#9A8C76; text-transform:uppercase; }
        .dB-grid { flex:1; display:grid; grid-template-columns:repeat(7,1fr); grid-template-rows:repeat(5,1fr); gap:10px; }
        .dB-cell { background:#FBF8F1; border-radius:14px; padding:9px 9px 7px; display:flex; flex-direction:column; gap:5px;
          min-height:0; overflow:hidden; box-shadow:0 1px 2px rgba(80,60,20,.04); }
        .dB-cell.out { background:rgba(251,248,241,.45); }
        .dB-cell.today { box-shadow:0 0 0 2px #2A6FDB, 0 6px 16px rgba(42,111,219,.18); }
        .dB-dn { font-size:14px; font-weight:700; color:#3A352D; }
        .dB-cell.out .dB-dn { color:#C2B6A0; font-weight:600; }
        .dB-cell.today .dB-dn { color:#2A6FDB; }
        .dB-blk { border-radius:7px; padding:4px 8px; font-size:11.5px; font-weight:600; line-height:1.25;
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .dB-blk .tm { font-weight:700; opacity:.7; margin-right:5px; }
        .dB-blk.pending { background:transparent !important; border:1.5px dashed; }
        .dB-more { font-size:10.5px; font-weight:600; color:#A2937B; padding-left:2px; }

        /* command panel */
        .dB-ai { width:440px; flex:none; background:#1A2029; display:flex; flex-direction:column; color:#E7E3DA; }
        .dB-ai-h { padding:26px 26px 20px; display:flex; align-items:center; gap:13px; border-bottom:1px solid #2A323D; }
        .dB-orb { width:40px; height:40px; border-radius:13px; flex:none; position:relative;
          background:radial-gradient(circle at 32% 30%,#5B92F0,#2A6FDB 60%,#1F4FA0); box-shadow:0 0 22px rgba(42,111,219,.5); }
        .dB-orb:after { content:''; position:absolute; inset:13px 13px auto 13px; height:3px; border-radius:2px; background:rgba(255,255,255,.85); box-shadow:0 6px 0 rgba(255,255,255,.55); }
        .dB-ai-h .nm { font-size:18px; font-weight:700; }
        .dB-ai-h .st { font-size:11px; color:#6FCF8E; margin-top:3px; font-weight:600; letter-spacing:.03em; white-space:nowrap; }
        .dB-thread { flex:1; overflow:hidden; padding:24px 26px; display:flex; flex-direction:column; gap:17px; }
        .dB-ma { font-size:14.5px; line-height:1.6; color:#C9C4B9; }
        .dB-mu { align-self:flex-end; background:#2A6FDB; color:#fff; padding:11px 15px; border-radius:15px 15px 5px 15px;
          font-size:14px; line-height:1.5; max-width:300px; }
        .dB-sum { background:#222A35; border-radius:16px; padding:6px 18px; }
        .dB-sum .row { display:flex; align-items:center; gap:14px; padding:13px 0; border-bottom:1px solid #2C3540; }
        .dB-sum .row:last-child { border-bottom:0; }
        .dB-sum .big { font-size:30px; font-weight:800; line-height:1; min-width:40px; }
        .dB-sum .big.u { color:#FF8A66; }
        .dB-sum .lab { font-size:14px; font-weight:600; color:#E7E3DA; }
        .dB-sum .sub { font-size:12px; color:#8A8576; margin-top:2px; }
        .dB-card { border:1.5px dashed #5B6DC8; border-radius:16px; padding:17px; background:rgba(91,109,200,.08); }
        .dB-card .ct { font-size:15.5px; font-weight:700; display:flex; align-items:center; gap:9px; }
        .dB-card .ct .pin { width:8px; height:8px; border-radius:50%; background:#8B9BF0; }
        .dB-card .cw { font-size:12.5px; color:#9BA8E8; font-weight:600; margin:7px 0 2px; }
        .dB-card .cs { font-size:11.5px; color:#7C7768; }
        .dB-card .note { font-size:13px; color:#B7B2A7; line-height:1.55; margin:12px 0 14px; }
        .dB-acts { display:flex; gap:9px; }
        .dB-bt { flex:1; height:40px; border-radius:11px; font-size:13.5px; font-weight:700; cursor:pointer; border:0; }
        .dB-bt.prim { background:#2A6FDB; color:#fff; }
        .dB-bt.ghost { background:#2C3540; color:#C9C4B9; }
        .dB-input { margin:0 22px 24px; background:#222A35; border-radius:15px; padding:14px 16px; display:flex;
          align-items:center; gap:10px; }
        .dB-input span { flex:1; font-size:14px; color:#6F6A5E; }
        .dB-snd { width:32px; height:32px; border-radius:9px; background:#2A6FDB; color:#fff; display:flex;
          align-items:center; justify-content:center; }
      `}</style>

      <div className="dB-cal">
        <div className="dB-top">
          <div className="dB-tl">
            <div className="dB-title">六月 <em>2026</em></div>
            <div className="dB-nav"><button>‹</button><button>›</button></div>
          </div>
          <div className="dB-seg">
            <button className="on">月</button><button>周</button><button>日</button><button>议程</button>
          </div>
        </div>

        <div className="dB-week">
          {C.WEEKDAYS.map(w => <span key={w}>周{w}</span>)}
        </div>
        <div className="dB-grid">
          {cells.map((c, i) => {
            const evs = c.out ? [] : (byDay[c.day] || []);
            const show = evs.slice(0, 3);
            const isToday = !c.out && c.day === C.TODAY;
            return (
              <div key={i} className={'dB-cell' + (c.out ? ' out' : '') + (isToday ? ' today' : '')}>
                <div className="dB-dn">{c.out && c.day === 1 ? '7/1' : c.day}</div>
                {show.map(e => {
                  const m = C.typeMeta[e.type];
                  const pending = e.status === 'pending';
                  return (
                    <div key={e.id} className={'dB-blk' + (pending ? ' pending' : '')}
                      style={pending ? { color: m.ink, borderColor: m.ink } : { background: m.soft, color: m.ink }}>
                      {!e.allDay && <span className="tm">{e.start}</span>}{e.title}
                    </div>
                  );
                })}
                {evs.length > 3 && <div className="dB-more">+{evs.length - 3}</div>}
              </div>
            );
          })}
        </div>
      </div>

      <div className="dB-ai">
        <div className="dB-ai-h">
          <div className="dB-orb" />
          <div>
            <div className="nm">日程助手</div>
            <div className="st">● 已扫描 4 个邮箱 · 7 条新发现</div>
          </div>
        </div>
        <div className="dB-thread">
          <div className="dB-ma">{C.chat[0].text}</div>
          <div className="dB-sum">
            {C.chat[1].bullets.map((b, i) => (
              <div className="row" key={i}>
                <div className={'big' + (b.urgent ? ' u' : '')}>{b.t.match(/\d+/)[0]}</div>
                <div>
                  <div className="lab">{b.t.replace(/^\d+\s*/, '')}</div>
                  <div className="sub">{b.sub}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="dB-card">
            <div className="ct"><span className="pin" />{C.chat[2].event.title}</div>
            <div className="cw">{C.chat[2].event.when}</div>
            <div className="cs">{C.chat[2].event.source}</div>
            <div className="note">{C.chat[2].note}</div>
            <div className="dB-acts">
              <button className="dB-bt prim">确认加入</button>
              <button className="dB-bt ghost">忽略</button>
            </div>
          </div>
          <div className="dB-mu">{C.chat[3].text}</div>
        </div>
        <div className="dB-input">
          <span>输入指令，或问我任何日程…</span>
          <div className="dB-snd">↑</div>
        </div>
      </div>
    </div>
  );
}
window.DirectionB = DirectionB;
