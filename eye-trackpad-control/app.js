const connectBtn = document.getElementById("connect-btn");
const disconnectBtn = document.getElementById("disconnect-btn");
const centerBtn = document.getElementById("center-btn");
const blinkBtn = document.getElementById("blink-btn");
const squintBtn = document.getElementById("squint-btn");
const autoblinkBtn = document.getElementById("autoblink-btn");
const horizontalPositionSlider = document.getElementById("horizontal-position-slider");
const verticalPositionSlider = document.getElementById("vertical-position-slider");
const lidPositionSlider = document.getElementById("lid-position-slider");
const upperLidPositionSlider = document.getElementById("upper-lid-position-slider");
const lowerLidPositionSlider = document.getElementById("lower-lid-position-slider");
const blinkSpeedSlider = document.getElementById("blink-speed-slider");
const squintUpperAngleSlider = document.getElementById("squint-upper-angle-slider");
const squintLowerAngleSlider = document.getElementById("squint-lower-angle-slider");
const squintDurationSlider = document.getElementById("squint-duration-slider");
const squintSpeedSlider = document.getElementById("squint-speed-slider");
const settingsForm = document.getElementById("settings-form");
const resetSettingsBtn = document.getElementById("reset-settings-btn");
const recordingNameInput = document.getElementById("recording-name-input");
const recordActionBtn = document.getElementById("record-action-btn");
const stopActionBtn = document.getElementById("stop-action-btn");

const trackpad = document.getElementById("trackpad");
const trackpadHandle = document.getElementById("trackpad-handle");

const statusPill = document.getElementById("status-pill");
const serialSupportText = document.getElementById("serial-support-text");
const connectionText = document.getElementById("connection-text");
const deviceText = document.getElementById("device-text");
const autoblinkText = document.getElementById("autoblink-text");
const horizontalPositionValue = document.getElementById("horizontal-position-value");
const verticalPositionValue = document.getElementById("vertical-position-value");
const lidPositionText = document.getElementById("lid-position-text");
const lidPositionValue = document.getElementById("lid-position-value");
const upperLidPositionValue = document.getElementById("upper-lid-position-value");
const lowerLidPositionValue = document.getElementById("lower-lid-position-value");
const blinkSpeedText = document.getElementById("blink-speed-text");
const blinkSpeedValue = document.getElementById("blink-speed-value");
const squintUpperAngleValue = document.getElementById("squint-upper-angle-value");
const squintLowerAngleValue = document.getElementById("squint-lower-angle-value");
const squintDurationValue = document.getElementById("squint-duration-value");
const squintSpeedValue = document.getElementById("squint-speed-value");
const squintStatusText = document.getElementById("squint-status-text");
const servoReadout = document.getElementById("servo-readout");
const settingsStatus = document.getElementById("settings-status");
const recordingStatus = document.getElementById("recording-status");
const recordingsCount = document.getElementById("recordings-count");
const recordingsList = document.getElementById("recordings-list");

const settingsInputs = {
  s1Left: document.getElementById("setting-s1-left"),
  s1Center: document.getElementById("setting-s1-center"),
  s1Right: document.getElementById("setting-s1-right"),
  s2Up: document.getElementById("setting-s2-up"),
  s2Center: document.getElementById("setting-s2-center"),
  s2Down: document.getElementById("setting-s2-down"),
  s3Open: document.getElementById("setting-s3-open"),
  s3Closed: document.getElementById("setting-s3-closed"),
  s4Open: document.getElementById("setting-s4-open"),
  s4Closed: document.getElementById("setting-s4-closed"),
};

const encoder = new TextEncoder();
const SEND_INTERVAL_MS = 1000 / 30;
const BLINK_MIN_MS = 3000;
const BLINK_MAX_MS = 4000;
const BLINK_TRAVEL_FAST_MS = 80;
const BLINK_HOLD_MS = 60;
const BLINK_FRAME_MS = 20;
const NEUTRAL_UNUSED = 90;
const SETTINGS_STORAGE_KEY = "veydalabs-headlink.eyeTrackpad.settings.v1";
const RECORDINGS_STORAGE_KEY = "veydalabs-headlink.eyeTrackpad.recordings.v1";
const ACTION_SETTINGS_STORAGE_KEY = "veydalabs-headlink.eyeTrackpad.actionSettings.v1";
const MAX_RECORDING_MS = 60_000;
const RECORDING_INTERVAL_MS = 50;
const ACTION_LID_LIMITS = {
  lowerMin: 75,
  lowerMax: 110,
  upperMin: 85,
  upperMax: 115,
};

const eyeChannels = {
  horizontal: { servoIndex: 0, label: "Eye Horizontal" },
  vertical: { servoIndex: 1, label: "Eye Vertical" },
  lowerLid: { servoIndex: 2, label: "Lower Lid" },
  upperLid: { servoIndex: 3, label: "Upper Lid" },
};

const DEFAULT_EYE_SETTINGS = {
  horizontal: { left: 85, center: 77.5, right: 70 },
  vertical: { up: 120, center: 105, down: 90 },
  lowerLid: { open: 80, closed: 95 },
  upperLid: { open: 110, closed: 90 },
};

const DEFAULT_ACTION_SETTINGS = {
  squintUpperAngle: 100,
  squintLowerAngle: 89,
  squintHoldMs: 350,
  squintSpeedMs: 180,
};

const servoLabels = [
  eyeChannels.horizontal.label,
  eyeChannels.vertical.label,
  eyeChannels.lowerLid.label,
  eyeChannels.upperLid.label,
  "Unused",
  "Unused",
  "Unused",
  "Unused",
];

const serialState = {
  port: null,
  connected: false,
};

let eyeSettings = cloneEyeSettings(DEFAULT_EYE_SETTINGS);
let recordings = [];
let actionSettings = { ...DEFAULT_ACTION_SETTINGS };

const uiState = {
  xNorm: 0.5,
  yNorm: 0.5,
  currentAngles: [78, 105, 80, 110, 90, 90, 90, 90],
  lastSentAngles: null,
  lastSendAt: 0,
  sendTimerId: 0,
  autoBlinkEnabled: false,
  autoBlinkTimerId: 0,
  isBlinking: false,
  isSquinting: false,
  isRecording: false,
  isPlayingBack: false,
  eyelidActionToken: 0,
  upperLidClosure: 0,
  lowerLidClosure: 0,
  blinkSlowdown: 1,
  recordingName: "",
  recordingStartedAt: 0,
  recordingFrames: [],
  recordingIntervalId: 0,
  playbackTimeoutIds: [],
};

let serialWriteQueue = Promise.resolve();

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

function hasWebSerial() {
  return "serial" in navigator;
}

function rounded(value) {
  return Math.round(value);
}

function cloneEyeSettings(source) {
  return {
    horizontal: { ...source.horizontal },
    vertical: { ...source.vertical },
    lowerLid: { ...source.lowerLid },
    upperLid: { ...source.upperLid },
  };
}

function currentLidAngleBounds() {
  return {
    upperMin: Math.min(eyeSettings.upperLid.open, eyeSettings.upperLid.closed),
    upperMax: Math.max(eyeSettings.upperLid.open, eyeSettings.upperLid.closed),
    lowerMin: Math.min(eyeSettings.lowerLid.open, eyeSettings.lowerLid.closed),
    lowerMax: Math.max(eyeSettings.lowerLid.open, eyeSettings.lowerLid.closed),
  };
}

function sanitizeAngle(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? clamp(parsed, 0, 180) : fallback;
}

function sanitizeEyeSettings(source) {
  const base = cloneEyeSettings(DEFAULT_EYE_SETTINGS);
  if (!source || typeof source !== "object") return base;

  const next = cloneEyeSettings(base);
  next.horizontal.left = sanitizeAngle(source.horizontal?.left, base.horizontal.left);
  next.horizontal.center = sanitizeAngle(source.horizontal?.center, base.horizontal.center);
  next.horizontal.right = sanitizeAngle(source.horizontal?.right, base.horizontal.right);
  next.vertical.up = sanitizeAngle(source.vertical?.up, base.vertical.up);
  next.vertical.center = sanitizeAngle(source.vertical?.center, base.vertical.center);
  next.vertical.down = sanitizeAngle(source.vertical?.down, base.vertical.down);
  next.lowerLid.open = sanitizeAngle(source.lowerLid?.open, base.lowerLid.open);
  next.lowerLid.closed = sanitizeAngle(source.lowerLid?.closed, base.lowerLid.closed);
  next.upperLid.open = sanitizeAngle(source.upperLid?.open, base.upperLid.open);
  next.upperLid.closed = sanitizeAngle(source.upperLid?.closed, base.upperLid.closed);

  next.horizontal.center = clamp(
    next.horizontal.center,
    Math.min(next.horizontal.left, next.horizontal.right),
    Math.max(next.horizontal.left, next.horizontal.right)
  );
  next.vertical.center = clamp(
    next.vertical.center,
    Math.min(next.vertical.up, next.vertical.down),
    Math.max(next.vertical.up, next.vertical.down)
  );

  return next;
}

function loadSavedEyeSettings() {
  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) {
      return { settings: cloneEyeSettings(DEFAULT_EYE_SETTINGS), fromStorage: false };
    }
    return { settings: sanitizeEyeSettings(JSON.parse(raw)), fromStorage: true };
  } catch (error) {
    console.error(error);
    return { settings: cloneEyeSettings(DEFAULT_EYE_SETTINGS), fromStorage: false };
  }
}

function saveEyeSettings() {
  try {
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(eyeSettings));
    return true;
  } catch (error) {
    console.error(error);
    return false;
  }
}

function clearSavedEyeSettings() {
  try {
    window.localStorage.removeItem(SETTINGS_STORAGE_KEY);
  } catch (error) {
    console.error(error);
  }
}

function sanitizeActionSettings(source) {
  const base = { ...DEFAULT_ACTION_SETTINGS };
  const bounds = ACTION_LID_LIMITS;
  if (!source || typeof source !== "object") {
    return {
      squintUpperAngle: clamp(base.squintUpperAngle, bounds.upperMin, bounds.upperMax),
      squintLowerAngle: clamp(base.squintLowerAngle, bounds.lowerMin, bounds.lowerMax),
      squintHoldMs: base.squintHoldMs,
      squintSpeedMs: base.squintSpeedMs,
    };
  }

  return {
    squintUpperAngle: clamp(
      sanitizeAngle(source.squintUpperAngle, base.squintUpperAngle),
      bounds.upperMin,
      bounds.upperMax
    ),
    squintLowerAngle: clamp(
      sanitizeAngle(source.squintLowerAngle, base.squintLowerAngle),
      bounds.lowerMin,
      bounds.lowerMax
    ),
    squintHoldMs: clamp(Math.round(Number(source.squintHoldMs) || base.squintHoldMs), 100, 3000),
    squintSpeedMs: clamp(Math.round(Number(source.squintSpeedMs) || base.squintSpeedMs), 80, 800),
  };
}

function loadSavedActionSettings() {
  try {
    const raw = window.localStorage.getItem(ACTION_SETTINGS_STORAGE_KEY);
    if (!raw) return sanitizeActionSettings(DEFAULT_ACTION_SETTINGS);
    return sanitizeActionSettings(JSON.parse(raw));
  } catch (error) {
    console.error(error);
    return sanitizeActionSettings(DEFAULT_ACTION_SETTINGS);
  }
}

function saveActionSettings() {
  try {
    window.localStorage.setItem(ACTION_SETTINGS_STORAGE_KEY, JSON.stringify(actionSettings));
    return true;
  } catch (error) {
    console.error(error);
    return false;
  }
}

function loadSavedRecordings() {
  try {
    const raw = window.localStorage.getItem(RECORDINGS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => ({
        id: typeof item.id === "string" ? item.id : `action-${Date.now()}`,
        name: typeof item.name === "string" && item.name.trim() ? item.name.trim() : "Untitled Action",
        createdAt: typeof item.createdAt === "string" ? item.createdAt : new Date().toISOString(),
        durationMs: clamp(Number(item.durationMs) || 0, 0, MAX_RECORDING_MS),
        frames: Array.isArray(item.frames)
          ? item.frames
              .filter((frame) => Array.isArray(frame) && frame.length === 6)
              .map((frame) => [
                clamp(Number(frame[0]) || 0, 0, MAX_RECORDING_MS),
                clamp(Number(frame[1]) || 0, 0, 100),
                clamp(Number(frame[2]) || 0, 0, 100),
                clamp(Number(frame[3]) || 0, 0, 100),
                clamp(Number(frame[4]) || 0, 0, 100),
                Array.isArray(frame[5])
                  ? frame[5].slice(0, 4).map((value) => clamp(Number(value) || 0, 0, 180))
                  : [78, 105, 80, 110],
              ])
          : [],
      }))
      .filter((item) => item.frames.length > 0);
  } catch (error) {
    console.error(error);
    return [];
  }
}

function saveRecordings() {
  try {
    window.localStorage.setItem(RECORDINGS_STORAGE_KEY, JSON.stringify(recordings));
    return true;
  } catch (error) {
    console.error(error);
    return false;
  }
}

function formatMultiplier(value) {
  return Number(value).toFixed(2).replace(/\.?0+$/, "");
}

function lerp(start, end, t) {
  return start + (end - start) * t;
}

function interpolateAroundCenter(norm, start, center, end) {
  if (norm <= 0.5) {
    return lerp(start, center, norm / 0.5);
  }
  return lerp(center, end, (norm - 0.5) / 0.5);
}

function easeInOutQuad(t) {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function setStatus(label, tone = "") {
  statusPill.textContent = label;
  statusPill.style.borderColor =
    tone === "active" ? "rgba(126, 224, 212, 0.72)" :
    tone === "error" ? "rgba(255, 154, 143, 0.72)" :
    "rgba(255, 219, 184, 0.34)";
  statusPill.style.color =
    tone === "active" ? "#7ee0d4" :
    tone === "error" ? "#ffb5ae" :
    "#fff3e8";
}

function setSettingsStatus(message, tone = "") {
  settingsStatus.textContent = message;
  settingsStatus.style.color =
    tone === "active" ? "#7ee0d4" :
    tone === "error" ? "#ffb5ae" :
    "#c7b5a4";
}

function setRecordingStatus(message, tone = "") {
  recordingStatus.textContent = message;
  recordingStatus.style.color =
    tone === "active" ? "#7ee0d4" :
    tone === "error" ? "#ffb5ae" :
    "#c7b5a4";
}

function isInteractionLocked() {
  return uiState.isPlayingBack;
}

function isEyelidActionActive() {
  return uiState.isBlinking || uiState.isSquinting;
}

function formatDuration(ms) {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function nextDefaultRecordingName() {
  return `Action ${recordings.length + 1}`;
}

function currentPoseFrame(elapsedMs) {
  return [
    clamp(Math.round(elapsedMs), 0, MAX_RECORDING_MS),
    clamp(Math.round(uiState.xNorm * 100), 0, 100),
    clamp(Math.round(uiState.yNorm * 100), 0, 100),
    clamp(Math.round(uiState.upperLidClosure * 100), 0, 100),
    clamp(Math.round(uiState.lowerLidClosure * 100), 0, 100),
    uiState.currentAngles.slice(0, 4).map((value) => clamp(rounded(value), 0, 180)),
  ];
}

function updateRecorderControls() {
  recordActionBtn.disabled = !serialState.connected || uiState.isRecording || uiState.isPlayingBack;
  stopActionBtn.disabled = !(uiState.isRecording || uiState.isPlayingBack);
  recordingNameInput.disabled = uiState.isRecording || uiState.isPlayingBack;
  recordingsCount.textContent = `${recordings.length} saved`;
}

function renderRecordingsList() {
  recordingsList.innerHTML = "";
  updateRecorderControls();

  if (recordings.length === 0) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "recordings-empty";
    emptyItem.textContent = "No saved actions yet. Record a move, stop, and it will appear here.";
    recordingsList.appendChild(emptyItem);
    return;
  }

  recordings.forEach((recording) => {
    const item = document.createElement("li");
    item.className = "recording-item";

    const head = document.createElement("div");
    head.className = "recording-head";

    const title = document.createElement("h3");
    title.className = "recording-title";
    title.textContent = recording.name;

    const meta = document.createElement("div");
    meta.className = "recording-meta";
    meta.textContent = `${formatDuration(recording.durationMs)} • ${recording.frames.length} frames`;

    head.appendChild(title);
    head.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "recording-actions";

    const playBtn = document.createElement("button");
    playBtn.className = "action-btn action-btn-primary recording-btn";
    playBtn.type = "button";
    playBtn.textContent = "Play";
    playBtn.disabled = !serialState.connected || uiState.isRecording || uiState.isPlayingBack;
    playBtn.addEventListener("click", () => {
      void playRecording(recording.id);
    });

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "action-btn recording-btn";
    deleteBtn.type = "button";
    deleteBtn.textContent = "Delete";
    deleteBtn.disabled = uiState.isRecording || uiState.isPlayingBack;
    deleteBtn.addEventListener("click", () => {
      deleteRecording(recording.id);
    });

    actions.appendChild(playBtn);
    actions.appendChild(deleteBtn);

    item.appendChild(head);
    item.appendChild(actions);
    recordingsList.appendChild(item);
  });
}

function formatDeviceName(info) {
  if (!info) return "Unknown";
  const vendor = typeof info.usbVendorId === "number" ? `0x${info.usbVendorId.toString(16).toUpperCase()}` : "----";
  const product = typeof info.usbProductId === "number" ? `0x${info.usbProductId.toString(16).toUpperCase()}` : "----";
  return `USB ${vendor}:${product}`;
}

function renderServoReadout() {
  servoReadout.innerHTML = "";
  for (let i = 0; i < uiState.currentAngles.length; i += 1) {
    const item = document.createElement("li");
    item.innerHTML = `
      <span class="servo-code">S${i + 1}</span>
      <span>${servoLabels[i]}</span>
      <span class="servo-angle">${uiState.currentAngles[i]}°</span>
    `;
    servoReadout.appendChild(item);
  }
}

function setButtonState() {
  connectBtn.disabled = !hasWebSerial() || serialState.connected;
  disconnectBtn.disabled = !serialState.connected;
  blinkBtn.disabled = !serialState.connected || uiState.isBlinking || uiState.isSquinting || uiState.isPlayingBack;
  squintBtn.disabled = !serialState.connected || uiState.isSquinting || uiState.isPlayingBack;
  autoblinkBtn.disabled = !serialState.connected || uiState.isPlayingBack;
  updateRecorderControls();
}

function updateAutoblinkButton() {
  autoblinkBtn.textContent = `Auto Blink: ${uiState.autoBlinkEnabled ? "On" : "Off"}`;
  autoblinkText.textContent = uiState.autoBlinkEnabled ? "On" : "Off";
}

function updateBlinkSpeedReadout() {
  const displayValue = uiState.blinkSlowdown <= 1
    ? "1x fastest"
    : `${formatMultiplier(uiState.blinkSlowdown)}x slower`;
  blinkSpeedSlider.value = String(uiState.blinkSlowdown);
  blinkSpeedValue.textContent = displayValue;
  blinkSpeedText.textContent = displayValue;
}

function updateSquintSettingsReadout() {
  const sanitized = sanitizeActionSettings(actionSettings);
  actionSettings = sanitized;

  squintUpperAngleSlider.min = String(ACTION_LID_LIMITS.upperMin);
  squintUpperAngleSlider.max = String(ACTION_LID_LIMITS.upperMax);
  squintLowerAngleSlider.min = String(ACTION_LID_LIMITS.lowerMin);
  squintLowerAngleSlider.max = String(ACTION_LID_LIMITS.lowerMax);

  squintUpperAngleSlider.value = String(rounded(actionSettings.squintUpperAngle));
  squintLowerAngleSlider.value = String(rounded(actionSettings.squintLowerAngle));
  squintDurationSlider.value = String(actionSettings.squintHoldMs);
  squintSpeedSlider.value = String(actionSettings.squintSpeedMs);

  squintUpperAngleValue.textContent = `${rounded(actionSettings.squintUpperAngle)}°`;
  squintLowerAngleValue.textContent = `${rounded(actionSettings.squintLowerAngle)}°`;
  squintDurationValue.textContent = `${actionSettings.squintHoldMs} ms`;
  squintSpeedValue.textContent = `${actionSettings.squintSpeedMs} ms`;
  squintStatusText.textContent = `${rounded(actionSettings.squintUpperAngle)}° / ${rounded(actionSettings.squintLowerAngle)}°`;
}

function formatAxisPosition(norm, negativeLabel, positiveLabel) {
  const delta = norm - 0.5;
  const percent = rounded(Math.abs(delta) * 200);
  if (percent === 0) return "Centered";
  return `${percent}% ${delta < 0 ? negativeLabel : positiveLabel}`;
}

function updateAxisPositionReadouts() {
  horizontalPositionSlider.value = String(rounded(uiState.xNorm * 100));
  verticalPositionSlider.value = String(rounded(uiState.yNorm * 100));
  horizontalPositionValue.textContent = formatAxisPosition(uiState.xNorm, "Left", "Right");
  verticalPositionValue.textContent = formatAxisPosition(uiState.yNorm, "Up", "Down");
}

function updateLidPositionReadout() {
  const upperPercent = rounded(uiState.upperLidClosure * 100);
  const lowerPercent = rounded(uiState.lowerLidClosure * 100);
  const averagePercent = rounded((upperPercent + lowerPercent) / 2);
  const displayValue = upperPercent === lowerPercent
    ? `${averagePercent}% closed`
    : `Mixed U${upperPercent}% L${lowerPercent}%`;
  lidPositionSlider.value = String(averagePercent);
  lidPositionValue.textContent = displayValue;
  lidPositionText.textContent = displayValue;
}

function updateIndependentLidReadouts() {
  const upperPercent = rounded(uiState.upperLidClosure * 100);
  const lowerPercent = rounded(uiState.lowerLidClosure * 100);
  upperLidPositionSlider.value = String(upperPercent);
  lowerLidPositionSlider.value = String(lowerPercent);
  upperLidPositionValue.textContent = `${upperPercent}% closed`;
  lowerLidPositionValue.textContent = `${lowerPercent}% closed`;
}

function setTrackpadPosition(xNorm, yNorm) {
  uiState.xNorm = clamp(xNorm, 0, 1);
  uiState.yNorm = clamp(yNorm, 0, 1);
  updateAxisPositionReadouts();

  const rect = trackpad.getBoundingClientRect();
  const x = uiState.xNorm * rect.width;
  const y = uiState.yNorm * rect.height;
  trackpadHandle.style.left = `${x}px`;
  trackpadHandle.style.top = `${y}px`;
}

function formatAngleInput(value) {
  return Number(value).toFixed(1).replace(/\.0$/, "");
}

function populateSettingsForm() {
  settingsInputs.s1Left.value = formatAngleInput(eyeSettings.horizontal.left);
  settingsInputs.s1Center.value = formatAngleInput(eyeSettings.horizontal.center);
  settingsInputs.s1Right.value = formatAngleInput(eyeSettings.horizontal.right);
  settingsInputs.s2Up.value = formatAngleInput(eyeSettings.vertical.up);
  settingsInputs.s2Center.value = formatAngleInput(eyeSettings.vertical.center);
  settingsInputs.s2Down.value = formatAngleInput(eyeSettings.vertical.down);
  settingsInputs.s3Open.value = formatAngleInput(eyeSettings.lowerLid.open);
  settingsInputs.s3Closed.value = formatAngleInput(eyeSettings.lowerLid.closed);
  settingsInputs.s4Open.value = formatAngleInput(eyeSettings.upperLid.open);
  settingsInputs.s4Closed.value = formatAngleInput(eyeSettings.upperLid.closed);
}

function readSettingsForm() {
  return sanitizeEyeSettings({
    horizontal: {
      left: settingsInputs.s1Left.value,
      center: settingsInputs.s1Center.value,
      right: settingsInputs.s1Right.value,
    },
    vertical: {
      up: settingsInputs.s2Up.value,
      center: settingsInputs.s2Center.value,
      down: settingsInputs.s2Down.value,
    },
    lowerLid: {
      open: settingsInputs.s3Open.value,
      closed: settingsInputs.s3Closed.value,
    },
    upperLid: {
      open: settingsInputs.s4Open.value,
      closed: settingsInputs.s4Closed.value,
    },
  });
}

async function applyEyeSettings(nextSettings, statusMessage, persist = false) {
  eyeSettings = sanitizeEyeSettings(nextSettings);
  populateSettingsForm();
  updateSquintSettingsReadout();
  saveActionSettings();
  if (!isEyelidActionActive()) {
    applyTargetAngles();
    await maybeSendCurrentPose(true);
  }
  let didPersist = false;
  if (persist) {
    didPersist = saveEyeSettings();
  }
  setSettingsStatus(
    persist && !didPersist ? "Could not save in browser storage." : statusMessage,
    persist ? (didPersist ? "active" : "error") : ""
  );
}

function applyActionSettings(nextSettings, persist = true) {
  actionSettings = sanitizeActionSettings(nextSettings);
  updateSquintSettingsReadout();
  const didPersist = persist ? saveActionSettings() : true;
  if (!didPersist) {
    setRecordingStatus("Could not save squint settings in browser storage.", "error");
  }
}

function currentRestLidAngles() {
  return {
    lowerLid: lerp(eyeSettings.lowerLid.open, eyeSettings.lowerLid.closed, uiState.lowerLidClosure),
    upperLid: lerp(eyeSettings.upperLid.open, eyeSettings.upperLid.closed, uiState.upperLidClosure),
  };
}

function currentTargetAngles() {
  const horizontal = rounded(interpolateAroundCenter(
    uiState.xNorm,
    eyeSettings.horizontal.left,
    eyeSettings.horizontal.center,
    eyeSettings.horizontal.right
  ));
  const vertical = rounded(interpolateAroundCenter(
    uiState.yNorm,
    eyeSettings.vertical.up,
    eyeSettings.vertical.center,
    eyeSettings.vertical.down
  ));

  const lids = currentRestLidAngles();
  return [
    clamp(horizontal, Math.min(eyeSettings.horizontal.left, eyeSettings.horizontal.right), Math.max(eyeSettings.horizontal.left, eyeSettings.horizontal.right)),
    clamp(vertical, Math.min(eyeSettings.vertical.up, eyeSettings.vertical.down), Math.max(eyeSettings.vertical.up, eyeSettings.vertical.down)),
    rounded(lids.lowerLid),
    rounded(lids.upperLid),
    NEUTRAL_UNUSED,
    NEUTRAL_UNUSED,
    NEUTRAL_UNUSED,
    NEUTRAL_UNUSED,
  ];
}

function poseWithLids(lowerLidAngle, upperLidAngle, lidBounds) {
  const pose = currentTargetAngles();
  pose[eyeChannels.lowerLid.servoIndex] = clamp(
    rounded(lowerLidAngle),
    lidBounds.lowerMin,
    lidBounds.lowerMax
  );
  pose[eyeChannels.upperLid.servoIndex] = clamp(
    rounded(upperLidAngle),
    lidBounds.upperMin,
    lidBounds.upperMax
  );
  return pose;
}

function applyTargetAngles() {
  if (isEyelidActionActive()) return;
  uiState.currentAngles = currentTargetAngles();
  renderServoReadout();
}

function applyRecordedFrame(frame) {
  const xNorm = clamp((Number(frame[1]) || 0) / 100, 0, 1);
  const yNorm = clamp((Number(frame[2]) || 0) / 100, 0, 1);
  uiState.upperLidClosure = clamp((Number(frame[3]) || 0) / 100, 0, 1);
  uiState.lowerLidClosure = clamp((Number(frame[4]) || 0) / 100, 0, 1);
  setTrackpadPosition(xNorm, yNorm);
  updateLidPositionReadout();
  updateIndependentLidReadouts();
  const pose = Array.isArray(frame[5]) ? frame[5].slice(0, 4) : [78, 105, 80, 110];
  uiState.currentAngles = [
    clamp(Number(pose[0]) || 0, 0, 180),
    clamp(Number(pose[1]) || 0, 0, 180),
    clamp(Number(pose[2]) || 0, 0, 180),
    clamp(Number(pose[3]) || 0, 0, 180),
    NEUTRAL_UNUSED,
    NEUTRAL_UNUSED,
    NEUTRAL_UNUSED,
    NEUTRAL_UNUSED,
  ];
  renderServoReadout();
}

function captureRecordingFrame() {
  if (!uiState.isRecording) return;
  const elapsedMs = performance.now() - uiState.recordingStartedAt;
  const frame = currentPoseFrame(elapsedMs);
  const previous = uiState.recordingFrames[uiState.recordingFrames.length - 1];
  if (previous && previous[0] === frame[0]) return;
  uiState.recordingFrames.push(frame);
  setRecordingStatus(
    `Recording "${uiState.recordingName}" • ${formatDuration(frame[0])} / 1:00`,
    "active"
  );
  if (frame[0] >= MAX_RECORDING_MS) {
    void stopRecording(true);
  }
}

async function stopPlayback(reason = "Playback stopped.") {
  if (!uiState.isPlayingBack) return;
  uiState.playbackTimeoutIds.forEach((timeoutId) => window.clearTimeout(timeoutId));
  uiState.playbackTimeoutIds = [];
  uiState.isPlayingBack = false;
  setRecordingStatus(reason);
  setButtonState();
  renderRecordingsList();
  if (serialState.connected) {
    await maybeSendCurrentPose(true);
  }
  scheduleNextAutoBlink();
}

async function playRecording(recordingId) {
  const recording = recordings.find((item) => item.id === recordingId);
  if (!recording || !serialState.connected || uiState.isRecording) return;

  if (uiState.isPlayingBack) {
    await stopPlayback("Previous playback stopped.");
  }

  stopAutoBlinkTimer();
  uiState.isPlayingBack = true;
  setButtonState();
  renderRecordingsList();
  setRecordingStatus(`Playing "${recording.name}"`, "active");

  recording.frames.forEach((frame) => {
    const timeoutId = window.setTimeout(() => {
      applyRecordedFrame(frame);
      void maybeSendCurrentPose(true);
    }, frame[0]);
    uiState.playbackTimeoutIds.push(timeoutId);
  });

  const finalDuration = recording.durationMs || recording.frames[recording.frames.length - 1][0] || 0;
  const finishTimeoutId = window.setTimeout(() => {
    uiState.playbackTimeoutIds = [];
    uiState.isPlayingBack = false;
    setRecordingStatus(`Finished "${recording.name}".`);
    setButtonState();
    renderRecordingsList();
    scheduleNextAutoBlink();
  }, finalDuration + 20);
  uiState.playbackTimeoutIds.push(finishTimeoutId);
}

function deleteRecording(recordingId) {
  recordings = recordings.filter((item) => item.id !== recordingId);
  if (!saveRecordings()) {
    setRecordingStatus("Could not update saved actions in browser storage.", "error");
  } else {
    setRecordingStatus("Deleted saved action.");
  }
  renderRecordingsList();
}

function startRecording() {
  if (!serialState.connected || uiState.isRecording || uiState.isPlayingBack) return;

  const chosenName = recordingNameInput.value.trim() || nextDefaultRecordingName();
  recordingNameInput.value = chosenName;
  uiState.isRecording = true;
  uiState.recordingName = chosenName;
  uiState.recordingStartedAt = performance.now();
  uiState.recordingFrames = [];
  updateRecorderControls();
  renderRecordingsList();
  stopAutoBlinkTimer();
  setRecordingStatus(`Recording "${chosenName}" • 0:00 / 1:00`, "active");
  captureRecordingFrame();
  uiState.recordingIntervalId = window.setInterval(captureRecordingFrame, RECORDING_INTERVAL_MS);
}

async function stopRecording(hitCap = false) {
  if (!uiState.isRecording) return;

  if (uiState.recordingIntervalId) {
    window.clearInterval(uiState.recordingIntervalId);
    uiState.recordingIntervalId = 0;
  }

  captureRecordingFrame();
  uiState.isRecording = false;

  const frames = uiState.recordingFrames.slice();
  const durationMs = frames.length > 0 ? frames[frames.length - 1][0] : 0;
  const savedName = uiState.recordingName || nextDefaultRecordingName();

  if (frames.length > 0) {
    recordings = [
      {
        id: `action-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        name: savedName,
        createdAt: new Date().toISOString(),
        durationMs,
        frames,
      },
      ...recordings,
    ];

    if (saveRecordings()) {
      setRecordingStatus(
        hitCap
          ? `Saved "${savedName}" at the 60 second cap.`
          : `Saved "${savedName}" (${formatDuration(durationMs)}).`,
        "active"
      );
    } else {
      recordings = recordings.slice(1);
      setRecordingStatus("Could not save action in browser storage.", "error");
    }
  } else {
    setRecordingStatus("No action data captured.", "error");
  }

  uiState.recordingFrames = [];
  uiState.recordingName = "";
  recordingNameInput.value = nextDefaultRecordingName();
  updateRecorderControls();
  renderRecordingsList();
  scheduleNextAutoBlink();
}

function queueSerialWrite(line) {
  const task = serialWriteQueue.then(async () => {
    if (!serialState.connected || !serialState.port?.writable) {
      throw new Error("device is not connected");
    }

    const writer = serialState.port.writable.getWriter();
    try {
      await writer.write(encoder.encode(line));
    } finally {
      writer.releaseLock();
    }
  });

  serialWriteQueue = task.catch(() => {});
  return task;
}

async function maybeSendCurrentPose(force = false) {
  if (!serialState.connected) return;

  const now = performance.now();
  if (!force && now - uiState.lastSendAt < SEND_INTERVAL_MS) return;

  const angles = uiState.currentAngles.map((value) => rounded(value));
  if (
    !force &&
    uiState.lastSentAngles &&
    angles.length === uiState.lastSentAngles.length &&
    angles.every((value, index) => value === uiState.lastSentAngles[index])
  ) {
    return;
  }

  uiState.lastSendAt = now;
  await queueSerialWrite(`A ${angles.join(" ")}\n`);
  uiState.lastSentAngles = [...angles];
}

function ensureSendLoop() {
  if (uiState.sendTimerId) return;
  uiState.sendTimerId = window.setInterval(() => {
    void maybeSendCurrentPose(false);
  }, SEND_INTERVAL_MS);
}

function stopSendLoop() {
  if (!uiState.sendTimerId) return;
  window.clearInterval(uiState.sendTimerId);
  uiState.sendTimerId = 0;
}

function updateTargetFromPointer(clientX, clientY) {
  if (isInteractionLocked()) return;
  const rect = trackpad.getBoundingClientRect();
  const xNorm = clamp((clientX - rect.left) / rect.width, 0, 1);
  const yNorm = clamp((clientY - rect.top) / rect.height, 0, 1);
  setTrackpadPosition(xNorm, yNorm);
  applyTargetAngles();
  void maybeSendCurrentPose(false);
}

function resetToCenter() {
  if (isInteractionLocked()) return;
  setTrackpadPosition(0.5, 0.5);
  applyTargetAngles();
  void maybeSendCurrentPose(true);
}

function scheduleNextAutoBlink() {
  if (!uiState.autoBlinkEnabled || !serialState.connected) return;
  const delay = BLINK_MIN_MS + Math.random() * (BLINK_MAX_MS - BLINK_MIN_MS);
  uiState.autoBlinkTimerId = window.setTimeout(() => {
    void blinkNow();
  }, delay);
}

function stopAutoBlinkTimer() {
  if (!uiState.autoBlinkTimerId) return;
  window.clearTimeout(uiState.autoBlinkTimerId);
  uiState.autoBlinkTimerId = 0;
}

function currentBlinkTravelMs() {
  return BLINK_TRAVEL_FAST_MS * uiState.blinkSlowdown;
}

function currentSquintTargets() {
  const bounds = ACTION_LID_LIMITS;
  return {
    lower: clamp(actionSettings.squintLowerAngle, bounds.lowerMin, bounds.lowerMax),
    upper: clamp(actionSettings.squintUpperAngle, bounds.upperMin, bounds.upperMax),
  };
}

function currentDisplayedLidAngles() {
  return {
    lowerLid: clamp(
      Number(uiState.currentAngles[eyeChannels.lowerLid.servoIndex]) || 0,
      ACTION_LID_LIMITS.lowerMin,
      ACTION_LID_LIMITS.lowerMax
    ),
    upperLid: clamp(
      Number(uiState.currentAngles[eyeChannels.upperLid.servoIndex]) || 0,
      ACTION_LID_LIMITS.upperMin,
      ACTION_LID_LIMITS.upperMax
    ),
  };
}

function startEyelidAction() {
  uiState.eyelidActionToken += 1;
  return uiState.eyelidActionToken;
}

function isCurrentEyelidAction(token) {
  return token === uiState.eyelidActionToken;
}

async function sleepInterruptible(ms, token) {
  if (ms <= 0) return isCurrentEyelidAction(token);
  const deadline = performance.now() + ms;
  while (serialState.connected && performance.now() < deadline) {
    if (!isCurrentEyelidAction(token)) return false;
    await sleep(Math.min(BLINK_FRAME_MS, Math.max(0, deadline - performance.now())));
  }
  return serialState.connected && isCurrentEyelidAction(token);
}

async function animateBlinkLids(startLower, startUpper, endLower, endUpper, durationMs, token, lidBounds) {
  if (!serialState.connected) return;

  const startedAt = performance.now();
  while (serialState.connected) {
    if (!isCurrentEyelidAction(token)) return false;

    const elapsed = performance.now() - startedAt;
    const linearT = durationMs <= 0 ? 1 : clamp(elapsed / durationMs, 0, 1);
    const easedT = easeInOutQuad(linearT);

    uiState.currentAngles = poseWithLids(
      lerp(startLower, endLower, easedT),
      lerp(startUpper, endUpper, easedT),
      lidBounds
    );
    renderServoReadout();
    await maybeSendCurrentPose(true);

    if (linearT >= 1) return true;
    await sleep(BLINK_FRAME_MS);
  }

  return false;
}

async function blinkNow() {
  if (!serialState.connected || uiState.isSquinting || uiState.isPlayingBack) return;

  stopAutoBlinkTimer();
  uiState.isBlinking = true;
  setButtonState();
  const actionToken = startEyelidAction();

  const restLids = currentRestLidAngles();
  const openLower = restLids.lowerLid;
  const openUpper = restLids.upperLid;
  const closedLower = eyeSettings.lowerLid.closed;
  const closedUpper = eyeSettings.upperLid.closed;
  const travelMs = currentBlinkTravelMs();
  const blinkLidBounds = currentLidAngleBounds();

  try {
    const closedReached = await animateBlinkLids(
      openLower,
      openUpper,
      closedLower,
      closedUpper,
      travelMs,
      actionToken,
      blinkLidBounds
    );
    if (closedReached && await sleepInterruptible(BLINK_HOLD_MS, actionToken)) {
      await animateBlinkLids(
        closedLower,
        closedUpper,
        openLower,
        openUpper,
        travelMs,
        actionToken,
        blinkLidBounds
      );
    }
  } catch (error) {
    console.error(error);
  } finally {
    const actionStillCurrent = isCurrentEyelidAction(actionToken);
    uiState.isBlinking = false;
    if (actionStillCurrent) {
      uiState.currentAngles = currentTargetAngles();
      renderServoReadout();
      if (serialState.connected) {
        await maybeSendCurrentPose(true);
      }
      scheduleNextAutoBlink();
    }
    setButtonState();
  }
}

async function squintNow() {
  if (!serialState.connected || uiState.isSquinting || uiState.isPlayingBack) return;

  stopAutoBlinkTimer();
  if (uiState.isBlinking) {
    startEyelidAction();
    uiState.isBlinking = false;
  }
  uiState.isSquinting = true;
  setButtonState();
  const actionToken = startEyelidAction();

  const startLids = currentDisplayedLidAngles();
  const squintTargets = currentSquintTargets();
  const squintLidBounds = ACTION_LID_LIMITS;

  try {
    const squintReached = await animateBlinkLids(
      startLids.lowerLid,
      startLids.upperLid,
      squintTargets.lower,
      squintTargets.upper,
      actionSettings.squintSpeedMs,
      actionToken,
      squintLidBounds
    );
    if (squintReached && await sleepInterruptible(actionSettings.squintHoldMs, actionToken)) {
      const returnLids = currentRestLidAngles();
      await animateBlinkLids(
        squintTargets.lower,
        squintTargets.upper,
        returnLids.lowerLid,
        returnLids.upperLid,
        actionSettings.squintSpeedMs,
        actionToken,
        squintLidBounds
      );
    }
  } catch (error) {
    console.error(error);
  } finally {
    const actionStillCurrent = isCurrentEyelidAction(actionToken);
    uiState.isSquinting = false;
    if (actionStillCurrent) {
      uiState.currentAngles = currentTargetAngles();
      renderServoReadout();
      if (serialState.connected) {
        await maybeSendCurrentPose(true);
      }
      scheduleNextAutoBlink();
    }
    setButtonState();
  }
}

function toggleAutoBlink() {
  uiState.autoBlinkEnabled = !uiState.autoBlinkEnabled;
  updateAutoblinkButton();
  stopAutoBlinkTimer();
  scheduleNextAutoBlink();
}

async function connectDevice() {
  if (!hasWebSerial()) return;

  try {
    const port = await navigator.serial.requestPort({
      filters: [
        { usbVendorId: 0x2341 },
        { usbVendorId: 0x2A03 },
        { usbVendorId: 0x1A86 },
        { usbVendorId: 0x10C4 },
        { usbVendorId: 0x0403 },
      ],
    });

    await port.open({ baudRate: 115200 });
    serialState.port = port;
    serialState.connected = true;

    const info = port.getInfo?.() ?? {};
    connectionText.textContent = "Connected";
    deviceText.textContent = formatDeviceName(info);
    setStatus("Connected", "active");
    setButtonState();
    ensureSendLoop();
    resetToCenter();
    scheduleNextAutoBlink();
  } catch (error) {
    connectionText.textContent = "Disconnected";
    deviceText.textContent = "None";
    setStatus("Connect Failed", "error");
    console.error(error);
  }
}

async function disconnectDevice() {
  if (uiState.isRecording) {
    await stopRecording(false);
  }
  if (uiState.isPlayingBack) {
    await stopPlayback("Playback stopped on disconnect.");
  }
  stopAutoBlinkTimer();
  stopSendLoop();

  if (serialState.port) {
    try {
      await serialState.port.close();
    } catch (error) {
      console.error(error);
    }
  }

  serialState.port = null;
  serialState.connected = false;
  connectionText.textContent = "Disconnected";
  deviceText.textContent = "None";
  setStatus("Disconnected");
  setButtonState();
}

function initReadout() {
  const loaded = loadSavedEyeSettings();
  eyeSettings = loaded.settings;
  actionSettings = loadSavedActionSettings();
  recordings = loadSavedRecordings();
  serialSupportText.textContent = hasWebSerial() ? "Available" : "Not Available";
  connectionText.textContent = "Disconnected";
  deviceText.textContent = "None";
  updateAutoblinkButton();
  updateLidPositionReadout();
  updateIndependentLidReadouts();
  updateBlinkSpeedReadout();
  updateSquintSettingsReadout();
  populateSettingsForm();
  setTrackpadPosition(0.5, 0.5);
  applyTargetAngles();
  renderServoReadout();
  setButtonState();
  renderRecordingsList();
  setSettingsStatus(
    loaded.fromStorage ? "Loaded saved browser settings." : "Using default browser settings."
  );
  setRecordingStatus("Ready. Max action length: 60 seconds.");
  if (!recordingNameInput.value.trim()) {
    recordingNameInput.value = nextDefaultRecordingName();
  }

  if (!hasWebSerial()) {
    setStatus("Need Chrome/Edge", "error");
  }
}

trackpad.addEventListener("pointerdown", (event) => {
  if (isInteractionLocked()) return;
  trackpad.classList.add("is-dragging");
  trackpad.setPointerCapture(event.pointerId);
  updateTargetFromPointer(event.clientX, event.clientY);
});

trackpad.addEventListener("pointermove", (event) => {
  if (!trackpad.hasPointerCapture(event.pointerId)) return;
  updateTargetFromPointer(event.clientX, event.clientY);
});

function endPointerDrag(event) {
  if (trackpad.hasPointerCapture(event.pointerId)) {
    trackpad.releasePointerCapture(event.pointerId);
  }
  trackpad.classList.remove("is-dragging");
}

trackpad.addEventListener("pointerup", endPointerDrag);
trackpad.addEventListener("pointercancel", endPointerDrag);
trackpad.addEventListener("pointerleave", (event) => {
  if (trackpad.hasPointerCapture(event.pointerId)) return;
  trackpad.classList.remove("is-dragging");
});

connectBtn.addEventListener("click", () => {
  void connectDevice();
});

disconnectBtn.addEventListener("click", () => {
  void disconnectDevice();
});

centerBtn.addEventListener("click", () => {
  resetToCenter();
});

blinkBtn.addEventListener("click", () => {
  void blinkNow();
});

squintBtn.addEventListener("click", () => {
  void squintNow();
});

autoblinkBtn.addEventListener("click", () => {
  toggleAutoBlink();
});

horizontalPositionSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  const nextValue = Number(event.target.value);
  setTrackpadPosition(clamp(nextValue, 0, 100) / 100, uiState.yNorm);
  applyTargetAngles();
  void maybeSendCurrentPose(false);
});

verticalPositionSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  const nextValue = Number(event.target.value);
  setTrackpadPosition(uiState.xNorm, clamp(nextValue, 0, 100) / 100);
  applyTargetAngles();
  void maybeSendCurrentPose(false);
});

lidPositionSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  const nextValue = Number(event.target.value);
  const nextClosure = clamp(nextValue, 0, 100) / 100;
  uiState.upperLidClosure = nextClosure;
  uiState.lowerLidClosure = nextClosure;
  updateLidPositionReadout();
  updateIndependentLidReadouts();
  applyTargetAngles();
  void maybeSendCurrentPose(false);
});

upperLidPositionSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  const nextValue = Number(event.target.value);
  uiState.upperLidClosure = clamp(nextValue, 0, 100) / 100;
  updateIndependentLidReadouts();
  updateLidPositionReadout();
  applyTargetAngles();
  void maybeSendCurrentPose(false);
});

lowerLidPositionSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  const nextValue = Number(event.target.value);
  uiState.lowerLidClosure = clamp(nextValue, 0, 100) / 100;
  updateIndependentLidReadouts();
  updateLidPositionReadout();
  applyTargetAngles();
  void maybeSendCurrentPose(false);
});

blinkSpeedSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  const nextValue = Number(event.target.value);
  uiState.blinkSlowdown = clamp(nextValue, 1, 5);
  updateBlinkSpeedReadout();
});

squintUpperAngleSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  applyActionSettings({
    ...actionSettings,
    squintUpperAngle: Number(event.target.value),
  });
});

squintLowerAngleSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  applyActionSettings({
    ...actionSettings,
    squintLowerAngle: Number(event.target.value),
  });
});

squintDurationSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  applyActionSettings({
    ...actionSettings,
    squintHoldMs: Number(event.target.value),
  });
});

squintSpeedSlider.addEventListener("input", (event) => {
  if (isInteractionLocked()) return;
  applyActionSettings({
    ...actionSettings,
    squintSpeedMs: Number(event.target.value),
  });
});

settingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (isInteractionLocked()) return;
  void applyEyeSettings(
    readSettingsForm(),
    "Saved and applied to live control.",
    true
  );
});

resetSettingsBtn.addEventListener("click", () => {
  if (isInteractionLocked()) return;
  clearSavedEyeSettings();
  void applyEyeSettings(
    DEFAULT_EYE_SETTINGS,
    "Reset to default browser settings.",
    false
  );
});

recordActionBtn.addEventListener("click", () => {
  startRecording();
});

stopActionBtn.addEventListener("click", () => {
  if (uiState.isRecording) {
    void stopRecording(false);
    return;
  }
  if (uiState.isPlayingBack) {
    void stopPlayback("Playback stopped.");
  }
});

window.addEventListener("resize", () => {
  setTrackpadPosition(uiState.xNorm, uiState.yNorm);
});

if (hasWebSerial()) {
  navigator.serial.addEventListener("disconnect", async (event) => {
    if (serialState.port && event.port === serialState.port) {
      await disconnectDevice();
    }
  });
}

window.addEventListener("beforeunload", () => {
  if (uiState.recordingIntervalId) {
    window.clearInterval(uiState.recordingIntervalId);
  }
  uiState.playbackTimeoutIds.forEach((timeoutId) => window.clearTimeout(timeoutId));
  stopAutoBlinkTimer();
  stopSendLoop();
});

initReadout();
