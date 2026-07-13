const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const projectRoot = path.join(__dirname, '..');
const buildVenvDir = path.join(projectRoot, '.venv-build-worker');
const distDir = path.join(projectRoot, 'dist-python');
const workDir = path.join(projectRoot, 'build', 'python-worker');
const workerName = 'video_enhancer_worker';

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    stdio: 'inherit',
    shell: false,
    ...options,
  });

  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} exited with code ${result.status}`);
  }
}

function commandExists(command) {
  const result = spawnSync(command, ['--version'], {
    stdio: 'ignore',
    shell: false,
  });
  return result.status === 0;
}

function findPython() {
  const candidates = process.platform === 'win32'
    ? ['py', 'python']
    : ['python3', 'python'];
  const python = candidates.find(commandExists);
  if (!python) {
    throw new Error('Python 3 was not found. Please install Python 3.9+ first.');
  }
  return python;
}

function getVenvPython() {
  return process.platform === 'win32'
    ? path.join(buildVenvDir, 'Scripts', 'python.exe')
    : path.join(buildVenvDir, 'bin', 'python');
}

function pyInstallerPathArg(source, target) {
  return `${source}${path.delimiter}${target}`;
}

function findExecutable(command) {
  const lookupCommand = process.platform === 'win32' ? 'where' : 'which';
  const result = spawnSync(lookupCommand, [command], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  });
  if (result.status !== 0) return null;
  return result.stdout.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || null;
}

function addFileIfExists(args, flag, source, target) {
  if (fs.existsSync(source)) {
    args.push(flag, pyInstallerPathArg(source, target));
  }
}

function buildWorker() {
  const python = findPython();
  if (!fs.existsSync(buildVenvDir)) {
    run(python, ['-m', 'venv', buildVenvDir]);
  }

  const venvPython = getVenvPython();
  run(venvPython, ['-m', 'pip', 'install', '--upgrade', 'pip']);
  run(venvPython, ['-m', 'pip', 'install', '-r', path.join(projectRoot, 'requirements.txt'), 'pyinstaller']);

  if (process.platform === 'darwin') {
    run(venvPython, [path.join(projectRoot, 'tools', 'download_realesrgan.py')]);
  }

  fs.rmSync(distDir, { recursive: true, force: true });
  fs.mkdirSync(distDir, { recursive: true });

  const pyInstallerArgs = [
    '-m',
    'PyInstaller',
    '--noconfirm',
    '--clean',
    '--onedir',
    '--name',
    workerName,
    '--distpath',
    distDir,
    '--workpath',
    workDir,
    '--collect-all',
    'you_get',
    '--hidden-import',
    'cv2',
    '--add-data',
    pyInstallerPathArg(path.join(projectRoot, 'resources'), 'resources'),
  ];

  const ffmpegPath = findExecutable('ffmpeg');
  if (ffmpegPath) {
    pyInstallerArgs.push('--add-binary', pyInstallerPathArg(ffmpegPath, 'tools'));
  } else {
    console.warn('Warning: FFmpeg was not found. The packaged app will still need FFmpeg on the target machine.');
  }

  if (process.platform === 'darwin') {
    const realesrganPath = path.join(projectRoot, 'tools', 'realesrgan-ncnn-vulkan');
    if (fs.existsSync(realesrganPath)) fs.chmodSync(realesrganPath, 0o755);
    addFileIfExists(pyInstallerArgs, '--add-binary', realesrganPath, 'tools');
  }

  pyInstallerArgs.push(path.join(projectRoot, 'src', 'video_enhancer.py'));
  run(venvPython, pyInstallerArgs);

  const executableName = process.platform === 'win32' ? `${workerName}.exe` : workerName;
  const workerPath = path.join(distDir, workerName, executableName);
  if (!fs.existsSync(workerPath)) {
    throw new Error(`Worker executable was not created: ${workerPath}`);
  }

  console.log(`Python worker built for ${os.platform()}: ${workerPath}`);
}

buildWorker();
