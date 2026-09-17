const vscode = require('vscode');
const fs = require('fs');
const path = require('path');

const STATE_RELATIVE_PATH = ['.runtime', 'computer', 'vscode-state.json'];
const INTERVAL_MS = 5000;
const MAX_VISIBLE_EDITORS = 20;
const MAX_WORKSPACE_FOLDERS = 20;

function relativeToWorkspace(uri) {
  if (!uri || uri.scheme !== 'file') return null;
  const workspaceFolder = vscode.workspace.getWorkspaceFolder(uri);
  if (!workspaceFolder) return uri.fsPath.slice(0, 500);
  return path.relative(workspaceFolder.uri.fsPath, uri.fsPath).split(path.sep).join('/').slice(0, 500);
}

function diagnosticCounts() {
  const result = { errors: 0, warnings: 0, information: 0, hints: 0 };
  for (const [uri, diagnostics] of vscode.languages.getDiagnostics()) {
    if (!uri || !Array.isArray(diagnostics)) continue;
    for (const item of diagnostics) {
      switch (item.severity) {
        case vscode.DiagnosticSeverity.Error: result.errors += 1; break;
        case vscode.DiagnosticSeverity.Warning: result.warnings += 1; break;
        case vscode.DiagnosticSeverity.Information: result.information += 1; break;
        case vscode.DiagnosticSeverity.Hint: result.hints += 1; break;
        default: break;
      }
    }
  }
  return result;
}

function buildState() {
  const folders = (vscode.workspace.workspaceFolders || [])
    .slice(0, MAX_WORKSPACE_FOLDERS)
    .map(folder => folder.name.slice(0, 200));
  const active = vscode.window.activeTextEditor;
  const activeEditor = active ? {
    path: relativeToWorkspace(active.document.uri),
    language: active.document.languageId.slice(0, 100),
    dirty: active.document.isDirty,
    line: active.selection.active.line + 1,
  } : null;
  const visibleEditors = vscode.window.visibleTextEditors
    .slice(0, MAX_VISIBLE_EDITORS)
    .map(editor => ({
      path: relativeToWorkspace(editor.document.uri),
      language: editor.document.languageId.slice(0, 100),
      dirty: editor.document.isDirty,
      line: editor.selection.active.line + 1,
    }))
    .filter(editor => editor.path);

  return {
    schema_version: 'pasi-vscode-readonly-v1',
    captured_at: new Date().toISOString(),
    source: 'pasi-vscode-readonly',
    workspace: {
      name: folders[0] || 'workspace',
      folders,
    },
    active_editor: activeEditor,
    visible_editors: visibleEditors,
    diagnostics: diagnosticCounts(),
  };
}

async function publish() {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || !folders.length) return;
  const root = folders[0].uri.fsPath;
  const statePath = path.join(root, ...STATE_RELATIVE_PATH);
  await fs.promises.mkdir(path.dirname(statePath), { recursive: true });
  const temporary = `${statePath}.tmp`;
  await fs.promises.writeFile(temporary, `${JSON.stringify(buildState(), null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
  await fs.promises.rename(temporary, statePath);
}

function activate(context) {
  let running = false;
  const safePublish = async () => {
    if (running) return;
    running = true;
    try { await publish(); } catch (error) { console.warn('[PASI] VS Code read-only publisher failed:', error); }
    finally { running = false; }
  };

  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(safePublish),
    vscode.window.onDidChangeActiveTextEditor(safePublish),
    vscode.workspace.onDidChangeTextDocument(safePublish),
    vscode.languages.onDidChangeDiagnostics(safePublish),
    { dispose: () => clearInterval(interval) },
  );

  const interval = setInterval(safePublish, INTERVAL_MS);
  safePublish();
}

function deactivate() {}

module.exports = { activate, deactivate, buildState };
