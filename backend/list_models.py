import google.generativeai as genai
genai.configure(api_key="AIzaSyD-O2eEgokFLV-XZmcmH7-hBmsLRdfWOXE")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)
