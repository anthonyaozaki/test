/*
  main.js
  - Optional shared JS file.
  - Currently unused, but it's a good place for shared helpers later.
  - Keeping it here avoids console 404s when base.html includes it.
*/

(function () {
  const state = {
    tubes: Object.fromEntries(Array.from({ length: 50 }, (_, i) => [i + 1, 1])),
    history: [],
    currentFilter: 'all'
  };

  // ------- Data generator  -------
  function generateData() {
    // Start all counts at 0 for this second's "snapshot"
    const metrics = { skip: 0, ideal: 0, double: 0, overdrop: 0 };

    // Loop through every tube in our state (now 1 through 50)
    Object.keys(state.tubes).forEach((tube) => {
      const count = pick(TUBE_CHOICES); // Pick a random simulated seed count
      state.tubes[tube] = count;
      
      // Add to the metrics totals
      const category = classify(count);
      metrics[category] += 1;
    });

    // Simulated Heatmap for the field (8x14 grid)
    const heatmap = Array.from({ length: 8 }, () =>
      Array.from({ length: 14 }, () => pick(HEAT_CHOICES))
    );

    const total = Object.values(state.tubes).reduce((a, b) => a + b, 0);
    state.history.push({ time: nowTime(), total });

    return {
      tubes: state.tubes,
      metrics, // These are the numbers for the 4 KPI cards
      history: state.history.slice(-20),
      heatmap
    };

  // Implemented the set filter function
window.setFilter = function(filterType) {
    state.currentFilter = filterType;
    
    // UI feedback for buttons
    document.querySelectorAll('.btn.small').forEach(btn => {
      btn.classList.remove('active-filter');
      const text = btn.textContent.toLowerCase();
      if (
        (filterType === 'all' && text.includes('all')) ||
        (filterType === 'ideal' && text.includes('ideal')) ||
        (filterType === 'double' && text.includes('double')) ||
        (filterType === 'skip' && text.includes('skip')) ||
        (filterType === 'overdrop' && text.includes('overdrop'))
      ) {
        btn.classList.add('active-filter');
      }
    });
  
    // Trigger an immediate update so the user doesn't wait 1 second
    if (window.refreshNow) window.refreshNow();
  };
  
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
    
    // Filter/Sorting Implementation 
    window.refreshNow = function() {
      const payload = {
        tubes: state.tubes,
        metrics: { 
          skip: Object.values(state.tubes).filter(v => v === 0).length,
          ideal: Object.values(state.tubes).filter(v => v === 1).length,
          double: Object.values(state.tubes).filter(v => v === 2).length,
          overdrop: Object.values(state.tubes).filter(v => v > 2).length
        }
      };
      updateUI(payload);
    };

    function updateUI(payload) {
      // Update KPIs
      setText("kpiSkip", payload.metrics.skip);
      setText("kpiIdeal", payload.metrics.ideal);
      setText("kpiDouble", payload.metrics.double);
      setText("kpiOver", payload.metrics.overdrop);

      if (tubeTable) {
        const entries = Object.entries(payload.tubes).filter(([_, count]) => {
          if (state.currentFilter === 'all') return true;
          return bucketLabel(count) === state.currentFilter;
        });

        if (entries.length === 0) {
          tubeTable.innerHTML = `<tr><td colspan="3" class="muted" style="text-align:center; padding:20px;">No tubes match this filter</td></tr>`;
        } else {
          tubeTable.innerHTML = entries.map(([tube, count]) => {
            const b = bucketLabel(count);
            return `<tr><td>Tube ${tube}</td><td>${count}</td><td><span class="badge ${b}">${b}</span></td></tr>`;
          }).join('');
        }
      }
    }
    
    function tick() {
      if (!isRunning) return; // Logic stops here if paused or stopped

      const payload = generateData();

      setText("kpiSkip", payload.metrics.skip);
      setText("kpiIdeal", payload.metrics.ideal);
      setText("kpiDouble", payload.metrics.double);
      setText("kpiOver", payload.metrics.overdrop);
        
      if (statusPill) {
        statusPill.textContent = "Live (simulated)";
        statusPill.className = "pill ok";
      }

      if (tubeTable) {
        // Implement filter buttons 
        const entries = Object.entries(payload.tubes).filter(([_, count]) => {
          if (state.currentFilter === 'all') return true;
          return bucketLabel(count) === state.currentFilter;
        });

        if (entries.length === 0) {
          tubeTable.innerHTML = `<tr><td colspan="3" class="muted" style="text-align:center; padding:20px;">No tubes match this filter</td></tr>`;
        } else {
          tubeTable.innerHTML = entries.map(([tube, count]) => {
            const b = bucketLabel(count);
            return `<tr><td>Tube ${tube}</td><td>${count}</td><td><span class="badge ${b}">${b}</span></td></tr>`;
          }).join('');
        }
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
