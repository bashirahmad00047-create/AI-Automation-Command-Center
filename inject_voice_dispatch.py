
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

# Locate send message section inside handle_inbound_auto_response
target_str = "res = cls.send_green_api_message(sender_phone, reply_text, organization_id=organization_id)"

replacement_str = """# Voice note response handling: If inbound was a voice note, convert reply to audio and send file
        if is_voice and reply_text:
            try:
                audio_path = cls.generate_spoken_audio(reply_text)
                if audio_path and os.path.exists(audio_path):
                    res = cls.send_green_api_file(sender_phone, audio_path, caption=reply_text, organization_id=organization_id)
                else:
                    res = cls.send_green_api_message(sender_phone, reply_text, organization_id=organization_id)
            except Exception as voice_err:
                res = cls.send_green_api_message(sender_phone, reply_text, organization_id=organization_id)
        else:
            res = cls.send_green_api_message(sender_phone, reply_text, organization_id=organization_id)"""

if target_str in content:
    content = content.replace(target_str, replacement_str)
    with open("whatsapp_service.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("SUCCESS: Voice note response dispatch logic injected successfully!")
else:
    print("WARNING: Exact target line not matched. Searching pattern...")
    import re
    # Fallback replace for send_green_api_message call inside handle_inbound_auto_response
    pattern = r"res\s*=\s*cls\.send_green_api_message\(sender_phone,\s*reply_text,\s*organization_id=organization_id\)"
    if re.search(pattern, content):
        content = re.sub(pattern, replacement_str, content, count=1)
        with open("whatsapp_service.py", "w", encoding="utf-8") as f:
            f.write(content)
        print("SUCCESS: Voice dispatch added via regex pattern replacement!")
    else:
        print("ERROR: Could not find target send_green_api_message call.")

