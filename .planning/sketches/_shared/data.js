// Invented data in the real shapes: audit.py records (ts, tool, op, args, target_id,
// before, after) and mail_recover receipts (plan + done). No real mail, names or ids.
window.DATA = {
  server: {
    version: "0.14.0", build: "2026-09-26 18:02", mode: "daemon",
    bind: "127.0.0.1:47632", pid: 4121, uptime: "3 d 4 h",
    responsible: "ren.lav.macos-apps-mcp",
  },

  accounts: {
    "A1F3-ICLOUD": "iCloud",
    "7C22-GMAIL": "Gmail",
    "E90B-WORK": "Work (IMAP)",
  },

  // One entry per write (sorted newest first below). Batch mail writes carry a receipt.
  audit: [
    {
      ts: "2026-09-28T09:42:07", tool: "create_reminder", op: "create", tier: "additive", app: "Reminders",
      args: { title: "Renew passport", due: "2026-10-03T09:00", list_name: "Personal" },
      target_id: "x-apple-reminder://5B1E7A0C-2F44",
      before: null,
      after: { id: "x-apple-reminder://5B1E7A0C-2F44", summary: "Renew passport — due Fri 3 Oct 09:00", deeplink: "x-apple-reminderkit://REMCDReminder/5B1E7A0C-2F44" },
    },
    {
      ts: "2026-09-28T09:40:12", tool: "trash_mail", op: "trash", tier: "destructive", app: "Mail",
      args: { ids: "6 ids", mailbox: "INBOX", dry_run: false },
      receipt: "20260928-094012-118244-001-trash",
      summary: "6 newsletters moved to Trash",
    },
    {
      ts: "2026-09-28T09:31:55", tool: "update_event", op: "update", tier: "destructive", app: "Calendar",
      args: { id: "ical-8841", start: "2026-09-30T15:00", end: "2026-09-30T15:30", span: "this" },
      target_id: "ical-8841",
      before: { id: "ical-8841", summary: "Dentist — Tue 30 Sep 14:00–14:30", deeplink: "ical://ekevent/8841" },
      after: { id: "ical-8841", summary: "Dentist — Tue 30 Sep 15:00–15:30", deeplink: "ical://ekevent/8841" },
    },
    {
      ts: "2026-09-28T09:12:31", tool: "move_mail", op: "move", tier: "destructive", app: "Mail",
      args: { ids: "12 ids", destination: "Receipts", dry_run: false },
      receipt: "20260928-091231-552190-002-move",
      summary: "12 receipts filed to Receipts",
    },
    {
      ts: "2026-09-28T08:55:02", tool: "complete_reminder", op: "complete", tier: "destructive", app: "Reminders",
      args: { id: "x-apple-reminder://C4A9" },
      target_id: "x-apple-reminder://C4A9",
      before: { id: "x-apple-reminder://C4A9", summary: "Call the bank about the card — open", deeplink: "x-apple-reminderkit://REMCDReminder/C4A9" },
      after: { id: "x-apple-reminder://C4A9", summary: "Call the bank about the card — done", deeplink: "x-apple-reminderkit://REMCDReminder/C4A9" },
    },
    {
      ts: "2026-09-27T17:20:44", tool: "update_note", op: "update", tier: "destructive", app: "Notes",
      args: { id: "x-coredata://NOTE/p412", body: "Passport, charger, rain jacket, …" },
      target_id: "x-coredata://NOTE/p412",
      before: { id: "x-coredata://NOTE/p412", summary: "Trip packing list — 9 lines", deeplink: "applenotes:note/p412" },
      after: { id: "x-coredata://NOTE/p412", summary: "Trip packing list — 14 lines", deeplink: "applenotes:note/p412" },
    },
    {
      ts: "2026-09-27T16:02:10", tool: "delete_event", op: "delete", tier: "destructive", app: "Calendar",
      args: { id: "ical-7710", span: "this" },
      target_id: "ical-7710",
      before: { id: "ical-7710", summary: "1:1 with Sam — Thu 2 Oct 10:00", deeplink: "ical://ekevent/7710" },
      after: null,
    },
    {
      ts: "2026-09-27T14:48:19", tool: "send_mail", op: "send", tier: "outbound", app: "Mail",
      args: { to: "jamie@example.org", subject: "Re: Friday dinner", dry_run: false },
      target_id: "<b7f2.9931@icloud.example>",
      before: null,
      after: { id: "<b7f2.9931@icloud.example>", summary: "Re: Friday dinner → jamie@example.org", deeplink: "message://%3Cb7f2.9931%40icloud.example%3E", folder: "Sent" },
    },
    {
      ts: "2026-09-27T11:15:36", tool: "create_draft", op: "create", tier: "additive", app: "Mail",
      args: { to: "sam@example.com", subject: "Re: Q4 planning notes" },
      target_id: "<d1a0.4410@icloud.example>",
      before: null,
      after: { id: "<d1a0.4410@icloud.example>", summary: "Draft: Re: Q4 planning notes", deeplink: "message://%3Cd1a0.4410%40icloud.example%3E", folder: "Drafts" },
    },
    {
      ts: "2026-09-27T10:03:11", tool: "trash_mail", op: "dedupe", tier: "destructive", app: "Mail",
      args: { ids: "9 ids", mailbox: "Archive", dry_run: false },
      receipt: "20260927-100311-901733-001-dedupe",
      summary: "9 duplicate copies moved to Trash",
      undone_by: "20260927-102540-011802-001-undo",
    },
    {
      ts: "2026-09-27T10:25:40", tool: "mail_undo", op: "undo", tier: "destructive", app: "Mail",
      args: { receipt: "20260927-100311-901733-001-dedupe", dry_run: false },
      receipt: "20260927-102540-011802-001-undo",
      summary: "Undo of the dedupe: 9 messages moved back to Archive",
    },
    // Previews: the caller omitted dry_run, the tool defaulted to True, and the
    // middleware logged it anyway — args carry no dry_run key (preview is derived).
    {
      ts: "2026-09-28T09:38:50", tool: "trash_mail", op: "trash", tier: "destructive", app: "Mail", preview: true,
      args: { ids: "6 ids", mailbox: "INBOX" },
      target_id: null, before: null, after: null,
      summary: "Would move 6 newsletters to Trash",
    },
    {
      ts: "2026-09-27T16:01:31", tool: "delete_event", op: "delete", tier: "destructive", app: "Calendar", preview: true,
      args: { id: "ical-7710" },
      target_id: "ical-7710",
      before: { id: "ical-7710", summary: "1:1 with Sam — Thu 2 Oct 10:00", deeplink: "ical://ekevent/7710" },
      after: null,
    },
    // Older writes, so one target shows a history.
    {
      ts: "2026-09-25T08:30:40", tool: "create_reminder", op: "create", tier: "additive", app: "Reminders",
      args: { title: "Call the bank about the card", list_name: "Personal" },
      target_id: "x-apple-reminder://C4A9",
      before: null,
      after: { id: "x-apple-reminder://C4A9", summary: "Call the bank about the card — open", deeplink: "x-apple-reminderkit://REMCDReminder/C4A9" },
    },
    {
      ts: "2026-09-22T19:05:12", tool: "create_event", op: "create", tier: "additive", app: "Calendar",
      args: { title: "Dentist", start: "2026-09-30T14:00", end: "2026-09-30T14:30", calendar: "Personal" },
      target_id: "ical-8841",
      before: null,
      after: { id: "ical-8841", summary: "Dentist — Tue 30 Sep 14:00–14:30", deeplink: "ical://ekevent/8841" },
    },
  ],

  // mail_recover plan + done, merged. fidelity: full | partial | absent.
  receipts: {
    "20260928-094012-118244-001-trash": {
      op: "trash", ts: "2026-09-28T09:40:12", destination: "Trash",
      backup_dir: "~/.local/state/macos-apps-mcp/backup/mail/20260928-094012-118244-001-trash",
      targets: [
        { id: "<nl.2211@news.example>", summary: "The Weekly Byte — issue 212", folder: "INBOX", account: "7C22-GMAIL", fidelity: "full", status: "ok" },
        { id: "<nl.2212@news.example>", summary: "Deals for you this autumn", folder: "INBOX", account: "7C22-GMAIL", fidelity: "full", status: "ok" },
        { id: "<nl.2213@news.example>", summary: "Your September recap", folder: "INBOX", account: "7C22-GMAIL", fidelity: "partial", status: "ok" },
        { id: "<nl.2214@news.example>", summary: "Webinar: scaling SQLite", folder: "INBOX", account: "7C22-GMAIL", fidelity: "full", status: "ok" },
        { id: "<nl.2215@news.example>", summary: "Last chance: 30% off", folder: "INBOX", account: "7C22-GMAIL", fidelity: "partial", status: "ok" },
        { id: "<nl.2216@news.example>", summary: "Community digest", folder: "INBOX", account: "7C22-GMAIL", fidelity: "full", status: "ok" },
      ],
    },
    "20260928-091231-552190-002-move": {
      op: "move", ts: "2026-09-28T09:12:31", destination: "Receipts",
      backup_dir: "~/.local/state/macos-apps-mcp/backup/mail/20260928-091231-552190-002-move",
      targets: [
        ["Your Hetzner invoice for September", "full"], ["Order #40211 shipped", "full"],
        ["Receipt from the pharmacy", "partial"], ["Train ticket — Ghent → Brussels", "full"],
        ["Your parking receipt", "full"], ["Domain renewal confirmed", "full"],
        ["Monthly phone bill", "partial"], ["Order #40219 delivered", "full"],
        ["Museum tickets", "full"], ["Coffee subscription renewed", "absent"],
        ["Your ride on Saturday", "full"], ["Hosting receipt — October", "full"],
      ].map(([summary, fidelity], i) => ({
        id: `<rcpt.${3100 + i}@shop.example>`, summary, folder: i < 9 ? "INBOX" : "Archive",
        account: i % 3 ? "A1F3-ICLOUD" : "E90B-WORK", fidelity, status: i === 9 ? "missing" : "ok",
      })),
    },
    "20260927-100311-901733-001-dedupe": {
      op: "dedupe", ts: "2026-09-27T10:03:11", destination: "Trash", undone_by: "20260927-102540-011802-001-undo",
      backup_dir: "~/.local/state/macos-apps-mcp/backup/mail/20260927-100311-901733-001-dedupe",
      targets: Array.from({ length: 9 }, (_, i) => ({
        id: `<dup.${510 + i}@list.example>`, summary: ["Meeting notes — week 38", "Re: flat viewing", "Photos from Sunday"][i % 3] + " (copy)",
        folder: "Archive", account: "A1F3-ICLOUD", fidelity: "full", status: "ok",
      })),
    },
  },

  // doctor(): per-adapter permission, grant, and whether it is enabled.
  adapters: [
    { name: "Mail", permission: "Full Disk Access + Automation", grant: "granted", enabled: true, tools: 24, calls: 1840 },
    { name: "Calendar", permission: "EventKit", grant: "granted", enabled: true, tools: 7, calls: 412 },
    { name: "Reminders", permission: "EventKit", grant: "granted", enabled: true, tools: 5, calls: 388 },
    { name: "Notes", permission: "Automation", grant: "granted", enabled: true, tools: 6, calls: 97 },
    { name: "Contacts", permission: "Automation", grant: "granted", enabled: true, tools: 2, calls: 41 },
    { name: "Messages", permission: "Full Disk Access", grant: "granted", enabled: true, tools: 4, calls: 63 },
    { name: "Safari", permission: "Automation", grant: "not asked", enabled: true, tools: 2, calls: 0 },
    { name: "Music", permission: "Automation", grant: "granted", enabled: false, tools: 6, calls: 12 },
    { name: "Photos", permission: "Automation", grant: "denied", enabled: false, tools: 1, calls: 0 },
    { name: "Shortcuts", permission: "Shortcuts CLI", grant: "granted", enabled: true, tools: 2, calls: 8 },
  ],

  outbound: { configured: ["mail"], registered: ["mail"] },
  backups: { mb: 18.4, receipts: 23, oldest: "2026-08-11" },
};

window.DATA.audit.sort((a, b) => b.ts.localeCompare(a.ts));

window.fmt = {
  time: (ts) => ts.slice(11, 16),
  day: (ts) => ({ "2026-09-28": "Today", "2026-09-27": "Yesterday" })[ts.slice(0, 10)] ||
    new Date(ts).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }),
  tierChip: (tier) => `<span class="chip ${tier}">${{ additive: "adds", destructive: "changes", outbound: "sends" }[tier]}</span>`,
  receiptStats(r) {
    const n = r.targets.length;
    const ok = r.targets.filter((t) => t.status === "ok").length;
    const full = r.targets.filter((t) => t.fidelity === "full").length;
    return { n, ok, full, lossy: n - full };
  },
  account: (id) => window.DATA.accounts[id] || id,
  appico: (app) => `<span class="appico ${app}" aria-hidden="true">${app === "Calendar" ? "30" : app[0]}</span>`,
  // "Updated Dentist — Tue 30 Sep 15:00–15:30" — one line a person can read.
  title(e) {
    if (e.summary) return e.summary;
    const verb = e.preview ? `Would ${e.op}` : { create: "Created", update: "Updated", delete: "Deleted", complete: "Completed", send: "Sent" }[e.op] || e.op;
    return `${verb} ${(e.after || e.before).summary}`;
  },
};
