
with open("whatsapp_service.py", "r", encoding="utf-8") as f:
    content = f.read()

target = "LANGUAGE REQUIREMENT (CRITICAL - ENGLISH)"
if target in content:
    # Find the else block containing English requirement
    idx = content.find(target)
    # Go back to find "else:"
    else_idx = content.rfind("else:", 0, idx)
    if else_idx != -1:
        # Replace from else: to the end of that return statement
        end_idx = content.find(")", idx)
        if end_idx != -1:
            old_section = content[else_idx:end_idx+1]
            new_section = """else:
        return (
            "LANGUAGE REQUIREMENT (CRITICAL - ROMAN URDU):\\n"
            f"- The customer messaged in an unspecified language (defaulting to Roman Urdu): \x27{clean_text}\x27.\\n"
            "- You MUST formulate your entire reply in natural, conversational Roman Urdu (Latin script Urdu).\\n"
            "- Do NOT answer in English by default.\\n"
            "- Use natural Roman Urdu phrasing (e.g., \x27Salam! OpsFlow Cloud mein khush-amdeed, main aapki kya madad kar sakta hoon?\x27).\\n"
            "- Preserve proprietary brand names such as \x27OpsFlow Cloud\x27 as-is."
        )"""
            content = content.replace(old_section, new_section)
            with open("whatsapp_service.py", "w", encoding="utf-8") as f:
                f.write(content)
            print("SUCCESS: Default fallback successfully updated to Roman Urdu!")
        else:
            print("ERROR: Could not find end of return statement.")
    else:
        print("ERROR: Could not find else block.")
else:
    print("ERROR: English requirement target not found.")

