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
            self.postMessage({ type: "stderr", text: (err.message || String(err)) + "\n" });
            self.postMessage({ type: "finished", has_error: true, error: err.message || String(err) });
        }
    }
};
