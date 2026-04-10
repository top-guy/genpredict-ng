/* ─────────────────────────────────────────────────────────
   main.js — GenPredict NG Client-Side JavaScript
   ─────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {

  // ── Flash message auto-dismiss ─────────────────────────
  document.querySelectorAll('.flash-msg').forEach(msg => {
    const close = msg.querySelector('.flash-close');
    if (close) close.addEventListener('click', () => dismissFlash(msg));
    setTimeout(() => dismissFlash(msg), 6000);
  });

  function dismissFlash(el) {
    el.style.transition = 'opacity 0.3s, transform 0.3s';
    el.style.opacity = '0';
    el.style.transform = 'translateX(120%)';
    setTimeout(() => el.remove(), 300);
  }

  // ── Sidebar mobile toggle ──────────────────────────────
  const sidebar  = document.querySelector('.sidebar');
  const overlay  = document.querySelector('.sidebar-overlay');
  const openBtn  = document.querySelector('.menu-toggle');

  if (openBtn && sidebar) {
    openBtn.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      overlay && overlay.classList.toggle('active');
    });
    overlay && overlay.addEventListener('click', () => {
      sidebar.classList.remove('open');
      overlay.classList.remove('active');
    });
  }

  // ── Slider live-value display ──────────────────────────
  document.querySelectorAll('.form-range[data-label]').forEach(slider => {
    const labelId = slider.getAttribute('data-label');
    const label   = document.getElementById(labelId);
    const suffix  = slider.getAttribute('data-suffix') || '';

    function updateLabel() {
      if (label) label.textContent = slider.value + suffix;
    }
    slider.addEventListener('input', updateLabel);
    updateLabel();
  });

  // ── Fault counter buttons ──────────────────────────────
  const faultCount  = document.getElementById('fault_count');
  const decreaseBtn = document.getElementById('fault-decrease');
  const increaseBtn = document.getElementById('fault-increase');
  const faultDisplay = document.getElementById('fault-display');

  if (faultCount && decreaseBtn && increaseBtn) {
    function updateFaultDisplay() {
      const v = parseInt(faultCount.value) || 0;
      if (faultDisplay) faultDisplay.textContent = v;
      decreaseBtn.disabled = v <= 0;
    }

    decreaseBtn.addEventListener('click', () => {
      const v = parseInt(faultCount.value) || 0;
      if (v > 0) { faultCount.value = v - 1; updateFaultDisplay(); }
    });

    increaseBtn.addEventListener('click', () => {
      const v = parseInt(faultCount.value) || 0;
      faultCount.value = v + 1;
      updateFaultDisplay();
    });

    updateFaultDisplay();
  }

  // ── Confirm delete dialogs ─────────────────────────────
  document.querySelectorAll('[data-confirm]').forEach(btn => {
    btn.addEventListener('click', e => {
      const msg = btn.getAttribute('data-confirm') || 'Are you sure?';
      if (!confirm(msg)) e.preventDefault();
    });
  });

  // ── Health Score Gauge Chart (canvas#healthGauge) ──────
  const gaugeCanvas = document.getElementById('healthGauge');
  if (gaugeCanvas && typeof Chart !== 'undefined') {
    const score     = parseFloat(gaugeCanvas.getAttribute('data-score')) || 0;
    const riskLevel = gaugeCanvas.getAttribute('data-risk') || 'HEALTHY';

    const colorMap = {
      'HEALTHY':   '#10b981',
      'MODERATE':  '#f59e0b',
      'HIGH RISK': '#f97316',
      'CRITICAL':  '#ef4444',
    };
    const barColor = colorMap[riskLevel] || '#10b981';
    const remainder = 100 - score;

    new Chart(gaugeCanvas, {
      type: 'doughnut',
      data: {
        datasets: [{
          data: [score, remainder],
          backgroundColor: [barColor, 'rgba(255,255,255,0.04)'],
          borderWidth: 0,
          borderRadius: 6,
        }]
      },
      options: {
        cutout: '78%',
        rotation: -90,
        circumference: 180,
        responsive: true,
        maintainAspectRatio: true,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        animation: { animateRotate: true, duration: 1200, easing: 'easeOutQuart' }
      }
    });

    // Animate the number
    const numEl = document.getElementById('healthScoreNum');
    if (numEl) {
      let current = 0;
      const step = score / 60;
      const interval = setInterval(() => {
        current = Math.min(current + step, score);
        numEl.textContent = Math.round(current);
        if (current >= score) clearInterval(interval);
      }, 16);
    }
  }

  // ── Health Trend Line Chart (canvas#trendChart) ────────
  const trendCanvas = document.getElementById('trendChart');
  if (trendCanvas && typeof Chart !== 'undefined') {
    const genId = trendCanvas.getAttribute('data-gen-id');
    if (genId) {
      fetch(`/api/generators/${genId}/trend`)
        .then(r => r.json())
        .then(data => {
          if (!data.labels || data.labels.length === 0) return;
          renderTrendChart(trendCanvas, data.labels, data.scores, data.risks);
        })
        .catch(console.error);
    }
  }

  function renderTrendChart(canvas, labels, scores, risks) {
    const colorMap = { 'HEALTHY': '#10b981', 'MODERATE': '#f59e0b', 'HIGH RISK': '#f97316', 'CRITICAL': '#ef4444' };
    const pointColors = (risks || []).map(r => colorMap[r] || '#94a3b8');

    new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Health Score',
          data: scores,
          borderColor: '#f59e0b',
          backgroundColor: 'rgba(245,158,11,0.08)',
          borderWidth: 2.5,
          pointBackgroundColor: pointColors,
          pointBorderColor: pointColors,
          pointRadius: 5,
          fill: true,
          tension: 0.4,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            min: 0, max: 100,
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#94a3b8' },
            border: { color: 'rgba(255,255,255,0.06)' }
          },
          x: {
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#94a3b8', maxRotation: 45 },
            border: { color: 'rgba(255,255,255,0.06)' }
          }
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#14142a',
            borderColor: 'rgba(255,255,255,0.08)',
            borderWidth: 1,
            titleColor: '#f1f5f9',
            bodyColor: '#94a3b8',
          }
        }
      }
    });
  }

  // ── Daily Logs Usage Chart (canvas#logsChart) ──────────
  const logsCanvas = document.getElementById('logsChart');
  if (logsCanvas && typeof Chart !== 'undefined') {
    const genId = logsCanvas.getAttribute('data-gen-id');
    if (genId) {
      fetch(`/api/generators/${genId}/logs/trend`)
        .then(r => r.json())
        .then(data => {
          if (!data.labels || data.labels.length === 0) return;
          new Chart(logsCanvas, {
            type: 'bar',
            data: {
              labels: data.labels,
              datasets: [
                {
                  label: 'Usage Hrs',
                  data: data.usage,
                  backgroundColor: 'rgba(59,130,246,0.6)',
                  borderColor: '#3b82f6',
                  borderWidth: 1,
                  borderRadius: 4,
                  yAxisID: 'y',
                },
                {
                  label: 'Load %',
                  data: data.load,
                  type: 'line',
                  borderColor: '#f59e0b',
                  backgroundColor: 'rgba(245,158,11,0.08)',
                  borderWidth: 2,
                  pointBackgroundColor: '#f59e0b',
                  pointRadius: 3,
                  fill: false,
                  tension: 0.4,
                  yAxisID: 'y2',
                }
              ]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              scales: {
                y:  { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#94a3b8' }, border: { color: 'rgba(255,255,255,0.06)' } },
                y2: { position: 'right', min: 0, max: 100, grid: { display: false }, ticks: { color: '#94a3b8' } },
                x:  { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#94a3b8' } }
              },
              plugins: {
                legend: { labels: { color: '#94a3b8', usePointStyle: true, pointStyleWidth: 8, font: { size: 11 } } },
                tooltip: { backgroundColor: '#14142a', borderColor: 'rgba(255,255,255,0.08)', borderWidth: 1, titleColor: '#f1f5f9', bodyColor: '#94a3b8' }
              }
            }
          });
        })
        .catch(console.error);
    }
  }

  // ── Indicator bar fill animations ─────────────────────
  document.querySelectorAll('.indicator-bar-fill[data-fill]').forEach(bar => {
    const fill = Math.min(parseFloat(bar.getAttribute('data-fill')) || 0, 100);
    setTimeout(() => { bar.style.width = fill + '%'; }, 200);
  });

  // ── Active nav highlighting ────────────────────────────
  const currentPath = window.location.pathname;
  document.querySelectorAll('.nav-item').forEach(item => {
    const href = item.getAttribute('href');
    if (href && currentPath.startsWith(href) && href !== '/') {
      item.classList.add('active');
    }
    if (href === '/' && currentPath === '/') {
      item.classList.add('active');
    }
  });

  // ── Confirm delete forms ───────────────────────────────
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', e => {
      const msg = form.getAttribute('data-confirm') || 'Are you sure?';
      if (!confirm(msg)) e.preventDefault();
    });
  });

});
