const form = document.getElementById("clip-form");
const submitBtn = document.getElementById("submit-btn");
const statusSection = document.getElementById("status");
const statusMessage = document.getElementById("status-message");
const resultsSection = document.getElementById("results");

const durationInput = document.getElementById("duration");
const durationOut = document.getElementById("duration-out");

let pollTimer = null;

durationInput.addEventListener("input", () => {
  durationOut.textContent = durationInput.value;
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearInterval(pollTimer);

  const payload = {
    url: document.getElementById("url").value.trim(),
    mode: "manual",
    vertical: document.getElementById("vertical").checked,
    start: document.getElementById("start").value.trim(),
    duration: Number(durationInput.value),
  };

  setBusy(true);
  resultsSection.classList.add("hidden");
  resultsSection.innerHTML = "";
  showStatus("Submitting…");

  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Could not start the job");
    }
    pollJob(data.job_id);
  } catch (err) {
    showError(err.message);
    setBusy(false);
  }
});

function pollJob(jobId) {
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      const job = await res.json();
      if (!res.ok) throw new Error(job.detail || "Job lookup failed");

      showStatus(job.message);

      if (job.status === "done") {
        clearInterval(pollTimer);
        setBusy(false);
        statusSection.classList.add("hidden");
        renderClips(job.clips);
      } else if (job.status === "error") {
        clearInterval(pollTimer);
        setBusy(false);
        showError(job.message);
      }
    } catch (err) {
      clearInterval(pollTimer);
      setBusy(false);
      showError(err.message);
    }
  }, 2000);
}

function renderClips(clips) {
  resultsSection.classList.remove("hidden");
  if (!clips.length) {
    resultsSection.innerHTML = "<p>No clips were produced.</p>";
    return;
  }
  resultsSection.innerHTML = clips
    .map(
      (clip) => `
      <div class="clip-card">
        <video controls preload="metadata" src="/clips/${encodeURIComponent(clip.filename)}"></video>
        <h3>${escapeHtml(clip.title)}</h3>
        ${clip.reason ? `<p>${escapeHtml(clip.reason)}</p>` : ""}
        <a class="download-btn" href="/clips/${encodeURIComponent(clip.filename)}" download>Download</a>
      </div>`
    )
    .join("");
}

function showStatus(message) {
  statusSection.classList.remove("hidden");
  statusMessage.textContent = message;
  statusMessage.classList.remove("error-text");
}

function showError(message) {
  statusSection.classList.remove("hidden");
  statusMessage.textContent = `Error: ${message}`;
  statusMessage.classList.add("error-text");
}

function setBusy(busy) {
  submitBtn.disabled = busy;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
