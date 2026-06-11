// Direction C — "Soft Mono / Ink"  (week timeline)
// Near-monochrome warm paper, hairlines, generous whitespace.
// Blue appears only on Today + the AI accent. Demonstrates the week view.
function DirectionC() {
  const C = window.CAL;
  const weekDays = [8, 9, 10, 11, 12, 13, 14];
  const labels = ['一', '二', '三', '四', '五', '六', '日'];
  const startH = 8, endH = 21, hourPx = 52;
  const toMin = s => { const [h, m] = s.split(':').map(Number); return h * 60 + m; };
  const byDay = {};
  C.events.forEach(e => { if (weekDays.includes(e.day)) (byDay[e.day] = byDay[e.day] || []).push(e); });

  return (
    <div className="dC">
      <style>{`
        .dC { width:1440px; height:940px; display:flex; background:#F4EFE6;
          font-family:'IBM Plex Sans',sans-serif; color:#2B2622; }
        .dC-cal { flex:1; display:flex; flex-direction:column; min-width:0; padding:0; }
        .dC-top { display:flex; align-items:center; justify-content:space-between; padding:30px 40px 24px; }
        .dC-tl { display:flex; align-items:baseline; gap:16px; }
        .dC-title { font-family:'Newsreader',serif; font-size:36px; font-weight:430; letter-spacing:-.3px; }
        .dC-range { font-family:'IBM Plex Mono',monospace; font-size:12px; letter-spacing:.06em; color:#A2937B; }
        .dC-r { display:flex; align-items:center; gap:22px; }
        .dC-nav { display:flex; align-items:center; gap:14px; font-family:'IBM Plex Mono',monospace; color:#8A7F6D; font-size:15px; }
        .dC-nav button { background:none; border:0; color:#8A7F6D; font-size:15px; cursor:pointer; }
        .dC-views { display:flex; gap:20px; font-family:'IBM Plex Mono',monospace; font-size:12px; letter-spacing:.08em; }
        .dC-views span { color:#B3A893; cursor:pointer; padding-bottom:4px; }
        .dC-views span.on { color:#2B2622; border-bottom:1.5px solid #2B2622; }
        .dC-hd { display:grid; grid-template-columns:56px repeat(7,1fr); border-top:1px solid #E4DBC9; }
        .dC-hd .gut { border-right:1px solid #E4DBC9; }
        .dC-dh { padding:12px 0 11px 14px; border-right:1px solid #E4DBC9; }
        .dC-dh .wd { font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:.14em; color:#A2937B; text-transform:uppercase; }
        .dC-dh .dt { font-family:'Newsreader',serif; font-size:25px; margin-top:3px; color:#3A352D; }
        .dC-dh.today .dt { color:#2A6FDB; }
        .dC-dh.today .wd { color:#2A6FDB; }
        .dC-dh.today { background:linear-gradient(#EAF1FC,rgba(234,241,252,0)); }
        /* all-day banner */
        .dC-ad { display:grid; grid-template-columns:56px repeat(7,1fr); border-top:1px solid #E4DBC9; min-height:34px; }
        .dC-ad .gut { border-right:1px solid #E4DBC9; font-family:'IBM Plex Mono',monospace; font-size:9px;
          color:#B3A893; display:flex; align-items:center; justify-content:center; letter-spacing:.04em; }
        .dC-ad .col { border-right:1px solid #E4DBC9; padding:5px 7px; }
        .dC-adchip { font-size:11px; padding:3px 8px; border-radius:4px; border-left:2.5px solid; background:#fff;
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .dC-adchip.pending { border:1px dashed #B4A7E8; border-left:2.5px dashed #6A5BD0; background:repeating-linear-gradient(135deg,#fff,#fff 5px,#F5F2FC 5px,#F5F2FC 10px); }
        /* timeline */
        .dC-tl-wrap { flex:1; display:grid; grid-template-columns:56px repeat(7,1fr); border-top:1px solid #E4DBC9;
          position:relative; overflow:hidden; }
        .dC-gutter { border-right:1px solid #E4DBC9; position:relative; }
        .dC-hr { position:absolute; right:8px; font-family:'IBM Plex Mono',monospace; font-size:10px; color:#B3A893;
          transform:translateY(-50%); }
        .dC-col { border-right:1px solid #E4DBC9; position:relative; }
        .dC-col.today { background:rgba(42,111,219,.035); }
        .dC-line { position:absolute; left:0; right:0; border-top:1px solid #EFE7D7; }
        .dC-now { position:absolute; left:0; right:0; height:0; border-top:1.5px solid #2A6FDB; z-index:3; }
        .dC-now:before { content:''; position:absolute; left:-4px; top:-3.5px; width:7px; height:7px; border-radius:50%; background:#2A6FDB; }
        .dC-ev { position:absolute; left:6px; right:6px; border-radius:7px; background:#FBF8F1; border:1px solid #EAE0CE;
          border-left:3px solid; padding:6px 8px; overflow:hidden; box-shadow:0 1px 2px rgba(80,60,20,.05); }
        .dC-ev .et { font-size:12px; font-weight:600; line-height:1.2; color:#2B2622; }
        .dC-ev .em { font-family:'IBM Plex Mono',monospace; font-size:10px; color:#9A8E7B; margin-top:2px; }
        .dC-ev.pending { background:repeating-linear-gradient(135deg,#fff,#fff 6px,#F5F2FC 6px,#F5F2FC 12px);
          border:1px dashed #B4A7E8; border-left:3px dashed #6A5BD0; }

        /* AI panel — ultra minimal */
        .dC-ai { width:400px; flex:none; background:#FBF8F1; border-left:1px solid #E4DBC9; display:flex; flex-direction:column; }
        .dC-ai-h { padding:30px 30px 22px; }
        .dC-ai-h .nm { font-family:'Newsreader',serif; font-size:24px; }
        .dC-ai-h .st { font-family:'IBM Plex Mono',monospace; font-size:10.5px; letter-spacing:.08em; color:#7FA86B; margin-top:6px; }
        .dC-thread { flex:1; overflow:hidden; padding:6px 30px; display:flex; flex-direction:column; gap:22px; }
        .dC-ma { font-size:15px; line-height:1.6; color:#3A352D; }
        .dC-mu { font-size:14.5px; line-height:1.55; color:#2A6FDB; padding-left:14px; border-left:2px solid #2A6FDB; }
        .dC-sum { }
        .dC-sum h4 { font-family:'IBM Plex Mono',monospace; font-size:10.5px; letter-spacing:.1em; text-transform:uppercase;
          color:#A89A86; margin:0 0 4px; }
        .dC-sum .row { display:flex; justify-content:space-between; align-items:baseline; padding:11px 0; border-bottom:1px solid #EFE7D7; }
        .dC-sum .row:last-child { border-bottom:0; }
        .dC-sum .lab { font-size:14px; color:#3A352D; }
        .dC-sum .lab small { display:block; font-size:12px; color:#A89A86; margin-top:2px; }
        .dC-sum .v { font-family:'Newsreader',serif; font-size:22px; color:#2B2622; }
        .dC-sum .v.u { color:#B14228; }
        .dC-card { padding-top:4px; }
        .dC-card .ct { font-size:15px; font-weight:600; }
        .dC-card .cw { font-family:'IBM Plex Mono',monospace; font-size:11.5px; color:#6A5BD0; margin:5px 0 12px; }
        .dC-card .note { font-size:13.5px; color:#5A5247; line-height:1.55; margin-bottom:14px; }
        .dC-acts { display:flex; gap:18px; align-items:center; }
        .dC-acts .yes { font-size:13.5px; font-weight:600; color:#2A6FDB; cursor:pointer; display:flex; gap:6px; align-items:center; }
        .dC-acts .yes:before { content:''; width:16px; height:16px; border-radius:50%; border:1.5px solid #2A6FDB; }
        .dC-acts .no { font-size:13.5px; color:#A89A86; cursor:pointer; }
        .dC-input { margin:22px 26px 26px; border-top:1px solid #EAE0CE; padding-top:18px; display:flex; align-items:center; gap:10px; }
        .dC-input span { flex:1; font-size:14.5px; color:#B3A893; }
        .dC-input .k { font-family:'IBM Plex Mono',monospace; font-size:10px; color:#B3A893; border:1px solid #E2D8C6; border-radius:4px; padding:2px 5px; }
      `}</style>

      <div className="dC-cal">
        <div className="dC-top">
          <div className="dC-tl">
            <div className="dC-title">这一周</div>
            <div className="dC-range">6月 8 — 14 · 2026</div>
          </div>
          <div className="dC-r">
            <div className="dC-nav"><button>‹</button><span>今天</span><button>›</button></div>
            <div className="dC-views"><span>月</span><span className="on">周</span><span>日</span><span>议程</span></div>
          </div>
        </div>

        <div className="dC-hd">
          <div className="gut" />
          {weekDays.map((d, i) => (
            <div key={d} className={'dC-dh' + (d === C.TODAY ? ' today' : '')}>
              <div className="wd">周{labels[i]}</div>
              <div className="dt">{d}</div>
            </div>
          ))}
        </div>

        <div className="dC-ad">
          <div className="gut">全天</div>
          {weekDays.map(d => (
            <div key={d} className="col">
              {(byDay[d] || []).filter(e => e.allDay).map(e => {
                const m = C.typeMeta[e.type];
                const pend = e.status === 'pending';
                return <div key={e.id} className={'dC-adchip' + (pend ? ' pending' : '')}
                  style={pend ? {} : { borderLeftColor: m.ink, color: m.ink }}>{e.title}</div>;
              })}
            </div>
          ))}
        </div>

        <div className="dC-tl-wrap">
          <div className="dC-gutter">
            {Array.from({ length: endH - startH }, (_, i) => startH + i).map(h => (
              <div key={h} className="dC-hr" style={{ top: (h - startH) * hourPx }}>{String(h).padStart(2, '0')}:00</div>
            ))}
          </div>
          {weekDays.map(d => {
            const timed = (byDay[d] || []).filter(e => !e.allDay);
            const isToday = d === C.TODAY;
            return (
              <div key={d} className={'dC-col' + (isToday ? ' today' : '')}>
                {Array.from({ length: endH - startH }, (_, i) => i).map(i => (
                  <div key={i} className="dC-line" style={{ top: i * hourPx }} />
                ))}
                {isToday && <div className="dC-now" style={{ top: ((11 * 60 + 5) / 60 - startH) * hourPx }} />}
                {timed.map(e => {
                  const top = (toMin(e.start) / 60 - startH) * hourPx;
                  const dur = e.end ? (toMin(e.end) - toMin(e.start)) : 50;
                  const h = Math.max(38, dur / 60 * hourPx - 4);
                  const m = C.typeMeta[e.type];
                  const pend = e.status === 'pending';
                  return (
                    <div key={e.id} className={'dC-ev' + (pend ? ' pending' : '')}
                      style={{ top, height: h, ...(pend ? {} : { borderLeftColor: m.ink }) }}>
                      <div className="et">{e.title}</div>
                      <div className="em">{e.start}{e.end ? '–' + e.end : ''}</div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>

      <div className="dC-ai">
        <div className="dC-ai-h">
          <div className="nm">助手</div>
          <div className="st">已读取 4 个邮箱 · 实时同步</div>
        </div>
        <div className="dC-thread">
          <div className="dC-ma">{C.chat[0].text}</div>
          <div className="dC-sum">
            <h4>本周一览</h4>
            {C.chat[1].bullets.map((b, i) => (
              <div className="row" key={i}>
                <div className="lab">{b.t.replace(/^\d+\s*/, '')}<small>{b.sub}</small></div>
                <div className={'v' + (b.urgent ? ' u' : '')}>{b.t.match(/\d+/)[0]}</div>
              </div>
            ))}
          </div>
          <div className="dC-card">
            <div className="ct">{C.chat[2].event.title}</div>
            <div className="cw">{C.chat[2].event.when} · {C.chat[2].event.source}</div>
            <div className="note">{C.chat[2].note}</div>
            <div className="dC-acts"><span className="yes">确认加入</span><span className="no">忽略</span></div>
          </div>
          <div className="dC-mu">{C.chat[3].text}</div>
        </div>
        <div className="dC-input">
          <span>问我任何关于日程的事…</span>
          <span className="k">⏎</span>
        </div>
      </div>
    </div>
  );
}
window.DirectionC = DirectionC;
