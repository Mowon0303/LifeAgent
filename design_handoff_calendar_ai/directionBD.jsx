// Direction B′ — B's bento month template, recolored to A's warm paper palette,
// with a Discord-style agent panel (channel header, grouped messages with
// avatars + usernames + timestamps, embeds, rounded composer).
function DirectionBD() {
  const C = window.CAL;
  const byDay = {};
  C.events.forEach(e => { (byDay[e.day] = byDay[e.day] || []).push(e); });
  const cells = [];
  for (let d = 1; d <= C.DAYS_IN_MONTH; d++) cells.push({ day: d, out: false });
  let t = 1; while (cells.length < 35) cells.push({ day: t++, out: true });

  const [view, setView] = React.useState('month');
  const segs = [['month', '月'], ['week', '周'], ['day', '日'], ['agenda', '议程']];
  const titleMap = {
    month: <>六月 <em>2026</em></>,
    week: <>六月 8–14 <em>本周</em></>,
    day: <>6月10日 <em>周三</em></>,
    agenda: <>议程 <em>接下来</em></>,
  };

  const START_H = 7, END_H = 21, HPX = 50;
  const HM = s => { const [h, m] = (s || '0:0').split(':').map(Number); return h + m / 60; };
  const wd = d => C.WEEKDAYS[(d - 1) % 7];
  const hours = []; for (let h = START_H; h <= END_H; h++) hours.push(h);
  const gridH = (END_H - START_H) * HPX;
  const NOW = 11 + 10 / 60;

  function TimeGrid({ days }) {
    const cols = `56px repeat(${days.length},1fr)`;
    return (
      <div className="dD-tg">
        <div className="dD-tg-head" style={{ gridTemplateColumns: cols }}>
          <div />
          {days.map(d => (
            <div key={d} className={'wk-dh' + (d === C.TODAY ? ' is-today' : '')}>
              <div className="wd">周{wd(d)}</div>
              <div className="dnum">{d}</div>
            </div>
          ))}
        </div>
        <div className="dD-allday" style={{ gridTemplateColumns: cols }}>
          <div className="adg-lab">全天</div>
          {days.map(d => (
            <div key={d} className="adg-cell">
              {(byDay[d] || []).filter(e => e.allDay).map(e => {
                const m = C.typeMeta[e.type]; const pend = e.status === 'pending';
                return <div key={e.id} className={'ad-chip' + (pend ? ' pending' : '')}
                  style={pend ? { color: m.ink, borderColor: m.ink } : { background: m.soft, color: m.ink }}>{e.title}</div>;
              })}
            </div>
          ))}
        </div>
        <div className="dD-tg-body" style={{ gridTemplateColumns: cols, height: gridH }}>
          <div className="tg-gutter">
            {hours.map(h => <div key={h} className="tg-hr" style={{ top: (h - START_H) * HPX }}>{String(h).padStart(2, '0')}:00</div>)}
            {hours.map(h => <div key={'g' + h} className="gln" style={{ top: (h - START_H) * HPX }} />)}
          </div>
          {days.map(d => {
            const evs = (byDay[d] || []).filter(e => !e.allDay && e.start);
            return (
              <div key={d} className="tg-col">
                {hours.map(h => <div key={h} className="ln" style={{ top: (h - START_H) * HPX }} />)}
                {evs.map(e => {
                  const m = C.typeMeta[e.type]; const pend = e.status === 'pending';
                  const s = HM(e.start); const en = e.end ? HM(e.end) : s + 0.75;
                  return (
                    <div key={e.id} className={'tg-ev' + (pend ? ' pending' : '')}
                      style={{ top: (s - START_H) * HPX, height: Math.max((en - s) * HPX, 38),
                        ...(pend ? { color: m.ink, borderColor: m.ink } : { background: m.soft, color: m.ink }) }}>
                      <div className="et">{e.title}</div>
                      <div className="ett">{e.start}{e.end ? '–' + e.end : ''}</div>
                    </div>
                  );
                })}
                {d === C.TODAY && <div className="tg-now" style={{ top: (NOW - START_H) * HPX }} />}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  function Agenda() {
    const up = C.events.filter(e => e.day >= C.TODAY)
      .sort((a, b) => a.day - b.day || (HM(a.start || '0:0') - HM(b.start || '0:0')));
    const groups = [];
    up.forEach(e => { let g = groups.find(x => x.day === e.day); if (!g) { g = { day: e.day, items: [] }; groups.push(g); } g.items.push(e); });
    const rel = d => d === C.TODAY ? '今天' : d === C.TODAY + 1 ? '明天' : `${d - C.TODAY} 天后`;
    return (
      <div className="dD-ag">
        {groups.map(g => (
          <div key={g.day} className="ag-day">
            <div className={'ag-dl' + (g.day === C.TODAY ? ' today' : '')}>
              <div className="dow">周{wd(g.day)}</div>
              <div className="dd">6/{g.day}</div>
              <div className="rel">{rel(g.day)}</div>
            </div>
            <div className="ag-rows">
              {g.items.map(e => {
                const m = C.typeMeta[e.type]; const pend = e.status === 'pending';
                return (
                  <div key={e.id} className={'ag-row' + (pend ? ' pending' : '')}>
                    <div className="ag-time">{e.allDay ? '全天' : e.start}</div>
                    <span className="ag-dot" style={{ background: m.ink }} />
                    <div className="ag-ttl">{e.title}</div>
                    <span className="ag-chip" style={{ background: m.soft, color: m.ink }}>{m.label}</span>
                    <div className="ag-src">{e.source}</div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="dD">
      <style>{`
        .dD { width:1440px; height:940px; display:flex; background:#EFE9DC;
          font-family:'IBM Plex Sans',sans-serif; color:#2B2622; }
        /* ---- calendar (B template, warm) ---- */
        .dD-cal { flex:1; display:flex; flex-direction:column; padding:30px 32px; min-width:0; }
        .dD-top { display:flex; align-items:center; justify-content:space-between; margin-bottom:24px; }
        .dD-tl { display:flex; align-items:center; gap:18px; }
        .dD-title { font-family:'Newsreader',serif; font-size:42px; font-weight:500; letter-spacing:-.5px; line-height:1; }
        .dD-title em { font-style:normal; color:#A2937B; font-weight:400; font-size:24px; }
        .dD-nav { display:flex; gap:6px; }
        .dD-nav button { width:38px; height:38px; border-radius:11px; border:1px solid #E0D6C4; background:#FBF8F1; color:#5C5446;
          font-size:17px; cursor:pointer; }
        .dD-nav button:hover { background:#EDE5D6; }
        .dD-seg { display:flex; background:#EBE2D2; border-radius:13px; padding:4px; gap:3px; }
        .dD-seg button { border:0; background:transparent; color:#8A7F6D; padding:9px 18px; border-radius:9px;
          font-size:13px; font-weight:600; cursor:pointer; }
        .dD-seg button.on { background:#2A6FDB; color:#fff; box-shadow:0 2px 6px rgba(42,111,219,.25); }
        .dD-week { display:grid; grid-template-columns:repeat(7,1fr); gap:10px; margin-bottom:10px; }
        .dD-week span { font-family:'IBM Plex Mono',monospace; font-size:11px; font-weight:500; letter-spacing:.1em; color:#A2937B; text-transform:uppercase; }
        .dD-grid { flex:1; display:grid; grid-template-columns:repeat(7,1fr); grid-template-rows:repeat(5,1fr); gap:10px; }
        .dD-cell { background:#FBF8F1; border-radius:14px; padding:9px 9px 7px; display:flex; flex-direction:column; gap:5px;
          min-height:0; overflow:hidden; box-shadow:0 1px 2px rgba(80,60,20,.04); }
        .dD-cell.out { background:rgba(251,248,241,.45); }
        .dD-cell.today { box-shadow:0 0 0 2px #2A6FDB, 0 6px 16px rgba(42,111,219,.16); }
        .dD-dn { font-family:'IBM Plex Mono',monospace; font-size:13px; font-weight:600; color:#6B6253; }
        .dD-cell.out .dD-dn { color:#C2B6A0; }
        .dD-cell.today .dD-dn { color:#2A6FDB; }
        .dD-blk { border-radius:7px; padding:4px 8px; font-size:11.5px; font-weight:600; line-height:1.25;
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .dD-blk .tm { font-weight:700; opacity:.7; margin-right:5px; }
        .dD-blk.pending { background:transparent !important; border:1.5px dashed; }
        .dD-more { font-size:10.5px; font-weight:600; color:#A2937B; padding-left:2px; }
        .dD-cell .dD-blk { cursor:default; }

        /* ---- week / day time grid ---- */
        .dD-tg { flex:1; display:flex; flex-direction:column; min-height:0; }
        .dD-tg-head { display:grid; }
        .wk-dh { text-align:center; padding:2px 0 12px; display:flex; flex-direction:column; align-items:center; gap:4px; }
        .wk-dh .wd { font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:#A2937B; }
        .wk-dh .dnum { font-family:'Newsreader',serif; font-size:24px; font-weight:500; color:#3A352D; line-height:1; }
        .wk-dh.is-today .wd { color:#2A6FDB; }
        .wk-dh.is-today .dnum { color:#fff; background:#2A6FDB; width:36px; height:36px; border-radius:50%;
          display:flex; align-items:center; justify-content:center; font-size:19px; box-shadow:0 4px 10px rgba(42,111,219,.3); }
        .dD-allday { display:grid; border-top:1px solid #E4DBC9; border-bottom:1px solid #E4DBC9; min-height:36px; }
        .adg-lab { font-family:'IBM Plex Mono',monospace; font-size:9.5px; letter-spacing:.06em; text-transform:uppercase;
          color:#B3A893; text-align:right; padding-right:11px; align-self:center; }
        .adg-cell { padding:5px; display:flex; flex-direction:column; gap:3px; border-left:1px solid #ECE3D2; }
        .ad-chip { border-radius:6px; padding:3px 8px; font-size:11.5px; font-weight:600;
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .ad-chip.pending { background:transparent !important; border:1.5px dashed; }
        .dD-tg-body { display:grid; overflow:auto; position:relative; }
        .tg-gutter { position:relative; }
        .tg-hr { position:absolute; right:9px; font-family:'IBM Plex Mono',monospace; font-size:10.5px;
          color:#9A8E7B; transform:translateY(-50%); white-space:nowrap; }
        .tg-col { position:relative; border-left:1px solid #DDD2BE; }
        .tg-col .ln { position:absolute; left:0; right:0; border-top:1px solid #DAD0BC; }
        .tg-gutter .gln { position:absolute; right:0; width:6px; border-top:1px solid #DAD0BC; }
        .tg-ev { position:absolute; left:5px; right:5px; border-radius:8px; padding:5px 9px; overflow:hidden;
          box-shadow:0 1px 3px rgba(80,60,20,.08); cursor:default; }
        .tg-ev .et { font-size:12.5px; font-weight:700; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .tg-ev .ett { font-family:'IBM Plex Mono',monospace; font-size:10px; opacity:.75; margin-top:2px; }
        .tg-ev.pending { background:transparent !important; border:1.5px dashed; }
        .tg-now { position:absolute; left:0; right:0; height:0; border-top:2px solid #B14228; z-index:5; }
        .tg-now:before { content:''; position:absolute; left:-4px; top:-5px; width:9px; height:9px; border-radius:50%; background:#B14228; }

        /* ---- agenda ---- */
        .dD-ag { flex:1; overflow:auto; padding-right:4px; }
        .ag-day { display:grid; grid-template-columns:108px 1fr; gap:22px; padding:15px 0; border-top:1px solid #E4DBC9; }
        .ag-day:first-child { border-top:0; padding-top:6px; }
        .ag-dl { padding-top:2px; }
        .ag-dl .dow { font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:#A2937B; }
        .ag-dl .dd { font-family:'Newsreader',serif; font-size:30px; font-weight:500; color:#3A352D; line-height:1; margin-top:5px; }
        .ag-dl.today .dd { color:#2A6FDB; }
        .ag-dl .rel { font-size:11px; color:#B3A893; margin-top:7px; }
        .ag-rows { display:flex; flex-direction:column; gap:8px; }
        .ag-row { display:flex; align-items:center; gap:13px; background:#FBF8F1; border-radius:11px; padding:11px 15px;
          box-shadow:0 1px 2px rgba(80,60,20,.05); }
        .ag-row.pending { background:transparent; border:1.5px dashed #C9BCEC; box-shadow:none; }
        .ag-time { font-family:'IBM Plex Mono',monospace; font-size:13px; font-weight:600; color:#6B6253; min-width:50px; }
        .ag-dot { width:9px; height:9px; border-radius:50%; flex:none; }
        .ag-ttl { font-size:15px; font-weight:600; color:#2B2622; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .ag-chip { font-size:10.5px; font-weight:700; border-radius:5px; padding:2px 8px; white-space:nowrap; }
        .ag-src { font-size:11.5px; color:#A89A86; min-width:88px; text-align:right; white-space:nowrap; }

        /* ---- Discord-style agent panel ---- */
        .dD-ai { width:438px; flex:none; background:#F1ECE1; border-left:1px solid #E0D6C4; display:flex; flex-direction:column; }
        .dD-chh { height:56px; flex:none; display:flex; align-items:center; gap:9px; padding:0 16px;
          border-bottom:1px solid #E4DBC9; box-shadow:0 1px 0 rgba(80,60,20,.03); }
        .dD-chh .hash { font-size:22px; color:#B3A893; font-weight:500; }
        .dD-chh .cn { font-size:15.5px; font-weight:700; color:#2B2622; }
        .dD-chh .sep { width:1px; height:20px; background:#E0D6C4; margin:0 4px; }
        .dD-chh .topic { font-size:12px; color:#9A8E7B; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .dD-chh .icons { margin-left:auto; display:flex; gap:14px; color:#A89A86; }
        .dD-chh .icons i { width:18px; height:18px; display:block; opacity:.8; }

        .dD-feed { flex:1; overflow:hidden; padding:14px 0 8px; display:flex; flex-direction:column; }
        .dD-div { display:flex; align-items:center; gap:10px; padding:6px 16px 14px; }
        .dD-div .ln { flex:1; height:1px; background:#E4DBC9; }
        .dD-div .pill { font-family:'IBM Plex Mono',monospace; font-size:10.5px; letter-spacing:.06em; color:#A89A86; }

        .dD-msg { display:grid; grid-template-columns:40px 1fr; gap:14px; padding:8px 16px; position:relative; }
        .dD-msg:hover { background:rgba(80,60,20,.035); }
        .dD-msg.right { grid-template-columns:1fr 40px; }
        .dD-msg.right .dD-av { grid-column:2; grid-row:1; }
        .dD-msg.right .dD-mc { grid-column:1; grid-row:1; text-align:right; }
        .dD-msg.right .dD-hl { justify-content:flex-end; }
        .dD-msg.right .dD-body { text-align:right; }
        .dD-av { width:40px; height:40px; border-radius:50%; flex:none; }
        .dD-av.bot { background:radial-gradient(circle at 34% 30%,#5B92F0,#2A6FDB 70%); position:relative; }
        .dD-av.bot:before { content:''; position:absolute; inset:11px; border:2px solid #fff; border-radius:3px; border-top-width:5px; }
        .dD-av.me { background:#4F7A4A; color:#fff; display:flex; align-items:center; justify-content:center;
          font-weight:700; font-size:15px; }
        .dD-hl { display:flex; align-items:baseline; gap:8px; margin-bottom:3px; }
        .dD-un { font-weight:700; font-size:15px; }
        .dD-un.bot { color:#2A6FDB; }
        .dD-un.me { color:#4F7A4A; }
        .dD-app { font-size:10px; font-weight:700; color:#fff; background:#2A6FDB; border-radius:4px; padding:1px 5px; letter-spacing:.02em;
          position:relative; top:-1px; }
        .dD-ts { font-family:'IBM Plex Mono',monospace; font-size:11px; color:#B3A893; }
        .dD-body { font-size:14.5px; line-height:1.5; color:#393429; }
        .dD-cont { grid-column:2; padding:2px 16px 2px 0; }

        /* embeds */
        .dD-embed { border-left:4px solid; background:#FBF8F1; border-radius:6px; padding:13px 16px; margin-top:8px;
          box-shadow:0 1px 2px rgba(80,60,20,.05); max-width:340px; }
        .dD-embed h4 { font-family:'IBM Plex Mono',monospace; font-size:10.5px; letter-spacing:.08em; text-transform:uppercase;
          color:#A89A86; margin:0 0 10px; }
        .dD-sumrow { display:flex; gap:12px; align-items:flex-start; padding:7px 0; border-top:1px solid #F1EADB; }
        .dD-sumrow:first-of-type { border-top:0; }
        .dD-sumrow .n { font-family:'Newsreader',serif; font-size:22px; line-height:1; min-width:26px; color:#2B2622; }
        .dD-sumrow .n.u { color:#B14228; }
        .dD-sumrow .lab { font-size:13.5px; font-weight:600; color:#2B2622; }
        .dD-sumrow .sub { font-size:12px; color:#9A8E7B; margin-top:1px; }
        .dD-embed .etitle { font-size:15px; font-weight:700; color:#2B2622; display:flex; align-items:center; gap:8px; }
        .dD-embed .etitle .pin { width:8px; height:8px; border-radius:50%; background:#6A5BD0; }
        .dD-embed .ewhen { font-family:'IBM Plex Mono',monospace; font-size:12px; color:#6A5BD0; margin:7px 0 1px; }
        .dD-embed .esrc { font-size:11.5px; color:#A89A86; }
        .dD-embed .enote { font-size:13.5px; color:#5A5247; line-height:1.5; margin-top:9px; }
        /* component buttons (under message, like Discord) */
        .dD-btns { display:flex; gap:8px; margin-top:9px; max-width:340px; }
        .dD-cbtn { height:34px; padding:0 16px; border-radius:8px; font-size:13px; font-weight:600; cursor:pointer; border:0;
          display:flex; align-items:center; gap:6px; }
        .dD-cbtn.prim { background:#2A6FDB; color:#fff; }
        .dD-cbtn.sec { background:#E6DECD; color:#5C5446; }

        /* AI flight card — boarding-pass styled, distinct from chat */
        .dD-flight { margin-top:9px; max-width:344px; background:#FBF8F1; border:1px solid #EAE0CE; border-radius:15px;
          overflow:hidden; box-shadow:0 4px 16px rgba(80,60,20,.09); position:relative; }
        .dD-flight .ff-banner { display:flex; align-items:center; gap:8px; padding:9px 14px;
          background:linear-gradient(100deg,#EFEBFA,#F4F1FB); border-bottom:1px solid #E7E1F4; }
        .ff-spark { color:#6A5BD0; font-size:13px; }
        .ff-bt { font-size:12px; font-weight:700; color:#5848C0; letter-spacing:.01em; }
        .ff-tag { margin-left:auto; font-family:'IBM Plex Mono',monospace; font-size:9.5px; letter-spacing:.06em;
          color:#6A5BD0; border:1px dashed #B4A7E8; border-radius:5px; padding:2px 7px; }
        .ff-route { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; padding:16px 16px 13px; }
        .ff-end .ff-code { font-family:'IBM Plex Mono',monospace; font-size:27px; font-weight:600; color:#2B2622; line-height:1; letter-spacing:.01em; }
        .ff-end .ff-city { font-size:11px; color:#9A8E7B; margin-top:5px; }
        .ff-end .ff-time { font-family:'IBM Plex Mono',monospace; font-size:15px; font-weight:600; color:#2B2622; margin-top:7px; }
        .ff-end.r { text-align:right; }
        .ff-mid { display:flex; flex-direction:column; align-items:center; gap:6px; padding:0 14px; min-width:86px; }
        .ff-no { font-family:'IBM Plex Mono',monospace; font-size:10px; font-weight:600; color:#6A5BD0; background:#EFEBFA;
          border-radius:6px; padding:2px 8px; letter-spacing:.04em; }
        .ff-line { display:flex; align-items:center; width:100%; gap:5px; }
        .ff-line .seg { flex:1; height:0; border-top:1.5px dashed #CFBFE6; }
        .ff-line .pl { color:#6A5BD0; display:flex; }
        .ff-dur { font-family:'IBM Plex Mono',monospace; font-size:9.5px; color:#A89A86; letter-spacing:.03em; white-space:nowrap; }
        .ff-perf { position:relative; height:0; border-top:1.5px dashed #D8CFBE; margin:0 16px; }
        .ff-meta { display:flex; align-items:center; gap:16px; padding:12px 16px 14px; }
        .ff-meta .cell .k { font-family:'IBM Plex Mono',monospace; font-size:9px; letter-spacing:.1em; text-transform:uppercase;
          color:#B3A893; display:block; margin-bottom:2px; }
        .ff-meta .cell .v { font-size:12.5px; font-weight:600; color:#3A352D; white-space:nowrap; }
        .ff-meta .ff-src { margin-left:auto; display:flex; align-items:center; gap:5px; font-family:'IBM Plex Mono',monospace;
          font-size:10px; color:#A89A86; white-space:nowrap; }

        /* composer */
        .dD-comp { padding:10px 16px 18px; }
        .dD-compbox { background:#FBF8F1; border:1px solid #E4DBC9; border-radius:13px; padding:11px 12px;
          display:flex; align-items:center; gap:11px; }
        .dD-plus { width:26px; height:26px; border-radius:50%; background:#E6DECD; color:#8A7F6D; flex:none;
          display:flex; align-items:center; justify-content:center; font-size:18px; line-height:1; }
        .dD-compbox .ph { flex:1; font-size:14px; color:#B3A893; }
        .dD-tools { display:flex; gap:12px; color:#B3A893; font-size:16px; }
      `}</style>

      {/* calendar */}
      <div className="dD-cal">
        <div className="dD-top">
          <div className="dD-tl">
            <div className="dD-title">{titleMap[view]}</div>
            <div className="dD-nav"><button>‹</button><button>›</button></div>
          </div>
          <div className="dD-seg">
            {segs.map(([k, l]) => (
              <button key={k} className={view === k ? 'on' : ''} onClick={() => setView(k)}>{l}</button>
            ))}
          </div>
        </div>

        {view === 'month' && (<>
          <div className="dD-week">{C.WEEKDAYS.map(w => <span key={w}>周{w}</span>)}</div>
          <div className="dD-grid">
            {cells.map((c, i) => {
              const evs = c.out ? [] : (byDay[c.day] || []);
              const show = evs.slice(0, 3);
              const isToday = !c.out && c.day === C.TODAY;
              return (
                <div key={i} className={'dD-cell' + (c.out ? ' out' : '') + (isToday ? ' today' : '')}>
                  <div className="dD-dn">{c.out && c.day === 1 ? '7/1' : c.day}</div>
                  {show.map(e => {
                    const m = C.typeMeta[e.type];
                    const pending = e.status === 'pending';
                    return (
                      <div key={e.id} className={'dD-blk' + (pending ? ' pending' : '')}
                        style={pending ? { color: m.ink, borderColor: m.ink } : { background: m.soft, color: m.ink }}>
                        {!e.allDay && <span className="tm">{e.start}</span>}{e.title}
                      </div>
                    );
                  })}
                  {evs.length > 3 && <div className="dD-more">+{evs.length - 3}</div>}
                </div>
              );
            })}
          </div>
        </>)}
        {view === 'week' && <TimeGrid days={[8, 9, 10, 11, 12, 13, 14]} />}
        {view === 'day' && <TimeGrid days={[10]} />}
        {view === 'agenda' && <Agenda />}
      </div>

      {/* Discord-style agent */}
      <div className="dD-ai">
        <div className="dD-chh">
          <span className="hash">#</span>
          <span className="cn">日程助手</span>
          <span className="sep" />
          <span className="topic">AI 已接入 4 个邮箱 · 实时同步日程</span>
          <span className="icons">
            <i dangerouslySetInnerHTML={{ __html: svgIcon('bell') }} />
            <i dangerouslySetInnerHTML={{ __html: svgIcon('search') }} />
            <i dangerouslySetInnerHTML={{ __html: svgIcon('users') }} />
          </span>
        </div>

        <div className="dD-feed">
          <div className="dD-div"><span className="ln" /><span className="pill">今天 · 6月10日</span><span className="ln" /></div>

          {/* bot group */}
          <div className="dD-msg">
            <div className="dD-av bot" />
            <div>
              <div className="dD-hl">
                <span className="dD-un bot">助手</span>
                <span className="dD-app">应用</span>
                <span className="dD-ts">今天 09:02</span>
              </div>
              <div className="dD-body">{C.chat[0].text}</div>
              <div className="dD-embed" style={{ borderLeftColor: '#2A6FDB' }}>
                <h4>{C.chat[1].title}</h4>
                {C.chat[1].bullets.map((b, i) => (
                  <div className="dD-sumrow" key={i}>
                    <div className={'n' + (b.urgent ? ' u' : '')}>{b.t.match(/\d+/)[0]}</div>
                    <div>
                      <div className="lab">{b.t.replace(/^\d+\s*/, '')}</div>
                      <div className="sub">{b.sub}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* bot continuation: event embed + buttons */}
          <div className="dD-msg">
            <div className="dD-av" style={{ visibility: 'hidden' }} />
            <div>
              <div className="dD-body">{C.chat[2].note}</div>
              <div className="dD-flight">
                <div className="ff-banner">
                  <span className="ff-spark">✦</span>
                  <span className="ff-bt">邮件中发现航班</span>
                  <span className="ff-tag">待确认</span>
                </div>
                <div className="ff-route">
                  <div className="ff-end">
                    <div className="ff-code">PVG</div>
                    <div className="ff-city">上海浦东 T2</div>
                    <div className="ff-time">08:20</div>
                  </div>
                  <div className="ff-mid">
                    <div className="ff-no">NH920</div>
                    <div className="ff-line">
                      <span className="seg" />
                      <span className="pl" dangerouslySetInnerHTML={{ __html: svgIcon('plane') }} />
                      <span className="seg" />
                    </div>
                    <div className="ff-dur">3h45m · 直飞</div>
                  </div>
                  <div className="ff-end r">
                    <div className="ff-code">HND</div>
                    <div className="ff-city">东京羽田</div>
                    <div className="ff-time">12:05</div>
                  </div>
                </div>
                <div className="ff-perf" />
                <div className="ff-meta">
                  <div className="cell"><span className="k">日期</span><span className="v">6/19 周五</span></div>
                  <div className="cell"><span className="k">提醒</span><span className="v">提前 24h</span></div>
                  <div className="ff-src"><span dangerouslySetInnerHTML={{ __html: svgIcon('mail') }} />ANA 邮件</div>
                </div>
              </div>
              <div className="dD-btns">
                <button className="dD-cbtn prim">✓ 确认加入日历</button>
                <button className="dD-cbtn sec">忽略</button>
              </div>
            </div>
          </div>

          {/* user group */}
          <div className="dD-msg right">
            <div className="dD-mc">
              <div className="dD-hl">
                <span className="dD-ts">今天 09:04</span>
                <span className="dD-un me">你</span>
              </div>
              <div className="dD-body">{C.chat[3].text}</div>
            </div>
            <div className="dD-av me">我</div>
          </div>

          {/* bot reply */}
          <div className="dD-msg">
            <div className="dD-av bot" />
            <div>
              <div className="dD-hl">
                <span className="dD-un bot">助手</span>
                <span className="dD-app">应用</span>
                <span className="dD-ts">今天 09:04</span>
              </div>
              <div className="dD-body">{C.chat[4].text}</div>
            </div>
          </div>
        </div>

        <div className="dD-comp">
          <div className="dD-compbox">
            <div className="dD-plus">+</div>
            <span className="ph">给 #日程助手 发消息…</span>
            <span className="dD-tools">☺ ⏎</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function svgIcon(name) {
  const s = 'stroke="#A89A86" stroke-width="1.7" fill="none" stroke-linecap="round" stroke-linejoin="round"';
  if (name === 'bell') return `<svg viewBox="0 0 22 22" width="18" height="18"><path ${s} d="M6 9a5 5 0 0 1 10 0c0 5 2 6 2 6H4s2-1 2-6"/><path ${s} d="M9.5 18a1.8 1.8 0 0 0 3 0"/></svg>`;
  if (name === 'search') return `<svg viewBox="0 0 22 22" width="18" height="18"><circle ${s} cx="10" cy="10" r="6"/><path ${s} d="M15 15l3 3"/></svg>`;
  if (name === 'plane') return `<svg viewBox="0 0 18 18" width="15" height="15"><path fill="#6A5BD0" d="M17 9c0 .5-.4.9-.9.9l-4.6.2-2.4 4.6c-.1.2-.3.3-.5.3h-.8c-.3 0-.5-.3-.4-.6l1.2-4.4-3.2.1-1 1.4c-.1.1-.2.2-.4.2h-.6c-.3 0-.5-.3-.4-.6L3 9l-.9-1.5c-.1-.3.1-.6.4-.6h.6c.2 0 .3.1.4.2l1 1.4 3.2.1L6.5 4.6c-.1-.3.1-.6.4-.6h.8c.2 0 .4.1.5.3l2.4 4.6 4.6.2c.5 0 .9.4.9.9z"/></svg>`;
  if (name === 'mail') return `<svg viewBox="0 0 16 16" width="12" height="12"><rect x="1.5" y="3" width="13" height="10" rx="1.5" fill="none" stroke="#B3A893" stroke-width="1.3"/><path d="M2 4.5l6 4 6-4" fill="none" stroke="#B3A893" stroke-width="1.3" stroke-linecap="round"/></svg>`;
  return `<svg viewBox="0 0 22 22" width="18" height="18"><circle ${s} cx="8" cy="8" r="3"/><path ${s} d="M2.5 18a5.5 5.5 0 0 1 11 0"/><path ${s} d="M15 6a3 3 0 0 1 0 6"/><path ${s} d="M15.5 18a5.5 5.5 0 0 0-2-4.3"/></svg>`;
}
window.DirectionBD = DirectionBD;
