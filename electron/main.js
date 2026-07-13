const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const crypto = require('node:crypto');
const { spawn, spawnSync } = require('node:child_process');
const { app, BrowserWindow, dialog, ipcMain, shell, Tray, Menu } = require('electron');

const PROJECT_ROOT = path.join(__dirname, '..');
const ICON_PATH = path.join(PROJECT_ROOT, 'resources', 'icons', 'logo.png');
const TRAY_ICON_PATH = path.join(PROJECT_ROOT, 'resources', 'icons', 'logo_16x16.png');
const CLOSE_ACTIONS = new Set(['quit', 'tray']);
const PYTHON_WORKER_SCRIPT = path.join(PROJECT_ROOT, 'src', 'video_enhancer.py');
const PACKAGED_WORKER_NAME = process.platform === 'win32'
  ? 'video_enhancer_worker.exe'
  : 'video_enhancer_worker';
const YOU_GET_HELPER_ARG = '--you-get-helper';
const CHROME_EPOCH_OFFSET_SECONDS = 11644473600;

let mainWindow = null;
let workerProcess = null;
let tray = null;
let isQuitting = false;

function getClosePreferencePath() {
  return path.join(app.getPath('userData'), 'close-preferences.json');
}

function loadCloseActionPreference() {
  try {
    const preference = JSON.parse(fs.readFileSync(getClosePreferencePath(), 'utf8'));
    return CLOSE_ACTIONS.has(preference.closeAction) ? preference.closeAction : null;
  } catch (_error) {
    return null;
  }
}

function saveCloseActionPreference(closeAction) {
  if (!CLOSE_ACTIONS.has(closeAction)) return;
  const preferencePath = getClosePreferencePath();
  fs.mkdirSync(path.dirname(preferencePath), { recursive: true });
  fs.writeFileSync(preferencePath, JSON.stringify({ closeAction }, null, 2));
}

function clearCloseActionPreference() {
  fs.rmSync(getClosePreferencePath(), { force: true });
}

function quitApp() {
  isQuitting = true;
  app.quit();
}

function showClosePreferenceMessage(message) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    dialog.showMessageBox(mainWindow, {
      type: 'info',
      title: '关闭行为',
      message,
      noLink: true,
    });
  }
}

function refreshClosePreferenceMenus() {
  updateAppMenu();
  updateTrayMenu();
}

function setCloseActionPreference(closeAction) {
  saveCloseActionPreference(closeAction);
  refreshClosePreferenceMenus();
  showClosePreferenceMessage(closeAction === 'tray'
    ? '已设置为关闭窗口时默认最小化到托盘。'
    : '已设置为关闭窗口时默认退出程序。');
}

function resetCloseActionPreference() {
  clearCloseActionPreference();
  refreshClosePreferenceMenus();
  showClosePreferenceMessage('已恢复为关闭窗口时弹框询问。');
}

function createClosePreferenceMenuItems() {
  const closeAction = loadCloseActionPreference();
  return [
    {
      label: `关闭窗口时弹框询问${closeAction ? '' : ' ✓'}`,
      click: resetCloseActionPreference,
    },
    {
      label: `关闭时默认最小化到托盘${closeAction === 'tray' ? ' ✓' : ''}`,
      click: () => setCloseActionPreference('tray'),
    },
    {
      label: `关闭时默认退出程序${closeAction === 'quit' ? ' ✓' : ''}`,
      click: () => setCloseActionPreference('quit'),
    },
  ];
}

function createEditMenu() {
  return {
    label: '编辑',
    submenu: [
      { role: 'undo', label: '撤销' },
      { role: 'redo', label: '重做' },
      { type: 'separator' },
      { role: 'cut', label: '剪切' },
      { role: 'copy', label: '复制' },
      { role: 'paste', label: '粘贴' },
      { role: 'pasteAndMatchStyle', label: '粘贴并匹配样式' },
      { role: 'delete', label: '删除' },
      { type: 'separator' },
      { role: 'selectAll', label: '全选' },
    ],
  };
}

function updateAppMenu() {
  const closePreferenceItems = createClosePreferenceMenuItems();
  const template = process.platform === 'darwin'
    ? [
      {
        label: app.name,
        submenu: [
          { role: 'about', label: `关于 ${app.name}` },
          { type: 'separator' },
          ...closePreferenceItems,
          { type: 'separator' },
          { role: 'quit', label: `退出 ${app.name}` },
        ],
      },
      createEditMenu(),
      {
        label: '窗口',
        submenu: [
          { role: 'minimize', label: '最小化' },
          { role: 'close', label: '关闭窗口' },
        ],
      },
    ]
    : [
      {
        label: '文件',
        submenu: [
          { label: '显示主窗口', click: showMainWindow },
          { type: 'separator' },
          ...closePreferenceItems,
          { type: 'separator' },
          { label: '退出程序', click: quitApp },
        ],
      },
      createEditMenu(),
    ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow();
    return;
  }

  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function createTray() {
  if (tray) return;

  tray = new Tray(fs.existsSync(TRAY_ICON_PATH) ? TRAY_ICON_PATH : ICON_PATH);
  tray.setToolTip('Video Enhancer');
  updateTrayMenu();
  tray.on('click', showMainWindow);
}

function updateTrayMenu() {
  if (!tray) return;

  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '显示主窗口', click: showMainWindow },
    { type: 'separator' },
    ...createClosePreferenceMenuItems(),
    { type: 'separator' },
    {
      label: '退出程序',
      click: quitApp,
    },
  ]));
}

function minimizeToTray() {
  createTray();
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.hide();
  }
}

async function confirmCloseAction() {
  const result = await dialog.showMessageBox(mainWindow, {
    type: 'question',
    title: '关闭程序',
    message: '关闭窗口时要执行什么操作？',
    detail: '可以退出程序，也可以最小化到托盘继续保留后台运行。',
    buttons: ['最小化到托盘', '退出程序', '取消'],
    defaultId: 0,
    cancelId: 2,
    checkboxLabel: '记住我的选择，下次默认执行（可在菜单中改回弹框询问）',
    checkboxChecked: false,
    noLink: true,
  });

  if (result.response === 2) return null;

  const closeAction = result.response === 1 ? 'quit' : 'tray';
  if (result.checkboxChecked) {
    saveCloseActionPreference(closeAction);
    refreshClosePreferenceMenus();
  }
  return closeAction;
}

async function handleWindowClose(event) {
  if (isQuitting) return;

  event.preventDefault();

  const closeAction = loadCloseActionPreference() || await confirmCloseAction();
  if (closeAction === 'quit') {
    isQuitting = true;
    app.quit();
    return;
  }

  if (closeAction === 'tray') {
    minimizeToTray();
  }
}

function getPythonPath() {
  const venvPython = path.join(PROJECT_ROOT, '.venv', 'bin', 'python');
  const windowsPython = path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');
  const preferredPython = process.platform === 'win32'
    ? path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')
    : venvPython;
  if (fs.existsSync(preferredPython)) return preferredPython;
  if (process.platform === 'win32' && fs.existsSync(windowsPython)) return windowsPython;
  return process.platform === 'win32' ? 'python' : 'python3';
}

function getPackagedWorkerPath() {
  return path.join(process.resourcesPath, 'python-worker', PACKAGED_WORKER_NAME);
}

function getWorkerLaunchConfig() {
  const packagedWorker = getPackagedWorkerPath();
  if (app.isPackaged && fs.existsSync(packagedWorker)) {
    return {
      command: packagedWorker,
      args: ['--electron-worker'],
      cwd: app.getPath('userData'),
    };
  }

  return {
    command: getPythonPath(),
    args: [PYTHON_WORKER_SCRIPT, '--electron-worker'],
    cwd: PROJECT_ROOT,
  };
}

function getYouGetLaunchConfig(args) {
  const packagedWorker = getPackagedWorkerPath();
  if (app.isPackaged && fs.existsSync(packagedWorker)) {
    return {
      command: packagedWorker,
      args: [YOU_GET_HELPER_ARG, ...args],
      cwd: app.getPath('userData'),
    };
  }

  return {
    command: getPythonPath(),
    args: ['-m', 'you_get', ...args],
    cwd: PROJECT_ROOT,
  };
}

function runYouGet(args, timeoutMs = 30000) {
  return new Promise((resolve) => {
    const launchConfig = getYouGetLaunchConfig(args);
    const processHandle = spawn(launchConfig.command, launchConfig.args, {
      cwd: launchConfig.cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      env: {
        ...process.env,
        PATH: `/opt/homebrew/bin:/usr/local/bin:${process.env.PATH || ''}`,
        PYTHONUNBUFFERED: '1',
      },
    });

    let stdout = '';
    let stderr = '';
    let didTimeout = false;
    const timeout = setTimeout(() => {
      didTimeout = true;
      processHandle.kill('SIGTERM');
    }, timeoutMs);

    processHandle.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    processHandle.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    processHandle.on('error', (error) => {
      clearTimeout(timeout);
      resolve({ ok: false, stdout, stderr: error.message });
    });
    processHandle.on('close', (code) => {
      clearTimeout(timeout);
      resolve({ ok: code === 0 && !didTimeout, code, stdout, stderr, didTimeout });
    });
  });
}

function createYouGetArgs(url, cookiesFile, modeArgs) {
  const args = [...modeArgs];
  if (cookiesFile && fs.existsSync(cookiesFile)) {
    args.push('--cookies', cookiesFile);
  }
  args.push(url);
  return args;
}

function extractJsonObject(output) {
  const start = output.indexOf('{');
  const end = output.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  try {
    return JSON.parse(output.slice(start, end + 1));
  } catch (_error) {
    return null;
  }
}

function formatBytes(bytes) {
  const size = Number(bytes);
  if (!Number.isFinite(size) || size <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = size;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)}${units[unitIndex]}`;
}

const QUALITY_LABEL_MAP = {
  '4k': '4K超清',
  '2160': '4K超清',
  '1440': '2K超清',
  '1080p60': '1080P60高帧率',
  '1080+': '1080P高码率',
  '1080': '1080高清',
  '720': '720准高清',
  '480': '480标清',
  '360': '360流畅',
};

function getSimpleQualityLabel(rawQuality) {
  if (!rawQuality) return '';
  const test = rawQuality.replace(/\s+/g, '').toLowerCase();
  for (const [key, label] of Object.entries(QUALITY_LABEL_MAP)) {
    if (test.includes(key)) return label;
  }
  return rawQuality.trim();
}

function normalizeQualityOptions(options) {
  const seenValues = new Set();
  const seenLabels = new Set();
  return options
    .filter((option) => option && option.value && !seenValues.has(option.value) && seenValues.add(option.value))
    .filter((option) => {
      const label = option.label || option.value;
      if (seenLabels.has(label)) return false;
      seenLabels.add(label);
      return true;
    })
    .map((option) => ({
      value: option.value,
      label: option.label || option.value,
    }));
}

function parseQualityOptionsFromJson(output) {
  const info = extractJsonObject(output);
  const streams = info?.streams;
  if (!streams || typeof streams !== 'object') return [];

  return normalizeQualityOptions(Object.entries(streams).map(([streamId, stream]) => {
    const rawQuality = stream.quality || stream.profile || stream.video_profile || '';
    const simpleLabel = getSimpleQualityLabel(rawQuality);
    return {
      value: streamId,
      label: simpleLabel || streamId,
    };
  }));
}

function parseQualityOptionsFromInfo(output) {
  const options = [];
  let current = null;

  output.split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trim();
    const bracketMatch = line.match(/^\[\s*([^\]]+?)\s*\]/);
    if (bracketMatch) {
      if (current?.value) options.push(current);
      current = { value: bracketMatch[1].trim() };
      return;
    }

    const formatMatch = line.match(/^-\s*format:\s*(.+)$/i);
    if (formatMatch) {
      if (!current) current = {};
      current.value = formatMatch[1].trim();
      return;
    }

    const qualityMatch = line.match(/^-\s*quality:\s*(.+)$/i);
    if (qualityMatch && current) {
      current.quality = qualityMatch[1].trim();
      return;
    }

    const containerMatch = line.match(/^-\s*container:\s*(.+)$/i);
    if (containerMatch && current) {
      current.container = containerMatch[1].trim().toUpperCase();
      return;
    }

    const sizeMatch = line.match(/^-\s*size:\s*(.+)$/i);
    if (sizeMatch && current) {
      current.size = sizeMatch[1].trim();
    }
  });

  if (current?.value) options.push(current);
  return normalizeQualityOptions(options.map((option) => {
    const simpleLabel = getSimpleQualityLabel(option.quality);
    return {
      value: option.value,
      label: simpleLabel || option.value,
    };
  }));
}

async function getQualityOptions(url, cookiesFile) {
  if (!url || !/^https?:\/\//i.test(url)) {
    return { ok: false, message: '请输入有效的视频地址' };
  }

  let jsonResult = null;
  let infoResult = null;

  if (!cookiesFile || !fs.existsSync(cookiesFile)) {
    // 无 cookies 时先用 --info 快速试探
    infoResult = await runYouGet(createYouGetArgs(url, '', ['--info']));
  }

  jsonResult = await runYouGet(createYouGetArgs(url, cookiesFile, ['--json']));
  let options = jsonResult.ok ? parseQualityOptionsFromJson(jsonResult.stdout) : [];

  if (options.length === 0 && !infoResult) {
    infoResult = await runYouGet(createYouGetArgs(url, cookiesFile, ['--info']));
  }
  if (options.length === 0 && infoResult?.ok) {
    options = infoResult.ok ? parseQualityOptionsFromInfo(infoResult.stdout) : [];
  }

  // 兜底扫描：仅在结构化解析未返回结果时执行
  if (options.length === 0 && (jsonResult?.stdout || infoResult?.stdout)) {
    const allOutput = (jsonResult.stdout || '') + ((infoResult && infoResult.stdout) || '');
    const qualityLabelSet = new Set(options.map((o) => o.label));
    // 1) 扫 - quality: xxxP / - quality: 1920x1080 行
    const qualityLineRegex = /-\s*quality:\s*(\d{3,4})\s*p?/gi;
    let match;
    while ((match = qualityLineRegex.exec(allOutput)) !== null) {
      const simpleLabel = getSimpleQualityLabel(match[1]);
      if (simpleLabel && !qualityLabelSet.has(simpleLabel)) {
        qualityLabelSet.add(simpleLabel);
        options.push({ value: match[1].includes('x') ? match[1] : `${match[1]}p`, label: simpleLabel });
      }
    }
    // 2) 扫 数字x数字 宽高格式, 如 1280x720 -> 720
    const sizeRegex = /(\d{3,4})\s*x\s*(\d{3,4})/gi;
    while ((match = sizeRegex.exec(allOutput)) !== null) {
      const height = match[2];
      const simpleLabel = getSimpleQualityLabel(height);
      if (simpleLabel && !qualityLabelSet.has(simpleLabel)) {
        qualityLabelSet.add(simpleLabel);
        options.push({ value: `${height}p`, label: simpleLabel });
      }
    }
    // 3) 扫普通 数字p 兜底
    const digitsRegex = /(\d{3,4})\s*p/gi;
    while ((match = digitsRegex.exec(allOutput)) !== null) {
      const simpleLabel = getSimpleQualityLabel(match[1]);
      if (simpleLabel && !qualityLabelSet.has(simpleLabel)) {
        qualityLabelSet.add(simpleLabel);
        options.push({ value: `${match[1]}p`, label: simpleLabel });
      }
    }
  }

  if (options.length === 0) {
    return {
      ok: false,
      message: '暂未查询到可选清晰度，将使用自动选择最高清',
    };
  }

  return { ok: true, options };
}

function getDefaultOutputDir() {
  if (app.isPackaged) {
    return path.join(app.getPath('downloads'), 'VideoEnhancer');
  }
  return path.join(PROJECT_ROOT, 'output');
}

function getMacBrowserConfigs() {
  return {
    chrome: {
      label: 'Chrome',
      root: path.join(os.homedir(), 'Library', 'Application Support', 'Google', 'Chrome'),
      safeStorageService: 'Chrome Safe Storage',
    },
    edge: {
      label: 'Microsoft Edge',
      root: path.join(os.homedir(), 'Library', 'Application Support', 'Microsoft Edge'),
      safeStorageService: 'Microsoft Edge Safe Storage',
    },
  };
}

function getChromiumProfileDirectories(browserRoot) {
  if (!fs.existsSync(browserRoot)) return [];

  return fs.readdirSync(browserRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && (entry.name === 'Default' || /^Profile \d+$/.test(entry.name)))
    .map((entry) => path.join(browserRoot, entry.name));
}

function getChromiumCookieDatabases(browserRoot) {
  const databasePaths = new Set();
  getChromiumProfileDirectories(browserRoot).forEach((profileDir) => {
    [
      path.join(profileDir, 'Network', 'Cookies'),
      path.join(profileDir, 'Cookies'),
    ].forEach((databasePath) => {
      if (fs.existsSync(databasePath)) databasePaths.add(databasePath);
    });
  });
  return [...databasePaths];
}

function runCommand(command, args) {
  const result = spawnSync(command, args, {
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  });

  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || `${command} 执行失败`).trim());
  }
  return result.stdout;
}

function getMacChromiumCookieKey(safeStorageService) {
  const { execSync } = require('child_process');
  let password;
  try {
    password = execSync(
      `security find-generic-password -w -s '${safeStorageService.replace(/'/g, "'\\''")}'`,
      { encoding: 'utf8', timeout: 30000, stdio: ['ignore', 'pipe', 'pipe'] },
    ).trim();
  } catch (e) {
    throw new Error(`未能从钥匙串读取 ${safeStorageService}：${e.stderr || e.message}`);
  }
  if (!password) throw new Error(`未能从钥匙串读取 ${safeStorageService}`);
  return crypto.pbkdf2Sync(password, 'saltysalt', 1003, 16, 'sha1');
}

function copyCookieDatabase(databasePath) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'video-enhancer-cookies-'));
  const tempDatabasePath = path.join(tempDir, 'Cookies');
  fs.copyFileSync(databasePath, tempDatabasePath);
  return { tempDir, tempDatabasePath };
}

function queryBilibiliCookies(databasePath) {
  const query = `
    SELECT host_key, name, path, value, hex(encrypted_value), expires_utc, is_secure, is_httponly
    FROM cookies
    WHERE host_key LIKE '%bilibili.com' OR host_key LIKE '%b23.tv';
  `;
  const output = runCommand('sqlite3', ['-batch', '-separator', '\t', databasePath, query]);
  return output.split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      const [hostKey, name, cookiePath, value, encryptedHex, expiresUtc, isSecure, isHttpOnly] = line.split('\t');
      return {
        hostKey,
        name,
        path: cookiePath || '/',
        value: value || '',
        encryptedHex: encryptedHex || '',
        expiresUtc: Number(expiresUtc) || 0,
        isSecure: isSecure === '1',
        isHttpOnly: isHttpOnly === '1',
      };
    });
}

function decryptMacChromiumCookie(cookie, key) {
  if (cookie.value) return cookie.value;
  if (!cookie.encryptedHex) return '';

  const encryptedValue = Buffer.from(cookie.encryptedHex, 'hex');
  if (encryptedValue.length === 0) return '';
  if (!encryptedValue.subarray(0, 3).toString().startsWith('v1')) {
    return encryptedValue.toString('utf8');
  }

  const payload = encryptedValue.subarray(3);
  const decipher = crypto.createDecipheriv('aes-128-cbc', key, Buffer.alloc(16, ' '));
  const decrypted = Buffer.concat([decipher.update(payload), decipher.final()]);
  const hostHash = crypto.createHash('sha256').update(cookie.hostKey).digest();
  const valueBuffer = decrypted.length > 32 && decrypted.subarray(0, 32).equals(hostHash)
    ? decrypted.subarray(32)
    : decrypted;
  return valueBuffer.toString('utf8');
}

function chromeTimeToUnixSeconds(chromeTime) {
  if (!chromeTime) return 0;
  return Math.max(0, Math.floor((chromeTime / 1000000) - CHROME_EPOCH_OFFSET_SECONDS));
}

function formatNetscapeCookie(cookie, value) {
  const domain = cookie.isHttpOnly ? `#HttpOnly_${cookie.hostKey}` : cookie.hostKey;
  const includeSubdomains = cookie.hostKey.startsWith('.') ? 'TRUE' : 'FALSE';
  const secure = cookie.isSecure ? 'TRUE' : 'FALSE';
  return [
    domain,
    includeSubdomains,
    cookie.path || '/',
    secure,
    String(chromeTimeToUnixSeconds(cookie.expiresUtc)),
    cookie.name,
    value,
  ].join('\t');
}

async function importMacBrowserCookies() {
  if (process.platform !== 'darwin') {
    return { ok: false, message: '当前自动导入仅支持 macOS 的 Chrome / Edge。' };
  }

  const browserChoice = await dialog.showMessageBox(mainWindow, {
    type: 'question',
    title: '自动导入浏览器 Cookies',
    message: '请选择要导入 B 站 Cookies 的浏览器',
    detail: '将读取本机浏览器中 bilibili.com / b23.tv 的 cookies，并生成本地 cookies.txt 文件，仅用于下载高清视频，不会上传。',
    buttons: ['Chrome', 'Edge', '取消'],
    defaultId: 0,
    cancelId: 2,
    noLink: true,
  });

  if (browserChoice.response === 2) return { ok: false, cancelled: true };

  const browserKey = browserChoice.response === 1 ? 'edge' : 'chrome';
  const browserConfig = getMacBrowserConfigs()[browserKey];
  const cookieDatabases = getChromiumCookieDatabases(browserConfig.root);
  if (cookieDatabases.length === 0) {
    return { ok: false, message: `未找到 ${browserConfig.label} 的 Cookies 数据库，请先登录 B 站后再试。` };
  }

  let key;
  try {
    key = getMacChromiumCookieKey(browserConfig.safeStorageService);
  } catch (error) {
    return {
      ok: false,
      message: `读取 ${browserConfig.label} 钥匙串授权失败：${error.message}`,
    };
  }

  const cookieMap = new Map();
  for (const databasePath of cookieDatabases) {
    const { tempDir, tempDatabasePath } = copyCookieDatabase(databasePath);
    try {
      queryBilibiliCookies(tempDatabasePath).forEach((cookie) => {
        try {
          const value = decryptMacChromiumCookie(cookie, key);
          if (!value) return;
          cookieMap.set(`${cookie.hostKey}\t${cookie.path}\t${cookie.name}`, formatNetscapeCookie(cookie, value));
        } catch (_error) {
          // Skip cookies that cannot be decrypted, but keep importing the rest.
        }
      });
    } finally {
      fs.rmSync(tempDir, { recursive: true, force: true });
    }
  }

  const cookieLines = [...cookieMap.values()];
  if (cookieLines.length === 0) {
    return { ok: false, message: `未从 ${browserConfig.label} 读取到可用的 B 站 Cookies，请确认已在浏览器登录 B 站。` };
  }

  const cookiesDir = path.join(app.getPath('userData'), 'browser-cookies');
  const cookiesPath = path.join(cookiesDir, 'bilibili-cookies.txt');
  fs.mkdirSync(cookiesDir, { recursive: true });
  fs.writeFileSync(cookiesPath, [
    '# Netscape HTTP Cookie File',
    '# Generated by Video Enhancer. Keep this file private.',
    ...cookieLines,
    '',
  ].join('\n'), 'utf8');

  return {
    ok: true,
    path: cookiesPath,
    count: cookieLines.length,
    browser: browserConfig.label,
  };
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1800,
    height: 1200,
    minWidth: 980,
    minHeight: 720,
    title: 'Video Enhancer',
    icon: ICON_PATH,
    backgroundColor: '#0f172a',
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.on('close', handleWindowClose);
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

function sendWorkerEvent(event) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('worker:event', event);
  }
}

function stopWorker() {
  if (!workerProcess) return false;

  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(workerProcess.pid), '/f', '/t']);
    } else {
      process.kill(-workerProcess.pid, 'SIGTERM');
    }
  } catch (_error) {
    try {
      workerProcess.kill('SIGTERM');
    } catch (_innerError) {
      // Ignore kill errors when the process already exited.
    }
  }

  return true;
}

function handleWorkerOutput(chunk) {
  const lines = String(chunk).split(/\r?\n/).filter(Boolean);
  lines.forEach((line) => {
    try {
      sendWorkerEvent(JSON.parse(line));
    } catch (_error) {
      sendWorkerEvent({ type: 'log', message: line });
    }
  });
}

ipcMain.handle('app:get-defaults', () => ({
  projectRoot: PROJECT_ROOT,
  outputDir: getDefaultOutputDir(),
}));

ipcMain.handle('dialog:select-output-dir', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择输出目录',
    properties: ['openDirectory', 'createDirectory'],
    defaultPath: getDefaultOutputDir(),
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('dialog:select-cookies-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择 cookies 文件',
    properties: ['openFile'],
    filters: [
      { name: 'Cookies / Text', extensions: ['txt', 'cookies'] },
      { name: 'All Files', extensions: ['*'] },
    ],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('cookies:import-browser', importMacBrowserCookies);

ipcMain.handle('video:get-quality-options', async (_event, payload = {}) => getQualityOptions(
  String(payload.url || '').trim(),
  String(payload.cookiesFile || '').trim(),
));

ipcMain.handle('shell:open-path', async (_event, targetPath) => {
  if (!targetPath) return false;
  await shell.openPath(targetPath);
  return true;
});

ipcMain.handle('worker:start', async (_event, payload) => {
  if (workerProcess) {
    return { ok: false, message: '已有任务正在运行' };
  }

  const workerConfig = getWorkerLaunchConfig();
  workerProcess = spawn(workerConfig.command, workerConfig.args, {
    cwd: workerConfig.cwd,
    detached: process.platform !== 'win32',
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
    env: {
      ...process.env,
      PATH: `/opt/homebrew/bin:/usr/local/bin:${process.env.PATH || ''}`,
      PYTHONUNBUFFERED: '1',
    },
  });

  workerProcess.stdout.on('data', handleWorkerOutput);
  workerProcess.stderr.on('data', (chunk) => {
    handleWorkerOutput(chunk);
  });
  workerProcess.on('error', (error) => {
    sendWorkerEvent({ type: 'error', message: `启动 Python Worker 失败: ${error.message}` });
  });
  workerProcess.on('close', (code, signal) => {
    sendWorkerEvent({ type: 'worker-exit', code, signal });
    workerProcess = null;
  });

  workerProcess.stdin.write(JSON.stringify(payload));
  workerProcess.stdin.end();
  return { ok: true };
});

ipcMain.handle('worker:cancel', () => ({
  ok: stopWorker(),
}));

app.whenReady().then(() => {
  if (process.platform === 'darwin' && app.dock) {
    app.dock.setIcon(ICON_PATH);
  }

  updateAppMenu();
  createWindow();

  app.on('activate', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      showMainWindow();
    } else if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('before-quit', () => {
  isQuitting = true;
  stopWorker();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
