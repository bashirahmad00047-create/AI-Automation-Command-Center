"""Real Live Integration Test for Gemini AI and Voice-to-Voice Pipeline.
STRICT NO-MOCK ENFORCEMENT: Tests live network calls against Google Gemini and Speech synthesis.
"""
import os
import sys
import base64
import asyncio

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from whatsapp_service import WhatsAppService

def test_live_text_and_voice():
    print("=" * 70)
    print("RUNNING MANDATORY LIVE INTEGRATION PROOF (NO MOCKS ALLOWED)")
    print("=" * 70)

    # -------------------------------------------------------------
    # TEST A: LIVE TEXT QUERY VIA GEMINI
    # -------------------------------------------------------------
    query_text = "Pakistan ka dar-ul-hukoomat kya hai aur wahan ka mausam kaisa hota hai?"
    print(f"\n[Test A] Sending live text prompt to Gemini LLM:\n>> '{query_text}'")

    res_a = WhatsAppService.generate_ai_auto_response(
        organization_id=None,
        message_body=query_text,
        sender_name="Ahmed Khan"
    )
    reply_a = res_a.get("reply_body", "")
    print(f"\n[Test A Result] Live Gemini Response ({len(reply_a)} chars):")
    print(f">> {reply_a}")

    assert reply_a, "Test A FAILED: No reply returned from Gemini"
    assert "Aap ke sawal ke hawalay se" not in reply_a, "Test A FAILED: Returned banned fallback string!"
    assert any(w in reply_a.lower() for w in ("islamabad", "dar-ul-hukoomat", "darul hukoomat", "mausam", "shehar")), \
        "Test A FAILED: Did not contain genuine answer about Islamabad/weather"
    print(">>> TEST A PASSED: Real Gemini LLM returned authentic conversational answer.")

    # -------------------------------------------------------------
    # TEST B: REAL LIVE VOICE-TO-VOICE (INBOUND AUDIO -> GEMINI MULTIMODAL -> TTS)
    # -------------------------------------------------------------
    spoken_question = "Bhai mujhe laptop lena hai graphic designing ke liye, kaunsa best rahega?"
    print(f"\n[Test B] Synthesizing real input voice note for Gemini Multimodal:\n>> '{spoken_question}'")

    # Synthesize genuine input voice note
    import edge_tts
    async def make_inbound_voice():
        comm = edge_tts.Communicate(spoken_question, "ur-PK-AsadNeural")
        chunks = []
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    inbound_audio_bytes = asyncio.run(make_inbound_voice())
    print(f"[Test B] Inbound audio synthesized: {len(inbound_audio_bytes)} bytes")
    assert len(inbound_audio_bytes) > 1000, "Inbound audio synthesis failed"

    # Send directly to Gemini Multimodal Audio
    print("[Test B] Calling WhatsAppService.call_gemini_multimodal_audio with live audio bytes...")
    mm_result = WhatsAppService.call_gemini_multimodal_audio(
        audio_bytes=inbound_audio_bytes,
        mime_type="audio/mp3",
        organization_id=None,
        customer_name="Graphic Designer User"
    )

    assert mm_result is not None, "Test B FAILED: Gemini Multimodal returned None!"
    transcript, ai_reply_b = mm_result
    print(f"\n[Test B Result] Multimodal Perception Success:")
    print(f"TRANSCRIPT: {transcript}")
    print(f"AI REPLY  : {ai_reply_b}")

    assert transcript, "Test B FAILED: Empty transcript"
    assert ai_reply_b, "Test B FAILED: Empty AI reply"
    assert "Aap ke sawal ke hawalay se" not in ai_reply_b, "Test B FAILED: Returned banned fallback string!"

    # Now convert AI reply text to speech audio (TTS)
    print("\n[Test B] Synthesizing outbound AI speech response using WhatsAppService.generate_spoken_audio...")
    synth_res = WhatsAppService.generate_spoken_audio(
        text=ai_reply_b,
        language="ur",
        organization_id=None,
        output_format="mp3"
    )
    assert synth_res is not None, "Test B FAILED: Outbound TTS returned None"
    out_audio_bytes, out_fn, out_mt = synth_res
    out_audio_b64 = base64.b64encode(out_audio_bytes).decode("ascii")

    print(f"[Test B Result] Outbound Speech Generated:")
    print(f">> Format: {out_fn} ({out_mt})")
    print(f">> Raw bytes: {len(out_audio_bytes)} bytes")
    print(f">> Base64 length: {len(out_audio_b64)} chars (Required > 5000: {len(out_audio_b64) > 5000})")

    assert len(out_audio_b64) > 5000, f"Test B FAILED: Base64 length ({len(out_audio_b64)}) <= 5000"

    print("\n" + "=" * 70)
    print("ALL MANDATORY LIVE INTEGRATION TESTS PASSED WITHOUT MOCKS!")
    print("=" * 70)

if __name__ == "__main__":
    test_live_text_and_voice()
