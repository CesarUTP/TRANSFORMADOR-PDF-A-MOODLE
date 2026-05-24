import sys
sys.path.insert(0, '.')
from formatter import verify_and_format
from parser import parse_answer_key, build_questions

with open("test_exam.txt", "r", encoding="utf-8") as f:
    text = f.read()

result, reformatted = verify_and_format(text)

with open("test_output.txt", "w", encoding="utf-8") as f:
    f.write(f"==== REFORMATTED: {reformatted} ====\n\n")
    f.write("=== GEMINI OUTPUT ===\n")
    f.write(result)
    f.write("\n\n=== ANSWER KEY PARSED ===\n")
    ak = parse_answer_key(result)
    for k, v in ak.items():
        f.write(f"  Q{k}: {v}\n")
    f.write("\n=== QUESTIONS PARSED ===\n")
    qs = build_questions(result, ak)
    for q in qs:
        f.write(f"  Q{q['num']} ({q['type']}): {str(q['data'])[:120]}\n")
