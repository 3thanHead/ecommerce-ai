import { useState } from "react";
import { stream } from "./api";

export type Step = { name: string; status: "running" | "done"; key?: string };

// Runs one streaming endpoint and exposes its live steps, the model's streamed
// thinking, the final result, and running/error flags. Powers every "show the
// work" panel (scout, drill, automate) with the same shape.
export function useJob<T = any>() {
  const [steps, setSteps] = useState<Step[]>([]);
  const [thinking, setThinking] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<T | null>(null);

  async function run(path: string, body: unknown) {
    setRunning(true);
    setSteps([]);
    setThinking("");
    setError("");
    setResult(null);
    try {
      await stream(path, body, (e) => {
        if (e.type === "step") {
          // A step with a `key` updates in place even as its label changes
          // ("measuring 12/40" -> "…40/40"); otherwise the name is the identity.
          setSteps((prev) => {
            const id = e.key || e.name;
            const i = prev.findIndex((s) => (s.key || s.name) === id);
            const step = { name: e.name, status: e.status, key: e.key };
            if (i >= 0) {
              const next = prev.slice();
              next[i] = step;
              return next;
            }
            return [...prev, step];
          });
        } else if (e.type === "thought") {
          setThinking((t) => t + e.text);
        } else if (e.type === "result") {
          setResult(e.data as T);
        } else if (e.type === "error") {
          setError(e.message);
        }
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  return { steps, thinking, running, error, result, run };
}
