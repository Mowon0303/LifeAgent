// Direction A — "Warm Paper / Editorial"
// Cream paper, Newsreader serif display, hairline rules, restrained blue.
function DirectionA() {
  const C = window.CAL;
  const byDay = {};
  C.events.forEach(e => { (byDay[e.day] = byDay[e.day] || []).push(e); });

  // build 35 cells, Monday-first, June 2026 (Jun 1 = Mon)
  const cells = [];
  for (let d = 1; d <= C.DAYS_IN_MONTH; d++) cells.push({ day: d, out: false });
  let t = 1;
  while (cells.length < 35) cells.push({ day: t++, out: true });

  return (
    <div className="dA">
      <style>{`
        .dA { width:1440px; height:940px; display:flex; background:#F4EFE6;
          font-family:'IBM Plex Sans',sans-serif; color:#2B2622; position:relative; }
        .dA-cal { flex:1; display:flex; flex-direction:column; padding:34px 34px 26px; min-width:0; }
        .dA-top { display:flex; align-items:flex-end; justify-content:space-between; margin-bottom:26px; }
        .dA-title { font-family:'Newsreader',serif; font-weight:500; font-size:46px; line-height:1;
          letter-spacing:-0.5px; display:flex; align-items:baseline; gap:14px; }
        .dA-title .yr { font-size:22px; color:#A89A86; font-weight:400; }
        .dA-nav { display:flex; align-items:center; gap:6px; }
        .dA-chev { width:34px; height:34px; border:1px solid #E0D6C4; border-radius:50%; background:transparent;
          display:flex; align-items:center; justify-content:center; cursor:pointer; color:#6B6253; font-size:15px; }
        .dA-chev:hover { background:#EDE5D6; }
        .dA-today { height:34px; padding:0 16px; border:1px solid #E0D6C4; border-radius:18px; background:#FBF8F1;
          font-family:'IBM Plex Mono',monospace; font-size:12px; letter-spacing:.04em; cursor:pointer; color:#4A4439; }
        .dA-views { display:flex; gap:2px; background:#EBE2D2; border-radius:10px; padding:3px; }
        .dA-views button { border:0; background:transparent; padding:7px 14px; border-radius:7px;
          font-family:'IBM Plex Mono',monospace; font-size:12px; letter-spacing:.05em; color:#8A7F6D; cursor:pointer; }
        .dA-views button.on { background:#FBF8F1; color:#2B2622; box-shadow:0 1px 2px rgba(60,40,10,.08); }
        .dA-week { display:grid; grid-template-columns:repeat(7,1fr); margin-bottom:8px; }
        .dA-week span { font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:.12em; text-transform:uppercase;
          color:#A89A86; padding:0 4px; }
        .dA-week span.we { color:#C0936F; }
        .dA-grid { flex:1; display:grid; grid-template-columns:repeat(7,1fr); grid-template-rows:repeat(5,1fr);
          border-top:1px solid #E4DBC9; border-left:1px solid #E4DBC9; }
        .dA-cell { border-right:1px solid #E4DBC9; border-bottom:1px solid #E4DBC9; padding:8px 8px 6px;
          display:flex; flex-direction:column; gap:4px; min-height:0; overflow:hidden; position:relative; }
        .dA-cell.out { background:rgba(0,0,0,.012); }
        .dA-dn { font-family:'IBM Plex Mono',monospace; font-size:13px; color:#6B6253; line-height:1; }
        .dA-cell.out .dA-dn { color:#C3B7A2; }
        .dA-today-mark { width:24px; height:24px; border-radius:50%; background:#2A6FDB; color:#fff;
          display:flex; align-items:center; justify-content:center; font-family:'IBM Plex Mono',monospace; font-size:13px; }
        .dA-chip { display:flex; align-items:center; gap:6px; padding:2px 6px; border-radius:5px; background:#fff;
          font-size:11.5px; line-height:1.25; white-space:nowrap; overflow:hidden; }
        .dA-chip .dot { width:6px; height:6px; border-radius:50%; flex:none; }
        .dA-chip .tm { font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:#9A8E7B; flex:none; }
        .dA-chip .lb { overflow:hidden; text-overflow:ellipsis; }
        .dA-chip.pending { background:repeating-linear-gradient(135deg,#fff,#fff 5px,#F3EFFB 5px,#F3EFFB 10px);
          border:1px dashed #B4A7E8; }
        .dA-more { font-family:'IBM Plex Mono',monospace; font-size:10px; color:#A89A86; padding-left:2px; }

        /* AI panel */
        .dA-ai { width:430px; flex:none; background:#FBF8F1; border-left:1px solid #E4DBC9;
          display:flex; flex-direction:column; }
        .dA-ai-h { padding:24px 26px 18px; border-bottom:1px solid #EDE4D3; display:flex; align-items:center; gap:12px; }
        .dA-mark { width:34px; height:34px; border-radius:10px; background:#2A6FDB; position:relative; flex:none; }
        .dA-mark:before { content:''; position:absolute; inset:9px; border:2px solid #fff; border-radius:3px;
          border-top-width:5px; }
        .dA-ai-h .nm { font-family:'Newsreader',serif; font-size:21px; }
        .dA-ai-h .st { font-family:'IBM Plex Mono',monospace; font-size:10.5px; letter-spacing:.08em; color:#7FA86B; margin-top:2px;
          display:flex; align-items:center; gap:6px; white-space:nowrap; }
        .dA-ai-h .st:before { content:''; width:6px; height:6px; border-radius:50%; background:#7FA86B; }
        .dA-thread { flex:1; overflow:hidden; padding:22px 26px; display:flex; flex-direction:column; gap:16px; }
        .dA-msg-ai { font-size:14.5px; line-height:1.55; color:#3A352D; max-width:330px; }
        .dA-msg-u { align-self:flex-end; background:#2A6FDB; color:#fff; padding:10px 14px; border-radius:14px 14px 4px 14px;
          font-size:14px; line-height:1.5; max-width:300px; }
        .dA-sum { border:1px solid #EAE0CE; background:#fff; border-radius:14px; padding:16px; }
        .dA-sum h4 { font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:.08em; text-transform:uppercase;
          color:#A89A86; margin:0 0 12px; }
        .dA-sum .row { display:flex; gap:11px; padding:8px 0; border-top:1px solid #F1EADB; align-items:flex-start; }
        .dA-sum .row:first-of-type { border-top:0; }
        .dA-sum .num { font-family:'Newsreader',serif; font-size:20px; line-height:1; color:#2B2622; min-width:54px; }
        .dA-sum .num.u { color:#B14228; }
        .dA-sum .tx { font-size:13px; color:#7C7263; line-height:1.4; padding-top:3px; }
        .dA-evcard { border:1px dashed #B4A7E8; background:repeating-linear-gradient(135deg,#fff,#fff 7px,#F6F3FC 7px,#F6F3FC 14px);
          border-radius:14px; padding:15px; }
        .dA-evcard .et { display:flex; align-items:center; gap:8px; font-weight:600; font-size:15px; }
        .dA-evcard .et .pin { width:7px; height:7px; border-radius:50%; background:#6A5BD0; }
        .dA-evcard .ew { font-family:'IBM Plex Mono',monospace; font-size:12px; color:#6A5BD0; margin:6px 0 2px; }
        .dA-evcard .es { font-size:11.5px; color:#A89A86; }
        .dA-evcard .note { font-size:13px; color:#5A5247; line-height:1.5; margin:11px 0 13px; }
        .dA-evcard .acts { display:flex; gap:8px; }
        .dA-btn { flex:1; height:36px; border-radius:9px; font-family:'IBM Plex Sans'; font-size:13px; font-weight:500;
          cursor:pointer; border:1px solid transparent; }
        .dA-btn.prim { background:#2A6FDB; color:#fff; }
        .dA-btn.ghost { background:#fff; color:#5A5247; border-color:#E2D8C6; }
        .dA-input { margin:0 22px 22px; border:1px solid #E2D8C6; background:#fff; border-radius:14px;
          padding:13px 15px; display:flex; align-items:center; gap:10px; }
        .dA-input span { flex:1; font-size:14px; color:#B3A893; }
        .dA-send { width:30px; height:30px; border-radius:8px; background:#EDE4D3; display:flex; align-items:center;
          justify-content:center; color:#8A7F6D; }
      `}</style>

      <div className="dA-cal">
        <div className="dA-top">
          <div>
            <div className="dA-title">{C.MONTH_LABEL}<span className="yr">2026</span></div>
          </div>
          <div className="dA-nav">
            <button className="dA-chev">‹</button>
            <button className="dA-today">今天</button>
            <button className="dA-chev">›</button>
            <div style={{ width: 14 }} />
            <div className="dA-views">
              <button className="on">月</button><button>周</button><button>日</button><button>议程</button>
            </div>
          </div>
        </div>

        <div className="dA-week">
          {C.WEEKDAYS.map((w, i) => <span key={w} className={i >= 5 ? 'we' : ''}>{w}</span>)}
        </div>

        <div className="dA-grid">
          {cells.map((c, i) => {
            const evs = c.out ? [] : (byDay[c.day] || []);
            const show = evs.slice(0, 3);
            const isToday = !c.out && c.day === C.TODAY;
            return (
              <div key={i} className={'dA-cell' + (c.out ? ' out' : '')}>
                {isToday
                  ? <div className="dA-today-mark">{c.day}</div>
                  : <div className="dA-dn">{c.out && c.day === 1 ? '7月 1' : c.day}</div>}
                {show.map(e => {
                  const m = C.typeMeta[e.type];
                  return (
                    <div key={e.id} className={'dA-chip' + (e.status === 'pending' ? ' pending' : '')}>
                      <span className="dot" style={{ background: m.ink }} />
                      {!e.allDay && <span className="tm">{e.start}</span>}
                      <span className="lb">{e.title}</span>
                    </div>
                  );
                })}
                {evs.length > 3 && <div className="dA-more">+{evs.length - 3} 更多</div>}
              </div>
            );
          })}
        </div>
      </div>

      <div className="dA-ai">
        <div className="dA-ai-h">
          <div className="dA-mark" />
          <div>
            <div className="nm">助手</div>
            <div className="st">已连接 4 个邮箱</div>
          </div>
        </div>
        <div className="dA-thread">
          <div className="dA-msg-ai">{C.chat[0].text}</div>
          <div className="dA-sum">
            <h4>{C.chat[1].title}</h4>
            {C.chat[1].bullets.map((b, i) => (
              <div className="row" key={i}>
                <div className={'num' + (b.urgent ? ' u' : '')}>{b.t.match(/\d+/)[0]}</div>
                <div className="tx"><strong style={{ color: '#3A352D', fontWeight: 600 }}>{b.t.replace(/^\d+\s*/, '')}</strong><br />{b.sub}</div>
              </div>
            ))}
          </div>
          <div className="dA-evcard">
            <div className="et"><span className="pin" />{C.chat[2].event.title}</div>
            <div className="ew">{C.chat[2].event.when}</div>
            <div className="es">{C.chat[2].event.source}</div>
            <div className="note">{C.chat[2].note}</div>
            <div className="acts">
              <button className="dA-btn prim">确认加入</button>
              <button className="dA-btn ghost">忽略</button>
            </div>
          </div>
          <div className="dA-msg-u">{C.chat[3].text}</div>
        </div>
        <div className="dA-input">
          <span>和你的日历对话…</span>
          <div className="dA-send">↑</div>
        </div>
      </div>
    </div>
  );
}
window.DirectionA = DirectionA;
