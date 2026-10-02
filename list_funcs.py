import ast

with open('main.py', 'r', encoding='utf-8') as f:
    source = f.read()

parsed = ast.parse(source)

for node in parsed.body:
    if isinstance(node, ast.FunctionDef):
        print(f"{node.name}:{node.lineno}-{node.end_lineno}")
    elif isinstance(node, ast.ClassDef):
        print(f"Class {node.name}:{node.lineno}-{node.end_lineno}")
