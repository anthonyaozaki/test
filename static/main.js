/*
  main.js
  - Optional shared JS file.
  - Currently unused, but it's a good place for shared helpers later.
  - Keeping it here avoids console 404s when base.html includes it.
*/

// ------- Live page logic -------
  function initLivePage() {
    const statusPill = byId("liveStatus");
    const tubeTable = byId("tubeTable");
    const chart = byId("historyChart");
    const heatmapEl = byId("heatmap");
    
    // Select the new buttons we added to live.html
    const pauseBtn = byId("pauseBtn");
    const resumeBtn = byId("resumeBtn");
    const stopBtn = byId("stopBtn");

    let isRunning = true; // State to track if monitoring is active

    function tick() {
      if (!isRunning) return; // Logic stops here if paused or stopped

      const payload = generateData();

      if (statusPill) {
        statusPill.textContent = "Live (simulated)";
        statusPill.className = "pill ok";
      }

      setText("kpiSkip", payload.metrics.skip);
      setText("kpiIdeal", payload.metrics.ideal);
      setText("kpiDouble", payload.metrics.double);
      setText("kpiOver", payload.metrics.overdrop);

      if (tubeTable) {
        tubeTable.innerHTML = "";
        Object.entries(payload.tubes).forEach(([tube, count]) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>Tube ${tube}</td>
            <td>${count}</td>
            <td><span class="badge ${bucketLabel(count)}">${bucketLabel(count)}</span></td>
          `;
          tubeTable.appendChild(tr);
        });
      }

      if (chart) drawHistory(chart, payload.history || []);
      if (heatmapEl) renderHeatmap(heatmapEl, payload.heatmap || []);
    }

    // --- Button Event Listeners ---
    pauseBtn.addEventListener("click", () => {
      isRunning = false;
      pauseBtn.style.display = "none";
      resumeBtn.style.display = "inline-flex";
      statusPill.textContent = "Paused";
      statusPill.className = "pill"; 
    });

    resumeBtn.addEventListener("click", () => {
      isRunning = true;
      resumeBtn.style.display = "none";
      pauseBtn.style.display = "inline-flex";
      statusPill.textContent = "Live (simulated)";
      statusPill.className = "pill ok";
    });

    stopBtn.addEventListener("click", () => {
      isRunning = false;
      statusPill.textContent = "EMERGENCY STOPPED";
      statusPill.style.color = "var(--bad)";
      statusPill.style.borderColor = "var(--bad)";
      
      // Lock the system
      pauseBtn.disabled = true;
      resumeBtn.disabled = true;
      stopBtn.textContent = "SYSTEM HALTED";
      stopBtn.classList.remove("bad"); // Remove red to show it's "dead"
    });

    tick();
    setInterval(tick, 1000);
  }
