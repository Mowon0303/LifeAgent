// Shared mock data for the Calendar + AI Agent directions.
// Narrative: the AI agent crawled the user's email inboxes, extracted dated
// items (deadlines, flights, meetings) and pre-filled them into the calendar.
// "pending" items show as dashed previews awaiting confirmation.

window.CAL = (function () {
  const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']; // Mon-first
  const MONTH_LABEL = '六月';
  const YEAR = 2026;
  const TODAY = 10; // Wed, June 10 2026
  // June 1 2026 is a Monday → clean Monday-first grid, 30 days.
  const DAYS_IN_MONTH = 30;
  const LEAD_BLANKS = 0; // first cell is Mon Jun 1

  // type → semantic role
  // deadline (terracotta), meeting (blue), personal (green), ai (pending preview)
  const events = [
    { id: 'e1', day: 9,  start: '09:30', title: '牙医复诊', type: 'personal', status: 'confirmed', source: '日历' },
    { id: 'e2', day: 10, start: '14:00', end: '15:00', title: '产品评审', type: 'meeting', status: 'confirmed', source: 'Google 日历' },
    { id: 'e3', day: 10, start: '16:30', end: '17:00', title: '1:1 · Lin', type: 'meeting', status: 'confirmed', source: 'Outlook' },
    { id: 'e4', day: 11, start: '11:00', title: '设计同步', type: 'meeting', status: 'confirmed', source: 'Google 日历' },
    { id: 'e5', day: 12, allDay: true, title: 'Q2 OKR 提交', type: 'deadline', status: 'confirmed', source: 'work@ 邮件' },
    { id: 'e6', day: 13, start: '19:00', title: '团队聚餐', type: 'ai', status: 'pending', source: 'Slack 邀请' },
    { id: 'e7', day: 15, allDay: true, title: '信用卡还款', type: 'deadline', status: 'confirmed', source: '银行邮件' },
    { id: 'e8', day: 16, start: '10:00', end: '11:00', title: '客户 Demo', type: 'meeting', status: 'confirmed', source: 'Outlook' },
    { id: 'e9', day: 18, allDay: true, title: '签证材料截止', type: 'deadline', status: 'confirmed', source: '领事馆邮件' },
    { id: 'e10', day: 19, start: '08:20', title: '值机 · 飞东京 NH920', type: 'ai', status: 'pending', source: 'ANA 邮件' },
    { id: 'e11', day: 19, allDay: true, title: '酒店入住 · 新宿', type: 'ai', status: 'pending', source: 'Booking 邮件' },
    { id: 'e12', day: 20, allDay: true, title: '妈妈生日', type: 'personal', status: 'confirmed', source: '通讯录' },
    { id: 'e13', day: 22, allDay: true, title: '论文 rebuttal 截止', type: 'deadline', status: 'pending', source: '学术邮件' },
    { id: 'e14', day: 24, start: '15:00', title: '季度复盘', type: 'meeting', status: 'confirmed', source: 'Google 日历' },
  ];

  const typeMeta = {
    deadline: { label: '截止', ink: '#B14228', soft: '#F6E4DC' },
    meeting:  { label: '会议', ink: '#2A6FDB', soft: '#E1ECFB' },
    personal: { label: '个人', ink: '#4F7A4A', soft: '#E4EFE2' },
    ai:       { label: 'AI 建议', ink: '#6A5BD0', soft: '#EAE6FA' },
  };

  // Day-view timeline (for the small agenda strip) — today, Jun 10
  const todayAgenda = events.filter(e => e.day === TODAY);

  // AI chat transcript
  const chat = [
    {
      role: 'ai', kind: 'text',
      text: '早上好。我扫描了你的 4 个邮箱，发现 7 条带日期的重要信息，已预填到日历——虚线的是等你确认的。'
    },
    {
      role: 'ai', kind: 'summary',
      title: '本周一览 · 6 月 8–14 日',
      bullets: [
        { t: '3 个会议', sub: '产品评审、1:1、设计同步' },
        { t: '1 个硬截止', sub: 'Q2 OKR 周五 (6/12) 前提交', urgent: true },
        { t: '1 条待确认', sub: '周六团队聚餐' },
      ],
    },
    {
      role: 'ai', kind: 'card',
      event: { title: '值机 · 飞东京 NH920', when: '6 月 19 日 周五 · 08:20', source: '来自 ANA 行程邮件', type: 'ai' },
      note: '我在你的邮箱看到这趟航班，要加进日历并提前 24 小时提醒值机吗？',
    },
    {
      role: 'user', kind: 'text',
      text: '加进去，顺便把那周五下午留空，我要去机场。',
    },
    {
      role: 'ai', kind: 'text',
      text: '好的，已确认航班并在 6/19 下午标记「外出 · 前往机场」，会自动拒绝该时段的会议邀请。',
    },
  ];

  return { WEEKDAYS, MONTH_LABEL, YEAR, TODAY, DAYS_IN_MONTH, LEAD_BLANKS, events, typeMeta, todayAgenda, chat };
})();
