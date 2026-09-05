const API = "http://127.0.0.1:8000/api";
const state = { profile: null, profileInput: null, github: null, resume: null, projects: null, profileSuggestionStates: {} };

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const scoreColor = n => Math.max(0, Math.min(10, Number(n)||0));

async function api(path, options={}) {
  const res = await fetch(API + path, options);
  const data = await res.json().catch(()=>({detail:"Unexpected server response"}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function go(page){
  document.querySelectorAll(".page").forEach(x=>x.classList.remove("active"));
  $(page).classList.add("active");
  document.querySelectorAll(".nav").forEach(x=>x.classList.toggle("active",x.dataset.page===page));
  const navButton=document.querySelector(`[data-page="${page}"]`);
  $("pageTitle").textContent = navButton?.dataset.title || navButton?.querySelector("span")?.textContent?.trim() || navButton?.textContent?.trim() || "Dashboard";
}
document.querySelectorAll(".nav").forEach(x=>x.onclick=()=>go(x.dataset.page));
document.querySelectorAll("[data-go]").forEach(x=>x.onclick=()=>go(x.dataset.go));

async function health(){
  try{
    const d=await api("/health");
    $("apiStatus").innerHTML=`<span class="status-dot"></span>API online · ${d.ai_configured?"AI configured":"rule-based mode"}`;
  }catch(e){$("apiStatus").innerHTML=`<span class="status-dot offline"></span>Backend offline`;}
}
health();

function bars(categories){
  return `<div class="bars">${Object.entries(categories||{}).map(([k,v])=>`<div class="bar-line"><span>${esc(k.replaceAll("_"," "))}</span><div class="bar"><i style="width:${scoreColor(v)*10}%"></i></div><b>${Number(v).toFixed(1)}</b></div>`).join("")}</div>`;
}

function profileSuggestions(items){
  if(!items?.length) return `<p class="muted empty-message">No rewrite suggestions were needed for the submitted profile.</p>`;
  return items.map((item,index)=>{
    const status=state.profileSuggestionStates[index]||"pending";
    return `<article class="suggestion-card" data-suggestion="${index}" data-status="${status}">
      <div class="suggestion-top"><span class="suggestion-section">${esc(item.section)}</span><span class="suggestion-status">${status==="pending"?"Review":status}</span></div>
      <div class="suggestion-version"><div><small>Current version</small><p>${esc(item.current)}</p></div><div class="suggestion-arrow">→</div><div class="improved-version"><small>Improved version</small><p>${esc(item.improved)}</p></div></div>
      <p class="suggestion-reason"><b>Why:</b> ${esc(item.reason)}</p>
      <div class="suggestion-actions"><button class="suggestion-button accept" data-suggestion-action="accepted" data-index="${index}">Accept</button><button class="suggestion-button reject" data-suggestion-action="rejected" data-index="${index}">Reject</button></div>
    </article>`;
  }).join("");
}

function bindSuggestionActions(){
  document.querySelectorAll("[data-suggestion-action]").forEach(button=>button.onclick=()=>{
    const index=button.dataset.index;
    state.profileSuggestionStates[index]=button.dataset.suggestionAction;
    const card=button.closest(".suggestion-card");
    card.dataset.status=button.dataset.suggestionAction;
    card.querySelector(".suggestion-status").textContent=button.dataset.suggestionAction;
    card.querySelectorAll("[data-suggestion-action]").forEach(x=>x.classList.remove("selected"));
    button.classList.add("selected");
  });
}

$("analyzeProfile").onclick=async()=>{
  const btn=$("analyzeProfile");
  const hasInput=["pName","pRole","pHeadline","pAbout","pSkills","pEducation","pExperience","pProjects","pProfileUrl"].some(id=>$(id).value.trim());
  if(!hasInput){
    $("profileResult").innerHTML=`<div class="card warning result-state"><b>Add some profile details first.</b><p>At least a target role, headline, skills, or experience is needed to produce a useful analysis.</p></div>`;
    return;
  }
  btn.disabled=true; btn.textContent="Analyzing…";
  try{
    const profileInput={
      name:$("pName").value, target_role:$("pRole").value, profile_url:$("pProfileUrl").value, headline:$("pHeadline").value,
      about:$("pAbout").value, skills:$("pSkills").value.split(",").map(x=>x.trim()).filter(Boolean),
      education:$("pEducation").value, experience:$("pExperience").value, projects:$("pProjects").value
    };
    const data=await api("/analyze-profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(profileInput)});
     state.profile=data;state.profileInput=profileInput;state.profileSuggestionStates={};$("dashProfile").textContent=data.score+"/10"; syncProjectInputs(); updateDashboard();
    const modeClass=data.mode==="ai"?"ai":"rules";
    $("profileResult").innerHTML=`<div class="card result profile-result">
      <div class="result-head"><div><p class="eyebrow">PROFILE ANALYSIS</p><h2>Profile score</h2><span class="analysis-mode ${modeClass}"><span class="mode-dot"></span>${esc(data.analysis_label||"Rule-based analysis")}</span></div><div class="score">${Number(data.score).toFixed(1)}/10</div></div>
      ${bars(data.categories)}
      <div class="grid two profile-insights"><div><h3>Strengths</h3><div class="list">${(data.strengths||[]).map(x=>`<div class="success">✓ ${esc(x)}</div>`).join("")||"<p class='muted'>Keep building evidence across your profile.</p>"}</div></div><div><h3>Weaknesses</h3><div class="list">${(data.weaknesses||[]).map(x=>`<div class="weakness">! ${esc(x)}</div>`).join("")||"<p class='muted'>No major gaps detected.</p>"}</div></div></div>
      <div class="assessment-card"><div><p class="eyebrow">RECRUITER LENS</p><h3>What a recruiter may think</h3></div><p>${esc(data.recruiter_assessment)}</p><small>${esc(data.disclaimer)}</small></div>
      <div class="recommendation-block"><div class="card-heading"><div><p class="eyebrow">PRIORITY IMPROVEMENTS</p><h3>Exact changes to make</h3></div></div><div class="list">${(data.recommendations||[]).map(x=>`<div>→ ${esc(x)}</div>`).join("")||"<p class='muted'>Your profile is in good shape.</p>"}</div></div>
      <div class="suggestions-block"><div class="card-heading"><div><p class="eyebrow">REWRITE LAB</p><h3>Suggested section improvements</h3></div><span class="heading-note">Accept or reject</span></div><div id="profileSuggestions" class="suggestions-grid">${profileSuggestions(data.suggestions)}</div></div>
      <div class="success-banner">✓ Analysis saved to your dashboard</div>
    </div>`;
    bindSuggestionActions();
  }catch(e){$("profileResult").innerHTML=`<div class="card warning">${esc(e.message)}</div>`}
  btn.disabled=false;btn.textContent="Analyze Profile";
};

function formatDate(value){
  if(!value)return "Unknown";
  const date=new Date(value);
  return Number.isNaN(date.getTime())?"Unknown":new Intl.DateTimeFormat(undefined,{month:"short",day:"numeric",year:"numeric"}).format(date);
}

function formatBytes(value){
  if(!value)return "—";
  if(value>1000000)return (value/1000000).toFixed(1)+" MB";
  if(value>1000)return (value/1000).toFixed(1)+" KB";
  return value+" B";
}

function githubError(message){
  const lower=String(message||"").toLowerCase();
  const rate=lower.includes("rate limit");
  const notFound=lower.includes("not found")||lower.includes("valid github username");
  const network=lower.includes("reached")||lower.includes("network");
  const title=rate?"GitHub rate limit reached":notFound?"GitHub user not found":network?"GitHub is unavailable":"GitHub analysis failed";
  const hint=rate?"Try again later or add GITHUB_TOKEN to the backend environment.":notFound?"Check the username and try again.":network?"Check your connection and retry.":"The public GitHub API returned an error. Retry in a moment.";
  return `<div class="card github-error"><div class="error-mark">!</div><div><h3>${title}</h3><p>${esc(message||hint)}</p><small>${hint}</small></div></div>`;
}

function repoCard(repo,featured=false){
  const languages=Object.keys(repo.languages||{}).slice(0,4);
  return `<article class="github-repo-card ${featured?"featured":""}">
    <div class="repo-card-head"><div><span class="rank-label">#${repo.rank||"—"} ${featured?"· STRONGEST SIGNAL":""}</span><h3>${esc(repo.name)}</h3></div><div class="repo-score">${Number(repo.score||0).toFixed(1)}<small>/10</small></div></div>
    <p class="repo-description">${esc(repo.description||"No description — this is one of the first things a recruiter may notice.")}</p>
    <div class="repo-facts"><span>${esc(repo.language||"Unknown")}</span><span>★ ${repo.stars||0}</span><span>⑂ ${repo.forks||0}</span><span>◉ ${repo.watchers||0}</span><span>Updated ${formatDate(repo.updated_at)}</span></div>
    <div class="repo-card-meta"><span>README ${Number(repo.readme?.score||0).toFixed(1)}/10</span><span>${formatBytes((repo.size_kb||0)*1024)}</span>${languages.map(x=>`<span>${esc(x)}</span>`).join("")}</div>
    <div class="repo-strengths"><div><small>Strengths</small>${(repo.strengths||[]).map(x=>`<p class="success">✓ ${esc(x)}</p>`).join("")}</div><div><small>Improve</small>${(repo.weaknesses||[]).map(x=>`<p class="weakness">! ${esc(x)}</p>`).join("")}</div></div>
    <div class="repo-card-footer"><span>${repo.archived?"Archived":"Original repository"} · ${esc(repo.default_branch||"main")}</span><a class="github-link" href="${esc(repo.html_url||"#")}" target="_blank" rel="noopener">View on GitHub <svg class="icon"><use href="#icon-arrow"/></svg></a></div>
  </article>`;
}

function renderGithubResults(data){
  const profile=data.profile||{};
  const best=data.best_repository;
  const evidence=(data.technology_evidence||[]).map(item=>`<span class="evidence-chip ${item.present?"present":"missing"}"><b>${item.present?"✓":"×"}</b>${esc(item.name)}</span>`).join("");
  const lens=data.recruiter_view||{};
  const lensRows=[["Strongest signal",lens.strongest_signal],["Biggest concern",lens.biggest_concern],["Missing evidence",lens.missing_evidence],["Portfolio credibility",lens.portfolio_credibility],["Technology alignment",lens.technology_alignment]];
  const pins=data.pinning||{};
  return `<div class="github-result result">
    <div class="github-score-header"><div><p class="eyebrow">GITHUB SIGNAL</p><h2>${esc(profile.name||profile.login||data.username)}</h2><p class="muted">${esc(profile.bio||"No public bio yet.")}</p><a class="profile-link" href="${esc(profile.profile_url||"#")}" target="_blank" rel="noopener">${esc(profile.profile_url||"Profile URL unavailable")} <svg class="icon"><use href="#icon-arrow"/></svg></a></div><div class="github-score-ring"><span>${Number(data.score||0).toFixed(1)}</span><small>/10</small><em>GITHUB SCORE</em></div></div>
    <div class="github-profile-strip"><div><small>Followers</small><b>${profile.followers||0}</b></div><div><small>Following</small><b>${profile.following||0}</b></div><div><small>Original repos</small><b>${data.repository_count||0}</b></div><div><small>Profile completeness</small><b>${Number(profile.completeness||0).toFixed(1)}/10</b></div><div><small>Recent repos</small><b>${profile.account_activity?.recent_original_repositories||0}</b></div></div>
    ${bars(data.categories)}
    <div class="github-section-heading"><div><p class="eyebrow">PORTFOLIO LEADER</p><h3>Your strongest portfolio repository</h3></div><span class="heading-note">${esc(pins.first||"None found")}</span></div>
    ${best?repoCard(best,true):`<div class="github-empty"><span>⌘</span><p>No original public repositories found.</p><small>Create or publish an original project to generate portfolio evidence.</small></div>`}
    <div class="github-section-heading"><div><p class="eyebrow">RANKED EVIDENCE</p><h3>Repository ranking</h3></div><span class="heading-note">${data.repository_count||0} original</span></div>
    <div class="github-repo-grid">${(data.repositories||[]).map(repo=>repoCard(repo)).join("")||`<div class="github-empty"><span>⌘</span><p>Your repository list is empty.</p><small>Forks are intentionally excluded from strongest-work analysis.</small></div>`}</div>
    <div class="github-two-column">
      <div class="github-subcard"><div class="github-section-heading compact"><div><p class="eyebrow">RECRUITER LENS</p><h3>What a technical recruiter may notice</h3></div></div><div class="recruiter-lens">${lensRows.map(([label,value])=>`<div><small>${label}</small><p>${esc(value||"Not enough public evidence yet.")}</p></div>`).join("")}</div><small class="github-disclaimer">${esc(data.recruiter_disclaimer)}</small></div>
      <div class="github-subcard"><div class="github-section-heading compact"><div><p class="eyebrow">PINNING PLAN</p><h3>What to highlight</h3></div></div><div class="pinning-list"><p><b>Pin first</b><span>${esc(pins.first||"No recommendation yet")}</span></p><p><b>Pin next</b><span>${esc((pins.recommended||[]).slice(1).join(", ")||"Build more original work")}</span></p><p><b>Do not lead with</b><span>${esc((pins.do_not_highlight||[]).join(", ")||"Nothing flagged")}</span></p></div></div>
    </div>
    <div class="github-section-heading"><div><p class="eyebrow">ROLE GAP ANALYSIS</p><h3>What is missing from your GitHub portfolio?</h3></div><span class="heading-note">${esc(data.target_role||"Add a target role")}</span></div>
    <div class="evidence-row">${evidence||`<span class="muted">Add a target role above to compare your repository evidence.</span>`}</div>
    <p class="gap-summary">${data.portfolio_gaps?.length?`The clearest gaps are ${esc(data.portfolio_gaps.slice(0,4).join(", "))}. Make these visible in code, tests, or README evidence.`:"Your public repositories cover the main signals detected for this target role. Add outcomes and depth to make the evidence stronger."}</p>
    <div class="github-section-heading"><div><p class="eyebrow">PERSONALIZED BUILDS</p><h3>Recommended projects</h3></div><span class="heading-note">Based on your gaps</span></div>
    <div class="github-project-grid">${(data.recommended_projects||[]).map(project=>`<article class="github-project-card"><span class="rank-label">${esc(project.difficulty)}</span><h3>${esc(project.title)}</h3><p><b>Problem:</b> ${esc(project.problem)}</p><p><b>Why build it:</b> ${esc(project.why)}</p><div class="project-detail"><small>Technologies</small><div class="repo-meta">${(project.technologies||[]).map(x=>`<span>${esc(x)}</span>`).join("")}</div></div><div class="project-detail"><small>Features</small><p>${esc((project.important_features||[]).join(" · "))}</p></div><div class="project-detail"><small>Recruiters would see</small><p>${esc(project.recruiter_takeaway)}</p></div><details><summary>Suggested README structure</summary><p>${esc((project.readme_structure||[]).join(" → "))}</p></details></article>`).join("")}</div>
    <p class="scoring-note">ⓘ ${esc(data.scoring_note||"Scores balance documentation, depth, relevance, activity, and presentation.")}</p>
  </div>`;
}

$("analyzeGithub").onclick=async()=>{
  const u=$("githubUser").value.trim();
  if(!u){$("githubResult").innerHTML=githubError("Enter a GitHub username to begin.");return;}
  const role=$("githubRole").value.trim()||$("pRole").value.trim();
  const btn=$("analyzeGithub");btn.disabled=true;btn.textContent="Analyzing GitHub…";
  try{
    const query=role?`?target_role=${encodeURIComponent(role)}`:"";
     const d=await api("/github/"+encodeURIComponent(u)+query);state.github=d;syncProjectInputs();$("dashGithub").textContent=d.score+"/10";updateDashboard();
    $("githubResult").innerHTML=renderGithubResults(d);
  }catch(e){$("githubResult").innerHTML=githubError(e.message)}
  btn.disabled=false;btn.textContent="Analyze GitHub";
};

function resumeMode(data){
  const isAI=data?.mode==="ai"||data?.mode==="gemini"||data?.analysis_mode==="gemini";
  return `<span class="analysis-mode ${isAI?"ai":"rules"}"><span class="mode-dot"></span>Analysis Mode: ${isAI?"Gemini":"Rule-based"}</span>`;
}

function resumeList(items, empty="No evidence detected yet."){
  return items?.length
    ? `<div class="list">${items.map(item=>`<div>→ ${esc(typeof item==="string"?item:item.item)}</div>`).join("")}</div>`
    : `<p class="muted">${esc(empty)}</p>`;
}

function resumeSuggestionCards(items){
  if(!items?.length) return `<p class="muted empty-message">No rewrite suggestions were generated for the current resume.</p>`;
  return items.map((item,index)=>{
    const status=state.resume?.suggestionStates?.[index]||"pending";
    const suggested=item.suggested||item.improved||"";
    return `<article class="resume-suggestion-card" data-resume-suggestion="${index}" data-status="${status}">
      <div class="suggestion-top"><span class="suggestion-section">${esc(item.section||"Resume")}</span><span class="suggestion-status">${status==="pending"?"Review":status}</span></div>
      <div class="suggestion-version"><div><small>Original / current</small><p>${esc(item.current)}</p></div><div class="suggestion-arrow">→</div><div class="improved-version"><small>${status==="accepted"?"Accepted version":"Suggested"}</small><p>${esc(suggested)}</p></div></div>
      <p class="suggestion-reason"><b>Why:</b> ${esc(item.why||item.reason)}</p>
      <div class="resume-edit-panel" hidden><label>Edit suggested version<textarea data-edit-suggestion="${index}" rows="4">${esc(suggested)}</textarea></label><button class="suggestion-button" data-resume-action="save-edit" data-index="${index}">Save Change</button></div>
      <div class="suggestion-actions"><button class="suggestion-button accept" data-resume-action="accept" data-index="${index}">Accept</button><button class="suggestion-button" data-resume-action="edit" data-index="${index}">Edit</button><button class="suggestion-button reject" data-resume-action="reject" data-index="${index}">Reject</button></div>
    </article>`;
  }).join("");
}

function renderResumeResults(data){
  const categories=data.category_scores||data.categories||{};
  const ats=data.ats_analysis||{}, alignment=data.role_alignment||{}, keywords=data.keywords||{};
  const recruiter=data.recruiter_review||{};
  const sections=Object.entries(data.sections||{}).map(([key,value])=>`<span class="section-chip ${value?"present":"missing"}"><b>${value?"✓":"○"}</b>${esc(key.replaceAll("_"," "))}</span>`).join("");
  const evidence=(alignment.evidence||[]).map(item=>`<span class="evidence-chip ${item.status==="present"?"present":"missing"}"><b>${item.status==="present"?"✓":"×"}</b>${esc(item.keyword)}</span>`).join("");
  const weaknesses=(data.weaknesses||[]).map(item=>`<div class="priority-item ${String(item.priority||"Medium").toLowerCase()}"><span>${esc(item.priority||"Medium")}</span><p>${esc(item.item||item)}</p></div>`).join("");
  const projects=(data.project_analysis||[]).map(item=>`<details class="analysis-detail"><summary>${esc(item.name)}</summary><div class="detail-grid"><p><small>Technologies</small>${esc((item.technologies||[]).join(" · ")||"Not clearly detected")}</p><p><small>Quality score</small>${Number(item.quality_score||0).toFixed(1)}/10</p><p><small>Purpose</small>${esc(item.purpose)}</p><p><small>Impact</small>${esc(item.measurable_impact)}</p><p><small>Strengthen it</small>${esc(item.how_to_strengthen)}</p></div></details>`).join("");
  const experience=(data.experience_analysis||[]).map(item=>`<details class="analysis-detail"><summary>${esc(item.entry)}</summary><div class="detail-grid"><p><small>Dates</small>${esc(item.dates)}</p><p><small>Technologies</small>${esc((item.technologies||[]).join(" · ")||"Not clearly detected")}</p><p><small>Achievements</small>${esc(item.achievements)}</p><p><small>Relevance</small>${esc(item.relevance)}</p></div></details>`).join("");
  return `<div class="card result resume-result">
    <div class="result-head"><div><p class="eyebrow">RESUME ANALYSIS</p><h2>Resume score</h2><p class="muted">${Number(data.word_count||0).toLocaleString()} words detected · ${esc(data.target_role||"No target role selected")}</p>${resumeMode(data)}</div><div class="score">${Number(data.score||0).toFixed(1)}/10</div></div>
    <div class="resume-disclaimer">Scores are based on extracted resume content. This is an ATS-style compatibility analysis, not a reproduction of any specific ATS vendor.</div>
    <h3 class="resume-subheading">Category scores</h3>${bars(categories)}
    <div class="resume-section">
      <div class="resume-section-heading"><div><p class="eyebrow">STRUCTURE</p><h3>Detected sections</h3></div><span class="heading-note">${esc((data.missing_sections||[]).length)} missing</span></div>
      <div class="section-chip-row">${sections}</div>
    </div>
    <div class="resume-two-column resume-section">
      <div><div class="resume-section-heading"><div><p class="eyebrow">ATS-STYLE REVIEW</p><h3>Compatibility findings</h3></div></div>${resumeList(ats.issues,"No major text-level compatibility issues detected.")}<small class="muted">${esc(ats.note||"Readable text only; formatting can vary by file.")}</small></div>
      <div><div class="resume-section-heading"><div><p class="eyebrow">ROLE MATCH</p><h3>${esc(alignment.target_role||data.target_role||"Target role")}</h3></div><span class="recommendation-score">${Number(alignment.score||categories.role_alignment||0).toFixed(1)}<small>/10</small></span></div><div class="evidence-row">${evidence||`<span class="muted">Add a target role to see role evidence.</span>`}</div><p class="muted resume-note">${esc(alignment.guidance||"Only add missing terms when they reflect real experience.")}</p></div>
    </div>
    <div class="resume-section"><div class="resume-section-heading"><div><p class="eyebrow">KEYWORD ANALYSIS</p><h3>What to keep, check, and avoid</h3></div></div><div class="keyword-grid"><div><small>Strong keywords</small><p>${esc((keywords.strong_keywords||[]).join(" · ")||"None clearly detected")}</p></div><div><small>Missing keywords</small><p>${esc((keywords.missing_keywords||[]).join(" · ")||"None flagged")}</p></div><div><small>Overused keywords</small><p>${esc((keywords.overused_keywords||[]).join(" · ")||"None flagged")}</p></div><div><small>Suggested keywords</small><p>${esc((keywords.suggested_keywords||[]).join(" · ")||"None flagged")}</p></div></div><p class="resume-note">${esc(keywords.warning||"Only add suggested keywords when you genuinely have experience with them.")}</p></div>
    <div class="resume-two-column resume-section"><div><div class="resume-section-heading"><div><p class="eyebrow">SIGNALS</p><h3>Strengths</h3></div></div>${resumeList(data.strengths,"No specific strengths detected yet.")}</div><div><div class="resume-section-heading"><div><p class="eyebrow">GAPS</p><h3>Prioritized weaknesses</h3></div></div><div class="priority-list">${weaknesses||`<p class="muted">No major weaknesses detected.</p>`}</div></div></div>
    <div class="resume-section recruiter-review"><div class="resume-section-heading"><div><p class="eyebrow">RECRUITER PERSPECTIVE</p><h3>What a recruiter may notice</h3></div></div><div class="review-grid">${[["First impression",recruiter.first_impression],["Strongest signal",recruiter.strongest_signal],["Biggest concern",recruiter.biggest_concern],["Missing evidence",recruiter.missing_evidence],["Most important change",recruiter.most_important_change],["Would I continue reading?",recruiter.would_continue_reading]].map(([label,value])=>`<div><small>${label}</small><p>${esc(value||"Not enough evidence detected.")}</p></div>`).join("")}</div><small class="github-disclaimer">${esc(recruiter.disclaimer||"AI-generated recruiter-style simulation. This is not an actual recruiter's opinion or hiring decision.")}</small></div>
    <div class="resume-two-column resume-section"><div><div class="resume-section-heading"><div><p class="eyebrow">ACTION PLAN</p><h3>Top 5 things to fix</h3></div></div>${resumeList(data.action_plan||data.recommendations)}</div><div><div class="resume-section-heading"><div><p class="eyebrow">DETAIL REVIEW</p><h3>Projects and experience</h3></div></div><div class="analysis-details">${projects||`<p class="muted">No Projects section detected.</p>`}${experience||`<p class="muted">No Experience section detected.</p>`}</div></div></div>
    <div class="resume-workspace resume-section"><div class="resume-section-heading"><div><p class="eyebrow">ORIGINAL + WORKING RESUME</p><h3>Keep the source safe while you improve</h3></div><span class="heading-note">Original preserved</span></div><div class="resume-compare"><div><small>Original resume</small><pre>${esc(state.resume?.originalText||data.original_text||data.text)}</pre></div><div><small>Working resume</small><pre id="workingResumePreview">${esc(state.resume?.workingText||data.text)}</pre></div></div></div>
    <div class="resume-improvement-lab resume-section"><div class="resume-section-heading"><div><p class="eyebrow">AI RESUME IMPROVEMENT</p><h3>Generate suggestions, then choose what changes</h3></div><span class="heading-note">Never auto-overwrites</span></div><label class="improvement-instruction">Tell AI how you want to improve your resume<textarea id="resumeInstruction" rows="3" placeholder="e.g. Make it suitable for Java backend jobs. Do not exaggerate anything."></textarea></label><div class="improvement-controls"><button class="suggestion-button active-mode" data-resume-mode="general">General</button><button class="suggestion-button" data-resume-mode="ats-optimize">ATS Optimize</button><button class="suggestion-button" data-resume-mode="recruiter">Recruiter Optimize</button><button class="suggestion-button" data-resume-mode="target-role">Target Role</button><button class="suggestion-button" data-resume-mode="one-page">Concise / One Page</button><button class="suggestion-button" data-resume-mode="stronger-bullets">Stronger Bullets</button><button class="suggestion-button" data-resume-mode="project-focus">Project Focus</button><button class="suggestion-button" data-resume-mode="skills-focus">Skills Focus</button><button class="primary" id="generateResumeSuggestions">Generate Suggestions</button></div><div id="resumeSuggestions" class="suggestions-grid">${resumeSuggestionCards(state.resume?.suggestions||data.improvements||[])}</div></div>
  </div>`;
}

function refreshResumeResult(){
  if(!state.resume)return;
  $("resumeResult").innerHTML=renderResumeResults(state.resume);
  bindResumeActions();
}

async function reanalyzeWorkingResume(){
  const targetRole=$("resumeRole").value.trim()||state.resume.target_role||"";
  const d=await api("/reanalyze-resume",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({resume_text:state.resume.workingText,target_role:targetRole})});
  const original=state.resume.originalText, working=state.resume.workingText, suggestions=state.resume.suggestions, suggestionStates=state.resume.suggestionStates;
  state.resume={...d,originalText:original,workingText:working,suggestions,suggestionStates,target_role:targetRole};
  $("dashResume").textContent=d.score+"/10";syncProjectInputs();updateDashboard();refreshResumeResult();
}

async function applyResumeSuggestion(index, replacement){
  const item=state.resume.suggestions[index];if(!item)return;
  const current=String(item.current||""), suggested=String(replacement||item.suggested||item.improved||"").trim();
  if(!suggested)return;
  const validation=await api("/validate-resume-edit",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({
      resume_text:state.resume.workingText,
      current_text:current,
      suggested_text:suggested
    })
  });
  if(!validation.valid) throw new Error((validation.errors||[]).join(" "));
  if(current && !current.startsWith("[") && state.resume.workingText.includes(current)){
    state.resume.workingText=state.resume.workingText.replace(current,suggested);
  }else{
    if(current && !current.startsWith("[")) throw new Error("The current suggestion text is no longer in the working resume.");
    const heading=String(item.section||"Resume").toUpperCase();
    state.resume.workingText=`${state.resume.workingText.trim()}\n\n${heading}\n${suggested}`.trim();
  }
  item.suggested=suggested;
  item.improved=suggested;
}

function bindResumeActions(){
  document.querySelectorAll("[data-resume-mode]").forEach(button=>button.onclick=()=>{
    document.querySelectorAll("[data-resume-mode]").forEach(x=>x.classList.remove("active-mode"));
    button.classList.add("active-mode");state.resume.improvementMode=button.dataset.resumeMode;
  });
  $("generateResumeSuggestions")?.addEventListener("click",async()=>{
    const btn=$("generateResumeSuggestions");btn.disabled=true;btn.textContent="Generating…";
    try{
      const targetRole=$("resumeRole").value.trim()||state.resume.target_role||"";
      const d=await api("/improve-resume",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({resume_text:state.resume.workingText,target_role:targetRole,user_feedback:$("resumeInstruction").value,mode:state.resume.improvementMode||"general"})});
      state.resume.suggestions=d.suggestions||[];state.resume.suggestionStates={};state.resume.suggestionMode=d.mode;refreshResumeResult();
    }catch(e){alert(e.message)}
    btn.disabled=false;
  });
  document.querySelectorAll("[data-resume-action]").forEach(button=>button.onclick=async()=>{
    const index=Number(button.dataset.index), action=button.dataset.resumeAction, card=button.closest("[data-resume-suggestion]");
    if(!state.resume.suggestionStates)state.resume.suggestionStates={};
    if(action==="edit"){card.querySelector(".resume-edit-panel").hidden=false;return;}
    if(action==="save-edit"){
      const edited=card.querySelector("[data-edit-suggestion]")?.value.trim();
      if(!edited)return;
      try{
        await applyResumeSuggestion(index,edited);
        state.resume.suggestionStates[index]="accepted";
        await reanalyzeWorkingResume();
      }catch(e){refreshResumeResult();alert(`Change was not applied: ${e.message}`)}
      return;
    }
    if(action==="accept"){
      try{
        await applyResumeSuggestion(index);
        state.resume.suggestionStates[index]="accepted";
        await reanalyzeWorkingResume();
      }catch(e){refreshResumeResult();alert(`Change was not applied: ${e.message}`)}
      return;
    }
    if(action==="reject"){
      state.resume.suggestionStates[index]="rejected";refreshResumeResult();
    }
  });
}

$("analyzeResume").onclick=async()=>{
  const file=$("resumeFile").files[0];if(!file){$("resumeResult").innerHTML=`<div class="card warning result-state"><b>Choose a resume first.</b><p>Upload a PDF, DOCX, or TXT file up to 8 MB.</p></div>`;return;}
  const fd=new FormData();fd.append("file",file);fd.append("target_role",$("resumeRole").value.trim());
  const btn=$("analyzeResume");btn.disabled=true;btn.textContent="Analyzing…";
  try{
    const d=await api("/analyze-resume",{method:"POST",body:fd});
    state.resume={...d,originalText:d.original_text||d.text,workingText:d.text||d.original_text,suggestions:d.improvements||[],suggestionStates:{},target_role:d.target_role||$("resumeRole").value.trim(),improvementMode:"general"};
    $("resumeRole").value=state.resume.target_role;syncProjectInputs();$("dashResume").textContent=d.score+"/10";updateDashboard();refreshResumeResult();
  }catch(e){$("resumeResult").innerHTML=`<div class="card warning result-state"><b>Resume analysis failed.</b><p>${esc(e.message)}</p></div>`}
  btn.disabled=false;btn.textContent="Analyze Resume";
};

function profileFormInput(){
  return {
    name:$("pName").value.trim(), target_role:$("pRole").value.trim(), profile_url:$("pProfileUrl").value.trim(),
    headline:$("pHeadline").value.trim(), about:$("pAbout").value.trim(),
    skills:$("pSkills").value.split(",").map(x=>x.trim()).filter(Boolean),
    education:$("pEducation").value.trim(), experience:$("pExperience").value.trim(), projects:$("pProjects").value.trim()
  };
}

function syncProjectInputs(){
  const role=state.profileInput?.target_role||state.github?.target_role||state.resume?.target_role||"";
  const skills=state.profileInput?.skills?.length?state.profileInput.skills:(state.github?.languages||[]);
  if(!$("projRole").value.trim()&&role) $("projRole").value=role;
  if(!$("resumeRole").value.trim()&&role) $("resumeRole").value=role;
  if(!$("projSkills").value.trim()&&skills.length) $("projSkills").value=skills.slice(0,8).join(", ");
  const sources=[];
  if(state.profile||state.profileInput) sources.push("Profile");
  if(state.github) sources.push("GitHub");
  if(state.resume) sources.push("Resume");
  $("projectContextHint").textContent=sources.length
    ? `Using analyzed context: ${sources.join(" + ")}. Recommendations will target the evidence your profile is missing.`
    : "Run Profile, GitHub, or Resume analysis first for a sharper recommendation. You can still generate from the role and skills above.";
}

function scoreBreakdown(breakdown){
  return Object.entries(breakdown||{}).map(([key,value])=>`<div class="score-factor"><span>${esc(key.replaceAll("_"," "))}</span><b>${Number(value||0).toFixed(1)}</b></div>`).join("");
}

function projectCard(project, featured=false){
  const index=(state.projects?.projects||[]).findIndex(item=>item.title===project.title);
  return `<article class="career-project-card ${featured?"featured":""}">
    <div class="career-project-top"><span class="rank-label">#${project.rank||"—"} ${featured?"· BEST NEXT MOVE":""}</span><div class="recommendation-score">${Number(project.score||0).toFixed(1)}<small>/10</small></div></div>
    <h3>${esc(project.title)}</h3>
    <p class="project-one-line">${esc(project.description||project.one_line_description)}</p>
    <div class="project-badges"><span>${esc(project.difficulty)}</span><span>${esc(project.estimated_development_complexity||project.complexity)}</span></div>
    <div class="project-detail"><small>Why this user should build it</small><p>${esc(project.why)}</p></div>
    <div class="project-detail"><small>Portfolio gap it fixes</small><p class="gap-highlight">${esc(project.portfolio_gap)}</p></div>
    <div class="project-detail"><small>Technology stack</small><div class="repo-meta">${(project.technologies||project.stack||[]).map(item=>`<span>${esc(item)}</span>`).join("")}</div></div>
    <div class="project-detail"><small>Recruiter value</small><p>${esc(project.recruiter_value||project.recruiter_takeaway)}</p></div>
    <div class="project-actions"><button class="secondary" data-project-action="blueprint" data-project-index="${index}">View Blueprint</button><button class="primary" data-project-action="blueprint" data-project-index="${index}">Build This Project <svg class="icon"><use href="#icon-arrow"/></svg></button></div>
  </article>`;
}

function listBlock(title, items){
  return `<div class="blueprint-block"><small>${esc(title)}</small><ul>${(items||[]).map(item=>`<li>${esc(item)}</li>`).join("")||"<li>Define this during implementation.</li>"}</ul></div>`;
}

function renderProjectBlueprint(project){
  const blueprint=project.blueprint||{};
  const technology=blueprint.technology_stack||{};
  return `<article class="project-blueprint-card">
    <div class="blueprint-head"><div><p class="eyebrow">PROJECT BLUEPRINT · #${project.rank||"—"}</p><h2>${esc(project.title)}</h2><p class="muted">${esc(project.description)}</p></div><div class="recommendation-score large">${Number(project.score||0).toFixed(1)}<small>/10</small></div></div>
    <div class="blueprint-grid">
      <div><small>Problem statement</small><p>${esc(blueprint.problem_statement)}</p></div>
      <div><small>Target users</small><p>${esc(blueprint.target_users)}</p></div>
      <div><small>Architecture</small><p class="architecture-copy">${esc(blueprint.architecture)}</p></div>
      <div><small>Recruiter value</small><p>${esc(project.recruiter_value||project.recruiter_takeaway)}</p></div>
    </div>
    <div class="blueprint-columns">
      ${listBlock("Core features", blueprint.core_features||project.core_features)}
      ${listBlock("Advanced features", blueprint.advanced_features||project.advanced_features)}
      ${listBlock("Development roadmap", blueprint.roadmap)}
    </div>
    <div class="blueprint-section"><h3>Technology stack</h3><div class="stack-grid">${Object.entries(technology).map(([key,value])=>`<div><small>${esc(key.replaceAll("_"," "))}</small><p>${esc(value)}</p></div>`).join("")}</div></div>
    <div class="blueprint-columns">
      ${listBlock("Database design", blueprint.database_design)}
      ${listBlock("API design", blueprint.api_design)}
      ${listBlock("GitHub-ready folder structure", blueprint.folder_structure)}
    </div>
    <div class="blueprint-columns">
      <div class="blueprint-block"><small>Testing strategy</small><p>${esc(blueprint.testing_strategy)}</p></div>
      <div class="blueprint-block"><small>Deployment</small><p>${esc(blueprint.deployment)}</p></div>
      ${listBlock("README structure", blueprint.readme_structure)}
    </div>
    <div class="impact-grid"><div><small>Before</small><p>${esc((project.before?.missing||[]).join(" · "))}</p></div><div><small>After</small><p>${esc((project.after?.demonstrates||[]).join(" · "))}</p></div></div>
  </article>`;
}

function bindProjectActions(){
  document.querySelectorAll("[data-project-action]").forEach(button=>button.onclick=()=>{
    const project=state.projects?.projects?.[Number(button.dataset.projectIndex)];
    if(!project) return;
    const target=$("projectBlueprint");
    target.hidden=false;
    target.innerHTML=renderProjectBlueprint(project);
    target.scrollIntoView({behavior:"smooth",block:"start"});
  });
}

function renderProjectResults(data){
  const gap=data.career_gap?.biggest||{};
  const recruiter=data.recruiter_view||{};
  const sources=Object.entries(data.available_sources||{}).filter(([,value])=>value).map(([key])=>key);
  const best=data.best_project||data.projects?.[0];
  return `<div class="career-project-result result">
    <div class="career-intelligence-head"><div><p class="eyebrow">CAREER PROJECT INTELLIGENCE</p><h2>Your next strongest signal</h2><p class="muted">Recommendations are ranked against ${esc(data.target_role)} and the evidence already present in your workspace.</p></div><span class="analysis-mode ${data.mode==="ai"?"ai":"rules"}"><span class="mode-dot"></span>${esc(data.analysis_label||"Rule-based recommendation")}</span></div>
    <div class="project-source-strip"><span>Target role <b>${esc(data.target_role)}</b></span><span>Career stage <b>${esc(data.career_stage||"early-career")}</b></span><span>Sources <b>${esc(sources.join(" + ")||"Role + skills")}</b></span></div>
    <div class="gap-intelligence"><div><p class="eyebrow">YOUR BIGGEST PORTFOLIO GAP</p><h3>${esc(gap.name||"Production depth")}</h3><p>${esc(gap.why_it_matters)}</p></div><div><small>Current evidence</small><p>${esc((gap.current_evidence||[]).join(" · "))}</p></div><div><small>Evidence to add</small><p>${esc(gap.evidence_to_add)}</p></div></div>
    <div class="career-section-heading"><div><p class="eyebrow">BEST PROJECT TO BUILD NEXT</p><h3>Why this project?</h3></div><span class="heading-note">Ranked #1</span></div>
    ${best?projectCard(best,true):`<div class="github-empty"><p>No recommendation could be generated.</p><small>Add a target role or skills and try again.</small></div>`}
    ${best?`<div class="best-project-reasons"><div><small>What this fixes</small><p>${esc(best.portfolio_gap)}</p></div><div><small>What you will demonstrate</small><p>${esc((best.skills_demonstrated||[]).slice(0,6).join(" · "))}</p></div><div><small>What a recruiter may notice</small><p>${esc(best.recruiter_value||best.recruiter_takeaway)}</p></div></div>`:""}
    <div class="project-recruiter-view"><div class="career-section-heading compact"><div><p class="eyebrow">RECRUITER VIEW</p><h3>What a technical recruiter may notice</h3></div><span class="heading-note">AI estimate</span></div><div class="recruiter-project-grid">${[["Strongest portfolio signal",recruiter.strongest_signal],["Biggest weakness",recruiter.biggest_weakness],["Missing evidence",recruiter.missing_evidence],["Technical depth",recruiter.technical_depth],["Role alignment",recruiter.role_alignment],["Project credibility",recruiter.project_credibility]].map(([label,value])=>`<div><small>${label}</small><p>${esc(value||"Not enough evidence yet.")}</p></div>`).join("")}</div></div>
    <div class="career-section-heading"><div><p class="eyebrow">OTHER RECOMMENDED PROJECTS</p><h3>Build the evidence in layers</h3></div><span class="heading-note">${data.projects?.length||0} ranked projects</span></div>
    <div class="career-project-grid">${(data.projects||[]).slice(1).map(project=>projectCard(project)).join("")}</div>
    <div class="score-method"><div><p class="eyebrow">TRANSPARENT RECOMMENDATION SCORE</p><h3>Why these rankings?</h3><p>${esc(data.scoring_note)}</p></div><div class="score-factors">${scoreBreakdown(best?.score_breakdown||{})}</div></div>
    <small class="github-disclaimer">${esc(data.recruiter_disclaimer)}</small>
    <div id="projectBlueprint" class="project-blueprint" hidden></div>
  </div>`;
}

$("generateProjects").onclick=async()=>{
  const role=$("projRole").value.trim()||state.profileInput?.target_role||state.github?.target_role||"";
  const profileInput=state.profileInput||profileFormInput();
  if(!role){
    $("projectsResult").innerHTML=`<div class="card warning result-state"><b>Add a target role first.</b><p>The recommendation engine needs a target role to decide which evidence matters most.</p></div>`;
    return;
  }
  const btn=$("generateProjects");btn.disabled=true;btn.textContent="Analyzing your career signal…";
  try{
    const d=await api("/generate-projects",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
      target_role:role,
      skills:$("projSkills").value.split(",").map(x=>x.trim()).filter(Boolean),
      profile:{input:profileInput,analysis:state.profile||{}},
      github:state.github||{},
      resume:state.resume||{},
      github_score:state.github?.score||0,resume_score:state.resume?.score||0,profile_score:state.profile?.score||0
    })});
    state.projects=d;$("dashProjects").textContent="Ready";$("projectsResult").innerHTML=renderProjectResults(d);bindProjectActions();
  }catch(e){$("projectsResult").innerHTML=`<div class="card warning result-state"><b>Project intelligence is unavailable.</b><p>${esc(e.message)}</p></div>`}
  btn.disabled=false;btn.innerHTML='Find My Best Next Project <svg class="icon"><use href="#icon-arrow"/></svg>';
};

syncProjectInputs();
$("pRole").addEventListener("input",()=>{if(!$("resumeRole").value.trim())$("resumeRole").value=$("pRole").value});
$("resumeRole").addEventListener("change",async()=>{
  if(!state.resume)return;
  const next=$("resumeRole").value.trim();
  if(next===state.resume.target_role)return;
  state.resume.target_role=next;
  try{await reanalyzeWorkingResume()}catch(e){alert(`Target role updated, but re-analysis failed: ${e.message}`)}
});

$("builderText").oninput=e=>$("resumePreview").textContent=e.target.value||"Your resume preview will appear here.";
document.querySelectorAll(".template").forEach(t=>t.onclick=()=>{document.querySelectorAll(".template").forEach(x=>x.classList.remove("selected"));t.classList.add("selected")});

async function download(kind){
  const text=$("builderText").value.trim();if(!text)return alert("Add your finalized resume text first.");
  const res=await fetch(API+"/export-resume/"+kind,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({resume_text:text})});
  if(!res.ok)return alert("Export failed.");
  const blob=await res.blob(), url=URL.createObjectURL(blob), a=document.createElement("a");a.href=url;a.download=kind==="pdf"?"CareerForge_Resume.pdf":"CareerForge_Resume.docx";a.click();URL.revokeObjectURL(url);
}
$("downloadPdf").onclick=()=>download("pdf");$("downloadDocx").onclick=()=>download("docx");

function updateDashboard(){
  const vals=[state.profile?.score,state.github?.score,state.resume?.score].filter(v=>typeof v==="number");
  if(vals.length){const s=(vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(1);$("overallScore").textContent=s}
  const metricMap={profile:state.profile?.score,github:state.github?.score,resume:state.resume?.score};
  Object.entries(metricMap).forEach(([key,value])=>{
    const el=$("dash"+key.charAt(0).toUpperCase()+key.slice(1));
    if(!el||typeof value!=="number")return;
    const metric=el.closest(".metric");
    el.textContent=value+"/10";
    metric.querySelector(".metric-foot span").textContent=value>=8?"Strong signal":value>=6?"Room to improve":"Needs attention";
    metric.querySelector(".metric-foot i").style.width=(Math.max(0,Math.min(10,value))*10)+"%";
  });
  const actions=[];
  if(state.profile?.recommendations) actions.push(...state.profile.recommendations.slice(0,2));
  if(state.github?.issues) actions.push(...state.github.issues.slice(0,2));
  if(state.resume?.recommendations) actions.push(...state.resume.recommendations.slice(0,2));
  $("priorityActions").innerHTML=actions.slice(0,5).map((x,i)=>`<div class="action-item"><span>${String(i+1).padStart(2,"0")}</span><p>${esc(x)}</p><svg class="icon"><use href="#icon-arrow"/></svg></div>`).join("")||"<p class='muted empty-message'>Run an analysis to generate personalized actions.</p>";

  const scored=[["Profile",state.profile?.score,"profile"],["GitHub",state.github?.score,"github"],["Resume",state.resume?.score,"resume"]].filter(x=>typeof x[1]==="number");
  if(scored.length){
    const weakest=scored.sort((a,b)=>a[1]-b[1])[0];
    const copy={Profile:"Your profile needs clearer role alignment.",GitHub:"Your GitHub needs stronger project evidence.",Resume:"Your resume has the biggest opportunity for a sharper story."};
    $("weakestArea").innerHTML=`<div class="focus-score"><span>${weakest[1].toFixed(1)}</span><small>/10</small></div><div><p class="focus-label">${esc(weakest[0])} is your current focus</p><p class="muted">${copy[weakest[0]]}</p><button class="text-button" data-go="${weakest[2]}">Work on ${esc(weakest[0])} <svg class="icon"><use href="#icon-arrow"/></svg></button></div>`;
    $("weakestArea").querySelector("[data-go]").onclick=()=>go(weakest[2]);
  }
  const progress=state.resume?75:0;
  $("resumeProgressBar").style.width=progress+"%";
  $("resumeProgressLabel").textContent=progress+"%";
  $("progressAnalyze").classList.toggle("done",!!state.resume);
}
