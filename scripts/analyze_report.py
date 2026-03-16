import re, json

with open('/Users/olawaleariyo/Documents/projects/exploration/webqa-plus/reports/report_20260315_154635.html', 'r') as f:
    content = f.read()

# Extract JSON data from the HTML
match = re.search(r'const testData = ({.*?});', content, re.DOTALL)
if match:
    data = json.loads(match.group(1))
    print("=== TEST STEPS ===")
    for step in data.get('steps', []):
        action = step.get('action_plan', {})
        step_num = step.get('step_number')
        atype = action.get('action_type', '?')
        target = action.get('target', '?')
        value = action.get('value', '')
        url = step.get('page_url', '?')[:80]
        selector_used = step.get('selector_used', '')
        result = step.get('result', '')[:60]
        print(f"Step {step_num}: [{atype}] target={target} value={value[:20]} | url={url}")
        if selector_used:
            print(f"         selector={selector_used}")
        if result:
            print(f"         result={result}")
    print("\n=== FLOW SUMMARY ===")
    for k, v in data.items():
        if k != 'steps':
            print(f"{k}: {str(v)[:100]}")
else:
    print("No testData found in report")
    # Try to extract other data
    print(content[:2000])
