/* All run content is untrusted data: DOM text only, no HTML interpolation. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  let bundle;
  let selectedState = "";
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  };
  const show = value => value === null || value === undefined || value === "" ? "—" : String(value);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const time = value => finite(value) ? `${(value / 1000).toFixed(1)} s` : "—";
  const cost = value => finite(value) ? `$${value.toFixed(4)}` : "—";
  const provenance = value => value === "real_execution" ? "REAL EXECUTION" : value === "synthetic" || value === "synthetic_fixture" ? "SYNTHETIC · TEST ONLY" : "UNVERIFIED PROVENANCE";
  const badge = value => element("span", provenance(value), `badge ${value === "real_execution" ? "real" : "synthetic"}`);
  const condition = value => ["agents_memory", "agent_memory", "memory", "with_memory"].includes(value) ? "memory" : ["agents_no_memory", "agent_no_memory", "no_memory", "without_memory"].includes(value) ? "control" : "baseline";
  const conditionName = value => ({memory: "Agents + memory", control: "Agents · no memory", baseline: "Frozen policy baseline"}[condition(value)]);
  const mediaPath = value => {
    if (typeof value !== "string" || !value || value.includes("\\")) return null;
    // Exported references are local, content-addressed assets. Uploaded bundle
    // JSON cannot cause external requests or load active content.
    if (!/^assets\/[a-zA-Z0-9_.-]+$/.test(value)) return null;
    return value;
  };
  function validate(data) {
    if (!data || data.schema_version !== "1" || !Array.isArray(data.attempts) || !data.graph || !Array.isArray(data.graph.nodes) || !Array.isArray(data.graph.edges)) throw new Error("Expected an ARMA schema_version 1 replay bundle.");
    return data;
  }
  function setBundle(data) {
    bundle = validate(data);
    $("error").hidden = true;
    const attempts = bundle.attempts;
    const baselineOnly = attempts.length > 0 && attempts.every(attempt => condition(attempt.condition) === "baseline");
    document.querySelector(".intro h1").textContent = baselineOnly ? "Inspect a frozen-policy baseline." : "See what the robot remembered.";
    document.querySelector(".intro .eyebrow").textContent = baselineOnly ? "POLICY BASELINE · NO MEMORY COMPARISON" : "THREE AGENTS. ONE FROZEN ROBOT POLICY.";
    document.querySelector(".intro .lede").textContent = baselineOnly ? "Recorded observations, actual actions, and the environment's result. This run does not measure memory benefit." : "Compare recorded attempts. Follow the evidence behind each instruction.";
    const kinds = new Set(attempts.map(attempt => provenance(attempt.provenance)));
    $("provenance").textContent = !attempts.length ? "NO EXECUTION DATA" : kinds.size === 1 ? [...kinds][0] : "MIXED PROVENANCE · INSPECT EACH RUN";
    $("provenance").className = `provenance ${attempts.length ? kinds.size === 1 && kinds.has("REAL EXECUTION") ? "real" : "synthetic" : ""}`;
    $("selection-note").textContent = baselineOnly ? "Baseline only: official task instruction, no agent API calls. An agent memory/no-memory comparison has not been included in this bundle." : bundle.selection_note || "Showing the earliest listed attempt per condition and state. Every outcome is listed below.";
    $("generated-at").textContent = bundle.generated_at ? `Exported ${bundle.generated_at}` : "";
    $("empty").hidden = attempts.length > 0;
    $("workspace").hidden = !attempts.length;
    const states = [...new Set(attempts.map(attempt => String(attempt.init_state_id ?? "unspecified")))];
    $("state-select").replaceChildren(...states.map(state => {
      const option = element("option", `State ${state}`);
      option.value = state;
      return option;
    }));
    $("state-select").disabled = !states.length;
    selectedState = states[0] || "";
    $("run-count").textContent = `${attempts.length} attempts · no outcome filtering`;
    renderResults();
    renderComparison();
    renderGraph();
  }
  function metric(label, value) {
    const node = element("div", undefined, "metric");
    node.append(element("span", label, "field-label"), element("strong", value));
    return node;
  }
  function makeCard(kind, attempt) {
    const card = element("article", undefined, `card ${kind}`);
    const heading = element("div", undefined, "card-heading");
    heading.append(element("h2", kind === "baseline" ? "Frozen policy baseline" : kind === "memory" ? "02 / With memory" : "01 / Without memory"));
    if (attempt) heading.append(badge(attempt.provenance));
    card.append(heading);
    const media = element("div", undefined, "media");
    const videoPath = attempt && mediaPath(attempt.video_ref);
    if (videoPath && /\.(mp4|webm)$/i.test(videoPath)) {
      const video = element("video");
      video.controls = true; video.preload = "metadata"; video.src = videoPath;
      video.setAttribute("aria-label", kind === "baseline" ? "Frozen policy baseline recorded attempt" : `${kind === "memory" ? "With" : "Without"} memory recorded attempt`);
      video.addEventListener("error", () => {
        const message = element("p", "Video unavailable. Keep the exported assets folder beside this page.");
        media.replaceChildren(message);
      });
      media.append(video);
    } else media.append(element("p", attempt ? "No video artifact recorded for this attempt." : "No matching attempt recorded for this state."));
    card.append(media);
    if (!attempt) return card;
    const body = element("div", undefined, "card-body");
    body.append(element("span", "Original goal", "field-label"), element("p", show(attempt.task_goal), "goal"));
    const decisions = Array.isArray(attempt.decisions) ? attempt.decisions : [];
    const picker = element("select"); picker.setAttribute("aria-label", `${kind} decision interval`);
    for (const [index, decision] of decisions.entries()) {
      const option = element("option", kind === "baseline" ? `Interval ${show(decision.decision_index ?? index)} · actions ${show(decision.execution?.start_step_index)}–${show(decision.execution?.end_step_index)}` : `Decision ${show(decision.decision_index ?? index)} · ${show(decision.planner?.stage ?? decision.stage)}`);
      option.value = String(index); picker.append(option);
    }
    if (!decisions.length) {picker.append(element("option", "No decision records available")); picker.disabled = true;}
    const instruction = element("p", "—", "instruction");
    const stage = element("p", "", "muted");
    const updateDecision = () => {
      const decision = decisions[Number(picker.value)];
      instruction.textContent = show(decision?.execution?.actual_instruction ?? decision?.retrieval?.instruction ?? decision?.retrieval?.executed_instruction ?? attempt.executed_instruction);
      stage.textContent = decision ? kind === "baseline" ? `Environment task result: ${show(decision.evaluation?.task_outcome ?? "running")} · Actions: ${show(decision.execution?.start_step_index)} → ${show(decision.execution?.end_step_index)} · No LLM stage selection` : `Stage: ${show(decision.planner?.stage ?? decision.stage)} · Subtask: ${show(decision.evaluation?.subtask_outcome)} · Task: ${show(decision.evaluation?.task_outcome)} · Actions: ${show(decision.execution?.start_step_index)} → ${show(decision.execution?.end_step_index)}` : "No interval-level evaluation available.";
      if (decision) showDetails("Decision record", decision);
    };
    picker.addEventListener("change", updateDecision);
    body.append(element("span", kind === "baseline" ? "Execution interval" : "Decision interval", "field-label"), picker, element("span", "Actual policy instruction", "field-label"), instruction, stage);
    const metrics = element("div", undefined, "metrics");
    metrics.append(metric("Result", show(attempt.outcome ?? attempt.status)), metric("Actions / decisions", `${show(attempt.step_index)} / ${show(attempt.decision_index)}`), metric("Wall time", time(attempt.elapsed_ms)), metric("Agent API cost", cost(attempt.cost_usd)));
    body.append(metrics); card.append(body); updateDecision(); return card;
  }
  function renderComparison() {
    const attempts = bundle.attempts.filter(attempt => String(attempt.init_state_id ?? "unspecified") === selectedState);
    const baseline = attempts.find(attempt => condition(attempt.condition) === "baseline");
    const baselineOnly = !!baseline && attempts.every(attempt => condition(attempt.condition) === "baseline");
    $("comparison").classList.toggle("baseline-only", baselineOnly);
    if (baselineOnly) $("comparison").replaceChildren(makeCard("baseline", baseline));
    else $("comparison").replaceChildren(makeCard("control", attempts.find(attempt => condition(attempt.condition) === "control")), makeCard("memory", attempts.find(attempt => condition(attempt.condition) === "memory")));
    for (const row of $("results").children) row.classList.toggle("selected", row.dataset.state === selectedState);
  }
  function renderResults() {
    $("results").replaceChildren(...bundle.attempts.map(attempt => {
      const row = element("tr"); row.dataset.state = String(attempt.init_state_id ?? "unspecified");
      const nameCell = element("td"); const button = element("button", show(attempt.attempt_id));
      button.addEventListener("click", () => {selectedState = row.dataset.state; $("state-select").value = selectedState; renderComparison(); showDetails("Attempt record", attempt);});
      nameCell.append(button); const evidence = element("td"); evidence.append(badge(attempt.provenance));
      row.append(nameCell, element("td", show(attempt.init_state_id)), element("td", conditionName(attempt.condition)), evidence, element("td", show(attempt.outcome ?? attempt.status), `result ${["success", "failure"].includes(attempt.outcome) ? attempt.outcome : "unknown"}`), element("td", `${show(attempt.step_index)} / ${show(attempt.decision_index)}`), element("td", time(attempt.elapsed_ms)), element("td", cost(attempt.cost_usd)));
      return row;
    }));
  }
  function showDetails(title, data) {
    const panel = $("details"); panel.replaceChildren(element("h3", title), element("pre", JSON.stringify(data, null, 2)));
    const refs = new Set();
    const collect = value => {if (!value || typeof value !== "object") return; for (const [key, item] of Object.entries(value)) {if (["uri", "rgb_ref", "image_ref", "video_ref", "artifact_ref"].includes(key) && mediaPath(item)) refs.add(item); else if (typeof item === "object") collect(item);}};
    collect(data);
    for (const ref of refs) {
      if (/\.(png|jpe?g|webp|gif)$/i.test(ref)) {const img = element("img"); img.src = ref; img.alt = "Recorded observation evidence"; img.loading = "lazy"; panel.append(img);}
      const link = element("a", `Open evidence: ${ref.split("/").pop().slice(0, 16)}…`); link.href = ref; link.target = "_blank"; link.rel = "noopener"; panel.append(link);
    }
  }
  function renderGraph() {
    const all = $("graph-level").value === "all";
    const nodes = bundle.graph.nodes.filter(node => all || !["Evidence", "StepEvent"].includes(node.label));
    const ids = new Set(nodes.map(node => node.id));
    const edges = bundle.graph.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target));
    $("graph-count").textContent = `${nodes.length} of ${bundle.graph.nodes.length} nodes · ${edges.length} connections · select a node to inspect`;
    $("graph").replaceChildren(); $("edges").replaceChildren();
    if (!nodes.length) {$("graph").append(element("p", "No graph records included in this export.", "muted")); return;}
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    const columns = Math.min(4, Math.max(2, Math.ceil(Math.sqrt(nodes.length))));
    const height = Math.max(280, Math.ceil(nodes.length / columns) * 110 + 40);
    const width = columns * 175 + 30;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`); svg.setAttribute("aria-label", "Exported experience graph");
    const positions = new Map(nodes.map((node, index) => [node.id, {x: 20 + index % columns * 175, y: 25 + Math.floor(index / columns) * 110}]));
    for (const edge of edges) {
      const a = positions.get(edge.source); const b = positions.get(edge.target); if (!a || !b) continue;
      const line = document.createElementNS(ns, "line");
      Object.entries({x1:a.x+68,y1:a.y+27,x2:b.x+68,y2:b.y+27,class:"graph-edge"}).forEach(([key, value]) => line.setAttribute(key, String(value)));
      svg.append(line);
      const button = element("button", `${edge.source} → ${edge.type} → ${edge.target}`); button.addEventListener("click", () => showDetails(edge.type, edge)); $("edges").append(button);
    }
    for (const node of nodes) {
      const pos = positions.get(node.id); const group = document.createElementNS(ns, "g");
      group.setAttribute("transform", `translate(${pos.x},${pos.y})`); group.setAttribute("class", `graph-node ${["Evidence", "Instruction", "Skill"].includes(node.label) ? "warm" : ""}`); group.setAttribute("tabindex", "0"); group.setAttribute("role", "button"); group.setAttribute("aria-label", `${node.label}: ${node.id}`);
      const rect = document.createElementNS(ns, "rect"); Object.entries({width:140,height:57,rx:9}).forEach(([key,value]) => rect.setAttribute(key,String(value))); group.append(rect);
      for (const [text, y] of [[node.label || "Record",23],[String(node.id).slice(0,18),41]]) {const label = document.createElementNS(ns,"text"); label.setAttribute("x","11"); label.setAttribute("y",String(y)); label.textContent = text; if (y === 41) {label.style.fontSize = "9px"; label.style.fontWeight = "400";} group.append(label);}
      const select = () => {svg.querySelectorAll(".selected").forEach(item => item.classList.remove("selected")); group.classList.add("selected"); showDetails(`${node.label || "Record"} · ${node.id}`, node.properties || node);};
      group.addEventListener("click", select); group.addEventListener("keydown", event => {if (event.key === "Enter" || event.key === " ") {event.preventDefault(); select();}}); svg.append(group);
    }
    $("graph").append(svg);
  }
  $("state-select").addEventListener("change", event => {selectedState = event.target.value; renderComparison();});
  $("graph-level").addEventListener("change", renderGraph);
  $("bundle-input").addEventListener("change", async event => {try {const file = event.target.files[0]; if (file) setBundle(JSON.parse(await file.text()));} catch (error) {$("error").textContent = error.message; $("error").hidden = false;}});
  try {setBundle(window.ARMA_BUNDLE || {schema_version:"1",attempts:[],graph:{nodes:[],edges:[]}});} catch (error) {$("error").textContent = error.message; $("error").hidden = false;}
})();
