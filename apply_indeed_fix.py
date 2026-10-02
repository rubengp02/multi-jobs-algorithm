import os

def fix_indeed():
    with open('fix_indeed_manually.py', 'r', encoding='utf-8') as f:
        good_top = f.read()
    
    with open('providers/indeed.py', 'r', encoding='utf-8') as f:
        code = f.read()

    # Find the start of def _count_result_nodes
    idx = code.find('    async def _count_result_nodes')
    if idx == -1:
        idx = code.find('    def _count_result_nodes')
        
    bottom = code[idx:]
    
    with open('providers/indeed.py', 'w', encoding='utf-8') as f:
        f.write(good_top + '\n' + bottom)

if __name__ == '__main__':
    fix_indeed()
