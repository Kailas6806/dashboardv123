import sys
sys.path.append(r'd:\KD\.venv\Lib\site-packages')
from nsepython import option_chain
import json

try:
    data = option_chain("NIFTY")
    with open('d:/KD/nse_test.json', 'w') as f:
        json.dump(data, f)
except Exception as e:
    with open('d:/KD/nse_test.json', 'w') as f:
        f.write(str(e))
