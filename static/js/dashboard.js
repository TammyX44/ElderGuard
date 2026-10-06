(function () {
  "use strict";

  var alertFeedInitialized = false;
  var notificationPollTimer = null;

  function statusClass(status) {
    return "status-pill status-" + String(status || "normal").toLowerCase();
  }

  function statusBackgroundClass(status) {
    return "patient-card-accent status-bg-" + String(status || "normal").toLowerCase();
  }

  function fetchJSON(url, options) {
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          var error = new Error((data && data.message) || "Request failed: " + response.status);
          error.data = data;
          throw error;
        }
        return data;
      });
    });
  }

  function escapeHTML(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","\'":"&#39;"}[char];
    });
  }

  function titleCase(value) {
    return String(value || "")
      .replaceAll("_", " ")
      .replace(/\b\w/g, function (m) { return m.toUpperCase(); });
  }

  function drawLineChart(container, values) {
    if (!container) return;

    var numericValues = (values || []).map(Number).filter(function (value) {
      return Number.isFinite(value);
    }).slice(-40);

    if (!numericValues.length) {
      container.innerHTML = '<div class="chart-empty">Waiting for live samples…</div>';
      return;
    }

    // Always draw immediately. The simulator preloads history, but duplicating a
    // single point also keeps the graph valid if a new patient is added later.
    if (numericValues.length === 1) numericValues.push(numericValues[0]);

    var width = 820;
    var height = 250;
    var left = 46;
    var right = 18;
    var top = 18;
    var bottom = 32;
    var plotWidth = width - left - right;
    var plotHeight = height - top - bottom;

    var dataMin = Math.min.apply(null, numericValues);
    var dataMax = Math.max.apply(null, numericValues);
    // Keep the normal HR band visible, while expanding cleanly for simulated spikes.
    var yMin = Math.min(50, Math.floor((dataMin - 8) / 10) * 10);
    var yMax = Math.max(120, Math.ceil((dataMax + 8) / 10) * 10);
    if (yMax - yMin < 70) yMax = yMin + 70;

    function xFor(index) {
      return left + (index / Math.max(1, numericValues.length - 1)) * plotWidth;
    }

    function yFor(value) {
      return top + (1 - ((value - yMin) / (yMax - yMin))) * plotHeight;
    }

    function esc(value) {
      return String(value).replace(/[&<>"]/g, function (char) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char];
      });
    }

    var grid = '';
    for (var i = 0; i <= 4; i++) {
      var gridValue = yMax - ((yMax - yMin) / 4) * i;
      var gy = top + (plotHeight / 4) * i;
      grid += '<line class="chart-grid-line" x1="' + left + '" y1="' + gy.toFixed(1) + '" x2="' + (width - right) + '" y2="' + gy.toFixed(1) + '"></line>';
      grid += '<text class="chart-axis-label" x="' + (left - 8) + '" y="' + (gy + 4).toFixed(1) + '" text-anchor="end">' + Math.round(gridValue) + '</text>';
    }

    var normalTop = yFor(100);
    var normalBottom = yFor(60);
    var normalY = Math.min(normalTop, normalBottom);
    var normalHeight = Math.abs(normalBottom - normalTop);

    var points = numericValues.map(function (value, index) {
      return xFor(index).toFixed(1) + ',' + yFor(value).toFixed(1);
    }).join(' ');

    var lastValue = numericValues[numericValues.length - 1];
    var lastX = xFor(numericValues.length - 1);
    var lastY = yFor(lastValue);

    var svg = '' +
      '<svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<rect class="chart-normal-band" x="' + left + '" y="' + normalY.toFixed(1) + '" width="' + plotWidth + '" height="' + normalHeight.toFixed(1) + '"></rect>' +
        grid +
        '<line class="chart-threshold-line" x1="' + left + '" y1="' + yFor(100).toFixed(1) + '" x2="' + (width - right) + '" y2="' + yFor(100).toFixed(1) + '"></line>' +
        '<polyline class="chart-line" points="' + esc(points) + '"></polyline>' +
        '<circle class="chart-last-point" cx="' + lastX.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="4.5"></circle>' +
        '<text class="chart-x-label" x="' + left + '" y="' + (height - 8) + '">Older</text>' +
        '<text class="chart-x-label" x="' + (width - right) + '" y="' + (height - 8) + '" text-anchor="end">Now</text>' +
      '</svg>' +
      '<div class="chart-current-value"><span>Current</span><strong>' + Math.round(lastValue) + '</strong><small>BPM</small></div>' +
      '<div class="chart-normal-key">Normal demo band 60–100 BPM</div>';

    container.innerHTML = svg;
  }

  // Five-check memory, shown as steps: dots 1-5 per vital, oldest first.
  // Amber = that check was abnormal. At 3 of 5 the vital turns persistent
  // and the overall status escalates one level.
  function renderMemoryInto(containerId, data) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var results = data.decision.vital_results;
    var labels = {
      heart_rate: "Heart rate",
      spo2: "SpO\u2082",
      temperature: "Temperature",
      blood_pressure: "Blood pressure"
    };

    var html = "";
    Object.keys(labels).forEach(function (key) {
      var result = results[key];
      if (!result || !result.history) return;
      var abnormal = result.history.filter(Boolean).length;
      var dots = result.history.map(function (flag, index) {
        return '<span class="memory-dot' + (flag ? " abnormal" : "") + '">' + (index + 1) + '</span>';
      }).join("");
      html += '<div class="memory-line' + (result.persistent ? " persistent" : "") + '">' +
        '<span class="memory-vital">' + labels[key] + '</span>' +
        '<span class="memory-dots-set">' + dots + '</span>' +
        '<strong class="memory-count">' + abnormal + '/5</strong>' +
        (result.persistent ? '<em class="memory-flag">persistent</em>' : '') +
      '</div>';
    });

    container.innerHTML = html +
      '<div class="memory-legend">' +
        '<span><i class="dot-key ok"></i>normal check</span>' +
        '<span><i class="dot-key bad"></i>abnormal check</span>' +
        '<span class="memory-rule">3 of 5 abnormal = persistent &rarr; status escalates one level</span>' +
      '</div>';
  }

  // Decision panel, in plain language: each vital gets a flag (0/1), every
  // flag carries an importance weight, points are flag x weight, and the
  // panel escalates when total points reach the threshold. The algorithm
  // names behind this live in the separate algorithms report.
  function neuronReading(key, vitals) {
    if (!vitals) return "";
    if (key === "heart_rate") return vitals.heart_rate + " BPM";
    if (key === "spo2") return vitals.spo2 + "%";
    if (key === "temperature") return vitals.temperature + "°C";
    if (key === "blood_pressure") return vitals.systolic + "/" + vitals.diastolic;
    return "";
  }

  function renderNeuronInto(containerId, data) {
    var container = document.getElementById(containerId);
    if (!container || !data.decision.neuron) return;
    var neuron = data.decision.neuron;

    var rows = neuron.inputs.map(function (input) {
      var state = input.x
        ? (input.currently_abnormal ? "problem now" : "kept flagging")
        : "normal";
      return '<div class="neuron-row' + (input.x ? " abnormal" : "") + '">' +
        '<span class="neuron-label">' + escapeHTML(input.label) +
          '<small>' + escapeHTML(neuronReading(input.key, data.vitals)) + ' · ' + state + '</small>' +
        '</span>' +
        '<code>' + input.x + '</code>' +
        '<code>' + input.w.toFixed(1) + '</code>' +
        '<strong>' + (input.x * input.w).toFixed(1) + '</strong>' +
      '</div>';
    }).join("");

    var meterPercent = Math.min(100, Math.round(100 * neuron.sum / neuron.theta));

    container.innerHTML =
      '<span class="neuron-title">How this status was decided</span>' +
      '<div class="neuron-table">' +
        '<div class="neuron-row neuron-head"><span>Vital</span><code>Flag</code><code>Weight</code><strong>Points</strong></div>' +
        rows +
      '</div>' +
      '<div class="neuron-sum ' + (neuron.output ? " fires" : "") + '">' +
        '<div class="neuron-meter-line"><span>Total points</span><div class="neuron-meter"><i style="width:' + meterPercent + '%"></i></div><span><strong>' + neuron.sum.toFixed(1) + '</strong> / ' + neuron.theta + ' needed</span></div>' +
        '<em>' + (neuron.output
          ? "Enough points — escalate the alert"
          : "Not enough points yet — keep watching") + '</em>' +
        '<small>A vital scores its flag when it leaves its normal range now, or kept flagging in 3 of its last 5 checks.</small>' +
      '</div>';
  }

  function renderReasonsInto(listId, data) {
    var list = document.getElementById(listId);
    if (!list) return;
    list.innerHTML = "";
    data.decision.reasons.forEach(function (reason) {
      var li = document.createElement("li");
      li.textContent = reason;
      list.appendChild(li);
    });
  }

  function renderActivityInto(feedId, data) {
    var feed = document.getElementById(feedId);
    if (!feed) return;
    feed.innerHTML = "";
    data.activity.forEach(function (event) {
      var row = document.createElement("div");
      row.className = "activity-item";
      var time = document.createElement("time");
      var source = document.createElement("span");
      var text = document.createElement("p");
      time.textContent = event.time;
      source.textContent = event.source;
      text.textContent = event.message;
      row.append(time, source, text);
      feed.appendChild(row);
    });
  }

  function startDashboardPolling() {
    var cards = Array.from(document.querySelectorAll("[data-dashboard-patient]"));
    if (!cards.length) return;
    var pollBusy = false;

    function renderRecentIncidents(alerts) {
      var container = document.getElementById("dashboard-recent-incidents");
      if (!container) return;
      if (!alerts || !alerts.length) {
        container.innerHTML = '<div class="empty-state">No incidents recorded yet.</div>';
        return;
      }
      container.innerHTML = alerts.map(function (alert) {
        var status = String(alert.status || "WATCH").toLowerCase();
        return '<div class="compact-incident">' +
          '<span class="incident-marker status-bg-' + status + '"></span>' +
          '<div><strong>' + escapeHTML(alert.patient_name || "Patient") + '</strong><small>' + escapeHTML(alert.reason || "Incident") + '</small></div>' +
          '<span class="status-pill status-' + status + '">' + escapeHTML(alert.status || "WATCH") + '</span>' +
        '</div>';
      }).join("");
    }

    function poll() {
      if (pollBusy) return;
      pollBusy = true;
      fetchJSON("/api/dashboard-state").then(function (data) {
        cards.forEach(function (card) {
          var id = card.dataset.dashboardPatient;
          var snap = data.snapshots[id];
          if (!snap) return;
          card.querySelector('[data-role="heart_rate"]').textContent = snap.vitals.heart_rate;
          card.querySelector('[data-role="spo2"]').textContent = snap.vitals.spo2;
          card.querySelector('[data-role="temperature"]').textContent = snap.vitals.temperature;
          card.querySelector('[data-role="bp"]').textContent = snap.vitals.systolic + "/" + snap.vitals.diastolic;
          card.querySelector('[data-role="updated-at"]').textContent = snap.updated_at;
          var status = card.querySelector('[data-role="status"]');
          status.textContent = snap.decision.status;
          status.className = statusClass(snap.decision.status);
          var accent = card.querySelector('[data-role="accent"]');
          accent.className = statusBackgroundClass(snap.decision.status);
          card.querySelector('[data-role="risk-score"]').textContent = snap.decision.risk_score;
          card.querySelector('[data-role="risk-bar"]').style.width = snap.decision.risk_score + "%";
        });

        var patientsCount = document.getElementById("patients-count");
        var attentionCount = document.getElementById("attention-count");
        var openCount = document.getElementById("open-incidents-count");
        var telegramSummary = document.getElementById("telegram-summary-state");
        var sidebarTelegram = document.getElementById("sidebar-telegram-state");
        if (patientsCount) patientsCount.textContent = data.summary.patients;
        if (attentionCount) attentionCount.textContent = data.summary.attention;
        if (openCount) openCount.textContent = data.summary.open_incidents;

        if (data.metrics) {
          var metricsMap = {
            "metrics-today": data.metrics.today,
            "metrics-critical": data.metrics.critical,
            "metrics-ack-rate": data.metrics.ack_rate + "%",
            "metrics-avg-ack": data.metrics.avg_ack
          };
          Object.keys(metricsMap).forEach(function (id) {
            var element = document.getElementById(id);
            if (element) element.textContent = metricsMap[id];
          });
        }
        if (telegramSummary) telegramSummary.textContent = data.summary.telegram_enabled ? "Telegram connected" : "Telegram setup required";
        if (sidebarTelegram) {
          sidebarTelegram.textContent = data.summary.telegram_enabled ? "READY" : "SETUP";
          sidebarTelegram.className = data.summary.telegram_enabled ? "channel-online" : "channel-offline";
        }
        renderRecentIncidents(data.recent_alerts);
      }).catch(function () {
        // Keep last values visible during a temporary dev-server interruption.
      }).finally(function () {
        pollBusy = false;
      });
    }

    poll();
    setInterval(poll, 1200);
  }

  function updatePatient(data) {
    var ids = {
      "heart-rate": data.vitals.heart_rate,
      "spo2": data.vitals.spo2,
      "temperature": data.vitals.temperature,
      "blood-pressure": data.vitals.systolic + "/" + data.vitals.diastolic,
      "heart-status": data.decision.vital_results.heart_rate.status,
      "spo2-status": data.decision.vital_results.spo2.status,
      "temperature-status": data.decision.vital_results.temperature.status,
      "bp-status": data.decision.vital_results.blood_pressure.status,
      "risk-score": data.decision.risk_score,
      "decision-action": data.decision.action,
      "current-scenario": titleCase(data.scenario)
    };
    Object.keys(ids).forEach(function (id) {
      var element = document.getElementById(id);
      if (element) element.textContent = ids[id];
    });
    var overall = document.getElementById("overall-status");
    if (overall) {
      overall.textContent = data.decision.status;
      overall.className = statusClass(data.decision.status);
    }
    renderReasonsInto("reason-list", data);
    renderNeuronInto("patient-neuron", data);
    renderMemoryInto("memory-dots", data);
    renderActivityInto("activity-feed", data);
    drawLineChart(document.getElementById("heart-chart"), data.history.heart_rate);
  }

  function startPatientPage() {
    var root = document.querySelector("[data-patient-id]");
    if (!root) return;
    var patientId = root.dataset.patientId;

    function poll() {
      fetchJSON("/api/live/" + patientId).then(updatePatient).catch(function () {});
    }

    poll();
    setInterval(poll, 1600);
  }

  function startSimulationPage(patients) {
    var root = document.querySelector("[data-simulation-page]");
    if (!root) return;

    var patientId = root.dataset.patientId;
    var selectedScenario = "heart_rate_spike";
    var selectedIntensity = "moderate";
    var duration = document.getElementById("sim-duration");
    var durationLabel = document.getElementById("sim-duration-label");
    var patientSelect = document.getElementById("simulation-patient-select");

    document.querySelectorAll("[data-scenario]").forEach(function (button) {
      button.addEventListener("click", function () {
        document.querySelectorAll("[data-scenario]").forEach(function (item) { item.classList.remove("active"); });
        button.classList.add("active");
        selectedScenario = button.dataset.scenario;
      });
    });

    document.querySelectorAll("[data-intensity]").forEach(function (button) {
      button.addEventListener("click", function () {
        document.querySelectorAll("[data-intensity]").forEach(function (item) { item.classList.remove("active"); });
        button.classList.add("active");
        selectedIntensity = button.dataset.intensity;
      });
    });

    duration.addEventListener("input", function () {
      durationLabel.textContent = duration.value + " sec";
    });

    patientSelect.addEventListener("change", function () {
      patientId = patientSelect.value;
      root.dataset.patientId = patientId;
      var patient = patients[patientId];
      document.getElementById("sim-patient-id").textContent = patient.id;
      document.getElementById("sim-patient-name").textContent = patient.name;
      document.getElementById("sim-patient-meta").textContent = patient.age + " yrs · " + patient.room;
      document.getElementById("sim-monitor-title").textContent = patient.name;
      if (window.history && window.history.replaceState) {
        window.history.replaceState({}, "", "/simulation?patient=" + encodeURIComponent(patientId));
      }
      poll();
    });

    function runScenario(scenario) {
      var body = {
        scenario: scenario || selectedScenario,
        intensity: selectedIntensity,
        duration: Number(duration.value)
      };
      fetchJSON("/api/simulate/" + patientId, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).then(function () {
        showToast("Simulation started", titleCase(body.scenario) + " · " + titleCase(body.intensity), "info");
        poll();
      }).catch(function () {
        showToast("Simulation could not start", "Check that the Flask server is running.", "warning");
      });
    }

    document.getElementById("sim-run-button").addEventListener("click", function () { runScenario(); });
    document.getElementById("sim-recovery-button").addEventListener("click", function () { runScenario("recovery"); });

    function updateSimulation(data) {
      document.getElementById("sim-heart-rate").textContent = data.vitals.heart_rate;
      document.getElementById("sim-spo2").textContent = data.vitals.spo2;
      document.getElementById("sim-temperature").textContent = data.vitals.temperature;
      document.getElementById("sim-bp").textContent = data.vitals.systolic + "/" + data.vitals.diastolic;
      document.getElementById("sim-risk-score").textContent = data.decision.risk_score;
      document.getElementById("sim-current-scenario").textContent = titleCase(data.scenario);
      document.getElementById("sim-decision-action").textContent = data.decision.action;
      var status = document.getElementById("sim-overall-status");
      status.textContent = data.decision.status;
      status.className = statusClass(data.decision.status);
      renderReasonsInto("sim-reason-list", data);
      renderNeuronInto("sim-neuron", data);
      renderMemoryInto("sim-memory-dots", data);
      renderActivityInto("sim-activity-feed", data);
      drawLineChart(document.getElementById("sim-heart-chart"), data.history.heart_rate);
    }

    function poll() {
      fetchJSON("/api/live/" + patientId).then(updateSimulation).catch(function () {});
    }

    poll();
    setInterval(poll, 1000);
  }


  function startTelegramSettings() {
    var root = document.getElementById("telegram-settings-root");
    if (!root) return;

    var tokenInput = document.getElementById("telegram-bot-token");
    var chatInput = document.getElementById("telegram-chat-id");
    var botResult = document.getElementById("telegram-bot-result");
    var chatResult = document.getElementById("telegram-chat-result");
    var message = document.getElementById("telegram-settings-message");
    var badge = document.getElementById("telegram-connection-badge");

    function payload() {
      return {
        bot_token: tokenInput.value.trim(),
        chat_id: chatInput.value.trim()
      };
    }

    function setMessage(text, ok) {
      message.textContent = text;
      message.className = "settings-message " + (ok ? "success" : "error");
    }

    function updateReadiness(configured, hasToken, chatId) {
      var readyToken = document.getElementById("ready-token");
      var readyChat = document.getElementById("ready-chat");
      var readyDelivery = document.getElementById("ready-delivery");
      var sidebarTelegram = document.getElementById("sidebar-telegram-state");
      if (readyToken) readyToken.textContent = hasToken ? "Saved" : "Missing";
      if (readyChat) readyChat.textContent = chatId || "Missing";
      if (readyDelivery) readyDelivery.textContent = configured ? "Ready" : "Setup needed";
      if (badge) {
        badge.textContent = configured ? "CONNECTED" : "NOT CONNECTED";
        badge.className = statusClass(configured ? "NORMAL" : "WATCH");
      }
      if (sidebarTelegram) {
        sidebarTelegram.textContent = configured ? "READY" : "SETUP";
        sidebarTelegram.className = configured ? "channel-online" : "channel-offline";
      }
    }

    document.getElementById("telegram-test-bot").addEventListener("click", function () {
      botResult.textContent = "Checking Telegram…";
      fetchJSON("/api/telegram/test-bot", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({bot_token: tokenInput.value.trim()})
      }).then(function (data) {
        botResult.innerHTML = '<strong>@' + escapeHTML(data.bot.username || "bot") + '</strong> · ID ' + escapeHTML(data.bot.id) + ' · ' + escapeHTML(data.bot.first_name);
        setMessage("Bot token is valid. Now send /start to this bot in Telegram.", true);
      }).catch(function () {
        botResult.textContent = "Token test failed";
        setMessage("Could not validate the bot token. Check the token and internet connection.", false);
      });
    });

    document.getElementById("telegram-discover-chat").addEventListener("click", function () {
      chatResult.textContent = "Looking for recent bot messages…";
      fetchJSON("/api/telegram/discover-chats", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({bot_token: tokenInput.value.trim()})
      }).then(function (data) {
        if (!data.chats.length) {
          chatResult.textContent = "No chat found yet";
          setMessage("Open your bot in Telegram, send /start, then click Find my chat ID again.", false);
          return;
        }
        var chat = data.chats[0];
        chatInput.value = chat.chat_id;
        chatResult.innerHTML = '<strong>' + escapeHTML(chat.name) + '</strong> · ' + escapeHTML(chat.type) + ' · ID ' + escapeHTML(chat.chat_id);
        setMessage("Chat ID found and filled in. Save the setup next.", true);
      }).catch(function () {
        chatResult.textContent = "Chat lookup failed";
        setMessage("Could not read bot updates. First test the token and send /start to the bot.", false);
      });
    });

    document.getElementById("telegram-save").addEventListener("click", function () {
      fetchJSON("/api/telegram/settings", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload())
      }).then(function (data) {
        tokenInput.value = "";
        tokenInput.placeholder = data.settings.has_token ? data.settings.bot_token : "Paste BotFather token";
        updateReadiness(data.settings.configured, data.settings.has_token, data.settings.chat_id);
        setMessage(data.settings.configured ? "Telegram setup saved and ready." : "Settings saved. Add both a valid bot token and chat ID to complete setup.", data.settings.configured);
      }).catch(function () {
        setMessage("Could not save Telegram settings.", false);
      });
    });

    document.getElementById("telegram-test-alert").addEventListener("click", function () {
      setMessage("Sending test alert…", true);
      fetchJSON("/api/telegram/test-alert", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload())
      }).then(function (data) {
        setMessage(data.message, true);
        showToast("Telegram test sent", "Check the caretaker phone.", "info");
      }).catch(function () {
        setMessage("Test alert failed. Save/verify the bot token and chat ID first.", false);
      });
    });
  }

  function bindAcknowledgements() {
    document.querySelectorAll(".ack-button").forEach(function (button) {
      button.addEventListener("click", function () {
        var id = button.dataset.alertId;
        fetchJSON("/api/alerts/" + id + "/acknowledge", { method: "POST" }).then(function (data) {
          var replacement = document.createElement("span");
          replacement.className = "acknowledged";
          replacement.innerHTML = "✓ " + data.alert.acknowledged_by + "<small>" + data.alert.acknowledged_at + "</small>";
          button.replaceWith(replacement);
        });
      });
    });
  }

  function getSeenAlerts() {
    try { return JSON.parse(localStorage.getItem("elderguardSeenAlerts") || "[]"); }
    catch (e) { return []; }
  }

  /* ----- Critical alarm sound (Web Audio API) -----
     Browsers only allow audio after a user gesture, so the context is created
     lazily and resumed on the first click. The beep loop runs while any
     CRITICAL incident is still unacknowledged and stops automatically once
     the caretaker acknowledges it. */
  var audioContext = null;
  var alarmTimer = null;

  function ensureAudio() {
    if (!audioContext) {
      try { audioContext = new (window.AudioContext || window.webkitAudioContext)(); }
      catch (e) { return; }
    }
    if (audioContext.state === "suspended") audioContext.resume();
  }

  function playBeep() {
    if (!audioContext || audioContext.state !== "running") return;
    var osc = audioContext.createOscillator();
    var gain = audioContext.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.001, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.15, audioContext.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + 0.3);
    osc.connect(gain);
    gain.connect(audioContext.destination);
    osc.start();
    osc.stop(audioContext.currentTime + 0.32);
  }

  function setCriticalAlarm(active) {
    if (active && !alarmTimer) {
      playBeep();
      alarmTimer = setInterval(playBeep, 800);
    } else if (!active && alarmTimer) {
      clearInterval(alarmTimer);
      alarmTimer = null;
    }
  }

  /* ----- Voice announcements (Speech Synthesis API) ----- */
  function speak(text) {
    if (!("speechSynthesis" in window)) return;
    var utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1;
    speechSynthesis.speak(utterance);
  }

  function saveSeenAlerts(ids) {
    localStorage.setItem("elderguardSeenAlerts", JSON.stringify(ids.slice(0, 80)));
  }

  function showToast(title, body, level) {
    var stack = document.getElementById("toast-stack");
    if (!stack) return;
    var toast = document.createElement("div");
    toast.className = "app-toast toast-" + (level || "info");
    var strong = document.createElement("strong");
    var text = document.createElement("span");
    strong.textContent = title;
    text.textContent = body;
    toast.append(strong, text);
    stack.appendChild(toast);
    requestAnimationFrame(function () { toast.classList.add("show"); });
    setTimeout(function () {
      toast.classList.remove("show");
      setTimeout(function () { toast.remove(); }, 250);
    }, 6000);
  }

  function updateNotificationButton() {
    var button = document.getElementById("browser-notification-button");
    var state = document.getElementById("browser-notification-state");
    if (!button || !state) return;

    if (!("Notification" in window)) {
      button.disabled = true;
      button.textContent = "Desktop alerts unavailable";
      state.textContent = "This browser does not support Web Notifications";
      return;
    }

    if (Notification.permission === "granted") {
      button.textContent = "Desktop alerts enabled";
      button.classList.add("enabled");
      state.textContent = "New warning/critical incidents can appear on this desktop";
    } else if (Notification.permission === "denied") {
      button.textContent = "Desktop alerts blocked";
      button.classList.remove("enabled");
      state.textContent = "Allow notifications in your browser site settings";
    } else {
      button.textContent = "Enable desktop alerts";
      button.classList.remove("enabled");
      state.textContent = "Click once before your class demonstration";
    }
  }

  function requestDesktopNotifications() {
    if (!("Notification" in window)) return;
    ensureAudio();
    Notification.requestPermission().then(function (permission) {
      updateNotificationButton();
      if (permission === "granted") {
        showToast("Desktop alerts enabled", "ElderGuard can now show new incident notifications.", "info");
        // First spoken phrase also primes speech output inside this user gesture.
        speak("Desktop alerts enabled.");
      }
    });
  }

  function sendDesktopAlert(alert) {
    var reason = alert.reasons && alert.reasons.length ? alert.reasons[0] : "Abnormal vital pattern detected";
    if (Notification.permission === "granted") {
      var notification = new Notification("ElderGuard · " + alert.status + " · " + alert.patient_name, {
        body: reason + "\nPriority " + alert.risk_score + "/100",
        tag: "elderguard-" + alert.id,
        renotify: true
      });
      notification.onclick = function () {
        window.focus();
        window.location.href = "/patient/" + alert.patient_id;
        notification.close();
      };
    }
    showToast(alert.status + " · " + alert.patient_name, reason, alert.status === "CRITICAL" ? "critical" : "warning");
    speak(alert.status === "CRITICAL"
      ? "Critical alert. " + alert.patient_name + ". " + reason
      : "Warning. " + alert.patient_name + ". " + reason);
  }

  function pollNotificationFeed() {
    fetchJSON("/api/notification-feed").then(function (data) {
      var seen = getSeenAlerts();
      var seenSet = new Set(seen);
      var currentIds = data.alerts.map(function (alert) { return alert.id; }).filter(Boolean);

      if (!alertFeedInitialized) {
        saveSeenAlerts(Array.from(new Set(currentIds.concat(seen))));
        alertFeedInitialized = true;
        return;
      }

      var newAlerts = data.alerts.filter(function (alert) { return alert.id && !seenSet.has(alert.id); });
      newAlerts.reverse().forEach(sendDesktopAlert);
      if (newAlerts.length) {
        saveSeenAlerts(Array.from(new Set(newAlerts.map(function (a) { return a.id; }).concat(seen))));
      }

      // Alarm beeps only while a patient is CURRENTLY critical - it stops the
      // moment vitals recover, regardless of whether incidents were acknowledged.
      var statuses = data.current_statuses || {};
      var criticalOpen = Object.keys(statuses).some(function (id) {
        return statuses[id] === "CRITICAL";
      });
      setCriticalAlarm(criticalOpen);
    }).catch(function () {});
  }

  function initThemeToggle() {
    var button = document.getElementById("theme-toggle");
    if (!button) return;

    function label() {
      button.textContent = document.documentElement.getAttribute("data-theme") === "dark"
        ? "Light mode"
        : "Dark mode";
    }

    button.addEventListener("click", function () {
      var dark = document.documentElement.getAttribute("data-theme") === "dark";
      if (dark) {
        document.documentElement.removeAttribute("data-theme");
        localStorage.setItem("elderguardTheme", "light");
      } else {
        document.documentElement.setAttribute("data-theme", "dark");
        localStorage.setItem("elderguardTheme", "dark");
      }
      label();
    });

    label();
  }

  function initGlobalAlerts() {
    if (document.body.dataset.authenticated !== "true") return;
    var button = document.getElementById("browser-notification-button");
    if (button) button.addEventListener("click", requestDesktopNotifications);
    initThemeToggle();
    // Browsers unlock audio/speech after the first user gesture.
    document.addEventListener("pointerdown", ensureAudio, { once: true });
    updateNotificationButton();
    pollNotificationFeed();
    if (!notificationPollTimer) notificationPollTimer = setInterval(pollNotificationFeed, 2400);
  }

  function startCaretakerForm() {
    var button = document.getElementById("caretaker-add");
    if (!button) return;
    var message = document.getElementById("caretaker-message");

    button.addEventListener("click", function () {
      var payload = {
        name: document.getElementById("caretaker-name").value.trim(),
        email: document.getElementById("caretaker-email").value.trim(),
        password: document.getElementById("caretaker-password").value
      };
      message.textContent = "Creating account…";
      message.className = "settings-message";
      fetchJSON("/api/caretakers/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (data) {
        message.textContent = data.message;
        message.className = "settings-message success";
        document.getElementById("caretaker-name").value = "";
        document.getElementById("caretaker-email").value = "";
        document.getElementById("caretaker-password").value = "";
        showToast("Caretaker added", payload.name + " can now sign in.", "info");
      }).catch(function (error) {
        message.textContent = error.data && error.data.message
          ? error.data.message
          : "Could not create the account. Check the fields and try again.";
        message.className = "settings-message error";
      });
    });
  }

  window.ElderGuard = {
    startDashboardPolling: startDashboardPolling,
    startPatientPage: startPatientPage,
    startSimulationPage: startSimulationPage,
    bindAcknowledgements: bindAcknowledgements,
    initGlobalAlerts: initGlobalAlerts,
    startTelegramSettings: startTelegramSettings,
    startCaretakerForm: startCaretakerForm
  };
})();
