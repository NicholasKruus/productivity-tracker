// Made-up data for the demo, generated in the browser so the last day is always
// today. A fixed seed keeps the same story on every visit: dictation and
// Claude's leverage rise, distracting time falls, output picks up.
(function () {
  let seed = 20261113;
  const rand = () => { seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const pick = (list) => list[Math.floor(rand() * list.length)];
  const poisson = (mean) => { let k = 0, p = Math.exp(-mean), s = p; const u = rand(); while (u > s && k < 50) { k += 1; p *= mean / k; s += p; } return k; };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const DAYS = 182;
  const today = new Date();
  const days = [];
  for (let i = DAYS - 1; i >= 0; i--) { const d = new Date(today); d.setDate(d.getDate() - i); days.push(d); }

  const daily = [], commits = [], sentMail = [], slack = [], rescuetime = [], shipped = [], log = [];
  const repos = ['website', 'newsletter-tools', 'data-pipeline', 'research-notes', 'grant-tracker'];
  days.forEach((d, i) => {
    const t = i / (DAYS - 1);                       // 0 at the start, 1 today
    const weekday = d.getDay() !== 0 && d.getDay() !== 6;
    const date = iso(d);
    const prompts = weekday ? poisson(8 + 22 * t) : poisson(3 + 6 * t);
    const minutesPerPrompt = 2.8 + 6.5 * t + (rand() - 0.5) * 1.5;
    const promptWords = Math.round(prompts * (55 - 25 * t) * (0.7 + rand() * 0.6));
    const dictated = Math.round(promptWords * (0.05 + 0.9 * t) * (0.6 + rand() * 0.8)) + (weekday ? poisson(40) : 0);
    const toAi = Math.round(Math.min(dictated, promptWords * (0.05 + 0.9 * t)));
    daily.push({
      date, dictations: Math.round(dictated / 35), dictated_words: dictated, dictated_minutes: Math.round(dictated / 13) / 10,
      dictated_words_to_ai: toAi, claude_prompts: prompts, claude_prompt_words: promptWords + toAi,
      claude_sessions: prompts ? 1 + poisson(prompts / 7) : 0,
      claude_agent_hours: Math.round((prompts * Math.max(1, minutesPerPrompt)) / 60 * 100) / 100,
      claude_peak_parallel: prompts ? 1 + Math.min(4, poisson(0.4 + 2 * t)) : 0,
    });
    const n = weekday ? poisson(1 + 4 * t) : poisson(0.4);
    for (let k = 0; k < n; k++) commits.push({ date, repo: pick(repos), commits: 1 + poisson(1.2) });
    sentMail.push({ date, to_people: weekday ? poisson(5) : poisson(1.2) });
    const sl = weekday ? poisson(3 + 3 * t) : poisson(0.6);
    for (let k = 0; k < sl; k++) slack.push({ date, workspace: 'Slack', key: `${date}-${k}` });
    const distracting = Math.max(0.1, (2.4 - 1.5 * t) * (0.6 + rand() * 0.8) + (weekday ? 0 : 0.8));
    rescuetime.push({ date, distracting_hours: Math.round(distracting * 100) / 100, social_hours: Math.round(distracting * (0.45 - 0.15 * t) * 100) / 100 });
  });

  const titles = {
    video: ['How we cut our weekly reporting to ten minutes', 'A tour of our research tooling', 'Five agents we run every day'],
    post: ['What we learned from a month of AI pair-programming', 'Notes on evaluating new tools', 'The automations that stuck', 'Writing less, shipping more', 'A field guide to weekly reviews', 'Our grant-writing pipeline', 'Three dashboards we actually read'],
    paper: ['Measuring uplift from AI assistants in small teams', 'A survey of agent reliability in practice'],
  };
  const plan = [[18, 'post'], [34, 'post'], [41, 'video'], [57, 'post'], [70, 'paper'], [88, 'post'], [101, 'video'], [116, 'post'], [129, 'post'], [138, 'paper'], [150, 'post'], [158, 'video'], [167, 'post'], [176, 'post']];
  const used = { video: 0, post: 0, paper: 0 };
  plan.forEach(([i, type]) => {
    if (i >= DAYS) return;
    const title = titles[type][used[type]++ % titles[type].length];
    shipped.push({ date: iso(days[i]), type, title, url: `https://example.com/${type}/${used[type]}` });
  });

  const external = ['Open Research Lab', 'Policy Institute', 'Funder Foundation', 'Startup founder', 'University team', 'Advisory network'];
  const internal = ['Data team', 'Research group', 'Operations'];
  days.forEach((d, i) => {
    const t = i / (DAYS - 1);
    if (d.getDay() === 0 || d.getDay() === 6) return;
    if (rand() < 0.12 + 0.18 * t) log.push({ date: iso(d), kind: 'conversation_external', label: pick(external) });
    if (rand() < 0.08 + 0.06 * t) log.push({ date: iso(d), kind: 'conversation_internal', label: pick(internal) });
    if (rand() < 0.025) log.push({ date: iso(d), kind: 'application', label: pick(['Fellowship', 'Research grant', 'Conference talk', 'Residency']) });
  });

  window.DEMO_DATA = { daily, shipped, commits, log, sent_mail: sentMail, slack_sent: slack, rescuetime };
})();
