from nsepython import option_chain
import json

def test():
    try:
        data = option_chain("NIFTY")
        print(data.keys())
        if 'records' in data:
            print("SUCCESS! Underlying:", data['records']['underlyingValue'])
        else:
            print("Valid, but no records key:", data)
    except Exception as e:
        print("Exception:", e)

test()
