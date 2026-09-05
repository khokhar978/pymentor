/**
 * Pyodide Web Worker
 * Runs Python in background with clean standard I/O streaming and
 * synchronous Atomics.wait for interactive terminal input.
 */

importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js");

let pyodide = null;
let controlArray = null;
let dataArray = null;

const encoder = new TextEncoder();
const decoder = new TextDecoder();

self.onmessage = async (e) => {
    const msg = e.data;

    if (msg.type === "init") {
        try {
            if (msg.controlBuffer && msg.dataBuffer) {
                controlArray = new Int32Array(msg.controlBuffer);
                dataArray = new Uint8Array(msg.dataBuffer);
            }

            self.postMessage({ type: "status", message: "Loading Python runtime..." });

            // Initialize Pyodide with official standard indexURL and stdout/stderr hooks
            pyodide = await loadPyodide({
                indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/",
                stdout: (text) => {
                    self.postMessage({ type: "stdout", text: text + "\n" });
                },
                stderr: (text) => {
                    self.postMessage({ type: "stderr", text: text + "\n" });
                }
            });

            // Helper to immediately send partial/prompt text to terminal without newline
            self.sendPrompt = (text) => {
                self.postMessage({ type: "stdout", text: text });
            };

            // Synchronous input bridge called from Python
            self.getUserInputSync = (promptText) => {
                if (!controlArray || !dataArray) {
                    return "";
                }

                // Notify main thread to spawn inline terminal input
                self.postMessage({ type: "await_input", prompt: promptText });

                // Set state to WAITING_FOR_INPUT (1)
                Atomics.store(controlArray, 0, 1);

                // Pause worker synchronously until main thread notifies
                Atomics.wait(controlArray, 0, 1);

                // Read input bytes written by main thread
                const len = Atomics.load(controlArray, 1);
                const inputBytes = dataArray.slice(0, len);
                const resultStr = decoder.decode(inputBytes);

                // Reset state to IDLE (0)
                Atomics.store(controlArray, 0, 0);

                return resultStr;
            };

            // Hook builtins.input in Python
            await pyodide.runPythonAsync(`
import builtins
import js

def _interactive_input(prompt=""):
    if prompt:
        js.sendPrompt(str(prompt))
    val = js.getUserInputSync(str(prompt))
    if val is None:
        return ""
    return str(val).rstrip("\\r\\n")

builtins.input = _interactive_input
`);

            self.postMessage({ type: "ready", message: "Ready" });
        } catch (err) {
            console.error("Pyodide worker init error:", err);
            self.postMessage({ type: "init_error", error: err.message || String(err) });
        }
    } else if (msg.type === "run") {
        if (!pyodide) {
            self.postMessage({ type: "finished", has_error: true, error: "Python runtime not initialized yet." });
            return;
        }

        try {
            if (controlArray) {
                Atomics.store(controlArray, 0, 0);
            }
            await pyodide.runPythonAsync(msg.code);
            self.postMessage({ type: "finished", has_error: false });
        } catch (err) {
            const cleanErr = formatCleanPythonError(err);
            self.postMessage({ type: "stderr", text: cleanErr + "\n" });
            self.postMessage({ type: "finished", has_error: true, error: cleanErr });
        }
    }
};

/**
 * Sanitizes Pyodide / WebAssembly Python error output.
 * Strips Pyodide internals (_base.py, CodeRunner, eval_code, pyodide.asm.js)
 * and replaces internal <exec> markers with a clean "main.py" filename.
 * Guarantees students only see authentic, standard Python tracebacks.
 */
function formatCleanPythonError(rawError) {
    if (!rawError) return "An error occurred during execution.";
    let text = typeof rawError === "string" ? rawError : (rawError.message || String(rawError));

    // Strip leading "PythonError: " prefix
    text = text.replace(/^PythonError:\s*/, "");

    const lines = text.split(/\r?\n/);
    const cleanedLines = [];
    let skipUntilNextFrame = false;

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];

        // Retain standard traceback header
        if (line.includes("Traceback (most recent call last):")) {
            cleanedLines.push("Traceback (most recent call last):");
            skipUntilNextFrame = false;
            continue;
        }

        // Detect Python traceback stack frame: File "...", line X, in ...
        if (/^\s*File\s+"[^"]+",\s+line\s+\d+/.test(line)) {
            // Check if this frame is from Pyodide / Emscripten internal runners
            if (
                line.includes("/pyodide/") ||
                line.includes("_base.py") ||
                line.includes("eval_code") ||
                line.includes("run_async") ||
                line.includes("pyodide.asm.js")
            ) {
                skipUntilNextFrame = true;
                continue;
            } else {
                skipUntilNextFrame = false;
                // Replace internal <exec> or <string> with standard main.py
                const cleanFrame = line
                    .replace(/File\s+"<exec>"/, 'File "main.py"')
                    .replace(/File\s+"<string>"/, 'File "main.py"');
                cleanedLines.push(cleanFrame);
                continue;
            }
        }

        // If skipping an internal frame, skip its associated code / caret lines
        if (skipUntilNextFrame) {
            // If we hit an unindented line, it's the actual Exception line
            if (/^\S/.test(line) && !line.startsWith("Traceback")) {
                skipUntilNextFrame = false;
                cleanedLines.push(line);
            }
            continue;
        }

        // Replace <exec> / <string> anywhere else (such as SyntaxError lines)
        const cleanLine = line
            .replace(/File\s+"<exec>"/, 'File "main.py"')
            .replace(/File\s+"<string>"/, 'File "main.py"');

        // Ignore internal WASM / Emscripten stack traces
        if (
            cleanLine.includes("at pyodide.asm.js") ||
            cleanLine.includes("at Object.runPythonAsync") ||
            cleanLine.includes("at Object.loadPyodide") ||
            cleanLine.includes("at new_page") ||
            cleanLine.includes("emscripten_")
        ) {
            continue;
        }

        cleanedLines.push(cleanLine);
    }

    // Trim trailing and leading blank lines
    while (cleanedLines.length && !cleanedLines[0].trim()) cleanedLines.shift();
    while (cleanedLines.length && !cleanedLines[cleanedLines.length - 1].trim()) cleanedLines.pop();

    const result = cleanedLines.join("\n");
    return result || text;
}
