import asyncio
import os
import sys
from nearai_inference_sdk import InferenceClient
from dotenv import load_dotenv


async def main():
    # Load environment variables from .env file
    load_dotenv()

    api_key = os.environ.get("NEARAI_API_KEY")
    if not api_key:
        print("ERROR: NEARAI_API_KEY not set in environment")
        print("Get your API key from https://cloud.near.ai")
        print("Create a .env file with: NEARAI_API_KEY=sk-your-key-here")
        sys.exit(1)

    print("=" * 60)
    print("BidVeil Phase 1: NEAR AI Cloud TEE Smoke Test")
    print("=" * 60)
    print(f"Python: {sys.version.split()[0]}")
    print(f"Model: z-ai/glm-5.3-flash (NEAR TEE model with E2EE)")
    print(f"Endpoint: https://cloud-api.near.ai/v1")
    print()

    try:
        async with InferenceClient(api_key, e2ee=True) as client:
            print("1. Preflight: Gateway attestation verification...")
            print("   (SDK verifies Gateway TDX quote + TLS binding automatically)")
            print()

            print("2. Preflight: Model attestation verification...")
            print("   (SDK verifies NEAR model TDX quote + nonce binding automatically)")
            print()

            print("3. Sending inference request...")
            completion = await client.chat.completions.create(
                model="z-ai/glm-5.3-flash",
                messages=[{"role": "user", "content": "Reply with: TEE test successful"}],
            )

            model_response = completion.choices[0].message.content or ""
            print(f"   Model response: {model_response}")
            print()

            print("4. Verifying response signature...")
            verified = await client.verify_response(completion.id)

            signature_kind = verified.signature_kind
            print(f"   Response signature kind: {signature_kind}")
            print()

            # Interpret the verification result
            if signature_kind == "provider_tee":
                print("   ✓ PROVIDER_TEE: Model TEE signed the exact request/response bytes")
                print("   ✓ This proves the model executed inside a verified TEE")
                model_tee_verified = True
            elif signature_kind == "gateway":
                print("   ⚠ GATEWAY: Only Gateway signed the request/response bytes")
                print("   ⚠ This does NOT prove model TEE execution")
                model_tee_verified = False
            else:
                print(f"   ? UNKNOWN signature kind: {signature_kind}")
                model_tee_verified = False

            print()
            print("=" * 60)
            print("VERIFICATION SUMMARY")
            print("=" * 60)
            print(f"Gateway attestation:  PASSED (SDK preflight)")
            print(f"Model TEE attestation:  {'PASSED' if model_tee_verified else 'NOT PROVEN'}")
            print(f"Response signature:     {signature_kind}")
            print(f"Completion ID:          {completion.id}")
            print()
            print(f"attestation verified: {str(model_tee_verified).lower()}")
            print()
            if model_tee_verified:
                print("MEANING: The response was signed by the attested model TEE.")
                print("         The model executed inside a verified Intel TDX environment.")
            else:
                print("MEANING: The response was only signed by the Gateway.")
                print("         Model TEE execution is NOT cryptographically proven.")

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())