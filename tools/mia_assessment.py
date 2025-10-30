#from google import genai
#import asyncio
import extism
import json
from typing import Dict, Any
from google.adk.tools import LongRunningFunctionTool
#from plugins.mia_plugin import run_mia_plugin  # import from your earlier file

# 1. Define the long running MIA assessment function
def run_mia_assessment(intent_request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handles a TMForum intent forwarded by the orchestrator.
    Example input structure:
        {
            "intentId": "intent-123",
            "parameters": {
                "model": { "path": "/data/model_v2.pt" },
                "shadowData": { "type": "synthetic" }
            }
          }
    """
    try:
        intent_id = intent_request.get("intentId", "unknown")
        params = intent_request.get("parameters", {})
        model_ref = params.get("model", {})
        shadow_ref = params.get("shadowData", {})

        print(f"Received intent: {intent_id}")
        print(f"Model reference: {model_ref}")
        print(f"Shadow dataset reference: {shadow_ref}")

        # Call the plugin runner (from the previous example)
        #report = run_mia_plugin(
        #    intent_id=intent_id,
        #    model_reference=model_ref,
        #    shadow_data_ref=shadow_ref
        #)

        # This is just to check that the extism interaction is working
        url = "https://github.com/extism/plugins/releases/latest/download/count_vowels.wasm"
        manifest = {"wasm": [{"url": url}]}
        plugin = extism.Plugin(manifest)

        wasm_vowel_count = plugin.call(
            "count_vowels",
            "hello world"
        )
        print(wasm_vowel_count)
        # => {"count": 3, "total": 3, "vowels": "aeiouAEIOU"}

        # Simulate computation time (the real MIA would run much longer)
        import time
        time.sleep(2)

        # Dummy MIA logic: generate fake numbers to mimic an assessment
        fake_attack_accuracy = 72.4  # e.g. attacker success rate
        fake_model_accuracy = 91.8   # model’s performance on validation set
        fake_assessment = (
            "vulnerable" if fake_attack_accuracy > 65.0 else "resilient"
        )

        result = {
            "intentId": intent_id,
            "status": "SUCCESS",
            "mia_accuracy": fake_attack_accuracy,
            "model_accuracy": fake_model_accuracy,
            "assessment": fake_assessment,
            "explanation": (
                "Model shows moderate vulnerability to MIAs; "
                "consider regularization or noise injection."
            ),
        }
        
        # Send report back to orchestrator
        return result

    except Exception as e:
        print(f"Error while running MIA plugin:", str(e))
        return {
            "status": "FAILED",
            "error": str(e)
        }

# Example usage for debugging:
if __name__ == "__main__":
    test_request = {
        "intentId": "intent-demo-789",
        "parameters": {
                "model": { "path": "/data/model_v2.pt" },
                "shadowData": { "type": "synthetic" }
            }
    }

    report = run_mia_assessment(test_request)
    print(json.dumps(report, indent=2))
