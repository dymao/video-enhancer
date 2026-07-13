const state = {
  tasks: [],
  selectedTaskIndex: -1,
  selectedTaskIndexes: new Set(),
  running: false,
  outputDir: '',
  currentTaskIndex: -1,
  runningTaskIndexes: [],
  currentTaskStartTime: 0,
  currentProgressPercent: 0,
  timeTimer: null,
  theme: 'system',
  qualityQueryTimer: null,
  qualityQueryId: 0,
  qualityOptionsLoaded: false,
  qualityOptionsUrl: '',
  qualityUserSelected: false,
};

const videoApi = /** @type {any} */ (window).videoEnhancer;
const THEME_STORAGE_KEY = 'video-enhancer-theme';
const systemThemeQuery = window.matchMedia('(prefers-color-scheme: dark)');

const urlInput = document.getElementById('urlInput');
const urlInputMessage = document.getElementById('urlInputMessage');
const qualitySelect = document.getElementById('qualitySelect');
const qualityStatus = document.getElementById('qualityStatus');
const addTaskButton = document.getElementById('addTaskButton');
const taskList = document.getElementById('taskList');
const taskCount = document.getElementById('taskCount');
const removeTaskButton = document.getElementById('removeTaskButton');
const clearTasksButton = document.getElementById('clearTasksButton');
const outputDirInput = document.getElementById('outputDirInput');
const browseOutputButton = document.getElementById('browseOutputButton');
const cookiesInput = document.getElementById('cookiesInput');
const importCookiesButton = document.getElementById('importCookiesButton');
const browseCookiesButton = document.getElementById('browseCookiesButton');
const formatSelect = document.getElementById('formatSelect');
const enhanceCheck = document.getElementById('enhanceCheck');
const startButton = document.getElementById('startButton');
const cancelButton = document.getElementById('cancelButton');
const statusTitle = document.getElementById('statusTitle');
const progressText = document.getElementById('progressText');
const progressBar = document.getElementById('progressBar');
const currentMessage = document.getElementById('currentMessage');
const timeEstimate = document.getElementById('timeEstimate');
const logOutput = document.getElementById('logOutput');
const clearLogButton = document.getElementById('clearLogButton');
const themeSelect = document.getElementById('themeSelect');

function getEffectiveTheme(theme) {
  if (theme === 'dark' || theme === 'light') return theme;
  return systemThemeQuery.matches ? 'dark' : 'light';
}

function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = getEffectiveTheme(theme);
  if (themeSelect) themeSelect.value = theme;
  localStorage.setItem(THEME_STORAGE_KEY, theme);
}

function initTheme() {
  const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
  const theme = ['system', 'light', 'dark'].includes(savedTheme) ? savedTheme : 'system';
  applyTheme(theme);
}

function appendLog(message) {
  const time = new Date().toLocaleTimeString();
  logOutput.textContent += `[${time}] ${message}\n`;
  logOutput.scrollTop = logOutput.scrollHeight;
}

function showUrlInputMessage(message) {
  urlInputMessage.textContent = message;
  urlInputMessage.hidden = false;
  urlInput.classList.add('input-error');
}

function clearUrlInputMessage() {
  urlInputMessage.textContent = '';
  urlInputMessage.hidden = true;
  urlInput.classList.remove('input-error');
}

function setRunning(running) {
  state.running = running;
  addTaskButton.disabled = running;
  qualitySelect.disabled = running;
  browseOutputButton.disabled = running;
  importCookiesButton.disabled = running;
  browseCookiesButton.disabled = running;
  cookiesInput.disabled = running;
  formatSelect.disabled = running;
  enhanceCheck.disabled = running;
  cancelButton.disabled = !running;
  updateTaskActionButtons();
}

function updateTaskCount() {
  taskCount.textContent = `${state.tasks.length} 个任务`;
}

function updateTaskActionButtons() {
  const hasTasks = state.tasks.length > 0;
  removeTaskButton.disabled = !hasTasks;
  clearTasksButton.disabled = !hasTasks || state.running;
  startButton.disabled = !hasTasks || state.running;
}

function setOutputDir(directory) {
  state.outputDir = directory;
  outputDirInput.value = directory;
  outputDirInput.title = directory;
}

function formatDuration(totalSeconds) {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return '--:--';
  const seconds = Math.floor(totalSeconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const restSeconds = seconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(restSeconds).padStart(2, '0')}`;
  }
  return `${String(minutes).padStart(2, '0')}:${String(restSeconds).padStart(2, '0')}`;
}

function updateTimeEstimate() {
  if (!state.currentTaskStartTime) {
    timeEstimate.textContent = '当前步骤 已耗时: --:-- | 预估剩余: --:--';
    return;
  }

  const elapsedSeconds = (Date.now() - state.currentTaskStartTime) / 1000;
  const percent = Math.max(0, Math.min(100, Number(state.currentProgressPercent) || 0));
  const remainingSeconds = percent > 0 && percent < 100
    ? elapsedSeconds * ((100 - percent) / percent)
    : NaN;
  timeEstimate.textContent = `当前步骤 已耗时: ${formatDuration(elapsedSeconds)} | 预估剩余: ${formatDuration(remainingSeconds)}`;
}

function startTimeTimer() {
  if (state.timeTimer) clearInterval(state.timeTimer);
  state.currentTaskStartTime = Date.now();
  state.currentProgressPercent = 0;
  updateTimeEstimate();
  state.timeTimer = setInterval(updateTimeEstimate, 1000);
}

function stopTimeTimer(reset = false) {
  if (state.timeTimer) {
    clearInterval(state.timeTimer);
    state.timeTimer = null;
  }
  if (reset) {
    state.currentTaskStartTime = 0;
    state.currentProgressPercent = 0;
  }
  updateTimeEstimate();
}

function getSelectedQuality() {
  const selectedOption = qualitySelect.options[qualitySelect.selectedIndex];
  return {
    qualityFormat: qualitySelect.value,
    qualityLabel: selectedOption?.textContent || '自动选择最高清',
  };
}

function resetQualityOptions(statusText = '贴入地址后自动查询可选清晰度') {
  qualitySelect.replaceChildren(new Option('自动选择最高清', ''));
  qualitySelect.value = '';
  state.qualityOptionsLoaded = false;
  state.qualityOptionsUrl = '';
  state.qualityUserSelected = false;
  qualityStatus.textContent = statusText;
  qualityStatus.classList.remove('error');
}

function setQualityOptions(url, options) {
  resetQualityOptions(`已查询到 ${options.length} 个清晰度选项，请选择`);
  options.forEach((option) => {
    qualitySelect.append(new Option(option.label, option.value));
  });
  state.qualityOptionsLoaded = true;
  state.qualityOptionsUrl = url;
}

async function queryQualityOptions() {
  const url = normalizeUrl(urlInput.value);
  state.qualityQueryId += 1;
  const queryId = state.qualityQueryId;

  if (!url) {
    resetQualityOptions();
    return false;
  }

  if (!isLikelyVideoUrl(url)) {
    resetQualityOptions('请输入有效 B 站地址后查询清晰度');
    return false;
  }

  qualityStatus.textContent = '正在查询可选清晰度...';
  qualityStatus.classList.remove('error');

  try {
    const result = await videoApi.getQualityOptions({
      url,
      cookiesFile: cookiesInput.value.trim(),
    });
    if (queryId !== state.qualityQueryId) return;

    if (result?.ok && Array.isArray(result.options) && result.options.length > 0) {
      setQualityOptions(url, result.options);
      return true;
    }

    resetQualityOptions(result?.message || '暂未查询到可选清晰度，将使用自动选择最高清');
    qualityStatus.classList.add('error');
    return false;
  } catch (error) {
    if (queryId !== state.qualityQueryId) return;
    resetQualityOptions(`清晰度查询失败：${error.message || error}`);
    qualityStatus.classList.add('error');
    return false;
  }
}

function scheduleQualityQuery() {
  if (state.qualityQueryTimer) clearTimeout(state.qualityQueryTimer);
  state.qualityQueryTimer = setTimeout(queryQualityOptions, 700);
}

function createTask(url) {
  const quality = getSelectedQuality();
  return {
    url,
    qualityFormat: quality.qualityFormat,
    qualityLabel: quality.qualityLabel,
    status: 'pending',
  };
}

function getTaskStatusText(task, index) {
  if (index === state.currentTaskIndex && state.running) return '进行中';
  const statusTextMap = {
    pending: '待处理',
    running: '进行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  };
  return statusTextMap[task.status] || '待处理';
}

function getTaskStatusClass(task, index) {
  if (index === state.currentTaskIndex && state.running) return 'running';
  return task.status || 'pending';
}

function toggleTaskSelection(index) {
  if (state.selectedTaskIndexes.has(index)) {
    state.selectedTaskIndexes.delete(index);
  } else {
    state.selectedTaskIndexes.add(index);
  }
  state.selectedTaskIndex = state.selectedTaskIndexes.has(index) ? index : -1;
  renderTaskList();
}

function remapTaskIndexAfterDelete(oldIndex, deletedIndexes) {
  if (oldIndex < 0 || deletedIndexes.has(oldIndex)) return -1;
  return oldIndex - [...deletedIndexes].filter((index) => index < oldIndex).length;
}

function renderTaskList() {
  taskList.replaceChildren();
  taskList.classList.toggle('scrollable', state.tasks.length > 4);
  state.tasks.forEach((task, index) => {
    const item = document.createElement('li');
    const isSelected = state.selectedTaskIndexes.has(index);
    const isInRunningQueue = state.running && state.runningTaskIndexes.includes(index);
    item.className = isSelected ? 'selected' : '';
    item.addEventListener('click', () => {
      toggleTaskSelection(index);
    });

    const checkbox = document.createElement('input');
    checkbox.className = 'task-checkbox';
    checkbox.type = 'checkbox';
    checkbox.checked = isSelected;
    checkbox.title = isInRunningQueue ? '执行中的任务需要先取消后才能删除' : '选择任务';
    checkbox.addEventListener('click', (event) => {
      event.stopPropagation();
      toggleTaskSelection(index);
    });

    const serial = document.createElement('span');
    serial.className = 'task-serial';
    serial.textContent = String(index + 1);

    const content = document.createElement('div');
    content.className = 'task-content';
    const title = document.createElement('strong');
    title.textContent = '视频任务';
    const url = document.createElement('small');
    url.textContent = task.url;
    const quality = document.createElement('small');
    quality.className = 'task-quality';
    quality.textContent = `清晰度：${task.qualityLabel || '自动选择最高清'}`;
    content.append(title, url, quality);

    const status = document.createElement('span');
    status.className = `pill ${getTaskStatusClass(task, index)}`;
    status.textContent = getTaskStatusText(task, index);

    item.append(checkbox, serial, content, status);
    taskList.appendChild(item);
  });
  updateTaskCount();
  updateTaskActionButtons();
}

function normalizeUrl(rawUrl) {
  return rawUrl.trim();
}

function isLikelyVideoUrl(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    return (parsed.protocol === 'http:' || parsed.protocol === 'https:')
      && (host === 'b23.tv' || host.endsWith('.b23.tv') || host === 'bilibili.com' || host.endsWith('.bilibili.com'));
  } catch (_error) {
    return false;
  }
}

async function ensureQualityReadyForTask(url) {
  if (state.qualityOptionsLoaded && state.qualityOptionsUrl === url) return true;

  if (state.qualityQueryTimer) {
    clearTimeout(state.qualityQueryTimer);
    state.qualityQueryTimer = null;
  }

  const originalText = addTaskButton.textContent;
  addTaskButton.disabled = true;
  addTaskButton.textContent = '获取清晰度...';
  qualityStatus.textContent = '添加任务前正在获取视频清晰度...';
  qualityStatus.classList.remove('error');

  try {
    return Boolean(await queryQualityOptions());
  } finally {
    addTaskButton.textContent = originalText;
    addTaskButton.disabled = state.running;
  }
}

async function addTaskFromInput() {
  const url = normalizeUrl(urlInput.value);
  if (!url) {
    showUrlInputMessage('请输入 B 站视频链接后再添加任务');
    urlInput.focus();
    return false;
  }
  clearUrlInputMessage();
  if (!isLikelyVideoUrl(url)) {
    showUrlInputMessage('地址格式不正确，请输入 B 站视频地址或 b23.tv 短链');
    urlInput.focus();
    return false;
  }
  if (state.tasks.some((task) => task.url === url)) {
    showUrlInputMessage('该 URL 已在任务列表中，请勿重复添加');
    urlInput.focus();
    return false;
  }
  if (!await ensureQualityReadyForTask(url)) {
    showUrlInputMessage('未获取到该视频的清晰度信息，请确认地址可访问，或先导入 Cookies 后重试');
    urlInput.focus();
    return false;
  }
  if (!state.qualityUserSelected) {
    showUrlInputMessage('请选择视频清晰度后再添加任务');
    qualitySelect.focus();
    return false;
  }
  state.tasks.push(createTask(url));
  state.selectedTaskIndex = state.tasks.length - 1;
  state.selectedTaskIndexes.add(state.selectedTaskIndex);
  urlInput.value = '';
  state.qualityQueryId += 1;
  state.qualityOptionsUrl = '';
  clearUrlInputMessage();
  renderTaskList();
  appendLog(`已添加任务：${url}`);
  return true;
}

function removeSelectedTask() {
  const selectedIndexes = [...state.selectedTaskIndexes].sort((left, right) => left - right);
  if (selectedIndexes.length === 0) {
    window.alert('请先选择要删除的任务');
    appendLog('请先选择要删除的任务');
    return;
  }

  const runningSelected = selectedIndexes.some((index) => state.runningTaskIndexes.includes(index)
    || index === state.currentTaskIndex
    || state.tasks[index]?.status === 'running');
  if (runningSelected) {
    window.alert('选中的任务正在执行或已进入本次执行队列，请先取消任务后才能删除');
    appendLog('选中的任务正在执行或已进入本次执行队列，请先取消任务后才能删除');
    return;
  }

  const deletedIndexes = new Set(selectedIndexes);
  const removedTasks = selectedIndexes.map((index) => state.tasks[index]).filter(Boolean);
  state.tasks = state.tasks.filter((_task, index) => !deletedIndexes.has(index));
  state.currentTaskIndex = remapTaskIndexAfterDelete(state.currentTaskIndex, deletedIndexes);
  state.runningTaskIndexes = state.runningTaskIndexes
    .map((index) => remapTaskIndexAfterDelete(index, deletedIndexes))
    .filter((index) => index >= 0);
  state.selectedTaskIndexes.clear();
  state.selectedTaskIndex = -1;
  appendLog(`已删除 ${removedTasks.length} 个任务`);
  renderTaskList();
}

function clearTasks() {
  state.tasks = [];
  state.selectedTaskIndex = -1;
  state.selectedTaskIndexes.clear();
  state.currentTaskIndex = -1;
  state.runningTaskIndexes = [];
  renderTaskList();
  appendLog('已清空任务列表');
}

function updateSteps(stepIndex = -1, status = 'pending') {
  document.querySelectorAll('.step').forEach((stepElement) => {
    const index = Number(stepElement.dataset.step);
    stepElement.classList.remove('running', 'completed');
    if (index < stepIndex || (index === stepIndex && status === 'completed')) {
      stepElement.classList.add('completed');
      stepElement.querySelector('span').textContent = '✓';
    } else if (index === stepIndex && status === 'running') {
      stepElement.classList.add('running');
      stepElement.querySelector('span').textContent = String(index + 1);
    } else {
      stepElement.querySelector('span').textContent = String(index + 1);
    }
  });
}

function setProgress(percent, message) {
  const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
  state.currentProgressPercent = safePercent;
  progressBar.style.width = `${safePercent}%`;
  progressText.textContent = `${safePercent.toFixed(2)}%`;
  if (message) {
    currentMessage.textContent = message;
  }
  updateTimeEstimate();
}

async function startProcessing() {
  if (urlInput.value.trim() && !await addTaskFromInput()) return;
  const selectedIndexes = [...state.selectedTaskIndexes].sort((left, right) => left - right);
  const hasSelectedTasks = selectedIndexes.length > 0;
  const sourceTaskEntries = hasSelectedTasks
    ? selectedIndexes.map((index) => ({ task: state.tasks[index], index })).filter(({ task }) => task)
    : state.tasks.map((task, index) => ({ task, index }));

  if (!hasSelectedTasks && state.tasks.length > 0) {
    window.alert('未选择任务，将默认处理任务列表中的全部待处理任务。');
  }

  const pendingTaskEntries = sourceTaskEntries
    .filter(({ task }) => task.status === 'pending');

  if (pendingTaskEntries.length === 0) {
    appendLog(state.tasks.length === 0
      ? '请先添加至少一个 B 站视频任务'
      : hasSelectedTasks
        ? '选中的任务没有待处理的新任务，已完成/失败/已取消的任务不会重复执行'
        : '没有待处理的新任务，已完成/失败/已取消的任务不会重复执行');
    return;
  }

  setRunning(true);
  state.currentTaskIndex = -1;
  state.runningTaskIndexes = pendingTaskEntries.map(({ index }) => index);
  renderTaskList();
  updateSteps();
  setProgress(0, '任务启动中...');
  statusTitle.textContent = `任务状态：共有 ${pendingTaskEntries.length} 个待处理任务，准备开始`;
  appendLog(`开始批量处理，共 ${pendingTaskEntries.length} 个待处理任务`);

  const result = await videoApi.startWorker({
    tasks: pendingTaskEntries.map(({ task }) => ({
      url: task.url,
      qualityFormat: task.qualityFormat || '',
    })),
    outputDir: outputDirInput.value,
    cookiesFile: cookiesInput.value.trim(),
    outputFormat: formatSelect.value,
    needEnhance: enhanceCheck.checked,
  });

  if (!result.ok) {
    appendLog(result.message || '任务启动失败');
    state.runningTaskIndexes = [];
    setRunning(false);
  }
}

async function cancelProcessing() {
  appendLog('正在取消任务...');
  await videoApi.cancelWorker();
}

function handleWorkerEvent(event) {
  if (!event || !event.type) return;

  switch (event.type) {
    case 'batch-start':
      statusTitle.textContent = `任务状态：共有 ${event.total} 个任务，开始处理`;
      break;
    case 'task-start':
      state.currentTaskIndex = state.runningTaskIndexes[event.index] ?? event.index;
      if (state.tasks[state.currentTaskIndex]) {
        state.tasks[state.currentTaskIndex].status = 'running';
      }
      statusTitle.textContent = `任务状态：第 ${event.index + 1}/${event.total} 个任务进行中`;
      startTimeTimer();
      renderTaskList();
      updateSteps();
      setProgress(0, `开始处理：${event.url}`);
      appendLog(`开始处理任务 ${event.index + 1}/${event.total}: ${event.url}`);
      break;
    case 'step':
      updateSteps(event.step, event.status);
      break;
    case 'progress':
      setProgress(event.percentage, event.message);
      appendLog(event.message);
      break;
    case 'enhance-check':
      enhanceCheck.checked = Boolean(event.checked);
      break;
    case 'finished':
      setProgress(100, event.message);
      appendLog(event.message);
      break;
    case 'error':
      appendLog(`错误：${event.message}`);
      currentMessage.textContent = event.message;
      break;
    case 'task-finished':
      {
        const taskIndex = state.runningTaskIndexes[event.index] ?? state.currentTaskIndex;
        if (state.tasks[taskIndex]) {
          state.tasks[taskIndex].status = event.cancelled
            ? 'cancelled'
            : (event.success ? 'completed' : 'failed');
        }
        renderTaskList();
      }
      stopTimeTimer();
      appendLog(event.success ? '当前任务处理完成' : '当前任务处理失败或已取消');
      break;
    case 'batch-finished':
      if (event.cancelled) {
        state.runningTaskIndexes.forEach((taskIndex) => {
          const task = state.tasks[taskIndex];
          if (task && (task.status === 'pending' || task.status === 'running')) {
            task.status = 'cancelled';
          }
        });
        renderTaskList();
      }
      statusTitle.textContent = event.cancelled
        ? `任务状态：已取消，成功 ${event.success} 个，失败 ${event.failed} 个`
        : `任务状态：已完成，成功 ${event.success} 个，失败 ${event.failed} 个`;
      stopTimeTimer(true);
      appendLog(`批量处理结束：成功 ${event.success} 个，失败 ${event.failed} 个`);
      break;
    case 'worker-exit':
      setRunning(false);
      state.currentTaskIndex = -1;
      state.runningTaskIndexes = [];
      stopTimeTimer(true);
      renderTaskList();
      appendLog(`Worker 已退出，退出码：${event.code ?? 'unknown'}`);
      break;
    case 'log':
      appendLog(event.message);
      break;
    default:
      appendLog(JSON.stringify(event));
      break;
  }
}

async function init() {
  initTheme();
  const defaults = await videoApi.getDefaults();
  setOutputDir(defaults.outputDir);
  updateSteps();
  renderTaskList();
  videoApi.onWorkerEvent(handleWorkerEvent);
}

addTaskButton.addEventListener('click', () => {
  addTaskFromInput();
});
urlInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    addTaskFromInput();
  }
});
urlInput.addEventListener('input', () => {
  if (urlInput.value.trim()) clearUrlInputMessage();
  scheduleQualityQuery();
});
urlInput.addEventListener('paste', () => {
  setTimeout(scheduleQualityQuery, 0);
});
qualitySelect.addEventListener('change', () => {
  state.qualityUserSelected = true;
});
cookiesInput.addEventListener('input', () => {
  if (urlInput.value.trim()) scheduleQualityQuery();
});
cookiesInput.addEventListener('blur', () => {
  if (urlInput.value.trim()) scheduleQualityQuery();
});
removeTaskButton.addEventListener('click', removeSelectedTask);
clearTasksButton.addEventListener('click', clearTasks);
startButton.addEventListener('click', startProcessing);
cancelButton.addEventListener('click', cancelProcessing);
clearLogButton.addEventListener('click', () => {
  logOutput.textContent = '';
});

if (themeSelect) {
  themeSelect.addEventListener('change', () => {
    applyTheme(themeSelect.value);
  });
}

systemThemeQuery.addEventListener('change', () => {
  if (state.theme === 'system') {
    document.documentElement.dataset.theme = getEffectiveTheme('system');
  }
});

browseOutputButton.addEventListener('click', async () => {
  const directory = await videoApi.selectOutputDir();
  if (directory) {
    setOutputDir(directory);
  }
});

browseCookiesButton.addEventListener('click', async () => {
  const filePath = await videoApi.selectCookiesFile();
  if (filePath) {
    cookiesInput.value = filePath;
    if (urlInput.value.trim()) scheduleQualityQuery();
  }
});

importCookiesButton.addEventListener('click', async () => {
  importCookiesButton.disabled = true;
  const originalText = importCookiesButton.textContent;
  importCookiesButton.textContent = '导入中...';

  try {
    const result = await videoApi.importBrowserCookies();
    if (result?.cancelled) return;
    if (result?.ok && result.path) {
      cookiesInput.value = result.path;
      if (urlInput.value.trim()) scheduleQualityQuery();
      appendLog(`已从 ${result.browser} 导入 ${result.count} 条 B 站 cookies`);
      window.alert(`已从 ${result.browser} 导入 ${result.count} 条 B 站 cookies。`);
      return;
    }
    window.alert(result?.message || '自动导入浏览器 Cookies 失败，请手动选择 cookies 文件');
  } catch (error) {
    window.alert(`自动导入浏览器 Cookies 失败：${error.message || error}`);
  } finally {
    importCookiesButton.textContent = originalText;
    importCookiesButton.disabled = state.running;
  }
});

init();
